"""Canonical offline event metrics, with explicit denominators and missing values."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable

import numpy as np

from spacedrums.eval.matching import MatchResult


def distribution(values: Iterable[float]) -> dict:
    x = np.asarray(list(values), dtype=float)
    if len(x) == 0:
        return {"n": 0, "median": None, "q1": None, "q3": None, "p10": None, "p90": None}
    return {
        "n": len(x),
        "median": float(np.median(x)),
        "q1": float(np.percentile(x, 25)),
        "q3": float(np.percentile(x, 75)),
        "p10": float(np.percentile(x, 10)),
        "p90": float(np.percentile(x, 90)),
    }


def _union(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for a, b in sorted(intervals):
        if not (math.isfinite(a) and math.isfinite(b) and b >= a):
            raise ValueError("interval endpoints must be finite and ordered")
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def active_seconds(
    accepted: Iterable[tuple[float, float]], loss: Iterable[tuple[float, float]] = ()
) -> float:
    """Measure union(accepted) minus union(loss), avoiding overlap double counts."""
    playing, lost = _union(accepted), _union(loss)
    total = sum(b - a for a, b in playing)
    for a, b in playing:
        total -= sum(max(0.0, min(b, y) - max(a, x)) for x, y in lost)
    return max(0.0, total)


def event_metrics(result: MatchResult, *, active_time_s: float) -> dict:
    if active_time_s < 0 or not math.isfinite(active_time_s):
        raise ValueError("active_time_s must be finite and nonnegative")
    pairs = result.pairs
    lead = [float(g["t_impact_est"]) - float(s["t_commit"]) for s, g in pairs]
    timing = [
        float(s["t_impact_pred"]) - float(g["t_impact_est"])
        for s, g in pairs
        if s.get("t_impact_pred") is not None
    ]
    event_timing = [
        float(s["t_impact_pred"] if s.get("t_impact_pred") is not None else s["t_impact_est"])
        - float(g["t_impact_est"])
        for s, g in pairs
        if s.get("t_impact_pred") is not None or s.get("t_impact_est") is not None
    ]
    correct_zone = sum(s["zone_id"] == g["zone_id"] for s, g in pairs)
    confusion = Counter((g["zone_id"], s["zone_id"]) for s, g in pairs)
    intensity = [
        (float(s["intensity_proxy"]), float(g["intensity_proxy_gt"]))
        for s, g in pairs
        if s.get("intensity_proxy") is not None and g.get("intensity_proxy_gt") is not None
    ]
    position_errors = [
        math.dist(s["impact_position"], g["impact_position"])
        for s, g in pairs
        if s.get("impact_position") is not None and g.get("impact_position") is not None
    ]
    n_gt = len(pairs) + len(result.false_negatives)
    fp_types = Counter(s.get("segment_type", "UNATTRIBUTED") for s in result.false_positives)
    out = {
        "matched": len(pairs),
        "fp": len(result.false_positives),
        "fn": len(result.false_negatives),
        "ground_truth": n_gt,
        "active_time_s": active_time_s,
        "fp_per_min": len(result.false_positives) * 60 / active_time_s if active_time_s else None,
        "fn_rate": len(result.false_negatives) / n_gt if n_gt else None,
        "zone_accuracy": correct_zone / len(pairs) if pairs else None,
        "lead_s": distribution(lead),
        "lead_positive_fraction": sum(v > 0 for v in lead) / len(lead) if lead else None,
        "te_pred_s": distribution(timing),
        "te_pred_bias_s": float(np.mean(timing)) if timing else None,
        "te_pred_mae_s": float(np.mean(np.abs(timing))) if timing else None,
        "te_event_s": distribution(event_timing),
        "te_event_bias_s": float(np.mean(event_timing)) if event_timing else None,
        "te_event_mae_s": float(np.mean(np.abs(event_timing))) if event_timing else None,
        "zone_confusion": [{"actual": g, "predicted": s, "n": n} for (g, s), n in sorted(confusion.items())],
        "impact_position_error": distribution(position_errors),
        "intensity_mae": float(np.mean([abs(a - b) for a, b in intensity])) if intensity else None,
        "intensity_pearson_r": float(np.corrcoef(np.asarray(intensity).T)[0, 1])
        if len(intensity) >= 3 and np.std(intensity, axis=0).min() > 0
        else None,
        "intensity_n": len(intensity),
        "fp_by_segment_type": dict(sorted(fp_types.items())),
    }
    return out


def trajectory_metrics(predicted: np.ndarray, target: np.ndarray, mask: np.ndarray) -> dict:
    """ADE/FDE against future causal tracks; mask is per step or per coordinate."""
    if predicted.shape != target.shape or predicted.ndim != 3 or predicted.shape[-1] != 2:
        raise ValueError("trajectory tensors must both be [samples, steps, 2]")
    valid = np.all(mask, axis=-1) if mask.shape == predicted.shape else np.asarray(mask, dtype=bool)
    if valid.shape != predicted.shape[:2]:
        raise ValueError("mask must be [samples, steps] or [samples, steps, 2]")
    dist = np.linalg.norm(predicted - target, axis=-1)
    ade = dist[valid]
    fde = [dist[i, np.flatnonzero(row)[-1]] for i, row in enumerate(valid) if row.any()]
    return {
        "ade": float(np.mean(ade)) if len(ade) else None,
        "fde": float(np.mean(fde)) if fde else None,
        "valid_points": int(valid.sum()),
        "valid_sequences": len(fde),
    }
