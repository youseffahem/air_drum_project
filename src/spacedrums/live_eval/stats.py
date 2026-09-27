"""Participant-level statistics of the Phase 18 confirmatory analysis (pre-registration §6).

The participant is the unit: every interval here is a percentile bootstrap that resamples
participants with replacement. Frames, events and seeds are never treated as independent people.
The declared constants are 10,000 resamples, ``numpy.random.default_rng(18)`` and a 95 % level.

For P ≤ 3 the percentile interval equals the [min, max] of the participant values up to resampling
noise, because a resample made of one participant repeated is more likely than 2.5 %. Every
result therefore carries ``degenerate``. Such an interval is a per-participant consistency
statement, not a population inference.

Nothing here decides a hypothesis. :mod:`spacedrums.live_eval.hypotheses` applies the declared
rules to these intervals.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np

BOOTSTRAP_REPEATS = 10_000
BOOTSTRAP_SEED = 18
CI_LEVEL = 0.95
SMALL_P = 3
SMALL_P_NOTE = (
    "P <= 3: the percentile interval spans the participant values (min..max); read it as a "
    "per-participant consistency statement, not a population inference"
)


def _clean(values: Mapping[str, float | None]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in values.items():
        if value is None:
            continue
        v = float(value)
        if not math.isfinite(v):
            raise ValueError(f"participant {key!r}: non-finite value {value!r}")
        out[str(key)] = v
    return out


def _percentiles(samples: np.ndarray, level: float) -> list[float]:
    tail = 100.0 * (1.0 - level) / 2.0
    lo, hi = np.percentile(samples, [tail, 100.0 - tail])
    return [float(lo), float(hi)]


def _check(repeats: int, level: float) -> None:
    if repeats < 1 or not 0.0 < level < 1.0:
        raise ValueError("repeats >= 1 and 0 < level < 1 required")


def bootstrap_mean(
    values: Mapping[str, float | None],
    *,
    repeats: int = BOOTSTRAP_REPEATS,
    seed: int = BOOTSTRAP_SEED,
    level: float = CI_LEVEL,
) -> dict[str, Any]:
    """Macro mean over participants with its participant-bootstrap interval.

    ``values`` maps a participant id to that participant's statistic (for example the median lead
    over their matched pairs). ``None`` means "undefined for this participant" and is counted, not
    imputed. Participants are sorted by id, so the result does not depend on mapping order.
    """
    _check(repeats, level)
    clean = _clean(values)
    ids = sorted(clean)
    x = np.asarray([clean[k] for k in ids], dtype=float)
    out: dict[str, Any] = {
        "n": len(ids),
        "undefined": len(values) - len(ids),
        "participants": ids,
        "values": {k: clean[k] for k in ids},
        "estimate": float(x.mean()) if len(x) else None,
        "ci": None,
        "degenerate": None,
        "level": level,
        "repeats": repeats,
        "seed": seed,
        "unit": "participant",
        "method": "percentile bootstrap of the participant mean",
        "note": None,
    }
    if len(x) < 2:
        out["note"] = "fewer than two participants: no interval"
        return out
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(repeats, len(x)))].mean(axis=1)
    ci = _percentiles(means, level)
    out["ci"] = ci
    out["degenerate"] = bool(math.isclose(ci[0], x.min()) and math.isclose(ci[1], x.max()))
    if len(x) <= SMALL_P:
        out["note"] = SMALL_P_NOTE
    return out


def paired_differences(a: Mapping[str, float | None], b: Mapping[str, float | None]) -> dict[str, float]:
    """``d(p) = a(p) - b(p)`` for every participant with both values defined."""
    ca, cb = _clean(a), _clean(b)
    return {k: ca[k] - cb[k] for k in sorted(set(ca) & set(cb))}


def bootstrap_paired(
    a: Mapping[str, float | None],
    b: Mapping[str, float | None],
    **kwargs: Any,
) -> dict[str, Any]:
    """Macro mean of paired participant differences ``a - b`` with its interval."""
    diffs = paired_differences(a, b)
    out = bootstrap_mean(diffs, **kwargs)
    out["unpaired"] = sorted(set(_clean(a)) ^ set(_clean(b)))
    out["method"] = "percentile bootstrap of the mean paired participant difference"
    return out


def bootstrap_ratio(
    numerators: Mapping[str, float | None],
    denominators: Mapping[str, float | None],
    *,
    scale: float = 1.0,
    repeats: int = BOOTSTRAP_REPEATS,
    seed: int = BOOTSTRAP_SEED,
    level: float = CI_LEVEL,
) -> dict[str, Any]:
    """Pooled ratio ``scale * sum(num) / sum(den)`` with participants resampled.

    Used for pooled FP per active minute. The numerator is the FP count, the denominator the
    active seconds, and ``scale = 60``. A resample whose denominator sums to zero has no ratio; the
    number of such resamples is reported, never silently dropped.
    """
    _check(repeats, level)
    num, den = _clean(numerators), _clean(denominators)
    ids = sorted(set(num) & set(den))
    if any(den[k] < 0 or num[k] < 0 for k in ids):
        raise ValueError("counts and denominators must be non-negative")
    n_arr = np.asarray([num[k] for k in ids], dtype=float)
    d_arr = np.asarray([den[k] for k in ids], dtype=float)
    total = float(d_arr.sum()) if len(ids) else 0.0
    out: dict[str, Any] = {
        "n": len(ids),
        "participants": ids,
        "numerators": {k: num[k] for k in ids},
        "denominators": {k: den[k] for k in ids},
        "estimate": scale * float(n_arr.sum()) / total if total > 0 else None,
        "ci": None,
        "degenerate": None,
        "undefined_resamples": None,
        "level": level,
        "repeats": repeats,
        "seed": seed,
        "unit": "participant",
        "method": "percentile bootstrap of the pooled ratio (participants resampled)",
        "note": None,
    }
    if len(ids) < 2:
        out["note"] = "fewer than two participants: no interval"
        return out
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(ids), size=(repeats, len(ids)))
    sums_n, sums_d = n_arr[idx].sum(axis=1), d_arr[idx].sum(axis=1)
    ok = sums_d > 0
    out["undefined_resamples"] = int((~ok).sum())
    if not ok.any():
        out["note"] = "every resample has a zero denominator"
        return out
    ratios = scale * sums_n[ok] / sums_d[ok]
    out["ci"] = _percentiles(ratios, level)
    per = [scale * n / d for n, d in zip(n_arr, d_arr, strict=True) if d > 0]
    if per:
        out["degenerate"] = bool(
            math.isclose(out["ci"][0], min(per)) and math.isclose(out["ci"][1], max(per))
        )
    if len(ids) <= SMALL_P:
        out["note"] = SMALL_P_NOTE
    return out


__all__ = [
    "BOOTSTRAP_REPEATS",
    "BOOTSTRAP_SEED",
    "CI_LEVEL",
    "SMALL_P_NOTE",
    "bootstrap_mean",
    "bootstrap_paired",
    "bootstrap_ratio",
    "paired_differences",
]
