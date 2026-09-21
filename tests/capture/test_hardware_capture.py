"""TEST-CAPTURE-5 (integration, hardware): capture runs for N seconds on the real webcam.

Opt-in: ``SPACEDRUMS_HW_TESTS=1`` (needs the HW-01 webcam free). Checks: no exceptions,
FrameSample fields populated and schema-valid, dropped_since_last sums to total drops,
t_capture monotone and <= t_frame_available, ROI view is a slice.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from spacedrums import timing
from spacedrums.capture import CaptureSettings, LiveFrameSource, OpenCvCamera
from spacedrums.config import load_config
from spacedrums.contracts import schema as contract_schema

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "configs" / "example.candidate.yaml"
CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"

pytestmark = pytest.mark.hardware

if os.environ.get("SPACEDRUMS_HW_TESTS") != "1":
    pytest.skip("set SPACEDRUMS_HW_TESTS=1 to run against the webcam", allow_module_level=True)


@pytest.mark.parametrize("backend", ["DSHOW", "MSMF"])
def test_capture_runs_without_exceptions(backend):
    cfg = load_config(BASE, CAMERA, overrides={"camera_profile": {
        "device": {"backend": backend},
        "timestamp_source": "DRIVER_MAPPED" if backend == "MSMF" else "GRAB_RETURN"}})
    settings = CaptureSettings.from_config(cfg.data)
    src = LiveFrameSource(OpenCvCamera(), settings)
    frames = []
    with src:
        t_end = timing.now() + 4.0
        while timing.now() < t_end:
            f = src.next_frame(timeout=0.5)
            if f is not None:
                frames.append(f)
                v = src.view(f)
                assert v.roi.shape == (440, 560, 3) and np.shares_memory(v.roi, v.full)
        st = src.stats()
    assert len(frames) > 30, "camera delivered almost nothing"
    assert all(contract_schema.is_valid("frame-sample", f.to_dict()) for f in frames)
    assert [f.frame_id for f in frames] == list(range(len(frames)))
    assert all(b.t_capture >= a.t_capture for a, b in zip(frames, frames[1:], strict=False))
    assert all(f.t_capture <= f.t_frame_available for f in frames)
    assert sum(f.dropped_since_last for f in frames) == st.dropped
    assert st.clamped_timestamps == 0
    assert all(f.camera_profile_id == "hw01-integrated-webcam-v0" for f in frames)
