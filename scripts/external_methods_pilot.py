"""Phase 18 Task 18.3: external timing-method pilot (M1 pad + microphone, M2 video, M3 software stamps).

    python scripts/external_methods_pilot.py --selftest                       # SYNTHETIC machinery check
    python scripts/external_methods_pilot.py --m1-clicks --allow-audio-device \
        [--input-device X --output-device Y]
    python scripts/external_methods_pilot.py --m1-pad --session <dir> --recording <wav>  # PERSON data
    python scripts/external_methods_pilot.py --decide [--click <json>] [--pad <json>] [--m2 <json>]

``--selftest`` runs every method's analysis on SYNTHETIC recordings with known answers:

* click pairs at known separations under a common unknown delay;
* a pad + speaker track with known latencies, including early sounds;
* event trains with offset and drift;
* a flash brightness series.

It proves the machinery and measures nothing.

``--m1-clicks`` is part (i) of the declared M1 rule, the **known-separation click validation**.
It plays pre-rendered click pairs of known sample separation (20-200 ms) through the output device
and records them with the microphone in one duplex stream, then compares the measured separation
with the scheduled one.

* It needs no person, but it plays audible clicks and records the room for about 40 s. It
  therefore needs ``--allow-audio-device``.
* The recording stays in memory: only ±15 ms excerpts around each located click and the derived
  numbers are written.
* The result is a developer-pilot MEASURED value for the microphone and position used. It is not
  M1's validity for pad strikes: part (ii), the developer pad pilot, needs a person, a practice pad
  and the pad zone. The output latency itself is not measured here: the duplex delay includes the
  input path.

``--decide`` applies ``acoustic.m1_decision`` and ``video.m2_decision`` and writes
``methods.json``, which the live lock copies.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from _p10 import write_json  # noqa: E402
from _p18 import ROOT, add_executor_args, evidence  # noqa: E402
from _p18_live import m1_session, pad_windows, read_json  # noqa: E402

from spacedrums.live_eval import acoustic, sync, video  # noqa: E402
from spacedrums.live_eval.sync import align_event_trains, detect_flashes, sync_pattern  # noqa: E402

RATE = 48000
SEPARATIONS_S = (0.020, 0.050, 0.100, 0.150, 0.200)
PAIR_SPACING_S = 0.8
N_PAIRS = 40
CLICK_GAIN = 0.3


def click_signature() -> np.ndarray:
    """The Phase 04 click (480 samples of Hann-windowed binary noise, seed 40409)."""
    rng = np.random.default_rng(40409)
    click = rng.choice(np.asarray([-1.0, 1.0]), size=480)
    return (click * np.hanning(len(click)) * CLICK_GAIN).astype(np.float32)


def click_stimulus(
    n_pairs: int = N_PAIRS, *, lead_s: float = 1.0
) -> tuple[np.ndarray, list[tuple[float, float]]]:
    click = click_signature()
    pairs, starts = [], []
    for k in range(n_pairs):
        first = lead_s + k * PAIR_SPACING_S
        second = first + SEPARATIONS_S[k % len(SEPARATIONS_S)]
        a, b = int(round(first * RATE)), int(round(second * RATE))
        pairs.append((a / RATE, b / RATE))
        starts += [a, b]
    out = np.zeros(max(starts) + len(click) + RATE, dtype=np.float32)
    for s in starts:
        out[s : s + len(click)] += click
    return out, pairs


def selftest() -> dict[str, Any]:
    rng = np.random.default_rng(18)
    click = click_signature()
    stim, pairs = click_stimulus(12)
    delay = 0.0873
    rec = np.concatenate([np.zeros(int(delay * RATE)), stim])[: len(stim)] + rng.normal(0, 0.001, len(stim))
    clicks = acoustic.click_pair_validation(rec, RATE, click, pairs)
    m = int(0.08 * RATE)
    tmpl = rng.normal(size=m) * np.exp(-np.arange(m) / (0.015 * RATE))
    x = rng.normal(0, 0.002, int(8.0 * RATE))
    truth = {0.5: 0.120, 1.5: 0.095, 2.5: -0.030, 3.5: 0.010, 4.5: 0.140, 5.5: 0.060, 6.5: -0.012}
    burst = int(0.01 * RATE)
    for pad, latency in truth.items():
        i = int(round(pad * RATE))
        x[i : i + burst] += (
            0.5 * np.exp(-np.arange(burst) / (0.0015 * RATE)) * rng.choice([-1, 1], size=burst)
        )
        j = int(round((pad + latency) * RATE))
        x[j : j + m] += 0.6 * tmpl
    sounds = acoustic.locate_template(x, tmpl, RATE, min_ncc=0.5)
    pads = acoustic.pad_onsets(x, RATE, sounds=sounds, template=tmpl)
    paired = acoustic.pair_strikes(pads, [s["t_s"] for s in sounds])
    errors = [
        p["latency_s"] - truth[min(truth, key=lambda t: abs(t - p["t_pad_s"]))] for p in paired["pairs"]
    ]
    pattern = sync_pattern(10)
    mono = [5000.0 + t for t in pattern]
    ext = [(t - 5000.0 + 12.34) / (1 + 80e-6) for t in mono] + [0.2, 17.0]
    aligned = align_event_trains(ext, mono, tolerance_s=0.01)
    fps, n = 240.0, 2400
    times = np.arange(n) / fps
    flash_true = [1.0 + 0.9 * k for k in range(10)]
    bright = 20 + rng.normal(0, 0.5, n)
    for t in flash_true:
        bright[(times >= t) & (times < t + 0.1)] += 60
    flashes = detect_flashes(bright, times)
    flash_err = [f - min(flash_true, key=lambda t: abs(t - f)) for f in flashes["onsets_s"]]
    return {
        "evidence": "SYNTHETIC machinery check (known answers); measures nothing physical",
        "click_pairs": {k: clicks[k] for k in ("n_pairs", "n_detected", "bias_s", "e95_s", "max_abs_s")},
        "pad_speaker": {
            "strikes": len(truth),
            "paired": len(paired["pairs"]),
            "excluded": paired["excluded"],
            "max_abs_error_s": float(np.max(np.abs(errors))) if errors else None,
            "early_sounds_recovered": sum(p["latency_s"] < 0 for p in paired["pairs"]),
        },
        "sync": {
            "status": aligned["status"],
            "map": aligned["map"],
            "true_offset_s": 5000.0 - 12.34,
            "true_drift": 80e-6,
        },
        "flashes": {
            "n_true": len(flash_true),
            "n_detected": len(flashes["onsets_s"]),
            "max_abs_error_s": float(np.max(np.abs(flash_err))) if flash_err else None,
            "frame_period_s": flashes["frame_period_s"],
        },
    }


def exploratory_click_diagnostic(
    recording: np.ndarray, stimulus: np.ndarray, pairs: list[tuple[float, float]], *, rate: int = RATE
) -> dict[str, Any]:
    """EXPLORATORY, post hoc: does the microphone hear the clicks, and would an envelope estimator do?

    Never changes the declared outcome, which is the template (NCC) validator above. Steps:

    * the common output + input delay comes from the envelope cross-correlation of the whole stimulus
      with the whole recording;
    * per click: the best NCC within ±5 ms of the expected time, the local SNR (window peak envelope
      over the RMS before the pair) and a half-peak envelope onset inside [−5 ms, +12 ms];
    * the pair errors are computed from those onsets.
    """
    x = np.asarray(recording, dtype=np.float64)
    lag = sync.xcorr_lag(np.asarray(stimulus, dtype=np.float64), x, rate, max_lag_s=1.0)
    delay = float(lag["lag_s"])
    if delay < 0 or lag["peak"] < 0.5:
        return {
            "label": "EXPLORATORY post-hoc diagnostic; the declared M1 part (i) outcome is the NCC validator",
            "alignment_valid": False,
            "delay_estimate_s": delay,
            "envelope_xcorr_peak": lag["peak"],
            "reason": "no click train found in the recording (envelope cross-correlation peak < 0.5 or a "
            "negative delay): per-click statistics would be measured at arbitrary times and are not reported",
        }
    ncc = acoustic.normalized_xcorr(x, click_signature())
    onsets: dict[float, float | None] = {}
    rows = []
    for first, second in pairs:
        b0, b1 = int((first + delay - 0.10) * rate), int((first + delay - 0.02) * rate)
        base = x[max(0, b0) : max(0, b1)]
        base_rms = float(np.sqrt(np.mean(base * base))) if len(base) else None
        for t in (first, second):
            c = t + delay
            j0, j1 = max(0, int((c - 0.005) * rate)), min(len(ncc), int((c + 0.005) * rate))
            i0, i1 = max(0, int((c - 0.005) * rate)), min(len(x), int((c + 0.012) * rate))
            seg = x[i0:i1]
            onset, peak = None, None
            if len(seg) > 8:
                env = sync.envelope(seg, rate, window_s=0.0005)
                peak = float(env.max())
                if peak > 0:
                    onset = (i0 + int(np.flatnonzero(env >= 0.5 * peak)[0])) / rate
            onsets[t] = onset
            rows.append(
                {
                    "t": t,
                    "ncc_max": float(ncc[j0:j1].max()) if j1 > j0 else None,
                    "snr": (peak / base_rms) if peak is not None and base_rms else None,
                }
            )
    errors = np.asarray(
        [
            (onsets[b] - onsets[a]) - (b - a)
            for a, b in pairs
            if onsets.get(a) is not None and onsets.get(b) is not None
        ],
        dtype=float,
    )
    ncc_values = [r["ncc_max"] for r in rows if r["ncc_max"] is not None]
    snr_values = [r["snr"] for r in rows if r["snr"] is not None]
    return {
        "label": "EXPLORATORY post-hoc diagnostic; the declared M1 part (i) outcome is the NCC validator",
        "alignment_valid": True,
        "delay_estimate_s": delay,
        "envelope_xcorr_peak": lag["peak"],
        "ncc_max_near_expected": {
            "median": float(np.median(ncc_values)) if ncc_values else None,
            "max": float(np.max(ncc_values)) if ncc_values else None,
            "declared_min_ncc": 0.3,
        },
        "snr_median": float(np.median(snr_values)) if snr_values else None,
        "envelope_onset_pairs": {
            "n": int(len(errors)),
            "bias_s": float(errors.mean()) if len(errors) else None,
            "e95_s": float(np.percentile(np.abs(errors), 95)) if len(errors) else None,
            "max_abs_s": float(np.abs(errors).max()) if len(errors) else None,
        },
    }


def m1_clicks(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:  # pragma: no cover - needs a device
    import sounddevice as sd

    stim, pairs = click_stimulus()
    device = (args.input_device, args.output_device)
    rec = sd.playrec(
        stim.reshape(-1, 1), samplerate=RATE, channels=1, dtype="float32", device=device, blocking=True
    )
    names = {
        "input": str(
            sd.query_devices(sd.default.device[0] if args.input_device is None else args.input_device)["name"]
        ),
        "output": str(
            sd.query_devices(sd.default.device[1] if args.output_device is None else args.output_device)[
                "name"
            ]
        ),
    }
    x = rec[:, 0].astype(np.float64)
    result = acoustic.click_pair_validation(x, RATE, click_signature(), pairs)
    located = acoustic.locate_template(x, click_signature(), RATE, min_ncc=0.3)
    half = int(0.015 * RATE)
    excerpts = (
        np.stack(
            [
                np.pad(x[max(0, int(f["t_s"] * RATE) - half) : int(f["t_s"] * RATE) + half], (0, 0))[
                    : 2 * half
                ]
                if int(f["t_s"] * RATE) - half >= 0 and int(f["t_s"] * RATE) + half <= len(x)
                else np.zeros(2 * half)
                for f in located
            ]
        )
        if located
        else np.zeros((0, 2 * half))
    )
    np.savez_compressed(
        run_dir / "click-excerpts.npz",
        excerpts=excerpts.astype(np.float32),
        t_s=np.asarray([f["t_s"] for f in located]),
        ncc=np.asarray([f["ncc"] for f in located]),
    )
    rms = float(np.sqrt(np.mean(x * x)))
    return {
        "exploratory": exploratory_click_diagnostic(x, stim, pairs),
        "evidence": "MEASURED developer pilot (device, no person): M1 part (i) known-separation "
        "click validation",
        "devices": names,
        "rate": RATE,
        "n_pairs": len(pairs),
        "separations_s": list(SEPARATIONS_S),
        "click_gain": CLICK_GAIN,
        "recording_rms": rms,
        "recording_peak": float(np.max(np.abs(x))),
        "n_clicks_located": len(located),
        "ncc_median": float(np.median([f["ncc"] for f in located])) if located else None,
        **{
            k: result[k]
            for k in (
                "n_detected",
                "n_missed",
                "bias_s",
                "e95_s",
                "max_abs_s",
                "alignment",
                "stream_to_recording_s",
            )
        },
        "errors_s": result["errors_s"],
        "privacy": "recording kept in memory; only +-15 ms excerpts around located clicks are stored",
        "declared_rule": {
            "min_pairs": acoustic.M1_CLICK_MIN_PAIRS,
            "max_abs_bias_s": acoustic.M1_CLICK_MAX_ABS_BIAS_S,
            "max_e95_s": acoustic.M1_CLICK_MAX_E95_S,
        },
    }


def m1_pad(args: argparse.Namespace) -> dict[str, Any]:
    from spacedrums.calib import load_calibrated_config

    cfg = load_calibrated_config(args.session / "config.snapshot.yaml").config
    base = read_json(args.session / "metadata.json")
    result = m1_session(args.session, cfg, args.recording, pad_windows=pad_windows(base))
    strikes = result.get("strikes", [])
    n = result.get("n_pad_onsets", 0)
    rises = [s["rise_time_s"] for s in strikes if s.get("rise_time_s") is not None]
    return {
        "evidence": "developer pad pilot (PERSON-DEPENDENT recording)",
        "session_kind": base["session_kind"],
        "n_strikes": n,
        "paired": len(strikes),
        "paired_fraction": len(strikes) / n if n else 0.0,
        "rise_time_median_s": float(np.median(rises)) if rises else None,
        "sync": result["sync"],
        "excluded": result.get("excluded", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--selftest", action="store_true")
    mode.add_argument("--m1-clicks", action="store_true")
    mode.add_argument("--m1-pad", action="store_true")
    mode.add_argument("--decide", action="store_true")
    ap.add_argument(
        "--allow-audio-device", action="store_true", help="--m1-clicks plays clicks and records the room"
    )
    ap.add_argument("--input-device", default=None)
    ap.add_argument("--output-device", default=None)
    ap.add_argument("--session", type=Path)
    ap.add_argument("--recording", type=Path)
    ap.add_argument("--click", type=Path, help="--decide: an --m1-clicks result.json")
    ap.add_argument("--pad", type=Path, help="--decide: an --m1-pad result.json")
    ap.add_argument("--m2", type=Path, help="--decide: an M2 validation json (video.m2_validation)")
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-18")
    add_executor_args(ap)
    args = ap.parse_args()
    if args.m1_clicks and not args.allow_audio_device:
        ap.error("--m1-clicks plays audible clicks and records the microphone: pass --allow-audio-device")
    if args.m1_pad and (args.session is None or args.recording is None):
        ap.error("--m1-pad needs --session and --recording")
    slug = "methods-" + (
        "selftest"
        if args.selftest
        else "m1-clicks"
        if args.m1_clicks
        else "m1-pad"
        if args.m1_pad
        else "decide"
    )
    with evidence(
        args, slug=slug, task="18.3", description=f"External-method pilot: {slug}", output=args.output
    ) as (run, _cfg):
        if args.selftest:
            result = selftest()
        elif args.m1_clicks:
            result = m1_clicks(args, run.dir)
        elif args.m1_pad:
            result = m1_pad(args)
        else:
            click = read_json(args.click) if args.click else None
            pad = read_json(args.pad) if args.pad else None
            m2 = read_json(args.m2) if args.m2 else None
            result = {
                "M1": {
                    **acoustic.m1_decision(click, pad),
                    "report": "docs/reports/phase-18-external-methods.md",
                },
                "M2": {**video.m2_decision(m2), "report": "docs/reports/phase-18-external-methods.md"},
                "M3": {
                    "status": "ESTIMATE_ONLY",
                    "output_latency_run_id": None,
                    "note": "Phase 04 output latency PENDING: M3 excludes the DAC path",
                },
                "inputs": {
                    "click": str(args.click) if args.click else None,
                    "pad": str(args.pad) if args.pad else None,
                    "m2": str(args.m2) if args.m2 else None,
                },
            }
        write_json(run.dir / "result.json", result)
        print({k: result[k] for k in list(result)[:6]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
