"""TEST-SCRIPTS-1: the Phase 02 measurement scripts produce schema-valid experiment logs.

Every script is run in its ``--synthetic`` mode (no camera, no window) into a temporary
experiments directory; run.json must validate against schemas/experiment-log.schema.json,
be COMPLETED, carry the config snapshot and list its artefacts with hashes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from spacedrums.contracts import schema as contract_schema

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _run(args: list[str], tmp: Path) -> Path:
    # global options go right after the script path (sub-command scripts parse them first)
    res = subprocess.run([sys.executable, args[0], "--experiments-dir", str(tmp), *args[1:]], cwd=ROOT,
                         capture_output=True, text=True, timeout=180, check=False)
    assert res.returncode == 0, res.stdout[-2000:] + res.stderr[-2000:]
    runs = [p for p in tmp.iterdir() if p.is_dir()]
    assert len(runs) == 1
    return runs[0]


def _check_run(run_dir: Path, phase_task: str, min_artefacts: int = 1) -> dict:
    rec = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    errs = contract_schema.errors("experiment-log", rec)
    assert not errs, errs
    assert rec["status"] == "COMPLETED" and rec["phase"] == "02" and rec["task"] == phase_task
    assert (run_dir / "config.resolved.yaml").exists() and (run_dir / "stdout.log").exists()
    assert len(rec["artefacts"]) >= min_artefacts
    for a in rec["artefacts"]:
        assert (run_dir / a["path"]).exists() and len(a["sha256"]) == 64
    assert rec["environment"]["lock_hash"].startswith("sha256:")
    assert rec["hardware"]["cpu_model"]
    return rec


def test_measure_fps_synthetic(tmp_path):
    run_dir = _run([str(SCRIPTS / "measure_fps.py"), "--synthetic", "--duration", "1.5",
                    "--modes", "64x48@100"], tmp_path)
    rec = _check_run(run_dir, "02.4")
    cell = next(iter(rec["metrics"]["cells"].values()))
    assert cell["fps_delivered"] is not None and cell["n_frames"] > 50
    assert cell["duplicates"] > 0  # the synthetic camera pads every 10th frame; refused, counted
    cells = json.loads((run_dir / "fps_cells.json").read_text(encoding="utf-8"))["cells"]
    assert cells[0]["interval_stats"]["nominal_s"] == pytest.approx(0.01)


def test_measure_capture_latency_synthetic(tmp_path):
    run_dir = _run([str(SCRIPTS / "measure_capture_latency.py"), "--synthetic", "--trials", "3",
                    "--baseline", "0.8"], tmp_path)
    rec = _check_run(run_dir, "02.8")
    m = rec["metrics"]
    assert m["detected"] == 3
    # the synthetic camera injects 20 ms; the half-period-corrected median must land near it
    assert 0.012 < m["corrected_half_period_median_s"] < 0.032
    assert m["capture_latency_raw_median_s"] >= 0.02


def test_enumerate_cameras_synthetic(tmp_path):
    run_dir = _run([str(SCRIPTS / "enumerate_cameras.py"), "--synthetic"], tmp_path)
    _check_run(run_dir, "02.1")


def test_exposure_inspect_synthetic(tmp_path):
    run_dir = _run([str(SCRIPTS / "exposure_blur_check.py"), "--synthetic", "inspect"], tmp_path)
    _check_run(run_dir, "02.5")


def test_show_guide_synthetic_headless(tmp_path):
    shot = tmp_path / "guide.png"
    res = subprocess.run([sys.executable, str(SCRIPTS / "show_guide.py"), "--synthetic", "--no-window",
                          "--duration", "0.8", "--screenshot", str(shot)], cwd=ROOT,
                         capture_output=True, text=True, timeout=120, check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    assert shot.exists() and shot.stat().st_size > 1000
