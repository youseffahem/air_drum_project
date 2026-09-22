from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from spacedrums.commit import CommitSettings
from spacedrums.config import load_config
from spacedrums.contracts import HandId, ResetReason, TrackState, TrackStatus
from spacedrums.eval.matching import match_events
from spacedrums.eval.metrics import active_seconds, event_metrics
from spacedrums.eval.replay import DelayPolicy, replay
from spacedrums.eval.report import write_result
from spacedrums.eval.selection import select_point
from spacedrums.features.batch import load_causal_tracks
from spacedrums.geometry import ZoneRegistry
from spacedrums.prediction import RuleSettings
from spacedrums.timing.logger import read_record_stream

ROOT = Path(__file__).resolve().parents[2]


def _track(i, y, *, t0=10.0, dt=0.02, x=0.4, speed=1.0):
    return TrackState(
        frame_id=i,
        t_capture=t0 + i * dt,
        hand_id=HandId.LEFT,
        status=TrackStatus.VALID,
        tracker_id="test",
        tip_method=None,
        tip_filtered=(x, y),
        tip_velocity=(0.0, speed),
        tip_acceleration=(0.0, 0.0),
        axis_angle=None,
        axis_angular_velocity=None,
        confidence=1.0,
        frames_since_valid=0,
        last_valid_t=t0 + i * dt,
        history_ref=None,
        reset_reason=ResetReason.SESSION_START if i == 0 else None,
    )


def _config():
    c = load_config(ROOT / "configs/prototype.candidate.yaml")
    return c, ZoneRegistry.from_config(c["zones"])


def test_matching_ties_zone_and_boundary():
    s = [dict(session_id="a", hand_id="LEFT", t_commit=t, zone_id="wrong") for t in (1.0, 1.1, 2)]
    g = [dict(session_id="a", hand_id="LEFT", t_impact_est=t, zone_id="snare") for t in (1.05, 2.05)]
    m = match_events(s, g, w_s=0.05)
    assert len(m.pairs) == 2
    assert m.pairs[0][0] is s[0]  # deterministic tie
    assert m.false_positives == (s[1],)
    assert event_metrics(m, active_time_s=60)["zone_accuracy"] == 0
    assert len(match_events(s, g, w_s=0.049).pairs) == 0


def test_active_time_union_and_empty_denominators():
    assert active_seconds([(0, 5), (3, 10)], [(1, 3), (2, 4), (8, 12)]) == 5
    m = match_events([], [], w_s=0.05)
    report = event_metrics(m, active_time_s=0)
    assert report["fp_per_min"] is None and report["fn_rate"] is None


def test_event_parquet_preserves_mixed_rows(tmp_path):
    import pyarrow.parquet as pq

    rows = [
        {"kind": "MATCH", "label_id": "g", "lead_s": 0.02},
        {"kind": "FP", "strike_id": "s", "segment_type": "NEG_FAKE_SWING"},
    ]
    write_result(tmp_path, {"pooled": {"matched": 1}, "events": rows})
    table = pq.read_table(tmp_path / "events.parquet").to_pylist()
    assert table[0]["label_id"] == "g" and table[1]["segment_type"] == "NEG_FAKE_SWING"


def test_operating_point_rejects_infeasible_lead():
    points = [
        {"settings": {"p": 0.3}, "median_lead_s": 0.04, "fp_per_min": 2.0, "fn_rate": 0.1},
        {"settings": {"p": 0.5}, "median_lead_s": 0.02, "fp_per_min": 0.5, "fn_rate": 0.2},
    ]
    chosen = select_point(points, fp_budget=1, fn_ceiling=0.25)
    assert chosen["feasible"] and chosen["point"]["settings"] == {"p": 0.5}
    assert not select_point(points, fp_budget=0.1, fn_ceiling=0.1)["feasible"]


