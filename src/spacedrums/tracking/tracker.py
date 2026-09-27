"""``CausalTracker``: the ``Tracker`` implementation (Phase 03, Tasks 03.12 + 03.13).

One instance per hand (ADR-0006). ``update(hand_obs, stick_obs, t_capture)`` receives only the
current observations and the tracker's own state — there is no look-ahead argument and no buffer
of later frames (causality rule). Per frame:

1. ``dt = t_capture - t_prev`` (variable; from the frames' ``t_capture``).
2. The state machine decides ``VALID / DEGRADED / INVALID / STALE`` and the filter action.
3. Filter: ``init`` from the observation, ``update`` with confidence-scaled noise, ``predict`` only
   (DEGRADED bridge: existing state propagated, nothing invented), or ``reset``.
4. Axis angle (image-plane, aspect-corrected) and angular velocity through a scalar filter.
5. Exactly one ``TrackState`` is emitted and appended to the causal history window (``history_n``,
   oldest first, all ``t_capture <=`` current); ``INVALID``/``STALE`` states carry null kinematics
   and the history is cleared on every reset (reset matrix, architecture.md 6.2).

``TrackReset`` events (hand, t, reason) are collected in ``resets`` for logging. Confidence in the
emitted state is the observation's ``tip_confidence`` (VALID / DEGRADED with observation), the
decayed bridge confidence, or 0.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from spacedrums.contracts import (
    HandId,
    HandObservation,
    HistoryRef,
    ResetReason,
    StickObservation,
    TrackState,
    TrackStatus,
)
from spacedrums.tracking.filter import ScalarAngleFilter, make_filter
from spacedrums.tracking.state_machine import StateMachineSettings, TrackingStateMachine


@dataclass(frozen=True)
class TrackReset:
    hand_id: HandId
    t: float
    reason: ResetReason
    frame_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"hand_id": str(self.hand_id), "t": self.t, "reason": str(self.reason),
                "frame_id": self.frame_id}


@dataclass(frozen=True)
class TrackerSettings:
    tracker_id: str = "causal-tracker"
    filter_type: str = "kalman_cv"
    filter_params: dict[str, Any] = field(default_factory=dict)
    machine: StateMachineSettings = StateMachineSettings()
    history_n: int = 16
    roi_aspect: float = 1.0  # w / h of the ROI: converts normalized axis_dir to an image-plane angle
    angle_alpha: float = 0.6
    angle_beta: float = 0.3
    causal_tolerance: float = 1e-6  # declared TEST-CAUSAL-2 tolerance (ROI-norm units) for N_eff
    # Phase 17 (ADR-0040): a frame interval above this is a tracking gap (None disables the rule).
    # Derived, not a new tunable: (g_max_frames + 1.5) nominal frame periods, i.e. more than g_max
    # frames missing at the requested rate. Not part of ``tracker_id`` (derived from g_max + fps).
    max_frame_gap_s: float | None = None

    def __post_init__(self) -> None:
        if self.history_n < 1:
            raise ValueError("history_n >= 1")
        if self.roi_aspect <= 0:
            raise ValueError("roi_aspect > 0")

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> TrackerSettings:
        tr = cfg["tracking"]
        params = dict(tr["filter"].get("params", {}))
        roi = cfg.get("roi", {}).get("px")
        aspect = (roi[2] / roi[3]) if roi else 1.0
        fps = (cfg.get("camera_profile") or {}).get("requested_fps")
        machine = StateMachineSettings.from_config(tr)
        return cls(tracker_id=str(tr["tracker_id"]), filter_type=str(tr["filter"]["type"]),
                   filter_params=params, machine=machine,
                   history_n=int(tr["history_n"]), roi_aspect=float(aspect),
                   angle_alpha=float(params.get("angle_alpha", 0.6)),
                   angle_beta=float(params.get("angle_beta", 0.3)),
                   causal_tolerance=float(params.get("causal_tolerance", 1e-6)),
                   max_frame_gap_s=(machine.g_max_frames + 1.5) / float(fps) if fps else None)

    def full_id(self) -> str:
        m = self.machine
        p = "-".join(f"{k}{v}" for k, v in sorted(self.filter_params.items())
                     if k not in ("bridge_decay", "acquire_on_degraded", "angle_alpha", "angle_beta",
                                  "causal_tolerance"))
        return (f"{self.tracker_id}:{self.filter_type}{(':' + p) if p else ''}:cv{m.c_valid:.2f}"
                f":cm{m.c_min:.2f}:g{m.g_max_frames}:age{m.age_max_s:.2f}:N{self.history_n}")


class CausalTracker:
    """Implements ``spacedrums.contracts.Tracker`` for one hand."""

    def __init__(self, hand_id: HandId | str, settings: TrackerSettings) -> None:
        self.hand_id = HandId(hand_id)
        self.settings = settings
        self.tracker_id = settings.full_id()
        self.filter = make_filter(settings.filter_type, settings.filter_params)
        self.angle = ScalarAngleFilter(settings.angle_alpha, settings.angle_beta)
        self.machine = TrackingStateMachine(settings.machine)
        self._history: deque[TrackState] = deque(maxlen=settings.history_n)
        self._t_prev: float | None = None
        self.resets: list[TrackReset] = []
        self.frames = 0
        self.gap_resets = 0

    # -- Tracker protocol ------------------------------------------------------------------
    @property
    def history(self) -> Sequence[TrackState]:
        return tuple(self._history)

    def reset(self, reason: ResetReason) -> None:
        self.machine.reset(reason)
        self.filter.reset()
        self.angle.reset()
        self._history.clear()
        self._t_prev = None
        self.resets.append(TrackReset(self.hand_id, float("nan"), reason))

    def declared_history(self, dt: float = 1 / 30) -> dict[str, Any]:
        """``N`` (config) and the filter's effective window at the declared tolerance (TEST-CAUSAL-2)."""
        n_eff = self.filter.effective_window_frames(self.settings.causal_tolerance, dt)
        return {"N": self.settings.history_n, "N_eff": int(n_eff), "N_min": 1,
                "tolerance": self.settings.causal_tolerance, "dt_assumed_s": dt}

    def update(self, hand_obs: HandObservation, stick_obs: StickObservation, t_capture: float) -> TrackState:
        if hand_obs.hand_id is not self.hand_id or stick_obs.hand_id is not self.hand_id:
            raise ValueError(f"tracker for {self.hand_id} received observations for another hand")
        self.frames += 1
        dt = (t_capture - self._t_prev) if self._t_prev is not None else 0.0
        if dt < 0:
            raise ValueError("t_capture must be non-decreasing (frames processed in order)")
        gap = self.settings.max_frame_gap_s
        if gap is not None and self._t_prev is not None and dt > gap and \
                self.machine.state.status in (TrackStatus.VALID, TrackStatus.DEGRADED):
            # Phase 17: too long without a frame to bridge - reset now, re-acquire below if possible
            self.machine.expire(ResetReason.GAP_EXCEEDED)
            self.filter.reset()
            self.angle.reset()
            self._history.clear()
            self.resets.append(TrackReset(self.hand_id, t_capture, ResetReason.GAP_EXCEEDED,
                                          hand_obs.frame_id))
            self.gap_resets += 1
        self._t_prev = t_capture
        has_obs = bool(stick_obs.present and stick_obs.tip is not None)
        conf = float(stick_obs.tip_confidence) if has_obs else 0.0
        dec = self.machine.step(t_capture, has_obs, conf)

        pos = vel = acc = None
        if dec.action == "init":
            out = self.filter.initialise(stick_obs.tip)
            self.angle.reset()
            self._history.clear()
        elif dec.action == "update":
            self.filter.predict(dt if dt > 0 else 1e-6)
            out = self.filter.update(stick_obs.tip, conf)
        elif dec.action == "predict":
            out = self.filter.predict(dt if dt > 0 else 1e-6)
        else:  # reset | none
            out = None
            if dec.action == "reset":
                self.filter.reset()
                self.angle.reset()
                self._history.clear()
                if dec.reset_reason is not None:
                    self.resets.append(TrackReset(self.hand_id, t_capture, dec.reset_reason,
                                                  hand_obs.frame_id))
        angle = omega = None
        if out is not None:
            pos, vel = out.pos, out.vel
            acc = out.acc
            z_angle = None
            if has_obs and stick_obs.axis_dir is not None and dec.action in ("init", "update"):
                dx, dy = stick_obs.axis_dir
                z_angle = math.atan2(dy, dx * self.settings.roi_aspect)
            angle, omega = self.angle.step(z_angle, dt if dt > 0 else 1e-6, conf if has_obs else 1.0)

        live = dec.status in (TrackStatus.VALID, TrackStatus.DEGRADED)
        state = TrackState(
            frame_id=hand_obs.frame_id, t_capture=t_capture, hand_id=self.hand_id, status=dec.status,
            tracker_id=self.tracker_id, tip_method=stick_obs.method_id,
            tip_filtered=pos if live else None, tip_velocity=vel if live else None,
            tip_acceleration=acc if live else None,
            axis_angle=angle if live else None, axis_angular_velocity=omega if live else None,
            confidence=dec.confidence if live else 0.0,
            frames_since_valid=dec.frames_since_valid,
            last_valid_t=dec.last_valid_t,
            history_ref=(HistoryRef(len(self._history), self._history[0].frame_id if self._history else None)
                         if live else None),
            reset_reason=dec.reset_reason,
        )
        if live:
            self._history.append(state)
        return state


__all__ = ["CausalTracker", "TrackReset", "TrackerSettings"]
