"""TEST-COMMIT-2 (every gate), TEST-CONFORM-5 (property tests) for ``PerHandCommitPolicy`` (Task 05.3).

All candidate streams are SYNTHETIC. The property test draws random candidate/status streams from
a seeded generator and asserts the safety invariants over thousands of steps.
"""

from __future__ import annotations

import dataclasses
import random

import pytest
from commit_helpers import candidate, policy, track

from spacedrums.commit import CommitSettings, Decision
from spacedrums.contracts import CommitPolicy, CommittedStrike, HandId, ResetReason, TrackStatus
from spacedrums.contracts import schema as contract_schema


def test_protocol_and_schema_valid_commit(make_policy):
    p = make_policy(tti_commit_s=0.05, p_commit=0.5)
    assert isinstance(p, CommitPolicy)
    out = p.step([candidate(3, 1.0, t_impact=1.04)], track(3, 1.0), 1.01)
    assert len(out) == 1
    s = out[0]
    assert isinstance(s, CommittedStrike) and contract_schema.is_valid("committed-strike", s.to_dict())
    assert s.arm.value == "B" and s.source.value == "RULE" and not s.shadow
    assert s.t_commit == 1.01 and s.t_impact_target == 1.04 and s.refractory_until == pytest.approx(1.11)
    assert (
        s.gain == 0.5 and s.episode_id == "syn-RIGHT-snare-e000001" and s.strike_id == "syn-RIGHT-B-s000001"
    )
    assert s.commit_policy_id == p.commit_policy_id and p.commits == 1
    assert p.trace[0].decision is Decision.COMMITTED


def test_reactive_commit_targets_now_and_ignores_probability_and_tti(make_policy):
    p = make_policy(arm="A", tti_commit_s=0.0, p_commit=1.0)
    c = candidate(3, 1.0, source="REACTIVE", t_impact=0.98)
    out = p.step([c], track(3, 1.0, pos=(0.5, 0.65)), 1.02)
    assert len(out) == 1 and out[0].t_impact_target == 1.02 and out[0].arm.value == "A"
    assert out[0].source.value == "REACTIVE" and out[0].derivation.value == "GEOMETRY"


def test_status_gate_never_commits_and_goes_idle(make_policy):
    p = make_policy()
    for status in (TrackStatus.DEGRADED, TrackStatus.INVALID, TrackStatus.STALE):
        out = p.step([candidate(1, 1.0, t_impact=1.02)], track(1, 1.0, status=status), 1.0)
        assert out == [] and p.trace[-1].decision is Decision.REJECT_STATUS
    assert p.commits == 0
    p_deg = make_policy(allow_degraded_commits=True)
    assert (
        len(p_deg.step([candidate(1, 1.0, t_impact=1.02)], track(1, 1.0, status=TrackStatus.DEGRADED), 1.0))
        == 1
    )
    assert (
        p_deg.step([candidate(2, 1.1, t_impact=1.12)], track(2, 1.1, status=TrackStatus.INVALID), 1.1) == []
    )


def test_frame_drop_guard(make_policy):
    p = make_policy(max_dropped_since_last=1)
    assert p.step([candidate(1, 1.0, t_impact=1.02)], track(1, 1.0), 1.0, dropped_since_last=2) == []
    assert p.trace[-1].decision is Decision.REJECT_FRAME_DROP
    assert len(p.step([candidate(2, 1.03, t_impact=1.05)], track(2, 1.03), 1.03, dropped_since_last=1)) == 1


def test_zone_validity_and_hand_ownership(make_policy):
    p = make_policy()
    assert p.step([candidate(1, 1.0, zone_id="kick", t_impact=1.02)], track(1, 1.0), 1.0) == []
    assert p.trace[-1].decision is Decision.REJECT_ZONE
    with pytest.raises(ValueError):
        p.step([], track(2, 1.1, hand=HandId.LEFT), 1.1)
    assert p.step([candidate(3, 1.2, t_impact=1.22, hand=HandId.LEFT)], track(3, 1.2), 1.2) == []
    assert p.trace[-1].decision is Decision.REJECT_ZONE


