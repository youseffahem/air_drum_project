"""Alignment of external recordings (microphone, high-frame-rate video) to ``t_mono``.

An external recorder has its own clock (a sample counter, a video frame clock). The live session
emits **sync markers** at known ``t_mono`` instants: software clicks through the speaker, screen
flashes, or operator claps marked with a key. The recording shows the same events at unknown
external times. The phase document's method is "clap / flash cross-correlation". Here it is done
on event trains:

1. detect the marker events in the recording (:func:`detect_flashes` for per-frame brightness,
   :func:`spacedrums.data.audio_capture.detect_onsets` or template location for audio);
2. :func:`align_event_trains` finds the offset that matches the most events. The marker intervals
   are pseudo-random (:func:`sync_pattern`), so one offset explains the whole train.
3. It then fits ``t_mono = offset + (1 + drift) · t_ext`` by least squares on the matched pairs.

A result is ``OK`` only with at least ``min_matches`` matched markers. The residual RMS and maximum
are reported and compared with the method's validated tolerance by the caller (pre-registration
§7). A failure is a first-class outcome with its reason; it is never replaced by a guess.

For M1 the action-to-sound latency is a difference of two onsets in one recording, so the sync
only attributes strikes to arm blocks. For M2 and for M3 cross-checks the fitted map matters, and
its residual is carried into every derived time.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

SYNC_OK = "OK"
SYNC_FAILED = "FAILED"


@dataclass(frozen=True)
class ClockMap:
    """``t_mono = offset_s + (1 + drift) * t_ext``, fitted on ``n`` matched markers."""

    offset_s: float
    drift: float
    n: int
    residual_rms_s: float
    residual_max_s: float

    def to_mono(self, t_ext: float) -> float:
        return self.offset_s + (1.0 + self.drift) * float(t_ext)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fit_clock_map(ext: Sequence[float], mono: Sequence[float]) -> ClockMap:
    """Least-squares line through matched ``(t_ext, t_mono)`` pairs (``n >= 2``)."""
    x = np.asarray(ext, dtype=float)
    y = np.asarray(mono, dtype=float)
    if x.shape != y.shape or len(x) < 2:
        raise ValueError("at least two matched markers are needed for a clock map")
    x0 = float(x.mean())
    slope, intercept = np.polyfit(x - x0, y, 1)
    offset = float(intercept - slope * x0)
    residuals = y - (offset + slope * x)
    return ClockMap(
        offset_s=offset,
        drift=float(slope - 1.0),
        n=len(x),
        residual_rms_s=float(np.sqrt(np.mean(residuals**2))),
        residual_max_s=float(np.max(np.abs(residuals))),
    )


def _match(ext: np.ndarray, mono: np.ndarray, to_mono, tolerance_s: float) -> list[tuple[int, int]]:
    """Greedy one-to-one nearest matching of mapped external events to markers within tolerance."""
    mapped = np.asarray([to_mono(t) for t in ext])
    pairs = sorted(
        (abs(mapped[i] - mono[j]), i, j)
        for i in range(len(ext))
        for j in range(len(mono))
        if abs(mapped[i] - mono[j]) <= tolerance_s
    )
    used_i: set[int] = set()
    used_j: set[int] = set()
    out = []
    for _, i, j in pairs:
        if i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            out.append((i, j))
    return sorted(out, key=lambda p: p[1])


def align_event_trains(
    ext_times: Sequence[float],
    mono_times: Sequence[float],
    *,
    tolerance_s: float = 0.02,
    min_matches: int = 3,
    max_offset_s: float | None = None,
) -> dict[str, Any]:
    """Offset search over all event pairs, then a drift fit on the best-matching set.

    Every candidate offset ``mono_j - ext_i`` is scored by the number of one-to-one matches within
    ``tolerance_s``; ties go to the smaller residual RMS. The winning set is refitted with drift
    and re-matched once. If the best score is below ``min_matches``, or two different offsets
    tie on count and residual, the result is ``FAILED`` with the reason.
    """
    ext = np.asarray(sorted(float(t) for t in ext_times))
    mono = np.asarray(sorted(float(t) for t in mono_times))
    base: dict[str, Any] = {
        "status": SYNC_FAILED,
        "reason": None,
        "n_ext": len(ext),
        "n_markers": len(mono),
        "tolerance_s": tolerance_s,
        "min_matches": min_matches,
        "map": None,
        "matches": [],
        "unmatched_markers": list(range(len(mono))),
    }
    if len(ext) < min_matches or len(mono) < min_matches:
        base["reason"] = f"fewer than {min_matches} events or markers"
        return base
    scored: list[tuple[int, float, float]] = []
    for i in range(len(ext)):
        for j in range(len(mono)):
            offset = float(mono[j] - ext[i])
            if max_offset_s is not None and abs(offset) > max_offset_s:
                continue
            matches = _match(ext, mono, lambda t, o=offset: t + o, tolerance_s)
            if not matches:
                continue
            res = [mono[b] - (ext[a] + offset) for a, b in matches]
            scored.append((len(matches), float(np.sqrt(np.mean(np.square(res)))), offset))
    if not scored:
        base["reason"] = "no offset matches any marker"
        return base
    scored.sort(key=lambda s: (-s[0], s[1], s[2]))
    best_n, best_rms, best_offset = scored[0]
    rivals = [s for s in scored[1:] if s[0] == best_n and abs(s[2] - best_offset) > tolerance_s]
    if rivals and math.isclose(rivals[0][1], best_rms, rel_tol=0.0, abs_tol=1e-9):
        base["reason"] = "ambiguous: two offsets explain the markers equally well"
        return base
    matches = _match(ext, mono, lambda t: t + best_offset, tolerance_s)
    if len(matches) < max(2, min_matches):
        base["reason"] = f"only {len(matches)} matched markers (< {min_matches})"
        return base
    fit = fit_clock_map([ext[a] for a, _ in matches], [mono[b] for _, b in matches])
    matches = _match(ext, mono, fit.to_mono, tolerance_s)
    if len(matches) < min_matches:
        base["reason"] = f"only {len(matches)} matched markers after the drift fit (< {min_matches})"
        return base
    fit = fit_clock_map([ext[a] for a, _ in matches], [mono[b] for _, b in matches])
    matched_markers = {b for _, b in matches}
    return {
        **base,
        "status": SYNC_OK,
        "map": fit.to_dict(),
        "matches": [[float(ext[a]), float(mono[b])] for a, b in matches],
        "unmatched_markers": [j for j in range(len(mono)) if j not in matched_markers],
    }


def sync_pattern(
    n: int = 8, *, seed: int = 18, min_gap_s: float = 0.4, max_gap_s: float = 1.2
) -> list[float]:
    """Marker times (s from the first) with distinct pseudo-random gaps, so the train is unambiguous."""
    if n < 2 or not 0 < min_gap_s < max_gap_s:
        raise ValueError("n >= 2 and 0 < min_gap < max_gap required")
    gaps = np.linspace(min_gap_s, max_gap_s, n - 1)
    rng = np.random.default_rng(seed)
    rng.shuffle(gaps)
    return [0.0, *np.cumsum(gaps).tolist()]


def detect_flashes(
    brightness: Sequence[float],
    times: Sequence[float],
    *,
    baseline_frames: int = 30,
    k_sigma: float = 6.0,
    min_delta: float = 3.0,
    min_gap_s: float = 0.2,
) -> dict[str, Any]:
    """Flash onsets in a per-frame brightness series (Phase 02 screen-flash thresholds).

    A flash starts on the first frame whose brightness exceeds ``mu + max(k_sigma * sigma,
    min_delta)`` after at least ``min_gap_s`` below it. ``mu`` and ``sigma`` come from the first
    ``baseline_frames`` frames, which must be dark. Each onset is quantised to its frame: the
    resolution is one frame period, reported with the result.
    """
    b = np.asarray(brightness, dtype=float)
    t = np.asarray(times, dtype=float)
    if b.shape != t.shape or len(b) <= baseline_frames:
        raise ValueError("brightness and times must align and exceed the baseline length")
    if np.any(np.diff(t) <= 0):
        raise ValueError("frame times must be strictly increasing")
    mu, sigma = float(b[:baseline_frames].mean()), float(b[:baseline_frames].std())
    threshold = mu + max(k_sigma * sigma, min_delta)
    onsets: list[float] = []
    contrast: list[float] = []
    armed = True
    dark_since: float | None = float(t[baseline_frames])
    for i in range(baseline_frames, len(b)):
        if b[i] > threshold:
            if armed:
                onsets.append(float(t[i]))
                contrast.append(float((b[i] - mu) / sigma) if sigma > 0 else math.inf)
                armed = False
            dark_since = None
        else:
            if dark_since is None:
                dark_since = float(t[i])
            if not armed and t[i] - dark_since >= min_gap_s:
                armed = True
    periods = np.diff(t)
    return {
        "onsets_s": onsets,
        "contrast_sigma": contrast,
        "threshold": threshold,
        "baseline": {"mu": mu, "sigma": sigma, "frames": baseline_frames},
        "frame_period_s": float(np.median(periods)),
        "resolution_s": float(np.median(periods)),
    }


def envelope(signal: np.ndarray, rate: int, *, window_s: float = 0.002) -> np.ndarray:
    """Moving RMS envelope (same length as the input)."""
    x = np.asarray(signal, dtype=float)
    if x.ndim == 2:
        x = x.mean(axis=1)
    w = max(1, int(round(window_s * rate)))
    kernel = np.ones(w) / w
    return np.sqrt(np.convolve(x * x, kernel, mode="same"))


def xcorr_lag(a: np.ndarray, b: np.ndarray, rate: int, *, max_lag_s: float) -> dict[str, float]:
    """Lag of ``b`` relative to ``a`` (s; positive = ``b`` later) by normalised cross-correlation of
    the two envelopes, refined by a parabola through the peak and its neighbours."""
    ea, eb = envelope(a, rate), envelope(b, rate)
    ea, eb = ea - ea.mean(), eb - eb.mean()
    n = len(ea) + len(eb) - 1
    size = 1 << (n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(eb, size) * np.conj(np.fft.rfft(ea, size)), size)
    max_lag = int(round(max_lag_s * rate))
    lags = np.concatenate((np.arange(0, max_lag + 1), np.arange(-max_lag, 0)))
    values = np.concatenate((corr[: max_lag + 1], corr[size - max_lag :]))
    k = int(np.argmax(values))
    lag = float(lags[k])
    if 0 < k < len(values) - 1 and lags[k - 1] == lags[k] - 1 and lags[k + 1] == lags[k] + 1:
        y0, y1, y2 = values[k - 1], values[k], values[k + 1]
        denom = y0 - 2 * y1 + y2
        if denom != 0:
            lag += 0.5 * (y0 - y2) / denom
    norm = float(np.linalg.norm(ea) * np.linalg.norm(eb))
    return {"lag_s": lag / rate, "peak": float(values[k] / norm) if norm > 0 else 0.0}


__all__ = [
    "SYNC_FAILED",
    "SYNC_OK",
    "ClockMap",
    "align_event_trains",
    "detect_flashes",
    "envelope",
    "fit_clock_map",
    "sync_pattern",
    "xcorr_lag",
]
