"""Executable Phase 18 verification; the owner retains gate, commit, tag and push decisions.

    python scripts/verify_phase18.py [--require-clean] --executor-model "<model>" --executor-effort "<effort>"

Runs, in order:

1. the repository checks: full pytest, ruff, import-layer contracts, schema validation,
   environment smoke, whitespace (tracked diff and untracked files), test-matrix freshness;
2. the pre-registration check: the document matches its latest archived hash, and the final
   evaluation report quotes that hash;
3. the SYNTHETIC external-method self-test;
4. the SYNTHETIC Experiment 1 rehearsal chain: rehearsal lock, then the offline runner (its own
   self-checks, including TEST-CAUSAL-1 on every locked arm), then regeneration from stored results
   and from raw data;
5. the SYNTHETIC Experiment 2 rehearsal chain: live session with a SYNTHETIC M1 track, then Phase 07
   labels, then M1 sync, then the live analysis.

Each chained step finds the previous step's run directory from the ``EVIDENCE:`` line it prints.
Everything here is machinery on generated data. Participant data, the live pilot and live sessions
with people are separate, person-dependent steps (the gate record lists them).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p10 import write_json  # noqa: E402
from _p18 import ROOT, add_executor_args, evidence  # noqa: E402
from _runlog import git_dirty  # noqa: E402

FINAL_REPORT = "docs/reports/phase-18-final-evaluation.md"
LIVE_DATASET = "ds-v0.0-selftest-p18-live"


def untracked_whitespace() -> list[str]:
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
        if p.suffix not in (".py", ".md", ".json", ".yaml", ".yml", ".txt", ".toml", ".jsonl"):
            continue
        for n, line in enumerate(p.read_bytes().split(b"\n"), start=1):
            if line.endswith((b" ", b"\t", b"\r")):
                problems.append(f"{rel}:{n}")
    return problems


def evidence_dir(log: bytes) -> str | None:
    found = re.findall(rb"EVIDENCE: (.+)", log)
    return found[-1].decode().strip() if found else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--require-clean", action="store_true")
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-18")
    add_executor_args(ap)
    args = ap.parse_args()
    if args.require_clean and git_dirty():
        ap.error("--require-clean needs the owner-committed tree")
    py = sys.executable
    binary = Path(py).parent
    executor = ["--executor-model", args.executor_model, "--executor-effort", args.executor_effort]
    with evidence(
        args,
        slug="p18-gate-verification",
        task="18.9",
        description="Phase 18 executable gate verification (development evidence)",
        output=args.output,
    ) as (run, _cfg):
        out = str(run.dir)
        state: dict[str, str | None] = {}
        steps = [
            (
                "pytest",
                lambda: [
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
            ),
            ("ruff", lambda: [str(binary / "ruff.exe"), "check", "src", "scripts", "tests"]),
            ("import-contracts", lambda: [str(binary / "lint-imports.exe"), "--config", ".importlinter"]),
            ("schemas", lambda: [py, "scripts/validate_contracts.py"]),
            ("environment", lambda: [py, "scripts/env_smoke.py"]),
            ("diff-check", lambda: ["git", "diff", "--check"]),
            ("test-matrix", lambda: [py, "scripts/build_test_matrix.py", "--check"]),
            ("prereg-hash", lambda: [py, "scripts/prereg_archive.py", "verify", "--cite", FINAL_REPORT]),
            (
                "methods-selftest",
                lambda: [py, "scripts/external_methods_pilot.py", "--selftest", "--output", out, *executor],
            ),
            (
                "rehearsal-lock",
                lambda: [py, "scripts/confirmatory_lock.py", "build-rehearsal", "--output", out, *executor],
            ),
            (
                "offline-rehearsal",
                lambda: [
                    py,
                    "scripts/run_offline_confirmatory.py",
                    "--rehearsal",
                    "--lock",
                    f"{state['rehearsal-lock']}/lock.json",
                    "--record",
                    f"{state['rehearsal-lock']}/rehearsal-record.json",
                    "--output",
                    out,
                    *executor,
                ],
            ),
            (
                "regenerate",
                lambda: [
                    py,
                    "scripts/regenerate_phase18.py",
                    "--run",
                    str(state["offline-rehearsal"]),
                    "--from-raw",
                    "--output",
                    out,
                    *executor,
                ],
            ),
            (
                "live-rehearsal",
                lambda: [
                    py,
                    "scripts/run_live_session.py",
                    "--synthetic",
                    "--participant-index",
                    "1",
                    "--pad-zone",
                    "snare",
                    "--synthetic-mic",
                    "--duration-scale",
                    "0.3",
                    "--output",
                    out,
                    *executor,
                ],
            ),
            (
                "live-labels",
                lambda: [
                    py,
                    "scripts/build_labels.py",
                    "--session",
                    live_session(state),
                    "--out",
                    f"{state['live-rehearsal']}/labels",
                    "--dataset-version",
                    LIVE_DATASET,
                ],
            ),
            (
                "live-sync",
                lambda: [
                    py,
                    "scripts/external_sync.py",
                    "--session",
                    live_session(state),
                    "--method",
                    "M1",
                    "--recording",
                    f"{live_session(state)}/m1_synthetic.wav",
                    "--output",
                    out,
                    *executor,
                ],
            ),
            (
                "live-analysis",
                lambda: [
                    py,
                    "scripts/analyze_live.py",
                    "--session",
                    live_session(state),
                    "--labels-root",
                    f"{state['live-rehearsal']}/labels",
                    "--rehearsal-method-u",
                    "0.002",
                    "--output",
                    out,
                    *executor,
                ],
            ),
        ]
        checks = []
        for i, (name, build) in enumerate(steps):
            try:
                command = build()
            except (KeyError, TypeError) as exc:
                checks.append(
                    {
                        "name": name,
                        "command": None,
                        "exit_code": None,
                        "log": None,
                        "skipped": f"previous step produced no evidence directory ({exc})",
                    }
                )
                print(f"[{i + 1}/{len(steps)}] {name}: SKIPPED", flush=True)
                continue
            result = subprocess.run(command, cwd=ROOT, capture_output=True)
            log = f"{i:02d}-{name}.log"
            (run.dir / log).write_bytes(result.stdout + result.stderr)
            state[name] = evidence_dir(result.stdout)
            checks.append(
                {
                    "name": name,
                    "command": command,
                    "exit_code": result.returncode,
                    "log": log,
                    "evidence": state[name],
                }
            )
            write_json(run.dir / "verification.json", checks)
            print(f"[{i + 1}/{len(steps)}] {name}: exit={result.returncode}", flush=True)
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
                "participant_data": "PENDING: ds-v1.0 does not exist; the offline confirmatory run "
                "has not happened",
                "live_person_steps": "PENDING: M1 pad pilot, M2 pilot, live participants "
                "(ethics Open Question)",
            },
        )
    return 0 if passed else 1


def live_session(state: dict[str, str | None]) -> str:
    """The session directory the live rehearsal recorded (read from its session-result.json)."""
    import json

    result = json.loads(
        (Path(str(state["live-rehearsal"])) / "session-result.json").read_text(encoding="utf-8")
    )
    return result["session_dir"]


if __name__ == "__main__":
    raise SystemExit(main())
