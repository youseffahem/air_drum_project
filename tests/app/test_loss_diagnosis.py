"""Loss-cause attribution (``spacedrums.app.loss_diagnosis``, live responsiveness 2026-10-02).

Every limiting factor is reachable from crafted observations, the precedence is the documented one,
resets get the cause that limited most frames since the last VALID frame (or a frame-gap cause), and
the app summary / SD-TRK-002 events carry the attribution. SYNTHETIC inputs only.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from spacedrums.app.loss_diagnosis import (
    LossCause,
    LossDiagnosisMonitor,
    RuntimeDiagnostics,
    frame_quality,
    majority,
)
from spacedrums.contracts import (
    HandId,
    HandObservation,
    ResetReason,
    StickObservation,
    TipMethod,
    TrackStatus,
)
from spacedrums.tracking import CausalTracker, TrackerSettings

H = HandId.RIGHT
C_VALID = 0.6
DT = 1 / 30


def hand(frame: int, *, present: bool = True, score: float = 0.95, bbox=(0.4, 0.4, 0.1, 0.1)):
    t = 100.0 + frame * DT
    if not present:
        return HandObservation.absent(frame, t, H, "det")
    lm = tuple((0.45 + 0.001 * i, 0.45) for i in range(21))
    return HandObservation(frame, t, H, True, "det", lm, None, score, bbox)


def stick(
    frame: int, *, tip_conf: float = 0.9, axis_conf: float = 0.8, present: bool = True, tip=(0.45, 0.3)
):
    t = 100.0 + frame * DT
    if not present:
        return StickObservation.absent(frame, t, H, TipMethod.GEOM)
    return StickObservation(
        frame, t, H, True, TipMethod.GEOM, (0.45, 0.45), (0.0, -1.0), tip, tip_conf, axis_conf, 0.27
    )


def component(reason: str | None, n_px: int):
    return SimpleNamespace(reject_reason=reason, n_px=n_px, kept=reason is None)


def analysis(components=(), *, region=True, segment=True):
    comps = tuple(components)
    seg = SimpleNamespace(components=comps, n_kept=sum(c.kept for c in comps)) if segment else None
    return SimpleNamespace(region=object() if region else None, segment=seg)


ASSIGN_CONT = SimpleNamespace(p_label=0.95, p_temporal=0.1)
ASSIGN_LABEL = SimpleNamespace(p_label=0.45, p_temporal=0.9)
NO_AXIS = dict(tip_conf=0.38, axis_conf=0.0)


@pytest.mark.parametrize(
    ("hand_kw", "stick_kw", "extra", "expected"),
    [
        ({"present": False}, {"present": False}, {}, LossCause.HAND_NOT_DETECTED),
        (
            {"present": False},
            {"present": False},
            {"last_seen_bbox": (0.0, 0.5, 0.1, 0.1)},
            LossCause.HAND_LEFT_ROI,
        ),
        ({}, {"present": False}, {}, LossCause.GRIP_DEGENERATE),
        ({}, {}, {}, None),
        ({"score": 0.5}, {"tip_conf": 0.45}, {"ambiguous": True}, LossCause.IDENTITY_AMBIGUOUS),
        ({"score": 0.55}, {"tip_conf": 0.5}, {"assignment": ASSIGN_CONT}, LossCause.IDENTITY_LOW_CONTINUITY),
        ({"score": 0.55}, {"tip_conf": 0.5}, {"assignment": ASSIGN_LABEL}, LossCause.IDENTITY_LOW_LABEL),
        ({"score": 0.55}, {"tip_conf": 0.5}, {"detail": False}, LossCause.IDENTITY_UNRESOLVED),
        ({}, NO_AXIS, {"analysis": analysis(region=False, segment=False)}, LossCause.STICK_NO_SEARCH_REGION),
        ({}, NO_AXIS, {"analysis": analysis()}, LossCause.STICK_NO_EDGES),
        (
            {},
            NO_AXIS,
            {"analysis": analysis([component("orientation", 300), component("too_small", 20)])},
            LossCause.STICK_REJECTED_ORIENTATION,
        ),
        (
            {},
            NO_AXIS,
            {"analysis": analysis([component("orientation", 30), component("not_elongated", 200)])},
            LossCause.STICK_REJECTED_ELONGATION,
        ),
        ({}, NO_AXIS, {"analysis": analysis([component("too_small", 24)])}, LossCause.STICK_REJECTED_SIZE),
        ({}, NO_AXIS, {"analysis": analysis([component(None, 400)])}, LossCause.AXIS_FIT_REJECTED),
        ({}, NO_AXIS, {"detail": False}, LossCause.AXIS_UNRESOLVED),
        ({}, {"tip_conf": 0.55, "axis_conf": 0.2}, {}, LossCause.AXIS_LOW_CONFIDENCE),
    ],
)
def test_limiting_factor_of_each_documented_case(hand_kw, stick_kw, extra, expected):
    q = frame_quality(hand(5, **hand_kw), stick(5, **stick_kw), c_valid=C_VALID, **extra)
    assert q.limiting is expected
    assert q.hand_present == hand_kw.get("present", True)


def test_identity_outranks_a_missing_axis_and_ambiguity_outranks_identity():
    both = frame_quality(
        hand(1, score=0.55),
        stick(1, **NO_AXIS),
        c_valid=C_VALID,
        assignment=ASSIGN_CONT,
        analysis=analysis([component("orientation", 50)]),
    )
    assert both.limiting is LossCause.IDENTITY_LOW_CONTINUITY and not both.axis_found
    capped = frame_quality(
        hand(1, score=0.5), stick(1, **NO_AXIS), c_valid=C_VALID, ambiguous=True, assignment=ASSIGN_CONT
    )
    assert capped.limiting is LossCause.IDENTITY_AMBIGUOUS


def test_majority_breaks_ties_by_declaration_order():
    from collections import Counter

    assert (
        majority(Counter({LossCause.AXIS_FIT_REJECTED: 2, LossCause.HAND_NOT_DETECTED: 2}))
        is LossCause.HAND_NOT_DETECTED
    )


def drive(frames, *, settings=None, dropped=None, times=None):
    """Feed (hand_obs, stick_obs, extra) frames through a real tracker and the monitor."""
    settings = settings or TrackerSettings(max_frame_gap_s=4.5 / 30)
    tracker = CausalTracker(H, settings)
    tracker.reset(ResetReason.SESSION_START)
    monitor = LossDiagnosisMonitor(max_gap_s=settings.max_frame_gap_s)
    out, prev_t = [], None
    for k, (h_obs, s_obs, extra) in enumerate(frames):
        t = times[k] if times else h_obs.t_capture
        h_obs = HandObservation(**{**h_obs.__dict__, "t_capture": t})
        s_obs = StickObservation(**{**s_obs.__dict__, "t_capture": t})
        track = tracker.update(h_obs, s_obs, t)
        q = frame_quality(h_obs, s_obs, c_valid=settings.machine.c_valid, **extra)
        d = monitor.observe(
            q,
            track,
            dt_s=None if prev_t is None else t - prev_t,
            dropped_since_last=(dropped or {}).get(k, 0),
        )
        out.append((track, d))
        prev_t = t
    return monitor, out


def test_hand_detector_miss_resets_with_its_cause_and_the_reacquisition_reports_it():
    frames = [(hand(k), stick(k), {}) for k in range(5)]
    frames += [(hand(k, present=False), stick(k, present=False), {}) for k in range(5, 10)]
    frames += [(hand(k), stick(k), {}) for k in range(10, 13)]
    monitor, out = drive(frames)
    resets = [d for _, d in out if d is not None]
    assert [(d.reason, d.cause) for d in resets] == [(ResetReason.GAP_EXCEEDED, LossCause.HAND_NOT_DETECTED)]
    assert out[10][0].status is TrackStatus.VALID
    assert monitor.reacquired_cause(H) == "HAND_NOT_DETECTED"
    summary = monitor.summary()
    assert summary["per_hand"]["RIGHT"]["reacquisitions"] == 1
    assert summary["resets_by_cause"]["counts"] == {"HAND_NOT_DETECTED": 1}
    assert sum(summary["resets_by_cause"]["percent"].values()) == pytest.approx(100.0)


def test_a_sustained_no_axis_stretch_goes_stale_with_the_segmentation_cause():
    rejected = {"analysis": analysis([component("orientation", 300)])}
    frames = [(hand(k), stick(k), {}) for k in range(3)]
    frames += [(hand(k), stick(k, **NO_AXIS), rejected) for k in range(3, 25)]  # 0.73 s without VALID
    _, out = drive(frames)
    resets = [d for _, d in out if d is not None]
    assert resets and resets[0].reason is ResetReason.STALE
    assert resets[0].cause is LossCause.STICK_REJECTED_ORIENTATION
    assert resets[0].breakdown == {"STICK_REJECTED_ORIENTATION": resets[0].window_frames}


@pytest.mark.parametrize(
    ("dropped", "expected"), [(5, LossCause.FRAME_GAP_DROPS), (0, LossCause.FRAME_GAP_STALL)]
)
def test_a_frame_interval_beyond_the_gap_limit_is_a_frame_gap(dropped, expected):
    frames = [(hand(k), stick(k), {}) for k in range(6)]
    times = [100.0 + k * DT for k in range(5)] + [100.0 + 4 * DT + 0.2]
    _, out = drive(frames, times=times, dropped={5: dropped})
    resets = [d for _, d in out if d is not None]
    assert [(d.reason, d.cause) for d in resets] == [(ResetReason.GAP_EXCEEDED, expected)]
    assert out[5][0].status is TrackStatus.VALID  # re-acquired on the same frame, nothing invented


def test_a_second_reset_during_one_loss_is_listed_but_the_loss_keeps_its_first_cause():
    frames = [(hand(k), stick(k), {}) for k in range(3)]
    frames += [(hand(k, present=False), stick(k, present=False), {}) for k in range(3, 25)]
    frames += [(hand(k), stick(k), {}) for k in range(25, 27)]
    monitor, out = drive(frames)
    resets = [d for _, d in out if d is not None]
    assert [d.reason for d in resets] == [ResetReason.GAP_EXCEEDED, ResetReason.STALE]
    per_hand = monitor.summary()["per_hand"]["RIGHT"]
    assert per_hand["losses_by_cause"] == {"HAND_NOT_DETECTED": 1}
    assert monitor.reacquired_cause(H) == "HAND_NOT_DETECTED"


def test_runtime_diagnostics_wire_into_the_app_summary_and_reacquisition_events(tmp_path, monkeypatch):
    from spacedrums.app.main import build_parser, run

    monkeypatch.setenv("SPACEDRUMS_FAULT_INJECTION", "1")  # observation_hook is a test-build seam

    def occlude_right(sample, observations):
        if not 20 <= sample.frame_id < 28:
            return observations
        out = dict(observations)
        t = sample.t_capture
        out[H] = (
            HandObservation.absent(sample.frame_id, t, H, "det"),
            StickObservation.absent(sample.frame_id, t, H, TipMethod.GEOM),
        )
        return out

    args = build_parser().parse_args(
        [
            "--synthetic",
            "single",
            "--no-window",
            "--no-audio",
            "--log-dir",
            str(tmp_path),
            "--session-id",
            "diag",
        ]
    )
    summary = run(args, observation_hook=occlude_right)
    diag = summary["counters"]["diagnostics"]
    assert set(diag) == {"loss_diagnosis", "frame_freshness", "hands_model_s_by_previous_hands_detected"}
    assert diag["frame_freshness"]["frame_available_to_processing_start"] == {"n": 0}  # not a live source
    losses = diag["loss_diagnosis"]["per_hand"]["RIGHT"]
    assert losses["losses_by_cause"] == {"HAND_NOT_DETECTED": 1} and losses["reacquisitions"] == 1
    lines = (tmp_path / "diag" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    reacquired = [e for e in map(json.loads, lines) if e["code"] == "SD-TRK-002"]
    assert [e["detail"]["loss_cause"] for e in reacquired] == ["HAND_NOT_DETECTED"]


def test_runtime_diagnostics_never_use_perception_detail_that_belongs_to_other_observations():
    diag = RuntimeDiagnostics(c_valid=C_VALID, max_gap_s=0.15, live=False)
    observations = {
        h: (HandObservation.absent(0, 100.0, h, "d"), StickObservation.absent(0, 100.0, h, TipMethod.GEOM))
        for h in (HandId.LEFT, HandId.RIGHT)
    }
    perception = SimpleNamespace(
        last_hands=SimpleNamespace(observations=(object(), object())), last_analyses={}
    )
    track = SimpleNamespace(
        status=TrackStatus.INVALID, reset_reason=None, frame_id=0, t_capture=100.0, hand_id=HandId.LEFT
    )
    result = SimpleNamespace(
        hands={
            h: SimpleNamespace(track=SimpleNamespace(**{**track.__dict__, "hand_id": h}))
            for h in (HandId.LEFT, HandId.RIGHT)
        }
    )
    sample = SimpleNamespace(t_capture=100.0, t_frame_available=100.001, dropped_since_last=0)
    assert diag.observe(sample, observations, result, perception, t_start=100.002) == {}
    assert diag.hands_s_by_prev_detected == {}  # foreign detail is ignored, not attributed
