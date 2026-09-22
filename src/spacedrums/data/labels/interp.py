"""Sub-frame crossing estimators and their comparison (Phase 07, Task 07.4).

Phase 04 estimates the crossing instant by **linear** interpolation between the two frames that
bracket the crossing (``spacedrums.geometry.impact.crossing_time``) and left the choice Pending.
This module adds the **quadratic** alternative and the paired comparison that decides which one
``t_impact_est`` uses (ADR-0020). Nothing here changes Phase 04: the live pipeline keeps calling
``geometry.crossing_time``; only the offline label generator may select an estimator.

Definition of the quantity being interpolated. Let ``d(t)`` be the signed distance of the tip to
the zone impact surface, positive outside the zone and negative inside (``rules.signed_distance_to_surface``).
An impact is a zero of ``d``. The linear estimator takes the zero of the straight line through the
two bracketing samples; the quadratic estimator fits a parabola through three samples centred on
the bracket and takes the root inside the bracket. On a constant-acceleration approach - which is
what a drum stroke is near the surface - the parabola is exact and the line is biased late by
approximately ``a * dt^2 / (8 * |v|)``.

Decision rule, **declared before any result was inspected** (phase document, Experimental Design):

    Choose the estimator with the smaller spread (IQR of the signed error against the best
    available reference). If the two spreads are within 10 % of each other, choose the one with
    the smaller |bias|. If both are within 10 %, keep LINEAR, because it is what Phase 04 already
    implements and the simpler estimator carries fewer assumptions.

The "best available reference" is, in order of preference: (1) the acoustic onset
``t_impact_phys`` on the pad+mic subset (Task 07.6), (2) manual frame annotations near impacts,
(3) the analytic crossing time of a SYNTHETIC trajectory. Only (3) is available without
recordings, and a comparison run on (3) is labelled SYNTHETIC and is not a measurement of the
real-world bias.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from spacedrums.data.labels.schema import Interpolation


@dataclass(frozen=True)
class CrossingEstimate:
    t_cross: float
    method: str
    used_samples: int
    residual: float
    """|d(t_cross)| of the fitted model at the returned instant (0 for an exact root)."""


def linear_crossing(t0: float, d0: float, t1: float, d1: float) -> CrossingEstimate | None:
    """Zero of the straight line through ``(t0, d0)`` and ``(t1, d1)``; ``None`` if they do not bracket."""
    if t1 <= t0:
        raise ValueError("trajectory times must be strictly increasing")
    if d0 == d1 or (d0 > 0) == (d1 > 0):
        return None
    u = d0 / (d0 - d1)
    if not 0.0 <= u <= 1.0:
        return None
    return CrossingEstimate(t0 + u * (t1 - t0), str(Interpolation.LINEAR), 2, 0.0)


def quadratic_crossing(times: Sequence[float], distances: Sequence[float], *, bracket: tuple[int, int]
                       ) -> CrossingEstimate | None:
    """Root of the parabola through three samples, inside the bracketing interval.

    ``bracket`` names the indices ``(i, i+1)`` whose signed distances change sign. The third sample
    is the neighbour that keeps the stencil centred on the crossing; if no third sample exists the
    function returns ``None`` and the caller falls back to the linear estimate (recorded as such).
    """
    i, j = bracket
    n = len(times)
    if len(distances) != n or not 0 <= i < j < n or j != i + 1:
        raise ValueError("bracket must be a consecutive index pair inside the sample range")
    third = i - 1 if i - 1 >= 0 else (j + 1 if j + 1 < n else None)
    if third is None:
        return None
    idx = sorted((third, i, j))
    t = [float(times[k]) for k in idx]
    d = [float(distances[k]) for k in idx]
    t0 = t[1]
    x = [ti - t0 for ti in t]
    # Lagrange coefficients of the quadratic through the three points.
    denom = [(x[0] - x[1]) * (x[0] - x[2]), (x[1] - x[0]) * (x[1] - x[2]), (x[2] - x[0]) * (x[2] - x[1])]
    if any(abs(v) <= 1e-18 for v in denom):
        return None
    a = sum(d[k] / denom[k] for k in range(3))
    b = -sum(d[k] * (sum(x[m] for m in range(3) if m != k)) / denom[k] for k in range(3))
    c = sum(d[k] * (math.prod(x[m] for m in range(3) if m != k)) / denom[k] for k in range(3))
    lo, hi = min(times[i], times[j]) - t0, max(times[i], times[j]) - t0
    roots: list[float] = []
    if abs(a) <= 1e-15:
        if abs(b) > 1e-18:
            roots = [-c / b]
    else:
        disc = b * b - 4 * a * c
        if disc < 0:
            return None
        s = math.sqrt(disc)
        roots = [(-b - s) / (2 * a), (-b + s) / (2 * a)]
    inside = [r for r in roots if lo - 1e-12 <= r <= hi + 1e-12]
    if not inside:
        return None
    r = min(inside, key=lambda v: abs(v - (lo + hi) / 2))
    return CrossingEstimate(t0 + r, str(Interpolation.QUADRATIC), 3, abs(a * r * r + b * r + c))


def crossing_time(
    times: Sequence[float],
    distances: Sequence[float],
    *,
    bracket: tuple[int, int],
    method: Interpolation | str = Interpolation.LINEAR,
) -> CrossingEstimate:
    """Sub-frame crossing instant by the requested estimator, falling back to LINEAR when the
    quadratic stencil is unavailable (the fallback is visible in ``CrossingEstimate.method``)."""
    i, j = bracket
    method = Interpolation(method)
    if method is Interpolation.QUADRATIC:
        est = quadratic_crossing(times, distances, bracket=bracket)
        if est is not None:
            return est
    lin = linear_crossing(times[i], distances[i], times[j], distances[j])
    if lin is None:
        raise ValueError("the bracket does not contain a sign change of the signed distance")
    return lin


def find_bracket(distances: Sequence[float], *, start: int = 0) -> tuple[int, int] | None:
    """First consecutive index pair at or after ``start`` where the signed distance changes from
    positive (outside) to non-positive (inside)."""
    for k in range(start, len(distances) - 1):
        if distances[k] > 0 >= distances[k + 1]:
            return (k, k + 1)
    return None


# ----------------------------------------------------------------------------- comparison


@dataclass(frozen=True)
class Comparison:
    """Paired comparison of the two estimators against one reference (Task 07.4 evidence).

    ``evidence_label`` names what the reference was; a comparison against a SYNTHETIC analytic
    crossing is never reported as a measurement of the real-world bias.
    """

    n: int
    reference: str
    evidence_label: str
    bias_linear_s: float | None
    bias_quadratic_s: float | None
    iqr_linear_s: float | None
    iqr_quadratic_s: float | None
    max_abs_linear_s: float | None
    max_abs_quadratic_s: float | None
    decision: str
    decision_reason: str
    errors_linear_s: tuple[float, ...] = ()
    errors_quadratic_s: tuple[float, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "reference": self.reference,
            "evidence_label": self.evidence_label,
            "bias_linear_s": self.bias_linear_s,
            "bias_quadratic_s": self.bias_quadratic_s,
            "iqr_linear_s": self.iqr_linear_s,
            "iqr_quadratic_s": self.iqr_quadratic_s,
            "max_abs_linear_s": self.max_abs_linear_s,
            "max_abs_quadratic_s": self.max_abs_quadratic_s,
            "decision": self.decision,
            "decision_reason": self.decision_reason,
        }


DECISION_RULE = (
    "smaller IQR wins; within 10 % of each other, smaller |bias| wins; within 10 % on both, keep "
    "LINEAR (the Phase 04 estimator, fewer assumptions). Declared before the run."
)


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _iqr(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n < 4:
        return float(max(s) - min(s)) if n else 0.0
    lo = _median(s[: n // 2])
    hi = _median(s[(n + 1) // 2 :])
    return float(hi - lo)


def compare(
    errors_linear: Sequence[float],
    errors_quadratic: Sequence[float],
    *,
    reference: str,
    evidence_label: str,
) -> Comparison:
    """Apply the pre-declared decision rule to two paired error samples (estimate - reference)."""
    if len(errors_linear) != len(errors_quadratic):
        raise ValueError("the comparison is paired: both estimators must cover the same events")
    n = len(errors_linear)
    if n == 0:
        return Comparison(0, reference, evidence_label, None, None, None, None, None, None,
                          "PENDING", "no paired events available", (), ())
    bl, bq = _median(errors_linear), _median(errors_quadratic)
    il, iq = _iqr(errors_linear), _iqr(errors_quadratic)
    mal, maq = max(abs(e) for e in errors_linear), max(abs(e) for e in errors_quadratic)
    ref = max(il, iq, 1e-15)
    if abs(il - iq) / ref > 0.10:
        decision = str(Interpolation.LINEAR) if il < iq else str(Interpolation.QUADRATIC)
        reason = f"IQR differs by more than 10 % ({il:.6g} s vs {iq:.6g} s)"
    else:
        bref = max(abs(bl), abs(bq), 1e-15)
        if abs(abs(bl) - abs(bq)) / bref > 0.10:
            decision = str(Interpolation.LINEAR) if abs(bl) < abs(bq) else str(Interpolation.QUADRATIC)
            reason = f"IQRs within 10 %; |bias| differs ({bl:.6g} s vs {bq:.6g} s)"
        else:
            decision = str(Interpolation.LINEAR)
            reason = "IQR and |bias| both within 10 %: keep the Phase 04 estimator"
    return Comparison(
        n=n,
        reference=reference,
        evidence_label=evidence_label,
        bias_linear_s=bl,
        bias_quadratic_s=bq,
        iqr_linear_s=il,
        iqr_quadratic_s=iq,
        max_abs_linear_s=mal,
        max_abs_quadratic_s=maq,
        decision=decision,
        decision_reason=reason,
        errors_linear_s=tuple(float(e) for e in errors_linear),
        errors_quadratic_s=tuple(float(e) for e in errors_quadratic),
    )


__all__ = [
    "DECISION_RULE",
    "Comparison",
    "CrossingEstimate",
    "compare",
    "crossing_time",
    "find_bracket",
    "linear_crossing",
    "quadratic_crossing",
]
