"""REQ-306 preparation tests. All generated identities and metrics are SYNTHETIC/DEV."""

import copy
import sys
from pathlib import Path

import numpy as np
import pytest
import torch
from jsonschema import ValidationError

from spacedrums.ablation.config import model_config, read_plan, validate_plan
from spacedrums.ablation.guards import (
    DependencyError,
    FrozenFiles,
    dependency_errors,
    refuse_experimental_execution,
    session_scope,
)
from spacedrums.ablation.statistics import compare, seed_band
from spacedrums.ablation.transforms import (
    MASK_GROUPS,
    MaskedAdapter,
    mask_normalized,
    mask_spec,
    model_variant,
    reusable_horizon,
)
from spacedrums.config import load_config
from spacedrums.features.schema import FeatureSchema
from spacedrums.live_eval.prereg import file_digest
from spacedrums.models.temporal.config import build_mt_model
from spacedrums.models.temporal.consistency import AuxHeadSettings

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def plan():
    return read_plan(ROOT / "configs/ablations/synthetic-dev.yaml")


@pytest.fixture
def cfg():
    return load_config(ROOT / "configs/prototype.candidate.yaml").data


@pytest.fixture
def schema(cfg):
    return FeatureSchema(cfg["zones"])


@pytest.mark.parametrize("aid", MASK_GROUPS)
def test_mask_exact_zero_flag_and_full_dimension(schema, aid):
    spec = mask_spec(schema, aid)
    values = np.arange(3 * schema.dimension, dtype=float).reshape(3, -1) + 1
    masks = np.ones_like(values, dtype=bool)
    x, m = mask_normalized(values, masks, spec)
    assert spec["indices"] and x.shape == values.shape
    assert np.all(x[:, spec["indices"]] == 0) and not m[:, spec["indices"]].any()
    kept = sorted(set(range(schema.dimension)) - set(spec["indices"]))
    np.testing.assert_array_equal(x[:, kept], values[:, kept])
    np.testing.assert_array_equal(values, np.arange(values.size).reshape(values.shape) + 1)
    if aid == "AB-VEL":
        assert all(name in spec["names"] for name in schema.names if name.startswith("tts_"))
    if aid == "AB-ZONE":
        assert all(
            name in spec["names"] for name in schema.names if name.startswith(("relative_", "inward_"))
        )

    class Echo:
        def __call__(self, track, history, window):
            return window

        def reset(self, reason=None):
            pass

    adapter = MaskedAdapter(Echo(), schema, spec)
    for a, b in zip(adapter(None, (), (values, masks)), (x, m), strict=True):
        np.testing.assert_array_equal(a, b)
    assert adapter(None, (), None) is None


@pytest.mark.parametrize("family", ["gru", "tcn"])
@pytest.mark.parametrize("aid", [*MASK_GROUPS, "AB-HIST-S", "AB-HOR-L", "AB-NOTRAJ", "AB-AUX", "AB-INT"])
def test_variant_causal_1_and_2_all_heads(plan, schema, family, aid):
    """Future mutation and declared-window truncation through each new input/head path."""
    plan["reference"]["model"]["base"]["family"] = family
    variant = next(v for v in plan["variants"] if v["ablation_id"] == aid)
    cfg, gate = model_variant(model_config(plan), variant, AuxHeadSettings(**plan["reference"]["gate"]))
    torch.manual_seed(19)
    model = build_mt_model(cfg).eval()
    rng = np.random.default_rng(19)
    x = rng.normal(size=(2, 23, schema.dimension)).astype("float32")
    m = np.ones_like(x, dtype=bool)
    if aid in MASK_GROUPS:
        x, m = mask_normalized(x, m, mask_spec(schema, aid))
    changed = x.copy()
    changed[:, 17:] += 100

    def run(v, mask):
        with torch.no_grad():
            return model(torch.from_numpy(v), torch.from_numpy(mask))

    a, b, c = (
        run(x[:, :17], m[:, :17]),
        run(changed[:, :17], m[:, :17]),
        run(x[:, 17 - cfg.base.n : 17], m[:, 17 - cfg.base.n : 17]),
    )
    for aa, bb, cc in zip(a, b, c, strict=True):
        torch.testing.assert_close(aa, bb, rtol=0, atol=0)
        torch.testing.assert_close(aa, cc, rtol=0, atol=0)
    if aid == "AB-NOTRAJ":
        assert not cfg.live_eligible and "trajectory" not in cfg.heads
    if aid == "AB-AUX":
        assert "strike" not in cfg.heads and not gate.use_p_aux
    if aid == "AB-INT":
        assert "intensity" not in cfg.heads and gate.intensity_source == "geometry"


