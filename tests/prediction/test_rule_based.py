"""TEST-PRED-1..3 + TEST-CONFORM-3 for the rule-based anticipator (Phase 05, Task 05.2).

All inputs are SYNTHETIC kinematic histories (conftest); nothing here is real-world evidence.
"""

from __future__ import annotations

import dataclasses
import math

import pytest
from synthetic_histories import DT, parabolic_history, track

from spacedrums.contracts import Anticipator, ResetReason, TrackStatus
from spacedrums.contracts import schema as contract_schema
from spacedrums.geometry import Arc, Ellipse, GeometryEngine, Zone, ZoneRegistry
from spacedrums.prediction import (
    DeclineReason,
    RuleBasedAnticipator,
    RuleSettings,
    combine_gates,
    direction_gate,
    extrapolate,
    speed_gate,
)


def _settings(**kw) -> RuleSettings:
    base = dict(anticipator_id="rule-test", motion_model="CV", K=6, dt_step=DT, v_min_predict=0.0)
    base.update(kw)
    return RuleSettings(**base)


def _registry() -> ZoneRegistry:
    zone = Zone(
        "snare",
        "Snare",
        "HAND_TIP",
        Ellipse((0.4, 0.7), 0.2, 0.1),
        Arc((0.4, 0.7), 0.2, 0.1, 0.0, math.pi, 2 * math.pi),
        (0.0, 1.0),
        ("LEFT", "RIGHT"),
        "s",
        "default",
    )
    return ZoneRegistry((zone,))


# ----------------------------------------------------------------------------- conformance


def test_conform_3_protocol_and_schema(parabola):
    ant = RuleBasedAnticipator(_settings(), clock=lambda: 200.0)
    assert isinstance(ant, Anticipator)
    assert ant.model_hash is None and ant.anticipator_id.startswith("rule-test:cv")
    pred = ant.predict(parabola)
    assert pred is not None
    assert pred.t_capture == parabola[-1].t_capture and pred.frame_id == parabola[-1].frame_id
    assert len(pred.positions) == pred.K == 6 and pred.dt_step == DT and pred.t_offsets_s is None
    assert pred.t_inference_done == 200.0 and pred.anticipator_id == ant.anticipator_id
    assert contract_schema.is_valid("trajectory-prediction", pred.to_dict())


def test_conform_3_declines_never_raise():
    ant = RuleBasedAnticipator(_settings(n_min_frames=2))
    assert ant.predict([]) is None and ant.last_decline is DeclineReason.EMPTY_HISTORY
    invalid = track(5, 100.0, None, None, status=TrackStatus.INVALID)
    assert ant.predict([invalid]) is None and ant.last_decline is DeclineReason.STATUS_NOT_LIVE
    stale = track(5, 100.0, None, None, status=TrackStatus.STALE)
    assert ant.predict([stale]) is None and ant.last_decline is DeclineReason.STATUS_NOT_LIVE
    one = parabolic_history(1)
    assert ant.predict(one) is None and ant.last_decline is DeclineReason.INSUFFICIENT_HISTORY
    h = parabolic_history(4)
    bad = h[:2] + [dataclasses.replace(h[2], t_capture=h[1].t_capture)] + h[3:]
    assert ant.predict(bad) is None and ant.last_decline is DeclineReason.NON_MONOTONIC_TIME
    assert ant.declines == {
        "EMPTY_HISTORY": 1,
        "STATUS_NOT_LIVE": 2,
        "INSUFFICIENT_HISTORY": 1,
        "NON_MONOTONIC_TIME": 1,
    }


def test_conform_3_reset_is_stateless(parabola):
    a, b = (
        RuleBasedAnticipator(_settings(), clock=lambda: 1.0),
        RuleBasedAnticipator(_settings(), clock=lambda: 1.0),
    )
    a.predict(parabola[:6])
    a.reset(ResetReason.GAP_EXCEEDED)
    assert a.predict(parabola).to_dict() == b.predict(parabola).to_dict()


# ----------------------------------------------------------------------------- extrapolation


