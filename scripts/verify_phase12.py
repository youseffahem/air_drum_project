"""Re-run Phase 12 executable gate checks without changing Git history or reading test participants."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _p10 import provenance, source_hashes, write_json
from _p12 import NOT_CODEX, predeclaration_record
from _runlog import RunLog, git_dirty, git_sha, sha256_file

from spacedrums.config import load_config
from spacedrums.contracts.schema import validate

ROOT = Path(__file__).resolve().parents[1]
# Phase 04/05/09 frozen components and the Phase 10/11 model code Phase 12 must not modify.
FROZEN = (
    "src/spacedrums/geometry/__init__.py",
    "src/spacedrums/geometry/impact.py",
    "src/spacedrums/geometry/intersect.py",
    "src/spacedrums/geometry/zones.py",
    "src/spacedrums/commit",
    "src/spacedrums/eval/matching.py",
    "src/spacedrums/eval/metrics.py",
    "src/spacedrums/eval/report.py",
    "src/spacedrums/eval/selection.py",
    "src/spacedrums/eval/constants.py",
    "src/spacedrums/eval/temporal.py",
    "src/spacedrums/models/temporal/adapter.py",
    "src/spacedrums/models/temporal/config.py",
    "src/spacedrums/models/temporal/consistency.py",
    "src/spacedrums/models/temporal/data.py",
    "src/spacedrums/models/temporal/decode.py",
    "src/spacedrums/models/temporal/export.py",
    "src/spacedrums/models/temporal/gru.py",
    "src/spacedrums/models/temporal/heads.py",
    "src/spacedrums/models/temporal/losses.py",
    "src/spacedrums/models/temporal/mt_adapter.py",
    "src/spacedrums/models/temporal/mt_train.py",
    "src/spacedrums/models/temporal/tcn.py",
    "src/spacedrums/models/temporal/train.py",
)
# Additive Phase 12 harness change: the C-TT arm label in the replay.
EXTENDED = ("src/spacedrums/eval/replay.py",)


def representative_cells(directory, plan, rows):
    """One reproduction per (variant, family): the first trained cell of each."""
    seen, picked = set(), []
    for cell, row in zip(plan["cells"], rows, strict=False):
        key = (cell["variant"], cell["family"])
        if key in seen:
            continue
        seen.add(key)
        picked.append((key, row["model_dir"], Path(cell["fold_dir"]) / "samples.val.npz"))
    return picked


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-clean", action="store_true")
    ap.add_argument("--runs", type=Path, nargs="*", default=[], help="completed Phase 12 run directories")
    ap.add_argument("--experiments-dir", type=Path, default=ROOT / "experiments/phase-12")
    args = ap.parse_args()
    if args.require_clean and git_dirty():
        ap.error("owner commit required before --require-clean")
    python, binary = sys.executable, Path(sys.executable).parent
    commands = [
        [python, "-m", "pytest", "-o", "addopts=", "-q", "--strict-markers"],
        [str(binary / "ruff.exe"), "check", "."],
        [str(binary / "lint-imports.exe"), "--config", ".importlinter"],
        [python, "scripts/validate_contracts.py"],
        [python, "scripts/env_smoke.py"],
        ["git", "diff", "--check"],
    ]
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    with RunLog(
        phase="12",
        task="12.8",
        slug="p12-gate-verification",
        config=cfg,
        experiments_dir=args.experiments_dir,
        description="Development gate checks; participant evidence/owner decisions remain pending",
    ) as run:
        context, hashes = {**provenance(), **NOT_CODEX}, source_hashes()
        write_json(run.dir / "execution.json", context)
        write_json(run.dir / "source-hashes.json", hashes)
        evidence = []
        for directory in args.runs:
            record = json.loads((directory / "run.json").read_text(encoding="utf-8"))
            validate("experiment-log", record)
            if record["status"] != "COMPLETED":
                raise ValueError(f"input run did not complete: {directory}")
            for item in record["artefacts"]:
                path = Path(item["path"])
                if not path.is_absolute():
                    path = directory / path
                if sha256_file(path) != item["sha256"]:
                    raise ValueError(f"artifact changed: {path}")
            evidence.append(
                {
                    "run_id": record["run_id"],
                    "task": record["task"],
                    "artifacts_verified": len(record["artefacts"]),
                    "git_sha": record["git_sha"],
                    "git_dirty": record["git_dirty"],
                }
            )
            plan_path, results_path = directory / "plan.json", directory / "results.json"
            if not plan_path.exists() or not results_path.exists():
                continue
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            rows = json.loads(results_path.read_text(encoding="utf-8"))
            for (variant, family), model_dir, samples in representative_cells(directory, plan, rows):
                commands.append(
                    [
                        python,
                        "scripts/eval_extension.py",
                        "--reproduce",
                        model_dir,
                        "--samples",
                        str(samples),
                        "--expected",
                        str(Path(model_dir) / "validation.json"),
                        "--result",
                        str(run.dir / f"reproduced-{variant}-{family}-{record['run_id']}.json"),
                    ]
                )
        checks = []
        for i, command in enumerate(commands):
            result = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
            log = run.dir / f"{i:02d}.log"
            log.write_bytes(result.stdout + result.stderr)
            checks.append(
                {
                    "command": command,
                    "exit_code": result.returncode,
                    "log": log.name,
                    "git_dirty_after": git_dirty(),
                }
            )
            write_json(run.dir / "verification.json", checks)
            print(f"[{i + 1}/{len(commands)}] exit={result.returncode}: {' '.join(command[:4])}", flush=True)

        def changed(paths):
            return subprocess.run(
                ["git", "diff", "--name-only", "HEAD", "--", *paths],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

        frozen = changed(FROZEN)
        declared = predeclaration_record()
        summary = {
            "all_commands_passed": all(c["exit_code"] == 0 for c in checks),
            "frozen_components_unchanged": not frozen,
            "changed_frozen_files": frozen,
            "extended_harness_files_changed_vs_head": changed(EXTENDED),
            "source_unchanged_during_verification": hashes == source_hashes(),
            "predeclaration_unchanged": declared["unchanged_since_archive"],
            "predeclaration": declared,
            "git_sha_final": git_sha(),
            "git_dirty_final": git_dirty(),
            "input_runs": evidence,
            "participant_evidence": "PENDING",
            "adopted_extensions": [],
            "phase_gate": "PENDING reviewer; proposed FAIL",
        }
        write_json(run.dir / "summary.json", summary)
        ok = (
            summary["all_commands_passed"]
            and not frozen
            and summary["source_unchanged_during_verification"]
            and summary["predeclaration_unchanged"]
        )
        if args.require_clean:
            ok = ok and not summary["git_dirty_final"]
        for path in run.dir.iterdir():
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            summary,
            status="COMPLETED" if ok else "FAILED",
            notes="DEVELOPMENT only if dirty; same-environment reproduction is not VALIDATED. "
            "No test participant run, adoption, commit, tag or push.",
        )
        print(f"RESULT {'PASS' if ok else 'FAIL'}: {run.dir}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
