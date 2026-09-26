"""Bounded sliding p95 budgets and a delivered-frame cadence guard (seconds throughout)."""

import math
from collections import deque

import numpy as np


class BudgetMonitor:
    def __init__(self, budget_s, window_frames):
        if not math.isfinite(budget_s) or budget_s <= 0 or window_frames < 1:
            raise ValueError("positive finite budget and window required")
        self.budget_s = budget_s
        self.samples = deque(maxlen=window_frames)

    @property
    def p95(self):
        return float(np.percentile(self.samples, 95)) if self.samples else None

    def observe(self, duration_s):
        if not math.isfinite(duration_s) or duration_s < 0:
            raise ValueError("duration must be finite and nonnegative")
        self.samples.append(duration_s)
        return len(self.samples) == self.samples.maxlen and self.p95 > self.budget_s


class CadenceMonitor:
    """Detect sustained native-rate mismatch, preserving actual dt and dropped-frame gaps."""

    def __init__(self, dt_step, window, tolerance):
        self.dt_step, self.tolerance = dt_step, tolerance
        self.intervals = deque(maxlen=window)
        self.previous = None

    def observe(self, sample):
        if self.previous is not None:
            old = self.previous
            if sample.frame_id <= old.frame_id or sample.t_capture <= old.t_capture:
                raise ValueError("delivered frames must strictly increase")
            self.intervals.append((sample.t_capture - old.t_capture) / (sample.frame_id - old.frame_id))
        self.previous = sample
        if len(self.intervals) == self.intervals.maxlen:
            median = float(np.median(self.intervals))
            if abs(median / self.dt_step - 1) > self.tolerance:
                raise ValueError(f"delivered FPS / training dt_step mismatch: median interval {median:.6f}s")
