"""M1: physical action-to-sound latency from one microphone recording of pad and speaker.

The participant strikes a practice pad placed on a calibrated zone. One microphone records both the
pad impact and the drum sound the system plays. The **difference of the two onsets in the same
recording** is the physical action-to-sound latency of the arm that sounded (pre-registration §8).
The microphone's own latency cancels in the difference, and no software timestamp enters the
number. The ``t_mono`` sync only attributes a strike to its arm block.

Method (declared):

* **Sound onset:** normalised cross-correlation of the recording with the played sample (the
  template), peak refined by a parabola to sub-sample precision (:func:`locate_template`).
* **Pad onset:** the recording minus the least-squares fit of every located sound, then the Phase
  06/07 onset detector (``detect_onsets``) at 1 ms frames (:func:`pad_onsets`).
* **Pairing:** a sound and a pad onset pair when exactly one pad onset lies in
  ``[t_sound - max_sound_after_s, t_sound + max_sound_before_s]`` and that pad onset is claimed by
  no other sound (:func:`pair_strikes`). Zero or two-plus candidates exclude the strike (§7).
* **Validation (Task 18.3):** :func:`click_pair_validation` measures the separation of pre-rendered
  click pairs of known sample separation. :func:`rise_time` gives the conservative pad-onset bound
  ``r_pad``. :func:`m1_decision` applies the declared GO thresholds.

Everything here is a pure function on arrays. The tests use SYNTHETIC recordings, which prove the
machinery only; the method's validity on real hardware is what the developer pilot measures.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from scipy.signal import fftconvolve

from spacedrums.data.audio_capture import detect_onsets

# Declared M1 acceptance thresholds (pre-registration §8; candidates the owner may amend before the
# live lock).
M1_CLICK_MIN_PAIRS = 30
M1_CLICK_MAX_ABS_BIAS_S = 0.001
M1_CLICK_MAX_E95_S = 0.002
M1_PAD_MIN_STRIKES = 30
M1_PAD_MIN_PAIRED_FRACTION = 0.90
M1_MAX_U_S = 0.005


def _mono(x: np.ndarray) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    return a.mean(axis=1) if a.ndim == 2 else a


def normalized_xcorr(signal: np.ndarray, template: np.ndarray) -> np.ndarray:
    """``ncc[i]`` = correlation of ``template`` with ``signal[i : i + m]`` in [-1, 1] (valid lags)."""
    x, t = _mono(signal), _mono(template)
    m = len(t)
    if m == 0 or len(x) < m:
        return np.zeros(0)
    t = t - t.mean()
    t_norm = float(np.linalg.norm(t))
    if t_norm == 0:
        raise ValueError("template has no energy")
    num = fftconvolve(x, t[::-1], mode="valid")
    c1 = np.concatenate(([0.0], np.cumsum(x)))
    c2 = np.concatenate(([0.0], np.cumsum(x * x)))
    s1 = c1[m:] - c1[:-m]
    s2 = c2[m:] - c2[:-m]
    var = np.maximum(s2 - s1 * s1 / m, 0.0)
    den = np.sqrt(var) * t_norm
    with np.errstate(divide="ignore", invalid="ignore"):
        ncc = np.where(den > 1e-12, num / den, 0.0)
    return np.clip(ncc, -1.0, 1.0)


def _refine(values: np.ndarray, k: int) -> float:
    if 0 < k < len(values) - 1:
        y0, y1, y2 = values[k - 1], values[k], values[k + 1]
        denom = y0 - 2.0 * y1 + y2
        if denom < 0:
            return float(k + 0.5 * (y0 - y2) / denom)
    return float(k)


def locate_template(
    recording: np.ndarray,
    template: np.ndarray,
    rate: int,
    *,
    min_ncc: float = 0.5,
    windows: Sequence[tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    """Onsets of ``template`` in ``recording`` (seconds from the first sample).

    With ``windows`` (start, end in seconds), at most one onset per window: the best peak inside it.
    Without, every local maximum above ``min_ncc``, with maxima suppressed within one template
    length of a stronger one.
    """
    ncc = normalized_xcorr(recording, template)
    m = len(_mono(template))
    found: list[dict[str, Any]] = []
    if len(ncc) == 0:
        return found
    if windows is not None:
        for a, b in windows:
            i0, i1 = max(0, int(math.floor(a * rate))), min(len(ncc), int(math.ceil(b * rate)) + 1)
            if i1 <= i0:
                continue
            k = i0 + int(np.argmax(ncc[i0:i1]))
            if ncc[k] >= min_ncc:
                found.append({"t_s": _refine(ncc, k) / rate, "ncc": float(ncc[k]), "window": [a, b]})
        return found
    candidates = np.flatnonzero(ncc >= min_ncc)
    taken: list[int] = []
    for k in sorted(candidates, key=lambda i: -ncc[i]):
        if all(abs(k - j) >= m for j in taken):
            taken.append(int(k))
    for k in sorted(taken):
        found.append({"t_s": _refine(ncc, k) / rate, "ncc": float(ncc[k]), "window": None})
    return found


def subtract_templates(
    recording: np.ndarray, rate: int, located: Sequence[Mapping[str, Any]], template: np.ndarray
) -> np.ndarray:
    """Recording minus the least-squares gain times ``template`` at each located onset."""
    x = _mono(recording).copy()
    t = _mono(template)
    m = len(t)
    energy = float(np.dot(t, t))
    for item in located:
        i = int(round(float(item["t_s"]) * rate))
        if i < 0 or i + m > len(x) or energy == 0:
            continue
        gain = float(np.dot(x[i : i + m], t)) / energy
        x[i : i + m] -= gain * t
    return x


def pad_onsets(
    recording: np.ndarray,
    rate: int,
    *,
    sounds: Sequence[Mapping[str, Any]] = (),
    template: np.ndarray | None = None,
    frame_s: float = 0.001,
    threshold_ratio: float = 0.3,
    min_gap_s: float = 0.08,
) -> list[float]:
    """Pad onsets (s) with the located sounds removed first (Phase 06/07 detector, 1 ms frames)."""
    residual = (
        subtract_templates(recording, rate, sounds, template)
        if template is not None and sounds
        else _mono(recording)
    )
    return detect_onsets(
        residual, rate, threshold_ratio=threshold_ratio, min_gap_s=min_gap_s, frame_s=frame_s
    )


def pair_strikes(
    pad_times: Sequence[float],
    sound_times: Sequence[float],
    *,
    max_sound_after_s: float = 0.35,
    max_sound_before_s: float = 0.25,
) -> dict[str, Any]:
    """Pair each sound with its pad onset; ``latency_s = t_sound - t_pad`` (negative = early sound).

    A pad onset is a candidate for a sound when ``-max_sound_before_s <= t_sound - t_pad <=
    max_sound_after_s``. A pair is kept only when the sound has exactly one candidate and that pad
    onset is a candidate of no other sound. Everything else is excluded with its reason.
    """
    pads = [float(t) for t in pad_times]
    sounds = [float(t) for t in sound_times]
    cand = {
        j: [i for i, p in enumerate(pads) if -max_sound_before_s <= s - p <= max_sound_after_s]
        for j, s in enumerate(sounds)
    }
    claims: dict[int, int] = {}
    for js in cand.values():
        for i in js:
            claims[i] = claims.get(i, 0) + 1
    pairs, excluded = [], []
    for j, s in enumerate(sounds):
        cs = cand[j]
        if not cs:
            excluded.append({"sound_index": j, "t_sound_s": s, "reason": "no pad onset in the window"})
        elif len(cs) > 1:
            excluded.append({"sound_index": j, "t_sound_s": s, "reason": "ambiguous: several pad onsets"})
        elif claims[cs[0]] > 1:
            excluded.append({"sound_index": j, "t_sound_s": s, "reason": "ambiguous: pad onset shared"})
        else:
            i = cs[0]
            pairs.append(
                {
                    "sound_index": j,
                    "pad_index": i,
                    "t_sound_s": s,
                    "t_pad_s": pads[i],
                    "latency_s": s - pads[i],
                }
            )
    paired_pads = {p["pad_index"] for p in pairs}
    return {
        "pairs": pairs,
        "excluded": excluded,
        "unpaired_pads": [{"pad_index": i, "t_pad_s": p} for i, p in enumerate(pads) if i not in paired_pads],
        "window": {"max_sound_after_s": max_sound_after_s, "max_sound_before_s": max_sound_before_s},
    }


def click_pair_validation(
    recording: np.ndarray,
    rate: int,
    click: np.ndarray,
    expected_pairs: Sequence[tuple[float, float]],
    *,
    min_ncc: float = 0.3,
    tolerance_s: float = 0.005,
    max_offset_s: float = 1.0,
) -> dict[str, Any]:
    """Known-separation check: measured minus scheduled separation of each click pair.

    ``expected_pairs`` are the output-stream times (s) of the two clicks of each pair. Every click is
    located in the whole recording (:func:`locate_template`). The located train is then aligned
    with the scheduled train by :func:`spacedrums.live_eval.sync.align_event_trains`: one common
    output + input delay, found by offset search, and a drift fit. A pair counts only when both of
    its clicks matched. Its error is the measured separation minus the scheduled one, so the unknown
    common delay cancels.
    """
    from spacedrums.live_eval.sync import align_event_trains

    found = [f["t_s"] for f in locate_template(recording, click, rate, min_ncc=min_ncc)]
    expected = sorted(t for pair in expected_pairs for t in pair)
    aligned = align_event_trains(found, expected, tolerance_s=tolerance_s, max_offset_s=max_offset_s)
    rec_of = {mono: ext for ext, mono in aligned["matches"]}
    errors, delays, missed = [], [], 0
    for first, second in expected_pairs:
        if first not in rec_of or second not in rec_of:
            missed += 1
            continue
        errors.append((rec_of[second] - rec_of[first]) - (second - first))
        delays.append(rec_of[first] - first)
    e = np.asarray(errors, dtype=float)
    return {
        "n_pairs": len(expected_pairs),
        "n_detected": len(errors),
        "n_missed": missed,
        "n_clicks_located": len(found),
        "alignment": {k: aligned[k] for k in ("status", "reason", "map", "unmatched_markers")},
        "errors_s": e.tolist(),
        "bias_s": float(e.mean()) if len(e) else None,
        "e95_s": float(np.percentile(np.abs(e), 95)) if len(e) else None,
        "max_abs_s": float(np.abs(e).max()) if len(e) else None,
        "stream_to_recording_s": {
            "median": float(np.median(delays)) if delays else None,
            "spread_p90_p10": float(np.percentile(delays, 90) - np.percentile(delays, 10))
            if delays
            else None,
            "note": "output + input path of the duplex stream; diagnostic only, not output latency",
        },
    }


def rise_time(
    recording: np.ndarray, rate: int, onset_s: float, *, window_s: float = 0.03, smooth_s: float = 0.0005
) -> float | None:
    """10-90 % rise time of the envelope from ``onset_s`` to its peak within ``window_s``."""
    x = _mono(recording)
    i0 = max(0, int(round(onset_s * rate)) - int(0.002 * rate))
    seg = np.abs(x[i0 : i0 + int(window_s * rate)])
    if len(seg) < 3:
        return None
    w = max(1, int(round(smooth_s * rate)))
    env = np.convolve(seg, np.ones(w) / w, mode="same")
    k = int(np.argmax(env))
    peak = env[k]
    if peak <= 0:
        return None
    rising = env[: k + 1]
    lo = np.flatnonzero(rising >= 0.1 * peak)
    hi = np.flatnonzero(rising >= 0.9 * peak)
    if not len(lo) or not len(hi):
        return None
    return float((hi[0] - lo[0]) / rate)


def m1_uncertainty(e95_click_s: float, r_pad_s: float) -> float:
    return float(math.hypot(e95_click_s, r_pad_s))


def m1_decision(click: Mapping[str, Any] | None, pad: Mapping[str, Any] | None) -> dict[str, Any]:
    """The declared M1 GO rule; a missing pilot part gives PENDING with the missing part named."""
    reasons: list[str] = []
    if click is None:
        return {"status": "PENDING", "u_s": None, "reasons": ["click-pair validation not run"]}
    if click["n_detected"] < M1_CLICK_MIN_PAIRS:
        reasons.append(f"click pairs detected {click['n_detected']} < {M1_CLICK_MIN_PAIRS}")
    if click["bias_s"] is None or abs(click["bias_s"]) > M1_CLICK_MAX_ABS_BIAS_S:
        reasons.append(f"click bias {click['bias_s']} exceeds {M1_CLICK_MAX_ABS_BIAS_S} s")
    if click["e95_s"] is None or click["e95_s"] > M1_CLICK_MAX_E95_S:
        reasons.append(f"click e95 {click['e95_s']} exceeds {M1_CLICK_MAX_E95_S} s")
    click_ok = not reasons
    if pad is None:
        return {
            "status": "PENDING" if click_ok else "NO_GO",
            "u_s": None,
            "click_part": "PASS" if click_ok else "FAIL",
            "reasons": reasons + ["developer pad pilot not run (person-dependent)"],
        }
    if pad["n_strikes"] < M1_PAD_MIN_STRIKES:
        reasons.append(f"pad strikes {pad['n_strikes']} < {M1_PAD_MIN_STRIKES}")
    if pad["paired_fraction"] < M1_PAD_MIN_PAIRED_FRACTION:
        reasons.append(f"paired fraction {pad['paired_fraction']:.3f} < {M1_PAD_MIN_PAIRED_FRACTION}")
    u = (
        m1_uncertainty(click["e95_s"], pad["rise_time_median_s"])
        if click["e95_s"] is not None and pad.get("rise_time_median_s") is not None
        else None
    )
    if u is None or u > M1_MAX_U_S:
        reasons.append(f"U_M1 {u} exceeds {M1_MAX_U_S} s")
    return {
        "status": "GO" if not reasons else "NO_GO",
        "u_s": u,
        "click_part": "PASS" if click_ok else "FAIL",
        "reasons": reasons,
    }


__all__ = [
    "M1_MAX_U_S",
    "click_pair_validation",
    "locate_template",
    "m1_decision",
    "m1_uncertainty",
    "normalized_xcorr",
    "pad_onsets",
    "pair_strikes",
    "rise_time",
    "subtract_templates",
]
