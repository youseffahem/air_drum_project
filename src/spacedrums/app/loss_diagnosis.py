"""Diagnostic attribution of tracking losses and live-loop freshness (live responsiveness, 2026-10-02).

``ResetReason`` (the contract enum on ``TrackState``) names the *rule* that ended a track:
``GAP_EXCEEDED``, ``LOW_CONFIDENCE`` or ``STALE``. This module names *why* the observations were not
good enough. Every frame whose stick observation stays below ``c_valid`` gets one limiting factor
from the perception detail of that frame (landmark detection, identity assignment, stick
analysis); every reset gets the cause that limited most frames since the hand's last ``VALID``
frame. Diagnostics only: nothing here feeds a decision, ``LossCause`` is not a contract enum and no
record or schema changes.

Limiting factor of a frame, first match wins. Each condition alone keeps the tip confidence below
``c_valid``: GEOM gives ``handedness * (0.5 + 0.5 * axis_confidence)`` with an axis and
``handedness * no_axis_confidence_factor`` without one (``stick.tip_geom``).

1. no hand from the landmark detector: ``HAND_LEFT_ROI`` when the hand was last seen at the ROI
   edge, else ``HAND_NOT_DETECTED``;
2. a hand but no stick record: ``GRIP_DEGENERATE``;
3. LEFT/RIGHT assignment ambiguous (score capped): ``IDENTITY_AMBIGUOUS``;
4. handedness below ``c_valid``: ``IDENTITY_LOW_CONTINUITY`` when the wrist-continuity term is the
   weaker one, else ``IDENTITY_LOW_LABEL``;
5. no stick axis: ``STICK_NO_SEARCH_REGION``, ``STICK_NO_EDGES``, ``STICK_REJECTED_ORIENTATION`` /
   ``_ELONGATION`` / ``_SIZE`` (the reject reason covering most edge pixels) or ``AXIS_FIT_REJECTED``
   (kept pixels, but no line passes the inlier and grip-tolerance tests);
6. an axis, but the tip still below ``c_valid``: ``AXIS_LOW_CONFIDENCE``.

``*_UNRESOLVED`` causes mean that the perception detail was not available (SYNTHETIC or injected
observations); they never appear for frames that came through ``Perception``. A reset whose frame
interval exceeds the tracker's gap limit (ADR-0040 D3) is ``FRAME_GAP_DROPS`` when the queue
reported dropped frames before that frame and ``FRAME_GAP_STALL`` otherwise.

Motion blur, fast movement and occlusion are not causes here: without ground truth they cannot be
separated from each other. Analyses stratify the limiting factors by wrist speed and brightness.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from spacedrums.contracts import (
    FrameSample,
    HandId,
    HandObservation,
    ResetReason,
    StickObservation,
    TrackState,
    TrackStatus,
)

HANDS = (HandId.LEFT, HandId.RIGHT)
LOST = (TrackStatus.INVALID, TrackStatus.STALE)
LOSS_RESETS = (ResetReason.GAP_EXCEEDED, ResetReason.LOW_CONFIDENCE, ResetReason.STALE)


class LossCause(StrEnum):
    """Diagnostic cause of a sub-``c_valid`` frame or of a reset (declaration order = precedence)."""

    FRAME_GAP_DROPS = "FRAME_GAP_DROPS"
    FRAME_GAP_STALL = "FRAME_GAP_STALL"
    HAND_LEFT_ROI = "HAND_LEFT_ROI"
    HAND_NOT_DETECTED = "HAND_NOT_DETECTED"
    GRIP_DEGENERATE = "GRIP_DEGENERATE"
    IDENTITY_AMBIGUOUS = "IDENTITY_AMBIGUOUS"
    IDENTITY_LOW_CONTINUITY = "IDENTITY_LOW_CONTINUITY"
    IDENTITY_LOW_LABEL = "IDENTITY_LOW_LABEL"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    STICK_NO_SEARCH_REGION = "STICK_NO_SEARCH_REGION"
    STICK_NO_EDGES = "STICK_NO_EDGES"
    STICK_REJECTED_ORIENTATION = "STICK_REJECTED_ORIENTATION"
    STICK_REJECTED_ELONGATION = "STICK_REJECTED_ELONGATION"
    STICK_REJECTED_SIZE = "STICK_REJECTED_SIZE"
    AXIS_FIT_REJECTED = "AXIS_FIT_REJECTED"
    AXIS_UNRESOLVED = "AXIS_UNRESOLVED"
    AXIS_LOW_CONFIDENCE = "AXIS_LOW_CONFIDENCE"


_PRECEDENCE = {cause: i for i, cause in enumerate(LossCause)}
_REJECTED = {
    "orientation": LossCause.STICK_REJECTED_ORIENTATION,
    "not_elongated": LossCause.STICK_REJECTED_ELONGATION,
    "too_small": LossCause.STICK_REJECTED_SIZE,
    "surplus": LossCause.STICK_REJECTED_SIZE,  # only reachable with kept components; listed for completeness
}


@dataclass(frozen=True)
class FrameQuality:
    """Why one hand's observation in one frame was (not) good enough for ``VALID``."""

    frame_id: int
    t_capture: float
    hand_id: HandId
    limiting: LossCause | None  # None: the observation reaches c_valid
    hand_present: bool
    stick_present: bool
    axis_found: bool
    handedness: float | None
    tip_confidence: float
    ambiguous: bool = False