def test_source_arm_invariant(make_policy):
    p = make_policy(arm="A")
    assert p.step([candidate(1, 1.0, t_impact=1.02)], track(1, 1.0), 1.0) == []  # RULE candidate on arm A
    assert p.trace[-1].decision is Decision.REJECT_SOURCE_ARM
    p_b = make_policy(arm="B")
    assert p_b.step([candidate(1, 1.0, source="REACTIVE", t_impact=0.99)], track(1, 1.0), 1.0) == []
    assert p_b.trace[-1].decision is Decision.REJECT_SOURCE_ARM


def test_stale_prediction_gate(make_policy):
    p = make_policy(stale_prediction_tolerance_s=0.02)
    assert p.step([candidate(1, 1.0, t_impact=0.97)], track(1, 1.0), 1.0) == []
    assert p.trace[-1].decision is Decision.REJECT_STALE
    assert (
        len(p.step([candidate(2, 1.03, t_impact=1.02)], track(2, 1.03), 1.03)) == 1
    )  # 10 ms past: within tolerance


def test_probability_gate_and_null_probability(make_policy):
    p = make_policy(p_commit=0.6)
    assert p.step([candidate(1, 1.0, t_impact=1.02, prob=0.59)], track(1, 1.0), 1.0) == []
    assert p.trace[-1].decision is Decision.REJECT_PROBABILITY
    assert len(p.step([candidate(2, 1.1, t_impact=1.12, prob=0.6)], track(2, 1.1), 1.1)) == 1
    p2 = make_policy(p_commit=1.0)
    assert (
        len(p2.step([candidate(3, 1.0, t_impact=1.02, prob=None)], track(3, 1.0), 1.0)) == 1
    )  # not estimated -> not gated


def test_tti_gate(make_policy):
    p = make_policy(tti_commit_s=0.05)
    assert p.step([candidate(1, 1.0, t_impact=1.06)], track(1, 1.0), 1.0) == []
    assert p.trace[-1].decision is Decision.REJECT_TTI
    assert (
        len(p.step([candidate(2, 1.03, t_impact=1.06)], track(2, 1.03), 1.03)) == 1
    )  # now within tau_commit


def test_refractory_zone_and_hand(make_policy):
    p = make_policy(refractory_zone_s=0.10, refractory_hand_s=0.04, stale_prediction_tolerance_s=0.0)
    assert len(p.step([candidate(1, 1.0, t_impact=1.02)], track(1, 1.0), 1.0)) == 1
    # same zone within r_zone: rejected by the zone timer (episode released once the target passed)
    assert p.step([candidate(2, 1.05, t_impact=1.07)], track(2, 1.05), 1.05) == []
    assert p.trace[-1].decision in (Decision.REJECT_REFRACTORY_ZONE, Decision.REJECT_EPISODE)
    # other zone within r_hand: rejected by the hand interval
    assert p.step([candidate(3, 1.02, zone_id="tom1", t_impact=1.03)], track(3, 1.02), 1.02) == []
    assert p.trace[-1].decision is Decision.REJECT_REFRACTORY_HAND
    # other zone after r_hand: allowed (rapid alternating on different zones)
    assert len(p.step([candidate(4, 1.05, zone_id="tom1", t_impact=1.06)], track(4, 1.05), 1.05)) == 1
    # same zone after r_zone: allowed again
    assert len(p.step([candidate(5, 1.20, t_impact=1.22)], track(5, 1.20), 1.20)) == 1


