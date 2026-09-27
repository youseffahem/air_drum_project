"""Phase 18 analysis layer on the frozen harness; TEST-CAUSAL-1 on evaluated arms (TEST-P18-OFFLINE).

The inputs are small constructed sessions with known answers (SYNTHETIC); no participant data.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from spacedrums.commit import CommitSettings
from spacedrums.config import load_config
from spacedrums.contracts import TrackState, TrajectoryAux, TrajectoryPrediction
from spacedrums.eval.replay import replay
from spacedrums.eval.report import evaluate_session
from spacedrums.geometry import ZoneRegistry
from spacedrums.live_eval import offline
from spacedrums.live_eval.causality import causal_check, perturb
from spacedrums.prediction import RuleSettings

ROOT = Path(__file__).resolve().parents[2]


def _label(i, t, *, hand="RIGHT", zone="snare", speed=1.0, session="s1"):
    return {
        "session_id": session,
        "hand_id": hand,
        "label_id": f"{session}-g{i}",
        "label_class": "POSITIVE",
        "t_impact_est": t,
        "zone_id": zone,
        "excluded": False,
        "qc_status": "PENDING_REVIEW",
        "review": {"reviewed": False},
        "segment_type": "SINGLE_HITS",
        "t_start": None,
        "t_end": None,
        "source_kind": "SYNTHETIC",
        "impact_position": [0.5, 0.6],
        "intensity_proxy_gt": speed,
    }


def _strike(i, t_commit, *, pred=None, est=None, hand="RIGHT", zone="snare", session="s1", intensity=1.0):
    return {
        "strike_id": f"{session}-s{i}",
        "session_id": session,
        "hand_id": hand,
        "zone_id": zone,
        "t_commit": t_commit,
        "t_impact_pred": pred,
        "t_impact_est": est,
        "impact_position": [0.5, 0.61],
        "intensity_proxy": intensity,
    }


SEGMENTS = [
    {
        "segment_id": "u",
        "t_start": 0.0,
        "t_end": 60.0,
        "eligible": True,
        "hands": ["LEFT", "RIGHT"],
        "type": "SINGLE_HITS",
    }
]


def _session(participant, strikes, labels, session):
    ev = evaluate_session(strikes, labels, SEGMENTS, w_s=0.05, include_unreviewed_selftest=True)
    return {
        "participant": participant,
        "session_id": session,
        "evaluation": ev,
        "strikes": strikes,
        "labels": labels,
    }


def test_participant_and_pooled_metrics_regroup_the_harness_events():
    s1 = _session(
        "P1",
        [
            _strike(1, 10.00, pred=10.02, intensity=1.1),
            _strike(2, 20.00, pred=20.03, intensity=2.2),
            _strike(3, 30.0, pred=30.0),
        ],
        [_label(1, 10.02, speed=1.0), _label(2, 20.04, speed=2.0), _label(3, 40.0, speed=3.0)],
        "s1",
    )
    s2 = _session(
        "P1",
        [_strike(1, 5.00, pred=5.01, session="s2", intensity=3.9)],
        [_label(1, 5.03, session="s2", speed=4.0)],
        "s2",
    )
    per = offline.participant_metrics([s1, s2])
    m = per["P1"]
    assert (m["sessions"], m["matched"], m["fp"], m["fn"]) == (2, 3, 1, 1)
    assert m["active_time_s"] == pytest.approx(120.0)
    assert m["fp_per_min"] == pytest.approx(0.5)
    assert m["lead_median_s"] == pytest.approx(0.03)
    assert m["te_pred_mae_s"] == pytest.approx((0.0 + 0.01 + 0.02) / 3)
    assert m["zone_accuracy"] == 1.0 and m["intensity_spearman_rho"] is not None
    pooled = offline.pooled_metrics([s1, s2])
    assert pooled["matched"] == 3 and pooled["fn_rate"] == pytest.approx(0.25)
    summary = offline.event_summary([s1, s2])
    assert summary["zone_confusion"] == [{"actual": "snare", "predicted": "snare", "n": 3}]
    assert summary["fp_by_segment_type"] == {"SINGLE_HITS": 1}


def test_strata_are_label_properties_and_speed_has_no_false_positives():
    labels = [
        _label(i, 10.0 * (i + 1), speed=float(i + 1), hand="LEFT" if i % 2 else "RIGHT") for i in range(6)
    ]
    strikes = [
        _strike(i, 10.0 * (i + 1) - 0.01, pred=10.0 * (i + 1), hand="LEFT" if i % 2 else "RIGHT")
        for i in range(6)
    ]
    strikes.append(_strike(9, 5.0, pred=5.0))
    sessions = [_session("P1", strikes, labels, "s1")]
    edges = offline.speed_tercile_edges(labels)
    st = offline.strata(
        sessions, speed_edges=edges, session_levels={"s1": {"lighting_id": "L2", "distance_mark": None}}
    )
    assert set(st["by_hand"]) == {"LEFT", "RIGHT"}
    assert sum(v["matched"] for v in st["by_speed_tercile"].values()) == 6
    assert all(v["fp_per_min"] is None for v in st["by_speed_tercile"].values())
    assert st["by_segment_type"]["SINGLE_HITS"]["fp"] == 1
    assert "fewer than two levels" in st["by_lighting"]["note"]


def test_sensitivity_s1_matches_an_early_accurate_commit_that_adr0023_counts_twice():
    labels = [_label(1, 10.00)]
    early = [_strike(1, 9.85, pred=10.005)]  # commit 150 ms before impact, predicted impact 5 ms late
    primary = evaluate_session(early, labels, SEGMENTS, w_s=0.05, include_unreviewed_selftest=True)
    assert (primary["pooled"]["matched"], primary["pooled"]["fp"], primary["pooled"]["fn"]) == (0, 1, 1)
    s1 = offline.reference_time_evaluation(
        early, labels, SEGMENTS, w_s=0.05, include_unreviewed_selftest=True
    )
    match = [e for e in s1["events"] if e["kind"] == "MATCH"]
    assert len(match) == 1 and match[0]["lead_s"] == pytest.approx(0.15) and match[0]["t_commit"] == 9.85
    reactive = offline.reference_time_rows([_strike(2, 10.04, est=10.001)])
    assert reactive[0]["t_commit"] == 10.001 and reactive[0]["t_commit_original"] == 10.04
    with pytest.raises(ValueError):
        offline.reference_time_rows([_strike(3, 1.0)])


def _track(i, xy, *, status="VALID", hand="RIGHT", t0=10.0, dt=1 / 30, reset=None):
    valid = status == "VALID"
    return TrackState(
        frame_id=i,
        t_capture=t0 + i * dt,
        hand_id=hand,
        tracker_id="t",
        status=status,
        tip_filtered=xy if valid else None,
        tip_velocity=(0.0, 0.6) if valid else None,
        tip_acceleration=(0.0, 0.0) if valid else None,
        confidence=0.9 if valid else 0.1,
        frames_since_valid=0 if valid else 1,
        last_valid_t=t0 + i * dt if valid else None,
        tip_method="GEOM",
        axis_angle=None,
        axis_angular_velocity=None,
        history_ref=None,
        reset_reason=reset,
    )


def _prediction(i, points, *, dt=1 / 30, t0=10.0):
    return TrajectoryPrediction(
        frame_id=i,
        t_capture=t0 + i * dt,
        hand_id="RIGHT",
        anticipator_id="test",
        model_hash=None,
        K=len(points),
        dt_step=dt,
        t_offsets_s=None,
        positions=tuple(points),
        velocities=None,
        uncertainty=None,
        uncertainty_kind=None,
        aux=TrajectoryAux(),
        t_inference_done=t0 + i * dt,
    )


def test_trajectory_error_uses_the_future_causal_track_inside_valid_spans_only():
    tracks = [_track(i, (0.5, 0.01 * i)) for i in range(6)] + [_track(6, None, status="INVALID")]
    exact = _prediction(1, [(0.5, 0.02), (0.5, 0.03)])
    off = _prediction(3, [(0.5, 0.05), (0.5, 0.07), (0.5, 0.08), (0.5, 0.09)])  # steps 3-4 cross the loss
    r = offline.trajectory_errors([exact, off], tracks)
    assert r["valid_sequences"] == 2 and r["valid_points"] == 4
    assert r["ade"] == pytest.approx((0.0 + 0.0 + 0.01 + 0.02) / 4) and r["fde"] == pytest.approx(
        (0.0 + 0.02) / 2
    )


@pytest.fixture(scope="module")
def harness_setup():
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    registry = ZoneRegistry.from_config(cfg["zones"])
    commit = replace(CommitSettings.from_config(cfg), n_confirm_frames=0, p_commit=0, tti_commit_s=0.05)
    rule = replace(
        RuleSettings.from_config(cfg), motion_model="CV", v_min_predict=0, speed_prob_lo=0, speed_prob_hi=0.1
    )
    # 0.401: a sample exactly on the impact surface (y = 0.58) suppresses the whole entry episode in the
    # frozen GeometryEngine.observe (boundary counts as inside, first_impact needs strictly inside).
    swing = [_track(i, (0.4, 0.401 + 0.02 * i)) for i in range(30)]
    donor = [_track(i, (0.6, 0.301 + 0.015 * i)) for i in range(30)]
    return registry, commit, rule, swing, donor


@pytest.mark.parametrize("arm", ["A", "B"])
def test_causal_check_passes_the_frozen_arms_and_its_perturbations_are_effective(harness_setup, arm):
    registry, commit, rule, swing, donor = harness_setup

    def run(tracks):
        return replay(
            tracks,
            arm=arm,
            registry=registry,
            commit_settings=commit,
            v_min=0.15,
            session_id="c",
            rule_settings=rule if arm == "B" else None,
        )

    report = causal_check(run, swing, donor=donor, cuts=[3, 6, 9, 12])
    assert report["passed"], report["failures"]
    assert report["records"]["committed"] >= 1
    assert report["effective_perturbations"]["GARBAGE"] > 0


def test_causal_check_catches_an_arm_that_reads_the_future(harness_setup):
    registry, commit, rule, swing, donor = harness_setup

    def leaky(tracks):
        v_min = 10.0 if len(tracks) > 20 else 0.15  # reads how long the sequence is: future information
        return replay(tracks, arm="A", registry=registry, commit_settings=commit, v_min=v_min, session_id="c")

    report = causal_check(leaky, swing, donor=donor, cuts=[12, 15], kinds=("REMOVED",))
    assert not report["passed"] and report["n_failures"] > 0


def test_perturbations_keep_the_prefix_and_retime_the_donor():
    tracks = [_track(i, (0.5, 0.1)) for i in range(10)]
    donor = [_track(i, (0.9, 0.9), t0=50.0) for i in range(10)]
    shifted = perturb(tracks, 4, "SHIFTED", donor=donor)
    assert shifted[:5] == tracks[:5] and [t.frame_id for t in shifted] == list(range(10))
    assert shifted[5].t_capture == tracks[5].t_capture and shifted[5].tip_filtered == (0.9, 0.9)
    assert len(perturb(tracks, 4, "REMOVED")) == 5
    garbage = perturb(tracks, 4, "GARBAGE", seed=1)
    assert garbage[:5] == tracks[:5] and garbage[6].tip_filtered != tracks[6].tip_filtered
