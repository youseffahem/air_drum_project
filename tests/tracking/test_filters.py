"""TEST-TRACK-1: filters on SYNTHETIC trajectories (Phase 03, Task 03.12) — lag and RMSE per filter.

The numbers printed by ``test_filter_benchmark_table`` are the Task 03.12 synthetic evidence
(``scripts/benchmark_filters.py`` writes the same table into an experiment log).
"""

from __future__ import annotations

import numpy as np
import pytest
from conftest import DT, constant_velocity_truth, parabolic_truth

from spacedrums.tracking import FILTER_TYPES, ScalarAngleFilter, make_filter


def run_filter(ftype, truth, noise=0.004, seed=0, dt=DT, params=None):
    rng = np.random.default_rng(seed)
    f = make_filter(ftype, params or {})
    est_pos, est_vel = [], []
    for k, p in enumerate(truth):
        z = (p[0] + rng.normal(0, noise), p[1] + rng.normal(0, noise))
        if k == 0:
            out = f.initialise(z)
        else:
            f.predict(dt)
            out = f.update(z, 0.9)
        est_pos.append(out.pos)
        est_vel.append(out.vel)
    return np.array(est_pos), np.array(est_vel)


def lag_frames(est: np.ndarray, truth: np.ndarray, max_lag: int = 8) -> float:
    """Lag (frames) minimising the position RMSE between est[k] and truth[k - lag]."""
    best, best_lag = None, 0
    for lag in range(0, max_lag + 1):
        e = est[lag + 10:] - truth[10:len(truth) - lag]
        r = float(np.sqrt(np.mean(np.sum(e * e, axis=1))))
        if best is None or r < best:
            best, best_lag = r, lag
    return float(best_lag)


@pytest.mark.parametrize("ftype", FILTER_TYPES)
def test_filters_track_constant_velocity(ftype):
    truth = np.array(constant_velocity_truth(90))
    pos, vel = run_filter(ftype, truth)
    err = pos[30:] - truth[30:]
    assert np.sqrt(np.mean(np.sum(err**2, axis=1))) < 0.02
    v_true = np.array([0.3, -0.2])
    assert np.allclose(vel[60:].mean(axis=0), v_true, atol=0.08)


@pytest.mark.parametrize("ftype", FILTER_TYPES)
def test_filters_follow_parabola_with_bounded_error(ftype):
    truth = np.array(parabolic_truth(60))
    pos, _ = run_filter(ftype, truth)
    err = pos[20:] - truth[20:]
    assert np.sqrt(np.mean(np.sum(err**2, axis=1))) < 0.05


def test_ca_filter_estimates_acceleration_cv_does_not_carry_it():
    truth = parabolic_truth(90)
    ca = make_filter("kalman_ca", {})
    cv = make_filter("kalman_cv", {})
    for k, p in enumerate(truth):
        if k == 0:
            ca.initialise(p)
            cv.initialise(p)
        else:
            ca.predict(DT)
            out_ca = ca.update(p, 1.0)
            cv.predict(DT)
            out_cv = cv.update(p, 1.0)
    assert out_ca.acc is not None and abs(out_ca.acc[1] - 6.0) < 1.5
    assert out_cv.acc is None


def test_confidence_scales_the_measurement_influence():
    for ftype in FILTER_TYPES:
        hi = make_filter(ftype, {})
        lo = make_filter(ftype, {})
        for f in (hi, lo):
            f.initialise((0.5, 0.5))
            f.predict(DT)
        a = hi.update((0.6, 0.5), 1.0).pos[0]
        b = lo.update((0.6, 0.5), 0.2).pos[0]
        assert 0.5 < b < a <= 0.6, (ftype, a, b)


def test_predict_only_propagates_without_inventing_observations():
    f = make_filter("kalman_cv", {})
    truth = constant_velocity_truth(20)
    for k, p in enumerate(truth):
        if k == 0:
            f.initialise(p)
        else:
            f.predict(DT)
            f.update(p, 1.0)
    p_before = np.array(f.output().pos)
    out = f.predict(DT)  # bridge step
    assert np.allclose(np.array(out.pos) - p_before, np.array(out.vel) * DT, atol=1e-9)


def test_variable_dt_is_honoured():
    f = make_filter("alpha_beta", {"alpha": 1.0, "beta": 1.0})
    f.initialise((0.0, 0.0))
    f.predict(0.1)
    f.update((0.1, 0.0), 1.0)  # v = 1.0 unit/s
    out = f.predict(0.5)
    assert out.pos[0] == pytest.approx(0.1 + 0.5 * 1.0)


def test_effective_window_declared_and_finite():
    for ftype in FILTER_TYPES:
        n = make_filter(ftype, {}).effective_window_frames(1e-6, DT)
        assert isinstance(n, int) and 1 <= n < 500


def test_factory_and_validation():
    with pytest.raises(ValueError):
        make_filter("particle", {})
    with pytest.raises(ValueError):
        make_filter("alpha_beta", {"alpha": 0})
    with pytest.raises(ValueError):
        make_filter("kalman_cv", {"q": -1})


def test_scalar_angle_filter_wraps():
    f = ScalarAngleFilter(0.6, 0.3)
    th, om = f.step(3.1, DT)
    assert th == pytest.approx(3.1) and om == 0.0
    th, _ = f.step(-3.1, DT)  # +0.083 rad across the wrap, not -6.2
    assert abs(th) > 3.0
    th2, om2 = f.step(None, DT)  # prediction only
    assert th2 is not None and om2 is not None
    f.reset()
    assert f.step(None, DT) == (None, None)


def test_filter_benchmark_table(capsys):
    """Lag / RMSE per filter on the two synthetic trajectories (SYNTHETIC evidence, Task 03.12)."""
    rows = []
    cases = (("constant_velocity", constant_velocity_truth(120)), ("parabolic", parabolic_truth(90)))
    for name, truth in cases:
        truth = np.array(truth)
        for ftype in FILTER_TYPES:
            pos, _ = run_filter(ftype, truth, noise=0.004, seed=3)
            err = pos[15:] - truth[15:]
            rmse = float(np.sqrt(np.mean(np.sum(err**2, axis=1))))
            rows.append((name, ftype, rmse, lag_frames(pos, truth)))
    with capsys.disabled():
        print("\nSYNTHETIC filter benchmark (noise sigma 0.004 ROI-norm, dt 1/30 s):")
        for name, ftype, rmse, lag in rows:
            print(f"  {name:18s} {ftype:10s} rmse {rmse:.4f}  lag {lag:.0f} frames")
    assert all(r[2] < 0.05 for r in rows)
