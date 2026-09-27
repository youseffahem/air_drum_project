"""Phase 18 Tasks 18.5 / 18.6: analyse recorded live sessions (Experiment 2).

    python scripts/analyze_live.py --session <dir> [--session <dir> ...] [--labels-root <dir>] \
        (--lock-live <live lock> | --rehearsal-method-u <s>) [--offline-results <results.json>]

Per session:

* **M3 (SOFTWARE ESTIMATE):** the README §5.3 decomposition per arm from ``timing.jsonl`` (mixed-clock
  records are rejected); per sounded strike ``t_out - t_impact_est`` (the DAC path is excluded
  unless an accepted output-latency run is recorded).
* **Harness on the live session** (only with Phase 07 labels under ``--labels-root/<session_id>``):
  each arm's commits against the labels, in its own AIR blocks and in every AIR block including
  shadow commits. Gives live FP / FN / ``L_pred`` on scripted negatives, and the exploratory
  motion summary: ground-truth inward speed at impact per sounding arm.
* **M1** (a recording registered in ``live-session.json`` whose sync is OK): per-strike physical
  action-to-sound latency, attributed as-treated to the arm that sounded (the commit record's
  ``arm``); ambiguous strikes are excluded with a count.

Across sessions: the per-participant median latency per arm, then **H4** (C vs A) and **H4-B**
(B vs A) by the declared rule. ``U`` comes from the live lock's primary method, or from
``--rehearsal-method-u`` in a SYNTHETIC rehearsal. The sound-before-impact fraction per arm is also
reported. Without a GO method H4 is PENDING and no effective-latency number is produced
(README §5.4).
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from _p10 import write_json  # noqa: E402
from _p18 import ROOT, add_executor_args, evidence  # noqa: E402
from _p18_live import m1_session, pad_windows, read_json, strike_rows  # noqa: E402

from spacedrums.calib import load_calibrated_config  # noqa: E402
from spacedrums.data.labels.generate import read_labels  # noqa: E402
from spacedrums.eval.report import evaluate_session  # noqa: E402
from spacedrums.live_eval import hypotheses as hyp  # noqa: E402
from spacedrums.live_eval import offline, software  # noqa: E402
from spacedrums.live_eval.metadata import LiveSessionMetadata, consistency_errors  # noqa: E402

LIVE_LABELS = ("A", "B", "C")


def _live_label(arm: str, c_label: str) -> str | None:
    return {"A": "A", "B": "B"}.get(arm, "C" if arm == c_label else None)


def harness_live(
    session_dir: Path,
    live: dict[str, Any],
    base: dict[str, Any],
    labels: list[dict[str, Any]],
    c_label: str,
    w_s: float,
) -> dict[str, Any]:
    rows = strike_rows(session_dir)
    air = [b for b in live["arm_blocks"] if b["kind"] == "AIR" and b["analysed"] and b["status"] != "NOT_RUN"]
    seg_types = {s["segment_id"]: s for s in base["segments"]}
    out: dict[str, Any] = {}
    for label in LIVE_LABELS:
        arm_rows = [r for r in rows if _live_label(str(r["arm"]), c_label) == label]
        for scope, blocks in (
            ("own_blocks", [b for b in air if b["arm"] == label]),
            ("all_blocks_shadow", air),
        ):
            ids = {s for b in blocks for s in b["segment_ids"]}
            segments = [
                {
                    **seg_types[s],
                    "eligible": seg_types[s]["status"] == "RECORDED",
                    "hands": seg_types[s]["hands"],
                }
                for s in ids
                if s in seg_types and seg_types[s]["t_end"] is not None
            ]
            if not segments:
                out.setdefault(label, {})[scope] = None
                continue
            ev = evaluate_session(
                arm_rows,
                labels,
                segments,
                w_s=w_s,
                include_unreviewed_selftest=live["session_kind"] in ("SYNTHETIC", "DEV_CAPTURE"),
            )
            out.setdefault(label, {})[scope] = {
                "pooled": offline.pooled_metrics(
                    [
                        {
                            "evaluation": ev,
                            "strikes": arm_rows,
                            "labels": labels,
                            "session_id": live["session_id"],
                        }
                    ]
                ),
                "fp_by_segment_type": ev["pooled"]["fp_by_segment_type"],
            }
    motion = {}
    for block in air:
        lo, hi = block["t_start"], block["t_end"]
        speeds = [
            g["intensity_proxy_gt"]
            for g in labels
            if g.get("label_class") == "POSITIVE"
            and g.get("t_impact_est") is not None
            and lo <= g["t_impact_est"] < hi
            and g.get("intensity_proxy_gt") is not None
        ]
        motion.setdefault(block["arm"], []).extend(speeds)
    out["motion_exploratory"] = {
        arm: {"n": len(v), "median_inward_speed": float(np.median(v)) if v else None}
        for arm, v in sorted(motion.items())
    }
    out["motion_note"] = (
        "EXPLORATORY: ground-truth inward crossing speed per sounding arm "
        "(does anticipatory sound change strokes?)"
    )
    return out


def analyse_session(session_dir: Path, labels_root: Path | None, w_s: float) -> dict[str, Any]:
    live_meta = LiveSessionMetadata.read(session_dir)
    live = live_meta.data
    base = read_json(session_dir / "metadata.json")
    cfg = load_calibrated_config(session_dir / "config.snapshot.yaml").config
    c_label = "C-" + cfg["anticipator"]["model"]["family"].upper()
    streams = software.load_session_streams(session_dir)
    latency = (read_json(session_dir / "session.json").get("audio") or {}).get("output_latency") or {}
    accepted = latency.get("status") == "MEASURED"
    out: dict[str, Any] = {
        "session_id": live["session_id"],
        "participant_id": live["participant_id"],
        "kind": live["session_kind"],
        "label": live["evidence_label"],
        "consistency_errors": consistency_errors(live, session_dir),
        "arm_order": live["live_protocol"]["arm_order"],
        "blocks": [
            {k: b[k] for k in ("block_id", "arm", "kind", "status", "commits_by_arm")}
            for b in live["arm_blocks"]
        ],
        "m3_decomposition": software.decomposition(streams["timing"]),
    }
    labels = None
    if labels_root is not None and (labels_root / live["session_id"] / "labels.jsonl").exists():
        labels = read_labels(labels_root / live["session_id"] / "labels.jsonl")
    impact_ref = None
    if labels is not None:
        out["harness"] = harness_live(session_dir, live, base, labels, c_label, w_s)
        rows = strike_rows(session_dir)
        positives = [
            g for g in labels if g.get("label_class") == "POSITIVE" and g.get("t_impact_est") is not None
        ]
        from spacedrums.eval.matching import match_events

        m = match_events([r for r in rows if not r["shadow"]], positives, w_s=w_s)
        impact_ref = {s["strike_id"]: float(g["t_impact_est"]) for s, g in m.pairs}
    else:
        out["harness"] = None
        out["harness_note"] = "no Phase 07 labels for this session: live FP / FN / L_pred PENDING"
    out["m3_strikes"] = software.strike_estimates(
        streams["committed"], streams["audio"], output_latency_accepted=accepted, impact_reference=impact_ref
    )
    m1 = next((m for m in live["external_methods"] if m["method"] == "M1"), None)
    if m1 and m1["recordings"] and (m1.get("sync") or {}).get("status") == "OK":
        result = m1_session(
            session_dir, cfg, session_dir / m1["recordings"][0]["path"], pad_windows=pad_windows(base)
        )
        for s in result.get("strikes", []):
            s["live_arm"] = _live_label(str(s["arm"]), c_label)
        out["m1"] = result
    else:
        out["m1"] = None
        out["m1_note"] = "no M1 recording with an OK sync: external latencies not available for this session"
    return out


def aggregate(sessions: list[dict[str, Any]], method: dict[str, Any] | None) -> dict[str, Any]:
    per: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    excluded = defaultdict(int)
    for s in sessions:
        if not s.get("m1"):
            continue
        for strike in s["m1"].get("strikes", []):
            if strike["live_arm"] in LIVE_LABELS:
                per[s["participant_id"]][strike["live_arm"]].append(strike["latency_s"])
        for e in s["m1"].get("excluded", []):
            excluded[e["reason"]] += 1
    medians = {
        arm: {p: (float(np.median(v[arm])) if v.get(arm) else None) for p, v in per.items()}
        for arm in LIVE_LABELS
    }
    pooled = {arm: [x for v in per.values() for x in v.get(arm, [])] for arm in LIVE_LABELS}
    return {
        "per_participant_median_s": medians,
        "pooled": {
            arm: {
                "n": len(v),
                "median_s": float(np.median(v)) if v else None,
                "p10_s": float(np.percentile(v, 10)) if v else None,
                "p90_s": float(np.percentile(v, 90)) if v else None,
                "sound_before_impact_fraction": float(np.mean(np.asarray(v) < 0)) if v else None,
            }
            for arm, v in pooled.items()
        },
        "excluded_strikes": dict(excluded),
        "hypotheses": [
            hyp.h4(medians["C"], medians["A"], method=method, arm="C"),
            hyp.h4(medians["B"], medians["A"], method=method, arm="B"),
        ],
        "method": method,
        "latency_definitions": {
            "A": "L_sys (physical): sound onset - pad onset",
            "B": "TE_audio (physical)",
            "C": "TE_audio (physical)",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", type=Path, action="append", required=True)
    ap.add_argument("--labels-root", type=Path, default=None)
    ap.add_argument("--lock-live", type=Path, default=None, help="archived live lock (participant analysis)")
    ap.add_argument(
        "--rehearsal-method-u", type=float, default=None, help="SYNTHETIC rehearsal only: U for H4 (s)"
    )
    ap.add_argument("--w-s", type=float, default=0.05, help="matching W (the frozen W for participant data)")
    ap.add_argument("--offline-results", type=Path, default=None)
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-18")
    add_executor_args(ap)
    args = ap.parse_args()
    if args.lock_live is not None:
        lock = read_json(args.lock_live)
        primary = lock["live"]["primary_method"]
        method = None if primary is None else {**lock["live"]["methods"][primary], "method": primary}
    elif args.rehearsal_method_u is not None:
        method = {
            "status": "GO",
            "u_s": args.rehearsal_method_u,
            "method": "M1 (SYNTHETIC rehearsal value, not a validation)",
        }
    else:
        method = None
    with evidence(
        args, slug="analyze-live", task="18.5", description="Experiment 2 analysis", output=args.output
    ) as (run, _cfg):
        sessions = [analyse_session(d, args.labels_root, args.w_s) for d in args.session]
        kinds = {s["kind"] for s in sessions}
        if kinds & {"PARTICIPANT", "PILOT"} and args.rehearsal_method_u is not None:
            raise SystemExit("--rehearsal-method-u is refused for participant / pilot sessions")
        results = {
            "label": " / ".join(sorted({s["label"] for s in sessions})),
            "sessions": sessions,
            "aggregate": aggregate(sessions, method),
            "offline_expectation": read_json(args.offline_results)["arms"] if args.offline_results else None,
            "w_s": args.w_s,
        }
        write_json(run.dir / "live-results.json", results)
        for h in results["aggregate"]["hypotheses"]:
            print(f"[live] {h['id']}: {h['decision']} ({h['reading'][:90]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
