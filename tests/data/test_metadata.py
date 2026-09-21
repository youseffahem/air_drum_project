"""TEST-DATA-2: SessionMetadata (Task 06.4) — schema + invariants, the four session kinds, structural
refusal of developer/synthetic material as participant data, consent gating, has_phys_gt rule,
re-take flags, NOT_COLLECTED defaults, naming, round trip."""

from __future__ import annotations

import copy

import pytest

from spacedrums.contracts import schema as contract_schema
from spacedrums.data.metadata import (
    ConsentStatus,
    SessionKind,
    SessionMetadata,
    classification_label,
    participant_id_for,
    session_id_for,
    validate_metadata,
)
from spacedrums.data.protocol import SegmentSpec, SegmentType


def _meta(kind: SessionKind, **kw) -> SessionMetadata:
    pid = participant_id_for(
        kind, kw.pop("participant_id", "P01" if kind is SessionKind.PARTICIPANT else "PILOT01")
    )
    sid = session_id_for(kind, pid, 1, slug="unit")
    base = dict(
        kind=kind,
        session_id=sid,
        participant_id=pid,
        session_index=1,
        date="2026-09-21",
        started_at="2026-09-21T12:00:00+03:00",
        t_mono_at_start=100.0,
        hardware_id="HW-01",
        camera_profile_id="synthetic-camera"
        if kind is SessionKind.SYNTHETIC
        else "hw01-integrated-webcam-v0",
        audio_profile_id="example-audio-profile",
        roi_px=(40, 20, 560, 440),
        config_hash="sha256:" + "0" * 64,
        git_sha="a" * 40,
        clock_id="perf_counter",
        zone_layout_id="mvp4",
        arm_active="A",
        arms_shadow=["B"],
        tip_method_active="GEOM",
        protocol=None,
        source={"kind": "SYNTHETIC" if kind is SessionKind.SYNTHETIC else "LIVE", "detail": {}},
        video={
            "container": "PNG_SEQUENCE",
            "codec": "png",
            "lossless": True,
            "crop": "FULL",
            "frame_size_px": [640, 480],
            "parameters": {},
        },
    )
    if kind in (SessionKind.PARTICIPANT, SessionKind.PILOT):
        base["lighting"] = {
            "id": "L2",
            "description": "room light",
            "mean_luminance_auto": None,
            "auto_exposure_unique_fps": None,
            "exposure_used": None,
            "flicker_note": "",
            "second_condition_id": None,
        }
        base["background"] = {"tag": "CLEAN", "people_present": False, "description": ""}
    if kind is SessionKind.DEV_CAPTURE:
        base["source"] = {"kind": "REPLAY", "detail": {}}
    base.update(kw)
    return SessionMetadata.new(**base)


def test_every_kind_builds_a_valid_document_with_explicit_not_collected_defaults():
    for kind in SessionKind:
        extra = (
            {"consent_status": "SIGNED", "consent_record_id": "CF-x"}
            if kind is SessionKind.PARTICIPANT
            else {}
        )
        m = _meta(kind, **extra)
        assert m.errors() == [], (kind, m.errors())
        pm = m.data["participant_meta"]
        assert pm["handedness"] == "NOT_COLLECTED" and pm["experience"] == "NOT_COLLECTED"
        assert m.data["measured_fps"] is None and m.data["capture_stats"] is None
        assert m.data["has_phys_gt"] is False and m.data["dataset_version"] == "ds-none-v0.0"
        assert kind.value.replace("_", " ") in classification_label(kind)
    assert _meta(SessionKind.SYNTHETIC).data["consent_status"] == "NOT_REQUIRED"
    assert _meta(SessionKind.PILOT).data["consent_status"] == "PENDING"  # never assumed signed


def test_synthetic_or_dev_material_cannot_be_promoted_to_participant_data():
    m = _meta(SessionKind.SYNTHETIC)
    promoted = copy.deepcopy(m.data)
    promoted["session_kind"] = "PARTICIPANT"
    assert validate_metadata(promoted)  # ids, consent, lighting, source all contradict PARTICIPANT
    for field, value in (
        ("participant_id", "P01"),
        ("dataset_version", "ds-raw-v1.0"),
        ("consent_status", "SIGNED"),
        ("session_id", "P01-S1"),
    ):
        d = copy.deepcopy(m.data)
        d[field] = value
        assert validate_metadata(d), field
    dev = _meta(SessionKind.DEV_CAPTURE)
    assert (
        dev.errors() == []
        and dev.data["participant_id"] == "DEV"
        and dev.data["session_id"].startswith("dev-")
    )
    d = copy.deepcopy(dev.data)
    d["dataset_version"] = "ds-raw-v1.0-pilot"
    assert validate_metadata(d)
    d = copy.deepcopy(dev.data)
    d["dataset_version"] = "ds-raw-v0.0-selftest-x"
    assert validate_metadata(d) == []