def at_roi_edge(bbox: tuple[float, float, float, float] | None, margin: float) -> bool:
    if bbox is None:
        return False
    x, y, w, h = bbox
    return x <= margin or y <= margin or x + w >= 1.0 - margin or y + h >= 1.0 - margin


def stick_failure(analysis: Any) -> LossCause:
    """Why GEOM found no axis, from the frame's ``StickAnalysis`` (None: detail unavailable)."""
    if analysis is None:
        return LossCause.AXIS_UNRESOLVED
    segment = getattr(analysis, "segment", None)
    if getattr(analysis, "region", None) is None or segment is None:
        return LossCause.STICK_NO_SEARCH_REGION
    if not segment.components:
        return LossCause.STICK_NO_EDGES
    if segment.n_kept > 0:
        return LossCause.AXIS_FIT_REJECTED
    pixels: Counter[LossCause] = Counter()
    for component in segment.components:
        if component.reject_reason in _REJECTED:
            pixels[_REJECTED[component.reject_reason]] += int(component.n_px)
    if not pixels:
        return LossCause.AXIS_FIT_REJECTED
    return min(pixels, key=lambda cause: (-pixels[cause], _PRECEDENCE[cause]))


def frame_quality(
    hand_obs: HandObservation,
    stick_obs: StickObservation,
    *,
    c_valid: float,
    assignment: Any = None,
    ambiguous: bool = False,
    analysis: Any = None,
    detail: bool = True,
    last_seen_bbox: tuple[float, float, float, float] | None = None,
    roi_edge_margin: float = 0.02,
) -> FrameQuality:
    """The limiting factor of one hand in one frame (module docstring).

    ``assignment`` is the hand's ``HandAssignment`` and ``analysis`` its ``StickAnalysis`` from the
    same frame; ``detail=False`` says that neither belongs to these observations (SYNTHETIC or
    injected), so identity and stick causes are reported ``*_UNRESOLVED``.
    """
    stick = bool(stick_obs.present and stick_obs.tip is not None)
    tip = float(stick_obs.tip_confidence) if stick else 0.0
    axis = bool(stick and stick_obs.axis_confidence > 0.0)
    handedness = hand_obs.handedness_score if hand_obs.present else None
    capped = bool(detail and ambiguous and hand_obs.present)
    limiting: LossCause | None = None
    if not hand_obs.present:
        limiting = (
            LossCause.HAND_LEFT_ROI
            if at_roi_edge(last_seen_bbox, roi_edge_margin)
            else LossCause.HAND_NOT_DETECTED
        )
    elif not stick:
        limiting = LossCause.GRIP_DEGENERATE
    elif tip >= c_valid:
        limiting = None
    elif capped:
        limiting = LossCause.IDENTITY_AMBIGUOUS
    elif handedness is not None and handedness < c_valid:
        if not detail or assignment is None:
            limiting = LossCause.IDENTITY_UNRESOLVED
        elif assignment.p_temporal is not None and assignment.p_temporal < assignment.p_label:
            limiting = LossCause.IDENTITY_LOW_CONTINUITY
        else:
            limiting = LossCause.IDENTITY_LOW_LABEL
    elif not axis:
        limiting = stick_failure(analysis if detail else None)
    else:
        limiting = LossCause.AXIS_LOW_CONFIDENCE
    return FrameQuality(
        frame_id=hand_obs.frame_id,
        t_capture=hand_obs.t_capture,
        hand_id=hand_obs.hand_id,
        limiting=limiting,
        hand_present=bool(hand_obs.present),
        stick_present=stick,
        axis_found=axis,
        handedness=handedness,
        tip_confidence=tip,
        ambiguous=capped,
    )