def test_cv_and_ca_extrapolation_match_closed_form():
    p, v, a = (0.1, 0.2), (0.5, -0.3), (2.0, 4.0)
    for k in (1, 3, 7):
        tau = k * DT
        cv_pos, cv_vel = extrapolate(p, v, None, k, DT)
        assert cv_pos == pytest.approx((p[0] + v[0] * tau, p[1] + v[1] * tau)) and cv_vel == v
        ca_pos, ca_vel = extrapolate(p, v, a, k, DT)
        assert ca_pos == pytest.approx(
            (p[0] + v[0] * tau + 0.5 * a[0] * tau**2, p[1] + v[1] * tau + 0.5 * a[1] * tau**2)
        )
        assert ca_vel == pytest.approx((v[0] + a[0] * tau, v[1] + a[1] * tau))


def test_ca_prediction_on_parabola_is_exact_and_cv_lags(parabola):
    """On an exact parabolic history CA reproduces the future positions; CV under-shoots (analytic)."""
    ca = RuleBasedAnticipator(_settings(motion_model="CA")).predict(parabola)
    cv = RuleBasedAnticipator(_settings(motion_model="CV")).predict(parabola)
    truth = parabolic_history(12 + 6)
    for k in range(6):
        exp = truth[12 + k].tip_filtered
        assert ca.positions[k] == pytest.approx(exp, abs=1e-9)
        assert cv.positions[k][1] < exp[1]  # constant-velocity ignores the downward acceleration
    assert ca.velocities[-1][1] == pytest.approx(truth[17].tip_velocity[1], abs=1e-9)


def test_predicted_crossing_time_vs_analytic_through_geometry(capsys):
    """Task 05.2 evidence: predicted crossing time (CA) vs analytic crossing of a synthetic parabola.

    Geometry interpolates linearly between the K predicted samples (dt_step = 1/30 s), so even the exact
    CA trajectory carries a sub-step interpolation error (declared tolerance 1e-3 s); CV lags the
    accelerating stroke by construction (declared tolerance 3e-2 s). Both errors are printed.
    """
    reg = _registry()
    p0, v0, a = (0.4, 0.4), (0.0, 0.6), (0.0, 8.0)
    # the top of the snare ellipse at x = 0.4 is y_s = 0.6
    # y_s = 0.4 + 0.6 t + 4 t^2  ->  4 t^2 + 0.6 t - 0.2 = 0
    t_cross = (-0.6 + math.sqrt(0.36 + 3.2)) / 8.0
    hist = parabolic_history(4, p0=p0, v0=v0, a=a)
    t_ref = hist[-1].t_capture
    assert t_cross > 3 * DT  # crossing lies in the future of the last history sample
    for model, tol in (("CA", 1e-3), ("CV", 0.03)):
        ant = RuleBasedAnticipator(_settings(motion_model=model, K=8), clock=lambda: 0.0)
        pred = ant.predict(hist)
        engine = GeometryEngine(reg, v_min=0.1, session_id="t")
        cand = engine.intersect_prediction(pred, current_position=hist[-1].tip_filtered, t_candidate=0.0)
        assert cand is not None and cand.source.value == "RULE" and cand.zone_id == "snare"
        err = cand.t_impact_pred - (100.0 + t_cross)
        with capsys.disabled():
            print(
                f"\nTEST-PRED-1 {model} SYNTHETIC parabola: predicted - analytic crossing = {err:+.2e} s "
                f"(tolerance {tol:g}, dt_step 1/30 s, linear sub-step interpolation)"
            )
        assert abs(err) <= tol
        assert cand.tti == pytest.approx(cand.t_impact_pred - t_ref)
        assert cand.t_impact_est is None and cand.derivation.value == "GEOMETRY"
        # L_pred convention: positive when the reference time precedes the impact
        assert cand.t_impact_pred - t_ref > 0


def test_ca_needs_an_acceleration_source():
    hist = parabolic_history(6, with_acc=False)
    ant_state = RuleBasedAnticipator(_settings(motion_model="CA", ca_acceleration_source="state"))
    assert ant_state.predict(hist) is None and ant_state.last_decline is DeclineReason.NO_ACCELERATION
    ant_fd = RuleBasedAnticipator(_settings(motion_model="CA", ca_acceleration_source="finite_difference"))
    pred = ant_fd.predict(hist)
    assert pred is not None
    # finite difference of exact velocities reproduces the constant acceleration
    p, v, acc, _ = ant_fd.kinematic_state(tuple(hist[-3:]))
    assert acc == pytest.approx((0.0, 6.0), abs=1e-9)


