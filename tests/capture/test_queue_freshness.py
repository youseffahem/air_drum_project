"""Capture-queue freshness (live responsiveness 2026-10-02): the depth the consumer sees at each
delivery, and the ``max_frames = 1`` setting that always hands over the newest frame.

Depth 1 means the delivered frame was the newest one available; depth >= 2 means a newer frame was
already waiting, so the consumer processed an older frame. Drop accounting and timestamps are the
Task 02.3 / Phase 17 invariants and must not change with the setting. SyntheticCamera only.
"""

from __future__ import annotations

from pathlib import Path

from spacedrums.capture import CaptureSettings, LiveFrameSource
from spacedrums.capture.backend import CameraOpenSpec, SyntheticCamera
from spacedrums.capture.frame_queue import BoundedFrameQueue
from spacedrums.config import load_config
from spacedrums.timing import sleep_s

ROOT = Path(__file__).resolve().parents[2]


def test_depth_at_get_counts_the_delivered_item_and_everything_behind_it():
    q: BoundedFrameQueue[str] = BoundedFrameQueue(2)
    assert q.last_depth_at_get is None
    q.put("a")
    q.put("b")
    assert q.get(0) == ("a", 0) and q.last_depth_at_get == 2  # "b" was newer and waiting: a late delivery
    assert q.get(0) == ("b", 0) and q.last_depth_at_get == 1
    assert q.get(0) is None and q.last_depth_at_get == 1  # a timeout leaves the last delivery's value


def test_a_one_slot_queue_always_delivers_the_newest_frame_and_counts_the_replaced_ones():
    q: BoundedFrameQueue[int] = BoundedFrameQueue(1)
    for i in range(5):
        q.put(i)
    assert q.get(0) == (4, 4) and q.last_depth_at_get == 1
    assert q.dropped == 4 and q.delivered == 1


def _source(max_frames: int, n: int = 60) -> LiveFrameSource:
    settings = CaptureSettings(
        camera_profile_id="synthetic",
        spec=CameraOpenSpec(width=64, height=48, fps=200.0),
        roi=None,
        queue_max_frames=max_frames,
        nominal_fps=200.0,
        warmup_frames=0,
    )
    return LiveFrameSource(SyntheticCamera(width=64, height=48, fps=200.0, n_frames=n), settings)


def _consume_slowly(src: LiveFrameSource) -> list:
    out = []
    with src:
        while True:
            sample = src.next_frame(timeout=0.5)
            if sample is None:
                break
            out.append(sample)
            sleep_s(0.012)  # slower than the 5 ms producer: the queue fills
    return out


def test_queue_report_counts_late_deliveries_with_two_slots():
    src = _source(2)
    samples = _consume_slowly(src)
    report = src.queue_report()
    assert report["max_frames"] == 2 and report["delivered"] == len(samples)
    assert sum(report["depth_at_get"].values()) == len(samples)
    assert report["late_deliveries"] == sum(v for k, v in report["depth_at_get"].items() if int(k) >= 2)
    assert report["late_deliveries"] > 0


def test_one_slot_keeps_every_delivery_fresh_without_changing_drop_or_timestamp_rules():
    src = _source(1)
    samples = _consume_slowly(src)
    report = src.queue_report()
    assert set(report["depth_at_get"]) == {"1"} and report["late_deliveries"] == 0
    stamps = [s.t_capture for s in samples]
    assert all(b > a for a, b in zip(stamps, stamps[1:], strict=False))  # strictly increasing, as recorded
    assert all(s.t_capture <= s.t_frame_available for s in samples)
    stats = src.stats()
    assert sum(s.dropped_since_last for s in samples) + src._queue.pending_drops == stats.dropped
    assert stats.dropped > 0


def test_the_config_schema_already_allows_a_one_slot_queue():
    cfg = load_config(
        ROOT / "configs" / "prototype.candidate.yaml",
        overrides={"camera_profile": {"queue": {"max_frames": 1}}},
    )
    assert CaptureSettings.from_config(cfg.data).queue_max_frames == 1
