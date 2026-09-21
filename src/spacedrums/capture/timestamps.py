"""``t_capture`` policies: driver-timestamp mapping and grab-return stamping (Task 02.2).

architecture.md section 5.2:

* ``DRIVER_MAPPED``: driver timestamps ``t_drv`` are mapped onto ``t_mono`` by a linear model
  ``t_capture = a + b * t_drv`` fitted over a warm-up window and re-estimated slowly.
* ``GRAB_RETURN``: ``t_capture = now() - bias_est`` at grab return, with ``bias_est`` the
  MEASURED capture-latency estimate of the camera profile (``grab_return_bias_s``), 0 until then.

Fitting detail (HW-01 finding, docs/camera-profile-hw01-integrated-webcam.md): the MSMF backend
reports ``CAP_PROP_POS_MSEC`` on the *same* QueryPerformanceCounter base as ``perf_counter``,
so the honest map is the identity. The mapper therefore first tests for a shared clock base
directly: if every raw lag ``t_grab - t_drv`` in the warm-up window lies within
``[-same_clock_neg_tol_s, same_clock_max_lag_s]`` (a foreign clock has an offset of seconds to
hours, a shared one only the hand-over lag), it uses ``a = 0, b = 1``
(``mode = IDENTITY_SAME_CLOCK``) without any slope fit: a least-squares slope on a short, bursty
window is noisy (observed 1.3e-3 on HW-01, i.e. 8 ms of drift over 6 s) and must not be trusted
for a same-clock backend. Otherwise it (1) fits the slope ``b`` by least squares over the window
once the window spans at least ``min_fit_span_s``, and (2) estimates the offset ``a`` from the
*earliest* observed hand-over lag (``min(t_grab - b * t_drv)``) rather than the mean, because
grab-return times can only be later than the capture instant and a mean would push ``t_capture``
towards the hand-over time. The residual it reports is the spread of ``t_grab - map(t_drv)``:
with an identity map that is the hand-over lag distribution, a MEASURED property of the backend,
not of the clock.

A non-monotone driver clock disables the mapping (``monotone = False``); the source then falls
back to ``GRAB_RETURN`` and records the fallback.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class LinearMap:
    a: float
    b: float
    mode: str  # IDENTITY_SAME_CLOCK | LEAST_SQUARES_MIN_LAG

    def __call__(self, t_drv: float) -> float:
        return self.a + self.b * t_drv


class DriverTimestampMapper:
    def __init__(
        self,
        *,
        warmup_n: int = 60,
        window_n: int = 900,
        refit_every: int = 150,
        same_clock_max_lag_s: float = 0.5,
        same_clock_neg_tol_s: float = 0.01,
        min_fit_span_s: float = 5.0,
    ) -> None:
        if warmup_n < 3:
            raise ValueError("warmup_n must be >= 3")
        self.warmup_n = warmup_n
        self.refit_every = max(1, refit_every)
        self.same_clock_max_lag_s = same_clock_max_lag_s
        self.same_clock_neg_tol_s = same_clock_neg_tol_s
        self.min_fit_span_s = min_fit_span_s
        self._pairs: deque[tuple[float, float]] = deque(maxlen=window_n)
        self._n_added = 0
        self._last_drv: float | None = None
        self.monotone = True
        self.map: LinearMap | None = None

    # -- feeding ---------------------------------------------------------------------------
    def add(self, t_drv: float, t_grab: float) -> None:
        if self._last_drv is not None and t_drv <= self._last_drv:
            self.monotone = False
        self._last_drv = t_drv
        self._pairs.append((float(t_drv), float(t_grab)))
        self._n_added += 1
        if self.monotone and self._n_added >= self.warmup_n and (
            self.map is None or (self._n_added - self.warmup_n) % self.refit_every == 0
        ):
            self.map = self.fit()

    @property
    def ready(self) -> bool:
        return self.map is not None and self.monotone

    @property
    def n_pairs(self) -> int:
        return len(self._pairs)

    # -- fitting ---------------------------------------------------------------------------
    def fit(self) -> LinearMap | None:
        if len(self._pairs) < 3 or not self.monotone:
            return None
        drv = np.array([p[0] for p in self._pairs])
        grab = np.array([p[1] for p in self._pairs])
        raw_lag = grab - drv
        if -self.same_clock_neg_tol_s <= raw_lag.min() and raw_lag.max() <= self.same_clock_max_lag_s:
            return LinearMap(a=0.0, b=1.0, mode="IDENTITY_SAME_CLOCK")
        span = float(drv[-1] - drv[0])
        if span < self.min_fit_span_s:
            return self.map  # keep the previous map (or none) until the window is long enough
        drv0 = drv - drv.mean()
        denom = float(np.dot(drv0, drv0))
        if denom <= 0:
            return self.map
        # least-squares slope on centred data (constant lags do not bias it)
        b = float(np.dot(drv0, grab - grab.mean()) / denom)
        min_lag = float((grab - b * drv).min())
        return LinearMap(a=min_lag, b=b, mode="LEAST_SQUARES_MIN_LAG")

    # -- use -------------------------------------------------------------------------------
    def to_mono(self, t_drv: float) -> float | None:
        if not self.ready:
            return None
        return self.map(t_drv)  # type: ignore[misc]

    def residual_stats(self) -> dict[str, Any]:
        """Spread of ``t_grab - map(t_drv)`` over the window (hand-over lag under identity)."""
        if self.map is None or not self._pairs:
            return {"n": 0, "mode": None, "a": None, "b": None, "monotone": self.monotone}
        drv = np.array([p[0] for p in self._pairs])
        grab = np.array([p[1] for p in self._pairs])
        r = grab - (self.map.a + self.map.b * drv)
        # slope-only fit residual (what a pure least-squares line would leave)
        drv0 = drv - drv.mean()
        b_ls = float(np.dot(drv0, grab - grab.mean()) / np.dot(drv0, drv0)) if drv0.any() else 1.0
        a_ls = float(grab.mean() - b_ls * drv.mean())
        r_ls = grab - (a_ls + b_ls * drv)
        return {
            "n": int(r.size),
            "mode": self.map.mode,
            "a": self.map.a,
            "b": self.map.b,
            "monotone": self.monotone,
            "lag_min_s": float(r.min()),
            "lag_p50_s": float(np.percentile(r, 50)),
            "lag_p95_s": float(np.percentile(r, 95)),
            "lag_max_s": float(r.max()),
            "lag_std_s": float(r.std()),
            "ls_slope": b_ls,
            "ls_slope_minus_1": b_ls - 1.0,
            "ls_residual_std_s": float(r_ls.std()),
            "ls_residual_p95_abs_s": float(np.percentile(np.abs(r_ls), 95)),
            "ls_residual_max_abs_s": float(np.abs(r_ls).max()),
        }


@dataclass(frozen=True)
class GrabReturnStamper:
    """``t_capture = t_grab_return - bias_s`` (bias 0 until Task 02.8 measures it)."""

    bias_s: float = 0.0

    def __post_init__(self) -> None:
        if self.bias_s < 0:
            raise ValueError("bias_s must be >= 0")

    def to_mono(self, t_grab_return: float) -> float:
        return t_grab_return - self.bias_s


__all__ = ["DriverTimestampMapper", "GrabReturnStamper", "LinearMap"]
