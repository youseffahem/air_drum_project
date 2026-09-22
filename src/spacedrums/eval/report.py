"""Session-level evaluation, stratification and machine-readable result writing."""

from __future__ import annotations

import json
from pathlib import Path

from spacedrums.eval.constants import EXCLUDED_LABEL_CLASSES, W_CANDIDATES_S
from spacedrums.eval.matching import match_events
from spacedrums.eval.metrics import active_seconds, event_metrics

EVENT_COLUMNS = (
    "kind",
    "strike_id",
    "label_id",
    "hand_id",
    "zone_pred",
    "zone_gt",
    "t_commit",
    "t_impact_est",
    "t_impact_pred",
    "lead_s",
    "segment_type",
)


def _in_interval(t: float, row: dict) -> bool:
    a, b = row.get("t_start"), row.get("t_end")
    return a is not None and b is not None and a <= t <= b


def _segment(t: float, segments: list[dict], hand: str) -> dict | None:
    return next(
        (s for s in segments if s["eligible"] and hand in s["hands"] and s["t_start"] <= t <= s["t_end"]),
        None,
    )


def evaluate_session(
    strike_rows: list[dict],
    labels: list[dict],
    segments: list[dict],
    *,
    w_s: float,
    include_unreviewed_selftest: bool = False,
) -> dict:
    if include_unreviewed_selftest:
        if any(g["source_kind"] not in ("SYNTHETIC", "DEV_CAPTURE") for g in labels):
            raise ValueError("unreviewed-label diagnostics only allowed for self-test sources")
    else:
        if any(
            g["qc_status"] not in ("ACCEPTED", "ADJUSTED") or not g["review"]["reviewed"]
            for g in labels
            if g["label_class"] not in EXCLUDED_LABEL_CLASSES
        ):
            raise ValueError("participant metrics require reviewed accepted labels")
    excluded = [g for g in labels if g["label_class"] in EXCLUDED_LABEL_CLASSES]
    positives = [g for g in labels if g["label_class"] == "POSITIVE" and not g["excluded"]]
    losses = [
        g
        for g in labels
        if g["label_class"] == "NEG_TRACKING_LOSS" and g["t_start"] is not None and g["t_end"] is not None
    ]

    def admissible_strikes(width: float) -> list[dict]:
        valid = []
        for s in strike_rows:
            seg = _segment(float(s["t_commit"]), segments, s["hand_id"])
            if seg is None or any(
                (g["hand_id"] == s["hand_id"] and _in_interval(s["t_commit"], g))
                or (
                    g["hand_id"] == s["hand_id"]
                    and g.get("t_impact_est") is not None
                    and abs(s["t_commit"] - g["t_impact_est"]) <= width
                )
                for g in excluded
            ):
                continue
            neg = next(
                (
                    g
                    for g in labels
                    if g["hand_id"] == s["hand_id"]
                    and g["label_class"].startswith("NEG_")
                    and _in_interval(s["t_commit"], g)
                ),
                None,
            )
            valid.append({**s, "segment_type": neg["label_class"] if neg else seg["type"]})
        return valid

    valid_strikes = admissible_strikes(w_s)
    positives = [
        g for g in positives if _segment(float(g["t_impact_est"]), segments, g["hand_id"]) is not None
    ]
    by_hand = {}
    all_events = []
    for hand in ("LEFT", "RIGHT"):
        ss = [s for s in valid_strikes if s["hand_id"] == hand]
        gg = [g for g in positives if g["hand_id"] == hand]
        allowed = [(s["t_start"], s["t_end"]) for s in segments if s["eligible"] and hand in s["hands"]]
        lost = [(g["t_start"], g["t_end"]) for g in losses if g["hand_id"] == hand]
        duration = active_seconds(allowed, lost)
        m = match_events(ss, gg, w_s=w_s)
        by_hand[hand] = event_metrics(m, active_time_s=duration)
        all_events.extend(
            {
                "kind": "MATCH",
                "strike_id": s["strike_id"],
                "label_id": g["label_id"],
                "hand_id": hand,
                "zone_pred": s["zone_id"],
                "zone_gt": g["zone_id"],
                "t_commit": s["t_commit"],
                "t_impact_est": g["t_impact_est"],
                "t_impact_pred": s.get("t_impact_pred"),
                "lead_s": g["t_impact_est"] - s["t_commit"],
                "segment_type": g["segment_type"],
            }
            for s, g in m.pairs
        )
        all_events.extend(
            {
                "kind": "FP",
                "strike_id": s["strike_id"],
                "hand_id": hand,
                "segment_type": s["segment_type"],
                "t_commit": s["t_commit"],
            }
            for s in m.false_positives
        )
        all_events.extend(
            {"kind": "FN", "label_id": g["label_id"], "hand_id": hand, "t_impact_est": g["t_impact_est"]}
            for g in m.false_negatives
        )
    pooled_duration = active_seconds(
        [(s["t_start"], s["t_end"]) for s in segments if s["eligible"]],
        [(g["t_start"], g["t_end"]) for g in losses],
    )
    pooled = event_metrics(match_events(valid_strikes, positives, w_s=w_s), active_time_s=pooled_duration)
    by_zone = {}
    for zone in sorted({g["zone_id"] for g in positives} | {s["zone_id"] for s in valid_strikes}):
        zone_result = match_events(
            [s for s in valid_strikes if s["zone_id"] == zone],
            [g for g in positives if g["zone_id"] == zone],
            w_s=w_s,
        )
        by_zone[zone] = event_metrics(zone_result, active_time_s=pooled_duration)
    segment_types = sorted({s["type"] for s in segments if s["eligible"]})
    by_segment = {}
    for kind in segment_types:
        section = [s for s in segments if s["eligible"] and s["type"] == kind]
        section_duration = active_seconds(
            [(s["t_start"], s["t_end"]) for s in section],
            [(g["t_start"], g["t_end"]) for g in losses],
        )
        section_strikes = [
            s for s in valid_strikes if any(q["t_start"] <= s["t_commit"] <= q["t_end"] for q in section)
        ]
        section_labels = [
            g for g in positives if any(q["t_start"] <= g["t_impact_est"] <= q["t_end"] for q in section)
        ]
        by_segment[kind] = event_metrics(
            match_events(section_strikes, section_labels, w_s=w_s), active_time_s=section_duration
        )
    sweep = {}
    for w in W_CANDIDATES_S:
        sweep[str(w)] = event_metrics(
            match_events(admissible_strikes(w), positives, w_s=w), active_time_s=pooled_duration
        )
    return {
        "pooled": pooled,
        "by_hand": by_hand,
        "by_zone": by_zone,
        "by_segment_type": by_segment,
        "w_sweep": sweep,
        "events": all_events,
        "excluded_labels": len(excluded),
        "unreviewed_selftest": include_unreviewed_selftest,
    }


def curve_points(results: list[dict]) -> list[dict]:
    return [
        {
            "settings": r["settings"],
            "median_lead_s": r["pooled"]["lead_s"]["median"],
            "fp_per_min": r["pooled"]["fp_per_min"],
            "fn_rate": r["pooled"]["fn_rate"],
        }
        for r in results
    ]


def write_result(output: str | Path, result: dict) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    events = result["events"]
    (output / "results.json").write_text(
        json.dumps({k: v for k, v in result.items() if k != "events"}, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (output / "events.jsonl").write_text(
        "".join(json.dumps(row, allow_nan=False) + "\n" for row in events), encoding="utf-8"
    )
    schema = pa.schema(
        [
            (
                key,
                pa.float64()
                if key in {"t_commit", "t_impact_est", "t_impact_pred", "lead_s"}
                else pa.string(),
            )
            for key in EVENT_COLUMNS
        ]
    )
    table = pa.Table.from_pylist(
        [{key: row.get(key) for key in EVENT_COLUMNS} for row in events], schema=schema
    )
    pq.write_table(table, output / "events.parquet", compression="zstd")