def test_schema_rejects_multifactor_unknown_and_wrong_direction(plan):
    for variant in [
        dict(ablation_id="AB-VEL", changes={"n": 4}),
        dict(ablation_id="AB-HIST-S", changes={"n": 12}),
        dict(ablation_id="AB-FPS", changes={"source_fps": 30, "target_fps": 60}),
    ]:
        bad = copy.deepcopy(plan)
        bad["variants"] = [variant]
        with pytest.raises((ValueError, ValidationError)):
            validate_plan(bad)
    plan["reference"]["training"]["unknown"] = 1
    with pytest.raises(TypeError):
        validate_plan(plan)


def test_pairing_seed_variance_and_missing_support():
    rows = [
        dict(participant=f"SYNTHETIC-{p}", fold=0, seed=s, value=p + 0.01 * s)
        for p in range(5)
        for s in (1, 2, 3)
    ]
    band = seed_band(rows)
    assert band == pytest.approx(0.02)
    shifted = [{**r, "value": r["value"] + 0.1} for r in rows]
    result = compare(rows, shifted, band=band)
    assert result["n"] == 5 and result["estimate"] == pytest.approx(0.1)
    assert result["interpretation"] == "MATERIAL"
    assert compare(rows, rows, band=band)["interpretation"] == "NO_MATERIAL_EFFECT"
    assert compare(list(reversed(rows)), shifted, band=band) == result
    with pytest.raises(ValueError):
        compare(rows, shifted[:-1], band=band)
    with pytest.raises(ValueError):
        compare(rows + [rows[0]], shifted, band=band)
    shifted[0]["value"] = None
    missing = compare(rows, shifted, band=band)
    assert missing["n"] == 4 and missing["excluded_incomplete_participants"] == ["SYNTHETIC-0"]
    assert seed_band([{**r, "value": None} for r in rows]) is None


def test_fail_closed_no_frozen_reference_or_synthetic_substitution(tmp_path):
    assert len(dependency_errors(None, tmp_path)) > 15
    errors = dependency_errors({"evidence": "SYNTHETIC/DEV", "dataset_version": "ds-v0.0-selftest"}, tmp_path)
    assert any("real PARTICIPANT" in e for e in errors)
    with pytest.raises(DependencyError, match="PREPARATION ONLY"):
        refuse_experimental_execution()
    from run_ablations import main

    with pytest.raises(SystemExit) as e:
        main(["--execute", "--reference", str(tmp_path / "unopened.json")])
    assert e.value.code == 2


def test_allowlist_hash_and_traversal(tmp_path):
    p = tmp_path / "synthetic.json"
    p.write_text('{"evidence":"SYNTHETIC/DEV"}')
    files = FrozenFiles(tmp_path, {p.name: file_digest(p)})
    assert files.json(p.name)["evidence"] == "SYNTHETIC/DEV"
    for bad in ("../synthetic.json", str(p), "undeclared.json"):
        with pytest.raises(DependencyError):
            files.path(bad)
    p.write_text("{}")
    with pytest.raises(DependencyError, match="hash mismatch"):
        files.path(p.name)


