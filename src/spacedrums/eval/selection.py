"""Validation-only, deterministic selection from achieved operating points."""

from __future__ import annotations

import json


def select_point(points: list[dict], *, fp_budget: float, fn_ceiling: float) -> dict:
    """Maximise lead inside both budgets; return an explicit infeasible diagnostic otherwise."""
    if fp_budget < 0 or not 0 <= fn_ceiling <= 1:
        raise ValueError("invalid operating-point budgets")
    valid = [
        p
        for p in points
        if p.get("median_lead_s") is not None
        and p.get("fp_per_min") is not None
        and p.get("fn_rate") is not None
    ]
    if not valid:
        return {"feasible": False, "point": None, "reason": "no matched validation events"}

    def stable(p):
        return json.dumps(p["settings"], sort_keys=True, separators=(",", ":"))

    feasible = [p for p in valid if p["fp_per_min"] <= fp_budget and p["fn_rate"] <= fn_ceiling]
    if feasible:
        selected = min(
            feasible, key=lambda p: (-p["median_lead_s"], p["fp_per_min"], p["fn_rate"], stable(p))
        )
        return {"feasible": True, "point": selected, "reason": None}
    diagnostic = min(valid, key=lambda p: (p["fp_per_min"], p["fn_rate"], -p["median_lead_s"], stable(p)))
    return {"feasible": False, "point": diagnostic, "reason": "no point meets both budgets"}


def select_lead_matched(points: list[dict], *, baseline_lead_s: float) -> dict:
    eligible = [
        p
        for p in points
        if p.get("median_lead_s") is not None
        and p.get("fp_per_min") is not None
        and p.get("fn_rate") is not None
        and p["median_lead_s"] >= baseline_lead_s
    ]
    if not eligible:
        return {"feasible": False, "point": None, "reason": "no lead-matched validation point"}
    selected = min(
        eligible, key=lambda p: (p["fp_per_min"], p["fn_rate"], json.dumps(p["settings"], sort_keys=True))
    )
    return {"feasible": True, "point": selected, "reason": None}
