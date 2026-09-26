"""Executable Phase 13 gate checks. No gate verdict, commit, tag, push or participant claim."""

import argparse
import subprocess
import sys
from pathlib import Path

from _p10 import source_hashes, write_json
from _p13 import execution
from _runlog import RunLog, git_dirty, git_sha

from spacedrums.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-clean", action="store_true")
    ap.add_argument("--config", type=Path, default=ROOT / "configs/live.arm-C.candidate.yaml")
    ap.add_argument("--parity-config", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--experiments-dir", type=Path, default=ROOT / "experiments/phase-13")
    args = ap.parse_args()
    if args.require_clean and git_dirty():
        ap.error("--require-clean needs the owner-committed tree")
    cfg = load_config(args.config)
    with RunLog(
        phase="13",
        task="13.8",
        slug="p13-gate-verification",
        config=cfg,
        experiments_dir=args.experiments_dir,
        description="Developer integration checks; participant fold and live strike timing pending",
    ) as run:
        initial = source_hashes()
        write_json(run.dir / "execution.json", execution())
        write_json(run.dir / "source-hashes-start.json", initial)
        py = sys.executable
        binary = Path(py).parent
        commands = [
            [py, "-m", "pytest", "-o", "addopts=", "-q", "--strict-markers"],
            [str(binary / "ruff.exe"), "check", "."],
            [str(binary / "lint-imports.exe"), "--config", ".importlinter"],
            [py, "scripts/validate_contracts.py"],
            [py, "scripts/env_smoke.py"],
            ["git", "diff", "--check"],
            [
                py,
                "scripts/parity_test.py",
                "--config",
                str(args.parity_config),
                "--plan",
                str(args.plan),
                "--output",
                str(run.dir / "raw-parity"),
            ],
            [
                py,
                "scripts/phase13_faults.py",
                "--config",
                str(args.config),
                "--output",
                str(run.dir / "faults"),
            ],
        ]
        for label, config in (
            ("candidate-budget", args.config),
            ("comparison-no-fallback", args.parity_config),
        ):
            commands.append(
                [
                    py,
                    "scripts/live_latency.py",
                    "--config",
                    str(config),
                    "--source",
                    "replay",
                    "--session-dir",
                    "data/dev-captures/swing-L2-exp-5",
                    "--output",
                    str(run.dir / label),
                    "--max-frames",
                    "171",
                    "--switch-frame",
                    "85",
                ]
            )
        checks = []
        for i, command in enumerate(commands):
            result = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
            log = run.dir / f"{i:02d}.log"
            log.write_bytes(result.stdout + result.stderr)
            checks.append({"command": command, "exit_code": result.returncode, "log": log.name})
            write_json(run.dir / "verification.json", checks)
            print(f"[{i + 1}/{len(commands)}] exit={result.returncode}: {' '.join(command[:4])}", flush=True)
        final = source_hashes()
        summary = {
            "all_commands_passed": all(c["exit_code"] == 0 for c in checks),
            "source_unchanged_during_verification": initial == final,
            "git_sha_final": git_sha(),
            "git_dirty_final": git_dirty(),
            "codex_model": "UNVERIFIED",
            "codex_reasoning_effort": "UNVERIFIED",
            "participant_fold": "PENDING: ds-v1.0 unavailable",
            "shipped_model": "PENDING owner selection",
            "live_strike_timing": "PENDING person-dependent session",
            "gate": "PENDING reviewer; no submitter PASS",
        }
        ok = summary["all_commands_passed"] and initial == final
        if args.require_clean:
            ok = ok and not git_dirty()
        write_json(run.dir / "summary.json", summary)
        for p in run.dir.rglob("*"):
            if p.is_file() and p.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(p, "other")
        run.finish(
            summary,
            status="COMPLETED" if ok else "FAILED",
            notes="Developer checks only; owner controls gate.",
        )
        print(f"RESULT {'PASS' if ok else 'FAIL'}: {run.dir}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
