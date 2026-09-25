"""Phase 11 script protocol: held-out refusal, participant-plan refusal, fixture integrity, cache."""

import subprocess
import sys

import numpy as np
import pytest
from _p11 import CachedPredictions
from _p11_fixture import kinematic_fixture

from spacedrums.config import load_config
from spacedrums.geometry import ZoneRegistry


def _run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def test_test_partition_refused_before_any_file_is_opened(tmp_path):
    result = _run(
        "scripts/eval_mt.py",
        "--partition",
        "test",
        "--model-dir",
        str(tmp_path / "absent"),
        "--output",
        str(tmp_path / "out"),
    )
    assert result.returncode != 0 and "PENDING" in result.stderr
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "script,extra",
    [
        ("scripts/sweep_weighting.py", ["--plan", "absent.json"]),
        ("scripts/ablate_heads.py", ["--plan", "absent.json", "--weighting-json", "{}"]),
        ("scripts/ablate_heads.py", ["--synthetic-fixture"]),
        ("scripts/eval_consistency.py", ["--run", "absent"]),
    ],
)
def test_participant_or_underspecified_grids_are_refused_without_a_run_directory(tmp_path, script, extra):
    result = _run(script, *extra, "--output", str(tmp_path / "runs"))
    assert result.returncode != 0
    assert "PENDING" in result.stderr or "weighting" in result.stderr
    assert not (tmp_path / "runs").exists()


def test_kinematic_fixture_is_deterministic_labelled_synthetic_and_geometric():
    cfg = load_config("configs/prototype.candidate.yaml")
    first, cv, sessions = kinematic_fixture(cfg, identities=5, seconds=6)
    again, _, _ = kinematic_fixture(cfg, identities=5, seconds=6)
    assert first["manifest_hash"] == again["manifest_hash"] and first["kind"] == "SELFTEST"
    assert len(cv["test_participants"]) == 1 and cv["folds"]
    registry, v_min = ZoneRegistry.from_config(cfg["zones"]), cfg["geometry"]["v_min"]
    positives = 0
    for session in sessions:
        assert session.table.participant.startswith("SYNTHETIC-") and session.table.source_kind == "SYNTHETIC"
        times = [t.t_capture for t in session.tracks]
        assert times == sorted(times) and {str(t.hand_id) for t in session.tracks} == {"LEFT", "RIGHT"}
        for g in session.labels:
            assert "SYNTHETIC" in g["notes"]
            if g["label_class"] != "POSITIVE":
                continue
            positives += 1
            zone = registry[g["zone_id"]]
            assert times[0] < g["t_impact_est"] < times[-1] and g["intensity_proxy_gt"] >= v_min - 1e-9
            # The labelled point lies on the zone's impact surface (ellipse boundary, rotation included).
            assert zone.shape.implicit(tuple(g["impact_position"])) == pytest.approx(1.0, abs=1e-3)
    assert positives > 10


def test_prediction_cache_refuses_a_changed_window():
    calls = []

    def model(track, history, window):
        calls.append(track)
        return "prediction"

    class Track:
        hand_id, frame_id, t_capture = "LEFT", 3, 10.0

    cached = CachedPredictions(model)
    window = (np.ones((2, 3)), np.ones((2, 3), bool))
    assert cached(Track, (), window) == cached(Track, (), window) == "prediction" and len(calls) == 1
    with pytest.raises(ValueError, match="different causal window"):
        cached(Track, (), (np.zeros((2, 3)), np.ones((2, 3), bool)))


def test_development_weighting_rule_is_mechanical():
    from _p11_grid import choose_weighting

    def entry(variant, family, ade, lead, degrades=False, delta=0.0):
        return {
            "variant": variant,
            "family": family,
            "metrics": {"ade": {"mean": ade}, "dev_lead_s": {"mean": lead}},
            "paired_delta": {"ade": {"degrades_beyond_seed_variance": degrades, "mean": delta}},
        }

    summary = [
        entry("fixed-1.0", "gru", 0.09, 0.010, degrades=True),
        entry("fixed-1.0", "tcn", 0.09, 0.030),
        entry("uncertainty", "gru", 0.08, 0.012),
        entry("uncertainty", "tcn", 0.08, 0.012),
        entry("gradnorm", "gru", 0.07, 0.012),
        entry("gradnorm", "tcn", 0.07, 0.012),
    ]
    assert choose_weighting(summary) == ("gradnorm", "step 2: highest mean development-budget lead")
    summary = [
        entry(v, f, 0.1, None, degrades=True, delta=d)
        for v, d in (("uncertainty", 0.02), ("fixed-0.3", 0.01))
        for f in ("gru", "tcn")
    ]
    assert choose_weighting(summary)[0] == "fixed-0.3"
