"""Re-run Phase 11 executable gate checks without changing Git history or reading test participants."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _p10 import provenance, source_hashes, write_json
from _runlog import RunLog, git_dirty, git_sha, sha256_file

from spacedrums.config import load_config
from spacedrums.contracts.schema import validate

ROOT = Path(__file__).resolve().parents[1]
FROZEN = (
    "src/spacedrums/geometry",
    "src/spacedrums/commit",
    "src/spacedrums/eval/matching.py",
    "src/spacedrums/eval/metrics.py",
    "src/spacedrums/eval/report.py",
    "src/spacedrums/eval/selection.py",
    "src/spacedrums/eval/constants.py",
)
# Additive Phase 11 harness extension (C-MT arm, post-geometry gate, flagged diagnostic mode).
EXTENDED = ("src/spacedrums/eval/replay.py",)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-clean", action="store_true")
    ap.add_argument("--runs", type=Path, nargs="*", default=[], help="completed Phase 11 run directories")
    ap.add_argument("--experiments-dir", type=Path, default=ROOT / "experiments/phase-11")
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
        phase="11",
        task="11.9",
        slug="p11-gate-verification",
        config=cfg,
        experiments_dir=args.experiments_dir,
        description="Development gate checks; participant evidence/owner decisions remain pending",
    ) as run:
        context, hashes = provenance(), source_hashes()
        context["codex_model"] = "NOT CODEX: Claude Opus 5.5 (claude-opus-5-5) via Claude Code"
        context["codex_reasoning_effort"] = "UNAVAILABLE to the agent; not asserted"
        write_json(run.dir / "execution.json", context)
        write_json(run.dir / "source-hashes.json", hashes)
        evidence, seen = [], set()
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
            if not (directory / "plan.json").exists() or not (directory / "results.json").exists():
                continue
            plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
            if "cells" not in plan:
                continue
            rows = json.loads((directory / "results.json").read_text(encoding="utf-8"))
            for row, cell in zip(rows, plan["cells"], strict=True):
                key = (row["family"], cell["variant"] if cell["variant"] in ("all", "no-traj") else "other")
                if key in seen:
                    continue
                seen.add(key)
                commands.append(
                    [
                        python,
                        "scripts/eval_mt.py",
                        "--model-dir",
                        row["model_dir"],
                        "--samples",
                        str(Path(cell["fold_dir"]) / "samples.val.npz"),
                        "--expected",
                        str(Path(row["model_dir"]) / "validation.json"),
                        "--output",
                        str(run.dir / f"reproduced-{key[0]}-{key[1]}-{record['run_id']}.json"),
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
        summary = {
            "all_commands_passed": all(c["exit_code"] == 0 for c in checks),
            "frozen_components_unchanged": not frozen,
            "changed_frozen_files": frozen,
            "extended_harness_files_changed_vs_head": changed(EXTENDED),
            "source_unchanged_during_verification": hashes == source_hashes(),
            "git_sha_final": git_sha(),
            "git_dirty_final": git_dirty(),
            "input_runs": evidence,
            "participant_evidence": "PENDING",
            "phase_gate": "PENDING reviewer; proposed FAIL",
        }
        write_json(run.dir / "summary.json", summary)
        ok = summary["all_commands_passed"] and not frozen and summary["source_unchanged_during_verification"]
        if args.require_clean:
            ok = ok and not summary["git_dirty_final"]
        for path in run.dir.iterdir():
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            summary,
            status="COMPLETED" if ok else "FAILED",
            notes="DEVELOPMENT only if dirty; same-environment reproduction is not VALIDATED. "
            "No test participant run, ship decision, commit, tag or push.",
        )
        print(f"RESULT {'PASS' if ok else 'FAIL'}: {run.dir}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
