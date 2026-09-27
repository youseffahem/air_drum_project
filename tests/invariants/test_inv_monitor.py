"""TEST-INV-1 / TEST-INV-2: the Phase 17 safety-invariant monitor (I1-I6).

TEST-INV-1 (negative controls): each invariant detects a deliberately constructed violation, so a
measured zero over the replay set is not vacuous. TEST-INV-2: nominal SYNTHETIC runs of every
scenario and both baseline arms produce zero violations with non-zero check counts; ``raise`` mode
raises, ``log`` mode logs and continues. Every input is SYNTHETIC.
"""

from __future__ import annotations

import dataclasses
import logging

import pytest
from inv_helpers import Ticker, make_pipeline, strike

from spacedrums.app.invariants import InvariantMonitor
from spacedrums.app.synthetic import SCENARIOS, scenario
from spacedrums.commit import CommitAuditor, CommitSettings, InvariantViolation
from spacedrums.contracts import Arm, HandId, TrackStatus


def _run(pipe, frames, monitor):
    for sample, obs in frames:
        monitor.observe(pipe.step(sample, obs, t_now=sample.t_frame_available), pipe)
    return monitor.finish()


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("active,shadow", [("A", ("B",)), ("B", ("A",))])
def test_nominal_scenarios_have_zero_violations(name, active, shadow, cfg, registry):
    pipe = make_pipeline(cfg, registry, active=active, shadow=shadow)
    summary = _run(
        pipe, scenario(name, registry, t_down=0.12, noise=0.002, seed=4), InvariantMonitor.for_pipeline(pipe)
    )
    assert summary["violations_total"] == 0
    assert summary["checks"]["I2"] > 0 and summary["checks"]["I6"] >= 0


def test_checks_are_not_vacuous_over_strokes(cfg, registry):
    pipe = make_pipeline(cfg, registry, active="B", shadow=("A",))
    summary = _run(pipe, scenario("repeated", registry, t_down=0.12), InvariantMonitor.for_pipeline(pipe))
    assert summary["violations_total"] == 0
    for inv in ("I1", "I2", "I3", "I4", "I5", "I6"):
        assert summary["checks"].get(inv, 0) > 0, inv


# -- negative controls: each invariant fires on a constructed violation (auditor level) ----------


def _tracks(frame_id, t, status, tip):
    from spacedrums.contracts import TrackState

    def one(hand):
        live = status in (TrackStatus.VALID, TrackStatus.DEGRADED)
        return TrackState(
            frame_id=frame_id,
            t_capture=t,
            hand_id=hand,
            status=status,
            tracker_id="t",
            tip_method="GEOM",
            tip_filtered=tip if live else None,
            tip_velocity=(0.0, 1.0) if live else None,
            tip_acceleration=None,
            axis_angle=None,
            axis_angular_velocity=None,
            confidence=0.9 if live else 0.0,
            frames_since_valid=0 if status is TrackStatus.VALID else 1,
            last_valid_t=t,
            history_ref=None,
            reset_reason=None,
        )

    return {HandId.LEFT: one(HandId.LEFT), HandId.RIGHT: one(HandId.RIGHT)}


def test_i1_detects_commit_while_invalid(registry):
    auditor = CommitAuditor(CommitSettings(), registry)
    tracks = _tracks(3, 1.0, TrackStatus.INVALID, None)
    found = auditor.audit_frame(frame_id=3, t_capture=1.0, t_now=1.0, tracks=tracks, commits=[strike(3, 1.0)])
    assert [v.invariant for v in found] == ["I1", "I4"]  # also no observed entry behind a reactive commit


def test_i1_allows_degraded_only_when_enabled(registry, snare_inside):
    tracks = _tracks(3, 1.0, TrackStatus.DEGRADED, snare_inside)
    off = CommitAuditor(CommitSettings(), registry)
    assert {
        v.invariant
        for v in off.audit_frame(
            frame_id=3, t_capture=1.0, t_now=1.0, tracks=tracks, commits=[strike(3, 1.0)]
        )
    } == {"I1"}
    on = CommitAuditor(CommitSettings(allow_degraded_commits=True), registry)
    assert on.audit_frame(frame_id=3, t_capture=1.0, t_now=1.0, tracks=tracks, commits=[strike(3, 1.0)]) == []


def test_i3_detects_refractory_break_per_arm_and_audible(registry, snare_inside, snare_outside):
    auditor = CommitAuditor(CommitSettings(refractory_zone_s=0.1), registry)
    out = auditor.audit_frame(
        frame_id=1,
        t_capture=1.0,
        t_now=1.0,
        tracks=_tracks(1, 1.0, TrackStatus.VALID, snare_outside),
        commits=[],
    )
    auditor.audit_frame(
        frame_id=2,
        t_capture=1.03,
        t_now=1.03,
        tracks=_tracks(2, 1.03, TrackStatus.VALID, snare_inside),
        commits=[strike(2, 1.03)],
    )
    auditor.audit_frame(
        frame_id=3,
        t_capture=1.06,
        t_now=1.06,
        tracks=_tracks(3, 1.06, TrackStatus.VALID, snare_outside),
        commits=[],
    )
    out = auditor.audit_frame(
        frame_id=4,
        t_capture=1.09,
        t_now=1.09,
        tracks=_tracks(4, 1.09, TrackStatus.VALID, snare_inside),
        commits=[strike(4, 1.09, arm=Arm.B, source="RULE")],
    )
    # a different arm: its own stream is fine, the audible stream breaks r_zone
    assert [v.invariant for v in out] == ["I3"] and out[0].detail["stream"] == "AUDIBLE"