def majority(counts: Counter[LossCause]) -> LossCause:
    """Most frequent cause; ties go to the earlier ``LossCause`` (declaration order)."""
    return min(counts, key=lambda cause: (-counts[cause], _PRECEDENCE[cause]))


@dataclass(frozen=True)
class ResetDiagnosis:
    hand_id: HandId
    frame_id: int
    t_capture: float
    reason: ResetReason
    cause: LossCause
    window_frames: int  # frames since the last VALID frame (or the previous reset) incl. this one
    breakdown: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hand_id": str(self.hand_id),
            "frame_id": self.frame_id,
            "t": self.t_capture,
            "reason": str(self.reason),
            "cause": str(self.cause),
            "window_frames": self.window_frames,
            "breakdown": dict(self.breakdown),
        }


@dataclass
class _HandState:
    window: Counter = field(default_factory=Counter)
    window_n: int = 0
    previous_status: TrackStatus | None = None
    episode_cause: LossCause | None = None  # cause of the first reset of the current loss
    reacquired_cause: LossCause | None = None  # cause of the loss that the last re-acquisition ended
    reacquisitions: int = 0


class LossDiagnosisMonitor:
    """Per-hand reset attribution over a session; feed one ``FrameQuality`` + ``TrackState`` per frame."""

    def __init__(self, *, max_gap_s: float | None, keep_resets: int = 2000) -> None:
        self.max_gap_s = max_gap_s
        self.keep_resets = int(keep_resets)
        self._state = {h: _HandState() for h in HANDS}
        self.resets: dict[HandId, list[ResetDiagnosis]] = {h: [] for h in HANDS}
        self.resets_truncated = {h: 0 for h in HANDS}
        self.reset_causes: dict[HandId, Counter] = {h: Counter() for h in HANDS}
        self.episode_causes: dict[HandId, Counter] = {h: Counter() for h in HANDS}
        self.non_valid_frames: dict[HandId, Counter] = {h: Counter() for h in HANDS}
        self.lost_frames: dict[HandId, Counter] = {h: Counter() for h in HANDS}

    def observe(
        self,
        quality: FrameQuality,
        track: TrackState,
        *,
        dt_s: float | None,
        dropped_since_last: int = 0,
    ) -> ResetDiagnosis | None:
        h = HandId(track.hand_id)
        st = self._state[h]
        status = TrackStatus(track.status)
        if status is TrackStatus.VALID:
            if st.previous_status in LOST:
                st.reacquisitions += 1
                st.reacquired_cause = st.episode_cause
                st.episode_cause = None
        elif quality.limiting is not None:
            st.window[quality.limiting] += 1
            self.non_valid_frames[h][quality.limiting] += 1
            if status in LOST and track.reset_reason is None:
                self.lost_frames[h][quality.limiting] += 1
        if status is not TrackStatus.VALID:
            st.window_n += 1
        diagnosis = None
        reason = None if track.reset_reason is None else ResetReason(track.reset_reason)
        if reason in LOSS_RESETS:
            gap = dt_s is not None and self.max_gap_s is not None and dt_s > self.max_gap_s
            if reason is ResetReason.GAP_EXCEEDED and gap:
                cause = LossCause.FRAME_GAP_DROPS if dropped_since_last > 0 else LossCause.FRAME_GAP_STALL
            elif st.window:
                cause = majority(st.window)
            else:  # a reset always follows at least one sub-c_valid frame; kept total, never silent
                cause = quality.limiting or LossCause.FRAME_GAP_STALL
            diagnosis = ResetDiagnosis(
                hand_id=h,
                frame_id=track.frame_id,
                t_capture=track.t_capture,
                reason=reason,
                cause=cause,
                window_frames=max(1, st.window_n),
                breakdown={
                    str(k): v for k, v in sorted(st.window.items(), key=lambda kv: _PRECEDENCE[kv[0]])
                },
            )
            self.reset_causes[h][(str(reason), str(cause))] += 1
            if st.episode_cause is None:
                st.episode_cause = cause
                self.episode_causes[h][str(cause)] += 1
            if status is TrackStatus.VALID:  # time-gap reset re-acquired on the same frame (no SD-TRK-002)
                st.episode_cause = None
            if len(self.resets[h]) < self.keep_resets:
                self.resets[h].append(diagnosis)
            else:
                self.resets_truncated[h] += 1
        if status is TrackStatus.VALID or diagnosis is not None:
            st.window.clear()
            st.window_n = 0
        st.previous_status = status
        return diagnosis

    def reacquired_cause(self, hand: HandId | str) -> str | None:
        """Cause of the loss that the most recent re-acquisition of ``hand`` ended."""
        cause = self._state[HandId(hand)].reacquired_cause
        return None if cause is None else str(cause)

    def summary(self) -> dict[str, Any]:
        def table(counter: Counter) -> dict[str, Any]:
            total = sum(counter.values())
            return {
                "total": total,
                "counts": {str(k): v for k, v in counter.most_common()},
                "percent": {str(k): 100.0 * v / total for k, v in counter.most_common()} if total else {},
            }

        all_resets: Counter = Counter()
        all_episodes: Counter = Counter()
        for h in HANDS:
            all_resets.update(cause for (_, cause), n in self.reset_causes[h].items() for _ in range(n))
            all_episodes.update(self.episode_causes[h])
        return {
            "note": "diagnostic attribution (spacedrums.app.loss_diagnosis); not a contract field",
            "resets_by_cause": table(all_resets),
            "losses_by_cause": table(all_episodes),
            "per_hand": {
                str(h): {
                    "reacquisitions": self._state[h].reacquisitions,
                    "reset_reason_cause": {
                        f"{r}/{c}": n for (r, c), n in sorted(self.reset_causes[h].items())
                    },
                    "losses_by_cause": dict(self.episode_causes[h].most_common()),
                    "non_valid_frames_by_cause": {
                        str(k): v for k, v in self.non_valid_frames[h].most_common()
                    },
                    "lost_frames_by_cause": {str(k): v for k, v in self.lost_frames[h].most_common()},
                    "resets": [r.to_dict() for r in self.resets[h]],
                    "resets_not_listed": self.resets_truncated[h],
                }
                for h in HANDS
            },
        }


