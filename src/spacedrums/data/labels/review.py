"""QC / review machinery and inter-annotator agreement (Phase 07, Task 07.5).

The interactive front end is ``tools/review_labels.py``; everything that can be tested without a
person is here: applying a decision to a label, the append-only review log, the sampling plan of
the QC protocol, and the agreement statistics between two review passes.

**QC protocol P07-QC-1** (recorded in ``docs/dataset/labeling-rules-v1.0.md`` section 6):

| Stratum | First pass | Second pass (agreement subset) |
|---|---|---|
| POSITIVE | 100 % (a lower rate is allowed only if the volume makes it impossible, and the rate is then recorded in the label set) | stratified sample |
| AMBIGUOUS | 100 % | stratified sample |
| NEG_* | sampled at ``negatives_rate`` | stratified sample |
| EXCLUDED | not reviewed (the material is quarantined) | - |

A second pass is performed by a **second annotator** where one is available; the phase document's
fallback - the same annotator re-reviewing after a stated time gap - is permitted and must then be
labelled ``SELF_REREVIEW`` in the agreement report, because a self re-review measures consistency,
not inter-annotator agreement.

Agreement is reported two ways, never merged:

* **event presence**: Cohen's kappa over the paired decisions (an event is *present* when the pass
  accepted or adjusted it, *absent* when it rejected or deferred it);
* **timing**: the distribution of ``|delta t|`` over events both passes accepted.

Nothing in this module invents a reviewer. A pass with no entries yields ``n = 0`` and a kappa of
``None``, which the reports print as PENDING rather than as a number.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spacedrums.data.labels.schema import (
    LABEL_REVIEW_SCHEMA_VERSION,
    LabelClass,
    QCStatus,
    ReviewDecision,
    adjustable,
    validate_review_entry,
)

QC_PROTOCOL_ID = "P07-QC-1"
TOOL_ID = "tools/review_labels.py:0.7.0"

PRESENT_DECISIONS = frozenset({str(ReviewDecision.ACCEPT), str(ReviewDecision.ADJUST),
                               str(ReviewDecision.ADD)})
ABSENT_DECISIONS = frozenset({str(ReviewDecision.REJECT), str(ReviewDecision.DEFER)})


@dataclass(frozen=True)
class SamplingPlan:
    """Review coverage actually applied. The rates are recorded, never assumed."""

    positives_rate: float = 1.0
    ambiguous_rate: float = 1.0
    negatives_rate: float = 0.2

    def __post_init__(self) -> None:
        for name in ("positives_rate", "ambiguous_rate", "negatives_rate"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must lie in [0, 1]")

    def to_dict(self) -> dict[str, float]:
        return {
            "positives_rate": float(self.positives_rate),
            "ambiguous_rate": float(self.ambiguous_rate),
            "negatives_rate": float(self.negatives_rate),
        }

    def rate_for(self, label_class: LabelClass | str) -> float:
        cls = LabelClass(label_class)
        if cls is LabelClass.POSITIVE:
            return self.positives_rate
        if cls is LabelClass.AMBIGUOUS:
            return self.ambiguous_rate
        if cls is LabelClass.EXCLUDED:
            return 0.0
        return self.negatives_rate


def review_queue(
    labels: Sequence[dict[str, Any]], plan: SamplingPlan | None = None
) -> list[dict[str, Any]]:
    """The labels the QC protocol asks a reviewer to look at, in deterministic order.

    Sampling is a deterministic stride over the class's labels (sorted by label id), not a random
    draw: the same label set always produces the same queue, so a review session can be resumed and
    a second annotator can be given exactly the same material.
    """
    plan = plan or SamplingPlan()
    out: list[dict[str, Any]] = []
    by_class: dict[str, list[dict[str, Any]]] = {}
    for rec in labels:
        by_class.setdefault(rec["label_class"], []).append(rec)
    for cls, recs in sorted(by_class.items()):
        recs = sorted(recs, key=lambda r: r["label_id"])
        rate = plan.rate_for(cls)
        if rate >= 1.0:
            out += recs
        elif rate <= 0.0:
            continue
        else:
            stride = max(1, round(1.0 / rate))
            out += recs[::stride]
    return sorted(out, key=lambda r: r["label_id"])


def stratum_of(record: dict[str, Any], *, lighting: str = "UNKNOWN") -> dict[str, Any]:
    """Stratification keys of the agreement subset (zone, hand, segment type, speed, lighting)."""
    speed = record["intensity_secondary"].get("peak_speed_pre")
    if speed is None:
        band = "UNKNOWN"
    elif speed < 0.5:
        band = "SLOW"
    elif speed < 1.5:
        band = "MEDIUM"
    else:
        band = "FAST"
    return {
        "zone_id": record["zone_id"],
        "hand_id": record["hand_id"],
        "segment_type": record["segment_type"],
        "speed_band": band,
        "lighting": lighting,
    }


def make_entry(
    record: dict[str, Any],
    *,
    decision: ReviewDecision | str,
    reviewer_id: str,
    reviewed_at: str,
    pass_no: int = 1,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    notes: str = "",
    lighting: str = "UNKNOWN",
    tool_id: str = TOOL_ID,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Build one schema-valid review-log entry for ``record``."""
    decision = ReviewDecision(decision)
    before = adjustable(record)
    entry = {
        "schema_version": LABEL_REVIEW_SCHEMA_VERSION,
        "entry_id": entry_id or f"{record['label_id']}-p{pass_no}-{reviewer_id}",
        "labels_version": record["labels_version"],
        "dataset_version": record["dataset_version"],
        "source_kind": record["source_kind"],
        "session_id": record["session_id"],
        "label_id": record["label_id"],
        "pass": int(pass_no),
        "reviewer_id": reviewer_id,
        "reviewed_at": reviewed_at,
        "decision": str(decision),
        "before": before,
        "after": after if decision is ReviewDecision.ADJUST else (
            after if decision is ReviewDecision.ADD else before
        ),
        "reason": reason,
        "notes": notes,
        "stratum": stratum_of(record, lighting=lighting),
        "tool_id": tool_id,
    }
    if decision is ReviewDecision.ADD:
        entry["before"] = None
    errs = validate_review_entry(entry)
    if errs:
        raise ValueError(f"review entry invalid: {errs[0]}")
    return entry