def test_i4_detects_second_commit_in_one_episode(registry, snare_inside, snare_outside):
    auditor = CommitAuditor(CommitSettings(refractory_zone_s=0.0, refractory_hand_s=0.0), registry)
    auditor.audit_frame(
        frame_id=1,
        t_capture=1.0,
        t_now=1.0,
        tracks=_tracks(1, 1.0, TrackStatus.VALID, snare_outside),
        commits=[],
    )
    first = auditor.audit_frame(
        frame_id=2,
        t_capture=1.03,
        t_now=1.03,
        tracks=_tracks(2, 1.03, TrackStatus.VALID, snare_inside),
        commits=[strike(2, 1.03)],
    )
    second = auditor.audit_frame(
        frame_id=3,
        t_capture=1.06,
        t_now=1.06,
        tracks=_tracks(3, 1.06, TrackStatus.VALID, snare_inside),
        commits=[strike(3, 1.06)],
    )
    assert first == [] and {v.invariant for v in second} == {"I4"}


def test_i4_anticipatory_commit_waits_for_its_entry(registry, snare_inside, snare_outside):
    auditor = CommitAuditor(CommitSettings(refractory_zone_s=0.0, refractory_hand_s=0.0), registry)
    auditor.audit_frame(
        frame_id=1,
        t_capture=1.0,
        t_now=1.0,
        tracks=_tracks(1, 1.0, TrackStatus.VALID, snare_outside),
        commits=[strike(1, 1.0, arm=Arm.B, source="RULE", target=1.04)],
    )
    found = auditor.audit_frame(
        frame_id=2,
        t_capture=1.033,
        t_now=1.033,
        tracks=_tracks(2, 1.033, TrackStatus.VALID, snare_inside),
        commits=[strike(2, 1.033, shadow=False)],
    )
    # the anticipatory B commit owns the entry; the reactive A commit is the audible stream's second
    assert {v.invariant for v in found} == {"I4"}


def test_i4_expired_prediction_is_unattributed_not_a_violation(registry, snare_inside, snare_outside):
    auditor = CommitAuditor(CommitSettings(refractory_zone_s=0.0, refractory_hand_s=0.0), registry)
    auditor.audit_frame(
        frame_id=1,
        t_capture=1.0,
        t_now=1.0,
        tracks=_tracks(1, 1.0, TrackStatus.VALID, snare_outside),
        commits=[strike(1, 1.0, arm=Arm.B, source="RULE", target=1.02)],
    )
    auditor.audit_frame(
        frame_id=2,
        t_capture=1.2,
        t_now=1.2,
        tracks=_tracks(2, 1.2, TrackStatus.VALID, snare_outside),
        commits=[],
    )
    found = auditor.audit_frame(
        frame_id=3,
        t_capture=1.3,
        t_now=1.3,
        tracks=_tracks(3, 1.3, TrackStatus.VALID, snare_inside),
        commits=[strike(3, 1.3)],
    )
    assert found == [] and auditor.summary()["anticipatory_unattributed"] == {"AUDIBLE": 1, "B": 1}


# -- negative controls at the frame-result level (I2, I5, I6) -----------------------------------


def _one_frame(cfg, registry):
    pipe = make_pipeline(cfg, registry, active="A", shadow=("B",))
    frames = list(scenario("single", registry, t_down=0.12))
    results = [pipe.step(s, o, t_now=s.t_frame_available) for s, o in frames]
    hit = next(r for r in results if any(not c.shadow for c in r.commits))  # an audible commit
    return pipe, results, hit


def test_i2_detects_future_record(cfg, registry):
    pipe, results, hit = _one_frame(cfg, registry)
    monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
    hand = hit.commits[0].hand_id
    bad = dataclasses.replace(hit.hands[hand].commits[0], t_capture=hit.sample.t_capture + 0.5)
    hit.hands[hand].commits[0] = bad
    monitor.observe(hit, None)
    assert monitor.counts["I2"] >= 1


def test_i2_detects_non_increasing_frames(cfg, registry):
    pipe, results, _ = _one_frame(cfg, registry)
    monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
    monitor.observe(results[5], None)
    monitor.observe(results[4], None)
    assert monitor.counts["I2"] == 1


def test_i5_detects_commit_in_transition_frame_and_wrong_shadow(cfg, registry):
    pipe, _, hit = _one_frame(cfg, registry)
    monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
    monitor.observe(dataclasses.replace(hit, transition_seq=1), None)
    assert monitor.counts["I5"] >= 1
    monitor2 = InvariantMonitor.for_pipeline(pipe, mode="collect")
    monitor2.observe(dataclasses.replace(hit, active_arm=Arm.B), None)
    assert monitor2.counts["I5"] >= 1


def test_i6_detects_audio_without_commit(cfg, registry):
    pipe, results, hit = _one_frame(cfg, registry)
    event = hit.audio[0]
    quiet = next(r for r in results if not r.commits)
    monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
    quiet.hands[HandId.RIGHT].audio.append(event)
    monitor.observe(quiet, None)
    assert monitor.counts["I6"] >= 1


def test_raise_and_log_modes(cfg, registry, caplog):
    pipe, results, _ = _one_frame(cfg, registry)
    with pytest.raises(InvariantViolation, match="I2"):
        m = InvariantMonitor.for_pipeline(pipe, mode="raise")
        m.observe(results[5], None)
        m.observe(results[4], None)
    m = InvariantMonitor.for_pipeline(pipe, mode="log")
    with caplog.at_level(logging.ERROR):
        m.observe(results[5], None)
        m.observe(results[4], None)
    assert m.counts["I2"] == 1 and "I2" in caplog.text
    with pytest.raises(ValueError):
        InvariantMonitor.for_pipeline(pipe, mode="silent")


def test_ticker_is_deterministic():
    t = Ticker()
    assert t() < t()
