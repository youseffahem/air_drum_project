"""M2: impact-to-sound latency from a high-frame-rate video (pre-registration §8).

A phone camera at its native high frame rate films the stick, the pad or the virtual surface, and
a visible sound marker: an LED driven by the audio output, or a screen flash driven at
``t_audio_out``. Both events are quantised to video frames:

* the impact frame is annotated by the operator;
* the marker frame comes from :func:`spacedrums.live_eval.sync.detect_flashes` on the per-frame
  brightness of a region of interest.

The per-strike latency is therefore known to about one frame period. The declared uncertainty is
``U_M2 = frame period + |bias|``.

The method is **Pending Benchmark** until the developer pilot passes :func:`m2_decision`. The
functions here read a video file and do arithmetic; they never assume a frame rate. The period is
measured from the container timestamps and reported.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from spacedrums.live_eval.acoustic import pair_strikes
from spacedrums.live_eval.sync import align_event_trains

M2_MAX_FRAME_PERIOD_S = 0.005
M2_MIN_EVENTS = 30
M2_MIN_DETECTED_FRACTION = 0.95


def brightness_series(
    video_path: str | Path,
    *,
    roi: tuple[int, int, int, int] | None = None,
    max_frames: int | None = None,
) -> dict[str, Any]:
    """Mean grey level per frame (inside ``roi`` = x, y, w, h) and container timestamps (s)."""
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise OSError(f"cannot open video {video_path}")
    times, values = [], []
    try:
        while max_frames is None or len(values) < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            times.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            if roi is not None:
                x, y, w, h = roi
                grey = grey[y : y + h, x : x + w]
            values.append(float(grey.mean()))
        advertised = float(cap.get(cv2.CAP_PROP_FPS))
    finally:
        cap.release()
    t = np.asarray(times, dtype=float)
    periods = np.diff(t) if len(t) > 1 else np.asarray([])
    return {
        "times_s": t.tolist(),
        "brightness": values,
        "n_frames": len(values),
        "frame_period_s": float(np.median(periods)) if len(periods) else None,
        "frame_period_p95_s": float(np.percentile(periods, 95)) if len(periods) else None,
        "advertised_fps": advertised,
        "note": "frame period measured from container timestamps; the advertised FPS is metadata only",
    }


def read_impact_annotations(path: str | Path) -> list[float]:
    """Operator annotations: a CSV with a ``time_s`` column (container time of the impact frame)."""
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or "time_s" not in rows[0]:
        raise ValueError("annotation CSV needs a time_s column")
    return sorted(float(r["time_s"]) for r in rows if r["time_s"].strip())


def m2_latency(
    impact_times: Sequence[float],
    sound_marker_times: Sequence[float],
    *,
    frame_period_s: float,
    max_sound_after_s: float = 0.35,
    max_sound_before_s: float = 0.25,
) -> dict[str, Any]:
    """Pair annotated impacts with sound-marker frames; latency = marker - impact (± one period)."""
    if frame_period_s <= 0:
        raise ValueError("frame period must be positive")
    paired = pair_strikes(
        impact_times,
        sound_marker_times,
        max_sound_after_s=max_sound_after_s,
        max_sound_before_s=max_sound_before_s,
    )
    for p in paired["pairs"]:
        p["uncertainty_s"] = frame_period_s
    return {**paired, "frame_period_s": frame_period_s}


def m2_validation(
    detected_ext_times: Sequence[float],
    driven_mono_times: Sequence[float],
    *,
    frame_period_s: float,
    known_bias_reference: Sequence[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Pilot statistics: detection fraction of driven marker events, alignment residual and bias.

    ``known_bias_reference`` (optional) lists pairs ``(t_ext_detected, t_ext_true)`` from an
    independent reference, for example an LED wired to the audio output and filmed together with a
    reference light. Without it, the bias is not identifiable from the video alone; the result says
    so and the decision stays PENDING.
    """
    aligned = align_event_trains(
        detected_ext_times, driven_mono_times, tolerance_s=max(2 * frame_period_s, 0.01)
    )
    n_driven = len(driven_mono_times)
    n_matched = len(aligned["matches"])
    bias = None
    if known_bias_reference:
        diffs = np.asarray([d - t for d, t in known_bias_reference], dtype=float)
        bias = float(diffs.mean())
    return {
        "n_driven": n_driven,
        "n_detected": n_matched,
        "detected_fraction": n_matched / n_driven if n_driven else 0.0,
        "alignment": {k: aligned[k] for k in ("status", "reason", "map")},
        "frame_period_s": frame_period_s,
        "bias_s": bias,
        "bias_note": None if bias is not None else "no independent reference: bias not identifiable",
    }


def m2_decision(validation: dict[str, Any] | None) -> dict[str, Any]:
    """The declared M2 GO rule (pre-registration §8)."""
    if validation is None:
        return {"status": "PENDING", "u_s": None, "reasons": ["M2 pilot not run (equipment / person)"]}
    reasons = []
    period = validation["frame_period_s"]
    if period is None or period > M2_MAX_FRAME_PERIOD_S:
        reasons.append(f"frame period {period} s exceeds {M2_MAX_FRAME_PERIOD_S} s (needs >= 200 FPS)")
    if validation["n_driven"] < M2_MIN_EVENTS:
        reasons.append(f"driven events {validation['n_driven']} < {M2_MIN_EVENTS}")
    if validation["detected_fraction"] < M2_MIN_DETECTED_FRACTION:
        reasons.append(
            f"detected fraction {validation['detected_fraction']:.3f} < {M2_MIN_DETECTED_FRACTION}"
        )
    if validation["bias_s"] is None:
        return {"status": "PENDING", "u_s": None, "reasons": [*reasons, validation["bias_note"]]}
    if period is not None and abs(validation["bias_s"]) > period:
        reasons.append(f"|bias| {abs(validation['bias_s'])} s exceeds one frame period")
    u = None if period is None else period + abs(validation["bias_s"])
    return {"status": "GO" if not reasons else "NO_GO", "u_s": u, "reasons": reasons}


__all__ = [
    "brightness_series",
    "m2_decision",
    "m2_latency",
    "m2_validation",
    "read_impact_annotations",
]
