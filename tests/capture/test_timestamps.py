"""TEST-CAPTURE-3: driver-timestamp mapping (Task 02.2) and grab-return stamping."""

from __future__ import annotations

import numpy as np
import pytest

from spacedrums.capture import DriverTimestampMapper, GrabReturnStamper


def _feed(m: DriverTimestampMapper, *, n=400, fps=30.0, offset=0.0, slope=1.0, lag=0.02,
          jitter=0.0, seed=0):
    rng = np.random.default_rng(seed)
    t_true = np.arange(n) / fps + 100.0
    for t in t_true:
        t_drv = offset + slope * t  # foreign clock reading for a frame captured at t
        t_grab = t + lag + (rng.uniform(0, jitter) if jitter else 0.0)
        m.add(t_drv, t_grab)
    return t_true


def test_same_clock_base_is_detected_as_identity():
    m = DriverTimestampMapper(warmup_n=30)
    _feed(m, lag=0.03, jitter=0.03)
    assert m.ready and m.map.mode == "IDENTITY_SAME_CLOCK"
    assert m.to_mono(123.456) == 123.456
    st = m.residual_stats()
    assert 0.03 <= st["lag_p50_s"] <= 0.06 and st["lag_min_s"] >= 0.03 - 1e-9


def test_foreign_clock_is_fitted_with_min_lag_offset():
    m = DriverTimestampMapper(warmup_n=30, min_fit_span_s=5.0)
    t_true = _feed(m, n=600, offset=-5000.0, slope=1.0 + 2e-5, lag=0.02, jitter=0.01)
    assert m.ready and m.map.mode == "LEAST_SQUARES_MIN_LAG"
    # mapped capture instants should recover t_true + min lag (0.02) within the jitter
    t_drv_last = -5000.0 + (1.0 + 2e-5) * t_true[-1]
    assert m.to_mono(t_drv_last) == pytest.approx(t_true[-1] + 0.02, abs=0.003)
    assert abs(m.map.b - (1.0 + 2e-5)) < 1e-3


def test_foreign_clock_waits_for_enough_span():
    m = DriverTimestampMapper(warmup_n=30, min_fit_span_s=5.0)
    _feed(m, n=60, offset=-5000.0)  # 2 s of data only
    assert not m.ready  # refuses to map on a too-short window


def test_non_monotone_driver_clock_disables_mapping():
    m = DriverTimestampMapper(warmup_n=5)
    m.add(1.0, 100.0)
    m.add(2.0, 101.0)
    m.add(1.5, 102.0)  # goes backwards
    for i in range(10):
        m.add(3.0 + i, 103.0 + i)
    assert m.monotone is False
    assert not m.ready and m.to_mono(5.0) is None
    assert m.residual_stats()["monotone"] is False


def test_grab_return_stamper():
    s = GrabReturnStamper(bias_s=0.004)
    assert s.to_mono(10.0) == pytest.approx(9.996)
    assert GrabReturnStamper().to_mono(1.0) == 1.0
    with pytest.raises(ValueError):
        GrabReturnStamper(bias_s=-0.1)


def test_warmup_argument_validation():
    with pytest.raises(ValueError):
        DriverTimestampMapper(warmup_n=2)
