"""Phase 05, Task 05.7 — hit-type verification protocol (developer session), and its SYNTHETIC self-test.

Live mode (PERSON-DEPENDENT; needs a developer with two ordinary sticks at the camera):

    python scripts/playability_session.py --live [--arm A|B] [--seconds-per-segment 20]

runs the prototype (``spacedrums.app.main``) in record mode through the scripted segments below, shows
the current instruction in the window, and stores the segment boundaries (``t_mono``) in the session's
``session.json`` so the recording can be reviewed segment by segment. Counting committed strikes per
segment and the manual review of misses/extras (Task 05.7 evidence) is done afterwards on the recording
(``scripts/shadow_compare.py`` / ``scripts/timing_summary.py`` for the tables; the manual miss/extra
review is a person's judgement and is entered into ``docs/reports/phase-05-playability.md``).
Recordings go to ``data/dev-sessions/`` (developer only; never a dataset).

SYNTHETIC self-test (no camera, no person; used by ``tests/scripts``):

    python scripts/playability_session.py --synthetic

runs every hit-type scenario of ``spacedrums.app.synthetic`` through the same pipeline with A active and
B shadow, evaluates both arms against the analytic SYNTHETIC crossings and writes an experiment run
with the per-hit-type table. **Those counts are unit-test evidence for the machinery, not a playability
result** — the playability report's per-hit-type counts stay PENDING until the live protocol has been
run by a person.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p05 import DEFAULT_CONFIG, ROOT, hit_type_table, run_synthetic_session  # noqa: E402
from _runlog import RunLog  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.app.main import build_parser, run  # noqa: E402
from spacedrums.config import load_config  # noqa: E402

# (segment_id, instruction shown to the developer, duration in seconds) — Phase 05 document, Task 05.7
SEGMENTS: list[tuple[str, str]] = [
    ("single_snare_R", "SINGLE hits on SNARE, RIGHT hand, ~1 per second"),
    ("single_snare_L", "SINGLE hits on SNARE, LEFT hand, ~1 per second"),
    ("single_hihat_R", "SINGLE hits on HI-HAT, RIGHT hand"),
    ("single_hihat_L", "SINGLE hits on HI-HAT, LEFT hand"),
    ("single_tom1_R", "SINGLE hits on TOM 1, RIGHT hand"),
    ("single_tom1_L", "SINGLE hits on TOM 1, LEFT hand"),
    ("single_crash_R", "SINGLE hits on CRASH/RIDE, RIGHT hand"),
    ("single_crash_L", "SINGLE hits on CRASH/RIDE, LEFT hand"),
    ("alternating_snare", "ALTERNATING L/R on SNARE"),
    ("alternating_two_zones", "ALTERNATING: RIGHT on SNARE, LEFT on HI-HAT"),
    ("repeated_increasing", "REPEATED hits on SNARE, RIGHT, slowly increasing the rate"),
    ("rapid", "RAPID consecutive hits on SNARE (as fast as you comfortably can)"),
    ("near_simultaneous", "NEAR-SIMULTANEOUS: both hands hit SNARE + TOM 1 together"),
    ("move_between_zones", "MOVE the sticks between zones WITHOUT striking"),
    ("fake_swings", "FAKE swings above the zones (no strike)"),
    ("stop_before_impact", "Swing towards the SNARE and STOP just before the surface"),
]
SYNTHETIC_SCENARIOS = [
    "single",
    "repeated",
    "rapid",
    "alternating_one_zone",
    "alternating_two_zones",
    "near_simultaneous",
    "between_zones",
    "stop_short",
    "hover",
    "lateral",
    "upward",
    "slow",
]


def live(args: argparse.Namespace) -> int:
    seg_s = float(args.seconds_per_segment)
    schedule = [
        {"segment_id": sid, "instruction": text, "t_start": None, "t_end": None} for sid, text in SEGMENTS
    ]
    state = {"index": -1, "t_next": None}
    meta: dict[str, Any] = {
        "protocol": "phase-05-task-05.7-hit-types",
        "segments": schedule,
        "seconds_per_segment": seg_s,
        "developer_only": True,
        "note": "developer session; NOT participant data; hit counts by manual review",
    }

    def on_frame(sample, result, pipeline) -> bool:
        now = timing.now()
        if state["t_next"] is None or now >= state["t_next"]:
            if state["index"] >= 0:
                schedule[state["index"]]["t_end"] = now
            state["index"] += 1
            if state["index"] >= len(schedule):
                return False
            schedule[state["index"]]["t_start"] = now
            state["t_next"] = now + seg_s
            print(
                f"[protocol] segment {state['index'] + 1}/{len(schedule)}: "
                f"{schedule[state['index']]['instruction']}"
            )
        return True

    def status_lines() -> list[str]:
        i = state["index"]
        if i < 0 or i >= len(schedule):
            return ["protocol finished - press q"]
        remaining = max(0.0, (state["t_next"] or 0.0) - timing.now())
        return [
            f"[{i + 1}/{len(schedule)}] {schedule[i]['instruction']}",
            f"{remaining:4.1f} s left in this segment",
        ]

    argv = [
        "--config",
        str(args.config),
        "--source",
        "live",
        "--record",
        "--output-dir",
        str(args.output_dir),
        "--session-id",
        args.session_id or f"dev-{timing.wall_clock_local_compact()}-playability",
    ]
    if args.arm:
        argv += ["--arm", args.arm]
    summary = run(
        build_parser().parse_args(argv), on_frame=on_frame, status_lines=status_lines, session_meta=meta
    )
    print(
        f"[protocol] recorded {summary.get('session_dir')}; now review the recording segment by segment "
        "and fill "
        f"docs/reports/phase-05-playability.md (per-hit-type counts are MEASURED on the developer only)"
    )
    return 0


def synthetic(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    tmp = Path(tempfile.mkdtemp(prefix="p05-playability-synth-"))
    desc = (
        "Task 05.7 SYNTHETIC self-test: every hit-type scenario of spacedrums.app.synthetic through the "
        "prototype pipeline (A active, B shadow), evaluated against analytic SYNTHETIC crossings. Machinery "
        "evidence only - NOT a playability result; live per-hit-type counts remain PENDING."
    )
    try:
        with RunLog(
            phase="05",
            task="05.7",
            slug="p05-playability-synthetic",
            config=cfg,
            experiments_dir=args.experiments_dir,
            description=desc,
            arm="A",
        ) as runlog:
            evaluations: dict[str, Any] = {}
            comparisons: dict[str, Any] = {}
            safety = 0
            for name in SYNTHETIC_SCENARIOS:
                summary = run_synthetic_session(
                    name,
                    out_dir=tmp,
                    session_id=f"synthetic-{name}",
                    active="A",
                    shadow=("B",),
                    config=args.config,
                )
                ss = summary["session_summary"]
                evaluations[name] = ss["synthetic_truth_evaluation"]
                comparisons[name] = {k: v for k, v in ss["arm_comparison"].items() if k != "pairs"}
                safety += ss["commits_during_non_valid"]
            table = hit_type_table(evaluations)
            print("\n".join(table))
            print(f"commits during non-VALID frames (all scenarios): {safety}")
            runlog.write_json_artefact(
                "playability_synthetic.json",
                {
                    "label": "SYNTHETIC - machinery self-test; not a playability result",
                    "scenarios": SYNTHETIC_SCENARIOS,
                    "evaluations": evaluations,
                    "arm_comparison": comparisons,
                    "commits_during_non_valid": safety,
                    "table_markdown": "\n".join(table),
                },
            )
            totals = {
                arm: {
                    k: sum(ev["arms"][arm][k] for ev in evaluations.values() if arm in ev["arms"])
                    for k in ("n_commits", "n_matched", "false_positives", "false_negatives", "duplicates")
                }
                for arm in ("A", "B")
            }
            runlog.finish(
                {
                    "label": "SYNTHETIC",
                    "n_scenarios": len(SYNTHETIC_SCENARIOS),
                    "n_truth": sum(ev["n_truth"] for ev in evaluations.values()),
                    "totals": totals,
                    "commits_during_non_valid": safety,
                }
            )
            print(f"\nRESULT: COMPLETED {runlog.run_id} (SYNTHETIC self-test)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiments-dir", type=Path, default=None)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--live", action="store_true", help="PERSON-DEPENDENT developer protocol with the camera"
    )
    mode.add_argument("--synthetic", action="store_true", help="SYNTHETIC self-test (no camera)")
    ap.add_argument("--arm", choices=("A", "B"), default=None)
    ap.add_argument("--seconds-per-segment", type=float, default=20.0)
    ap.add_argument("--output-dir", type=Path, default=ROOT / "data" / "dev-sessions")
    ap.add_argument("--session-id", default=None)
    args = ap.parse_args(argv)
    return live(args) if args.live else synthetic(args)


if __name__ == "__main__":
    sys.exit(main())
