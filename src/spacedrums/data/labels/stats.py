"""Label statistics (Phase 07, Task 07.9).

Counts per class, zone, hand, segment type and participant; the distribution of the GT intensity
proxy; tracking validity around positives; the ambiguous fraction; the review adjustment rate; the
distance and lighting strata sizes.

One rule shapes the whole module: **counts of different source kinds are never summed.**
``aggregate`` groups by ``source_kind`` first and refuses to produce a single total across kinds
(``schema.evidence_label`` raises). A table of SYNTHETIC counts and a table of PARTICIPANT counts
are two tables, and the report prints them as such (integrity I-4).

Every number produced here is MEASURED from the labels it was computed over - which is not the same
as measured on participants. The evidence label carried in each group says which.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from spacedrums.data.labels.schema import (
    METRIC_EXCLUDED_CLASSES,
    LabelClass,
    QCStatus,
    evidence_label,
)


def _quantiles(xs: Sequence[float]) -> dict[str, float | None]:
    if not xs:
        return {"n": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None,
                "mean": None}
    s = sorted(float(x) for x in xs)

    def q(p: float) -> float:
        pos = p * (len(s) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (pos - lo)

    return {
        "n": len(s),
        "min": s[0],
        "p25": q(0.25),
        "median": q(0.5),
        "p75": q(0.75),
        "max": s[-1],
        "mean": sum(s) / len(s),
    }


@dataclass
class GroupStats:
    """Statistics of one ``source_kind`` group. Never merged with another group."""

    source_kind: str
    evidence_label: str
    n_labels: int = 0
    n_sessions: int = 0
    n_participants: int = 0
    by_class: dict[str, int] = field(default_factory=dict)
    by_zone: dict[str, int] = field(default_factory=dict)
    by_hand: dict[str, int] = field(default_factory=dict)
    by_segment_type: dict[str, int] = field(default_factory=dict)
    by_participant: dict[str, int] = field(default_factory=dict)
    positives_by_participant: dict[str, int] = field(default_factory=dict)
    by_distance_mark: dict[str, int] = field(default_factory=dict)
    by_lighting: dict[str, int] = field(default_factory=dict)
    intensity_proxy_gt: dict[str, float | None] = field(default_factory=dict)
    positives_confidence: dict[str, float | None] = field(default_factory=dict)
    positives_reference_valid_fraction: dict[str, float | None] = field(default_factory=dict)
    ambiguous_fraction: float | None = None
    excluded_fraction: float | None = None
    adjustment_rate: float | None = None
    review_coverage: dict[str, float | None] = field(default_factory=dict)
    metric_eligible: int = 0
    phys_labelled: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "evidence_label": self.evidence_label,
            "n_labels": self.n_labels,
            "n_sessions": self.n_sessions,
            "n_participants": self.n_participants,
            "by_class": dict(sorted(self.by_class.items())),
            "by_zone": dict(sorted(self.by_zone.items())),
            "by_hand": dict(sorted(self.by_hand.items())),
            "by_segment_type": dict(sorted(self.by_segment_type.items())),
            "by_participant": dict(sorted(self.by_participant.items())),
            "positives_by_participant": dict(sorted(self.positives_by_participant.items())),
            "by_distance_mark": dict(sorted(self.by_distance_mark.items())),
            "by_lighting": dict(sorted(self.by_lighting.items())),
            "intensity_proxy_gt": self.intensity_proxy_gt,
            "positives_confidence": self.positives_confidence,
            "positives_reference_valid_fraction": self.positives_reference_valid_fraction,
            "ambiguous_fraction": self.ambiguous_fraction,
            "excluded_fraction": self.excluded_fraction,
            "adjustment_rate": self.adjustment_rate,
            "review_coverage": self.review_coverage,
            "metric_eligible": self.metric_eligible,
            "phys_labelled": self.phys_labelled,
            "label": f"MEASURED from the listed labels; evidence class: {self.evidence_label}",
        }


def group_stats(
    labels: Sequence[dict[str, Any]],
    *,
    strata: dict[str, dict[str, str]] | None = None,
) -> GroupStats:
    """Statistics of one homogeneous group of labels (all of the same ``source_kind``).

    ``strata`` maps ``session_id`` to session-level descriptors (``distance_mark``, ``lighting``)
    so the distance and lighting stratum sizes can be reported without re-reading the sessions.
    """
    kinds = {rec["source_kind"] for rec in labels}
    stats = GroupStats(
        source_kind=next(iter(kinds)) if len(kinds) == 1 else "NONE",
        evidence_label=evidence_label(kinds),  # raises on mixed kinds: that is the point
    )
    strata = strata or {}
    intensities: list[float] = []
    confidences: list[float] = []
    valid_fractions: list[float] = []
    sessions: set[str] = set()
    participants: set[str] = set()
    n_reviewed = n_adjusted = 0
    for rec in labels:
        stats.n_labels += 1
        sessions.add(rec["session_id"])
        participants.add(rec["participant_id"])
        cls = rec["label_class"]
        stats.by_class[cls] = stats.by_class.get(cls, 0) + 1
        stats.by_hand[rec["hand_id"]] = stats.by_hand.get(rec["hand_id"], 0) + 1
        if rec["zone_id"]:
            stats.by_zone[rec["zone_id"]] = stats.by_zone.get(rec["zone_id"], 0) + 1
        key = rec["segment_type"] or "NO_SEGMENT"
        stats.by_segment_type[key] = stats.by_segment_type.get(key, 0) + 1
        stats.by_participant[rec["participant_id"]] = (
            stats.by_participant.get(rec["participant_id"], 0) + 1
        )
        info = strata.get(rec["session_id"], {})
        for field_name, target in (("distance_mark", stats.by_distance_mark),
                                   ("lighting", stats.by_lighting)):
            value = info.get(field_name)
            if value:
                target[value] = target.get(value, 0) + 1
        if rec["review"]["reviewed"]:
            n_reviewed += 1
        if rec["review"]["adjusted"]:
            n_adjusted += 1
        if rec["t_impact_phys"] is not None:
            stats.phys_labelled += 1
        if LabelClass(cls) not in METRIC_EXCLUDED_CLASSES and not rec["excluded"]:
            stats.metric_eligible += 1
        if cls == str(LabelClass.POSITIVE):
            stats.positives_by_participant[rec["participant_id"]] = (
                stats.positives_by_participant.get(rec["participant_id"], 0) + 1
            )
            if rec["intensity_proxy_gt"] is not None:
                intensities.append(float(rec["intensity_proxy_gt"]))
            confidences.append(float(rec["confidence"]))
            q = rec["reference_quality"]
            if q["n_samples"]:
                valid_fractions.append(q["n_valid"] / q["n_samples"])
    stats.n_sessions = len(sessions)
    stats.n_participants = len(participants)
    stats.intensity_proxy_gt = _quantiles(intensities)
    stats.positives_confidence = _quantiles(confidences)
    stats.positives_reference_valid_fraction = _quantiles(valid_fractions)
    n = stats.n_labels or 1
    stats.ambiguous_fraction = stats.by_class.get(str(LabelClass.AMBIGUOUS), 0) / n
    stats.excluded_fraction = sum(1 for r in labels if r["excluded"]) / n
    stats.adjustment_rate = (n_adjusted / n_reviewed) if n_reviewed else None
    stats.review_coverage = {
        "reviewed_fraction": n_reviewed / n,
        "pending_fraction": sum(1 for r in labels
                                if r["qc_status"] == str(QCStatus.PENDING_REVIEW)) / n,
    }
    return stats


def aggregate(
    labels: Sequence[dict[str, Any]],
    *,
    strata: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Statistics grouped by ``source_kind``; there is deliberately no cross-kind total."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for rec in labels:
        groups.setdefault(rec["source_kind"], []).append(rec)
    return {kind: group_stats(recs, strata=strata).to_dict() for kind, recs in sorted(groups.items())}


def class_balance(stats: dict[str, Any]) -> dict[str, float]:
    """Class shares within one group - what Phase 09/10 loss design needs to see."""
    by_class = stats["by_class"]
    total = sum(by_class.values()) or 1
    return {k: v / total for k, v in sorted(by_class.items())}


def markdown_table(stats_by_kind: dict[str, dict[str, Any]]) -> str:
    """One markdown section per source kind. Never one table across kinds."""
    lines: list[str] = []
    for kind, s in stats_by_kind.items():
        lines.append(f"### {kind} — {s['evidence_label']}")
        lines.append("")
        lines.append(f"Labels: **{s['n_labels']}** · sessions: {s['n_sessions']} · "
                     f"participants: {s['n_participants']} · metric-eligible: {s['metric_eligible']} · "
                     f"with physical GT: {s['phys_labelled']}")
        lines.append("")
        lines.append("| Class | Count | Share |")
        lines.append("|---|---:|---:|")
        total = sum(s["by_class"].values()) or 1
        for cls, n in s["by_class"].items():
            lines.append(f"| `{cls}` | {n} | {n / total:.3f} |")
        lines.append("")
        for title, key in (("Zone", "by_zone"), ("Hand", "by_hand"),
                           ("Segment type", "by_segment_type"), ("Participant", "by_participant")):
            if not s[key]:
                continue
            lines.append(f"| {title} | Count |")
            lines.append("|---|---:|")
            for k, n in s[key].items():
                lines.append(f"| `{k}` | {n} |")
            lines.append("")
        i = s["intensity_proxy_gt"]
        lines.append("| `intensity_proxy_gt` (ROI-norm/s, positives) | n | min | p25 | median | p75 | max |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        fmt = (lambda v: "—" if v is None else f"{v:.4f}")
        lines.append(f"| distribution | {i['n']} | {fmt(i['min'])} | {fmt(i['p25'])} | "
                     f"{fmt(i['median'])} | {fmt(i['p75'])} | {fmt(i['max'])} |")
        lines.append("")
        rate = s["adjustment_rate"]
        rate_text = "PENDING (nothing reviewed)" if rate is None else f"{rate:.4f}"
        lines.append(f"Ambiguous fraction: {s['ambiguous_fraction']:.4f} · "
                     f"excluded fraction: {s['excluded_fraction']:.4f} · "
                     f"adjustment rate: {rate_text} · "
                     f"reviewed fraction: {s['review_coverage']['reviewed_fraction']:.4f}")
        lines.append("")
    return "\n".join(lines)


__all__ = ["GroupStats", "aggregate", "class_balance", "group_stats", "markdown_table"]
