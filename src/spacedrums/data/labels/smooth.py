"""Offline **non-causal** reference smoother (Phase 07, Task 07.2).

This is the only component in the system that is allowed to look into the future, and it exists for
exactly one purpose: to produce the trajectory from which labels are constructed. The causal track
(``tracks_causal.jsonl``, a normal ``TrackState`` stream) is what a model may see; the reference
track (``tracks_reference.jsonl``) is what the labels are built from, and
``docs/architecture/causality-tests.md`` section 1.1 forbids it from ever reaching a ``Tracker``,
feature, ``Anticipator``, ``Geometry`` or ``CommitPolicy`` call.

Two candidate smoothers, both non-causal (phase document: "RTS smoother over the Kalman model, or
centred Savitzky-Golay; candidate choice by comparison to manual annotations"):

* ``rts-kalman-cv-v1`` / ``rts-kalman-ca-v1`` — Rauch-Tung-Striebel fixed-interval smoother over the
  **same** linear Kalman model the Phase 03 tracker uses (``spacedrums.tracking.filter``), so the
  reference differs from the causal track only by the backward pass, not by the motion model.
* ``savgol-centred-v1`` — centred Savitzky-Golay polynomial filter on the raw measurements, with
  the velocity taken from the analytic derivative of the fitted polynomial.

Gaps: a run of frames without a usable measurement shorter than ``max_gap_s`` is bridged (the
Kalman prediction carries the state across it and the samples are flagged ``interpolated``); a
longer gap ends the segment and is reported as a tracking-loss interval, which the rules turn into
a ``NEG_TRACKING_LOSS`` label (R8). No sample is ever invented across a long gap.

The smoother choice and its window are a **Decision That Must Be Experimentally Validated**
(phase document): the comparison against manual tip annotations near impacts needs recordings,
which do not exist yet. What is implemented and tested here is the machinery plus its behaviour on
synthetic signals with a known analytic answer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from spacedrums.data.labels.schema import SmootherId, sha256_obj

DEFAULT_KALMAN_PARAMS: dict[str, float] = {"q": 200.0, "r_base": 1e-4, "c_floor": 0.2,
                                           "p0_vel": 1.0, "p0_acc": 10.0}
"""Same model as the Phase 03 tracker filter but a **different** process noise, on purpose.

