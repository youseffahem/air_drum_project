"""Phase 18 sync tooling and timing methods on SYNTHETIC recordings (TEST-P18-SYNC, TEST-P18-M1/M2/M3).

Every signal here is generated with a known answer; the tests prove the machinery, not a microphone,
a camera or an output latency.
"""

from __future__ import annotations

import numpy as np
import pytest

from spacedrums.live_eval import acoustic, software, sync, video

RATE = 48000


def _template(rng, seconds=0.08):
    m = int(seconds * RATE)
    return rng.normal(size=m) * np.exp(-np.arange(m) / (0.015 * RATE))


def _pad_and_sound(truth, rng, *, gain=0.6, pad=0.5, duration=8.0):
    tmpl = _template(rng)
    x = rng.normal(0, 0.002, int(duration * RATE))
    burst = int(0.01 * RATE)
    for t_pad, latency in truth:
        i = int(round(t_pad * RATE))
        x[i : i + burst] += (
            pad * np.exp(-np.arange(burst) / (0.0015 * RATE)) * rng.choice([-1, 1], size=burst)
        )
        j = int(round((t_pad + latency) * RATE))
        x[j : j + len(tmpl)] += gain * tmpl
    return x, tmpl


def test_event_train_alignment_recovers_offset_and_drift_and_ignores_extra_events():
    pattern = sync.sync_pattern(9)
    mono = [700.0 + t for t in pattern]
    ext = [(t - 700.0 + 3.21) / (1 + 60e-6) for t in mono] + [0.05, 25.0]
    r = sync.align_event_trains(ext, mono, tolerance_s=0.01)
    assert r["status"] == sync.SYNC_OK and len(r["matches"]) == 9 and r["unmatched_markers"] == []
    assert r["map"]["drift"] == pytest.approx(60e-6, abs=1e-9)
    assert r["map"]["residual_rms_s"] < 1e-9
    fit = sync.ClockMap(**r["map"])
    assert fit.to_mono(ext[0]) == pytest.approx(mono[0], abs=1e-9)


def test_alignment_fails_explicitly_without_enough_or_with_ambiguous_markers():
    assert sync.align_event_trains([1.0, 2.0], [5.0, 6.0])["status"] == sync.SYNC_FAILED
    periodic = [float(k) for k in range(6)]  # equally spaced: every shift explains the train
    r = sync.align_event_trains(
        periodic[:5], [10.0 + t for t in periodic[:5]], tolerance_s=0.01, min_matches=3
    )
    assert r["status"] == sync.SYNC_OK  # the full overlap is the unique best count
    r = sync.align_event_trains([0.0, 1.0, 2.0], [0.5, 1.5, 2.5, 3.5], tolerance_s=0.01, min_matches=4)
    assert r["status"] == sync.SYNC_FAILED and "fewer than 4" in r["reason"]


def test_flash_detection_is_frame_quantised_and_reports_its_resolution():
    rng = np.random.default_rng(3)
    fps, n = 240.0, 2400
    t = np.arange(n) / fps
    true = [1.0 + 0.9 * k for k in range(8)]
    b = 20 + rng.normal(0, 0.5, n)
    for f in true:
        b[(t >= f) & (t < f + 0.1)] += 50
    found = sync.detect_flashes(b, t)
    assert len(found["onsets_s"]) == len(true)
    assert (
        max(abs(a - e) for a, e in zip(found["onsets_s"], true, strict=True)) <= found["resolution_s"] + 1e-9
    )
    assert found["frame_period_s"] == pytest.approx(1 / fps)


def test_envelope_cross_correlation_finds_a_sub_millisecond_lag():
    rng = np.random.default_rng(4)
    a = np.zeros(RATE)
    a[10000:10480] = rng.normal(size=480)
    b = np.roll(a, 173)
    assert sync.xcorr_lag(a, b, RATE, max_lag_s=0.05)["lag_s"] == pytest.approx(
        173 / RATE, abs=0.3 / RATE * 10
    )


def test_m1_recovers_known_latencies_including_early_sound():
    rng = np.random.default_rng(5)
    truth = [(0.5, 0.120), (1.5, 0.095), (2.5, -0.030), (3.5, 0.010), (4.5, 0.140), (5.5, -0.012)]
    x, tmpl = _pad_and_sound(truth, rng)
    sounds = acoustic.locate_template(x, tmpl, RATE, min_ncc=0.5)
    assert len(sounds) == len(truth)
    pads = acoustic.pad_onsets(x, RATE, sounds=sounds, template=tmpl)
    paired = acoustic.pair_strikes(pads, [s["t_s"] for s in sounds])
    got = sorted(p["latency_s"] for p in paired["pairs"])
    assert got == pytest.approx(sorted(latency for _, latency in truth), abs=0.0015)
    assert sum(latency < 0 for latency in got) == 2 and not paired["excluded"]


def test_m1_excludes_ambiguous_strikes_instead_of_guessing():
    paired = acoustic.pair_strikes([1.00, 1.10, 3.00], [1.20, 3.10, 5.00])
    reasons = {e["t_sound_s"]: e["reason"] for e in paired["excluded"]}
    assert "several pad onsets" in reasons[1.20]
    assert "no pad onset" in reasons[5.00]
    assert [p["t_sound_s"] for p in paired["pairs"]] == [3.10]


