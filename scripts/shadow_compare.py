"""Phase 05, Task 05.10 — informal Baseline B (shadow) vs Baseline A comparison on a recorded session.

    python scripts/shadow_compare.py --session-dir data/dev-sessions/<session_id> [--window-s 0.10]
    python scripts/shadow_compare.py --synthetic       # SYNTHETIC self-test (temporary synthetic session)

For every rule-arm commit (B, active or shadow) the reactive arm's observed crossing (``t_impact_est``
of the matched A commit, same hand, within ``--window-s``) is the reference:

    L_pred  = t_impact_est(A) - t_commit(B)      (README 5.4 sign: positive = committed before the crossing)
    advance = t_commit(A)     - t_commit(B)      (how much earlier B committed than A)
    TE_pred = t_impact_pred(B) - t_impact_est(A)

**"Developer sanity check — not an experimental result."** The reactive arm is a *reference*, not ground
truth (Phase 07 labels are), the developer session is not participant data, and the matching window is a
provisional value (Phase 09 sweeps it). Writes an experiment run with the pair table.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p05 import DEFAULT_CONFIG, run_synthetic_session  # noqa: E402
from _runlog import RunLog  # noqa: E402

from spacedrums.app.session_summary import DEFAULT_WINDOW_S, summarise_session  # noqa: E402
from spacedrums.config import load_config  # noqa: E402


def _fmt(st: dict, key: str = "median_s") -> str:
    v = st.get(key)
    return "n/a" if v is None else f"{1000 * v:+.1f} ms"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiments-dir", type=Path, default=None)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--session-dir", type=Path, default=None)
    mode.add_argument("--synthetic", action="store_true")
    ap.add_argument(
        "--window-s", type=float, default=DEFAULT_WINDOW_S, help="matching tolerance W (provisional)"
    )
    ap.add_argument("--hardware-id", default="HW-01")
    args = ap.parse_args(argv)

    tmp: Path | None = None
    try:
        if args.synthetic:
            tmp = Path(tempfile.mkdtemp(prefix="p05-shadow-synth-"))
            summary = run_synthetic_session(
                "rapid",
                out_dir=tmp,
                session_id="synthetic-shadow",
                active="A",
                shadow=("B",),
                config=args.config,
            )
            session_dir = Path(summary["session_dir"])
            cfg = load_config(args.config)
        else:
            session_dir = args.session_dir
            snapshot = session_dir / "config.snapshot.yaml"
            cfg = load_config(snapshot if snapshot.exists() else args.config)
        ss = summarise_session(session_dir, window_s=args.window_s)
        cmp = ss["arm_comparison"]
        label = "SYNTHETIC self-test" if args.synthetic else f"developer session {session_dir.name}"
        desc = (
            f"Task 05.10 informal B-vs-A comparison on {label}: developer sanity check - not an experimental "
            f"result; reactive arm as reference; W = {args.window_s} s (provisional)."
        )
        with RunLog(
            phase="05",
            task="05.10",
            slug="p05-shadow-compare" + ("-synthetic" if args.synthetic else ""),
            config=cfg,
            experiments_dir=args.experiments_dir,
            description=desc,
            arm="B",
            hardware_id=args.hardware_id,
        ) as runlog:
            print(
                f"session: {session_dir}  A commits={cmp['n_A']}  B commits={cmp['n_B']}  "
                f"matched={cmp['n_matched']}  "
                f"B unmatched={cmp['n_B_unmatched']}  A unmatched={cmp['n_A_unmatched']}  W={args.window_s} s"
            )
            print("| quantity | n | median | p10 | p90 |")
            print("|---|---|---|---|---|")
            for name, key in (
                ("L_pred (B vs A crossing)", "L_pred_B_vs_A_s"),
                ("commit advance (A - B)", "commit_advance_B_vs_A_s"),
                ("TE_pred (B vs A crossing)", "TE_pred_B_vs_A_s"),
                ("L_pred of A itself", "L_pred_A_s"),
            ):
                st = cmp[key]
                print(f"| {name} | {st['n']} | {_fmt(st)} | {_fmt(st, 'p10_s')} | {_fmt(st, 'p90_s')} |")
            print(
                f"zone agreement: {cmp['zone_agreement']}; fraction of B commits before the A crossing: "
                f"{cmp['L_pred_B_positive_fraction']}"
            )
            print(f"LABEL: {cmp['label']}")
            runlog.write_json_artefact(
                "shadow_compare.json",
                {
                    "label": "SYNTHETIC"
                    if args.synthetic
                    else "developer sanity check - not an experimental result",
                    "session_dir": str(session_dir),
                    "comparison": cmp,
                    "counts": ss["counts"],
                },
            )
            runlog.finish(
                {
                    "label": "SYNTHETIC" if args.synthetic else "developer-sanity-check",
                    "n_A": cmp["n_A"],
                    "n_B": cmp["n_B"],
                    "n_matched": cmp["n_matched"],
                    "L_pred_B_vs_A_median_s": cmp["L_pred_B_vs_A_s"]["median_s"],
                    "commit_advance_median_s": cmp["commit_advance_B_vs_A_s"]["median_s"],
                    "window_s": args.window_s,
                }
            )
            print(f"\nRESULT: COMPLETED {runlog.run_id}")
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
