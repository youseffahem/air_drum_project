"""Compare recorded app.play sessions (e.g. --fingers vs --red-tips) against counted ground truth.

    python scripts/compare_play_sessions.py \
        --run fingers data/dev-product/<session> snare=16 \
        --run sticks  data/dev-product/<session> snare=16 \
        --run sticks  data/dev-product/<session> none \
        --output comparison.json

Each ``--run MODE DIR EXPECT`` is one recorded block. ``EXPECT`` is the strikes the player counted, e.g.
``snare=16`` or ``hihat=8,snare=8``, or ``none`` for an idle block (moving between drums without
striking). Per block and per mode the script reports:

* strikes: correct (min(commits, expected) per drum), missed (expected not reached), false (commits on
  drums not in the block, commits beyond the expected count, every idle-block commit) and duplicates
  (two commits on the same drum less than ``--duplicate-ms`` apart). A count can hide a miss plus a
  false hit on the same drum; the timed duplicate check catches the double-trigger case only.
* tracking continuity: per hand, the share of frames with a MEASURED tip after its first measurement,
  and the distribution of detection gaps (consecutive frames without one).
* processing: perception / decision / whole-frame ms, delivered FPS and the software
  capture-to-audio-schedule latency logged by the app. That is not acoustic action-to-sound latency.

Nothing is measured here: it only reads what the app logged. Developer evidence only.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HANDS = ("LEFT", "RIGHT")


def parse_expect(text: str) -> dict[str, int]:
    if text.strip().lower() == "none":
        return {}
    out = {}
    for part in text.split(","):
        zone, _, n = part.partition("=")
        if not zone.strip() or not n.strip().isdigit():
            raise argparse.ArgumentTypeError(f"expected DRUM=N[,DRUM=N...] or none, got {text!r}")
        out[zone.strip()] = int(n)
    return out


def distribution(values):
    if not values:
        return None
    p50, p95, top = (round(float(v), 3) for v in np.percentile(values, [50, 95, 100]))
    return {"n": len(values), "p50": p50, "p95": p95, "max": top}


def analyse_run(mode: str, directory: Path, expect: dict[str, int], duplicate_s: float) -> dict:
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    lines = (directory / "observations.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    commits = [c for r in rows for c in r["commits"]]
    counts = Counter(c["zone_id"] for c in commits)
    correct = sum(min(counts[z], n) for z, n in expect.items())
    missed = sum(max(0, n - counts[z]) for z, n in expect.items())
    wrong_zone = sum(n for z, n in counts.items() if z not in expect)
    excess = sum(max(0, counts[z] - n) for z, n in expect.items())
    duplicates = 0
    by_zone = defaultdict(list)
    for c in commits:
        by_zone[c["zone_id"]].append(c["t_impact_target"])
    for times in by_zone.values():
        times.sort()
        duplicates += sum(b - a < duplicate_s for a, b in zip(times, times[1:], strict=False))
    measured = {h: 0 for h in HANDS}
    after = {h: 0 for h in HANDS}
    gaps = {h: [] for h in HANDS}
    run = dict.fromkeys(HANDS, 0)
    seen = dict.fromkeys(HANDS, False)
    for r in rows:
        kinds = {e["hand_id"]: e["kind"] for e in r["endpoints"]}
        for h in HANDS:
            ok = kinds.get(h) == "MEASURED"
            if ok:
                if seen[h] and run[h]:
                    gaps[h].append(run[h])
                seen[h], run[h] = True, 0
                measured[h] += 1
            elif seen[h]:
                run[h] += 1
            after[h] += seen[h]
    latency = report.get("latency_ms") or {}

    def p(key, q):
        return (latency.get(key) or {}).get(q)

    minutes = len(rows) / 30.0 / 60.0
    return {
        "mode": mode, "session": str(directory), "frames": len(rows), "expected": expect,
        "tip_method": report.get("tip_method", "AXIS_REFINED"),
        "commits_by_drum": dict(counts), "correct": correct, "missed": missed,
        "false": wrong_zone + excess, "wrong_zone": wrong_zone, "excess": excess, "duplicates": duplicates,
        "false_per_minute_at_30fps": (wrong_zone + excess) / minutes if minutes else None,
        "continuity": {h: {"measured_share_after_first": measured[h] / after[h] if after[h] else None,
                           "gap_frames": distribution(gaps[h])} for h in HANDS},
        "fps": report.get("live_unique_fps") or report.get("source_timeline_fps"),
        "perception_ms": {"p50": p("perception_ms", "p50"), "p95": p("perception_ms", "p95")},
        "decision_ms": {"p50": p("decision_ms", "p50"), "p95": p("decision_ms", "p95")},
        "frame_work_ms": {"p50": p("frame_work_ms", "p50"), "p95": p("frame_work_ms", "p95")},
        "capture_to_schedule_ms": {"p50": p("capture_to_schedule_ms", "p50"),
                                   "p95": p("capture_to_schedule_ms", "p95")},
        "error": report.get("error"),
    }


def aggregate(runs: list[dict]) -> dict:
    modes = {}
    for mode in dict.fromkeys(r["mode"] for r in runs):
        rs = [r for r in runs if r["mode"] == mode]
        expected = sum(sum(r["expected"].values()) for r in rs)
        correct = sum(r["correct"] for r in rs)
        shares = {h: [r["continuity"][h]["measured_share_after_first"] for r in rs
                      if r["continuity"][h]["measured_share_after_first"] is not None] for h in HANDS}

        def median(key, q="p50", runs_=rs):
            values = [r[key][q] for r in runs_ if r[key][q] is not None]
            return float(np.median(values)) if values else None

        modes[mode] = {
            "runs": len(rs), "expected": expected, "correct": correct,
            "recall": correct / expected if expected else None,
            "missed": sum(r["missed"] for r in rs), "false": sum(r["false"] for r in rs),
            "wrong_zone": sum(r["wrong_zone"] for r in rs), "duplicates": sum(r["duplicates"] for r in rs),
            "measured_share_median": {h: float(np.median(v)) if v else None for h, v in shares.items()},
            "perception_ms_p50_median": median("perception_ms"),
            "frame_work_ms_p50_median": median("frame_work_ms"),
            "capture_to_schedule_ms_p50_median": median("capture_to_schedule_ms"),
            "fps_median": float(np.median([r["fps"] for r in rs if r["fps"]])) if any(r["fps"] for r in rs)
            else None,
        }
    return modes


def table(modes: dict) -> str:
    def fmt(v, pattern="{:.1f}"):
        return "-" if v is None else pattern.format(v)

    lines = ["| mode | runs | expected | correct | missed | false | wrong zone | duplicates | recall | "
             "measured L / R | perception p50 ms | capture->schedule p50 ms | FPS |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for mode, m in modes.items():
        share = " / ".join(fmt(m["measured_share_median"][h], "{:.0%}") for h in HANDS)
        lines.append(
            f"| {mode} | {m['runs']} | {m['expected']} | {m['correct']} | {m['missed']} | {m['false']} | "
            f"{m['wrong_zone']} | {m['duplicates']} | {fmt(m['recall'], '{:.0%}')} | {share} | "
            f"{fmt(m['perception_ms_p50_median'])} | {fmt(m['capture_to_schedule_ms_p50_median'])} | "
            f"{fmt(m['fps_median'])} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", nargs=3, action="append", required=True, metavar=("MODE", "DIR", "EXPECT"))
    ap.add_argument("--duplicate-ms", type=float, default=60.0)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    runs = [analyse_run(mode, Path(d), parse_expect(e), args.duplicate_ms / 1000) for mode, d, e in args.run]
    result = {"participant_evidence": False, "runs": runs, "modes": aggregate(runs)}
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(table(result["modes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
