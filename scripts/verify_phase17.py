"""Executable Phase 17 verification; the owner retains gate, commit, tag and push decisions.

    python scripts/verify_phase17.py [--require-clean] --executor-model "<model>" --executor-effort "<effort>"
                                     [--quick-campaigns]

Runs, in order: the full pytest suite; ruff; the import-layer contracts; schema validation; the
environment smoke test; whitespace checks (tracked diff and untracked files); the test-matrix
freshness check; the Phase 16 frozen raw/harness regression with future perturbation; the Phase 13
raw live/offline parity and causality check on the developer captures; the invariant replay over the
full development replay set with system-level TEST-CAUSAL-1; the failure-injection campaign (all
suites); the DEGRADED-commit experiment; the re-acquisition threshold (g_max / age_max) sweep. The
live-mode assertion set, the live soak (``soak_test.py``) and every person-dependent
check are separate artefacts. The executor fields are arguments on purpose (Phase 13 found a
verifier that hard-coded its first executor).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _p10 import write_json
from _p17 import RULE_CONFIG, add_executor_args, evidence
from _runlog import git_dirty

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "experiments/phase-16/20260926-1301-reference-fixed/snapshot.json"
PERF_CONFIG = ROOT / "configs/perf.developer.candidate.yaml"
PLAN = ROOT / "configs/perf.regression-plan.json"


def untracked_whitespace() -> list[str]:
    """Trailing whitespace / CR in untracked text files (``git diff --check`` misses them)."""
    out = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    problems = []
    for rel in out:
        p = ROOT / rel
        if p.suffix not in (".py", ".md", ".json", ".yaml", ".yml", ".txt", ".toml"):
            continue
        for n, line in enumerate(p.read_bytes().split(b"\n"), start=1):
            if line.endswith((b" ", b"\t", b"\r")):
                problems.append(f"{rel}:{n}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--require-clean", action="store_true")
    ap.add_argument("--quick-campaigns", action="store_true", help="reduced injection / DEGRADED grids")
    ap.add_argument("--reference", type=Path, default=REFERENCE)
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-17")
    add_executor_args(ap)
    args = ap.parse_args()
    if args.require_clean and git_dirty():
        ap.error("--require-clean needs the owner-committed tree")
    py = sys.executable
    binary = Path(py).parent
    executor = ["--executor-model", args.executor_model, "--executor-effort", args.executor_effort]
    quick = ["--quick"] if args.quick_campaigns else []
    with evidence(
        RULE_CONFIG,
        args,
        slug="p17-gate-verification",
        task="17.2",
        description="Phase 17 executable gate verification (development evidence)",
        output=args.output,
    ) as (run, _cfg):
        val_samples = (
            ROOT
            / "experiments/phase-10/20260924-1926-synthetic-horizon/features/n8-k1/fold-0/samples.val.npz"
        )
        commands = [
            (
                "pytest",
                [py, "-m", "pytest", "-o", "addopts=", "-q", "--strict-markers", "-p", "no:cacheprovider"],
            ),
            ("ruff", [str(binary / "ruff.exe"), "check", "src", "scripts", "tests"]),
            ("import-contracts", [str(binary / "lint-imports.exe"), "--config", ".importlinter"]),
            ("schemas", [py, "scripts/validate_contracts.py"]),
            ("environment", [py, "scripts/env_smoke.py"]),
            ("diff-check", ["git", "diff", "--check"]),
            ("test-matrix", [py, "scripts/build_test_matrix.py", "--check"]),
            (
                "p16-frozen-regression",
                [
                    py,
                    "scripts/regression_check.py",
                    "--config",
                    str(PERF_CONFIG),
                    "--plan",
                    str(PLAN),
                    "--val-samples",
                    str(val_samples),
                    "--reference",
                    str(args.reference),
                    "--output",
                    str(run.dir / "regression"),
                    "--opencv-threads",
                    "1",
                    "--causal",
                ],
            ),
            (
                "p13-raw-parity",
                [
                    py,
                    "scripts/parity_test.py",
                    "--config",
                    str(PERF_CONFIG),
                    "--plan",
                    str(PLAN),
                    "--output",
                    str(run.dir / "raw-parity"),
                ],
            ),
            ("invariant-replay", [py, "scripts/invariant_replay.py", "--output", str(run.dir), *executor]),
            (
                "failure-injection",
                [
                    py,
                    "scripts/inject_faults.py",
                    "--suite",
                    "all",
                    "--output",
                    str(run.dir),
                    *quick,
                    *executor,
                ],
            ),
            (
                "degraded-experiment",
                [py, "scripts/degraded_experiment.py", "--output", str(run.dir), *quick, *executor],
            ),
            (
                "reacquisition-experiment",
                [py, "scripts/reacquisition_experiment.py", "--output", str(run.dir), *quick, *executor],
            ),
        ]
        checks = []
        for i, (name, command) in enumerate(commands):
            result = subprocess.run(command, cwd=ROOT, capture_output=True)
            log = f"{i:02d}-{name}.log"
            (run.dir / log).write_bytes(result.stdout + result.stderr)
            checks.append({"name": name, "command": command, "exit_code": result.returncode, "log": log})
            write_json(run.dir / "verification.json", checks)
            print(f"[{i + 1}/{len(commands)}] {name}: exit={result.returncode}", flush=True)
        whitespace = untracked_whitespace()
        write_json(run.dir / "untracked-whitespace.json", whitespace)
        passed = all(c["exit_code"] == 0 for c in checks) and not whitespace
        if args.require_clean:
            passed = passed and not git_dirty()
        write_json(
            run.dir / "verification-summary.json",
            {
                "all_commands_passed": passed,
                "untracked_whitespace_problems": len(whitespace),
                "gate": "PENDING reviewer",
                "participant_replay_set": "PENDING: no participant dataset",
                "live_person_tests": "PENDING: physical occlusion, lighting, second person, device removal",
                "soak": "separate artefact (scripts/soak_test.py)",
            },
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