def apply_entry(record: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Return ``record`` with the reviewer's decision applied (the input is not mutated).

    An adjustment keeps the generator's values in ``review.original`` and appends one
    ``review.history`` item per changed field; a second-pass entry is stored beside the first pass
    and, when it disagrees, sets ``review.disagreement`` whose default resolution is AMBIGUOUS
    (rule R6c) - the event then leaves every metric numerator and denominator but stays in the set.
    """
    out = json.loads(json.dumps(record))
    review = out["review"]
    decision = ReviewDecision(entry["decision"])
    if int(entry["pass"]) == 2:
        review["second_pass"] = {
            "reviewer_id": entry["reviewer_id"],
            "decision": str(decision),
            "t_impact_est": (entry["after"] or {}).get("t_impact_est"),
            "zone_id": (entry["after"] or {}).get("zone_id"),
            "reviewed_at": entry["reviewed_at"],
            "notes": entry["notes"],
        }
        first_present = out["qc_status"] in (str(QCStatus.ACCEPTED), str(QCStatus.ADJUSTED))
        second_present = str(decision) in PRESENT_DECISIONS
        kind: str | None = None
        delta: float | None = None
        if first_present != second_present:
            kind = "PRESENCE"
        elif first_present and (entry["after"] or {}).get("zone_id") not in (None, out["zone_id"]):
            kind = "ZONE"
        elif first_present and out["t_impact_est"] is not None:
            t2 = (entry["after"] or {}).get("t_impact_est")
            if t2 is not None:
                delta = float(t2) - float(out["t_impact_est"])
                if abs(delta) > 0:
                    kind = "TIMING"
        if kind in ("PRESENCE", "ZONE"):
            review["disagreement"] = {
                "kind": kind,
                "delta_t_s": delta,
                "resolution": "AMBIGUOUS",
                "resolved_by": None,
                "note": "presence/zone disagreement between the two passes (rule R6c)",
            }
            out["label_class"] = str(LabelClass.AMBIGUOUS)
            out["label_rule_id"] = "P07-R6c"
        elif kind == "TIMING":
            review["disagreement"] = {
                "kind": "TIMING",
                "delta_t_s": delta,
                "resolution": "FIRST_PASS",
                "resolved_by": entry["reviewer_id"],
                "note": "timing difference recorded; the first pass value is kept",
            }
        return out

    review["reviewed"] = True
    review["reviewer_id"] = entry["reviewer_id"]
    review["reviewed_at"] = entry["reviewed_at"]
    review["notes"] = entry["notes"]
    review["reason"] = entry["reason"]
    if decision is ReviewDecision.ACCEPT:
        out["qc_status"] = str(QCStatus.ACCEPTED)
    elif decision is ReviewDecision.REJECT:
        out["qc_status"] = str(QCStatus.REJECTED)
    elif decision is ReviewDecision.DEFER:
        # Reviewed but undecided: the event becomes AMBIGUOUS and leaves every metric (rule R6c).
        out["qc_status"] = str(QCStatus.ACCEPTED)
        out["label_class"] = str(LabelClass.AMBIGUOUS)
        out["label_rule_id"] = "P07-R6c"
    elif decision is ReviewDecision.ADJUST:
        after = entry["after"]
        if review["original"] is None:
            review["original"] = adjustable(record)
        for field in ("t_impact_est", "t_event", "zone_id", "label_class"):
            if after.get(field) != out[field]:
                review["history"].append(
                    {
                        "at": entry["reviewed_at"],
                        "reviewer_id": entry["reviewer_id"],
                        "field": field,
                        "from": out[field],
                        "to": after.get(field),
                        "reason": entry["reason"] or "",
                    }
                )
                out[field] = after.get(field)
        review["adjusted"] = True
        out["qc_status"] = str(QCStatus.ADJUSTED)
    if out["label_class"] in {str(c) for c in (LabelClass.NEG_NO_STRIKE_MOTION,
                                               LabelClass.NEG_FAKE_SWING,
                                               LabelClass.NEG_STOP_BEFORE_IMPACT,
                                               LabelClass.NEG_BETWEEN_ZONES,
                                               LabelClass.NEG_UPWARD_CROSSING,
                                               LabelClass.NEG_TRACKING_LOSS)}:
        out["t_impact_est"] = None
        out["intensity_proxy_gt"] = None
    out["labeller_id"] = record["labeller_id"]
    return out


def write_review_log(entries: Iterable[dict[str, Any]], path: str | Path, *, append: bool = True) -> Path:
    """Append entries to the review log (JSONL, no stream header: a review log is not a record stream)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append and path.exists() else "w"
    with path.open(mode, encoding="utf-8", newline="\n") as fh:
        for entry in entries:
            errs = validate_review_entry(entry)
            if errs:
                raise ValueError(f"review entry invalid: {errs[0]}")
            fh.write(json.dumps(entry, allow_nan=False, sort_keys=True) + "\n")
    return path


def read_review_log(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


# ----------------------------------------------------------------------------- agreement


@dataclass(frozen=True)
class Agreement:
    """Inter-annotator agreement over one stratified subset (Task 07.5 evidence)."""

    n_pairs: int
    kind: str
    """INTER_ANNOTATOR (two annotators) or SELF_REREVIEW (fallback of the phase document)."""

    evidence_label: str
    kappa: float | None
    p_observed: float | None
    p_expected: float | None
    n_both_present: int
    delta_t_abs_s: tuple[float, ...]
    median_abs_dt_s: float | None
    p95_abs_dt_s: float | None
    max_abs_dt_s: float | None
    by_stratum: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_pairs": self.n_pairs,
            "kind": self.kind,
            "evidence_label": self.evidence_label,
            "kappa": self.kappa,
            "p_observed": self.p_observed,
            "p_expected": self.p_expected,
            "n_both_present": self.n_both_present,
            "median_abs_dt_s": self.median_abs_dt_s,
            "p95_abs_dt_s": self.p95_abs_dt_s,
            "max_abs_dt_s": self.max_abs_dt_s,
            "by_stratum": dict(sorted(self.by_stratum.items())),
        }


def cohen_kappa(pairs: Sequence[tuple[bool, bool]]) -> tuple[float | None, float, float]:
    """Cohen's kappa for binary presence decisions; ``None`` when it is undefined.

    Kappa is undefined (not 1.0) when both annotators used a single category throughout, because
    the expected agreement is then 1 and the correction divides by zero. Reporting ``None`` keeps
    that case visible instead of printing a perfect score that means nothing.
    """
    n = len(pairs)
    if n == 0:
        return None, 0.0, 0.0
    both = sum(1 for a, b in pairs if a and b)
    neither = sum(1 for a, b in pairs if not a and not b)
    p_o = (both + neither) / n
    a_yes = sum(1 for a, _ in pairs if a) / n
    b_yes = sum(1 for _, b in pairs if b) / n
    p_e = a_yes * b_yes + (1 - a_yes) * (1 - b_yes)
    if abs(1.0 - p_e) < 1e-12:
        return None, p_o, p_e
    return (p_o - p_e) / (1.0 - p_e), p_o, p_e


def _quantile(xs: Sequence[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return float(s[lo] + (s[hi] - s[lo]) * (pos - lo))


def agreement(
    entries: Sequence[dict[str, Any]], *, kind: str = "INTER_ANNOTATOR", evidence_label: str = "PENDING"
) -> Agreement:
    """Pair pass-1 and pass-2 entries by ``label_id`` and compute presence kappa and |delta t|."""
    first = {e["label_id"]: e for e in entries if int(e["pass"]) == 1}
    second = {e["label_id"]: e for e in entries if int(e["pass"]) == 2}
    shared = sorted(set(first) & set(second))
    pairs: list[tuple[bool, bool]] = []
    deltas: list[float] = []
    strata: dict[str, int] = {}
    for lid in shared:
        a, b = first[lid], second[lid]
        pa = a["decision"] in PRESENT_DECISIONS
        pb = b["decision"] in PRESENT_DECISIONS
        pairs.append((pa, pb))
        key = f"{a['stratum']['zone_id']}|{a['stratum']['hand_id']}|{a['stratum']['speed_band']}"
        strata[key] = strata.get(key, 0) + 1
        if pa and pb:
            ta = (a["after"] or {}).get("t_impact_est")
            tb = (b["after"] or {}).get("t_impact_est")
            if ta is not None and tb is not None:
                deltas.append(abs(float(tb) - float(ta)))
    kappa, p_o, p_e = cohen_kappa(pairs)
    return Agreement(
        n_pairs=len(pairs),
        kind=kind,
        evidence_label=evidence_label,
        kappa=kappa,
        p_observed=p_o if pairs else None,
        p_expected=p_e if pairs else None,
        n_both_present=len(deltas),
        delta_t_abs_s=tuple(deltas),
        median_abs_dt_s=_quantile(deltas, 0.5),
        p95_abs_dt_s=_quantile(deltas, 0.95),
        max_abs_dt_s=max(deltas) if deltas else None,
        by_stratum=strata,
    )


def qc_summary(labels: Sequence[dict[str, Any]], plan: SamplingPlan | None = None) -> dict[str, Any]:
    """The ``label_set["qc"]`` block for a reviewed label list."""
    plan = plan or SamplingPlan()
    reviewed = [r for r in labels if r["review"]["reviewed"]]
    return {
        "protocol_id": QC_PROTOCOL_ID,
        "reviewed": len(reviewed),
        "accepted": sum(1 for r in labels if r["qc_status"] == str(QCStatus.ACCEPTED)),
        "rejected": sum(1 for r in labels if r["qc_status"] == str(QCStatus.REJECTED)),
        "adjusted": sum(1 for r in labels if r["qc_status"] == str(QCStatus.ADJUSTED)),
        "pending": sum(1 for r in labels if r["qc_status"] == str(QCStatus.PENDING_REVIEW)),
        "second_pass": sum(1 for r in labels if r["review"]["second_pass"] is not None),
        "sampling": plan.to_dict(),
        "label": "MEASURED from this label set's review state",
    }


__all__ = [
    "ABSENT_DECISIONS",
    "PRESENT_DECISIONS",
    "QC_PROTOCOL_ID",
    "TOOL_ID",
    "Agreement",
    "SamplingPlan",
    "agreement",
    "apply_entry",
    "cohen_kappa",
    "make_entry",
    "qc_summary",
    "read_review_log",
    "review_queue",
    "stratum_of",
    "write_review_log",
]
