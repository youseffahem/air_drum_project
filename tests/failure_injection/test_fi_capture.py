"""TEST-FI-CAP-1..6: capture and timing faults (Phase 17, Task 17.4). SYNTHETIC inputs only.

Frame stalls, drop bursts, timestamp jumps (forward, and non-monotone driver / grab clocks in the
live source), FPS dips: no crash, strictly increasing delivered frames, drop accounting, the
time-gap tracking reset, and the commit guard on missing frames.
"""

from __future__ import annotations

import json

import pytest
from inv_helpers import make_pipeline, run_frames

from spacedrums.app import faults as F
from spacedrums.app.invariants import InvariantMonitor
from spacedrums.app.synthetic import scenario
from spacedrums.capture import CaptureSettings, LiveFrameSource, ReplayFrameSource, Roi, SyntheticCamera
from spacedrums.capture.backend import CameraOpenSpec
from spacedrums.commit import frames_missing
from spacedrums.contracts import (
    HandId,
    HandObservation,
    ResetReason,
    StickObservation,
    TimestampSource,
    TipMethod,
)


def _settings(ts):
    return CaptureSettings(
        camera_profile_id="synthetic-p17",
        spec=CameraOpenSpec(),
        roi=Roi(8, 8, 40, 30),
        timestamp_source=ts,
        nominal_fps=100.0,
        queue_max_frames=4,
        warmup_frames=3,
        mapper_warmup_n=10,
    )


def _absent(sample):
    return {
        h: (
            HandObservation.absent(sample.frame_id, sample.t_capture, h, "none"),
            StickObservation.absent(sample.frame_id, sample.t_capture, h, TipMethod.GEOM),
        )
        for h in (HandId.LEFT, HandId.RIGHT)
    }


@pytest.mark.parametrize(
    "ts,cam_kw,fault_kw",
    [
        (TimestampSource.DRIVER_MAPPED, {"lag_s": 0.05}, {}),  # mapped stamps start below grab stamps
        (TimestampSource.DRIVER_MAPPED, {}, {"driver_shift": {40: -5.0}}),
        (TimestampSource.DRIVER_MAPPED, {}, {"driver_shift": {40: 2.0}}),
        (TimestampSource.GRAB_RETURN, {}, {"grab_shift": {40: -0.05}}),
        (TimestampSource.GRAB_RETURN, {}, {"stall_at": {40: 0.2}}),
        (TimestampSource.GRAB_RETURN, {}, {"disconnect": (40, 20)}),
    ],
)
def test_live_source_survives_timestamp_faults(cfg, registry, ts, cam_kw, fault_kw):
    """TEST-FI-CAP-1: every delivered frame strictly increases; the pipeline never stops."""
    cam = F.FaultyCamera(SyntheticCamera(fps=100.0, n_frames=120, paced=True, **cam_kw), **fault_kw)
    src = LiveFrameSource(cam, _settings(ts))
    pipe = make_pipeline(cfg, registry)
    monitor = InvariantMonitor.for_pipeline(pipe, mode="raise")
    delivered = []
    with src:
        for sample in src:
            monitor.observe(pipe.step(sample, _absent(sample), t_now=sample.t_frame_available), pipe)
            delivered.append(sample)
    assert len(delivered) > 30
    assert all(b.t_capture > a.t_capture for a, b in zip(delivered, delivered[1:], strict=False))
    assert all(s.t_capture <= s.t_frame_available for s in delivered)
    report = src.timestamp_report()
    assert report["refused_non_monotone"] <= src.stats().clamped_timestamps


