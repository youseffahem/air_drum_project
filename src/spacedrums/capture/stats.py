"""Frame-interval statistics, stall detection and ``CaptureStats`` (Tasks 02.3 / 02.4).

Definitions (Phase 02 *Algorithms*):

* intervals are consecutive ``t_capture`` differences of **delivered, unique** frames;
* a *gap* is flagged when an interval exceeds ``drop_factor`` x nominal (candidate 1.5, tunable);
* a *stall* is flagged when no frame arrives for more than ``stall_factor`` x nominal
  (candidate 2.0, tunable; ``camera_profile.queue.stall_factor``);
* delivered FPS is ``(N - 1) / (t_last - t_first)`` over the delivered unique frames — it is a
  *measurement* of what the camera delivered, never the requested mode (integrity I-5).

Nothing here interpolates, resamples or invents frames.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class IntervalStats:
    """Statistics of consecutive timestamp differences (seconds)."""

    n_frames: int
    n_intervals: int
    duration_s: float
    fps: float  # (n_frames - 1) / duration_s
    mean_s: float
    std_s: float
    min_s: float
    p1_s: float
    p50_s: float
    p99_s: float
    max_s: float
    nominal_s: float | None
    n_gaps: int  # intervals > drop_factor x nominal
    n_stalls: int  # intervals > stall_factor x nominal
    drop_factor: float
    stall_factor: float
    histogram_edges_s: list[float] = field(default_factory=list)
    histogram_counts: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def interval_stats(
    timestamps: Sequence[float],
    nominal_interval_s: float | None,
    *,
    drop_factor: float = 1.5,
    stall_factor: float = 2.0,
    histogram_bins: int = 40,
) -> IntervalStats:
    """Compute :class:`IntervalStats` from monotone timestamps.

    Raises ``ValueError`` for fewer than two timestamps or a non-monotone sequence: statistics of
    a broken timestamp stream must not be reported as if they were frame intervals.
    """
    t = np.asarray(timestamps, dtype=float)
    if t.ndim != 1 or t.size < 2:
        raise ValueError("interval statistics need at least two timestamps")
    d = np.diff(t)
    if np.any(d < 0):
        raise ValueError("timestamps must be non-decreasing")
    if nominal_interval_s is not None and nominal_interval_s <= 0:
        raise ValueError("nominal_interval_s must be > 0")
    duration = float(t[-1] - t[0])
    fps = float((t.size - 1) / duration) if duration > 0 else float("inf")
    if nominal_interval_s is not None:
        n_gaps = int(np.count_nonzero(d > drop_factor * nominal_interval_s))
        n_stalls = int(np.count_nonzero(d > stall_factor * nominal_interval_s))
        hi = max(float(d.max()), 3.0 * nominal_interval_s)
    else:
        n_gaps = n_stalls = 0
        hi = float(d.max()) if d.max() > 0 else 1.0
    counts, edges = np.histogram(d, bins=histogram_bins, range=(0.0, hi))
    return IntervalStats(
        n_frames=int(t.size),
        n_intervals=int(d.size),
        duration_s=duration,
        fps=fps,
        mean_s=float(d.mean()),
        std_s=float(d.std()),
        min_s=float(d.min()),
        p1_s=float(np.percentile(d, 1)),
        p50_s=float(np.percentile(d, 50)),
        p99_s=float(np.percentile(d, 99)),
        max_s=float(d.max()),
        nominal_s=nominal_interval_s,
        n_gaps=n_gaps,
        n_stalls=n_stalls,
        drop_factor=drop_factor,
        stall_factor=stall_factor,
        histogram_edges_s=[float(e) for e in edges],
        histogram_counts=[int(c) for c in counts],
    )


class StallDetector:
    """Flags "no frame for > stall_factor x expected interval" (Task 02.3), causally."""

    def __init__(self, nominal_interval_s: float, stall_factor: float = 2.0) -> None:
        if nominal_interval_s <= 0 or stall_factor <= 1.0:
            raise ValueError("nominal_interval_s must be > 0 and stall_factor > 1")
        self.threshold_s = stall_factor * nominal_interval_s
        self.stalls = 0
        self._t_last: float | None = None

    def observe(self, t: float) -> bool:
        """Register a frame at ``t``; return True if the wait since the previous one was a stall."""
        stalled = self._t_last is not None and (t - self._t_last) > self.threshold_s
        if stalled:
            self.stalls += 1
        self._t_last = t
        return stalled

    def is_stalling(self, t_now: float) -> bool:
        """True while the current wait already exceeds the threshold (no frame yet)."""
        return self._t_last is not None and (t_now - self._t_last) > self.threshold_s


@dataclass(frozen=True)
class CaptureStats:
    """Counters exposed to the debug overlay (Phase 15) and session metadata (Phase 06).

    Fields of the Phase 02 interface contract plus ``duplicates`` (byte-identical consecutive
    frames the backend delivered and capture refused to count: Task 02.4 finding on HW-01) and
    ``clamped_timestamps`` (timestamp-policy interventions: a mapped ``t_capture`` clamped to keep
    ``t_capture <= t_frame_available``, or - Phase 17 - a frame refused because its ``t_capture``
    would not strictly increase; must be 0 in a healthy run).
    """

    delivered: int
    dropped: int
    stalled: int
    duplicates: int
    fps_measured: float | None
    interval_p50: float | None
    interval_p99: float | None
    clamped_timestamps: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["CaptureStats", "IntervalStats", "StallDetector", "interval_stats"]
