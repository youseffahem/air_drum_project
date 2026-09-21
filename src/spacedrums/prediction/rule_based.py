"""Baseline B — rule-based kinematic extrapolation (Phase 05, Task 05.2; README section 9 arm B).

Causal data flow (nothing after ``t_ref = history[-1].t_capture`` is ever read):

    TrackState history (filtered tip p, velocity v, acceleration a; status; confidence)
      -> kinematic state at t_ref            (this module; last ``N`` states only)
      -> K-step extrapolation                (CV: p + v k dt; CA: p + v k dt + 1/2 a (k dt)^2)
      -> TrajectoryPrediction                (positions[1..K] at t_ref + k dt_step, prefix = p at t_ref
                                              is added by geometry.intersect_prediction)
      -> geometry.intersect(..., RULE)       (Phase 04; the SAME impact definition as the reactive arm)
      -> StrikeCandidate(t_impact_pred, tti) -> commit policy (Phase 05, Task 05.3)

Coordinate convention: ROI-normalized ``[x, y]``, origin top-left, **y down** (ADR-0005); velocities in
ROI-norm/s, accelerations in ROI-norm/s^2. "Downward" therefore means increasing ``y``; the zone's
``inward_normal`` (geometry) — not this module — decides what counts as an approach.

Prediction lead time (sign convention, README section 5.4): ``L_pred = t_impact_est - t_commit``;
positive = the commit happened before the estimated impact. Time-to-impact carried by the candidate:
``tti = t_impact_pred - t_ref`` (README section 6). Neither is a latency; ``L_sys``, capture
latency and the frame period are separate quantities (README section 5.3).

Heuristic ``strike_probability`` (candidate form; monotone in every gate; documented, not tuned):

    speed_gate     = clip((|v| - speed_prob_lo) / (speed_prob_hi - speed_prob_lo), 0, 1)
    direction_gate = mean over the last m states of max(0, cos(angle(v_i, v_now)))   (1.0 if m = 1)
    validity_gate  = 1.0 if status == VALID else confidence (DEGRADED)
    probability    = product (default) or min of the three gates

Deterministic safeguards (all configurable, all PROVISIONAL until Phase 09/18 tune them on data):

    n_min_frames      minimum live history before predicting            (insufficient history)
    v_min_predict     |v| below this -> no prediction                    (stopped / low velocity)
    a_max             |a| above this -> no prediction                    (high acceleration / noisy)
    K, dt_step        bounded horizon H = K * dt_step                    (prediction horizon limit)
    zone validity, approach direction, one strike per episode            (geometry, Phase 04)
    hysteresis / refractory / duplicate suppression / confidence gate    (commit policy, Task 05.3)

CA needs an acceleration: ``ca_acceleration_source`` = ``state`` (``TrackState.tip_acceleration``, a
CA filter), ``finite_difference`` (``(v_now - v_prev) / dt`` from the last two states — causal), or
``state_or_finite_difference`` (default). Without any usable acceleration CA declines rather than
silently degrading to CV.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from spacedrums.contracts import TrackState, TrackStatus, TrajectoryAux, TrajectoryPrediction
from spacedrums.prediction.base import AnticipatorBase, DeclineReason
from spacedrums.timing import now

MOTION_MODELS = ("CV", "CA")
COMBINE_MODES = ("product", "min")
ACCELERATION_SOURCES = ("state", "finite_difference", "state_or_finite_difference")

Vec = tuple[float, float]


@dataclass(frozen=True)
class RuleSettings:
    """``anticipator`` config block + ``anticipator.rule.params`` (all values candidates)."""

    anticipator_id: str = "rule-cv-v1"
    motion_model: str = "CV"
    K: int = 6
    dt_step: float = 1.0 / 30.0
    n_min_frames: int = 2
    v_min_predict: float = 0.2
    a_max: float | None = 60.0
    direction_window_frames: int = 3
    speed_prob_lo: float = 0.2
    speed_prob_hi: float = 1.5
    combine: str = "product"
    ca_acceleration_source: str = "state_or_finite_difference"
    provisional: bool = True  # every threshold above is a playability candidate, not a tuned value
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.motion_model not in MOTION_MODELS:
            raise ValueError(f"motion_model must be one of {MOTION_MODELS}")
        if self.K < 1 or self.dt_step <= 0:
            raise ValueError("K >= 1 and dt_step > 0 required")
        if self.n_min_frames < 1 or self.direction_window_frames < 1:
            raise ValueError("n_min_frames and direction_window_frames must be >= 1")
        if self.v_min_predict < 0 or (self.a_max is not None and self.a_max <= 0):
            raise ValueError("v_min_predict >= 0 and a_max > 0 (or null) required")
        if not (0.0 <= self.speed_prob_lo < self.speed_prob_hi):
            raise ValueError("require 0 <= speed_prob_lo < speed_prob_hi")
        if self.combine not in COMBINE_MODES:
            raise ValueError(f"combine must be one of {COMBINE_MODES}")
        if self.ca_acceleration_source not in ACCELERATION_SOURCES:
            raise ValueError(f"ca_acceleration_source must be one of {ACCELERATION_SOURCES}")
        if self.extra:
            raise ValueError(f"unknown anticipator.rule.params keys: {sorted(self.extra)}")

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> RuleSettings:
        ant = cfg["anticipator"]
        if ant["type"] != "rule" or not ant.get("rule"):
            raise ValueError("RuleSettings.from_config needs anticipator.type = rule with a rule block")
        params = dict(ant["rule"].get("params") or {})
        known = {
            "n_min_frames",
            "v_min_predict",
            "a_max",
            "direction_window_frames",
            "speed_prob_lo",
            "speed_prob_hi",
            "combine",
            "ca_acceleration_source",
            "provisional",
        }
        kwargs = {k: params.pop(k) for k in list(params) if k in known}
        if "a_max" in kwargs and kwargs["a_max"] is not None:
            kwargs["a_max"] = float(kwargs["a_max"])
        return cls(
            anticipator_id=str(ant["anticipator_id"]),
            motion_model=str(ant["rule"]["motion_model"]),
            K=int(ant["K"]),
            dt_step=float(ant["dt_step_s"]),
            extra=params,
            **kwargs,
        )

    @property
    def horizon_s(self) -> float:
        return self.K * self.dt_step

    @property
    def n_window(self) -> int:
        """States actually read: the direction window, the finite-difference pair, the warm-up."""
        return max(self.direction_window_frames, 2, self.n_min_frames)

    def full_id(self) -> str:
        return f"{self.anticipator_id}:{self.motion_model.lower()}:K{self.K}:dt{self.dt_step:.4f}"


def _speed(v: Vec) -> float:
    return math.hypot(v[0], v[1])


def _cos(a: Vec, b: Vec) -> float | None:
    na, nb = _speed(a), _speed(b)
    if na <= 0.0 or nb <= 0.0:
        return None
    return (a[0] * b[0] + a[1] * b[1]) / (na * nb)


def speed_gate(speed: float, lo: float, hi: float) -> float:
    return min(1.0, max(0.0, (speed - lo) / (hi - lo)))


def direction_gate(velocities: tuple[Vec, ...]) -> float:
    """Mean of max(0, cos) between each windowed velocity and the current one; 1.0 with one sample."""
    if len(velocities) < 2:
        return 1.0
    v_now = velocities[-1]
    vals = [c for v in velocities[:-1] if (c := _cos(v, v_now)) is not None]
    if not vals:
        return 1.0
    return sum(max(0.0, c) for c in vals) / len(vals)


def validity_gate(state: TrackState) -> float:
    return 1.0 if state.status is TrackStatus.VALID else float(state.confidence)


def combine_gates(gates: tuple[float, ...], mode: str) -> float:
    if mode == "min":
        return min(gates)
    out = 1.0
    for g in gates:
        out *= g
    return min(1.0, max(0.0, out))


def extrapolate(p: Vec, v: Vec, a: Vec | None, k: int, dt: float) -> tuple[Vec, Vec]:
    """Position and velocity at ``k * dt`` after ``t_ref`` (CV when ``a`` is None, CA otherwise)."""
    tau = k * dt
    if a is None:
        return (p[0] + v[0] * tau, p[1] + v[1] * tau), v
    return (
        (p[0] + v[0] * tau + 0.5 * a[0] * tau * tau, p[1] + v[1] * tau + 0.5 * a[1] * tau * tau),
        (v[0] + a[0] * tau, v[1] + a[1] * tau),
    )


class RuleBasedAnticipator(AnticipatorBase):
    """``Anticipator`` implementation for arm B (``source = RULE``; ``model_hash = None``)."""

    def __init__(self, settings: RuleSettings, *, clock: Callable[[], float] = now) -> None:
        super().__init__(
            anticipator_id=settings.full_id(),
            n_window=settings.n_window,
            n_min=settings.n_min_frames,
            clock=clock,
        )
        self.settings = settings

    # -- kinematic state -------------------------------------------------------------------
    def kinematic_state(self, window: tuple[TrackState, ...]) -> tuple[Vec, Vec, Vec | None, float]:
        """(p, v, a | None, |v|) at ``t_ref`` from the causal window; ``a`` per the CA source rule."""
        latest = window[-1]
        p, v = latest.tip_filtered, latest.tip_velocity
        assert p is not None and v is not None
        a: Vec | None = None
        if self.settings.motion_model == "CA":
            src = self.settings.ca_acceleration_source
            if src in ("state", "state_or_finite_difference") and latest.tip_acceleration is not None:
                a = latest.tip_acceleration
            elif src in ("finite_difference", "state_or_finite_difference") and len(window) >= 2:
                prev = window[-2]
                dt = latest.t_capture - prev.t_capture
                assert prev.tip_velocity is not None and dt > 0
                a = ((v[0] - prev.tip_velocity[0]) / dt, (v[1] - prev.tip_velocity[1]) / dt)
        return p, v, a, _speed(v)

    def strike_probability(self, window: tuple[TrackState, ...]) -> float:
        s = self.settings
        latest = window[-1]
        assert latest.tip_velocity is not None
        vels = tuple(
            st.tip_velocity for st in window[-s.direction_window_frames :] if st.tip_velocity is not None
        )
        gates = (
            speed_gate(_speed(latest.tip_velocity), s.speed_prob_lo, s.speed_prob_hi),
            direction_gate(vels),
            validity_gate(latest),
        )
        return combine_gates(gates, s.combine)

    # -- prediction ------------------------------------------------------------------------
    def _predict_window(self, window: tuple[TrackState, ...]) -> TrajectoryPrediction | None:
        s = self.settings
        p, v, a, speed = self.kinematic_state(window)
        if speed < s.v_min_predict:
            return self._decline(DeclineReason.LOW_SPEED)
        if s.motion_model == "CA":
            if a is None:
                return self._decline(DeclineReason.NO_ACCELERATION)
            if s.a_max is not None and _speed(a) > s.a_max:
                return self._decline(DeclineReason.HIGH_ACCELERATION)
        latest = window[-1]
        steps = [extrapolate(p, v, a, k, s.dt_step) for k in range(1, s.K + 1)]
        return TrajectoryPrediction(
            frame_id=latest.frame_id,
            t_capture=latest.t_capture,
            hand_id=latest.hand_id,
            anticipator_id=self.anticipator_id,
            model_hash=None,
            K=s.K,
            dt_step=s.dt_step,
            t_offsets_s=None,
            positions=tuple(pos for pos, _ in steps),
            velocities=tuple(vel for _, vel in steps),
            uncertainty=None,
            uncertainty_kind=None,
            aux=TrajectoryAux(strike_prob_within_H=self.strike_probability(window)),
            t_inference_done=float(self.clock()),
        )


__all__ = [
    "ACCELERATION_SOURCES",
    "COMBINE_MODES",
    "MOTION_MODELS",
    "RuleBasedAnticipator",
    "RuleSettings",
    "combine_gates",
    "direction_gate",
    "extrapolate",
    "speed_gate",
    "validity_gate",
]
