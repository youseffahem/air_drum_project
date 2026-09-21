"""TEST-DATA-4: microphone-capture machinery (Task 06.6) on SYNTHETIC signals — t_mono mapping of
device blocks, WAV round trip, onset detection, sync residuals, determinism. No microphone is used;
nothing here measures sync accuracy (pilot PENDING)."""

from __future__ import annotations

import numpy as np

from spacedrums.data.audio_capture import (
    AudioCapture,
    detect_onsets,
    onsets_on_t_mono,
    read_wav,
    sync_check,
    synthetic_clicks,
    write_wav,
)

SR = 16000


def test_on_block_maps_device_time_onto_t_mono_and_writes_a_sidecar(tmp_path):
    cap = AudioCapture(sample_rate_hz=SR, channels=1, device="SYNTHETIC")
    assert cap.t_mono_first_sample is None and cap.clock_fit() is None
    x = synthetic_clicks(SR, 1.0, [0.5])
    block = 400
    offset, lag = (
        -2000.0,
        0.008,
    )  # device clock = t_mono - 2000; callback runs 8 ms after the block's ADC time
    for i in range(0, len(x), block):
        t_mono_block = 300.0 + i / SR
        cap.on_block(
            x[i : i + block],
            adc_time=t_mono_block + offset,
            current_time=t_mono_block + offset + lag,
            t_mono_now=t_mono_block + lag,
        )
    assert abs(cap.t_mono_first_sample - 300.0) < 1e-6
    fit = cap.clock_fit()
    assert (
        abs(fit["slope"] - 1.0) < 1e-9
        and fit["residual_rms_s"] < 1e-9
        and fit["n"] == len(range(0, len(x), block))
    )
    info = cap.write(tmp_path)
    assert (tmp_path / "audio_track.wav").exists() and info["n_samples"] == len(x)
    assert info["sha256"].startswith("sha256:") and info["dtype"] == "pcm16" and info["device"] == "SYNTHETIC"
    y, sr = read_wav(tmp_path / "audio_track.wav")
    assert sr == SR and y.shape == (len(x), 1)
    assert np.max(np.abs(y[:, 0] - x)) < 1.0 / 16384  # within one PCM-16 quantisation step


def test_wav_round_trip_stereo(tmp_path):
    x = np.stack([np.linspace(-0.5, 0.5, 100), np.zeros(100)], axis=1).astype(np.float32)
    write_wav(tmp_path / "s.wav", x, 8000)
    y, sr = read_wav(tmp_path / "s.wav")
    assert sr == 8000 and y.shape == (100, 2) and np.max(np.abs(y - x)) < 1e-3


def test_onsets_found_at_click_times_within_frame_resolution():
    clicks = [0.30, 1.10, 2.05]
    x = synthetic_clicks(SR, 3.0, clicks, seed=1)
    got = detect_onsets(x, SR)
    assert len(got) == len(clicks)
    assert all(abs(g - c) <= 0.006 for g, c in zip(got, clicks, strict=True))
    assert detect_onsets(np.zeros(SR), SR) == []
    assert detect_onsets(x[: SR // 2], SR) == [detect_onsets(x, SR)[0]]  # prefix gives the first onset only
    assert onsets_on_t_mono(x, SR, 1000.0) == [1000.0 + g for g in got]


def test_sync_check_residuals_and_unmatched():
    markers = [10.0, 12.0, 14.0]
    onsets = [10.02, 12.03, 20.0]  # third marker has no onset within the window; extra onset at 20
    res = sync_check(markers, onsets, window_s=0.5)
    assert res.n_matched == 2 and res.unmatched_markers == (2,)
    assert np.allclose(res.residuals_s, [0.02, 0.03])
    assert abs(res.residual_mean_s - 0.025) < 1e-12 and abs(res.residual_max_abs_s - 0.03) < 1e-12
    d = res.to_dict()
    assert d["n_markers"] == 3 and d["n_onsets"] == 3 and d["window_s"] == 0.5
    empty = sync_check([], [])
    assert empty.residual_rms_s is None and empty.to_dict()["residuals_s"] == []


def test_synthetic_pipeline_is_deterministic():
    a = synthetic_clicks(SR, 2.0, [0.4, 1.4], seed=5)
    b = synthetic_clicks(SR, 2.0, [0.4, 1.4], seed=5)
    assert np.array_equal(a, b)
    assert detect_onsets(a, SR) == detect_onsets(b, SR)
    assert not np.array_equal(a, synthetic_clicks(SR, 2.0, [0.4, 1.4], seed=6))
