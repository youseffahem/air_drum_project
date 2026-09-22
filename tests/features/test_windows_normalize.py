"""TEST-FEATURE-2/3: fold leakage, target semantics, exact history alignment and safety."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from spacedrums.features.batch import build_features
from spacedrums.features.normalize import FeatureTable, NormStats, fit_norm
from spacedrums.features.streaming import StreamingFeatures
from spacedrums.features.targets import auxiliary_target
from spacedrums.features.windows import WindowParams, build_windows, write_samples


def make_tables(schema, factory):
    tables = []
    for j, participant in enumerate(("SYNTHETIC-A", "SYNTHETIC-B", "SYNTHETIC-C")):
        tracks = [factory(i, tip_filtered=(0.2 + j, 0.3 + i * 0.01)) for i in range(20)]
        tables.append(
            FeatureTable(
                participant,
                f"synthetic-{j}",
                "SYNTHETIC",
                build_features(tracks, schema),
                [True] * len(tracks),
            )
        )
    fold = {
        "fold": 0,
        "train_participants": ["SYNTHETIC-A"],
        "val_participants": ["SYNTHETIC-B"],
        "train_sessions": ["synthetic-0"],
        "val_sessions": ["synthetic-1"],
    }
    return tables, fold


def fit(tables, schema, fold):
    return fit_norm(
        tables,
        schema,
        fold,
        ["SYNTHETIC-C"],
        dataset_version="ds-v0.0-selftest-features",
        dataset_hash="sha256:" + "1" * 64,
        split_hash="sha256:" + "2" * 64,
    )


def test_train_only_stats_unchanged_by_val_test_and_differ_across_folds(schema, track_factory):
    tables, fold = make_tables(schema, track_factory)
    baseline = fit(tables, schema, fold)
    changed = deepcopy(tables)
    for table in changed[1:]:
        table.records = [replace(r, values=tuple(v * 10000 for v in r.values)) for r in table.records]
    assert fit(changed, schema, fold).data == baseline.data
    swapped = {
        **fold,
        "fold": 1,
        "train_participants": fold["val_participants"],
        "val_participants": fold["train_participants"],
        "train_sessions": fold["val_sessions"],
        "val_sessions": fold["train_sessions"],
    }
    assert fit(tables, schema, swapped).data["center"] != baseline.data["center"]
    assert baseline.data["train_participants"] == ["SYNTHETIC-A"]


@pytest.mark.parametrize("bad", ["overlap", "session", "missing", "duplicate", "kind", "empty"])
def test_leakage_and_provenance_refusals(schema, track_factory, bad):
    tables, fold = make_tables(schema, track_factory)
    if bad == "overlap":
        fold["train_participants"].append("SYNTHETIC-C")
    elif bad == "session":
        fold["train_sessions"] = ["synthetic-1"]
    elif bad == "missing":
        tables.pop()
    elif bad == "duplicate":
        tables.append(tables[0])
    elif bad == "kind":
        tables[1].source_kind = "DEV_CAPTURE"
    elif bad == "empty":
        tables[0].eligible = [False] * 20
    with pytest.raises(ValueError):
        fit(tables, schema, fold)


def test_normalization_sentinels_angles_zero_spread_and_provenance(schema, track_factory, tmp_path):
    tables, fold = make_tables(schema, track_factory)
    stats = fit(tables, schema, fold)
    rows = tables[0].records
    x, m = np.array([r.values for r in rows]), np.array([r.mask for r in rows])
    normalized, mask = stats.apply(x, m, schema)
    assert np.isfinite(normalized).all() and np.all(normalized[~mask] == 0)
    assert np.array_equal(normalized[:, schema.index["axis_sin"]], x[:, schema.index["axis_sin"]])
    assert stats.data["scale"][schema.index["tip_x"]] == 1
    assert not stats.data["usable"][schema.index["stick_length"]]
    path = tmp_path / "stats.json"
    stats.write(path)
    kwargs = dict(
        fold=0,
        dataset_version=stats.data["dataset_version"],
        split_hash=stats.data["split_hash"],
        dataset_hash=stats.data["dataset_hash"],
        schema=schema,
    )
    assert NormStats.read(path, **kwargs).data == stats.data
    with pytest.raises(ValueError, match="provenance"):
        NormStats.read(path, **{**kwargs, "fold": 1})
    changed_schema = deepcopy(schema)
    changed_schema.fingerprint = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="mismatch"):
        stats.apply(x, m, changed_schema)


def sample_inputs(schema, factory):
    tracks = [factory(i, t_capture=100.0 + i * 0.05) for i in range(20)]
    features = build_features(tracks, schema)
    labels = [
        {
            "session_id": "synthetic-session",
            "segment_id": "s1",
            "segment_take": 1,
            "hand_id": "RIGHT",
            "label_class": "POSITIVE",
            "t_impact_est": 100.4,
            "t_event": 100.4,
            "excluded": False,
            "zone_id": "snare",
            "impact_position": [0.4, 0.58],
            "intensity_proxy_gt": 0.7,
        }
    ]
    segments = [{"segment_id": "s1", "take": 1, "t_start": 100.0, "t_end": 101.0, "eligible": True}]
    return tracks, features, labels, segments


def windows(inputs, schema, params=None, **kwargs):
    params = params or WindowParams(4, 3, 0.15, 0.3)
    return build_windows(
        *inputs,
        schema,
        params,
        participant="SYNTHETIC",
        session_id="synthetic-session",
        source_kind="SYNTHETIC",
        **kwargs,
    )


def test_window_alignment_trajectory_displacement_time_offsets_and_streaming(schema, track_factory, tmp_path):
    inputs = sample_inputs(schema, track_factory)
    samples, report = windows(inputs, schema)
    s = samples[0]
    assert s["X"].shape == (4, schema.dimension) and s["T"].shape == (3, 2)
    np.testing.assert_allclose(
        s["T"], np.array([t.tip_filtered for t in inputs[0][4:7]]) - inputs[0][3].tip_filtered
    )
    np.testing.assert_allclose(s["target_offsets_s"], [0.05, 0.1, 0.15])
    np.testing.assert_allclose(s["X"][:, schema.index["window_elapsed"]], [0.0, 0.05, 0.1, 0.15])
    stream = StreamingFeatures(schema, history_n=4)
    for t in inputs[0][:4]:
        stream.update(t)
    x, m = stream.window("RIGHT")
    assert np.array_equal(s["X"], x) and np.array_equal(s["M"], m)
    assert report["total_windows"] == 17
    assert report["class_counts"]["POSITIVE"] > 0
    write_samples(tmp_path / "samples.npz", samples, schema, WindowParams(4, 3, 0.15, 0.3))
    with np.load(tmp_path / "samples.npz", allow_pickle=False) as data:
        assert data["X"].shape == (17, 4, schema.dimension)
        assert data["aux"].dtype.kind == "U"


def test_window_no_future_input_and_labels_cannot_change_x(schema, track_factory):
    inputs = sample_inputs(schema, track_factory)
    base, _ = windows(inputs, schema)
    changed = deepcopy(inputs)
    changed[2][0]["t_impact_est"] = 100.7
    got, _ = windows(changed, schema)
    assert all(np.array_equal(a["X"], b["X"]) for a, b in zip(base, got, strict=True))
    tracks = inputs[0][:8] + [replace(t, tip_filtered=(90.0, 90.0)) for t in inputs[0][8:]]
    got, _ = windows((tracks, build_features(tracks, schema), *inputs[2:]), schema)
    for a, b in zip(base[:5], got[:5], strict=True):
        assert np.array_equal(a["X"], b["X"])
    assert not np.array_equal(base[4]["T"], got[4]["T"])


def test_auxiliary_horizon_open_left_closed_right_hand_and_tail_masks():
    label = {
        "session_id": "synthetic",
        "segment_id": "s",
        "segment_take": 1,
        "hand_id": "RIGHT",
        "label_class": "POSITIVE",
        "t_impact_est": 10.5,
        "zone_id": "snare",
        "impact_position": [0.4, 0.5],
        "intensity_proxy_gt": 0.9,
    }
    kw = dict(
        t=10.0,
        hand_id="RIGHT",
        session_id="synthetic",
        segment_id="s",
        segment_take=1,
        end=11.0,
        h=0.5,
        h_max=1.0,
    )
    a = auxiliary_target([label], **kw)
    assert a["strike_within_H"] == 1 and a["tti"] == 0.5 and a["impact_mask"]
    assert auxiliary_target([label], **{**kw, "t": 10.5})["strike_within_H"] == 0
    assert not auxiliary_target([label], **{**kw, "hand_id": "LEFT"})["tti_mask"]
    assert not auxiliary_target([], **{**kw, "end": 10.1})["strike_mask"]
    assert not auxiliary_target([], **kw)["tti_mask"]
    assert not auxiliary_target([{**label, "qc_status": "REJECTED"}], **kw)["tti_mask"]


@pytest.mark.parametrize("problem", ["gap", "quarantine", "boundary", "ambiguous"])
def test_bad_windows_retained_for_safety_not_anticipation(schema, track_factory, problem):
    tracks, rows, labels, segments = sample_inputs(schema, track_factory)
    if problem == "gap":
        tracks[3] = track_factory(3, t_capture=100.15, status="INVALID")
        rows = build_features(tracks, schema)
    elif problem == "quarantine":
        segments[0]["eligible"] = False
    elif problem == "boundary":
        segments = [{**segments[0], "t_end": 100.1}, {**segments[0], "segment_id": "s2", "t_start": 100.1}]
    else:
        labels[0]["label_class"] = "AMBIGUOUS"
    samples, counts = windows((tracks, rows, labels, segments), schema)
    assert counts["safety_only_windows"] > 0
    assert not samples[0]["anticipation_eligible"]
    if problem == "gap":
        assert not samples[0]["M"][-1].any()
    if problem == "quarantine":
        assert not samples[0]["T_mask"].any() and not samples[0]["aux"]["strike_mask"]


def test_future_tracking_loss_masks_reacquisition_targets(schema, track_factory):
    tracks, _, labels, segments = sample_inputs(schema, track_factory)
    tracks[5] = track_factory(5, t_capture=100.25, status="INVALID")
    samples, _ = windows((tracks, build_features(tracks, schema), labels, segments), schema)
    assert samples[0]["T_mask"].tolist() == [True, False, False]


@pytest.mark.parametrize(
    "params", [(0, 1, 0.1, 0.2), (1, 0, 0.1, 0.2), (1, 1, 0.3, 0.2), (1, 1, float("nan"), 0.2)]
)
def test_invalid_window_parameters(params):
    with pytest.raises(ValueError):
        WindowParams(*params)
