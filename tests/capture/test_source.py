"""TEST-CAPTURE-4 / TEST-CONFORM-7 (live source): LiveFrameSource on the synthetic camera.

Checks the FrameSource contract (strictly increasing frame_id, non-decreasing t_capture,
schema-valid records), drop accounting, duplicate refusal, per-frame timestamp labelling,
the ROI view, and the config-driven settings. The hardware integration test is in
test_hardware_capture.py (opt-in).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from spacedrums.capture import CaptureSettings, LiveFrameSource, Roi, SyntheticCamera
from spacedrums.capture.backend import CameraOpenSpec
from spacedrums.config import load_config
from spacedrums.contracts import FrameSample, FrameSource, TimestampSource
from spacedrums.contracts import schema as contract_schema

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "configs" / "example.candidate.yaml"
CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"


def _settings(**kw):
    base = dict(camera_profile_id="synthetic-test", spec=CameraOpenSpec(), roi=Roi(8, 8, 40, 30),
                timestamp_source=TimestampSource.DRIVER_MAPPED, nominal_fps=200.0,
                queue_max_frames=2, warmup_frames=5, mapper_warmup_n=20)
    base.update(kw)
    return CaptureSettings(**base)


def test_frame_source_contract_and_schema():
    cam = SyntheticCamera(fps=300, n_frames=300, paced=False)
    src = LiveFrameSource(cam, _settings())
    assert isinstance(src, FrameSource)
    with src:
        frames = list(src)
    assert frames, "nothing delivered"
    assert all(isinstance(f, FrameSample) for f in frames)
    ids = [f.frame_id for f in frames]
    assert ids == list(range(len(frames)))  # strictly increasing, no id consumed by drops
    assert all(b.t_capture >= a.t_capture for a, b in zip(frames, frames[1:], strict=False))
    assert all(f.t_capture <= f.t_frame_available for f in frames)
    assert all(contract_schema.is_valid("frame-sample", f.to_dict()) for f in frames)
    assert all(f.roi_px == (8, 8, 40, 30) and f.frame_size_px == (64, 48) for f in frames)
    assert src.stats().clamped_timestamps == 0


def test_drop_accounting_sums_to_total_drops():
    cam = SyntheticCamera(fps=1000, n_frames=400, paced=False)
    src = LiveFrameSource(cam, _settings(queue_max_frames=1))
    src.start()
    # let the producer run ahead so the 1-slot queue must drop
    import threading

    threading.Event().wait(0.3)
    frames = list(src)
    st = src.stats()
    src.stop()
    assert st.dropped > 0, "test needs drops to be meaningful"
    assert sum(f.dropped_since_last for f in frames) == st.dropped
    assert st.delivered == len(frames)
    assert st.delivered + st.dropped + st.duplicates == 400 - 5  # raw minus warm-up


def test_duplicates_are_refused_and_counted():
    cam = SyntheticCamera(fps=300, n_frames=300, paced=False, duplicate_every=3)
    src = LiveFrameSource(cam, _settings())
    with src:
        frames = list(src)
    st = src.stats()
    assert st.duplicates > 0
    imgs = [f.image_ref.array for f in frames]
    assert all(not np.array_equal(a, b) for a, b in zip(imgs, imgs[1:], strict=False))
    assert st.delivered + st.duplicates + st.dropped == 300 - 5


def test_dedupe_can_be_disabled_for_diagnostics():
    cam = SyntheticCamera(fps=300, n_frames=100, paced=False, duplicate_every=2)
    src = LiveFrameSource(cam, _settings(dedupe=False))
    with src:
        frames = list(src)
    assert src.stats().duplicates == 0 and len(frames) + src.stats().dropped == 95


def test_timestamp_labels_follow_the_policy():
    # driver stamps on a foreign clock with too little span -> everything GRAB_RETURN until fitted
    cam = SyntheticCamera(fps=300, n_frames=200, paced=False, drv_offset=-777.0)
    src = LiveFrameSource(cam, _settings())
    with src:
        frames = list(src)
    assert {str(f.timestamp_source) for f in frames} == {"GRAB_RETURN"}
    rep = src.timestamp_report()
    assert rep["frames_driver_mapped"] == 0 and rep["driver_timestamps_seen"] is True
    # same clock base -> DRIVER_MAPPED after the mapper warm-up, GRAB_RETURN before
    cam = SyntheticCamera(fps=300, n_frames=200, paced=False)
    src = LiveFrameSource(cam, _settings(queue_max_frames=1000))  # no drops: indices are raw
    with src:
        frames = list(src)
    srcs = [str(f.timestamp_source) for f in frames]
    assert "DRIVER_MAPPED" in srcs and srcs[0] == "GRAB_RETURN"
    assert srcs.index("DRIVER_MAPPED") == 20 - 1  # warm-up of the mapper (20 pairs)
    assert src.stats().dropped == 0
    assert src.timestamp_report()["driver_mapper"]["mode"] == "IDENTITY_SAME_CLOCK"
    # policy GRAB_RETURN never uses driver stamps even when present
    cam = SyntheticCamera(fps=300, n_frames=100, paced=False)
    src = LiveFrameSource(cam, _settings(timestamp_source=TimestampSource.GRAB_RETURN,
                                         grab_return_bias_s=0.001))
    with src:
        frames = list(src)
    assert {str(f.timestamp_source) for f in frames} == {"GRAB_RETURN"}


def test_view_is_a_pure_slice():
    cam = SyntheticCamera(fps=300, n_frames=30, paced=False)
    src = LiveFrameSource(cam, _settings())
    with src:
        f = next(iter(src))
        v = src.view(f)
    assert v.roi.shape == (30, 40, 3)
    assert np.shares_memory(v.roi, v.full)
    assert v.sample is f


def test_roi_must_fit_negotiated_frame():
    cam = SyntheticCamera(fps=300, n_frames=10, paced=False)
    src = LiveFrameSource(cam, _settings(roi=Roi(0, 0, 100, 100)))
    with pytest.raises(ValueError):
        src.start()


def test_exposure_reapplied_after_stream_start():
    cam = SyntheticCamera(fps=300, n_frames=40, paced=False)
    spec = CameraOpenSpec(exposure_mode="MANUAL", exposure_value=-6)
    src = LiveFrameSource(cam, _settings(spec=spec))
    with src:
        list(src)
    assert [c["mode"] for c in cam.exposure_calls] == ["MANUAL", "MANUAL"]
    assert src.exposure_report == {"mode": "MANUAL", "requested_value": -6}


def test_settings_from_config():
    cfg = load_config(BASE, CAMERA)
    s = CaptureSettings.from_config(cfg.data)
    assert s.camera_profile_id == "hw01-integrated-webcam-v0"
    assert s.spec.backend == "DSHOW" and s.spec.width == 640 and s.spec.fps == 30
    assert s.roi == Roi(40, 20, 560, 440)
    assert s.timestamp_source is TimestampSource.GRAB_RETURN
    assert s.grab_return_bias_s == 0.0  # null in the config until measured
    assert s.queue_max_frames == 2 and s.stall_factor == 2.0
