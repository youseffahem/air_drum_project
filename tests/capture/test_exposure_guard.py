"""Measured-rate exposure guard (ADR-0048). SYNTHETIC: no webcam opens.

The fake camera reproduces the HW-01 finding: after another application switches the device to auto
exposure, the unique-frame rate halves while the driver still reports the requested value. Only a
re-applied exposure restores the rate.
"""

from __future__ import annotations

import pytest

from spacedrums import timing
from spacedrums.capture import (
    CaptureSettings,
    ExposureGuard,
    ExposureWatch,
    LiveFrameSource,
    Roi,
    SyntheticCamera,
)
from spacedrums.capture.backend import CameraOpenSpec
from spacedrums.capture.exposure import exposure_seconds
from spacedrums.contracts import TimestampSource

GUARD = ExposureGuard(min_fps=24, window_s=1.0, settle_s=2.0, fallback_value=-5, max_actions=3)


def feed(watch, fps, t0, seconds):
    """Unique frames at ``fps``; returns (end time, actions)."""
    actions, t = [], t0
    while t < t0 + seconds:
        a = watch.observe(t, 50.0)
        if a is not None:
            actions.append((round(t, 3), a))
        t += 1 / fps
    return t, actions


def test_manual_exposure_is_reapplied_when_the_rate_falls_and_not_before():
    w = ExposureWatch(GUARD, "MANUAL", -5, 0.0)
    t, actions = feed(w, 30, 0.0, 5.0)
    assert actions == [] and w.last_fps == pytest.approx(29, abs=1.5)
    t, actions = feed(w, 15, t, 3.0)  # Windows Camera switched the device to auto exposure
    assert [a for _, a in actions][:1] == [("MANUAL", -5)]
    assert w.events[0]["action"] == "REAPPLIED" and w.events[0]["fps"] < 24
    # every action waits a fresh window: at most one action per window_s
    times = [t for t, _ in actions]
    assert all(b - a >= GUARD.window_s - 1e-9 for a, b in zip(times, times[1:], strict=False))


def test_the_guard_gives_up_instead_of_fighting_forever():
    w = ExposureWatch(GUARD, "MANUAL", -5, 0.0)
    _, actions = feed(w, 10, 0.0, 20.0)
    assert len(actions) == GUARD.max_actions and not w.active
    assert "GAVE_UP" in w.events[-1]["note"]


def test_a_manual_exposure_longer_than_the_floor_period_is_not_guarded():
    assert exposure_seconds(-4) == pytest.approx(0.0625)
    w = ExposureWatch(GUARD, "MANUAL", -4, 0.0)  # 62.5 ms: 16 FPS is its normal rate
    _, actions = feed(w, 16, 0.0, 6.0)
    assert actions == [] and "longer than" in w.inactive_reason


def test_auto_waits_to_converge_then_switches_once_to_the_fallback():
    w = ExposureWatch(GUARD, "AUTO", None, 0.0)
    t, actions = feed(w, 15, 0.0, 1.9)
    assert actions == []  # still converging (settle_s)
    t, actions = feed(w, 15, t, 0.15)  # judged once settle_s and window_s have passed
    assert [a for _, a in actions] == [("MANUAL", -5)] and w.events[0]["action"] == "AUTO_TO_MANUAL"
    assert w.mode == "MANUAL" and w.value == -5
    _, actions = feed(w, 30, t, 4.0)
    assert actions == []


def test_auto_in_good_light_is_left_alone_and_without_a_fallback_only_recorded():
    w = ExposureWatch(GUARD, "AUTO", None, 0.0)
    assert feed(w, 30, 0.0, 6.0)[1] == [] and w.events == []
    w = ExposureWatch(ExposureGuard(min_fps=24, window_s=1.0, settle_s=1.0), "AUTO", None, 0.0)
    assert feed(w, 15, 0.0, 6.0)[1] == []
    assert [e["action"] for e in w.events] == ["AUTO_SLOW"]  # logged once


def test_invalid_guards_are_refused():
    for bad in ({"min_fps": 0}, {"window_s": 0}, {"max_actions": 0}, {"settle_s": -1}):
        with pytest.raises(ValueError):
            ExposureGuard.from_config(bad)


class HijackedCamera(SyntheticCamera):
    """Halves its unique rate after ``hijack_after`` frames until the exposure is applied again."""

    def __init__(self, hijack_after, **kw):
        super().__init__(width=64, height=48, fps=30.0, paced=True, **kw)
        self.hijack_after = hijack_after
        self.slow = False
        self.applied = []
        self.frames = 0

    def apply_exposure(self, mode, value):
        self.applied.append((mode, value))
        self.slow = False
        return super().apply_exposure(mode, value)

    def read(self):
        self.frames += 1
        if self.frames == self.hijack_after:
            self.slow = True
        if self.slow:  # every other sensor frame is lost: 15 unique FPS
            super().read()
        return super().read()


def settings(**kw):
    return CaptureSettings(camera_profile_id="synthetic-guard",
                           spec=CameraOpenSpec(exposure_mode="MANUAL", exposure_value=-5.0),
                           roi=Roi(0, 0, 64, 48), timestamp_source=TimestampSource.GRAB_RETURN,
                           nominal_fps=30.0, queue_max_frames=8, warmup_frames=2, **kw)


def test_live_source_reapplies_a_hijacked_exposure_and_reports_it():
    cam = HijackedCamera(hijack_after=60)
    s = settings(exposure_guard=ExposureGuard(min_fps=24, window_s=0.8, settle_s=0.0))
    src = LiveFrameSource(cam, s)
    with src:
        t0 = timing.now()
        while timing.now() - t0 < 4.5:
            src.next_frame(timeout=0.5)
    report = src.capture_report()["exposure"]
    assert report["requested"] == {"mode": "MANUAL", "value": -5.0}
    events = report["guard"]["events"]
    assert events and events[0]["action"] == "REAPPLIED"
    assert events[0]["to"] == {"mode": "MANUAL", "value": -5.0}
    assert cam.applied.count(("MANUAL", -5.0)) >= 2  # the warm-up apply, then the guard's
    assert not cam.slow  # the rate was restored


def test_without_a_guard_nothing_is_reapplied():
    cam = HijackedCamera(hijack_after=30)
    s = settings()
    src = LiveFrameSource(cam, s)
    with src:
        t0 = timing.now()
        while timing.now() - t0 < 2.5:
            src.next_frame(timeout=0.5)
    assert src.capture_report()["exposure"]["guard"] is None and cam.slow