# ----------------------------------------------------------------------------- probability


def test_gates_are_monotone_and_bounded():
    assert (
        speed_gate(0.0, 0.2, 1.5) == 0.0
        and speed_gate(1.5, 0.2, 1.5) == 1.0
        and speed_gate(5.0, 0.2, 1.5) == 1.0
    )
    vals = [speed_gate(s, 0.2, 1.5) for s in (0.1, 0.3, 0.6, 0.9, 1.2, 1.6)]
    assert vals == sorted(vals) and all(0 <= v <= 1 for v in vals)
    assert direction_gate(((0.0, 1.0),)) == 1.0
    assert direction_gate(((0.0, 1.0), (0.0, 1.0), (0.0, 1.0))) == pytest.approx(1.0)
    assert direction_gate(((0.0, -1.0), (0.0, 1.0))) == 0.0  # reversal counts as inconsistent
    assert direction_gate(((1.0, 0.0), (0.0, 1.0))) == pytest.approx(0.0)  # orthogonal -> no support
    assert combine_gates((0.5, 0.5, 1.0), "product") == 0.25 and combine_gates((0.5, 0.2, 1.0), "min") == 0.2
    for mode in ("product", "min"):
        prev = -1.0
        for g in (0.0, 0.25, 0.5, 0.75, 1.0):  # monotone in each gate
            cur = combine_gates((g, 0.8, 1.0), mode)
            assert cur >= prev
            prev = cur


def test_strike_probability_monotone_in_speed_and_validity():
    s = _settings(speed_prob_lo=0.2, speed_prob_hi=1.5)
    ant = RuleBasedAnticipator(s)
    probs = []
    for speed in (0.3, 0.6, 1.0, 1.4):
        hist = tuple(track(k, 100.0 + k * DT, (0.4, 0.3 + speed * k * DT), (0.0, speed)) for k in range(3))
        probs.append(ant.strike_probability(hist))
    assert probs == sorted(probs) and probs[0] < probs[-1]
    valid = tuple(track(k, 100.0 + k * DT, (0.4, 0.3), (0.0, 1.0)) for k in range(3))
    degraded = valid[:2] + (
        dataclasses.replace(valid[2], status=TrackStatus.DEGRADED, frames_since_valid=1, confidence=0.4),
    )
    assert ant.strike_probability(degraded) < ant.strike_probability(valid)
    pred = ant.predict(valid)
    assert pred.aux.strike_prob_within_H == pytest.approx(ant.strike_probability(valid))


# ----------------------------------------------------------------------------- failure cases (H)


