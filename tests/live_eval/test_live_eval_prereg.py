"""Phase 18 pre-registration precedence: hash record, locks, execute-once ledger (TEST-P18-PREREG)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from spacedrums.live_eval import hypotheses as hyp
from spacedrums.live_eval.prereg import (
    Ledger,
    PreregError,
    archive_document,
    archive_lock,
    document_digest,
    lock_digest,
    lock_errors,
    verify_document,
    verify_lock,
)

ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / "docs/experiments/phase-18-prereg.md"
RECORD = ROOT / "docs/experiments/phase-18-prereg.hashes.json"
DOC = "docs/experiments/phase-18-prereg.md"
EXAMPLE = ROOT / "schemas/examples/confirmatory-lock.valid.example.json"


def _archive(doc: Path, record: Path, note: str = "v", **kw) -> dict:
    return archive_document(
        doc,
        record,
        document=DOC,
        archived_at="2026-09-27T08:00:00+03:00",
        git_head="0" * 40,
        git_dirty=True,
        note=note,
        **kw,
    )


def _lock(version: int, digest: str) -> dict:
    lock = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    lock["prereg"] = {"path": DOC, "version": version, "sha256": digest}
    return lock


def test_the_tracked_preregistration_matches_its_archived_hash_and_names_every_rule():
    check = verify_document(PREREG, RECORD, document=DOC)
    assert check["ok"], check
    text = PREREG.read_text(encoding="utf-8")
    for hid in hyp.HYPOTHESES:
        assert f"**{hid}**" in text, hid
    for phrase in (
        "SUPPORTED iff CI low > 0",
        "CI high ≤ `B_FP`",
        "CI high < −`U`",
        "δ_TE = max(δ_audio, 2 · s_phys)",
        "10,000 resamples",
        "default_rng(18)",
        "Williams design",
        "U_M1 = sqrt(e95_click² + r_pad²) ≤ 5 ms",
    ):
        assert phrase in text, phrase


def test_archive_is_append_only_and_a_version_after_a_lock_needs_a_reason(tmp_path):
    doc, record = tmp_path / "prereg.md", tmp_path / "record.json"
    doc.write_text("rules v1\r\n", encoding="utf-8", newline="")
    first = _archive(doc, record)
    assert first["version"] == 1 and first["sha256"] == document_digest(doc)
    assert _archive(doc, record).get("unchanged") is True
    doc.write_bytes(b"rules v1\n")  # line endings alone do not change the digest
    assert verify_document(doc, record, document=DOC)["ok"]
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock(1, first["sha256"])), encoding="utf-8")
    entry = archive_lock(
        lock_path,
        record,
        document=DOC,
        doc_path=doc,
        archived_at="2026-09-27T09:00:00+03:00",
        git_head="0" * 40,
    )
    assert entry["prereg_version"] == 1
    doc.write_text("rules v2\n", encoding="utf-8")
    assert not verify_document(doc, record, document=DOC)["ok"]
    with pytest.raises(PreregError, match="new pre-registered run"):
        _archive(doc, record)
    second = _archive(doc, record, after_lock_reason="owner amendment after review")
    assert second["version"] == 2 and second["new_preregistered_run"] is True


def test_lock_validation_refuses_placeholders_and_inconsistent_arms():
    lock = _lock(1, "sha256:" + "a" * 64)
    assert lock_errors(lock) == []
    bad = copy.deepcopy(lock)
    bad["offline"]["matching"]["provenance"]["decided_by"] = "PENDING owner"
    assert any("placeholder" in e for e in lock_errors(bad))
    bad = copy.deepcopy(lock)
    bad["offline"]["c_primary"] = bad["offline"]["b_primary"]
    assert any("c_primary" in e for e in lock_errors(bad))
    bad = copy.deepcopy(lock)
    bad["offline"]["budgets"]["delta_te_s"] = 0.5
    assert any("delta_te_s" in e for e in lock_errors(bad))
    bad = copy.deepcopy(lock)
    bad["evidence"] = "PARTICIPANT"
    assert lock_errors(bad)  # git_dirty true and a SELFTEST dataset are refused for participant locks


def test_verify_lock_needs_archiving_after_the_latest_version(tmp_path):
    doc, record = tmp_path / "prereg.md", tmp_path / "record.json"
    doc.write_text("rules\n", encoding="utf-8")
    v1 = _archive(doc, record)
    lock = _lock(1, v1["sha256"])
    assert (
        verify_lock(lock, record, document=DOC, doc_path=doc)["reason"]
        == "lock not archived in the hash record"
    )
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    archive_lock(
        lock_path,
        record,
        document=DOC,
        doc_path=doc,
        archived_at="2026-09-27T09:00:00+03:00",
        git_head="0" * 40,
    )
    assert verify_lock(lock, record, document=DOC, doc_path=doc)["ok"]
    stale = _lock(1, "sha256:" + "b" * 64)
    stale_path = tmp_path / "stale.json"
    stale_path.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(PreregError, match="latest archived"):
        archive_lock(
            stale_path,
            record,
            document=DOC,
            doc_path=doc,
            archived_at="2026-09-27T09:30:00+03:00",
            git_head="0" * 40,
        )
    assert lock_digest(lock) != lock_digest(stale)


def test_participant_use_needs_a_recorded_approval_of_the_latest_version(tmp_path):
    doc, record = tmp_path / "prereg.md", tmp_path / "record.json"
    doc.write_text("rules\n", encoding="utf-8")
    v1 = _archive(doc, record)
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(_lock(1, v1["sha256"])), encoding="utf-8")
    kw = {"document": DOC, "doc_path": doc, "archived_at": "2026-09-27T09:00:00+03:00", "git_head": "0" * 40}
    with pytest.raises(PreregError, match="approval"):
        archive_lock(lock_path, record, require_approval=True, **kw)
    archive_lock(lock_path, record, **kw)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert (
        "approval" in verify_lock(lock, record, document=DOC, doc_path=doc, require_approval=True)["reason"]
    )
    data = json.loads(record.read_text(encoding="utf-8"))
    data["approvals"].append({"version": 1, "by": "owner", "date": "2026-09-28"})
    record.write_text(json.dumps(data), encoding="utf-8")
    assert verify_lock(lock, record, document=DOC, doc_path=doc, require_approval=True)["ok"]


def test_ledger_refuses_a_second_participant_execution_without_a_reviewed_reason(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    kw = {"lock_sha256": "sha256:" + "c" * 64, "at": "2026-09-27T10:00:00+03:00", "git_head": "0" * 40}
    ledger.reserve(run_id="r1", evidence="PARTICIPANT", **kw)
    ledger.finish(lock_sha256=kw["lock_sha256"], run_id="r1", status="FAILED", at=kw["at"])
    with pytest.raises(PreregError, match="already executed"):
        ledger.reserve(run_id="r2", evidence="PARTICIPANT", **kw)
    retry = ledger.reserve(
        run_id="r2", evidence="PARTICIPANT", retry_reason="crash reviewed by the owner", **kw
    )
    assert retry["attempt"] == 2
    ledger.reserve(run_id="s1", evidence="SYNTHETIC_REHEARSAL", **kw)  # rehearsals may repeat
    assert [e["event"] for e in ledger.entries()] == ["RESERVED", "FAILED", "RESERVED", "RESERVED"]
    with pytest.raises(ValueError):
        ledger.finish(lock_sha256=kw["lock_sha256"], run_id="r2", status="DONE", at=kw["at"])
