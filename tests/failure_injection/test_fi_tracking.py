"""TEST-FI-TRK-1..6: tracking and vision faults in observation space (Phase 17, Task 17.3). SYNTHETIC.

Occlusion (100-1000 ms) during the approach, at the impact and during idle; the hand leaving the
ROI; low confidence; a background hand reported as the user's; identity swaps. README section 8:
DEGRADED bridge for at most g_max frames, then INVALID (reset), STALE after age_max, re-acquisition
on a fresh VALID observation; zero commits while not VALID; the invariant monitor raises on any
violation. Fabrication by the baseline arms is checked against the analytic truth.
"""

from __future__ import annotations

import pytest
from inv_helpers import make_pipeline, run_frames

from spacedrums.app import faults as F
from spacedrums.app.invariants import InvariantMonitor
from spacedrums.app.synthetic import scenario
from spacedrums.contracts import HandId, ResetReason

DT = 1 / 30
R = HandId.RIGHT


def _frames(registry, name="repeated", **kw):
    seq = scenario(name, registry, t_down=kw.pop("t_down", 0.2), **kw)
    return seq, list(seq)


def _crossing(frames, t):
    return next(i for i, (s, _) in enumerate(frames) if s.t_capture >= t)


@pytest.mark.parametrize("duration", [3, 6, 9, 15, 30])
@pytest.mark.parametrize("position", ["approach", "impact", "idle"])
def test_occlusion_state_transitions_and_zero_unsafe_commits(cfg, registry, duration, position):
    seq, frames = _frames(registry)
    k = _crossing(frames, seq.truth[1].t_cross)
    start = {"approach": max(1, k - 1 - duration), "impact": k - 1, "idle": 2}[position]
    end = start + duration
    plan = F.FaultPlan().observations(start, end, "OCCLUSION", lambda o, _i: F.drop_hand(o, R))
    pipe = make_pipeline(cfg, registry, active="A", shadow=("B",))
    results = run_frames(pipe, frames, plan=plan, monitor=InvariantMonitor.for_pipeline(pipe, mode="raise"))
    statuses = [results[i].hands[R].track.status for i in range(start, end)]
    g_max = cfg["tracking"]["g_max_frames"]
    assert all(s == "DEGRADED" for s in statuses[:g_max])
    if duration > g_max:
        assert statuses[g_max] == "INVALID"
        assert results[start + g_max].hands[R].track.reset_reason in (
            ResetReason.GAP_EXCEEDED,
            ResetReason.STALE,
        )
        age = cfg["tracking"]["age_max_s"]
        t_valid = results[start - 1].sample.t_capture
        for i in range(start + g_max, end):
            s = results[i].hands[R].track.status
            assert s in (("STALE",) if results[i].sample.t_capture - t_valid > age else ("INVALID", "STALE"))
    # zero commits while not VALID (the invariant monitor would have raised), re-acquisition after
    assert all(c.hand_id is not R for i in range(start, end) for c in results[i].commits)
    assert results[end].hands[R].track.status == "VALID"


@pytest.mark.parametrize("kind", ["OCCLUSION", "OUT_OF_ROI", "LOW_CONF", "BACKGROUND_HAND"])
@pytest.mark.parametrize("active,shadow", [("A", ("B",)), ("B", ("A",))])
def test_baseline_arms_never_fabricate_under_loss_faults(cfg, registry, kind, active, shadow):
    """No commit without a same-hand strike within 300 ms (fabrication) for arms A and B."""
    seq, frames = _frames(registry, "alternating_two_zones")
    truth = [(t.hand, t.t_cross) for t in seq.truth]
    for start in range(3, len(frames) - 12, 7):
        plan = F.FaultPlan()
        if kind == "OCCLUSION":
            plan.observations(start, start + 9, kind, lambda o, _i: F.drop_hand(o, R))
        elif kind == "OUT_OF_ROI":
            plan.observations(
                start, start + 9, kind, lambda o, _i: F.drop_hand(F.translate_hand(o, R, 0.9, 0), R)
            )
        elif kind == "LOW_CONF":
            plan.observations(start, start + 9, kind, lambda o, _i: F.set_confidence(o, R, 0.45))
        else:
            plan.observations(
                start,
                start + 9,
                kind,
                lambda o, _i: F.replace_hand(o, R, F.translate_hand(o, R, -0.3, -0.25)[R]),
            )
        pipe = make_pipeline(cfg, registry, active=active, shadow=shadow)
        results = run_frames(
            pipe, frames, plan=plan, monitor=InvariantMonitor.for_pipeline(pipe, mode="raise")
        )
        for c in (c for r in results for c in r.commits):
            assert any(h is c.hand_id and abs(t - c.t_commit) <= 0.3 for h, t in truth), (kind, start, c)


def test_identity_swap_is_a_documented_residual_risk(cfg, registry):
    """Swaps teleport a track onto the other hand: reactive/rule arms can then commit a strike for the
    wrong hand (Phase 17 finding; mitigated only by the identity layer). The monitor still sees no
    invariant violation - the risk is attribution, recorded in the failure catalogue."""
    seq, frames = _frames(registry, "alternating_two_zones")
    k = _crossing(frames, seq.truth[0].t_cross)
    plan = F.FaultPlan().observations(k - 1, k + 2, "SWAP", lambda o, _i: F.swap_hands(o))
    pipe = make_pipeline(cfg, registry, active="A", shadow=("B",))
    monitor = InvariantMonitor.for_pipeline(pipe, mode="raise")
    run_frames(pipe, frames, plan=plan, monitor=monitor)
    assert monitor.finish()["violations_total"] == 0


def test_reacquisition_needs_a_fresh_valid_observation(cfg, registry):
    seq, frames = _frames(registry)
    plan = F.FaultPlan()
    plan.observations(10, 20, "OCCLUSION", lambda o, _i: F.drop_hand(o, R))
    plan.observations(20, 23, "LOW_CONF", lambda o, _i: F.set_confidence(o, R, 0.45))
    pipe = make_pipeline(cfg, registry)
    results = run_frames(pipe, frames, plan=plan, monitor=InvariantMonitor.for_pipeline(pipe, mode="raise"))
    # DEGRADED-level observations do not re-acquire (acquire_on_degraded = false)
    assert all(results[i].hands[R].track.status in ("INVALID", "STALE") for i in range(20, 23))
    assert results[23].hands[R].track.status == "VALID"
    assert results[23].hands[R].prediction is None  # rule arm warms up again after the reset


@pytest.mark.parametrize(
    "name",
    ["single", "repeated", "rapid", "alternating_one_zone", "alternating_two_zones", "near_simultaneous"],
)
def test_hit_types_under_short_occlusion_keep_invariants(cfg, registry, name):
    """REQ-012 x REQ-035: every hit type with a 100 ms occlusion of each hand in turn."""
    seq, frames = _frames(registry, name, t_down=0.12)
    for hand in (HandId.LEFT, HandId.RIGHT):
        for start in range(4, len(frames) - 4, 9):
            plan = F.FaultPlan().observations(
                start, start + 3, "OCCLUSION", lambda o, _i, h=hand: F.drop_hand(o, h)
            )
            pipe = make_pipeline(cfg, registry, active="B", shadow=("A",))
            run_frames(pipe, frames, plan=plan, monitor=InvariantMonitor.for_pipeline(pipe, mode="raise"))
