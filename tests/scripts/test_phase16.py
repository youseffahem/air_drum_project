"""Negative controls for performance evidence: changed behavior and fake FPS must fail."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def test_regression_rejects_large_epoch_timestamp_shift():
    from regression_check import compare

    with pytest.raises(AssertionError):
        compare({"t_capture": 125000.01}, {"t_capture": 125000.0}, atol=1e-6, rtol=1e-5)


@pytest.mark.parametrize("field,value", [("zone_id", "tom1"), ("hand_id", "RIGHT"), ("t_commit", 5.001)])
def test_commit_change_is_not_hidden_by_prediction_tolerance(field, value):
    from regression_check import compare

    reference = {"zone_id": "snare", "hand_id": "LEFT", "t_commit": 5.0}
    with pytest.raises(AssertionError):
        compare([{**reference, field: value}], [reference])


def test_nonfinite_regression_values_fail():
    from regression_check import compare

    with pytest.raises(AssertionError):
        compare(float("nan"), 0.0, atol=1e-6)


def test_replay_capacity_cannot_claim_native_fps():
    from fps_end_to_end import assess

    with pytest.raises(ValueError, match="live"):
        assess({"source": "replay", "kind": "wall-time profile"}, [], 60)


def test_fallback_cannot_claim_model_60fps():
    from fps_end_to_end import assess

    sample = {
        "rows": [{"active_arm": "B", "fallback": "slow model"}] * 100,
        "delivered_processing_fps": 60.0,
        "capture_drops": 0,
        "application": {"source": {"capture_stats": {"duplicates": 0}}},
        "processing": {"p95_ms": 1.0},
    }
    result = assess({"source": "live", "kind": "wall-time profile"}, [sample], 60)
    assert not result["target_met"] and not result["native_60fps_claim"]


def test_empty_live_profile_cannot_pass():
    from fps_end_to_end import assess

    assert not assess({"source": "live", "kind": "wall-time profile"}, [], 60)["target_met"]


def test_idle_model_cannot_claim_native_60fps():
    from fps_end_to_end import assess

    sample = {
        "rows": [{"active_arm": "C-GRU", "fallback": None, "predictions": 0}] * 100,
        "delivered_processing_fps": 60.0,
        "capture_drops": 0,
        "application": {"source": {"capture_stats": {}}},
        "processing": {"p95_ms": 1.0},
    }
    assert not assess({"source": "live", "kind": "wall-time profile"}, [sample], 60)["target_met"]


@pytest.mark.parametrize("defect", [None, "id", "timestamp", "duplicate"])
def test_fps_requires_unique_native_delivery(defect):
    from fps_end_to_end import assess

    rows = [
        {"frame_id": i, "t_capture": i / 60, "active_arm": "C-GRU", "fallback": None, "predictions": 1}
        for i in range(100)
    ]
    if defect == "id":
        rows[-1]["frame_id"] = rows[0]["frame_id"]
    if defect == "timestamp":
        rows[-1]["t_capture"] = rows[0]["t_capture"]
    sample = {
        "rows": rows,
        "delivered_processing_fps": 60.0,
        "capture_drops": 0,
        "application": {"source": {"capture_stats": {"duplicates": int(defect == "duplicate")}}},
        "processing": {"p95_ms": 1.0},
    }
    result = assess({"source": "live", "kind": "wall-time profile"}, [sample], 60)
    assert result["target_met"] is (defect is None)


def test_regression_rejects_a_different_validation_archive():
    from regression_check import compare_snapshot

    reference = {
        "inputs": {},
        "raw": [],
        "validation": {},
        "harness": [],
        "val_samples_hash": "frozen",
        "synthetic_fold": 0,
        "synthetic_split_hash": "split",
    }
    result = compare_snapshot({**reference, "val_samples_hash": "replacement"}, reference)
    assert not result["passed"]


def test_perception_initialized_before_source_and_closed_on_source_failure(monkeypatch):
    from spacedrums.app import main as app

    calls = []

    class FakePerception:
        def __init__(self, cfg):
            calls.append("perception")

        def close(self):
            calls.append("closed")

    def unavailable(*args):
        calls.append("source")
        raise OSError("unavailable camera")

    monkeypatch.setattr(app, "Perception", FakePerception)
    args = app.build_parser().parse_args(["--no-audio", "--no-window"])
    with pytest.raises(OSError, match="unavailable camera"):
        app.run(args, source_factory=unavailable)
    assert calls == ["perception", "source", "closed"]


def test_candidate_patch_restored_on_failure():
    from _p16 import candidate

    from spacedrums.hands.landmarker import HandLandmarker

    original = HandLandmarker._input_image
    with pytest.raises(RuntimeError), candidate("half-detection"):
        assert HandLandmarker._input_image is not original
        raise RuntimeError("negative control")
    assert HandLandmarker._input_image is original
