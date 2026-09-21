"""TEST-DATA-5: session verification and the unusable-recording policy (Tasks 06.7, 06.8) on a SYNTHETIC
session recorded through the real record mode + guided recorder: an intact session is ACCEPT with
every integrity check PASS; each corruption is caught by the check that owns it; policy thresholds
produce segment exclusions, session quarantine and schema-valid ExclusionRecords; the verdict is
deterministic; the verify document validates; a session_kind can never be promoted."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from data_helpers import make_session

from spacedrums.contracts import schema as contract_schema
from spacedrums.data.metadata import SessionMetadata
from spacedrums.data.validation import (
    VerifyThresholds,
    format_verdict,
    hand_order_flips,
    read_exclusions,
    validate_verification,
    verify_session,
    write_exclusions,
)


@pytest.fixture(scope="module")
def session(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("raw")
    sd, _meta, _extra = make_session(root, pad_zone=None)
    return sd


def _copy(session: Path, tmp_path: Path) -> Path:
    dst = tmp_path / session.parent.name / session.name
    shutil.copytree(session, dst)
    return dst


def _status(doc, cid):
    return next(c["status"] for c in doc["checks"] if c["id"] == cid)


def test_intact_synthetic_session_is_accepted_and_document_validates(session):
    doc = verify_session(session, write=True, git_sha="c" * 40)
    assert doc["verdict"] == "ACCEPT", doc["reasons"]
    assert validate_verification(doc) == []
    assert doc["session_kind"] == "SYNTHETIC" and "SYNTHETIC" in doc["label"]
    for cid in (
        "V-FILES",
        "V-META-SCHEMA",
        "V-CONFIG-HASH",
        "V-HEADERS",
        "V-FRAMES-SCHEMA",
        "V-FRAME-ORDER",
        "V-FRAME-FILES",
        "V-CAMERA",
        "V-FPS",
        "V-RECORDS-SCHEMA",
        "V-RECORD-FRAMES",
        "V-REFS",
        "V-TRACK",
        "V-ZONES",
        "V-SAFETY",
        "V-SEGMENTS",
    ):
        assert _status(doc, cid) == "PASS", cid
    assert _status(doc, "V-CONSENT") == "SKIP" and _status(doc, "V-AUDIO") == "SKIP"
    q = doc["quality"]
    assert q["frames"] > 0 and q["dropped"] == 0 and q["events"]["commits_during_non_valid"] == 0
    assert q["events"]["commits_by_arm"].get("A", 0) >= 1  # single hits produced reactive commits
    assert q["storage"]["frames_bytes"] > 0 and q["tracking"]["RIGHT"]["valid_fraction"] > 0.5
    assert {s["segment_id"] for s in doc["segments"]} == {"s01_single", "s02_fake"}
    assert all(s["verdict"] == "ACCEPT" for s in doc["segments"])
    assert (session / "verify.json").exists()
    meta = SessionMetadata.read(session)
    assert meta.data["measured_fps"] is not None and meta.errors() == []  # verify fills the measured FPS
    assert "verdict: ACCEPT" in format_verdict(doc)


def test_verification_is_deterministic(session):
    a = verify_session(session, write=False, git_sha="c" * 40)
    b = verify_session(session, write=False, git_sha="c" * 40)
    strip = lambda d: {k: v for k, v in d.items() if k not in ("generated_at",)}  # noqa: E731
    ex = lambda d: [{k: v for k, v in e.items() if k != "decided_at"} for e in d["exclusions"]]  # noqa: E731
    assert strip({**a, "exclusions": []}) == strip({**b, "exclusions": []}) and ex(a) == ex(b)


def test_missing_image_is_quarantined(session, tmp_path):
    sd = _copy(session, tmp_path)
    png = sorted((sd / "frames").glob("*.png"))[3]
    png.unlink()
    doc = verify_session(sd, write=False)
    assert doc["verdict"] == "QUARANTINE" and _status(doc, "V-FRAME-FILES") == "FAIL"
    assert any(e["level"] == "SESSION" for e in doc["exclusions"])
    assert validate_verification(doc) == []


def test_config_snapshot_tamper_is_quarantined(session, tmp_path):
    sd = _copy(session, tmp_path)
    cfg = yaml.safe_load((sd / "config.snapshot.yaml").read_text(encoding="utf-8"))
    cfg["commit"]["tti_commit_s"] = 0.99
    (sd / "config.snapshot.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    doc = verify_session(sd, write=False)
    assert doc["verdict"] == "QUARANTINE" and _status(doc, "V-CONFIG-HASH") == "FAIL"


def test_frame_order_and_duplicate_timestamps_are_caught(session, tmp_path):
    sd = _copy(session, tmp_path)
    lines = (sd / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    lines[5], lines[6] = lines[6], lines[5]
    (sd / "frames.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    doc = verify_session(sd, write=False)
    assert doc["verdict"] == "QUARANTINE" and _status(doc, "V-FRAME-ORDER") == "FAIL"
    sd2 = _copy(session, tmp_path / "dup")
    lines = (sd2 / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[7])
    rec["t_capture"] = json.loads(lines[6])["t_capture"]
    lines[7] = json.dumps(rec)
    (sd2 / "frames.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    doc = verify_session(sd2, write=False)
    assert _status(doc, "V-FRAME-ORDER") == "FAIL"


def test_malformed_record_and_dangling_reference(session, tmp_path):
    sd = _copy(session, tmp_path)
    path = sd / "records" / "TrackState.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["confidence"] = 7.0  # out of [0, 1]
    lines[1] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    doc = verify_session(sd, write=False)
    assert doc["verdict"] == "QUARANTINE" and _status(doc, "V-RECORDS-SCHEMA") == "FAIL"
    sd2 = _copy(session, tmp_path / "ref")
    path = sd2 / "records" / "CommittedStrike.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 1, "fixture session has no commit"
    rec = json.loads(lines[1])
    rec["candidate_id"] = "nope"
    lines[1] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    doc = verify_session(sd2, write=False)
    assert _status(doc, "V-REFS") == "FAIL" and doc["verdict"] == "REVIEW"


def test_metadata_forged_as_participant_is_quarantined(session, tmp_path):
    sd = _copy(session, tmp_path)
    meta = json.loads((sd / "metadata.json").read_text(encoding="utf-8"))
    meta["session_kind"] = "PARTICIPANT"  # a dev/synthetic session relabelled
    (sd / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    doc = verify_session(sd, write=False)
    assert doc["verdict"] == "QUARANTINE" and _status(doc, "V-META-SCHEMA") == "FAIL"
    sd2 = _copy(session, tmp_path / "gone")
    (sd2 / "metadata.json").unlink()
    doc = verify_session(sd2, write=False)
    assert doc["verdict"] == "QUARANTINE" and _status(doc, "V-FILES") == "FAIL"


def test_segment_policy_thresholds_exclude_segments_and_quarantine_session(session, tmp_path):
    sd = _copy(session, tmp_path)
    th = VerifyThresholds(q_seg=1.01)  # impossible validity -> every take excluded
    doc = verify_session(sd, thresholds=th, write=False)
    assert all(s["verdict"] == "EXCLUDE" for s in doc["segments"])
    assert _status(doc, "V-SESSION-POLICY") == "FAIL" and doc["verdict"] == "QUARANTINE"
    seg_ex = [e for e in doc["exclusions"] if e["level"] == "SEGMENT"]
    assert len(seg_ex) == len(doc["segments"]) and all(
        "LOW_TRACKING_VALIDITY" in e["reason_codes"] for e in seg_ex
    )
    assert all(not contract_schema.errors("exclusion-record", e) for e in doc["exclusions"])
    assert doc["thresholds"]["q_seg"] == 1.01 and doc["thresholds_hash"] != VerifyThresholds().hash
    # milder: only a tolerance change -> REVIEW, not QUARANTINE
    doc2 = verify_session(sd, thresholds=VerifyThresholds(fps_tolerance=0.0), write=False)
    assert doc2["verdict"] == "REVIEW" and any(r.startswith("V-FPS") for r in doc2["reasons"])
    log = tmp_path / "exclusions.jsonl"
    write_exclusions(log, doc["exclusions"])
    write_exclusions(log, doc["exclusions"][:1])
    assert len(read_exclusions(log)) == len(doc["exclusions"]) + 1
    with pytest.raises(ValueError):
        write_exclusions(log, [{"schema_version": "1.0"}])


def test_thresholds_file_and_unknown_keys(tmp_path):
    p = tmp_path / "th.yaml"
    p.write_text("q_seg: 0.7\nq_sess: 0.25\n", encoding="utf-8")
    th = VerifyThresholds.from_file(p)
    assert th.q_seg == 0.7 and th.q_sess == 0.25 and th.fps_tolerance == VerifyThresholds().fps_tolerance
    p.write_text("q_segg: 0.7\n", encoding="utf-8")
    with pytest.raises(ValueError):
        VerifyThresholds.from_file(p)


def test_hand_order_flips_heuristic():
    def obs(fid, hand, x):
        return {"frame_id": fid, "hand_id": hand, "present": True, "landmarks": [[x, 0.5]] + [[0, 0]] * 20}

    hands = [
        obs(0, "LEFT", 0.2),
        obs(0, "RIGHT", 0.8),
        obs(1, "LEFT", 0.9),
        obs(1, "RIGHT", 0.1),
        obs(2, "LEFT", 0.9),
        obs(2, "RIGHT", 0.1),
        obs(3, "LEFT", 0.3),
    ]
    assert hand_order_flips(hands) == (1, 3)
    assert hand_order_flips([]) == (0, 0)
