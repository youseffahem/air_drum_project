"""TEST-COMMIT-1: every transition of the per-(hand, zone) commit machine and the refractory timers."""

from __future__ import annotations

import pytest

from spacedrums.commit import CommitPhase, RefractoryTimers, ZoneCommitMachine
from spacedrums.contracts import ResetReason


def test_idle_to_committed_to_refractory_to_idle():
    m = ZoneCommitMachine(n_confirm=0, release_after_s=0.02)
    m.begin_frame(1.0, False)
    assert m.s.phase is CommitPhase.IDLE and m.passing_candidate() is True
    n = m.commit(1.0, 1.05, 1.1)
    assert n == 1 and m.s.phase is CommitPhase.COMMITTED and m.s.commit_pending
    assert m.passing_candidate() is False  # no second commit in the commit frame
    m.begin_frame(1.03, False)
    assert m.s.phase is CommitPhase.REFRACTORY
    assert m.passing_candidate() is False
    m.begin_frame(1.1, False)  # timer elapsed
    assert m.s.phase is CommitPhase.IDLE
    assert m.s.commit_pending is False  # predicted crossing not observed by 1.05 + 0.02 -> released


def test_armed_hysteresis_requires_consecutive_passing_frames():
    m = ZoneCommitMachine(n_confirm=3, release_after_s=0.0)
    m.begin_frame(0.0, False)
    assert m.passing_candidate() is False and m.s.phase is CommitPhase.ARMED and m.s.armed_frames == 1
    m.begin_frame(0.03, False)
    assert m.passing_candidate() is False and m.s.armed_frames == 2
    m.begin_frame(0.06, False)
    m.no_passing_candidate()  # a frame without a passing candidate discards the ARMED state
    assert m.s.phase is CommitPhase.IDLE and m.s.armed_frames == 0
    for k in range(3):
        m.begin_frame(0.1 + 0.03 * k, False)
        committed = m.passing_candidate()
    assert committed is True and m.s.armed_frames == 3


def test_episode_bookkeeping_entry_exit_and_release():
    m = ZoneCommitMachine(n_confirm=0, release_after_s=0.05)
    m.begin_frame(0.0, False)
    m.commit(0.0, 0.04, 10.0)  # long refractory so only the episode logic matters here
    assert m.s.commit_pending and m.episode_blocked()
    m.begin_frame(0.03, True)  # observed entry: the predicted crossing materialised
    assert not m.s.commit_pending and m.s.committed_in_episode and m.episode_blocked()
    m.begin_frame(0.06, True)  # hovering inside: still the same episode
    assert m.episode_blocked()
    m.begin_frame(0.09, False)  # exit closes the episode
    assert not m.episode_blocked()
    # release without entry (false positive by definition): pending cleared after target + release
    m2 = ZoneCommitMachine(n_confirm=0, release_after_s=0.05)
    m2.begin_frame(0.0, False)
    m2.commit(0.0, 0.04, 0.0)
    m2.begin_frame(0.08, False)
    assert m2.episode_blocked()  # 0.08 <= 0.04 + 0.05
    m2.begin_frame(0.10, False)
    assert not m2.episode_blocked()


def test_commit_while_inside_marks_episode_not_pending():
    m = ZoneCommitMachine(n_confirm=0, release_after_s=0.02)
    m.begin_frame(0.0, True)  # reactive commit happens on the entry frame (tip already inside)
    m.commit(0.0, 0.0, 0.1)
    assert m.s.committed_in_episode and not m.s.commit_pending and m.episode_blocked()
    m.begin_frame(0.2, False)
    assert not m.episode_blocked()


def test_invalidate_and_reset_go_idle_and_keep_episode_counter():
    m = ZoneCommitMachine(n_confirm=2, release_after_s=0.02)
    m.begin_frame(0.0, False)
    m.passing_candidate()
    assert m.s.phase is CommitPhase.ARMED
    m.invalidate()
    assert m.s.phase is CommitPhase.IDLE and m.s.armed_frames == 0 and not m.s.inside
    m.begin_frame(0.1, False)
    m.passing_candidate()
    m.passing_candidate()
    m.commit(0.1, 0.1, 0.2)
    m.reset()
    assert m.s.phase is CommitPhase.IDLE and m.s.episode_n == 1  # ids persist (reset matrix)


def test_invalid_arguments():
    with pytest.raises(ValueError):
        ZoneCommitMachine(n_confirm=-1, release_after_s=0.0)
    with pytest.raises(ValueError):
        RefractoryTimers(r_zone_s=-0.1, r_hand_s=0.0)


def test_refractory_timers_persist_except_session_start():
    t = RefractoryTimers(r_zone_s=0.1, r_hand_s=0.04)
    assert not t.zone_blocked("snare", 1.0) and not t.hand_blocked(1.0)
    until = t.note_commit("snare", 1.0)
    assert until == pytest.approx(1.1)
    assert (
        t.zone_blocked("snare", 1.05)
        and not t.zone_blocked("snare", 1.1)
        and not t.zone_blocked("tom1", 1.05)
    )
    assert t.hand_blocked(1.03) and not t.hand_blocked(1.04)
    for reason in (
        ResetReason.GAP_EXCEEDED,
        ResetReason.LOW_CONFIDENCE,
        ResetReason.STALE,
        ResetReason.MANUAL,
        ResetReason.ARM_SWITCH,
        ResetReason.CONFIG_RELOAD,
    ):
        t.reset(reason)
        assert t.zone_blocked("snare", 1.05) and t.last_commit_t == 1.0
    t.reset(ResetReason.SESSION_START)
    assert not t.zone_blocked("snare", 1.05) and t.last_commit_t is None
    assert RefractoryTimers(r_zone_s=0.1, r_hand_s=0.0).hand_blocked(0.0) is False
