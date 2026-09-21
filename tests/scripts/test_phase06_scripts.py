"""TEST-SCRIPTS-3: the Phase 06 scripts run in their SYNTHETIC / DEV CAPTURE modes and write schema-valid
experiment logs, sessions, verification documents and manifests (no camera, no person, no recording).
The ``--live`` mode is never exercised here."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from spacedrums.contracts import schema as contract_schema
from spacedrums.data.manifest import read_manifest
from spacedrums.data.validation import validate_verification

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
DEV_CAPTURE = ROOT / "data" / "dev-captures" / "swing-L2-exp-5"


def _run(args: list[str], *, check: bool = True, timeout: int = 900) -> subprocess.CompletedProcess:
    res = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if check:
        assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-3000:]
    return res


def _check_run(run_dir: Path, task: str) -> dict:
    rec = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    errs = contract_schema.errors("experiment-log", rec)
    assert not errs, errs
    assert rec["status"] == "COMPLETED" and rec["phase"] == "06" and rec["task"] == task
    assert (run_dir / "config.resolved.yaml").exists() and (run_dir / "stdout.log").exists()
    return rec


@pytest.fixture(scope="module")
def synthetic_run(tmp_path_factory):
    """One SYNTHETIC full-protocol session with the pad condition, verified, kept on disk."""
    exp = tmp_path_factory.mktemp("exp")
    raw = tmp_path_factory.mktemp("raw")
    res = _run(
        [
            str(SCRIPTS / "record_session.py"),
            "--synthetic",
            "--pad-zone",
            "snare",
            "--verify",
            "--duration-scale",
            "0.04",
            "--keep-temp",
            "--output-root",
            str(raw),
            "--experiments-dir",
            str(exp),
            "--slug",
            "scripts-test",
        ]
    )
    runs = [p for p in exp.iterdir() if p.is_dir()]
    assert len(runs) == 1
    return runs[0], raw / "SYNTHETIC" / "synthetic-scripts-test", res.stdout


def test_record_session_synthetic_writes_a_complete_verified_session(synthetic_run):
    run_dir, session_dir, out = synthetic_run
    rec = _check_run(run_dir, "06.10")
    assert rec["metrics"]["label"] == "SYNTHETIC" and rec["metrics"]["commits_during_non_valid"] == 0
    assert any(a["path"] == "record_session.json" for a in rec["artefacts"])
    data = json.loads((run_dir / "record_session.json").read_text(encoding="utf-8"))
    assert "SYNTHETIC" in data["label"] and "not participant evidence" in data["label"]
    assert (
        data["session_kind"] == "SYNTHETIC" and data["has_phys_gt"] is True
    )  # synthetic click track present
    assert data["protocol"]["version"].endswith("-draft")
    assert "RESULT: COMPLETED" in out and "SYNTHETIC" in out and "pilot" in out.lower()
    for name in (
        "metadata.json",
        "verify.json",
        "frames.jsonl",
        "timing.jsonl",
        "config.snapshot.yaml",
        "audio_track.wav",
        "session.json",
    ):
        assert (session_dir / name).exists(), name
    meta = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
    assert not contract_schema.errors("session-metadata", meta)
    assert meta["session_kind"] == "SYNTHETIC" and meta["participant_id"] == "SYNTHETIC"
    assert (
        meta["consent_status"] == "NOT_REQUIRED" and meta["participant_meta"]["handedness"] == "NOT_COLLECTED"
    )
    types = {s["type"] for s in meta["segments"]}
    assert {
        "WARMUP",
        "SINGLE_HITS",
        "TEMPO",
        "RAPID",
        "FAKE_SWING",
        "STOP_BEFORE_IMPACT",
        "OCCLUSION",
        "TRACKING_INTERRUPTION",
        "PAD_MIC",
    } <= types
    assert meta["measured_fps"] is not None  # filled by verify
    verify = json.loads((session_dir / "verify.json").read_text(encoding="utf-8"))
    assert validate_verification(verify) == []
    assert verify["verdict"] in ("ACCEPT", "REVIEW") and verify["sync"]["n_matched"] == 2
    assert all(
        c["status"] == "PASS"
        for c in verify["checks"]
        if c["id"]
        in (
            "V-FILES",
            "V-META-SCHEMA",
            "V-CONFIG-HASH",
            "V-FRAME-ORDER",
            "V-RECORDS-SCHEMA",
            "V-SAFETY",
            "V-SEGMENTS",
            "V-AUDIO",
        )
    )


def test_verify_session_script_and_exclusions_log(synthetic_run, tmp_path):
    _run_dir, session_dir, _ = synthetic_run
    th = tmp_path / "th.yaml"
    th.write_text("q_seg: 1.01\n", encoding="utf-8")  # every take excluded -> session rule -> QUARANTINE
    log = tmp_path / "exclusions.jsonl"
    res = _run(
        [
            str(SCRIPTS / "verify_session.py"),
            str(session_dir),
            "--thresholds",
            str(th),
            "--exclusions-log",
            str(log),
            "--no-write",
        ],
        check=False,
    )
    assert res.returncode == 2, res.stdout[-2000:]
    assert "verdict: QUARANTINE" in res.stdout and "V-SESSION-POLICY" in res.stdout
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines and all(not contract_schema.errors("exclusion-record", e) for e in lines)
    assert any(e["level"] == "SESSION" for e in lines)
    res = _run([str(SCRIPTS / "verify_session.py"), str(session_dir), "--json"])
    doc = json.loads(res.stdout[res.stdout.index("{") :])
    assert doc["verdict"] in ("ACCEPT", "REVIEW")


def test_build_raw_manifest_script_selftest_and_refused_participant(synthetic_run, tmp_path):
    _run_dir, session_dir, _ = synthetic_run
    raw_root = session_dir.parents[1]
    res = _run(
        [
            str(SCRIPTS / "build_raw_manifest.py"),
            "build",
            "ds-raw-v0.0-selftest-scripts",
            "--raw-root",
            str(raw_root),
            "--manifests-dir",
            str(tmp_path),
            "--include-review",
        ]
    )
    assert "TEST / DEVELOPMENT ONLY" in res.stdout
    doc = read_manifest(tmp_path / "ds-raw-v0.0-selftest-scripts.json")
    assert doc["kind"] == "SELFTEST" and [s["session_id"] for s in doc["sessions"]] == [
        "synthetic-scripts-test"
    ]
    assert (tmp_path / "ds-raw-v0.0-selftest-scripts.exclusions.jsonl").exists()
    res = _run(
        [
            str(SCRIPTS / "build_raw_manifest.py"),
            "check",
            str(tmp_path / "ds-raw-v0.0-selftest-scripts.json"),
            "--raw-root",
            str(raw_root),
        ]
    )
    assert "0 problems" in res.stdout
    res = _run(
        [
            str(SCRIPTS / "build_raw_manifest.py"),
            "build",
            "ds-raw-v1.0",
            "--raw-root",
            str(raw_root),
            "--manifests-dir",
            str(tmp_path),
        ],
        check=False,
    )
    assert (
        res.returncode == 3
        and "NOT written" in res.stdout
        and "cannot enter a participant manifest" in res.stdout
    )
    assert not (tmp_path / "ds-raw-v1.0.json").exists()
    res = _run(
        [
            str(SCRIPTS / "build_raw_manifest.py"),
            "withdraw",
            str(tmp_path / "ds-raw-v0.0-selftest-scripts.json"),
            "--participant",
            "SYNTHETIC",
            "--date",
            "2026-09-22",
        ]
    )
    assert "1 session(s) removed" in res.stdout
    doc = read_manifest(tmp_path / "ds-raw-v0.0-selftest-scripts.json")
    assert doc["sessions"] == [] and doc["withdrawals"][0]["participant_id"] == "SYNTHETIC"


def test_session_checklist_script(tmp_path):
    sd = tmp_path / "P01-S1"
    res = _run(
        [
            str(SCRIPTS / "session_checklist.py"),
            str(sd),
            "--operator",
            "XX",
            "--yes",
            "CL-04",
            "CL-07",
            "--na",
            "CL-11",
            "--note",
            "CL-06=L2",
        ]
    )
    assert "3/15 items answered" in res.stdout
    doc = json.loads((sd / "checklist.json").read_text(encoding="utf-8"))
    assert doc["complete"] is False and doc["all_yes_or_na"] is False
    assert {i["id"]: i["answer"] for i in doc["items"]}["CL-01"] == "NOT_ANSWERED"
    assert {i["id"]: i["note"] for i in doc["items"]}["CL-06"] == "L2"
    res = _run(
        [str(SCRIPTS / "session_checklist.py"), str(sd), "--operator", "XX", "--yes", "CL-99"], check=False
    )
    assert res.returncode == 1


def test_record_session_live_refuses_without_kind():
    res = _run([str(SCRIPTS / "record_session.py"), "--live"], check=False)
    assert res.returncode != 0 and "--kind" in (res.stdout + res.stderr)


@pytest.mark.skipif(not DEV_CAPTURE.exists(), reason="developer capture not present on this machine")
def test_record_session_devcapture_ingest_check(tmp_path):
    exp = tmp_path / "exp"
    raw = tmp_path / "raw"
    res = _run(
        [
            str(SCRIPTS / "record_session.py"),
            "--devcapture",
            "swing-L2-exp-5",
            "--verify",
            "--duration-scale",
            "0.02",
            "--output-root",
            str(raw),
            "--experiments-dir",
            str(exp),
            "--slug",
            "ingest-test",
            "--max-frames",
            "60",
        ]
    )
    run_dir = next(p for p in exp.iterdir() if p.is_dir())
    rec = _check_run(run_dir, "06.10")
    assert rec["metrics"]["label"] == "DEV CAPTURE"
    sd = raw / "DEV" / "dev-ingest-test"
    meta = json.loads((sd / "metadata.json").read_text(encoding="utf-8"))
    assert (
        meta["session_kind"] == "DEV_CAPTURE"
        and meta["participant_id"] == "DEV"
        and meta["source"]["kind"] == "REPLAY"
    )
    assert meta["camera_profile_id"] == "hw01-integrated-webcam-v0"
    verify = json.loads((sd / "verify.json").read_text(encoding="utf-8"))
    assert validate_verification(verify) == [] and "DEV CAPTURE" in verify["label"]
    assert all(
        c["status"] == "PASS"
        for c in verify["checks"]
        if c["id"]
        in (
            "V-FILES",
            "V-META-SCHEMA",
            "V-CONFIG-HASH",
            "V-FRAME-ORDER",
            "V-FRAME-FILES",
            "V-RECORDS-SCHEMA",
            "V-SAFETY",
        )
    )
    assert "DEV CAPTURE" in res.stdout
    # Task 06.3: re-track the recorded raw frames and compare the derived records (regeneration check)
    res = _run(
        [
            str(SCRIPTS / "regenerate_session.py"),
            str(sd),
            "--no-runlog",
            "--max-frames",
            "60",
        ],
        check=False,
    )
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-2000:]
    assert "RESULT: BIT-IDENTICAL" in res.stdout or "RESULT: DECISION-IDENTICAL" in res.stdout
    assert "('REPLAY', 'REGENERATED')" in res.stdout


def test_regenerate_session_refuses_to_compare_synthetic_frames(synthetic_run):
    _run_dir, session_dir, _ = synthetic_run
    res = _run([str(SCRIPTS / "regenerate_session.py"), str(session_dir), "--no-runlog"])
    assert "not comparable" in res.stdout
