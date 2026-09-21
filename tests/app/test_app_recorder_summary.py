"""TEST-APP-9/10: record mode persists every stream; a replay reproduces the committed-strike list;
the session summary machinery (Tasks 05.4, 05.5, 05.9, 05.10) runs on the recording. SYNTHETIC input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app_helpers import Ticker, all_commits

from spacedrums.app import SessionRecorder
from spacedrums.app.session_summary import (
    commits_during_non_valid,
    load_session,
    summarise_session,
)
from spacedrums.app.synthetic import scenario
from spacedrums.capture import ReplayFrameSource
from spacedrums.contracts import HandId, HandObservation, StickObservation
from spacedrums.contracts import schema as contract_schema
from spacedrums.timing.logger import read_record_stream

FAST = 0.12
SCHEMA_OF = {
    "HandObservation": "hand-observation",
    "StickObservation": "stick-observation",
    "TrackState": "track-state",
    "TrajectoryPrediction": "trajectory-prediction",
    "StrikeCandidate": "strike-candidate",
    "CommittedStrike": "committed-strike",
    "AudioEvent": "audio-event",
}


def _record(tmp_path: Path, cfg, make_pipeline, *, name="alternating_two_zones", active="A", shadow=("B",)):
    seq = scenario(name, registry=None or _registry(cfg), t_down=FAST, image=True, noise=0.002, seed=2)
    pipe = make_pipeline(active=active, shadow=shadow, clock=Ticker())
    rec = SessionRecorder(
        tmp_path,
        session_id="dev-synthetic",
        config=cfg,
        git_sha="a" * 40,
        producer="REPLAY",
        store_crop="FULL",
        extra_meta={"synthetic_truth": [t.to_dict() for t in seq.truth]},
    )
    results = []
    for sample, obs in seq:
        r = pipe.step(sample, obs, t_now=sample.t_frame_available)
        rec.write_frame(sample, sample.image_ref.array, r, obs)
        results.append(r)
    session_dir = rec.close({"frames": len(seq)})
    return seq, results, session_dir


def _registry(cfg):
    from spacedrums.geometry import ZoneRegistry

    return ZoneRegistry.from_config(cfg["zones"])


def test_record_mode_writes_every_stream_and_validates(tmp_path, cfg, make_pipeline):
    seq, results, d = _record(tmp_path, cfg, make_pipeline)
    assert (d / "config.snapshot.yaml").exists() and (d / "session.json").exists()
    assert len(list((d / "frames").glob("*.png"))) == len(seq)
    meta = json.loads((d / "session.json").read_text(encoding="utf-8"))
    assert (
        meta["frames"] == len(seq) and meta["config_hash"] == cfg.config_hash and meta["producer"] == "REPLAY"
    )
    for name, stem in SCHEMA_OF.items():
        header, rows = read_record_stream(d / "records" / f"{name}.jsonl")
        assert contract_schema.is_valid("record-stream-header", header) and header["record_type"] == name
        assert header["derived"] is True and header["units"]["time"] == "s"
        assert all(contract_schema.is_valid(stem, r) for r in rows), name
    th, trows = read_record_stream(d / "timing.jsonl")
    assert th["record_type"] == "TimingRecord" and all(
        contract_schema.is_valid("timing-record", r) for r in trows
    )
    assert sum(1 for r in trows if r["kind"] == "FRAME") == len(seq)
    assert sum(1 for r in trows if r["kind"] == "STRIKE") == len(all_commits(results))
    assert (d / "frames.jsonl").read_bytes().count(b"\r") == 0
    with pytest.raises(FileExistsError):
        SessionRecorder(tmp_path, session_id="dev-synthetic", config=cfg, git_sha="a" * 40, producer="REPLAY")


def test_replay_of_the_recording_reproduces_the_committed_strike_list(tmp_path, cfg, make_pipeline):
    seq, results, d = _record(tmp_path, cfg, make_pipeline)
    src = ReplayFrameSource(d)
    assert [s.t_capture for s in src] == [s.t_capture for s, _ in seq]
    assert [s.dropped_since_last for s in src] == [s.dropped_since_last for s, _ in seq]
    # replay the recorded observation streams through a fresh pipeline (the perception stage of a real
    # replay would re-derive them from the PNGs; on blank synthetic frames it has nothing to detect)
    hands = [
        HandObservation.from_dict(r) for r in read_record_stream(d / "records" / "HandObservation.jsonl")[1]
    ]
    sticks = [
        StickObservation.from_dict(r) for r in read_record_stream(d / "records" / "StickObservation.jsonl")[1]
    ]
    by_frame: dict[int, dict] = {}
    for h, s in zip(hands, sticks, strict=True):
        assert h.frame_id == s.frame_id and h.hand_id is s.hand_id
        by_frame.setdefault(h.frame_id, {})[h.hand_id] = (h, s)
    pipe2 = make_pipeline(active="A", shadow=("B",), clock=Ticker())
    replayed = [
        pipe2.step(sample, by_frame[sample.frame_id], t_now=sample.t_frame_available) for sample in src
    ]
    a = [c.to_dict() for c in all_commits(results)]
    b = [c.to_dict() for c in all_commits(replayed)]
    assert a and a == b  # identical committed-strike list (ids, times, zones, arms, shadow flags)
    recorded = read_record_stream(d / "records" / "CommittedStrike.jsonl")[1]
    assert recorded == a


def test_session_summary_and_safety_count(tmp_path, cfg, make_pipeline):
    seq, results, d = _record(tmp_path, cfg, make_pipeline, active="B", shadow=("A",))
    truth = [t.to_dict() for t in seq.truth]
    summary = summarise_session(d, truth=truth)
    counts = summary["counts"]
    assert counts["commits"]["A"] == counts["commits"]["B"] == len(truth)
    assert (
        counts["commits_sounding"] == counts["commits"]["B"]
        and counts["commits_shadow"] == counts["commits"]["A"]
    )
    assert counts["audio_events"] == counts["commits_sounding"] and counts["predictions"] > 0
    assert summary["commits_during_non_valid"] == 0
    assert summary["timing_decomposition"]["live"] is False and "n/a" in summary["timing_table_markdown"]
    cmp = summary["arm_comparison"]
    assert cmp["n_matched"] == len(truth) and cmp["zone_agreement"] == 1.0 and "sanity check" in cmp["label"]
    ev = summary["synthetic_truth_evaluation"]
    assert ev["arms"]["A"]["false_negatives"] == 0 and ev["arms"]["B"]["false_negatives"] == 0
    assert "SYNTHETIC" in ev["label"]
    assert json.dumps(summary, allow_nan=False)
    s = load_session(d)
    assert commits_during_non_valid(s["CommittedStrike"], s["TrackState"]) == 0
    assert counts["track_status_frames"]["RIGHT"]["VALID"] > 0
    assert set(HandId(k) for k in counts["track_status_frames"]) == {HandId.LEFT, HandId.RIGHT}
