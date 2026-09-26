"""Executable Phase 16 verification; the owner retains gate, commit, tag and push decisions."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _p10 import write_json
from _p16 import evidence
from _runlog import git_dirty

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/perf.developer.candidate.yaml")
    parser.add_argument("--plan", type=Path, default=ROOT / "configs/perf.regression-plan.json")
    parser.add_argument("--output", type=Path, default=ROOT / "experiments/phase-16")
    args = parser.parse_args()
    if args.require_clean and git_dirty():
        parser.error("--require-clean needs the owner-committed tree")
    py = sys.executable
    binary = Path(py).parent
    with evidence(args.config, args.output, "gate-verification", "16.8") as (run, cfg):
        samples = Path(cfg["anticipator"]["model"]["norm_stats_path"]).with_name("samples.val.npz")
        commands = [
            [py, "-m", "pytest", "-o", "addopts=", "-q", "--strict-markers"],
            [str(binary / "ruff.exe"), "check", "src", "scripts", "tests"],
            [str(binary / "lint-imports.exe"), "--config", ".importlinter"],
            [py, "scripts/validate_contracts.py"],
            [py, "scripts/env_smoke.py"],
            ["git", "diff", "--check"],
            [
                py,
                "scripts/regression_check.py",
                "--config",
                str(args.config),
                "--plan",
                str(args.plan),
                "--val-samples",
                str(samples),
                "--reference",
                str(args.reference),
                "--output",
                str(run.dir / "regression"),
                "--opencv-threads",
                "1",
                "--causal",
            ],
            [
                py,
                "scripts/parity_test.py",
                "--config",
                str(args.config),
                "--plan",
                str(args.plan),
                "--output",
                str(run.dir / "raw-parity"),
            ],
            [
                py,
                "scripts/phase13_faults.py",
                "--config",
                "configs/live.arm-C.candidate.yaml",
                "--output",
                str(run.dir / "faults"),
            ],
            [
                py,
                "scripts/profile_pipeline.py",
                "--config",
                str(args.config),
                "--sessions",
                *[s["path"] for s in json.loads(args.plan.read_text(encoding="utf-8"))["sessions"]],
                "--repeats",
                "3",
                "--output",
                str(run.dir / "profile"),
                "--opencv-threads",
                "1",
            ],
        ]
        checks = []
        for i, command in enumerate(commands):
            result = subprocess.run(command, cwd=ROOT, capture_output=True)
            (run.dir / f"{i:02d}.log").write_bytes(result.stdout + result.stderr)
            checks.append({"command": command, "exit_code": result.returncode, "log": f"{i:02d}.log"})
            write_json(run.dir / "verification.json", checks)
            print(f"[{i + 1}/{len(commands)}] exit={result.returncode}", flush=True)
        passed = all(c["exit_code"] == 0 for c in checks)
        if args.require_clean:
            passed = passed and not git_dirty()
        write_json(
            run.dir / "verification-summary.json",
            {
                "all_commands_passed": passed,
                "gate": "PENDING reviewer",
                "participant_fold": "PENDING",
                "shipped_model": "PENDING owner decision",
                "live_stroke_delay": "PENDING person-dependent measurement",
            },
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