def test_session_identity_rejected_before_any_stream_is_opened(tmp_path, monkeypatch):
    import json

    from spacedrums.data import feature_dataset

    def forbidden(*args, **kwargs):
        raise AssertionError("mismatched participant streams must not be opened")

    monkeypatch.setattr(feature_dataset, "load_session", forbidden)
    directory = tmp_path / "synthetic-guard-fixture"
    directory.mkdir()
    metadata = directory / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "evidence": "SYNTHETIC/DEV failure fixture",
                "session_kind": "PARTICIPANT",
                "participant_id": "SYNTHETIC-RESERVED",
                "session_id": "s",
            }
        )
    )
    files = FrozenFiles(tmp_path, {"synthetic-guard-fixture/metadata.json": file_digest(metadata)})
    with pytest.raises(DependencyError, match="streams were not opened"):
        files.session(
            {
                "participant_id": "SYNTHETIC-CV",
                "session_id": "s",
                "directory": "synthetic-guard-fixture",
                "label_directory": "unopened",
            }
        )


def test_cv_scope_rejects_test_identity_session_and_extra_file(tmp_path):
    cv = dict(
        test_participants=["SYNTHETIC-TEST"],
        sessions_by_participant={"SYNTHETIC-TRAIN": ["s1"], "SYNTHETIC-VAL": ["s2"]},
        folds=[
            dict(
                fold=0,
                train_participants=["SYNTHETIC-TRAIN"],
                val_participants=["SYNTHETIC-VAL"],
                train_sessions=["s1"],
                val_sessions=["s2"],
            )
        ],
    )
    sessions = [
        dict(participant_id="SYNTHETIC-TRAIN", session_id="s1"),
        dict(participant_id="SYNTHETIC-VAL", session_id="s2"),
    ]
    assert session_scope(cv, sessions, fold=0, partition="val") == sessions[1:]
    with pytest.raises(DependencyError):
        session_scope(cv, sessions, fold=0, partition="test")
    with pytest.raises(DependencyError):
        session_scope(cv, sessions + sessions[:1], fold=0, partition="train")
    cv["folds"][0]["val_participants"] = ["SYNTHETIC-TEST"]
    with pytest.raises(DependencyError):
        session_scope(cv, sessions, fold=0, partition="val")
    (tmp_path / "extra.txt").write_text("SYNTHETIC/DEV")
    with pytest.raises(DependencyError):
        FrozenFiles(tmp_path, {}).check_tree(".")


def test_horizon_reuse_needs_complete_identical_binding():
    keys = (
        "dataset labels split norm features model_config training seed fold harness "
        "w_s delay operating_rule budget sources"
    ).split()
    binding = {key: "SYNTHETIC/DEV" for key in keys}
    assert reusable_horizon(binding, binding)
    for key in keys:
        assert not reusable_horizon(binding, {**binding, key: "changed"})
    assert not reusable_horizon({}, {})


def test_synthetic_train_replay_report_determinism(plan, cfg, tmp_path):
    from _p11_fixture import kinematic_fixture
    from _p19 import export_cv, run_synthetic

    from spacedrums.ablation.report import render
    from spacedrums.features.windows import WindowParams

    plan["variants"] = [v for v in plan["variants"] if v["ablation_id"] in ("AB-VEL", "AB-NOTRAJ", "AB-AUX")]
    plan["seeds"] = [19]
    plan["reference"]["training"]["epochs"] = 1
    a = run_synthetic(plan, cfg, tmp_path / "first", {})
    b = run_synthetic(plan, cfg, tmp_path / "second", {})
    assert a == b and a["experimental_execution"] is False
    assert all(c["evidence"] == "SYNTHETIC/DEV" and c["causality"]["passed"] for c in a["cells"])
    assert all(c["metrics"] for c in a["cells"])
    assert not list(tmp_path.rglob("samples.test.npz"))
    report = render(a, tmp_path / "report")
    assert report["evidence"] == "SYNTHETIC/DEV"
    with pytest.raises(ValueError):
        render({**a, "evidence": "PARTICIPANT"}, tmp_path / "refused")
    manifest, cv, sessions = kinematic_fixture(cfg, **plan["fixture"])
    with pytest.raises(ValueError, match="test session"):
        export_cv(
            manifest,
            cv,
            sessions,
            cv["folds"][0],
            WindowParams(8, 4, 0.13333333333333333, 0.3, 1, 0),
            tmp_path / "leak",
        )
