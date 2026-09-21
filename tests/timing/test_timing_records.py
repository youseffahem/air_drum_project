"""TEST-TIMING-2: TimingRecord class, collector, JSONL streams and the README section 5.3 decomposition."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from spacedrums.contracts import (
    AudioEvent,
    CommittedStrike,
    FrameSample,
    ImageRef,
    StrikeCandidate,
    TimingRecord,
)
from spacedrums.contracts import schema as contract_schema
from spacedrums.timing.decomposition import (
    L_SYS_EST_TERMS,
    decompose,
    decomposition_table,
    stats,
    strike_components,
)
from spacedrums.timing.logger import RecordStreamWriter, read_record_stream, stream_header
from spacedrums.timing.records import TimingCollector

ROOT = Path(__file__).resolve().parents[2]
HASH = "sha256:" + "0" * 64


def _sample(frame_id: int = 3, t: float = 10.0) -> FrameSample:
    return FrameSample(
        frame_id=frame_id,
        t_capture=t,
        t_frame_available=t + 0.005,
        timestamp_source="GRAB_RETURN",
        frame_size_px=(640, 480),
        roi_px=(40, 20, 560, 440),
        image_ref=ImageRef.memory(np.zeros((2, 2, 3), np.uint8)),
        camera_profile_id="p",
        dropped_since_last=0,
    )


def _candidate(reactive: bool) -> StrikeCandidate:
    return StrikeCandidate(
        candidate_id="c1",
        frame_id=3,
        t_capture=10.0,
        hand_id="RIGHT",
        zone_id="snare",
        source="REACTIVE" if reactive else "RULE",
        derivation="GEOMETRY",
        anticipator_id=None if reactive else "rule",
        t_impact_pred=None if reactive else 10.08,
        t_impact_est=9.99 if reactive else None,
        tti=None if reactive else 0.08,
        impact_position=(0.5, 0.6),
        crossing_velocity=(0.0, 1.0),
        strike_probability=None if reactive else 0.9,
        intensity_proxy=1.0,
        t_candidate=10.02,
    )


def _commit(reactive: bool, shadow: bool = False) -> CommittedStrike:
    return CommittedStrike(
        strike_id="s1",
        candidate_id="c1",
        frame_id=3,
        t_capture=10.0,
        hand_id="RIGHT",
        zone_id="snare",
        source="REACTIVE" if reactive else "RULE",
        derivation="GEOMETRY",
        arm="A" if reactive else "B",
        shadow=shadow,
        t_commit=10.03,
        t_impact_target=10.03 if reactive else 10.08,
        intensity_proxy=1.0,
        gain=0.5,
        refractory_until=10.13,
        episode_id="e1",
        commit_policy_id="cp",
    )


def _audio() -> AudioEvent:
    return AudioEvent(
        strike_id="s1",
        sample_id="snare",
        t_audio_scheduled=10.031,
        t_target_play=10.03,
        t_audio_out_est=10.045,
        audio_late_s=0.001,
        gain=0.5,
        audio_profile_id="ap",
    )


def test_timing_record_class_matches_schema_and_example():
    example = json.loads(
        (ROOT / "schemas" / "examples" / "timing-record.valid.example.json").read_text(encoding="utf-8")
    )
    rec = TimingRecord.from_dict(example)
    assert rec.to_dict() == example and contract_schema.is_valid("timing-record", rec.to_dict())
    frame = dataclasses.replace(rec, kind="FRAME", strike_id=None, hand_id=None, t_commit=None)
    assert contract_schema.is_valid("timing-record", frame.to_dict())
    with pytest.raises(ValueError):
        dataclasses.replace(rec, kind="FRAME")  # FRAME with strike_id
    with pytest.raises(ValueError):
        dataclasses.replace(rec, kind="STRIKE", t_commit=None)
    with pytest.raises(ValueError):
        dataclasses.replace(rec, kind="NOPE")


def test_collector_frame_and_strike_records_and_audio_out_est_rule():
    col = TimingCollector(hardware_id="HW-01", config_hash=HASH, audio_out_measured=False)
    f = col.frame(_sample(), t_tracking_done=10.02, t_inference_done=10.021, arm="B")
    assert (
        f.kind == "FRAME"
        and f.strike_id is None
        and f.arm.value == "B"
        and contract_schema.is_valid("timing-record", f.to_dict())
    )
    s = col.strike(
        _commit(True),
        _candidate(True),
        _sample(),
        t_tracking_done=10.02,
        t_inference_done=None,
        audio=_audio(),
    )
    assert s.kind == "STRIKE" and s.t_commit == 10.03 and s.t_audio_scheduled == 10.031
    assert s.t_audio_out_est is None  # no MEASURED output latency -> withheld
    assert s.t_audio_out is None and s.t_acoustic_onset is None and s.t_impact_phys is None
    assert s.t_impact_est == 9.99 and s.t_impact_pred is None
    col_m = TimingCollector(hardware_id="HW-01", config_hash=HASH, audio_out_measured=True)
    s2 = col_m.strike(
        _commit(True),
        _candidate(True),
        _sample(),
        t_tracking_done=10.02,
        t_inference_done=None,
        audio=_audio(),
    )
    assert s2.t_audio_out_est == 10.045
    with pytest.raises(ValueError):
        col.strike(
            _commit(False, shadow=True),
            _candidate(False),
            _sample(),
            t_tracking_done=10.02,
            t_inference_done=10.021,
            audio=_audio(),
        )
    sh = col.strike(
        _commit(False, shadow=True),
        _candidate(False),
        _sample(),
        t_tracking_done=10.02,
        t_inference_done=10.021,
        audio=None,
    )
    assert sh.t_audio_scheduled is None and sh.t_impact_pred == 10.08 and sh.t_impact_est is None
    assert len(col.records) == 3 and col.n_frame == 1 and col.n_strike == 2


def test_decomposition_terms_and_labels():
    col = TimingCollector(hardware_id="HW-01", config_hash=HASH, audio_out_measured=True)
    recs = [
        col.frame(_sample(), t_tracking_done=10.02, t_inference_done=10.021, arm="B"),
        col.strike(
            _commit(True),
            _candidate(True),
            _sample(),
            t_tracking_done=10.02,
            t_inference_done=None,
            audio=_audio(),
        ),
        col.strike(
            _commit(False, True),
            _candidate(False),
            _sample(),
            t_tracking_done=10.02,
            t_inference_done=10.021,
            audio=None,
        ),
    ]
    comp_a = strike_components(recs[1])
    assert comp_a["capture"] == pytest.approx(0.005) and comp_a["tracking"] == pytest.approx(0.015)
    assert comp_a["commit"] == pytest.approx(0.01) and comp_a["frame_quantization"] == pytest.approx(0.01)
    assert comp_a["audio_dispatch"] == pytest.approx(0.001) and comp_a["audio_out_est"] == pytest.approx(
        0.014
    )
    assert comp_a["L_sys_est"] == pytest.approx(10.045 - 9.99)
    assert comp_a["L_sys_est"] == pytest.approx(sum(comp_a[t] for t in L_SYS_EST_TERMS))
    assert comp_a["L_pred"] == pytest.approx(9.99 - 10.03)  # negative for the reactive arm, by construction
    comp_b = strike_components(recs[2])
    assert (
        "L_pred" not in comp_b
        and "frame_quantization" not in comp_b
        and comp_b["commit"] == pytest.approx(0.009)
    )
    dec = decompose(recs, live=True)
    assert dec["audio_out_est_available"] and dec["strike_by_arm"]["A"]["L_sys_est"]["n"] == 1
    table = decomposition_table(dec)
    assert "software-estimated" in table and "L_sys_est" in table and "term" in table
    dec_replay = decompose(recs, live=False)
    assert "tracking" not in dec_replay["frame"] and "commit" not in dec_replay["strike_by_arm"]["A"]
    assert "N/A in replay" in decomposition_table(dec_replay)
    st = stats([3.0, 1.0, 2.0, 4.0, 5.0])
    assert st.n == 5 and st.median_s == 3.0 and st.min_s == 1.0 and st.max_s == 5.0 and st.iqr_s == 2.0
    assert stats([]).n == 0 and stats([]).median_s is None


def test_record_stream_header_and_round_trip(tmp_path):
    header = stream_header(
        record_type="TimingRecord",
        record_schema_version="1.0",
        session_id="dev-x",
        config_hash=HASH,
        git_sha="a" * 40,
        clock_id="perf_counter",
        producer="LIVE",
        derived=True,
    )
    assert contract_schema.is_valid("record-stream-header", header)
    col = TimingCollector(hardware_id="HW-01", config_hash=HASH)
    rec = col.frame(_sample(), t_tracking_done=10.02)
    path = tmp_path / "timing.jsonl"
    with RecordStreamWriter(path, header) as w:
        w.write(rec)
        w.write(rec.to_dict())
    assert w.count == 2
    h, rows = read_record_stream(path)
    assert h == header and rows == [rec.to_dict(), rec.to_dict()]
    assert path.read_bytes().count(b"\r") == 0  # LF only
    empty = tmp_path / "empty.jsonl"
    RecordStreamWriter(empty, header).close()
    assert read_record_stream(empty) == (header, [])
    with pytest.raises(ValueError):
        stream_header(
            record_type="TimingRecord",
            record_schema_version="1.0",
            session_id="s",
            config_hash=HASH,
            git_sha="a" * 40,
            clock_id="perf_counter",
            producer="OFFLINE",
            derived=True,
        )