def test_replay_analytic_reactive_delay_and_future_causality():
    c, registry = _config()
    settings = replace(CommitSettings.from_config(c), n_confirm_frames=0, p_commit=0)
    tracks = [_track(i, 0.505 + i * 0.02) for i in range(9)]
    ideal = replay(
        tracks, arm="A", registry=registry, commit_settings=settings, v_min=0.15, session_id="analytic"
    )
    delayed = replay(
        tracks,
        arm="A",
        registry=registry,
        commit_settings=settings,
        v_min=0.15,
        session_id="analytic",
        delay=DelayPolicy("fixed", 0.012),
    )
    assert len(ideal.committed) == len(delayed.committed) == 1
    assert delayed.committed[0].t_commit - ideal.committed[0].t_commit == pytest.approx(0.012)
    assert ideal.committed[0].frame_id == 4  # top of snare is y=0.58
    cut = 4
    changed = tracks[:cut] + [_track(i, 0.51, x=0.9) for i in range(cut, len(tracks))]
    a = replay(
        tracks[:cut], arm="A", registry=registry, commit_settings=settings, v_min=0.15, session_id="analytic"
    )
    b = replay(
        changed[:cut], arm="A", registry=registry, commit_settings=settings, v_min=0.15, session_id="analytic"
    )
    assert [x.to_dict() for x in a.committed] == [x.to_dict() for x in b.committed]
    rule = replace(
        RuleSettings.from_config(c), motion_model="CV", v_min_predict=0, speed_prob_lo=0, speed_prob_hi=0.1
    )
    rule_settings = replace(settings, tti_commit_s=0.05)
    full_b = replay(
        tracks,
        arm="B",
        registry=registry,
        commit_settings=rule_settings,
        v_min=0.15,
        session_id="analytic",
        rule_settings=rule,
    )
    assert len(full_b.committed) == 1
    assert full_b.committed[0].frame_id == 2
    assert full_b.committed[0].t_impact_target == pytest.approx(10.075, abs=1e-9)
    assert 10.075 - full_b.committed[0].t_commit == pytest.approx(0.035)
    stopped = [_track(i, min(0.505 + i * 0.02, 0.565)) for i in range(9)]
    no_impact = replay(
        stopped, arm="A", registry=registry, commit_settings=settings, v_min=0.15, session_id="stop"
    )
    assert not no_impact.committed
    for n, prefix in enumerate((tracks[:cut], changed[:cut])):
        out = replay(
            prefix,
            arm="B",
            registry=registry,
            commit_settings=settings,
            v_min=0.15,
            session_id="analytic",
            rule_settings=rule,
        )
        if n == 0:
            reference = out
        else:
            assert [x.to_dict() for x in out.committed] == [x.to_dict() for x in reference.committed]


def test_developer_session_reproduces_live_commit_stamps():
    source = ROOT / "data/dev-sessions/dev-p05-swing-L2-exp-5"
    if not (source / "records/TrackState.jsonl").exists():
        pytest.skip("git-ignored Phase 05 developer session is unavailable")
    c = load_config(source / "config.snapshot.yaml")
    registry = ZoneRegistry.from_config(c["zones"])
    tracks = load_causal_tracks(source / "records/TrackState.jsonl")
    frames = [json.loads(line) for line in (source / "frames.jsonl").read_text().splitlines()]
    delays = {f["frame_id"]: f["t_frame_available"] - f["t_capture"] for f in frames}
    drops = {f["frame_id"]: f["dropped_since_last"] for f in frames}
    result = replay(
        tracks,
        arm="A",
        registry=registry,
        commit_settings=CommitSettings.from_config(c),
        v_min=c["geometry"]["v_min"],
        session_id="dev-p05-swing-L2-exp-5",
        delay=DelayPolicy("per_frame", per_frame_s=delays),
        dropped_by_frame=drops,
    )
    _, recorded = read_record_stream(source / "records/CommittedStrike.jsonl")
    expected = [r for r in recorded if r["arm"] == "A"]

    def projection(s):
        return (s["frame_id"], s["hand_id"], s["zone_id"], s["t_commit"])

    assert [projection(s.to_dict()) for s in result.committed] == [projection(s) for s in expected]