def test_participant_session_requires_signed_consent_with_a_record_id():
    assert (
        _meta(SessionKind.PARTICIPANT, consent_status="SIGNED", consent_record_id="CF-P01-1").errors() == []
    )
    assert _meta(SessionKind.PARTICIPANT).errors()  # PENDING consent
    assert _meta(SessionKind.PARTICIPANT, consent_status="SIGNED").errors()  # no record id
    assert _meta(SessionKind.PARTICIPANT, consent_status="NOT_REQUIRED", consent_record_id="x").errors()
    d = _meta(SessionKind.PARTICIPANT, consent_status="SIGNED", consent_record_id="CF").data
    d["lighting"]["id"] = "L0"  # developer-only lighting id on a participant session
    assert validate_metadata(d)
    d = _meta(SessionKind.PARTICIPANT, consent_status="SIGNED", consent_record_id="CF").data
    d["source"]["kind"] = "REPLAY"
    assert validate_metadata(d)


def test_naming_rules():
    assert session_id_for(SessionKind.PARTICIPANT, "P07", 2) == "P07-S2"
    assert session_id_for(SessionKind.PILOT, "PILOT01", 1) == "PILOT01-S1"
    assert session_id_for(SessionKind.DEV_CAPTURE, "DEV", 1, slug="swing") == "dev-swing"
    assert session_id_for(SessionKind.SYNTHETIC, "SYNTHETIC", 1, slug="x") == "synthetic-x"
    with pytest.raises(ValueError):
        session_id_for(SessionKind.SYNTHETIC, "SYNTHETIC", 1)
    with pytest.raises(ValueError):
        participant_id_for(SessionKind.PARTICIPANT, None)
    assert participant_id_for(SessionKind.DEV_CAPTURE, "P01") == "DEV"  # dev material never gets a pseudonym


def test_segments_takes_and_has_phys_gt_rule():
    m = _meta(SessionKind.SYNTHETIC, pad_zone_id="snare")
    single = SegmentSpec("s01", SegmentType.SINGLE_HITS, "c", 2.0, zone_ids=("snare",))
    pad = SegmentSpec(
        "s02", SegmentType.PAD_MIC, "c", 2.0, zone_ids=("snare",), condition="PAD", pad_zone_id="snare"
    )
    s1 = m.open_segment(single, 100.0, take=1)
    assert m.errors() == []  # an open marker (ABORTED, no t_end) is valid: a crash leaves exactly that
    m.close_segment(s1, 102.0, None)
    assert m.errors() == []
    # re-take: earlier take must be flagged RETAKEN, the new one RECORDED
    m.mark_retaken("s01")
    s1b = m.open_segment(single, 102.0, take=2)
    m.close_segment(s1b, 104.0, None)
    assert m.errors() == [] and m.data["segments"][0]["status"] == "RETAKEN"
    m.data["segments"][0]["status"] = "RECORDED"
    assert any("superseded" in e for e in m.errors())
    m.data["segments"][0]["status"] = "RETAKEN"
    # PAD segment without audio track: has_phys_gt stays False (availability rule)
    s3 = m.open_segment(pad, 104.0, take=1)
    m.close_segment(s3, 106.0, None)
    m.refresh_has_phys_gt()
    assert m.data["has_phys_gt"] is False and m.errors() == []
    m.data["has_phys_gt"] = True
    assert m.errors()  # schema: has_phys_gt true needs an audio track ref + residual + PAD segment
    m.set_audio_track(
        {
            "path": "audio_track.wav",
            "sample_rate_hz": 48000,
            "channels": 1,
            "dtype": "pcm16",
            "n_samples": 10,
            "t_mono_first_sample": 100.0,
            "clock_fit": None,
            "device": "x",
            "sha256": None,
        },
        0.004,
    )
    assert m.data["has_phys_gt"] is True and m.errors() == []
    # overlapping marker rejected
    bad = m.open_segment(single, 105.0, take=3)
    m.mark_retaken("s01")
    m.close_segment(bad, 107.0, None)
    assert any("overlaps" in e or "not after" in e for e in m.errors())


def test_round_trip_and_schema_example(tmp_path):
    m = _meta(SessionKind.SYNTHETIC)
    path = m.write(tmp_path)
    back = SessionMetadata.read(tmp_path)
    assert back.data == m.data and path.name == "metadata.json"
    assert not contract_schema.errors("session-metadata", back.data)
    with pytest.raises(ValueError):
        SessionMetadata.from_dict({"schema_version": "9.9"})
    m.data["consent_status"] = str(ConsentStatus.SIGNED)  # invalid for SYNTHETIC
    with pytest.raises(ValueError):
        m.write(tmp_path)
