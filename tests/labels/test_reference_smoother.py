"""TEST-LABEL-2 — the non-causal reference smoother (Phase 07, Task 07.2).

Covers: correctness on signals with a closed-form answer, the property that makes the smoother
non-causal (a sample depends on later measurements — the one place that is allowed), the gap
policy, the parameter guards, and determinism.
"""

from __future__ import annotations

import math

import pytest
from label_helpers import parabola, ramp

from spacedrums.data.labels.smooth import (
    SIGMA_UNUSABLE,
    Measurement,
    ReferenceSmoother,
    resample,
    speed,
)

# ----------------------------------------------------------------------------- correctness


@pytest.mark.parametrize("method", ["rts-kalman-cv-v1", "rts-kalman-ca-v1", "savgol-centred-v1"])
def test_smoother_recovers_a_constant_velocity_ramp(method):
    sm = ReferenceSmoother(method).smooth(ramp(vy=1.0))
    interior = sm.samples[5:-5]
    assert interior
    for s in interior:
        expected_y = 0.2 + 1.0 * (s.t - 100.0)
        assert s.p[1] == pytest.approx(expected_y, abs=2e-3)
        assert s.v[1] == pytest.approx(1.0, abs=5e-2)


@pytest.mark.parametrize("method", ["rts-kalman-ca-v1", "savgol-centred-v1"])
def test_smoother_recovers_a_parabola_interior(method):
    """CA and a quadratic Savitzky-Golay represent a constant-acceleration path exactly."""
    sm = ReferenceSmoother(method).smooth(parabola(a=4.0))
    for s in sm.samples[6:-6]:
        expected = 0.3 + 0.5 * 4.0 * ((s.t - 100.0) - 0.6) ** 2
        assert s.p[1] == pytest.approx(expected, abs=5e-3)


def test_velocity_sign_flips_at_the_minimum_of_a_parabola():
    """y = 0.3 + a/2 (t - 0.6)^2 falls until t = 0.6 and rises after, so v_y flips sign there."""
    sm = ReferenceSmoother("rts-kalman-ca-v1").smooth(parabola(a=4.0, t_min=0.6))
    before = [s for s in sm.samples if 100.3 < s.t < 100.5]
    after = [s for s in sm.samples if 100.7 < s.t < 100.9]
    assert before and after
    assert all(s.v[1] < 0 for s in before)
    assert all(s.v[1] > 0 for s in after)


def test_speed_helper_matches_the_euclidean_norm():
    s = ReferenceSmoother().smooth(ramp()).samples[10]
    assert speed(s) == pytest.approx(math.hypot(*s.v))


# ----------------------------------------------------------------------------- non-causality


def test_a_reference_sample_depends_on_later_measurements():
    """This is the defining property of the reference trajectory and the reason it may never be an
    input to a causal component: changing a LATER measurement changes an EARLIER sample."""
    base = ramp()
    mid = len(base) // 2
    perturbed = list(base)
    perturbed[mid + 2] = Measurement(base[mid + 2].frame_id, base[mid + 2].t, (0.9, 0.9), 0.9)
    a = ReferenceSmoother().smooth(base).samples
    b = ReferenceSmoother().smooth(perturbed).samples
    assert a[mid].frame_id == b[mid].frame_id
    assert a[mid].p != b[mid].p, "the backward pass must propagate future information"
    assert a[:mid - 4] != b[:mid - 4], "the influence reaches further back than one sample"


def test_truncating_the_future_changes_the_reference_but_not_the_first_sample_identity():
    base = ramp()
    full = ReferenceSmoother().smooth(base).samples
    cut = ReferenceSmoother().smooth(base[:20]).samples
    assert full[0].frame_id == cut[0].frame_id
    assert any(f.p != c.p for f, c in zip(full[:20], cut, strict=False))


# ----------------------------------------------------------------------------- gap policy


def test_a_short_gap_is_bridged_and_flagged_interpolated():
    meas = ramp(n=30)
    meas[10] = Measurement(10, meas[10].t, None, 0.0)
    meas[11] = Measurement(11, meas[11].t, None, 0.0)
    out = ReferenceSmoother(max_gap_s=0.2).smooth(meas)
    bridged = [s for s in out.samples if s.interpolated]
    assert {s.frame_id for s in bridged} == {10, 11}
    assert out.loss_intervals == ()