def test_failure_cases_decline_or_produce_no_candidate():
    reg = _registry()
    engine = GeometryEngine(reg, v_min=0.1, session_id="t")
    cv = RuleBasedAnticipator(_settings(v_min_predict=0.2, a_max=30.0))
    # stopped stick -> LOW_SPEED
    still = tuple(track(k, 100.0 + k * DT, (0.4, 0.5), (0.0, 0.0)) for k in range(3))
    assert cv.predict(still) is None and cv.last_decline is DeclineReason.LOW_SPEED
    # low velocity (below v_min_predict)
    slow = tuple(track(k, 100.0 + k * DT, (0.4, 0.5 + 0.1 * k * DT), (0.0, 0.1)) for k in range(3))
    assert cv.predict(slow) is None and cv.last_decline is DeclineReason.LOW_SPEED
    # upward movement above the zone -> prediction exists, geometry yields no candidate
    up = tuple(track(k, 100.0 + k * DT, (0.4, 0.55 - 1.0 * k * DT), (0.0, -1.0)) for k in range(3))
    pred = cv.predict(up)
    assert pred is not None
    assert engine.intersect_prediction(pred, current_position=up[-1].tip_filtered, t_candidate=0.0) is None
    # lateral movement above the zone -> no candidate
    lat = tuple(track(k, 100.0 + k * DT, (0.1 + 1.0 * k * DT, 0.55), (1.0, 0.0)) for k in range(3))
    pred = cv.predict(lat)
    assert engine.intersect_prediction(pred, current_position=lat[-1].tip_filtered, t_candidate=0.0) is None
    # crossing after the prediction horizon -> no candidate (bounded horizon)
    far = tuple(track(k, 100.0 + k * DT, (0.4, 0.2 + 0.5 * k * DT), (0.0, 0.5)) for k in range(3))
    pred = RuleBasedAnticipator(_settings(K=2)).predict(far)  # horizon 2/30 s, crossing needs ~0.8 s
    assert engine.intersect_prediction(pred, current_position=far[-1].tip_filtered, t_candidate=0.0) is None
    # predicted crossing outside the zone (x far from the zone) -> no candidate
    miss = tuple(track(k, 100.0 + k * DT, (0.9, 0.5 + 2.0 * k * DT), (0.0, 2.0)) for k in range(3))
    pred = cv.predict(miss)
    assert engine.intersect_prediction(pred, current_position=miss[-1].tip_filtered, t_candidate=0.0) is None
    # high acceleration -> CA declines
    ca = RuleBasedAnticipator(_settings(motion_model="CA", a_max=30.0))
    jerk = tuple(track(k, 100.0 + k * DT, (0.4, 0.4), (0.0, 1.0), (0.0, 100.0)) for k in range(3))
    assert ca.predict(jerk) is None and ca.last_decline is DeclineReason.HIGH_ACCELERATION
    # timestamp irregularity (duplicate timestamp) -> decline
    dup = (track(0, 100.0, (0.4, 0.4), (0.0, 1.0)), track(1, 100.0, (0.4, 0.43), (0.0, 1.0)))
    assert cv.predict(dup) is None and cv.last_decline is DeclineReason.NON_MONOTONIC_TIME


def test_multiple_zones_resolve_to_earliest_crossing():
    z1 = Zone(
        "upper",
        "U",
        "HAND_TIP",
        Ellipse((0.4, 0.5), 0.2, 0.05),
        Arc((0.4, 0.5), 0.2, 0.05, 0.0, math.pi, 2 * math.pi),
        (0.0, 1.0),
        ("LEFT", "RIGHT"),
        "s",
        "default",
    )
    z2 = Zone(
        "lower",
        "L",
        "HAND_TIP",
        Ellipse((0.4, 0.8), 0.2, 0.05),
        Arc((0.4, 0.8), 0.2, 0.05, 0.0, math.pi, 2 * math.pi),
        (0.0, 1.0),
        ("LEFT", "RIGHT"),
        "s",
        "default",
    )
    engine = GeometryEngine(ZoneRegistry((z1, z2)), v_min=0.1, session_id="t")
    hist = tuple(track(k, 100.0 + k * DT, (0.4, 0.2 + 3.0 * k * DT), (0.0, 3.0)) for k in range(3))
    pred = RuleBasedAnticipator(_settings(K=12)).predict(hist)
    cand = engine.intersect_prediction(pred, current_position=hist[-1].tip_filtered, t_candidate=0.0)
    assert cand is not None and cand.zone_id == "upper"  # first valid crossing along the trajectory


def test_settings_from_config_and_validation():
    cfg = {
        "anticipator": {
            "type": "rule",
            "anticipator_id": "rule-cv-v1",
            "K": 6,
            "dt_step_s": 0.0333,
            "rule": {
                "motion_model": "CA",
                "params": {"n_min_frames": 3, "v_min_predict": 0.1, "a_max": None, "combine": "min"},
            },
            "model": None,
            "fallback": None,
        }
    }
    s = RuleSettings.from_config(cfg)
    assert s.motion_model == "CA" and s.n_min_frames == 3 and s.a_max is None and s.combine == "min"
    assert s.n_window == 3 and s.horizon_s == pytest.approx(6 * 0.0333)
    cfg["anticipator"]["rule"]["params"]["unknown"] = 1
    with pytest.raises(ValueError, match="unknown"):
        RuleSettings.from_config(cfg)
    with pytest.raises(ValueError):
        _settings(motion_model="NN")
    with pytest.raises(ValueError):
        _settings(speed_prob_lo=2.0, speed_prob_hi=1.0)
