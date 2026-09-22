"""TEST-LABEL-3 — sub-frame crossing estimators and their comparison (Phase 07, Task 07.4)."""

from __future__ import annotations

import pytest

from spacedrums.data.labels import interp
from spacedrums.data.labels.schema import Interpolation

# A constant-acceleration approach to the surface: d(t) = d0 - v0 t - a/2 t^2, zero at t*.
A, V0, D0 = 6.0, 1.0, 0.5


def _d(t: float) -> float:
    return D0 - V0 * t - 0.5 * A * t * t


T_STAR = (-V0 + (V0 * V0 + 2 * A * D0) ** 0.5) / A  # positive root of d(t) = 0


def _samples(dt: float = 1 / 30):
    times, dists = [], []
    t = 0.0
    while t <= T_STAR + 2 * dt:
        times.append(t)
        dists.append(_d(t))
        t += dt
    return times, dists


# ----------------------------------------------------------------------------- linear


def test_linear_crossing_is_exact_on_a_straight_line():
    est = interp.linear_crossing(0.0, 1.0, 1.0, -1.0)
    assert est is not None
    assert est.t_cross == pytest.approx(0.5)
    assert est.method == str(Interpolation.LINEAR)
    assert est.used_samples == 2


def test_linear_crossing_needs_a_sign_change():
    assert interp.linear_crossing(0.0, 1.0, 1.0, 2.0) is None
    assert interp.linear_crossing(0.0, -1.0, 1.0, -2.0) is None


def test_linear_crossing_rejects_non_increasing_time():
    with pytest.raises(ValueError, match="strictly increasing"):
        interp.linear_crossing(1.0, 1.0, 1.0, -1.0)


# ----------------------------------------------------------------------------- quadratic


def test_quadratic_crossing_is_exact_on_a_parabola():
    times, dists = _samples()
    bracket = interp.find_bracket(dists)
    assert bracket is not None
    est = interp.quadratic_crossing(times, dists, bracket=bracket)
    assert est is not None
    assert est.t_cross == pytest.approx(T_STAR, abs=1e-12)
    assert est.method == str(Interpolation.QUADRATIC)
    assert est.used_samples == 3


def test_quadratic_beats_linear_on_an_accelerating_approach():
    times, dists = _samples()
    bracket = interp.find_bracket(dists)
    lin = interp.linear_crossing(times[bracket[0]], dists[bracket[0]],
                                 times[bracket[1]], dists[bracket[1]])
    quad = interp.quadratic_crossing(times, dists, bracket=bracket)
    assert abs(quad.t_cross - T_STAR) < abs(lin.t_cross - T_STAR)


def test_quadratic_falls_back_to_linear_without_a_third_sample():
    est = interp.crossing_time([0.0, 1.0], [1.0, -1.0], bracket=(0, 1),
                               method=Interpolation.QUADRATIC)
    assert est.method == str(Interpolation.LINEAR)
    assert est.t_cross == pytest.approx(0.5)


def test_quadratic_rejects_a_non_consecutive_bracket():
    times, dists = _samples()
    with pytest.raises(ValueError, match="consecutive index pair"):
        interp.quadratic_crossing(times, dists, bracket=(0, 5))


def test_crossing_time_dispatches_on_the_requested_method():
    times, dists = _samples()
    bracket = interp.find_bracket(dists)
    assert interp.crossing_time(times, dists, bracket=bracket,
                                method=Interpolation.LINEAR).method == "LINEAR"
    assert interp.crossing_time(times, dists, bracket=bracket,
                                method=Interpolation.QUADRATIC).method == "QUADRATIC"


def test_crossing_time_refuses_a_bracket_without_a_sign_change():
    with pytest.raises(ValueError, match="sign change"):
        interp.crossing_time([0.0, 1.0], [1.0, 2.0], bracket=(0, 1))


def test_find_bracket_locates_the_outside_to_inside_transition():
    assert interp.find_bracket([3.0, 2.0, 1.0, -1.0, -2.0]) == (2, 3)
    assert interp.find_bracket([-1.0, -2.0]) is None


# ----------------------------------------------------------------------------- comparison


def test_comparison_picks_the_smaller_spread():
    result = interp.compare([0.01, 0.02, 0.03, 0.04], [0.0, 0.0005, 0.001, 0.0015],
                            reference="synthetic", evidence_label="SYNTHETIC")
    assert result.decision == str(Interpolation.QUADRATIC)
    assert "IQR" in result.decision_reason


def test_comparison_falls_back_to_bias_when_spreads_match():
    linear = [0.010, 0.011, 0.012, 0.013]
    quad = [0.001, 0.002, 0.003, 0.004]
    result = interp.compare(linear, quad, reference="synthetic", evidence_label="SYNTHETIC")
    assert result.decision == str(Interpolation.QUADRATIC)
    assert "bias" in result.decision_reason


def test_comparison_keeps_linear_when_neither_wins():
    xs = [0.001, 0.002, 0.003, 0.004]
    result = interp.compare(xs, list(xs), reference="synthetic", evidence_label="SYNTHETIC")
    assert result.decision == str(Interpolation.LINEAR)
    assert "keep the Phase 04 estimator" in result.decision_reason


def test_comparison_is_paired():
    with pytest.raises(ValueError, match="paired"):
        interp.compare([0.1], [0.1, 0.2], reference="r", evidence_label="SYNTHETIC")


def test_comparison_with_no_events_is_pending_not_a_number():
    result = interp.compare([], [], reference="r", evidence_label="SYNTHETIC")
    assert result.decision == "PENDING"
    assert result.bias_linear_s is None and result.iqr_quadratic_s is None


def test_comparison_carries_its_evidence_label():
    result = interp.compare([0.001], [0.002], reference="analytic", evidence_label="SYNTHETIC label")
    assert result.to_dict()["evidence_label"] == "SYNTHETIC label"
    assert result.to_dict()["reference"] == "analytic"


def test_decision_rule_is_documented_in_the_module():
    assert "IQR" in interp.DECISION_RULE
    assert "Declared before the run" in interp.DECISION_RULE