def test_a_long_gap_becomes_a_loss_interval_and_carries_no_samples():
    meas = ramp(n=40)
    for k in range(10, 22):  # 12 frames at 30 FPS = 0.4 s > max_gap_s
        meas[k] = Measurement(k, meas[k].t, None, 0.0)
    out = ReferenceSmoother(max_gap_s=0.2).smooth(meas)
    assert len(out.loss_intervals) == 1
    li = out.loss_intervals[0]
    assert (li.first_frame_id, li.last_frame_id) == (10, 21)
    assert not any(10 <= s.frame_id <= 21 for s in out.samples)


def test_a_trailing_gap_is_reported_as_a_loss_interval():
    meas = ramp(n=30)
    for k in range(20, 30):
        meas[k] = Measurement(k, meas[k].t, None, 0.0)
    out = ReferenceSmoother(max_gap_s=0.2).smooth(meas)
    assert out.loss_intervals and out.loss_intervals[-1].last_frame_id == 29


def test_a_session_without_any_measurement_yields_no_samples():
    meas = [Measurement(k, 100.0 + k / 30, None, 0.0) for k in range(10)]
    out = ReferenceSmoother().smooth(meas)
    assert out.samples == ()
    assert len(out.loss_intervals) == 1


# ----------------------------------------------------------------------------- guards


def test_measurements_must_be_strictly_increasing_in_time():
    meas = ramp(n=5)
    meas[3] = Measurement(3, meas[2].t, (0.5, 0.5), 0.9)
    with pytest.raises(ValueError, match="strictly increasing"):
        ReferenceSmoother().smooth(meas)


@pytest.mark.parametrize(
    "method, params, match",
    [
        ("savgol-centred-v1", {"window": 4.0}, "odd integer"),
        ("savgol-centred-v1", {"window": 5.0, "polyorder": 5.0}, "polyorder"),
        ("rts-kalman-cv-v1", {"not_a_param": 1.0}, "unknown smoother parameters"),
    ],
)
def test_smoother_rejects_impossible_parameters(method, params, match):
    with pytest.raises(ValueError, match=match):
        ReferenceSmoother(method, params=params)


def test_max_gap_must_be_positive():
    with pytest.raises(ValueError, match="max_gap_s"):
        ReferenceSmoother(max_gap_s=0.0)


# ----------------------------------------------------------------------------- provenance


def test_smoother_hash_covers_method_parameters_and_gap_bound():
    a = ReferenceSmoother("rts-kalman-cv-v1", params={"q": 200.0})
    b = ReferenceSmoother("rts-kalman-cv-v1", params={"q": 201.0})
    c = ReferenceSmoother("rts-kalman-cv-v1", params={"q": 200.0}, max_gap_s=0.3)
    assert a.smoother_hash == ReferenceSmoother("rts-kalman-cv-v1", params={"q": 200.0}).smoother_hash
    assert len({a.smoother_hash, b.smoother_hash, c.smoother_hash}) == 3


def test_smoothing_is_deterministic():
    meas = ramp()
    a = ReferenceSmoother().smooth(meas)
    b = ReferenceSmoother().smooth(meas)
    assert [s.to_dict() for s in a.samples] == [s.to_dict() for s in b.samples]


# ----------------------------------------------------------------------------- quality


def test_quality_is_bounded_and_falls_with_uncertainty():
    for s in ReferenceSmoother().smooth(ramp()).samples:
        assert 0.0 <= s.quality <= 1.0
    noisy = ReferenceSmoother("rts-kalman-cv-v1", params={"r_base": 1e-2}).smooth(ramp())
    clean = ReferenceSmoother("rts-kalman-cv-v1", params={"r_base": 1e-6}).smooth(ramp())
    assert min(s.quality for s in noisy.samples) < min(s.quality for s in clean.samples)


def test_sigma_unusable_is_the_documented_zero_point():
    assert SIGMA_UNUSABLE == pytest.approx(0.05)


# ----------------------------------------------------------------------------- resampling


def test_resample_interpolates_inside_the_range_and_refuses_outside():
    samples = ReferenceSmoother().smooth(ramp()).samples
    mid_t = (samples[5].t + samples[6].t) / 2
    got = resample(samples, mid_t)
    assert got is not None
    assert min(samples[5].p[1], samples[6].p[1]) <= got.p[1] <= max(samples[5].p[1], samples[6].p[1])
    assert resample(samples, samples[0].t - 1.0) is None
    assert resample(samples, samples[-1].t + 1.0) is None
