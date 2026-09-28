"""Phase 19 PREPARATION ONLY verification. No participant execution or approvals."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _p10 import source_hashes, write_json
from _p18 import add_executor_args, execution
from _runlog import RunLog
from verify_phase18 import evidence_dir, untracked_whitespace

from spacedrums.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=ROOT / "experiments/phase-19")
    ap.add_argument(
        "--skip-full",
        action="store_true",
        help="record an explicit skip when another verifier runs the full suite",
    )
    add_executor_args(ap)
    args = ap.parse_args()
    py, binary = sys.executable, Path(sys.executable).parent
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    with RunLog(
        phase="19",
        task="19.1",
        slug="preparation-verification",
        config=cfg,
        experiments_dir=args.output.resolve(),
        description="SYNTHETIC/DEV ONLY Phase 19 preparation verification",
    ) as run:
        before = source_hashes()
        write_json(run.dir / "execution.json", execution(args))
        write_json(run.dir / "source-hashes.json", before)
        exe = ["--executor-model", args.executor_model, "--executor-effort", args.executor_effort]
        commands = (
            []
            if args.skip_full
            else [
                (
                    "full-suite",
                    [
                        py,
                        "-m",
                        "pytest",
                        "-o",
                        "addopts=",
                        "-q",
                        "--strict-markers",
                        "-p",
                        "no:cacheprovider",
                    ],
                    0,
                )
            ]
        )
        commands += [
            (
                "focused",
                [
                    py,
                    "-m",
                    "pytest",
                    "-o",
                    "addopts=",
                    "-q",
                    "tests/ablation",
                    "tests/app/test_per_arm_settings.py",
                    "tests/parity/test_per_arm_model.py",
                    "tests/calib/test_per_arm_calibration.py",
                    "tests/invariants/test_per_arm_audit.py",
                ],
                0,
            ),
            ("ruff", [str(binary / "ruff.exe"), "check", "src", "scripts", "tests"], 0),
            ("imports", [str(binary / "lint-imports.exe"), "--config", ".importlinter"], 0),
            ("contracts", [py, "scripts/validate_contracts.py"], 0),
            ("environment", [py, "scripts/env_smoke.py"], 0),
            ("test-matrix", [py, "scripts/build_test_matrix.py", "--check"], 0),
            ("prereg-unchanged", [py, "scripts/prereg_archive.py", "verify"], 0),
            ("missing-inputs-refused", [py, "scripts/run_ablations.py", "--check-dependencies"], 2),
            ("execution-refused", [py, "scripts/run_ablations.py", "--execute"], 2),
            (
                "synthetic-dev",
                [py, "scripts/run_ablations.py", "--synthetic-dev", "--output", str(run.dir), *exe],
                0,
            ),
            ("diff", ["git", "diff", "--check"], 0),
        ]
        checks = []
        for i, (name, cmd, expected) in enumerate(commands):
            result = subprocess.run(cmd, cwd=ROOT, capture_output=True)
            log = f"{i:02d}-{name}.log"
            (run.dir / log).write_bytes(result.stdout + result.stderr)
            checks.append(
                dict(
                    name=name,
                    command=cmd,
                    exit_code=result.returncode,
                    expected=expected,
                    passed=result.returncode == expected,
                    log=log,
                )
            )
            write_json(run.dir / "verification.json", checks)
            print(f"[{i + 1}/{len(commands)}] {name}: {result.returncode} (expected {expected})", flush=True)
            if name == "synthetic-dev" and result.returncode == 0:
                source = Path(evidence_dir(result.stdout))
                cmd = [
                    py,
                    "scripts/run_ablations.py",
                    "--regenerate",
                    str(source / "results.json"),
                    "--output",
                    str(run.dir / "regeneration"),
                ]
                regenerated = subprocess.run(cmd, cwd=ROOT, capture_output=True)
                (run.dir / "regeneration.log").write_bytes(regenerated.stdout + regenerated.stderr)
                original = json.loads((source / "report-manifest.json").read_text())
                target = run.dir / "regeneration/regenerated-synthetic-report/report-manifest.json"
                identical = regenerated.returncode == 0 and original == json.loads(target.read_text())
                checks.append(
                    dict(
                        name="report-regeneration",
                        command=cmd,
                        exit_code=regenerated.returncode,
                        passed=identical,
                    )
                )
                write_json(run.dir / "verification.json", checks)
        whitespace = untracked_whitespace()
        summary = dict(
            evidence="SYNTHETIC/DEV",
            experimental_execution=False,
            phase18="PENDING",
            full_suite="SKIPPED (separate verifier)" if args.skip_full else "see full-suite check",
            source_unchanged=before == source_hashes(),
            untracked_whitespace=whitespace,
            passed=all(c["passed"] for c in checks) and before == source_hashes() and not whitespace,
        )
        write_json(run.dir / "summary.json", summary)
        for path in sorted(run.dir.rglob("*")):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            {"checks_passed": sum(c["passed"] for c in checks)}, notes="PREPARATION ONLY; Phase 18 PENDING"
        )
        print(f"EVIDENCE: {run.dir}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
