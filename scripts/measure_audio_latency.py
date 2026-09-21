"""Measure synchronized output-to-loopback latency, or self-test the machinery synthetically.

The live method uses an output device and an *electrical/digital loopback input* (for HW-01,
Realtek Stereo Mix). No microphone or participant recording is requested. Only per-click detected
latencies are retained; the captured audio buffer is not written to disk. The result is the
output-to-loopback capture-path latency, which includes the loopback input path and is not physical
acoustic onset. PortAudio's advertised latency is logged only as metadata and never as a result.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from _runlog import RunLog  # noqa: E402

from spacedrums.audio import DeviceClockMapper  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.timing import now  # noqa: E402

RATE = 48_000


def click_signature() -> np.ndarray:
    rng = np.random.default_rng(40409)
    click = rng.choice(np.asarray([-1.0, 1.0]), size=480).astype(np.float32)
    click *= np.hanning(len(click)).astype(np.float32) * 0.30
    return click


def stimulus(trials: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    click = click_signature()
    starts = (0.5 * RATE + np.arange(trials) * 0.20 * RATE).astype(np.int64)
    out = np.zeros((int(starts[-1] + 0.4 * RATE), 2), np.float32)
    for start in starts:
        out[start : start + len(click), :] = click[:, None]
    return out, starts, click


def detect_latencies(
    recorded: np.ndarray, starts: np.ndarray, click: np.ndarray, *, max_latency_s: float = 0.15
) -> list[float]:
    mono = np.mean(recorded, axis=1)
    latencies = []
    width = int(max_latency_s * RATE)
    for expected in starts:
        segment = mono[int(expected) : int(expected) + width + len(click)]
        if len(segment) < len(click):
            continue
        correlation = np.correlate(segment, click, mode="valid")
        peak = int(np.argmax(np.abs(correlation)))
        # Reject a window that contains no response distinguishable from its RMS background.
        score = abs(float(correlation[peak]))
        floor = float(np.std(segment) * np.linalg.norm(click))
        if score <= max(1e-8, 1.5 * floor):
            continue
        latencies.append(peak / RATE)
    return latencies


def live_capture(
    stim: np.ndarray, *, input_device: int, output_device: int, buffer_frames: int
) -> tuple[np.ndarray, int, dict]:
    import sounddevice as sd

    captured = np.zeros_like(stim)
    cursor = 0
    xruns = 0
    mapper = DeviceClockMapper(max_samples=4096)

    def callback(indata, outdata, frames, _time_info, status):
        nonlocal cursor, xruns
        mapper.update(float(_time_info.currentTime), now())
        if status:
            xruns += 1
        n = min(frames, len(stim) - cursor)
        outdata.fill(0)
        if n:
            outdata[:n] = stim[cursor : cursor + n]
            captured[cursor : cursor + n] = indata[:n]
        cursor += n
        if cursor >= len(stim):
            raise sd.CallbackStop

    with sd.Stream(
        device=(input_device, output_device),
        samplerate=RATE,
        blocksize=buffer_frames,
        channels=(2, 2),
        dtype="float32",
        callback=callback,
    ) as stream:
        while stream.active:
            sd.sleep(50)
        metadata = {
            "reported_input_latency_s": float(stream.latency[0]),
            "reported_output_latency_s": float(stream.latency[1]),
            "clock_mapping": {
                "offset_s": mapper.fit.offset_s,
                "slope": mapper.fit.slope,
                "residual_rms_s": mapper.fit.residual_rms_s,
                "n": mapper.fit.n,
            },
        }
    return captured, xruns, metadata


def percentile(values: list[float], q: float) -> float:
    return float(np.quantile(np.asarray(values), q, method="linear"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiments-dir", type=Path, default=ROOT / "experiments")
    parser.add_argument("--buffer-frames", nargs="+", type=int, default=[64, 128, 256, 512])
    parser.add_argument("--trials", type=int, default=35)
    parser.add_argument("--input-device", type=int, default=10)
    parser.add_argument("--output-device", type=int, default=13)
    parser.add_argument(
        "--method", choices=("digital-loopback", "microphone"), default="digital-loopback"
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Self-test with an injected 17 ms delay; never output-latency evidence",
    )
    args = parser.parse_args()
    if args.trials < 30 and not args.synthetic:
        parser.error("live measurement requires at least 30 trials per buffer size")
    config = load_config(ROOT / "configs/example.candidate.yaml", ROOT / "configs/zones/mvp4.candidate.yaml")
    stim, starts, click = stimulus(args.trials)
    for buffer_frames in args.buffer_frames:
        mode_slug = "synth" if args.synthetic else "mic" if args.method == "microphone" else "loop"
        device_label = (
            "SYNTHETIC injected delay"
            if args.synthetic
            else f"{args.method} input {args.input_device} <- output {args.output_device}"
        )
        with RunLog(
            phase="04",
            task="04.9",
            slug=f"p04-audio-{mode_slug}-b{buffer_frames}",
            description=(
                "SYNTHETIC audio-latency detector self-test"
                if args.synthetic
                else f"HW-01 synchronized {args.method} click-onset measurement"
            ),
            config=config,
            experiments_dir=args.experiments_dir,
            audio_device=device_label,
        ) as run:
            if args.synthetic:
                delay = round(0.017 * RATE)
                captured = np.zeros_like(stim)
                captured[delay:] = stim[:-delay]
                xruns, metadata = 0, {"injected_delay_s": delay / RATE}
            else:
                captured, xruns, metadata = live_capture(
                    stim,
                    input_device=args.input_device,
                    output_device=args.output_device,
                    buffer_frames=buffer_frames,
                )
            values = detect_latencies(captured, starts, click)
            spread_s = percentile(values, 0.9) - percentile(values, 0.1) if values else None
            complete = len(values) == args.trials and spread_s is not None and spread_s <= 0.020
            evidence_label = (
                "SYNTHETIC"
                if args.synthetic
                else "MEASURED"
                if args.method == "microphone" and complete
                else "MEASURED_DIAGNOSTIC"
                if complete
                else "PENDING"
            )
            output_status = (
                "MEASURED_WITH_MICROPHONE_PATH_LIMITATION"
                if evidence_label == "MEASURED"
                else "PENDING"
            )
            trials_doc = {
                "evidence_label": evidence_label,
                "output_latency_status": output_status,
                "method": args.method,
                "buffer_frames": buffer_frames,
                "sample_rate_hz": RATE,
                "requested_trials": args.trials,
                "detected_trials": len(values),
                "detector_consistent": complete,
                "p90_minus_p10_s": spread_s,
                "latencies_s": values,
                "xruns": xruns,
                "metadata": metadata,
            }
            run.write_json_artefact("latency_trials.json", trials_doc, "table")
            metrics = {
                **trials_doc,
                "status": output_status,
                "median_s": statistics.median(values) if values else None,
                "p90_s": percentile(values, 0.9) if values else None,
                "limitation": (
                    "synthetic machinery check only"
                    if args.synthetic
                    else "includes microphone input path and acoustic propagation"
                    if args.method == "microphone"
                    else "Stereo Mix tap location is upstream/unknown; not DAC or acoustic onset"
                ),
            }
            run.finish(metrics, status="COMPLETED" if complete else "FAILED")
            print(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
