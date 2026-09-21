"""TEST-TRACK-2: every README section 8 transition of the state machine (Phase 03, Task 03.13)."""

from __future__ import annotations

import pytest

from spacedrums.contracts import ResetReason, TrackStatus
from spacedrums.tracking import StateMachineSettings, TrackingStateMachine

S = StateMachineSettings(c_valid=0.6, c_min=0.3, g_max_frames=3, age_max_s=0.5, bridge_decay=0.5)
DT = 1 / 30


def run(machine, steps):
    """steps: list of (has_obs, conf); returns decisions with t advancing by DT."""
    out = []
    for k, (has, conf) in enumerate(steps):
        out.append(machine.step(100.0 + k * DT, has, conf))
    return out


def test_initial_state_is_invalid_and_acquires_on_valid_confidence():
    m = TrackingStateMachine(S)
    d0 = m.step(100.0, False, 0.0)
    assert d0.status is TrackStatus.INVALID and d0.action == "none" and d0.frames_since_valid == 1
    d1 = m.step(100.0 + DT, True, 0.9)
    assert d1.status is TrackStatus.VALID and d1.action == "init" and d1.frames_since_valid == 0
    assert d1.last_valid_t == pytest.approx(100.0 + DT) and d1.confidence == 0.9


def test_valid_to_degraded_on_mid_confidence_and_back():
    m = TrackingStateMachine(S)
    d = run(m, [(True, 0.9), (True, 0.4), (True, 0.35), (True, 0.8)])
    assert [x.status for x in d] == [TrackStatus.VALID, TrackStatus.DEGRADED, TrackStatus.DEGRADED,
                                     TrackStatus.VALID]
    assert [x.action for x in d] == ["init", "update", "update", "update"]  # observation still used
    assert [x.frames_since_valid for x in d] == [0, 1, 2, 0]
    assert d[1].last_valid_t == d[0].last_valid_t  # last VALID time unchanged during DEGRADED


def test_gap_is_bridged_for_g_max_then_invalid_gap_exceeded():
    m = TrackingStateMachine(S)
    d = run(m, [(True, 0.9)] + [(False, 0.0)] * 5)
    assert [x.status for x in d[1:5]] == [TrackStatus.DEGRADED] * 3 + [TrackStatus.INVALID]
    assert [x.action for x in d[1:4]] == ["predict"] * 3  # prediction only, nothing invented
    assert d[1].confidence == pytest.approx(0.45) and d[2].confidence == pytest.approx(0.225)
    assert d[4].action == "reset" and d[4].reset_reason is ResetReason.GAP_EXCEEDED
    assert d[5].status is TrackStatus.INVALID and d[5].action == "none" and d[5].reset_reason is None
    assert d[4].frames_since_valid == 4 and d[5].frames_since_valid == 5


def test_low_confidence_observations_count_as_gap_and_name_the_reason():
    m = TrackingStateMachine(S)
    d = run(m, [(True, 0.9)] + [(True, 0.1)] * 4)
    assert [x.status for x in d[1:]] == [TrackStatus.DEGRADED] * 3 + [TrackStatus.INVALID]
    assert d[4].reset_reason is ResetReason.LOW_CONFIDENCE


def test_gap_counter_resets_on_any_usable_observation():
    m = TrackingStateMachine(S)
    d = run(m, [(True, 0.9), (False, 0), (False, 0), (True, 0.4), (False, 0), (False, 0), (False, 0),
                (False, 0)])
    # 2 bridged, degraded obs, then 3 bridged, then INVALID on the 4th
    assert [x.status for x in d] == [TrackStatus.VALID] + [TrackStatus.DEGRADED] * 6 + [TrackStatus.INVALID]


def test_stale_after_age_max_without_valid():
    m = TrackingStateMachine(StateMachineSettings(c_valid=0.6, c_min=0.3, g_max_frames=100, age_max_s=0.1))
    m.step(100.0, True, 0.9)
    d1 = m.step(100.05, False, 0.0)
    assert d1.status is TrackStatus.DEGRADED  # within age_max: still bridging
    d2 = m.step(100.2, False, 0.0)  # 0.2 s since the last VALID > age_max 0.1
    assert d2.status is TrackStatus.STALE and d2.action == "reset" and d2.reset_reason is ResetReason.STALE
    d3 = m.step(100.25, False, 0.0)
    assert d3.status is TrackStatus.STALE and d3.action == "none" and d3.reset_reason is None
    d4 = m.step(100.3, True, 0.4)  # degraded-level observation does not re-acquire
    assert d4.status is TrackStatus.STALE and d4.action == "none"
    d5 = m.step(100.35, True, 0.9)  # re-acquisition
    assert d5.status is TrackStatus.VALID and d5.action == "init" and d5.frames_since_valid == 0


def test_degraded_observation_does_not_reacquire_from_invalid_unless_enabled():
    m = TrackingStateMachine(S)
    d = m.step(100.0, True, 0.4)
    assert d.status is TrackStatus.INVALID and d.action == "none"
    m2 = TrackingStateMachine(StateMachineSettings(acquire_on_degraded=True))
    d2 = m2.step(100.0, True, 0.4)
    assert d2.status is TrackStatus.DEGRADED and d2.action == "init" and d2.frames_since_valid == 1


def test_external_reset_is_reported_on_the_next_frame_only():
    m = TrackingStateMachine(S)
    run(m, [(True, 0.9), (True, 0.9)])
    m.reset(ResetReason.MANUAL)
    d = m.step(100.5, True, 0.9)
    assert d.status is TrackStatus.VALID and d.action == "init" and d.reset_reason is ResetReason.MANUAL
    d2 = m.step(100.6, True, 0.9)
    assert d2.reset_reason is None


def test_frames_since_valid_zero_iff_valid():
    m = TrackingStateMachine(S)
    for d in run(m, [(False, 0), (True, 0.9), (True, 0.4), (False, 0), (False, 0), (False, 0), (False, 0),
                     (True, 0.9), (True, 0.9)]):
        assert (d.frames_since_valid == 0) == (d.status is TrackStatus.VALID)


def test_g_max_zero_means_no_bridge():
    m = TrackingStateMachine(StateMachineSettings(g_max_frames=0))
    d = run(m, [(True, 0.9), (False, 0.0)])
    assert d[1].status is TrackStatus.INVALID and d[1].reset_reason is ResetReason.GAP_EXCEEDED


def test_settings_validation():
    with pytest.raises(ValueError):
        StateMachineSettings(c_valid=0.2, c_min=0.5)
    with pytest.raises(ValueError):
        StateMachineSettings(age_max_s=0)
    with pytest.raises(ValueError):
        StateMachineSettings(bridge_decay=0)