def test_click_pair_validation_cancels_the_common_delay():
    rng = np.random.default_rng(6)
    click = rng.choice([-1.0, 1.0], size=480) * np.hanning(480) * 0.3
    pairs = [(0.5 + 0.8 * k, 0.5 + 0.8 * k + (0.02, 0.05, 0.1, 0.15, 0.2)[k % 5]) for k in range(10)]
    rec = rng.normal(0, 0.001, int(9.5 * RATE))
    for a, b in pairs:
        for t in (a, b):
            i = int(round((t + 0.1234) * RATE))
            rec[i : i + 480] += click
    v = acoustic.click_pair_validation(rec, RATE, click, pairs)
    assert v["n_detected"] == 10 and abs(v["bias_s"]) < 1 / RATE and v["e95_s"] <= 1 / RATE
    assert v["stream_to_recording_s"]["median"] == pytest.approx(0.1234, abs=1 / RATE)


def test_m1_decision_applies_the_declared_rule_and_names_missing_parts():
    good = {"n_detected": 40, "bias_s": 0.0002, "e95_s": 0.0008}
    assert acoustic.m1_decision(None, None)["status"] == "PENDING"
    pending = acoustic.m1_decision(good, None)
    assert pending["status"] == "PENDING" and pending["click_part"] == "PASS"
    assert acoustic.m1_decision({**good, "e95_s": 0.01}, None)["status"] == "NO_GO"
    go = acoustic.m1_decision(good, {"n_strikes": 40, "paired_fraction": 0.95, "rise_time_median_s": 0.002})
    assert go["status"] == "GO" and go["u_s"] == pytest.approx(np.hypot(0.0008, 0.002))
    assert (
        acoustic.m1_decision(good, {"n_strikes": 40, "paired_fraction": 0.5, "rise_time_median_s": 0.002})[
            "status"
        ]
        == "NO_GO"
    )


def test_m2_rule_needs_high_frame_rate_and_an_identifiable_bias():
    v = video.m2_validation(
        [1.0 + k for k in range(30)], [100.0 + k for k in range(30)], frame_period_s=1 / 240
    )
    assert v["detected_fraction"] == 1.0 and v["bias_s"] is None
    assert video.m2_decision(v)["status"] == "PENDING"
    with_ref = {**v, "bias_s": 0.001}
    assert video.m2_decision(with_ref)["status"] == "GO"
    assert video.m2_decision({**with_ref, "frame_period_s": 1 / 30})["status"] == "NO_GO"
    lat = video.m2_latency([1.0, 2.0], [1.1, 1.95], frame_period_s=1 / 240)
    assert [round(p["latency_s"], 3) for p in lat["pairs"]] == [0.1, -0.05]


def _strike(arm, t_capture, *, shadow=False, **stamps):
    base = {"kind": "STRIKE", "arm": arm, "t_capture": t_capture, "strike_id": f"s-{arm}-{t_capture}"}
    return {**base, **stamps, "shadow": shadow}


def test_m3_decomposes_only_single_clock_records_and_labels_the_dac_path():
    good = _strike(
        "A",
        10.0,
        t_frame_available=10.03,
        t_tracking_done=10.05,
        t_inference_done=10.051,
        t_commit=10.052,
        t_audio_scheduled=10.053,
    )
    replay = _strike("B", 10.0, t_frame_available=10.03, t_tracking_done=5000.0)
    d = software.decomposition([good, replay, {"kind": "FRAME", "t_capture": 9.0, "t_frame_available": 9.02}])
    assert d["rejected_mixed_clock"]["STRIKE"] == 1
    assert d["by_arm"]["A"]["camera_capture"]["p50_s"] == pytest.approx(0.03)
    assert d["by_arm"]["A"]["audio_output"]["n"] == 0 and d["frames"]["camera_capture"]["n"] == 1
    committed = [
        {"strike_id": "a1", "arm": "A", "t_impact_est": 9.99, "shadow": False},
        {"strike_id": "c1", "arm": "C-GRU", "shadow": False},
        {"strike_id": "b1", "arm": "B", "shadow": True},
    ]
    audio = [
        {"strike_id": "a1", "t_target_play": 10.06, "t_audio_out_est": None},
        {"strike_id": "c1", "t_target_play": 11.00, "t_audio_out_est": None},
    ]
    est = software.strike_estimates(
        committed, audio, output_latency_accepted=False, impact_reference={"c1": 11.02}
    )
    by_id = {r["strike_id"]: r for r in est["strikes"]}
    assert by_id["a1"]["estimate_s"] == pytest.approx(0.07) and by_id["a1"]["quantity"] == "L_sys"
    assert by_id["c1"]["estimate_s"] == pytest.approx(-0.02) and "EXCLUDED" in by_id["c1"]["dac_path"]
    assert est["sound_before_reference_fraction"]["C-GRU"] == 1.0 and "b1" not in by_id
