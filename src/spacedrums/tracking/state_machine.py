"""README section 8 tracking state machine (Phase 03, Task 03.13) — pure transition logic.

Thresholds (all tunable, ``tracking`` config block): ``c_valid``, ``c_min``, ``g_max_frames``,
``age_max_s``; bridge confidence decay ``bridge_decay`` (per bridged frame).

Rules implemented (Q34-Q35: never fabricate, never use the future):

* observation with ``conf >= c_valid``                -> ``VALID``   (fresh; ``frames_since_valid = 0``)
* observation with ``c_min <= conf < c_valid``        -> ``DEGRADED`` (observation used, noise scaled)
* no usable observation (absent or ``conf < c_min``)  -> ``DEGRADED`` **bridge** (prediction only,
  confidence decays) for at most ``g_max_frames`` consecutive frames, then ``INVALID`` with reset
  reason ``LOW_CONFIDENCE`` (the hand is seen but untrustworthy) or ``GAP_EXCEEDED`` (no hand at all);
  a bridge is only possible from a live state (``VALID``/``DEGRADED``).
* ``t - last_valid_t > age_max_s`` while not fresh    -> ``STALE`` (reset reason ``STALE`` once).
* re-acquisition from ``INVALID``/``STALE`` needs ``conf >= c_valid`` (a DEGRADED-level observation
  does not re-acquire — tunable ``acquire_on_degraded``); the filter is initialised from that
  observation and history starts empty (architecture.md 6.2, "initialise from observation").

The machine decides *what* the tracker does with the filter (``init`` / ``update`` / ``predict`` /
``reset`` / ``none``); the tracker executes it. Kept separate so every transition is unit-testable
without a filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spacedrums.contracts import ResetReason, TrackStatus


@dataclass(frozen=True)
class StateMachineSettings:
    c_valid: float = 0.6
    c_min: float = 0.3
    g_max_frames: int = 3
    age_max_s: float = 0.5
    bridge_decay: float = 0.7  # confidence multiplier per bridged (prediction-only) frame
    acquire_on_degraded: bool = False

    def __post_init__(self) -> None:
        if not (0.0 <= self.c_min <= self.c_valid <= 1.0):
            raise ValueError("require 0 <= c_min <= c_valid <= 1")
        if self.g_max_frames < 0 or self.age_max_s <= 0:
            raise ValueError("g_max_frames >= 0 and age_max_s > 0 required")
        if not (0.0 < self.bridge_decay <= 1.0):
            raise ValueError("bridge_decay in (0, 1]")

    @classmethod
    def from_config(cls, tracking_cfg: dict[str, Any]) -> StateMachineSettings:
        params = tracking_cfg.get("filter", {}).get("params", {})
        return cls(c_valid=float(tracking_cfg["c_valid"]), c_min=float(tracking_cfg["c_min"]),
                   g_max_frames=int(tracking_cfg["g_max_frames"]), age_max_s=float(tracking_cfg["age_max_s"]),
                   bridge_decay=float(params.get("bridge_decay", 0.7)),
                   acquire_on_degraded=bool(params.get("acquire_on_degraded", False)))


@dataclass(frozen=True)
class Decision:
    status: TrackStatus
    action: str  # init | update | predict | reset | none
    confidence: float
    frames_since_valid: int
    last_valid_t: float | None
    reset_reason: ResetReason | None
    gap_frames: int  # consecutive frames without a usable observation (after this frame)


@dataclass
class MachineState:
    status: TrackStatus = TrackStatus.INVALID
    confidence: float = 0.0
    frames_since_valid: int = 0
    last_valid_t: float | None = None
    gap_frames: int = 0
    pending_reset: ResetReason | None = None  # external reset to report on the next frame

    def reset(self, reason: ResetReason) -> None:
        self.status = TrackStatus.INVALID
        self.confidence = 0.0
        self.frames_since_valid = 0
        self.last_valid_t = None
        self.gap_frames = 0
        self.pending_reset = reason


class TrackingStateMachine:
    def __init__(self, settings: StateMachineSettings) -> None:
        self.s = settings
        self.state = MachineState()

    def reset(self, reason: ResetReason) -> None:
        self.state.reset(reason)

    def step(self, t: float, has_obs: bool, conf: float) -> Decision:
        s, st = self.s, self.state
        pending, st.pending_reset = st.pending_reset, None
        live = st.status in (TrackStatus.VALID, TrackStatus.DEGRADED)
        usable = has_obs and conf >= s.c_min

        if usable and conf >= s.c_valid:
            action = "update" if live else "init"
            st.status, st.confidence, st.frames_since_valid, st.last_valid_t, st.gap_frames = \
                TrackStatus.VALID, conf, 0, t, 0
            return Decision(TrackStatus.VALID, action, conf, 0, t, pending, 0)

        if usable:  # c_min <= conf < c_valid
            if live or s.acquire_on_degraded:
                action = "update" if live else "init"
                st.status = TrackStatus.DEGRADED
                st.confidence = conf
                st.frames_since_valid += 1
                st.gap_frames = 0
                if st.last_valid_t is None:
                    st.last_valid_t = t  # acquired on a degraded observation: counts for STALE
                dec = Decision(TrackStatus.DEGRADED, action, conf, st.frames_since_valid, st.last_valid_t,
                               pending, 0)
                return self._maybe_stale(t, dec)
            # INVALID/STALE and a degraded observation: stays where it is, nothing fabricated
            st.frames_since_valid += 1
            return Decision(st.status, "none", 0.0, st.frames_since_valid, st.last_valid_t, pending,
                            st.gap_frames)

        # no usable observation
        if live:
            st.gap_frames += 1
            st.frames_since_valid += 1
            if st.gap_frames <= s.g_max_frames:
                st.status = TrackStatus.DEGRADED
                st.confidence = st.confidence * s.bridge_decay
                dec = Decision(TrackStatus.DEGRADED, "predict", st.confidence, st.frames_since_valid,
                               st.last_valid_t, pending, st.gap_frames)
                return self._maybe_stale(t, dec)
            reason = ResetReason.LOW_CONFIDENCE if has_obs else ResetReason.GAP_EXCEEDED
            last_valid = st.last_valid_t
            fsv = st.frames_since_valid
            st.reset(reason)
            st.pending_reset = None
            st.last_valid_t = last_valid  # kept for the STALE decision (reset matrix)
            st.frames_since_valid = fsv
            return Decision(TrackStatus.INVALID, "reset", 0.0, fsv, last_valid, reason, st.gap_frames)
        # already INVALID/STALE
        st.frames_since_valid += 1
        st.gap_frames += 1
        dec = Decision(st.status, "none", 0.0, st.frames_since_valid, st.last_valid_t, pending, st.gap_frames)
        return self._maybe_stale(t, dec)

    def _maybe_stale(self, t: float, dec: Decision) -> Decision:
        s, st = self.s, self.state
        if dec.status is TrackStatus.VALID:
            return dec
        aged = st.last_valid_t is not None and (t - st.last_valid_t) > s.age_max_s
        if aged and st.status is not TrackStatus.STALE:
            st.status = TrackStatus.STALE
            st.confidence = 0.0
            return Decision(TrackStatus.STALE, "reset", 0.0, dec.frames_since_valid, st.last_valid_t,
                            ResetReason.STALE, dec.gap_frames)
        if st.status is TrackStatus.STALE:
            return Decision(TrackStatus.STALE, "none", 0.0, dec.frames_since_valid, st.last_valid_t,
                            dec.reset_reason, dec.gap_frames)
        return dec


__all__ = ["Decision", "MachineState", "StateMachineSettings", "TrackingStateMachine"]