def distribution_ms(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    v = np.asarray(values, dtype=float) * 1000.0
    out: dict[str, Any] = {"n": int(v.size)}
    for p in (50, 90, 95, 99):
        out[f"p{p}_ms"] = float(np.percentile(v, p))
    out["max_ms"] = float(v.max())
    return out


class RuntimeDiagnostics:
    """Per-session diagnostics for the app summary: reset causes, frame freshness, hand-model cost.

    Nothing here is a decision input. ``observe`` runs after the frame's processing time is taken.
    """

    def __init__(self, *, c_valid: float, max_gap_s: float | None, live: bool, roi_edge_margin: float = 0.02):
        self.c_valid = float(c_valid)
        self.live = bool(live)
        self.roi_edge_margin = roi_edge_margin
        self.monitor = LossDiagnosisMonitor(max_gap_s=max_gap_s)
        self.age_at_start_s: list[float] = []
        self.capture_to_start_s: list[float] = []
        self.hands_s_by_prev_detected: dict[int, list[float]] = {}
        self._prev_detected: int | None = None
        self._prev_t: float | None = None
        self._last_bbox: dict[HandId, tuple[float, float, float, float] | None] = {h: None for h in HANDS}

    def observe(
        self,
        sample: FrameSample,
        observations: Any,
        result: Any,
        perception: Any = None,
        *,
        t_start: float,
    ) -> dict[HandId, ResetDiagnosis]:
        if self.live:
            self.age_at_start_s.append(t_start - sample.t_frame_available)
            self.capture_to_start_s.append(t_start - sample.t_capture)
        hands_result = getattr(perception, "last_hands", None) if perception is not None else None
        detail = hands_result is not None and hands_result.observations[0] is observations[HandId.LEFT][0]
        identity = hands_result.identity if detail else None
        analyses = getattr(perception, "last_analyses", {}) if detail else {}
        if detail:
            if self._prev_detected is not None:
                self.hands_s_by_prev_detected.setdefault(self._prev_detected, []).append(
                    hands_result.processing_s
                )
            self._prev_detected = hands_result.n_detected
        dt = None if self._prev_t is None else sample.t_capture - self._prev_t
        self._prev_t = sample.t_capture
        out: dict[HandId, ResetDiagnosis] = {}
        for h in HANDS:
            hand_obs, stick_obs = observations[h]
            quality = frame_quality(
                hand_obs,
                stick_obs,
                c_valid=self.c_valid,
                assignment=identity.assignments.get(h) if identity is not None else None,
                ambiguous=bool(identity is not None and identity.ambiguous and h in identity.assignments),
                analysis=analyses.get(h),
                detail=detail,
                last_seen_bbox=self._last_bbox[h],
                roi_edge_margin=self.roi_edge_margin,
            )
            if hand_obs.present:
                self._last_bbox[h] = hand_obs.bbox
            diagnosis = self.monitor.observe(
                quality, result.hands[h].track, dt_s=dt, dropped_since_last=sample.dropped_since_last
            )
            if diagnosis is not None:
                out[h] = diagnosis
        return out

    def reacquired_cause(self, hand: HandId | str) -> str | None:
        return self.monitor.reacquired_cause(hand)

    def summary(self, source_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        queue = (source_meta or {}).get("queue")
        return {
            "loss_diagnosis": self.monitor.summary(),
            "frame_freshness": {
                "scope": "live sources only (replay timestamps are historical)",
                "frame_available_to_processing_start": distribution_ms(self.age_at_start_s),
                "capture_to_processing_start": distribution_ms(self.capture_to_start_s),
                "queue": queue,
            },
            "hands_model_s_by_previous_hands_detected": {
                str(k): distribution_ms(v) for k, v in sorted(self.hands_s_by_prev_detected.items())
            },
        }


__all__ = [
    "FrameQuality",
    "LossCause",
    "LossDiagnosisMonitor",
    "ResetDiagnosis",
    "RuntimeDiagnostics",
    "at_roi_edge",
    "distribution_ms",
    "frame_quality",
    "majority",
    "stick_failure",
]