def test_one_commit_per_episode_predicted_then_observed(make_policy):
    """B commits before the crossing; the same crossing's later candidate frames must not re-commit."""
    p = make_policy(refractory_zone_s=0.0, refractory_hand_s=0.0, stale_prediction_tolerance_s=0.02)
    out = p.step([candidate(1, 1.00, t_impact=1.04)], track(1, 1.00, pos=(0.5, 0.55)), 1.00)
    assert len(out) == 1
    # next frame, still outside, prediction repeats the same crossing -> episode pending -> reject
    assert p.step([candidate(2, 1.03, t_impact=1.045)], track(2, 1.03, pos=(0.5, 0.58)), 1.03) == []
    assert p.trace[-1].decision is Decision.REJECT_EPISODE
    # tip enters the zone (observed), hovers inside: no commit while inside after the commit
    assert p.step([candidate(3, 1.06, t_impact=1.07)], track(3, 1.06, pos=(0.5, 0.65)), 1.06) == []
    assert p.step([], track(4, 1.09, pos=(0.5, 0.66)), 1.09) == []
    # leaves and re-enters: a new episode may commit
    p.step([], track(5, 1.30, pos=(0.5, 0.50)), 1.30)
    assert len(p.step([candidate(6, 1.33, t_impact=1.36)], track(6, 1.33, pos=(0.5, 0.55)), 1.33)) == 1


def test_stop_before_impact_after_commit_is_a_false_positive_by_design(make_policy):
    p = make_policy(refractory_zone_s=0.0, refractory_hand_s=0.0, stale_prediction_tolerance_s=0.02)
    out = p.step([candidate(1, 1.00, t_impact=1.04)], track(1, 1.00, pos=(0.5, 0.55)), 1.00)
    assert len(out) == 1  # committed; V1 never cancels
    for k in range(1, 6):  # the tip never enters; the pending episode is released after target + tolerance
        p.step([], track(1 + k, 1.0 + 0.03 * k, pos=(0.5, 0.55)), 1.0 + 0.03 * k)
    assert not p.machines["snare"].episode_blocked()
    assert p.commits == 1


def test_n_confirm_hysteresis_through_policy(make_policy):
    p = make_policy(n_confirm_frames=2, tti_commit_s=0.2)
    assert p.step([candidate(1, 1.00, t_impact=1.10)], track(1, 1.00), 1.00) == []
    assert p.trace[-1].decision is Decision.ARMED
    assert len(p.step([candidate(2, 1.03, t_impact=1.10)], track(2, 1.03), 1.03)) == 1
    # an interrupted sequence restarts the count
    p2 = make_policy(n_confirm_frames=2, tti_commit_s=0.2, refractory_zone_s=0.0, refractory_hand_s=0.0)
    p2.step([candidate(1, 1.00, t_impact=1.10)], track(1, 1.00), 1.00)
    p2.step([], track(2, 1.03), 1.03)
    assert p2.step([candidate(3, 1.06, t_impact=1.10)], track(3, 1.06), 1.06) == []


def test_reset_matrix_discards_armed_keeps_timers(make_policy):
    p = make_policy(n_confirm_frames=2, tti_commit_s=0.2, refractory_zone_s=0.5)
    p.step([candidate(1, 1.0, t_impact=1.1)], track(1, 1.0), 1.0)
    p.reset(ResetReason.GAP_EXCEEDED)
    assert p.step([candidate(2, 1.03, t_impact=1.1)], track(2, 1.03), 1.03) == []  # count restarted
    assert len(p.step([candidate(3, 1.06, t_impact=1.1)], track(3, 1.06), 1.06)) == 1
    p.reset(ResetReason.MANUAL)
    assert p.timers.zone_blocked("snare", 1.2)  # timers persist across resets
    p.reset(ResetReason.SESSION_START)
    assert not p.timers.zone_blocked("snare", 1.2)