def test_replay_source_refuses_non_monotone_recording(tmp_path):
    """TEST-FI-CAP-2: a recording whose t_capture does not strictly increase is refused at load."""
    from spacedrums.contracts import FrameSample, ImageRef

    rows = [
        FrameSample(
            frame_id=i,
            t_capture=t,
            t_frame_available=t + 0.004,
            timestamp_source=TimestampSource.GRAB_RETURN,
            frame_size_px=(64, 48),
            roi_px=(0, 0, 64, 48),
            image_ref=ImageRef(kind="FILE", path=f"frames/frame_{i:05d}.png", index=i, crop="FULL"),
            camera_profile_id="synthetic-p17",
            dropped_since_last=0,
        ).to_dict()
        for i, t in enumerate((1.0, 1.033, 1.033, 1.1))
    ]
    (tmp_path / "frames.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="t_capture"):
        ReplayFrameSource(tmp_path)
    (tmp_path / "frames.jsonl").write_text("\n".join(json.dumps(r) for r in rows[:2]), encoding="utf-8")
    assert len(ReplayFrameSource(tmp_path)) == 2


def test_stream_faults_account_for_drops(registry):
    """TEST-FI-CAP-3: drop bursts are reported on the next delivered frame; stalls report none."""
    frames = list(scenario("single", registry))
    dropped, events = F.apply_stream_faults(frames, [F.DropBurst(at=10, frames=4)])
    stalled, _ = F.apply_stream_faults(frames, [F.Stall(at=10, frames=4)])
    assert len(dropped) == len(stalled) == len(frames) - 4
    assert sum(s.dropped_since_last for s, _ in dropped) == 4 and dropped[10][0].dropped_since_last == 4
    assert sum(s.dropped_since_last for s, _ in stalled) == 0
    assert [s.frame_id for s, _ in dropped] == list(range(len(dropped)))
    assert events[0].to_dict()["end_frame"] == 14


@pytest.mark.parametrize("gap_frames,expect_reset", [(2, False), (3, False), (4, True), (9, True)])
def test_time_gap_beyond_g_max_resets_the_tracker(cfg, registry, gap_frames, expect_reset):
    """TEST-FI-CAP-4: a frame interval with more than g_max missing frames resets (GAP_EXCEEDED)."""
    frames = list(scenario("single", registry, t_down=0.5))
    stalled, _ = F.apply_stream_faults(frames, [F.Stall(at=20, frames=gap_frames)])
    pipe = make_pipeline(cfg, registry)
    results = run_frames(pipe, stalled, monitor=InvariantMonitor.for_pipeline(pipe))
    after = results[20].hands[HandId.RIGHT].track
    assert (after.reset_reason is ResetReason.GAP_EXCEEDED) is expect_reset
    assert after.status == "VALID"  # re-acquired from the fresh observation in the same frame


def test_missing_frames_helper_and_commit_guard(cfg, registry):
    """TEST-FI-CAP-5: stalls and queue drops count alike; no commit after more than the guard allows."""
    assert frames_missing(1 / 30, 1 / 30, 0) == 0
    assert frames_missing(0.1, 1 / 30, 0) == 2
    assert frames_missing(1 / 30, 1 / 30, 3) == 3
    assert frames_missing(0.049, 1 / 30, 0) == 0 and frames_missing(0.051, 1 / 30, 0) == 1
    assert frames_missing(0.2, None, 1) == 1
    seq = scenario("single", registry, t_down=0.5)
    frames = list(seq)
    crossing = next(i for i, (s, _) in enumerate(frames) if s.t_capture >= seq.truth[0].t_cross)
    for fault in (F.Stall(at=crossing - 1, frames=2), F.DropBurst(at=crossing - 1, frames=2)):
        faulted, _ = F.apply_stream_faults(frames, [fault])
        # a strict guard (1) blocks the first frame after two missing frames, stall or drop alike ...
        strict = make_pipeline(cfg, registry, overrides={"commit": {"max_dropped_since_last": 1}})
        blocked = run_frames(strict, faulted, monitor=InvariantMonitor.for_pipeline(strict, mode="raise"))
        assert not blocked[crossing - 1].commits, type(fault).__name__
        # ... the chosen candidate guard (3 = g_max_frames, ADR-0040 D4) lets the real strike through
        pipe = make_pipeline(cfg, registry)
        assert pipe.commit_settings.max_dropped_since_last == 3
        results = run_frames(pipe, faulted, monitor=InvariantMonitor.for_pipeline(pipe, mode="raise"))
        assert results[crossing - 1].commits, type(fault).__name__


def test_fps_dip_and_forward_jump_keep_invariants(cfg, registry):
    """TEST-FI-CAP-6: FPS dips and forward clock jumps: no crash, zero invariant violations."""
    frames = list(scenario("alternating_two_zones", registry, t_down=0.2))
    for faults in ([F.FpsChange(at=10, keep_every=2, until=60)], [F.TimestampJump(at=30, delta_s=0.4)]):
        faulted, _ = F.apply_stream_faults(frames, faults)
        pipe = make_pipeline(cfg, registry)
        monitor = InvariantMonitor.for_pipeline(pipe, mode="raise")
        run_frames(pipe, faulted, monitor=monitor)
        assert monitor.finish()["violations_total"] == 0