The tracker's ``q = 5.0`` is tuned for a *causal* filter that must reject measurement noise without
overshooting. As a *reference* smoother it over-smooths the velocity reversal at impact: on the
SYNTHETIC stroke set of ``scripts/reference_smoother_check.py`` it loses the surface entry
altogether on 7 of 24 strokes and biases the crossing time about +11 ms late. ``q = 200`` keeps
24/24 entries with a crossing-time bias below 1 ms (SYNTHETIC evidence; the final choice is a
Decision That Must Be Experimentally Validated against manual tip annotations near impacts, which
needs recordings - phase document, Task 07.2).
"""

DEFAULT_SAVGOL_PARAMS: dict[str, float] = {"window": 5.0, "polyorder": 2.0}
"""Window 5 at 30 FPS spans ~165 ms: a stroke's downward phase is ~150-200 ms, so a wider window
flattens the reversal (window 9 loses the entry on most SYNTHETIC strokes)."""


@dataclass(frozen=True)
class Measurement:
    """One raw tip measurement of a hand (from ``records/StickObservation.jsonl``)."""

    frame_id: int
    t: float
    p: tuple[float, float] | None
    confidence: float

    @property
    def present(self) -> bool:
        return self.p is not None


@dataclass(frozen=True)
class ReferenceSample:
    """One smoothed, non-causal sample. ``quality`` is a smoother posterior quality, never a
    ``TrackState.confidence``: the two are different estimators and must not be compared."""

    frame_id: int
    t: float
    p: tuple[float, float]
    v: tuple[float, float]
    quality: float
    interpolated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": int(self.frame_id),
            "t": float(self.t),
            "p": [float(self.p[0]), float(self.p[1])],
            "v": [float(self.v[0]), float(self.v[1])],
            "quality": float(self.quality),
            "interpolated": bool(self.interpolated),
        }


@dataclass(frozen=True)
class LossInterval:
    t_start: float
    t_end: float
    first_frame_id: int
    last_frame_id: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "t_start": float(self.t_start),
            "t_end": float(self.t_end),
            "first_frame_id": int(self.first_frame_id),
            "last_frame_id": int(self.last_frame_id),
        }


@dataclass(frozen=True)
class SmoothResult:
    samples: tuple[ReferenceSample, ...]
    loss_intervals: tuple[LossInterval, ...]
    method_id: str
    params: dict[str, Any]

    @property
    def smoother_hash(self) -> str:
        return sha256_obj({"method_id": self.method_id, "params": self.params})


class ReferenceSmoother:
    """Non-causal smoother over a hand's measurements. ``smooth`` consumes the WHOLE sequence."""

    def __init__(
        self,
        method_id: SmootherId | str = SmootherId.RTS_KALMAN_CV,
        *,
        params: dict[str, Any] | None = None,
        max_gap_s: float = 0.20,
    ) -> None:
        self.method_id = SmootherId(method_id)
        if max_gap_s <= 0:
            raise ValueError("max_gap_s must be > 0")
        self.max_gap_s = float(max_gap_s)
        defaults = (
            dict(DEFAULT_SAVGOL_PARAMS)
            if self.method_id is SmootherId.SAVGOL_CENTRED
            else dict(DEFAULT_KALMAN_PARAMS)
        )
        merged = {**defaults, **(params or {})}
        unknown = set(merged) - set(defaults)
        if unknown:
            raise ValueError(f"unknown smoother parameters for {self.method_id}: {sorted(unknown)}")
        self.params = {k: float(v) for k, v in merged.items()}
        if self.method_id is SmootherId.SAVGOL_CENTRED:
            window, order = int(self.params["window"]), int(self.params["polyorder"])
            if window < 3 or window % 2 == 0:
                raise ValueError("savgol window must be an odd integer >= 3")
            if not 1 <= order < window:
                raise ValueError("savgol polyorder must satisfy 1 <= polyorder < window")

    @property
    def smoother_id(self) -> str:
        return str(self.method_id)

    @property
    def smoother_hash(self) -> str:
        return sha256_obj({"method_id": str(self.method_id), "params": self.params,
                           "max_gap_s": self.max_gap_s})

    def describe(self) -> dict[str, Any]:
        return {"method_id": str(self.method_id), "params": dict(self.params),
                "max_gap_s": self.max_gap_s}

    # -- segmentation ----------------------------------------------------------------------

    def _segments(self, meas: Sequence[Measurement]) -> tuple[list[list[Measurement]], list[LossInterval]]:
        """Split at gaps longer than ``max_gap_s``; a bridged gap keeps its (absent) frames in the
        segment so the smoother can carry the state across them and flag them ``interpolated``."""
        segments: list[list[Measurement]] = []
        losses: list[LossInterval] = []
        current: list[Measurement] = []
        pending: list[Measurement] = []  # absent frames since the last present one
        last_present: Measurement | None = None
        for m in meas:
            if m.present:
                if last_present is not None and pending:
                    if m.t - last_present.t > self.max_gap_s:
                        segments.append(current)
                        losses.append(
                            LossInterval(last_present.t, m.t, pending[0].frame_id, pending[-1].frame_id)
                        )
                        current = []
                    else:
                        current += pending
                pending = []
                current.append(m)
                last_present = m
            else:
                pending.append(m)
        if current:
            segments.append(current)
        if last_present is not None and pending:
            losses.append(LossInterval(last_present.t, pending[-1].t, pending[0].frame_id,
                                       pending[-1].frame_id))
        if last_present is None and pending:
            losses.append(LossInterval(pending[0].t, pending[-1].t, pending[0].frame_id,
                                       pending[-1].frame_id))
        return [s for s in segments if s], losses

    # -- public ----------------------------------------------------------------------------

    def smooth(self, measurements: Sequence[Measurement]) -> SmoothResult:
        meas = list(measurements)
        for a, b in zip(meas, meas[1:], strict=False):
            if b.t <= a.t:
                raise ValueError("measurement times must be strictly increasing")
        segments, losses = self._segments(meas)
        samples: list[ReferenceSample] = []
        for seg in segments:
            present = [m for m in seg if m.present]
            if len(present) < 2:
                continue
            if self.method_id is SmootherId.SAVGOL_CENTRED:
                samples += self._savgol(seg)
            else:
                samples += self._rts(seg)
        samples.sort(key=lambda s: s.t)
        return SmoothResult(tuple(samples), tuple(losses), str(self.method_id), self.describe())

    # -- RTS over the Phase 03 Kalman model -------------------------------------------------

    def _rts(self, seg: Sequence[Measurement]) -> list[ReferenceSample]:
        """Forward Kalman + backward Rauch-Tung-Striebel pass over the constant-velocity (order 1)
        or constant-acceleration (order 2) model of ``spacedrums.tracking.filter``.

        The backward pass is what makes this non-causal: sample ``k`` is conditioned on every
        measurement of the segment, including those after ``t_k``.
        """
        order = 2 if self.method_id is SmootherId.RTS_KALMAN_CA else 1
        n = order + 1
        dim = 2 * n
        q, r_base = self.params["q"], self.params["r_base"]
        c_floor = self.params["c_floor"]
        H = np.zeros((2, dim))
        H[0, 0], H[1, n] = 1.0, 1.0

        def FQ(dt: float) -> tuple[np.ndarray, np.ndarray]:
            if order == 1:
                f = np.array([[1.0, dt], [0.0, 1.0]])
                qb = q * np.array([[dt**3 / 3, dt**2 / 2], [dt**2 / 2, dt]])
            else:
                f = np.array([[1.0, dt, dt**2 / 2], [0.0, 1.0, dt], [0.0, 0.0, 1.0]])
                qb = q * np.array([[dt**5 / 20, dt**4 / 8, dt**3 / 6],
                                   [dt**4 / 8, dt**3 / 3, dt**2 / 2],
                                   [dt**3 / 6, dt**2 / 2, dt]])
            F = np.zeros((dim, dim))
            Q = np.zeros((dim, dim))
            F[:n, :n] = f
            F[n:, n:] = f
            Q[:n, :n] = qb
            Q[n:, n:] = qb
            return F, Q

        first = next(m for m in seg if m.present)
        x = np.zeros(dim)
        x[0], x[n] = first.p[0], first.p[1]
        diag = [r_base, self.params["p0_vel"]] + ([self.params["p0_acc"]] if order == 2 else [])
        P = np.diag(diag * 2).astype(float)

        xs_pred: list[np.ndarray] = []
        Ps_pred: list[np.ndarray] = []
        xs_filt: list[np.ndarray] = []
        Ps_filt: list[np.ndarray] = []
        Fs: list[np.ndarray] = []
        start = seg.index(first)
        used = list(seg[start:])
        for k, m in enumerate(used):
            if k == 0:
                F = np.eye(dim)
            else:
                dt = m.t - used[k - 1].t
                F, Q = FQ(dt)
                x = F @ x
                P = F @ P @ F.T + Q
            Fs.append(F)
            xs_pred.append(x.copy())
            Ps_pred.append(P.copy())
            if m.present:
                r = r_base / max(c_floor, float(m.confidence))
                R = np.eye(2) * r
                y = np.asarray(m.p, float) - H @ x
                S = H @ P @ H.T + R
                K = P @ H.T @ np.linalg.inv(S)
                x = x + K @ y
                I_KH = np.eye(dim) - K @ H
                P = I_KH @ P @ I_KH.T + K @ R @ K.T
            xs_filt.append(x.copy())
            Ps_filt.append(P.copy())

        # Backward RTS pass: this is the future information the labels are allowed to use.
        xs_sm = [a.copy() for a in xs_filt]
        Ps_sm = [a.copy() for a in Ps_filt]
        for k in range(len(used) - 2, -1, -1):
            F = Fs[k + 1]
            P_pred = Ps_pred[k + 1]
            try:
                C = Ps_filt[k] @ F.T @ np.linalg.inv(P_pred)
            except np.linalg.LinAlgError:  # pragma: no cover - singular covariance
                continue
            xs_sm[k] = xs_filt[k] + C @ (xs_sm[k + 1] - xs_pred[k + 1])
            Ps_sm[k] = Ps_filt[k] + C @ (Ps_sm[k + 1] - P_pred) @ C.T

        out: list[ReferenceSample] = []
        for k, m in enumerate(used):
            xk, Pk = xs_sm[k], Ps_sm[k]
            var = max(float(Pk[0, 0] + Pk[n, n]), 0.0)
            out.append(
                ReferenceSample(
                    frame_id=m.frame_id,
                    t=m.t,
                    p=(float(xk[0]), float(xk[n])),
                    v=(float(xk[1]), float(xk[n + 1])),
                    quality=_quality_from_variance(var),
                    interpolated=not m.present,
                )
            )
        return out

    # -- centred Savitzky-Golay --------------------------------------------------------------

    def _savgol(self, seg: Sequence[Measurement]) -> list[ReferenceSample]:
        """Centred polynomial fit over a symmetric window; near the ends the window is truncated
        symmetrically so the filter stays centred (never one-sided, which would be causal-ish and
        would bias the crossing time)."""
        present = [m for m in seg if m.present]
        window, order = int(self.params["window"]), int(self.params["polyorder"])
        ts = np.array([m.t for m in present], float)
        xs = np.array([m.p[0] for m in present], float)
        ys = np.array([m.p[1] for m in present], float)
        half = window // 2
        out: list[ReferenceSample] = []
        index_of = {m.frame_id: k for k, m in enumerate(present)}
        for m in seg:
            if m.frame_id not in index_of:
                continue
            i = index_of[m.frame_id]
            h = min(half, i, len(present) - 1 - i)
            if h < 1:
                p = (float(xs[i]), float(ys[i]))
                nb = min(i + 1, len(present) - 1)
                dt = ts[nb] - ts[i] if nb != i else 1.0
                v = ((xs[nb] - xs[i]) / dt, (ys[nb] - ys[i]) / dt) if nb != i else (0.0, 0.0)
                out.append(ReferenceSample(m.frame_id, m.t, p, v, 0.5, False))
                continue
            sl = slice(i - h, i + h + 1)
            tau = ts[sl] - ts[i]
            deg = min(order, 2 * h)
            cx = np.polyfit(tau, xs[sl], deg)
            cy = np.polyfit(tau, ys[sl], deg)
            p = (float(np.polyval(cx, 0.0)), float(np.polyval(cy, 0.0)))
            v = (float(np.polyval(np.polyder(cx), 0.0)), float(np.polyval(np.polyder(cy), 0.0)))
            resid = float(np.mean((xs[sl] - np.polyval(cx, tau)) ** 2 + (ys[sl] - np.polyval(cy, tau)) ** 2))
            out.append(ReferenceSample(m.frame_id, m.t, p, v,
                                       _quality_from_variance(resid), False))
        return out


