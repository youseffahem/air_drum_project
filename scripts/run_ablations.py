"""Phase 19 PREPARATION ONLY. Synthetic tests, dependency preflight and report regeneration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _p10 import source_hashes, write_json
from _p18 import add_executor_args, execution
from _runlog import RunLog, git_dirty, git_sha

from spacedrums.ablation.config import read_plan
from spacedrums.ablation.guards import DependencyError, dependency_errors, refuse_experimental_execution
from spacedrums.ablation.report import render
from spacedrums.config import config_hash, load_config
from spacedrums.live_eval.prereg import file_digest

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    modes = ap.add_mutually_exclusive_group(required=True)
    modes.add_argument("--synthetic-dev", action="store_true")
    modes.add_argument("--check-dependencies", action="store_true")
    modes.add_argument("--execute", action="store_true", help="always refused in preparation")
    modes.add_argument("--regenerate", type=Path, help="stored SYNTHETIC/DEV results.json")
    ap.add_argument("--reference", type=Path)
    ap.add_argument("--plan", type=Path, default=ROOT / "configs/ablations/synthetic-dev.yaml")
    ap.add_argument("--output", type=Path, default=ROOT / "experiments/phase-19")
    add_executor_args(ap)
    args = ap.parse_args(argv)
    if args.execute:
        # Refuse before opening even a user-supplied plan/reference/data file.
        try:
            refuse_experimental_execution()
        except DependencyError as exc:
            ap.error(str(exc))
    if args.check_dependencies:
        ref = None if args.reference is None else json.loads(args.reference.read_text(encoding="utf-8"))
        errors = dependency_errors(ref, args.reference.parent if args.reference else ROOT)
        print(
            json.dumps(
                {
                    "status": "BLOCKED" if errors else "INPUTS_PRESENT_EXECUTION_STILL_DISABLED",
                    "experimental_execution": False,
                    "errors": errors,
                },
                indent=2,
            )
        )
        return 2 if errors else 0
    if args.reference is not None:
        ap.error("synthetic/regeneration modes do not accept a participant reference")
    if args.regenerate:
        result = json.loads(args.regenerate.read_text(encoding="utf-8"))
        target = args.output / "regenerated-synthetic-report"
        if target.exists():
            ap.error("regeneration target exists; choose a fresh --output")
        manifest = render(result, target)
        write_json(target / "report-manifest.json", manifest)
        return 0
    plan = read_plan(args.plan)
    if plan["evidence"] != "SYNTHETIC/DEV":
        ap.error("--synthetic-dev requires a SYNTHETIC/DEV plan")
    from _p19 import run_synthetic

    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    with RunLog(
        phase="19",
        task="19.2",
        slug="synthetic-dev",
        config=cfg,
        description="SYNTHETIC/DEV ONLY: Phase 19 preparation, never participant evidence",
        experiments_dir=args.output,
        seed=plan["seeds"][0],
        camera_model="none: generated fixture",
        audio_device="none",
    ) as run:
        initial = source_hashes()
        context = execution(args)
        write_json(run.dir / "execution.json", context)
        write_json(run.dir / "source-hashes.json", initial)
        write_json(run.dir / "plan.json", plan)
        result = run_synthetic(plan, cfg, run.dir, context)
        write_json(run.dir / "results.json", result)
        write_json(run.dir / "report-manifest.json", render(result, run.dir / "report"))
        audit = {
            "source_unchanged": source_hashes() == initial,
            "git_sha_final": git_sha(),
            "git_dirty_final": git_dirty(),
            "evidence": "SYNTHETIC/DEV",
            "experimental_execution": False,
            "plan_sha256": config_hash(plan),
            "results_sha256": file_digest(run.dir / "results.json"),
        }
        write_json(run.dir / "audit.json", audit)
        if not audit["source_unchanged"]:
            raise RuntimeError("source changed during synthetic development check")
        for path in sorted(run.dir.rglob("*")):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.record.update(
            dataset_version="ds-selftest-v0.0",
            dataset_hash=result["dataset"]["manifest_hash"],
            deterministic=True,
            split={"scheme": "SYNTHETIC/DEV CV"},
        )
        run.finish(
            {"preparation_checks": len(result["cells"])}, notes="SYNTHETIC/DEV only; Phase 18 PENDING."
        )
        print(f"EVIDENCE: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
