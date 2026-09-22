"""Reproducible Phase 08 gate verification, including owner post-commit clean reruns.

No Git history is changed. Existing raw sessions are replayed; no participant recording is made.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from _runlog import RunLog, git_dirty  # noqa: E402

from spacedrums.config import load_config  # noqa: E402
from spacedrums.features.windows import WindowParams  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-clean", action="store_true")
    ap.add_argument("--labels-root", type=Path, default=ROOT / "data/labels")
    ap.add_argument("--experiments-dir", type=Path, default=ROOT / "experiments/phase-08")
    args = ap.parse_args(argv)
    if args.require_clean and git_dirty():
        ap.error("owner commit required: working tree is dirty")
    cfg = load_config(
        ROOT / "configs/prototype.candidate.yaml",
        ROOT / "configs/features/fs-v1.candidate.yaml",
        overrides={"features": {"window": asdict(WindowParams(8, 4, 0.1, 0.3, 1, 1))}},
    )
    py = sys.executable
    bindir = Path(py).parent
    commands = [
        [
            py,
            "-m",
            "pytest",
            "tests/labels/test_label_leakage.py",
            "tests/features",
            "tests/architecture",
            "tests/contracts",
            "tests/scripts/test_phase08_scripts.py",
            "-o",
            "addopts=",
            "-q",
            "--strict-markers",
        ],
        [py, "-m", "pytest", "-o", "addopts=", "-q", "--strict-markers"],
        [str(bindir / "ruff.exe"), "check", "."],
        [str(bindir / "lint-imports.exe"), "--config", ".importlinter"],
        [py, "scripts/validate_contracts.py"],
        [py, "scripts/env_smoke.py"],
        [py, "scripts/fetch_hand_landmarker_model.py", "--verify"],
        [py, "scripts/fetch_drum_samples.py", "--verify"],
        ["git", "diff", "--check"],
    ]
    with RunLog(
        phase="08",
        task="08.10",
        slug="p08-gate-verification",
        config=cfg,
        description="Phase 08 gate verification: tests/static checks; separate SYNTHETIC UNIT fixture, "
        "SYNTHETIC session, DEV CAPTURE replay and CPU compute timing. No participant dataset.",
        experiments_dir=args.experiments_dir,
    ) as run:
        children = run.dir / "children"
        common = [
            "--n",
            "8",
            "--k",
            "4",
            "--h",
            ".1",
            "--h-max",
            ".3",
            "--stride",
            "1",
            "--g-win",
            "1",
            "--experiments-dir",
            str(children),
        ]
        data_root = ROOT / "data/features/ds-v0.0-selftest-features/fs-v1" / run.run_id
        for script, name in (("build_features", "unit-folds"), ("compute_norm_stats", "unit-stats")):
            commands.append(
                [py, f"scripts/{script}.py", "--synthetic-fixture", "--out", str(data_root / name), *common]
            )
        for kind, session in (("DEV", "dev-p06-ingest-exp-5"), ("SYNTHETIC", "synthetic-p07-labels")):
            commands.append(
                [
                    py,
                    "scripts/build_features.py",
                    "--selftest",
                    "--session",
                    str(ROOT / "data/raw" / kind / session),
                    "--labels",
                    str(args.labels_root / session),
                    "--out",
                    str(data_root / session),
                    *common,
                ]
            )
        commands.append(
            [
                py,
                "scripts/feature_latency.py",
                "--synthetic",
                "--iterations",
                "2000",
                "--warmup",
                "200",
                "--experiments-dir",
                str(children),
            ]
        )
        results = []
        for i, command in enumerate(commands):
            start = perf_counter()
            result = subprocess.run(
                command, cwd=ROOT, capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"}
            )
            log = run.dir / f"{i:02d}.log"
            log.write_bytes(result.stdout + result.stderr)
            run.add_artefact(log, "log")
            results.append(
                {
                    "command": command,
                    "exit_code": result.returncode,
                    "seconds": perf_counter() - start,
                    "log": str(log),
                    "git_dirty_after": git_dirty(),
                }
            )
            (run.dir / "verification.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(f"[{i + 1}/{len(commands)}] exit={result.returncode}: {' '.join(command[:4])}", flush=True)
        run.add_artefact(run.dir / "verification.json", "other")
        for path in sorted(children.rglob("*")):
            if path.is_file():
                run.add_artefact(path, "other")
        for path in sorted(data_root.rglob("*")):
            if path.is_file():
                run.add_artefact(path, "other")
        # Capture exact uncommitted implementation fingerprints without touching the index.
        source_hashes = {}
        from _runlog import sha256_file

        for base in ("src", "scripts", "tests", "schemas", "configs"):
            for path in sorted((ROOT / base).rglob("*")):
                if path.is_file() and path.suffix in (".py", ".json", ".yaml"):
                    source_hashes[path.relative_to(ROOT).as_posix()] = sha256_file(path)
        run.write_json_artefact("source-hashes.json", source_hashes, "other")
        ok = all(r["exit_code"] == 0 for r in results)
        if args.require_clean:
            ok = ok and not any(r["git_dirty_after"] for r in results)
        run.finish(
            {"all_passed": ok, "commands": results},
            status="COMPLETED" if ok else "FAILED",
            notes="Re-run this script with --require-clean after owner commit. Dirty results are "
            "DEVELOPMENT evidence only. Participant conditions remain pending regardless of test success.",
        )
        print(f"RESULT: {'PASS' if ok else 'FAIL'}; {run.dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