SIGMA_UNUSABLE = 0.05
"""Posterior position standard deviation (ROI-normalized) at which a label is worthless.

5 % of the ROI is about 28 px horizontally on the HW-01 ROI - an impact position that uncertain
says nothing about which zone was struck or when. The scale is a candidate, and it is an absolute
position scale on purpose: a *relative* quality (posterior variance over measurement variance)
would sit near 0.5 for every setting of this smoother and would carry no information.
"""


def _quality_from_variance(var: float, sigma_unusable: float = SIGMA_UNUSABLE) -> float:
    """Map a posterior position variance to a [0, 1] quality: 1 at zero uncertainty, 0 at
    ``sigma_unusable`` standard deviation.

    A monotone summary for rule R7. It is a *quality of the reference trajectory*, not a
    probability that a strike happened, and it is never compared with a ``TrackState.confidence``:
    the two come from different estimators.
    """
    sd = math.sqrt(max(float(var), 0.0))
    return float(min(1.0, max(0.0, 1.0 - sd / max(sigma_unusable, 1e-12))))


def resample(samples: Sequence[ReferenceSample], t: float) -> ReferenceSample | None:
    """Linear interpolation of the reference trajectory at ``t`` (used for event windows).

    Returns ``None`` outside the sampled range; never extrapolates.
    """
    if len(samples) < 2 or t < samples[0].t or t > samples[-1].t:
        return None
    for a, b in zip(samples, samples[1:], strict=False):
        if a.t <= t <= b.t:
            span = b.t - a.t
            u = 0.0 if span <= 0 else (t - a.t) / span
            return ReferenceSample(
                frame_id=a.frame_id if u < 0.5 else b.frame_id,
                t=t,
                p=(a.p[0] + u * (b.p[0] - a.p[0]), a.p[1] + u * (b.p[1] - a.p[1])),
                v=(a.v[0] + u * (b.v[0] - a.v[0]), a.v[1] + u * (b.v[1] - a.v[1])),
                quality=a.quality + u * (b.quality - a.quality),
                interpolated=a.interpolated or b.interpolated,
            )
    return None  # pragma: no cover - covered by the range test above


def speed(sample: ReferenceSample) -> float:
    return math.hypot(sample.v[0], sample.v[1])


__all__ = [
    "DEFAULT_KALMAN_PARAMS",
    "DEFAULT_SAVGOL_PARAMS",
    "LossInterval",
    "Measurement",
    "ReferenceSample",
    "ReferenceSmoother",
    "SIGMA_UNUSABLE",
    "SmoothResult",
    "resample",
    "speed",
]
