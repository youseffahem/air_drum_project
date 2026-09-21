"""TEST-DATA-6: raw manifests (Task 06.9) — hashing, ordering, schema validity, kind gating (developer /
synthetic sessions can never enter a participant or pilot manifest; consent must be SIGNED), refusal
of unverified / quarantined sessions, tamper detection, withdrawal records, empty-manifest refusal,
deterministic hashes."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from data_helpers import make_session

from spacedrums.data.manifest import (
    admissible,
    apply_withdrawal,
    build_raw_manifest,
    check_manifest_files,
    manifest_hash,
    manifest_kind,
    read_manifest,
    validate_manifest,
    write_manifest,
)
from spacedrums.data.metadata import SessionMetadata
from spacedrums.data.validation import verify_session


@pytest.fixture(scope="module")
def raw_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("raw")
    a, _, _ = make_session(root, session_id="synthetic-b", seed=3)
    b, _, _ = make_session(root, session_id="synthetic-a", seed=4)
    verify_session(a, git_sha="c" * 40)
    verify_session(b, git_sha="c" * 40)
    make_session(root, session_id="synthetic-unverified", seed=5)  # no verify.json
    return root


def test_manifest_kind_from_version():
    assert manifest_kind("ds-raw-v1.0") == "PARTICIPANT"
    assert manifest_kind("ds-raw-v0.3-pilot") == "PILOT"
    assert manifest_kind("ds-raw-v0.0-selftest") == "SELFTEST"
    assert manifest_kind("ds-raw-v0.0-selftest-devcheck") == "SELFTEST"
    for bad in ("ds-v1.0", "ds-raw-v1.0-selftest", "ds-raw-v0.1-selftest", "raw-v1"):
        with pytest.raises(ValueError):
            manifest_kind(bad)


def test_selftest_manifest_lists_verified_sessions_sorted_with_hashes(raw_root, tmp_path):
    doc = build_raw_manifest(raw_root, "ds-raw-v0.0-selftest-unit", git_sha="c" * 40, git_dirty=False)
    assert validate_manifest(doc) == []
    assert doc["kind"] == "SELFTEST" and "TEST / DEVELOPMENT ONLY" in doc["label"]
    assert [s["session_id"] for s in doc["sessions"]] == [
        "synthetic-a",
        "synthetic-b",
    ]  # sorted, not creation order
    assert [r["session_id"] for r in doc["refused"]] == ["synthetic-unverified"]
    assert "not verified" in doc["refused"][0]["reason"]
    s = doc["sessions"][0]
    assert s["n_files"] == len(s["files"]) and s["total_bytes"] == sum(f["bytes"] for f in s["files"])
    assert [f["path"] for f in s["files"]] == sorted(f["path"] for f in s["files"])
    assert all(f["sha256"].startswith("sha256:") and len(f["sha256"]) == 71 for f in s["files"])
    assert {"frames.jsonl", "metadata.json", "verify.json", "config.snapshot.yaml"} <= {
        f["path"] for f in s["files"]
    }
    assert doc["totals"]["n_sessions"] == 2 and doc["totals"]["n_participants"] == 1
    assert doc["participants"] == ["SYNTHETIC"]
    mpath, epath = write_manifest(doc, tmp_path)
    back = read_manifest(mpath)
    assert back == doc and epath.exists()
    assert check_manifest_files(back, raw_root) == []


def test_tamper_detection_and_hash_determinism(raw_root, tmp_path):
    a = build_raw_manifest(
        raw_root, "ds-raw-v0.0-selftest-unit", git_sha="c" * 40, generated_at="2026-09-21T00:00:00+00:00"
    )
    b = build_raw_manifest(
        raw_root, "ds-raw-v0.0-selftest-unit", git_sha="c" * 40, generated_at="2026-09-21T00:00:00+00:00"
    )
    assert a["manifest_hash"] == b["manifest_hash"] == manifest_hash(a)
    tampered = copy.deepcopy(a)
    tampered["sessions"][0]["files"][0]["bytes"] += 1
    assert validate_manifest(tampered) == ["manifest_hash does not match the document"]
    sd = raw_root / "SYNTHETIC" / "synthetic-a"
    path = sd / "timing.jsonl"
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n")
        problems = check_manifest_files(a, raw_root)
        assert problems and "timing.jsonl" in problems[0]
    finally:
        path.write_bytes(original)
    assert check_manifest_files(a, raw_root) == []


def test_participant_and_pilot_manifests_refuse_synthetic_and_unsigned(raw_root, tmp_path):
    doc = build_raw_manifest(raw_root, "ds-raw-v1.0", git_sha="c" * 40)
    assert doc["sessions"] == [] and len(doc["refused"]) == 3
    assert all(
        "cannot enter a participant manifest" in r["reason"]
        for r in doc["refused"]
        if r["session_id"] != "synthetic-unverified"
    )
    with pytest.raises(ValueError, match="refusing to write an empty PARTICIPANT manifest"):
        write_manifest(doc, tmp_path)
    assert not (tmp_path / "ds-raw-v1.0.json").exists()
    write_manifest(doc, tmp_path, allow_empty=True)  # explicit only
    pilot = build_raw_manifest(raw_root, "ds-raw-v0.1-pilot", git_sha="c" * 40)
    assert pilot["sessions"] == []
    # admissibility rules on metadata documents (no files needed)
    meta = SessionMetadata.read(raw_root / "SYNTHETIC" / "synthetic-a")
    assert admissible("SELFTEST", meta) is None
    assert "cannot enter a participant manifest" in admissible("PARTICIPANT", meta)
    forged = SessionMetadata(copy.deepcopy(meta.data))
    forged.data.update(
        session_kind="PARTICIPANT",
        participant_id="P01",
        session_id="P01-S1",
        consent_status="PENDING",
        consent_record_id=None,
    )
    assert "only SIGNED consent" in admissible("PARTICIPANT", forged)
    forged.data.update(consent_status="SIGNED", consent_record_id="CF-P01")
    assert admissible("PARTICIPANT", forged) is None  # admissible in principle ...
    assert (
        forged.errors()
    )  # ... but the document itself is invalid (SYNTHETIC lighting / source), so the builder refuses it
    pil = SessionMetadata(copy.deepcopy(meta.data))
    pil.data.update(
        session_kind="PILOT", participant_id="PILOT01", session_id="PILOT01-S1", consent_status="PENDING"
    )
    assert "only with SIGNED consent" in admissible("PILOT", pil)
    assert "cannot enter a self-test manifest" in admissible("SELFTEST", pil)


def test_quarantined_and_review_sessions(raw_root, tmp_path):
    sd = raw_root / "SYNTHETIC" / "synthetic-b"
    vpath = sd / "verify.json"
    original = vpath.read_text(encoding="utf-8")
    try:
        v = json.loads(original)
        v["verdict"] = "REVIEW"
        vpath.write_text(json.dumps(v), encoding="utf-8")
        doc = build_raw_manifest(raw_root, "ds-raw-v0.0-selftest-unit", git_sha="c" * 40)
        assert [s["session_id"] for s in doc["sessions"]] == ["synthetic-a"]
        assert any(r["session_id"] == "synthetic-b" and "REVIEW" in r["reason"] for r in doc["refused"])
        doc = build_raw_manifest(raw_root, "ds-raw-v0.0-selftest-unit", git_sha="c" * 40, include_review=True)
        assert [s["session_id"] for s in doc["sessions"]] == ["synthetic-a", "synthetic-b"]
        v["verdict"] = "QUARANTINE"
        vpath.write_text(json.dumps(v), encoding="utf-8")
        doc = build_raw_manifest(raw_root, "ds-raw-v0.0-selftest-unit", git_sha="c" * 40, include_review=True)
        assert [s["session_id"] for s in doc["sessions"]] == ["synthetic-a"]
    finally:
        vpath.write_text(original, encoding="utf-8")


def test_withdrawal_removes_sessions_and_records_it(raw_root):
    doc = build_raw_manifest(raw_root, "ds-raw-v0.0-selftest-unit", git_sha="c" * 40)
    out = apply_withdrawal(doc, "SYNTHETIC", date="2026-09-22", note="unit test")
    assert out["sessions"] == [] and out["participants"] == [] and out["totals"]["n_sessions"] == 0
    assert out["withdrawals"] == [
        {"participant_id": "SYNTHETIC", "date": "2026-09-22", "n_sessions_removed": 2, "note": "unit test"}
    ]
    assert validate_manifest(out) == [] and out["manifest_hash"] != doc["manifest_hash"]
    untouched = apply_withdrawal(doc, "P99", date="2026-09-22")
    assert len(untouched["sessions"]) == 2 and untouched["withdrawals"][0]["n_sessions_removed"] == 0
