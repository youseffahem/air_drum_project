"""TEST-HANDS-3: the real MediaPipe backend behind the wrapper (needs the pinned model file).

Skipped with a visible reason when ``assets/models/hand_landmarker.task`` is absent
(``scripts/fetch_hand_landmarker_model.py`` downloads it once). The dev-capture integration check
is the measurement script (``scripts/hands_landmark_check.py``); here we pin only what must hold on
any machine: the model loads from the manifest with a verified hash, a hand-free image yields two
``present=False`` records without raising, the ``detector_id`` embeds the hash prefix, and the
visibility finding (the estimator provides none) holds for the pinned model.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from spacedrums.capture import Roi, crop_roi
from spacedrums.contracts import FrameSample, FrameView, ImageRef, TimestampSource
from spacedrums.contracts import schema as contract_schema
from spacedrums.hands import HandLandmarker, HandLandmarkerSettings, ModelAssetError, resolve_model_asset

ROOT = Path(__file__).resolve().parents[2]
ASSET_ID = "mediapipe-hand-landmarker-float16-v1"
MODEL = ROOT / "assets" / "models" / "hand_landmarker.task"
DEV_CAPTURE = ROOT / "data" / "dev-captures" / "swing-L2-exp-5"

needs_model = pytest.mark.skipif(not MODEL.exists(),
                                 reason="model file absent; run scripts/fetch_hand_landmarker_model.py once")


def _view(full: np.ndarray, frame_id: int = 0, t: float = 1.0) -> FrameView:
    roi = Roi(40, 20, 560, 440)
    s = FrameSample(frame_id=frame_id, t_capture=t, t_frame_available=t + 0.001,
                    timestamp_source=TimestampSource.REPLAY, frame_size_px=(640, 480),
                    roi_px=roi.as_tuple(), image_ref=ImageRef.memory(full),
                    camera_profile_id="test", dropped_since_last=0)
    return FrameView(sample=s, roi=crop_roi(full, roi), full=full)


@needs_model
def test_model_asset_resolves_with_verified_hash():
    asset = resolve_model_asset(ASSET_ID, verify=True)
    assert asset.path == MODEL and len(asset.sha256) == 64 and asset.bytes == MODEL.stat().st_size


def test_unknown_asset_id_is_refused():
    with pytest.raises(ModelAssetError):
        resolve_model_asset("no-such-model", verify=False)


@needs_model
def test_real_backend_on_a_hand_free_image_emits_two_absent_records():
    rng = np.random.default_rng(0)
    full = rng.integers(0, 40, size=(480, 640, 3), dtype=np.uint8)  # dark noise: no hand
    with HandLandmarker(HandLandmarkerSettings(running_mode="VIDEO")) as lm:
        assert lm.asset is not None and lm.asset.hash_prefix in lm.detector_id
        assert lm.detector_id.startswith("mediapipe-hand-landmarker@")
        res = lm.detect(_view(full, 0, 1.0))
        res2 = lm.detect(_view(full, 1, 1.05))
    for r in (res, res2):
        assert not r.left.present and not r.right.present
        for o in r.observations:
            assert not contract_schema.errors("hand-observation", o.to_dict())
    assert res.processing_s > 0.0


@needs_model
def test_image_mode_runs_without_timestamps():
    full = np.zeros((480, 640, 3), np.uint8)
    with HandLandmarker(HandLandmarkerSettings(running_mode="IMAGE")) as lm:
        res = lm.detect(_view(full))
    assert res.n_detected == 0 and ":image:" in lm.detector_id


@needs_model
@pytest.mark.skipif(not (DEV_CAPTURE / "frames.jsonl").exists(),
                    reason="developer-only dev capture swing-L2-exp-5 not on this machine")
def test_dev_capture_integration_via_script(tmp_path):
    """Task 03.1 integration evidence path: the script completes, N is *reported*, records validate."""
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "hands_landmark_check.py"),
                          "--experiments-dir", str(tmp_path), "--capture", "swing-L2-exp-5", "--limit", "40",
                          "--no-overlay"], cwd=ROOT, capture_output=True, text=True, timeout=600, check=False)
    assert res.returncode == 0, res.stdout[-2000:] + res.stderr[-2000:]
    run_dir = next(p for p in tmp_path.iterdir() if p.is_dir())
    rec = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert not contract_schema.errors("experiment-log", rec)
    m = rec["metrics"]["captures"]["swing-L2-exp-5"]
    assert m["n_frames"] == 40 and isinstance(m["frames_both_present"], int)  # reported, not targeted
    assert m["schema_valid_all"] is True and m["visibility_available"] is False
    assert m["processing_all_frames"]["p50_s"] > 0
    lines = (run_dir / "hand_observations.swing-L2-exp-5.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 80  # two records per frame, always
