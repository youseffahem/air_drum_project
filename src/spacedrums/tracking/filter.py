"""Per-hand causal filters (Phase 03, Task 03.12): alpha-beta, Kalman CV, Kalman CA, scalar angle.

All filters: 2-D position measurement (ROI-normalized) with **confidence-scaled measurement
noise**, variable ``dt`` from ``t_capture``, outputs position / velocity / acceleration, plus a
``predict_only(dt)`` step used by the DEGRADED bridge (no observation invented: the state is
propagated, never updated). Every parameter is a tunable candidate (``tracking.filter.params``).

Memory: none of these filters has a finite hard window — a Kalman/alpha-beta state depends on all
past measurements with geometrically decaying weight. For ``TEST-CAUSAL-2`` each filter therefore
declares an **effective window** ``N_eff`` (frames after a cold start on the window at which the
truncated run agrees with the reference within the declared tolerance); ``effective_window_frames``
simulates it from the filter's own linear error dynamics at the lowest confidence gain, starting
from the declared initial error bounds ``V_ERR_BOUND`` / ``A_ERR_BOUND`` (``tests/tracking/test_causal.py``
measures the actual deviation and fails if the declaration is too small).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

MAX_N_EFF = 2000  # cap of the declared effective window (frames)
DECL_WARM = 300  # frames the long-running instance has seen before the cold start
DECL_PERSIST = 30  # frames of continued agreement required before N_eff is accepted


def _declaration_sequence(dt: float, n: int) -> list[tuple[float, float]]:
    """Deterministic SYNTHETIC measurements for the N_eff declaration: a parabola with strong
    acceleration and sigma = 0.01 noise (seeded), i.e. a harsher sequence than a stick swing."""
    rng = np.random.default_rng(12345)
    out = []
    for k in range(n):
        t = k * dt
        x = 0.2 + 0.6 * t + 1.0 * t * t * 0.5
        y = 0.8 - 1.2 * t + 4.0 * t * t * 0.5
        x, y = x % 1.0, y % 1.0  # keep inside the ROI range (a wrap is just a jump: harsher, not gentler)
        out.append((x + rng.normal(0, 0.01), y + rng.normal(0, 0.01)))
    return out


@dataclass(frozen=True)
class FilterOutput:
    pos: tuple[float, float]
    vel: tuple[float, float]
    acc: tuple[float, float] | None


class _Filter2D:
    filter_id = "base"

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = dict(params)
        self.initialised = False

    def reset(self) -> None:
        self.initialised = False

    def initialise(self, z: tuple[float, float]) -> FilterOutput:
        raise NotImplementedError

    def predict(self, dt: float) -> FilterOutput:
        raise NotImplementedError

    def update(self, z: tuple[float, float], confidence: float) -> FilterOutput:
        raise NotImplementedError

    def output(self) -> FilterOutput:
        raise NotImplementedError

    def clone(self) -> _Filter2D:
        return make_filter(self.filter_id, self.params)

    def effective_window_frames(self, tolerance: float, dt: float, margin: float = 1.5) -> int:
        """Declared ``N_eff`` for TEST-CAUSAL-2: frames after a cold start until this filter agrees
        with a long-running instance within ``tolerance`` (position; velocity x dt; acceleration x dt^2)
        and stays there, on a deterministic SYNTHETIC measurement sequence at the **lowest**
        confidence (``c_floor``: smallest gains, slowest convergence of both state and covariance).
        ``margin`` inflates the measured count (the test measures the real deviation and fails if
        the declaration is still too small).
        """
        c = float(getattr(self, "c_floor", 0.2))
        z = _declaration_sequence(dt, DECL_WARM + MAX_N_EFF)
        warm = self.clone()
        cold = self.clone()
        warm.initialise(z[0])
        for k in range(1, DECL_WARM):
            warm.predict(dt)
            warm.update(z[k], c)
        cold.initialise(z[DECL_WARM - 1])
        warm.predict(dt)
        warm.update(z[DECL_WARM - 1], c)  # both now at the same frame
        agree_since: int | None = None
        for k in range(1, MAX_N_EFF):
            zk = z[DECL_WARM - 1 + k]
            warm.predict(dt)
            a = warm.update(zk, c)
            cold.predict(dt)
            b = cold.update(zk, c)
            dev = max(abs(a.pos[0] - b.pos[0]), abs(a.pos[1] - b.pos[1]),
                      abs(a.vel[0] - b.vel[0]) * dt, abs(a.vel[1] - b.vel[1]) * dt)
            if a.acc is not None and b.acc is not None:
                dev = max(dev, abs(a.acc[0] - b.acc[0]) * dt * dt, abs(a.acc[1] - b.acc[1]) * dt * dt)
            if dev <= tolerance:
                if agree_since is None:
                    agree_since = k
                if k - agree_since >= DECL_PERSIST:
                    return min(MAX_N_EFF, int(math.ceil(agree_since * margin)))
            else:
                agree_since = None
        return MAX_N_EFF


class AlphaBetaFilter(_Filter2D):
    """x += v dt; r = z - x; x += a_eff r; v += b_eff r / dt with a_eff = alpha * g(c), b_eff = beta * g(c).

    ``g(c) = clip(c / c_ref, c_floor, 1)``: a low-confidence measurement moves the state less
    (the confidence-scaled-noise analogue for a fixed-gain filter). Acceleration = finite
    difference of the velocity estimate over the last step.
    """

    filter_id = "alpha_beta"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.alpha = float(params.get("alpha", 0.6))
        self.beta = float(params.get("beta", 0.3))
        self.c_ref = float(params.get("c_ref", 1.0))
        self.c_floor = float(params.get("c_floor", 0.2))
        if not (0 < self.alpha <= 1) or not (0 <= self.beta <= 2) or not (0 < self.c_floor <= 1):
            raise ValueError("alpha in (0,1], beta in [0,2], c_floor in (0,1] required")
        self.x = np.zeros(2)
        self.v = np.zeros(2)
        self.a = np.zeros(2)

    def initialise(self, z):
        self.x = np.asarray(z, float).copy()
        self.v = np.zeros(2)
        self.a = np.zeros(2)
        self.initialised = True
        return self.output()

    def predict(self, dt):
        self.x = self.x + self.v * dt
        self._dt = dt
        return self.output()

    def update(self, z, confidence):
        g = min(1.0, max(self.c_floor, confidence / self.c_ref))
        r = np.asarray(z, float) - self.x
        dt = max(self._dt, 1e-6) if hasattr(self, "_dt") else 1e-6
        v_old = self.v.copy()
        self.x = self.x + self.alpha * g * r
        self.v = self.v + self.beta * g * r / dt
        self.a = (self.v - v_old) / dt
        return self.output()

    def output(self):
        return FilterOutput(pos=(float(self.x[0]), float(self.x[1])),
                            vel=(float(self.v[0]), float(self.v[1])),
                            acc=(float(self.a[0]), float(self.a[1])))



class KalmanFilter2D(_Filter2D):
    """Linear Kalman filter, constant-velocity (``order=1``) or constant-acceleration (``order=2``).

    State per axis: [p, v] or [p, v, a]; process noise = white-noise jerk/acceleration model with
    intensity ``q``; measurement noise ``R = r_base / max(confidence, c_floor)``.
    """

    def __init__(self, params: dict[str, Any], order: int) -> None:
        super().__init__(params)
        self.order = order
        self.q = float(params.get("q", 5.0))  # process noise intensity (ROI-norm units^2 / s^(2k-1))
        self.r_base = float(params.get("r_base", 1e-4))  # measurement variance at confidence 1
        self.c_floor = float(params.get("c_floor", 0.2))
        self.p0_vel = float(params.get("p0_vel", 1.0))  # initial velocity variance
        self.p0_acc = float(params.get("p0_acc", 10.0))
        if self.q <= 0 or self.r_base <= 0 or not (0 < self.c_floor <= 1):
            raise ValueError("q > 0, r_base > 0, c_floor in (0,1] required")
        n = order + 1
        self.n = n
        self.x = np.zeros(2 * n)
        self.P = np.eye(2 * n)
        self.H = np.zeros((2, 2 * n))
        self.H[0, 0] = 1.0
        self.H[1, n] = 1.0

    @property
    def filter_id(self) -> str:  # type: ignore[override]
        return "kalman_cv" if self.order == 1 else "kalman_ca"

    def _F_Q(self, dt: float) -> tuple[np.ndarray, np.ndarray]:
        n = self.n
        if self.order == 1:
            f = np.array([[1.0, dt], [0.0, 1.0]])
            qb = self.q * np.array([[dt**3 / 3, dt**2 / 2], [dt**2 / 2, dt]])
        else:
            f = np.array([[1.0, dt, dt**2 / 2], [0.0, 1.0, dt], [0.0, 0.0, 1.0]])
            qb = self.q * np.array([[dt**5 / 20, dt**4 / 8, dt**3 / 6],
                                    [dt**4 / 8, dt**3 / 3, dt**2 / 2],
                                    [dt**3 / 6, dt**2 / 2, dt]])
        F = np.zeros((2 * n, 2 * n))
        Q = np.zeros((2 * n, 2 * n))
        F[:n, :n] = f
        F[n:, n:] = f
        Q[:n, :n] = qb
        Q[n:, n:] = qb
        return F, Q

    def initialise(self, z):
        n = self.n
        self.x = np.zeros(2 * n)
        self.x[0], self.x[n] = float(z[0]), float(z[1])
        diag = [self.r_base, self.p0_vel] + ([self.p0_acc] if self.order == 2 else [])
        self.P = np.diag(diag * 2).astype(float)
        self.initialised = True
        return self.output()

    def predict(self, dt):
        F, Q = self._F_Q(dt)
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q
        return self.output()

    def update(self, z, confidence):
        r = self.r_base / max(self.c_floor, float(confidence))
        R = np.eye(2) * r
        y = np.asarray(z, float) - self.H @ self.x
        S = self.H @ self.P @ self.H.T + R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        I_KH = np.eye(2 * self.n) - K @ self.H
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T  # Joseph form: symmetric, positive
        return self.output()

    def output(self):
        n = self.n
        pos = (float(self.x[0]), float(self.x[n]))
        vel = (float(self.x[1]), float(self.x[n + 1]))
        acc = (float(self.x[2]), float(self.x[n + 2])) if self.order == 2 else None
        return FilterOutput(pos=pos, vel=vel, acc=acc)



class ScalarAngleFilter:
    """Alpha-beta on an angle with wrap-around (angles are equivalent mod pi for an unoriented axis
    but the stick axis is oriented, so the period is 2*pi); outputs angle and angular velocity."""

    def __init__(self, alpha: float = 0.6, beta: float = 0.3) -> None:
        self.alpha, self.beta = float(alpha), float(beta)
        self.theta: float | None = None
        self.omega = 0.0

    def reset(self) -> None:
        self.theta, self.omega = None, 0.0

    @staticmethod
    def wrap(a: float) -> float:
        return (a + math.pi) % (2 * math.pi) - math.pi

    def step(self, z: float | None, dt: float, confidence: float = 1.0) -> tuple[float | None, float | None]:
        if self.theta is None:
            if z is None:
                return None, None
            self.theta, self.omega = float(z), 0.0
            return self.theta, self.omega
        pred = self.theta + self.omega * dt
        if z is None:
            self.theta = self.wrap(pred)
            return self.theta, self.omega
        r = self.wrap(float(z) - pred)
        g = min(1.0, max(0.2, confidence))
        self.theta = self.wrap(pred + self.alpha * g * r)
        self.omega = self.omega + self.beta * g * r / max(dt, 1e-6)
        return self.theta, self.omega


FILTER_TYPES = ("alpha_beta", "kalman_cv", "kalman_ca")


def make_filter(filter_type: str, params: dict[str, Any] | None = None) -> _Filter2D:
    """Factory by ``tracking.filter.type`` (Pending Benchmark -> ADR-0016)."""
    params = params or {}
    if filter_type == "alpha_beta":
        return AlphaBetaFilter(params)
    if filter_type == "kalman_cv":
        return KalmanFilter2D(params, order=1)
    if filter_type == "kalman_ca":
        return KalmanFilter2D(params, order=2)
    raise ValueError(f"unknown filter type {filter_type!r}; candidates {FILTER_TYPES}")


@dataclass
class FilterBenchmarkResult:
    """Lag / RMSE of one filter on one synthetic trajectory (Task 03.12 evidence, labelled synthetic)."""

    filter_id: str
    rmse_pos: float
    rmse_vel: float
    lag_frames: float  # cross-correlation lag of the filtered position vs the truth
    extras: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "FILTER_TYPES",
    "AlphaBetaFilter",
    "FilterBenchmarkResult",
    "FilterOutput",
    "KalmanFilter2D",
    "ScalarAngleFilter",
    "make_filter",
]
