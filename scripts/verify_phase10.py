"""Re-run Phase 10 executable gate checks without changing Git history or reading test participants."""

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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-clean", action="store_true")
    ap.add_argument("--horizon-run", type=Path)
    ap.add_argument("--window-run", type=Path)
    ap.add_argument("--comparison-run", type=Path)
    ap.add_argument("--experiments-dir", type=Path, default=ROOT / "experiments/phase-10")
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
        phase="10",
        task="10.14",
        slug="p10-gate-verification",
        config=cfg,
        experiments_dir=args.experiments_dir,
        description="Development gate checks; participant evidence/owner decisions remain pending",
    ) as run:
        context, hashes = provenance(), source_hashes()
        write_json(run.dir / "execution.json", context)
        write_json(run.dir / "source-hashes.json", hashes)
        evidence = []
        seen = set()
        for directory in (args.horizon_run, args.window_run, args.comparison_run):
            if directory is None:
                continue
            record = json.loads((directory / "run.json").read_text(encoding="utf-8"))
            validate("experiment-log", record)
            if record["status"] != "COMPLETED":
                raise ValueError("input development run did not complete")
            for item in record["artefacts"]:
                path = Path(item["path"])
                if not path.is_absolute():
                    path = directory / path
                if sha256_file(path) != item["sha256"]:
                    raise ValueError(f"artifact changed: {path}")
            evidence.append(
                {
                    "run_id": record["run_id"],
                    "artifacts_verified": len(record["artefacts"]),
                    "git_sha": record["git_sha"],
                    "git_dirty": record["git_dirty"],
                }
            )
            if not (directory / "plan.json").exists():
                continue
            plan = json.loads((directory / "plan.json").read_text())["cells"]
            for row, cell in zip(json.loads((directory / "results.json").read_text()), plan, strict=True):
                key = row["family"], row["auxiliary"]
                if key in seen:
                    continue
                seen.add(key)
                commands.append(
                    [
                        python,
                        "scripts/eval_temporal.py",
                        "--model-dir",
                        row["model_dir"],
                        "--samples",
                        str(Path(cell["fold_dir"]) / "samples.val.npz"),
                        "--expected",
                        str(Path(row["model_dir"]) / "validation.json"),
                        "--output",
                        str(run.dir / f"reproduced-{key[0]}-{key[1]}.json"),
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
        # Audit exactly which frozen components changed relative to the owner HEAD.
        frozen = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                "HEAD",
                "--",
                "src/spacedrums/geometry",
                "src/spacedrums/commit",
                "src/spacedrums/eval/matching.py",
                "src/spacedrums/eval/metrics.py",
                "src/spacedrums/eval/report.py",
                "src/spacedrums/eval/selection.py",
                "src/spacedrums/eval/constants.py",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        summary = {
            "all_commands_passed": all(c["exit_code"] == 0 for c in checks),
            "frozen_components_unchanged": not frozen,
            "changed_frozen_files": frozen,
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
            "No test participant run, model selection, commit, tag or push.",
        )
        print(f"RESULT {'PASS' if ok else 'FAIL'}: {run.dir}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
