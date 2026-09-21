"""TEST-SCRIPTS-2: the Phase 05 protocol/summary scripts run in their SYNTHETIC modes and write schema-valid
experiment logs (no camera, no person, no recording)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from spacedrums.contracts import schema as contract_schema

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _run(args: list[str], tmp: Path) -> tuple[Path, str]:
    res = subprocess.run(
        [sys.executable, args[0], "--experiments-dir", str(tmp), *args[1:]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-3000:]
    runs = [p for p in tmp.iterdir() if p.is_dir()]
    assert len(runs) == 1
    return runs[0], res.stdout


def _check_run(run_dir: Path, phase_task: str, artefact: str) -> dict:
    rec = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    errs = contract_schema.errors("experiment-log", rec)
    assert not errs, errs
    assert rec["status"] == "COMPLETED" and rec["phase"] == "05" and rec["task"] == phase_task
    assert (run_dir / "config.resolved.yaml").exists() and (run_dir / "stdout.log").exists()
    assert any(a["path"] == artefact for a in rec["artefacts"])
    data = json.loads((run_dir / artefact).read_text(encoding="utf-8"))
    assert "SYNTHETIC" in data["label"]
    return data


def test_playability_session_synthetic(tmp_path):
    run_dir, out = _run([str(SCRIPTS / "playability_session.py"), "--synthetic"], tmp_path)
    data = _check_run(run_dir, "05.7", "playability_synthetic.json")
    assert data["commits_during_non_valid"] == 0
    assert data["evaluations"]["repeated"]["arms"]["A"]["false_negatives"] == 0
    assert "| Scenario (SYNTHETIC) |" in out and "RESULT: COMPLETED" in out


def test_induced_loss_synthetic(tmp_path):
    run_dir, out = _run([str(SCRIPTS / "induced_loss_test.py"), "--synthetic"], tmp_path)
    data = _check_run(run_dir, "05.8", "induced_loss_synthetic.json")
    assert (
        all(c["ok"] for c in data["cases"]) and sum(c["commits_during_non_valid"] for c in data["cases"]) == 0
    )
    assert any(c["expect_invalid"] and "I" in c["trace"] for c in data["cases"])
    assert any(not c["expect_invalid"] and "D" in c["trace"] and "I" not in c["trace"] for c in data["cases"])


def test_timing_summary_synthetic(tmp_path):
    run_dir, out = _run([str(SCRIPTS / "timing_summary.py"), "--synthetic"], tmp_path)
    data = _check_run(run_dir, "05.9", "timing_decomposition.json")
    assert (
        data["decomposition"]["live"] is False and data["decomposition"]["audio_out_est_available"] is False
    )
    assert "PENDING" in out and "L_sys_est terms" in out


def test_shadow_compare_synthetic(tmp_path):
    run_dir, out = _run([str(SCRIPTS / "shadow_compare.py"), "--synthetic"], tmp_path)
    data = _check_run(run_dir, "05.10", "shadow_compare.json")
    cmp = data["comparison"]
    assert cmp["n_matched"] > 0 and cmp["commit_advance_B_vs_A_s"]["min_s"] > 0
    assert "not an experimental result" in out


def test_rule_sensitivity_synthetic_quick(tmp_path):
    run_dir, out = _run([str(SCRIPTS / "rule_baseline_sensitivity.py"), "--quick"], tmp_path)
    data = _check_run(run_dir, "05.6", "rule_sensitivity_synthetic.json")
    assert len(data["rows"]) == 2 and {r["motion"] for r in data["rows"]} == {"CV", "CA"}
    assert "not tuning" in data["label"]