def test_two_hands_do_not_share_state(registry):
    left = policy(registry, hand=HandId.LEFT)
    right = policy(registry, hand=HandId.RIGHT)
    cl = candidate(1, 1.0, t_impact=1.02, hand=HandId.LEFT)
    cr = candidate(1, 1.0, t_impact=1.02, hand=HandId.RIGHT)
    assert len(left.step([cl], track(1, 1.0, hand=HandId.LEFT), 1.0)) == 1
    assert len(right.step([cr], track(1, 1.0, hand=HandId.RIGHT), 1.0)) == 1  # near-simultaneous: independent
    assert (
        left.timers.snapshot() == right.timers.snapshot() and left.state_snapshot() != right.state_snapshot()
    )


def test_shadow_policy_flags_commits(registry):
    p = policy(registry, shadow=True)
    out = p.step([candidate(1, 1.0, t_impact=1.02)], track(1, 1.0), 1.0)
    assert out and out[0].shadow is True


def test_settings_from_config_and_ids():
    cfg = {
        "commit": {
            "commit_policy_id": "c",
            "tti_commit_s": 0.05,
            "p_commit": 0.5,
            "n_confirm_frames": 0,
            "refractory_zone_s": 0.1,
            "refractory_hand_s": 0.04,
            "allow_degraded_commits": False,
            "stale_prediction_tolerance_s": 0.02,
            "max_dropped_since_last": 1,
        }
    }
    s = CommitSettings.from_config(cfg)
    assert s.allowed_statuses == (TrackStatus.VALID,) and s.full_id().startswith("c:tti0.050:p0.50:n0")
    with pytest.raises(ValueError):
        CommitSettings(p_commit=1.5)


# ----------------------------------------------------------------------------- property test (TEST-CONFORM-5)


def test_property_no_commit_outside_allowed_status_and_invariants(registry):
    rng = random.Random(1234)
    statuses = list(TrackStatus)
    for trial in range(40):
        allow_deg = trial % 2 == 1
        p = policy(
            registry,
            allow_degraded_commits=allow_deg,
            refractory_zone_s=rng.choice([0.0, 0.05, 0.1]),
            refractory_hand_s=rng.choice([0.0, 0.02, 0.04]),
            n_confirm_frames=rng.choice([0, 0, 1, 2]),
            tti_commit_s=rng.choice([0.0, 0.05, 0.2]),
            p_commit=rng.random(),
        )
        t = 1.0
        last_commit_zone: dict[str, float] = {}
        episodes: set[str] = set()
        for frame in range(300):
            t += 1 / 30
            status = rng.choice(statuses) if rng.random() < 0.3 else TrackStatus.VALID
            pos = (0.5, rng.uniform(0.1, 0.9))
            cands = []
            for _ in range(rng.choice([0, 0, 1, 1, 2, 3])):
                src = rng.choice(["RULE", "REACTIVE"])
                z = rng.choice(["snare", "tom1", "kick"])
                cands.append(
                    candidate(
                        frame,
                        t,
                        source=src,
                        zone_id=z,
                        t_impact=t + rng.uniform(-0.1, 0.3),
                        prob=rng.choice([None, rng.random()]),
                    )
                )
            arm_cands = [c for c in cands if c.source.value == "RULE"]
            out = p.step(
                arm_cands,
                track(frame, t, status=status, pos=pos),
                t,
                dropped_since_last=rng.choice([0, 0, 0, 3]),
            )
            allowed = (TrackStatus.VALID, TrackStatus.DEGRADED) if allow_deg else (TrackStatus.VALID,)
            if status not in allowed:
                assert out == []
            for s in out:
                assert dataclasses.replace(s).hand_id is HandId.RIGHT and s.zone_id in ("snare", "tom1")
                assert s.episode_id not in episodes, "one commit per episode"
                episodes.add(s.episode_id)
                if s.zone_id in last_commit_zone:
                    assert t - last_commit_zone[s.zone_id] >= p.settings.refractory_zone_s - 1e-9
                last_commit_zone[s.zone_id] = t
                assert s.t_impact_target >= t - p.settings.stale_prediction_tolerance_s - 1e-9
                assert contract_schema.is_valid("committed-strike", s.to_dict())
