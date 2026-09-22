"""Development verification of Phase 09 machinery on available self-test inputs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _runlog import RunLog

from spacedrums.config import load_config

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
SCRIPTS = Path(__file__).parent
FEATURES = ROOT / (
    "data/features/ds-v0.0-selftest-features/fs-v1/20260922-2115-p08-gate-verification/unit-folds"
)


def main():
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    with RunLog(
        phase="09",
        task="09.4",
        slug="p09-development-verification",
        config=cfg,
        description="Phase 09 self-test and developer diagnostic; no participant dataset available.",
        experiments_dir=ROOT / "experiments/phase-09",
        seed=9,
    ) as run:
        checks = []

        def execute(name: str, args: list[str]) -> None:
            proc = subprocess.run(
                args,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            path = run.dir / f"{len(checks):02d}-{name}.log"
            path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
            run.add_artefact(path, "other")
            checks.append({"name": name, "command": args, "exit_code": proc.returncode, "log": path.name})
            print(f"{name}: {'PASS' if proc.returncode == 0 else 'FAIL'}")
            if proc.returncode:
                raise RuntimeError(f"{name} failed; see {path}")

        execute("focused-tests", [PYTHON, "-m", "pytest", "tests/eval", "-q"])
        execute("full-regression", [PYTHON, "-m", "pytest", "-q"])
        execute("ruff", [str(Path(PYTHON).parent / "ruff.exe"), "check", "."])
        execute("import-linter", [str(Path(PYTHON).parent / "lint-imports.exe"), "--config", ".importlinter"])
        execute(
            "dev-baselines",
            [
                PYTHON,
                str(SCRIPTS / "eval_baselines.py"),
                "--session-dir",
                "data/raw/DEV/dev-p06-ingest-exp-5",
                "--label-dir",
                "data/labels/dev-p06-ingest-exp-5",
                "--output",
                str(run.dir / "baselines-dev"),
                "--selftest",
            ],
        )
        execute(
            "synthetic-baselines",
            [
                PYTHON,
                str(SCRIPTS / "eval_baselines.py"),
                "--session-dir",
                "data/raw/SYNTHETIC/synthetic-p07-labels",
                "--label-dir",
                "data/labels/synthetic-p07-labels",
                "--output",
                str(run.dir / "baselines-synthetic"),
                "--selftest",
            ],
        )
        execute(
            "gbdt-train",
            [
                PYTHON,
                str(SCRIPTS / "train_gbdt.py"),
                "--features-dir",
                str(FEATURES),
                "--output",
                str(run.dir / "gbdt"),
                "--seed",
                "9",
            ],
        )
        for fold in range(3):
            model = run.dir / f"gbdt/fold-{fold}"
            samples = FEATURES / f"fold-{fold}/samples.val.npz"
            execute(
                f"gbdt-val-{fold}",
                [
                    PYTHON,
                    str(SCRIPTS / "gbdt_sample_diagnostics.py"),
                    "--model-dir",
                    str(model),
                    "--samples",
                    str(samples),
                    "--output",
                    str(model / "diagnostics.val.json"),
                ],
            )
        execute(
            "gbdt-event-replay",
            [
                PYTHON,
                str(SCRIPTS / "gbdt_fixture_replay.py"),
                "--model-dir",
                str(run.dir / "gbdt/fold-0"),
                "--fold-dir",
                str(FEATURES / "fold-0"),
                "--output",
                str(run.dir / "gbdt-event-replay"),
            ],
        )
        execute(
            "gbdt-latency",
            [
                PYTHON,
                str(SCRIPTS / "gbdt_latency.py"),
                "--model-dir",
                str(run.dir / "gbdt/fold-0"),
                "--samples",
                str(FEATURES / "fold-0/samples.val.npz"),
                "--output",
                str(run.dir / "gbdt/fold-0/latency.json"),
                "--calls",
                "500",
                "--warmup",
                "50",
            ],
        )
        summary = {
            "evidence_class": "SYNTHETIC/DEV CAPTURE; development run; no participant claim",
            "checks": checks,
            "participant_dataset_present": False,
            "primary_W_frozen": False,
            "phase_gate": "FAIL: participant results and clean-tree rerun unavailable",
        }
        (run.dir / "verification.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        for path in sorted(run.dir.rglob("*")):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                if path.name not in {c["log"] for c in checks}:
                    run.add_artefact(path, "other")
        run.finish(
            {"checks_passed": len(checks), "selftest_gbdt_folds": 3},
            notes="The self-test fixture uses generated identities; ds-none-v0.0 denotes no "
            "participant dataset in this experiment-log schema. "
            "Dirty-tree outputs are development evidence only.",
        )
        print(run.dir)


if __name__ == "__main__":
    main()
