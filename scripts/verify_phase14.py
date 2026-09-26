"""Executable Phase 14 gate checks. No gate verdict, commit, tag, push or person/participant claim.

    python scripts/verify_phase14.py [--require-clean] --executor-model "<model>" --executor-effort "<effort>"

Runs the regression suite, lint, import contracts, contract validation, environment smoke and the diff
check (tracked files, plus a whitespace/CR scan of untracked text files), then the Phase 14 machinery:
a SYNTHETIC wizard run and its screenshots, an app session and a Phase 06 recording that load the
calibration and record its hash, the zero-drift regression, the pinned Phase 10 model on a calibrated
layout, re-calibration trigger checks, a SYNTHETIC repeatability machinery check and DEVELOPER_REPLAY
diagnostics on the three developer captures. Person-dependent evidence (developer live wizard runs,
L_prior repeatability, wizard duration, validation strikes) is reported PENDING, never substituted.

The executor fields are arguments on purpose: whoever re-runs this after the owner commit records who
they are (Phase 13 found a verifier that hard-coded its first executor).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml
from _p10 import provenance, source_hashes, write_json
from _runlog import RunLog, git_dirty, git_sha

from spacedrums.config import load_config

ROOT = Path(__file__).resolve().parents[1]
TEXT = (".py", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".ini", ".cfg")


def untracked_whitespace() -> list[str]:
    """``git diff --check`` for files git does not track yet (CR or trailing blanks on any line)."""
    out = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    problems = []
    for rel in out:
        if not rel.endswith(TEXT):
            continue
        for n, line in enumerate((ROOT / rel).read_bytes().split(b"\n"), 1):
            if line.endswith((b"\r", b" ", b"\t")):
                problems.append(f"{rel}:{n}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--require-clean", action="store_true")
    ap.add_argument("--config", type=Path, default=ROOT / "configs/prototype.candidate.yaml")
    ap.add_argument("--experiments-dir", type=Path, default=ROOT / "experiments/phase-14")
    ap.add_argument("--executor-model", default="UNVERIFIED")
    ap.add_argument("--executor-effort", default="UNVERIFIED")
    ap.add_argument("--skip-pytest", action="store_true", help="development only; a gate run keeps pytest")
    args = ap.parse_args()
    if args.require_clean and git_dirty():
        ap.error("--require-clean needs the owner-committed tree")
    cfg = load_config(args.config)
    with RunLog(
        phase="14",
        task="14.7",
        slug="p14-gate-verification",
        config=cfg,
        experiments_dir=args.experiments_dir,
        description="Phase 14 machinery checks; developer live calibrations and repeatability PENDING",
    ) as run:
        initial = source_hashes()
        execution = {
            **provenance(),
            "codex_model": "not used",
            "codex_reasoning_effort": "not applicable",
            "executor_model": args.executor_model,
            "executor_reasoning_effort": args.executor_effort,
        }
        write_json(run.dir / "execution.json", execution)
        write_json(run.dir / "source-hashes-start.json", initial)
        py = sys.executable
        binary = Path(py).parent
        d = run.dir
        synth = d / "wizard" / "user-synthetic-actor-hw-01.calib.yaml"
        stale_cfg = d / "stale-camera.yaml"
        stale = yaml.safe_load(args.config.read_text(encoding="utf-8"))
        stale["camera_profile"]["exposure"]["value"] = -5
        stale_cfg.write_text(yaml.safe_dump(stale), encoding="utf-8")
        commands: list[tuple[str, list[str], int]] = []
        if not args.skip_pytest:
            commands.append(("pytest", [py, "-m", "pytest", "-o", "addopts=", "-q", "--strict-markers"], 0))
        commands += [
            ("ruff", [str(binary / "ruff.exe"), "check", "."], 0),
            ("import-contracts", [str(binary / "lint-imports.exe"), "--config", ".importlinter"], 0),
            ("validate-contracts", [py, "scripts/validate_contracts.py"], 0),
            ("env-smoke", [py, "scripts/env_smoke.py"], 0),
            ("diff-check", ["git", "diff", "--check"], 0),
            (
                "wizard-synthetic",
                [
                    py,
                    "-m",
                    "spacedrums.app.calibrate",
                    "--synthetic",
                    "--user-tag",
                    "synthetic-actor",
                    "--seed",
                    "1",
                    "--output",
                    str(synth),
                    "--summary-json",
                    str(d / "wizard" / "summary.json"),
                ],
                0,
            ),
            (
                "render",
                [
                    py,
                    "scripts/render_calibration.py",
                    "--calibration",
                    str(synth),
                    "--frame",
                    "data/dev-captures/swing-L2-exp-5/frame_00050.png",
                    "--output-dir",
                    str(d / "render"),
                ],
                0,
            ),
            (
                "app-session",
                [
                    py,
                    "-m",
                    "spacedrums.app.main",
                    "--synthetic",
                    "repeated",
                    "--calibration",
                    str(synth),
                    "--record",
                    "--output-dir",
                    str(d / "session"),
                    "--no-window",
                ],
                0,
            ),
            (
                "session-check",
                [
                    py,
                    "scripts/_p14.py",
                    "session",
                    "--calibration",
                    str(synth),
                    "--session",
                    str(d / "session"),
                ],
                0,
            ),
            (
                "record-session",
                [
                    py,
                    "scripts/record_session.py",
                    "--synthetic",
                    "--calibration",
                    str(synth),
                    "--no-runlog",
                    "--keep-temp",
                    "--output-root",
                    str(d / "recording"),
                ],
                0,
            ),
            (
                "metadata-check",
                [
                    py,
                    "scripts/_p14.py",
                    "metadata",
                    "--calibration",
                    str(synth),
                    "--root",
                    str(d / "recording"),
                ],
                0,
            ),
            ("regression", [py, "scripts/_p14.py", "regression", "--out", str(d / "regression")], 0),
            (
                "model-compat",
                [
                    py,
                    "scripts/_p14.py",
                    "model-compat",
                    "--calibration",
                    str(synth),
                    "--out",
                    str(d / "model-compat"),
                ],
                0,
            ),
            ("trigger-valid", [py, "-m", "spacedrums.app.calibrate", "--check", str(synth)], 0),
            (
                "trigger-camera",
                [py, "-m", "spacedrums.app.calibrate", "--config", str(stale_cfg), "--check", str(synth)],
                3,
            ),
            (
                "app-refuses-stale",
                [
                    py,
                    "-m",
                    "spacedrums.app.main",
                    "--config",
                    str(stale_cfg),
                    "--synthetic",
                    "single",
                    "--calibration",
                    str(synth),
                    "--no-window",
                ],
                2,
            ),
        ]
        repeat = []
        for seed in range(1, 6):
            out = d / "repeatability" / f"synthetic-{seed}.calib.yaml"
            repeat.append(out)
            commands.append(
                (
                    f"repeat-{seed}",
                    [
                        py,
                        "-m",
                        "spacedrums.app.calibrate",
                        "--synthetic",
                        "--user-tag",
                        "synthetic-actor",
                        "--seed",
                        str(seed),
                        "--synthetic-noise",
                        "0.002",
                        "--synthetic-support-noise",
                        "0.004",
                        "--output",
                        str(out),
                    ],
                    0,
                )
            )
        commands.append(
            (
                "repeatability",
                [
                    py,
                    "scripts/calibration_repeatability.py",
                    "--calibrations",
                    *map(str, repeat),
                    "--output-dir",
                    str(d / "repeatability"),
                ],
                0,
            )
        )
        for capture in ("swing-L2-exp-5", "swing-L2-exp-6", "swing-L2-exp-7"):
            commands.append(
                (
                    f"replay-{capture}",
                    [
                        py,
                        "-m",
                        "spacedrums.app.calibrate",
                        "--source",
                        "replay",
                        "--session-dir",
                        f"data/dev-captures/{capture}",
                        "--window-scale",
                        "0.2",
                        "--scope",
                        "SETUP",
                        "--setup-tag",
                        f"devcapture-{capture}",
                        "--output",
                        str(d / "replay" / f"{capture}.calib.yaml"),
                        "--no-window",
                        "--summary-json",
                        str(d / "replay" / f"{capture}.summary.json"),
                    ],
                    -1,
                )
            )
        checks = []
        for i, (label, command, expected) in enumerate(commands):
            result = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
            log = d / f"{i:02d}-{label}.log"
            log.write_bytes(result.stdout + result.stderr)
            ok = expected == -1 or result.returncode == expected
            checks.append(
                {
                    "label": label,
                    "command": command,
                    "exit_code": result.returncode,
                    "expected_exit": expected,
                    "ok": ok,
                    "log": log.name,
                }
            )
            write_json(d / "verification.json", checks)
            print(
                f"[{i + 1}/{len(commands)}] {'ok ' if ok else 'BAD'} exit={result.returncode} {label}",
                flush=True,
            )
        whitespace = untracked_whitespace()
        final = source_hashes()
        replay = {}
        for capture in ("swing-L2-exp-5", "swing-L2-exp-6", "swing-L2-exp-7"):
            path = d / "replay" / f"{capture}.summary.json"
            replay[capture] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        summary = {
            "all_commands_passed": all(c["ok"] for c in checks),
            "untracked_whitespace_problems": whitespace,
            "source_unchanged_during_verification": initial == final,
            "git_sha_final": git_sha(),
            "git_dirty_final": git_dirty(),
            "executor_model": args.executor_model,
            "executor_reasoning_effort": args.executor_effort,
            "replay_diagnostics": {k: (v or {}).get("status") for k, v in replay.items()},
            "developer_live_calibration": "PENDING: person-dependent (developer at the camera)",
            "l_prior_repeatability": "PENDING: needs repeated live calibrations of one developer",
            "wizard_duration": "PENDING: only a live run gives a MEASURED t_mono duration",
            "validation_strikes": "PENDING per live calibration (Arm A)",
            "gate": "PENDING reviewer; no submitter PASS",
        }
        ok = summary["all_commands_passed"] and initial == final and not whitespace
        if args.require_clean:
            ok = ok and not git_dirty()
        write_json(d / "summary.json", summary)
        for p in sorted(d.rglob("*")):
            if not p.is_file() or p.name in ("run.json", "stdout.log", "config.resolved.yaml"):
                continue
            if "frames" in p.relative_to(d).parts:  # recorded SYNTHETIC frame images (hashed per session)
                continue
            run.add_artefact(p, "figure" if p.suffix == ".png" else "other")
        run.finish(
            summary,
            status="COMPLETED" if ok else "FAILED",
            notes="Machinery checks only; owner controls the gate.",
        )
        print(f"RESULT {'PASS' if ok else 'FAIL'}: {d}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
