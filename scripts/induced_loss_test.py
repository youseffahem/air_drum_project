"""Phase 05, Task 05.8 — induced tracking-loss safety test, and its SYNTHETIC self-test.

Hard requirement (Q34-Q35, README section 8): **zero commits while a hand's status is not VALID**, correct
resets, and re-enabling after valid tracking returns.

Live mode (PERSON-DEPENDENT; a developer covers the camera / occludes one hand for controlled intervals
during and outside swings, including the ~100-300 ms range and longer):

    python scripts/induced_loss_test.py --live [--arm A|B]

records a session with the prototype and, at the end, counts commits on non-VALID frames from the
recorded ``TrackState`` / ``CommittedStrike`` streams (``session_summary.commits_during_non_valid``) and
prints the per-hand status trace with resets. The occlusion intervals themselves are the person's
actions; the script does not know when they happened — it verifies the invariant over the whole session.

SYNTHETIC self-test (no camera; used by ``tests/scripts``):

    python scripts/induced_loss_test.py --synthetic

injects occlusions of 100 / 200 / 300 / 500 ms into synthetic strike sequences (during a swing, right
before the crossing, and away from any swing) for each hand, runs the pipeline with A active + B shadow,
and asserts zero commits on non-VALID frames, the expected DEGRADED -> INVALID transitions (``g_max``)
and re-acquisition. Writes an experiment run with the state traces. Machinery evidence only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p05 import DEFAULT_CONFIG, ROOT  # noqa: E402
from _runlog import RunLog  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.app import AudioOutput, DecisionPipeline, OutputLatency  # noqa: E402
from spacedrums.app.main import build_parser, run  # noqa: E402
from spacedrums.app.session_summary import summarise_session  # noqa: E402
from spacedrums.app.synthetic import DT, Swing, build_sequence  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import HandId, TrackStatus  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402

LETTER = {TrackStatus.VALID: "V", TrackStatus.DEGRADED: "D", TrackStatus.INVALID: "I", TrackStatus.STALE: "S"}
LOSS_MS = (100, 200, 300, 500)


def live(args: argparse.Namespace) -> int:
    argv = [
        "--config",
        str(args.config),
        "--source",
        "live",
        "--record",
        "--output-dir",
        str(args.output_dir),
        "--session-id",
        args.session_id or f"dev-{timing.wall_clock_local_compact()}-induced-loss",
    ]
    if args.arm:
        argv += ["--arm", args.arm]
    meta = {
        "protocol": "phase-05-task-05.8-induced-loss",
        "developer_only": True,
        "instruction": "cover the camera / occlude one hand for ~100, 200, 300, 500+ ms during and outside "
        "swings; q to finish",
    }
    summary = run(
        build_parser().parse_args(argv),
        status_lines=lambda: ["INDUCED LOSS TEST: occlude a hand / cover the camera; q to finish"],
        session_meta=meta,
    )
    ss = summarise_session(summary["session_dir"])
    n_bad = ss["commits_during_non_valid"]
    print(
        f"[induced-loss] commits during non-VALID frames: {n_bad} -> {'PASS' if n_bad == 0 else 'FAIL'} "
        f"(recorded {summary['session_dir']}; status frames {ss['counts']['track_status_frames']})"
    )
    return 0 if n_bad == 0 else 1


def _cases(registry: ZoneRegistry) -> list[dict[str, Any]]:
    """Occlusion cases: (hand, when, duration) on a two-strike sequence per hand."""
    cases = []
    for hand, zone in ((HandId.RIGHT, "snare"), (HandId.LEFT, "hihat")):
        swings = [Swing(hand, zone, 0.4, t_down=0.12), Swing(hand, zone, 1.4, t_down=0.12)]
        truth_frame = int(round((0.4 + 0.0906) / DT))  # analytic crossing of the first swing (~0.49 s)
        for ms in LOSS_MS:
            n = max(1, int(round(ms / 1000 / DT)))
            for when, start in (
                ("during_swing", truth_frame - n + 1),
                ("before_crossing", truth_frame - n - 1),
                ("outside_swing", int(round(0.9 / DT))),
            ):
                cases.append(
                    {
                        "hand": hand,
                        "zone": zone,
                        "loss_ms": ms,
                        "when": when,
                        "frames": set(range(start, start + n)),
                        "swings": swings,
                    }
                )
    return cases


def synthetic(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    registry = ZoneRegistry.from_config(cfg["zones"])
    desc = (
        "Task 05.8 SYNTHETIC self-test: occlusions of 100/200/300/500 ms injected during / before / outside "
        "synthetic swings for each hand; zero commits on non-VALID frames, DEGRADED->INVALID after g_max, "
        "re-acquisition. Machinery evidence only; the live induced-loss test remains PENDING."
    )
    with RunLog(
        phase="05",
        task="05.8",
        slug="p05-induced-loss-synthetic",
        config=cfg,
        experiments_dir=args.experiments_dir,
        description=desc,
        arm="A",
    ) as runlog:
        g_max = int(cfg["tracking"]["g_max_frames"])
        rows: list[dict[str, Any]] = []
        total_bad = 0
        for case in _cases(registry):
            hand = case["hand"]
            seq = build_sequence(
                registry,
                case["swings"],
                duration_s=2.4,
                occluded={hand: case["frames"]},
                name=f"loss-{hand}-{case['loss_ms']}-{case['when']}",
            )
            audio = AudioOutput(cfg.data, latency=OutputLatency.unmeasured(), device_enabled=False)
            pipe = DecisionPipeline(
                cfg.data,
                registry=registry,
                session_id="synthetic-loss",
                active_arm="A",
                shadow_arms=("B",),
                hardware_id="HW-01",
                config_hash=cfg.config_hash,
                audio=audio,
            )
            trace, bad, commits = [], 0, []
            for sample, obs in seq:
                r = pipe.step(sample, obs, t_now=sample.t_frame_available)
                st = r.hands[hand].track.status
                trace.append(LETTER[st])
                for c in r.commits:
                    commits.append(
                        (c.arm.value, c.hand_id.value, c.frame_id, LETTER[r.hands[c.hand_id].track.status])
                    )
                    if r.hands[c.hand_id].track.status is not TrackStatus.VALID:
                        bad += 1
            n_occ = len(case["frames"])
            expect_invalid = n_occ > g_max
            resets = [
                (x["frame_id"], x["reason"])
                for x in pipe.counters()["tracker_resets"][str(hand)]
                if x["frame_id"] is not None
            ]
            trace_s = "".join(trace)
            # re-acquired: the hand returns to VALID after the loss (and stays VALID at the end)
            reacquired = trace_s.endswith("V") and (
                (("I" in trace_s) and "IV" in trace_s) if expect_invalid else ("DV" in trace_s)
            )
            ok = bad == 0 and (("I" in trace_s) == expect_invalid) and reacquired
            total_bad += bad
            rows.append(
                {
                    "hand": str(hand),
                    "loss_ms": case["loss_ms"],
                    "when": case["when"],
                    "occluded_frames": n_occ,
                    "expect_invalid": expect_invalid,
                    "trace": trace_s,
                    "resets": resets,
                    "commits": commits,
                    "commits_during_non_valid": bad,
                    "ok": ok,
                }
            )
            print(
                f"{str(hand):5s} {case['loss_ms']:3d} ms {case['when']:16s} occl={n_occ:2d} "
                f"{'INVALID' if expect_invalid else 'bridged'}: {trace_s} bad={bad} {'OK' if ok else 'FAIL'}"
            )
        all_ok = all(r["ok"] for r in rows)
        runlog.write_json_artefact(
            "induced_loss_synthetic.json",
            {
                "label": "SYNTHETIC - machinery self-test; live induced-loss test PENDING",
                "g_max_frames": g_max,
                "cases": rows,
            },
        )
        runlog.finish(
            {
                "label": "SYNTHETIC",
                "n_cases": len(rows),
                "commits_during_non_valid": total_bad,
                "all_cases_ok": all_ok,
            }
        )
        print(
            f"\ncommits during non-VALID frames: {total_bad}; "
            f"cases ok: {sum(r['ok'] for r in rows)}/{len(rows)}"
        )
        print(f"RESULT: {'COMPLETED' if all_ok else 'FAILED'} {runlog.run_id} (SYNTHETIC self-test)")
    return 0 if all_ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiments-dir", type=Path, default=None)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="PERSON-DEPENDENT developer test with the camera")
    mode.add_argument("--synthetic", action="store_true", help="SYNTHETIC self-test (no camera)")
    ap.add_argument("--arm", choices=("A", "B"), default=None)
    ap.add_argument("--output-dir", type=Path, default=ROOT / "data" / "dev-sessions")
    ap.add_argument("--session-id", default=None)
    args = ap.parse_args(argv)
    return live(args) if args.live else synthetic(args)


if __name__ == "__main__":
    sys.exit(main())
