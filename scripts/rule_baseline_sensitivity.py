"""Phase 05 — SYNTHETIC sensitivity of the rule-based arm (B) to its provisional thresholds (Tasks 05.2/05.6).

    python scripts/rule_baseline_sensitivity.py [--noise 0.003]

Sweeps motion model (CV / CA), tracking filter (kalman_cv / kalman_ca), ``tti_commit_s`` and ``p_commit``
over labelled SYNTHETIC strike scenarios (two stroke speeds, rapid strokes) and the SYNTHETIC
"stop-before-impact" fake swing, and reports per configuration: rule-arm matched / missed / false
commits against the analytic crossings, lead time ``L_pred`` (vs the analytic crossing) and vs the
reactive arm, timing error, and the fake-swing false-positive count.

**What this is:** a deterministic sensitivity table on synthetic strokes so the threshold *rationale* in
``configs/prototype.candidate.yaml`` can be written down (which knobs matter, in which direction).
**What this is not:** tuning, optimisation or evidence about real strokes; the synthetic stroke shape
(constant-acceleration downstroke + symmetric rebound, no hand/stick appearance model) is arbitrary and
the numbers do not transfer to participants. Threshold values remain provisional until Phases 09/18.
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p05 import DEFAULT_CONFIG  # noqa: E402
from _runlog import RunLog  # noqa: E402

from spacedrums.app import AudioOutput, DecisionPipeline, OutputLatency  # noqa: E402
from spacedrums.app.session_summary import (  # noqa: E402
    commits_from_results,
    compare_arms,
    evaluate_against_truth,
)
from spacedrums.app.synthetic import scenario  # noqa: E402
from spacedrums.config import config_hash, deep_merge, load_config, validate  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402

SCENARIOS = (("repeated", 0.20), ("repeated", 0.12), ("rapid", 0.10))
FAKE = ("stop_short", 0.12)


def run_config(
    base: dict[str, Any],
    registry: ZoneRegistry,
    *,
    motion: str,
    filt: str,
    tti: float,
    p: float,
    noise: float,
    seed: int,
) -> dict[str, Any]:
    data = deep_merge(
        base,
        {
            "anticipator": {
                "rule": {"motion_model": motion},
                "anticipator_id": f"rule-{motion.lower()}-sweep",
            },
            "tracking": {"filter": {"type": filt}},
            "commit": {"tti_commit_s": tti, "p_commit": p},
        },
    )
    validate(data)
    chash = config_hash(data)
    out: dict[str, Any] = {
        "motion": motion,
        "filter": filt,
        "tti_commit_s": tti,
        "p_commit": p,
        "scenarios": {},
    }
    for name, t_down in (*SCENARIOS, FAKE):
        seq = scenario(name, registry, t_down=t_down, noise=noise, seed=seed)
        audio = AudioOutput(data, latency=OutputLatency.unmeasured(), device_enabled=False)
        pipe = DecisionPipeline(
            data,
            registry=registry,
            session_id="sweep",
            active_arm="B",
            shadow_arms=("A",),
            hardware_id="HW-01",
            config_hash=chash,
            audio=audio,
        )
        results = [pipe.step(s, o, t_now=s.t_frame_available) for s, o in seq]
        commits, cands = commits_from_results(
            [c for r in results for c in r.commits],
            [c for r in results for h in r.hands.values() for c in h.candidates],
        )
        ev = evaluate_against_truth(commits, cands, [t.to_dict() for t in seq.truth])
        cmp = compare_arms(commits, cands)
        b = ev["arms"].get(
            "B",
            {
                "n_commits": 0,
                "n_matched": 0,
                "false_positives": 0,
                "false_negatives": ev["n_truth"],
                "L_pred_s": {"median_s": None},
                "TE_s": {"median_s": None},
            },
        )
        out["scenarios"][f"{name}@{t_down}"] = {
            "n_truth": ev["n_truth"],
            "B_commits": b["n_commits"],
            "B_matched": b["n_matched"],
            "B_false_positives": b["false_positives"],
            "B_false_negatives": b["false_negatives"],
            "B_L_pred_vs_truth_median_s": b["L_pred_s"]["median_s"],
            "B_TE_median_s": b["TE_s"]["median_s"],
            "B_L_pred_vs_A_median_s": cmp["L_pred_B_vs_A_s"]["median_s"],
            "commit_advance_median_s": cmp["commit_advance_B_vs_A_s"]["median_s"],
            "A_commits": cmp["n_A"],
        }
    return out


def _ms(v: float | None) -> str:
    return "n/a" if v is None else f"{1000 * v:+.1f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiments-dir", type=Path, default=None)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument(
        "--noise", type=float, default=0.003, help="SYNTHETIC tip noise (ROI-norm, Gaussian sigma)"
    )
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--quick", action="store_true", help="smaller grid (tests)")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    registry = ZoneRegistry.from_config(cfg["zones"])
    grid = {
        "motion": ["CV", "CA"],
        "filter": ["kalman_cv", "kalman_ca"],
        "tti": [0.05, 0.10],
        "p": [0.3, 0.5],
    }
    if args.quick:
        grid = {"motion": ["CV", "CA"], "filter": ["kalman_cv"], "tti": [0.05], "p": [0.5]}
    desc = (
        "SYNTHETIC sensitivity of the rule-based arm to motion model, tracking filter, tti_commit_s and "
        "p_commit on "
        "synthetic strokes (not tuning; not real-stroke evidence; thresholds stay provisional)."
    )
    with RunLog(
        phase="05",
        task="05.6",
        slug="p05-rule-sensitivity-synthetic",
        config=cfg,
        experiments_dir=args.experiments_dir,
        description=desc,
        arm="B",
        seed=args.seed,
    ) as runlog:
        rows = []
        header = (
            "| motion | filter | tau_commit s | p_commit | "
            + " | ".join(f"{n}@{td}: matched/FN/FP L_pred(truth) L_pred(A) adv" for n, td in SCENARIOS)
            + " | fake-swing FP |"
        )
        print(header)
        print("|" + "---|" * (4 + len(SCENARIOS) + 1))
        for motion, filt, tti, p in itertools.product(grid["motion"], grid["filter"], grid["tti"], grid["p"]):
            r = run_config(
                cfg.data, registry, motion=motion, filt=filt, tti=tti, p=p, noise=args.noise, seed=args.seed
            )
            rows.append(r)
            cells = []
            for n, td in SCENARIOS:
                s = r["scenarios"][f"{n}@{td}"]
                cells.append(
                    f"{s['B_matched']}/{s['B_false_negatives']}/{s['B_false_positives']} "
                    f"{_ms(s['B_L_pred_vs_truth_median_s'])} {_ms(s['B_L_pred_vs_A_median_s'])} "
                    f"{_ms(s['commit_advance_median_s'])}"
                )
            fake = r["scenarios"][f"{FAKE[0]}@{FAKE[1]}"]["B_commits"]
            print(f"| {motion} | {filt} | {tti} | {p} | " + " | ".join(cells) + f" | {fake} |")
        runlog.write_json_artefact(
            "rule_sensitivity_synthetic.json",
            {
                "label": "SYNTHETIC sensitivity - not tuning, not real-stroke evidence",
                "noise": args.noise,
                "seed": args.seed,
                "grid": grid,
                "scenarios": [f"{n}@{td}" for n, td in (*SCENARIOS, FAKE)],
                "rows": rows,
            },
        )
        runlog.finish({"label": "SYNTHETIC", "n_configs": len(rows), "noise": args.noise, "seed": args.seed})
        print(
            f"\nRESULT: COMPLETED {runlog.run_id} (SYNTHETIC sensitivity; units ms; "
            "L_pred > 0 = before impact)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
