"""The pre-registered decision rules of Phase 18 (``docs/experiments/phase-18-prereg.md`` §3).

Every function takes participant-level values (or already-computed intervals) and returns one
outcome record. The record carries the id, the statement, the rule, the estimate and interval, the
decision, and the reading that the report must print. Decisions:

* ``SUPPORTED`` / ``NOT_SUPPORTED`` / ``INCONCLUSIVE``: the declared interval rules.
* ``NOT_TESTABLE``: a declared precondition failed (for example, no budget-feasible validation
  point for C); the failed precondition is named.
* ``PENDING``: an input does not exist (for example, no external method passed its acceptance
  rules).

The two-sided C-versus-B comparison ``CB`` has its own outcomes (``C_LONGER``, ``B_LONGER``,
``NO_MATERIAL_DIFFERENCE``, ``INCONCLUSIVE``). An outcome in which A or B is preferable is as
reportable as any other: no winner is assumed (README §9).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from spacedrums.live_eval.stats import bootstrap_mean, bootstrap_paired, bootstrap_ratio

SUPPORTED = "SUPPORTED"
NOT_SUPPORTED = "NOT_SUPPORTED"
INCONCLUSIVE = "INCONCLUSIVE"
NOT_TESTABLE = "NOT_TESTABLE"
PENDING = "PENDING"
C_LONGER = "C_LONGER"
B_LONGER = "B_LONGER"
NO_MATERIAL_DIFFERENCE = "NO_MATERIAL_DIFFERENCE"

HYPOTHESES: dict[str, dict[str, str]] = {
    "H1a": {
        "statement": "C achieves positive useful lead on held-out participants at its budget-feasible "
        "operating point: macro of per-participant median L_pred(C) > 0.",
        "rule": "SUPPORTED iff CI low > 0; NOT SUPPORTED iff CI high <= 0; else INCONCLUSIVE",
        "failure": "the temporal model gives no positive useful lead at an acceptable FP budget on "
        "held-out participants; the latency motivation is not supported offline",
    },
    "H1b": {
        "statement": "C leads A: macro paired L_pred(C) - L_pred(A) > 0.",
        "rule": "SUPPORTED iff CI low > 0; NOT SUPPORTED iff CI high <= 0; else INCONCLUSIVE",
        "failure": "C gives no earlier commit than reactive detection",
    },
    "CB": {
        "statement": "C versus B at their frozen operating points: macro paired L_pred(C) - L_pred(B) "
        "(informative, two-sided).",
        "rule": "C_LONGER iff CI low > 0; B_LONGER iff CI high < 0; otherwise NO_MATERIAL_DIFFERENCE "
        "iff -delta_lead < CI low and CI high < delta_lead; else INCONCLUSIVE; a C_LONGER interval "
        "inside (0, delta_lead) or a B_LONGER interval inside (-delta_lead, 0) is not material",
        "failure": "learned trajectory prediction adds no lead over physics extrapolation at the same "
        "budget; B suffices for anticipation",
    },
    "H2": {
        "statement": "C's pooled test FP/min at its operating point <= B_FP.",
        "rule": "SUPPORTED iff CI high <= B_FP; NOT SUPPORTED iff CI low > B_FP; else INCONCLUSIVE",
        "failure": "the FP budget chosen on validation does not transfer to held-out participants; "
        "FP control is not demonstrated",
    },
    "H3": {
        "statement": "C's macro TE_pred MAE <= delta_TE.",
        "rule": "SUPPORTED iff CI high <= delta_TE; NOT SUPPORTED iff CI low > delta_TE; else INCONCLUSIVE",
        "failure": "predicted impact times are not accurate enough for audio scheduling at the "
        "declared tolerance; lead without timing accuracy is not useful",
    },
    "H4": {
        "statement": "Externally measured action-to-sound latency of C is lower than that of A by more "
        "than the measurement uncertainty U.",
        "rule": "SUPPORTED iff CI high < -U; NOT SUPPORTED iff CI low >= -U; else INCONCLUSIVE; "
        "PENDING if no external method passed its acceptance rules",
        "failure": "no effective-latency reduction is measurable within the method's resolution; the "
        "offline lead does not translate into earlier sound",
    },
    "H4-B": {
        "statement": "Externally measured action-to-sound latency of B is lower than that of A by more "
        "than the measurement uncertainty U.",
        "rule": "as H4",
        "failure": "no effective-latency reduction of B is measurable within the method's resolution",
    },
}


def _ci(stat: Mapping[str, Any] | None) -> tuple[float, float] | None:
    if stat is None or stat.get("ci") is None:
        return None
    lo, hi = stat["ci"]
    return float(lo), float(hi)


def decide_greater(ci: tuple[float, float] | None, threshold: float = 0.0) -> str:
    """H1a / H1b: the quantity exceeds ``threshold``."""
    if ci is None:
        return INCONCLUSIVE
    lo, hi = ci
    if lo > threshold:
        return SUPPORTED
    if hi <= threshold:
        return NOT_SUPPORTED
    return INCONCLUSIVE


def decide_at_most(ci: tuple[float, float] | None, bound: float) -> str:
    """H2 / H3: the quantity does not exceed ``bound``."""
    if ci is None:
        return INCONCLUSIVE
    lo, hi = ci
    if hi <= bound:
        return SUPPORTED
    if lo > bound:
        return NOT_SUPPORTED
    return INCONCLUSIVE


def decide_reduction(ci: tuple[float, float] | None, u: float) -> str:
    """H4: the paired difference ``lat_X - lat_A`` lies below ``-U``."""
    if u < 0:
        raise ValueError("measurement uncertainty U must be non-negative")
    if ci is None:
        return INCONCLUSIVE
    lo, hi = ci
    if hi < -u:
        return SUPPORTED
    if lo >= -u:
        return NOT_SUPPORTED
    return INCONCLUSIVE


def decide_cb(ci: tuple[float, float] | None, delta_lead: float | None) -> tuple[str, bool | None]:
    """CB: ``(outcome, material)``. ``material`` is False for a C_LONGER interval below delta_lead."""
    if ci is None:
        return INCONCLUSIVE, None
    lo, hi = ci
    if lo > 0:
        return C_LONGER, None if delta_lead is None else hi >= delta_lead
    if hi < 0:
        return B_LONGER, None if delta_lead is None else lo <= -delta_lead
    if delta_lead is not None and -delta_lead < lo and hi < delta_lead:
        return NO_MATERIAL_DIFFERENCE, False
    return INCONCLUSIVE, None


def _record(hid: str, stat: Mapping[str, Any] | None, decision: str, **extra: Any) -> dict[str, Any]:
    spec = HYPOTHESES[hid]
    if decision == SUPPORTED:
        reading = "supported: " + spec["statement"]
    elif decision in (NOT_TESTABLE, PENDING):
        reading = f"{decision.lower().replace('_', ' ')}: " + str(extra.get("reason", ""))
    elif decision == INCONCLUSIVE:
        reading = (
            "inconclusive: the interval does not decide; if confirmed, we would report that "
            + spec["failure"]
        )
    else:
        reading = "not supported: " + spec["failure"]
    return {
        "id": hid,
        "statement": spec["statement"],
        "rule": spec["rule"],
        "decision": decision,
        "estimate": None if stat is None else stat.get("estimate"),
        "ci": None if stat is None else stat.get("ci"),
        "n": None if stat is None else stat.get("n"),
        "degenerate": None if stat is None else stat.get("degenerate"),
        "note": None if stat is None else stat.get("note"),
        "reading": reading,
        **extra,
    }


def not_testable(hid: str, reason: str) -> dict[str, Any]:
    return _record(hid, None, NOT_TESTABLE, reason=reason)


def pending(hid: str, reason: str) -> dict[str, Any]:
    return _record(hid, None, PENDING, reason=reason)


def h1a(lead_c: Mapping[str, float | None], *, c_feasible: bool, **boot: Any) -> dict[str, Any]:
    if not c_feasible:
        return not_testable("H1a", "the offline lock records no budget-feasible validation point for C")
    stat = bootstrap_mean(lead_c, **boot)
    return _record("H1a", stat, decide_greater(_ci(stat)), statistic=stat)


def h1b(
    lead_c: Mapping[str, float | None],
    lead_a: Mapping[str, float | None],
    *,
    c_feasible: bool,
    **boot: Any,
) -> dict[str, Any]:
    if not c_feasible:
        return not_testable("H1b", "the offline lock records no budget-feasible validation point for C")
    stat = bootstrap_paired(lead_c, lead_a, **boot)
    return _record("H1b", stat, decide_greater(_ci(stat)), statistic=stat)


def cb(
    lead_c: Mapping[str, float | None],
    lead_b: Mapping[str, float | None],
    *,
    delta_lead: float | None,
    c_feasible: bool,
    b_feasible: bool,
    **boot: Any,
) -> dict[str, Any]:
    if not (c_feasible and b_feasible):
        which = " and ".join(x for x, ok in (("C", c_feasible), ("B", b_feasible)) if not ok)
        return not_testable("CB", f"no budget-feasible validation point for {which}")
    stat = bootstrap_paired(lead_c, lead_b, **boot)
    outcome, material = decide_cb(_ci(stat), delta_lead)
    record = _record("CB", stat, outcome, statistic=stat, material=material, delta_lead=delta_lead)
    record["reading"] = {
        C_LONGER: "C commits earlier than B at the same budget"
        + (" (below delta_lead: not material)" if material is False else ""),
        B_LONGER: "B commits earlier than C at the same budget"
        + (" (above -delta_lead: not material)" if material is False else "")
        + ": "
        + HYPOTHESES["CB"]["failure"],
        NO_MATERIAL_DIFFERENCE: "no material difference between C and B: " + HYPOTHESES["CB"]["failure"],
        INCONCLUSIVE: "inconclusive: the interval does not separate C and B"
        + ("" if delta_lead is not None else " (delta_lead not set)"),
    }[outcome]
    return record


def h2(
    fp_c: Mapping[str, float | None],
    active_s_c: Mapping[str, float | None],
    *,
    fp_budget_per_min: float,
    c_feasible: bool,
    **boot: Any,
) -> dict[str, Any]:
    if not c_feasible:
        return not_testable("H2", "the offline lock records no budget-feasible validation point for C")
    stat = bootstrap_ratio(fp_c, active_s_c, scale=60.0, **boot)
    return _record(
        "H2", stat, decide_at_most(_ci(stat), fp_budget_per_min), statistic=stat, bound=fp_budget_per_min
    )


def h3(
    te_mae_c: Mapping[str, float | None], *, delta_te_s: float, c_feasible: bool, **boot: Any
) -> dict[str, Any]:
    if not c_feasible:
        return not_testable("H3", "the offline lock records no budget-feasible validation point for C")
    stat = bootstrap_mean(te_mae_c, **boot)
    return _record("H3", stat, decide_at_most(_ci(stat), delta_te_s), statistic=stat, bound=delta_te_s)


def delta_te(delta_audio_s: float, s_phys_s: float | None) -> float:
    """The declared H3 bound: ``max(delta_audio, 2 * s_phys)``; ``s_phys`` None means not measured."""
    if delta_audio_s <= 0 or (s_phys_s is not None and s_phys_s < 0):
        raise ValueError("delta_audio must be positive and s_phys non-negative")
    return delta_audio_s if s_phys_s is None else max(delta_audio_s, 2.0 * s_phys_s)


def h4(
    lat_x: Mapping[str, float | None],
    lat_a: Mapping[str, float | None],
    *,
    method: Mapping[str, Any] | None,
    arm: str = "C",
    **boot: Any,
) -> dict[str, Any]:
    hid = "H4" if arm == "C" else "H4-B"
    if method is None or method.get("status") != "GO" or method.get("u_s") is None:
        return pending(hid, "no external timing method passed its acceptance rules (pre-registration §8)")
    u = float(method["u_s"])
    stat = bootstrap_paired(lat_x, lat_a, **boot)
    return _record(
        hid, stat, decide_reduction(_ci(stat), u), statistic=stat, u_s=u, method=method.get("method")
    )


__all__ = [
    "B_LONGER",
    "C_LONGER",
    "HYPOTHESES",
    "INCONCLUSIVE",
    "NOT_SUPPORTED",
    "NOT_TESTABLE",
    "NO_MATERIAL_DIFFERENCE",
    "PENDING",
    "SUPPORTED",
    "cb",
    "decide_at_most",
    "decide_cb",
    "decide_greater",
    "decide_reduction",
    "delta_te",
    "h1a",
    "h1b",
    "h2",
    "h3",
    "h4",
    "not_testable",
    "pending",
]
