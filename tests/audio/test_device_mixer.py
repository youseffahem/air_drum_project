from __future__ import annotations

import numpy as np
import pytest

from spacedrums.audio import CallbackMixer, DeviceClockMapper
from spacedrums.contracts import AudioEvent


def event(strike, target, gain=1.0):
    return AudioEvent(strike, "sample", 9.9, target, target, 0.0, gain, "profile")


def test_device_clock_mapping_offset_drift_and_residual():
    mapper = DeviceClockMapper()
    for t in np.linspace(0, 10, 101):
        mapper.update(float(t), 100.0 + 1.00002 * float(t))
    fit = mapper.fit
    assert fit.offset_s == pytest.approx(100.0, abs=1e-12)
    assert fit.slope == pytest.approx(1.00002, abs=1e-12)
    assert fit.residual_rms_s < 1e-12
    assert mapper.to_mono(12.0) == pytest.approx(112.00024)


def test_sample_accurate_offset_and_polyphony():
    mixer = CallbackMixer(sample_rate_hz=1000, channels=1)
    mixer.enqueue(event("a", 10.010, 0.5), np.ones(4, np.float32))
    mixer.enqueue(event("b", 10.012, 0.25), np.ones(3, np.float32))
    out = mixer.mix(20, 10.0)[:, 0]
    assert np.flatnonzero(out)[0] == 10
    assert out[10] == pytest.approx(0.5)
    assert out[12] == pytest.approx(0.75)
    assert out[14] == pytest.approx(0.25)
    assert mixer.stats.events_mixed == 2


def test_voice_continues_across_buffers_and_late_starts_at_zero():
    mixer = CallbackMixer(sample_rate_hz=1000, channels=1)
    mixer.enqueue(event("long", 4.998), np.arange(1, 9, dtype=np.float32) / 10)
    first = mixer.mix(4, 5.0)[:, 0]
    second = mixer.mix(4, 5.004)[:, 0]
    assert first == pytest.approx([0.1, 0.2, 0.3, 0.4])
    assert second == pytest.approx([0.5, 0.6, 0.7, 0.8])
    assert mixer.stats.events_late == 1
    mixer.note_underrun()
    assert mixer.stats.underruns == 1


def test_future_event_waits_for_own_buffer():
    mixer = CallbackMixer(sample_rate_hz=1000, channels=1)
    mixer.enqueue(event("future", 2.01), np.ones(2, np.float32))
    assert not mixer.mix(5, 2.0).any()
    assert mixer.mix(10, 2.005)[5, 0] == pytest.approx(1.0)
