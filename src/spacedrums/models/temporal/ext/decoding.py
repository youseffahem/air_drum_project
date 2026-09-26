"""E5 decoding: residual over the causal constant-velocity/-acceleration extrapolation, and
bounded-acceleration projection of decoded points.

The residual base reads only the current frame's velocity (and acceleration) features of the causal
window, de-normalised with the training fold's statistics (buffers saved with the model). It is
Baseline B's motion model applied to the model's own inputs, without B's speed/acceleration gates.
"""

import numpy as np
import torch
from torch import nn


class ResidualExtrapolation(nn.Module):
    """point = extrapolation(current velocity[, acceleration]) at the output offsets + inner point."""

    def __init__(self, inner, config, center=None, scale=None):
        super().__init__()
        width = len(config.residual_features)
        self.inner = inner
        self.n = config.n
        self.constant_acceleration = config.residual == "ca"
        center = torch.zeros(width) if center is None else torch.as_tensor(center, dtype=torch.float32)
        scale = torch.ones(width) if scale is None else torch.as_tensor(scale, dtype=torch.float32)
        if center.shape != (width,) or scale.shape != (width,) or not bool((scale > 0).all()):
            raise ValueError("residual base needs one positive scale per declared feature")
        self.register_buffer("index", torch.tensor(config.residual_features, dtype=torch.long))
        self.register_buffer("center", center.clone())
        self.register_buffer("scale", scale.clone())
        self.register_buffer("tau", torch.tensor(config.offsets_s, dtype=torch.float32))

    @torch.jit.export
    def base(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        values, present = x[:, -1][:, self.index], mask[:, -1][:, self.index]
        # Select before arithmetic: a masked NaN payload cannot leak into the extrapolation.
        raw = torch.where(present, values, torch.zeros_like(values)) * self.scale + self.center
        raw = torch.where(present, raw, torch.zeros_like(raw))
        tau = self.tau.reshape(1, -1, 1)
        displacement = raw[:, None, :2] * tau
        if self.constant_acceleration:
            displacement = displacement + 0.5 * raw[:, None, 2:4] * tau * tau
        return displacement

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        point, aux = self.inner(x, mask)
        return point + self.base(x, mask), aux


def _second_differences(points, times):
    """Non-uniform second differences at interior points (both neighbours present)."""
    h0, h1 = np.diff(times)[:-1], np.diff(times)[1:]
    v0 = (points[1:-1] - points[:-2]) / h0[:, None]
    v1 = (points[2:] - points[1:-1]) / h1[:, None]
    return 2 * (v1 - v0) / (h0 + h1)[:, None]


def bounded_acceleration(displacements, offsets_s, a_max):
    """Greedy forward projection: from the second step on, each point follows the prediction unless
    the implied acceleration exceeds ``a_max`` (ROI/s^2), in which case it is clipped in magnitude.
    The first step is unconstrained; the anchor (current tip) is displacement zero at time zero.
    """
    p = np.vstack((np.zeros(2), np.asarray(displacements, dtype=float)))
    t = np.r_[0.0, np.asarray(offsets_s, dtype=float)]
    if p.shape != (len(t), 2) or (np.diff(t) <= 0).any() or not a_max > 0:
        raise ValueError("finite [K,2] displacements, increasing offsets and positive a_max required")
    out = p.copy()
    for j in range(1, len(p) - 1):
        h0, h1 = t[j] - t[j - 1], t[j + 1] - t[j]
        v0 = (out[j] - out[j - 1]) / h0
        v1 = (p[j + 1] - out[j]) / h1
        acceleration = 2 * (v1 - v0) / (h0 + h1)
        norm = float(np.hypot(*acceleration))
        if norm > a_max:
            v1 = v0 + acceleration * (a_max / norm) * (h0 + h1) / 2
        out[j + 1] = out[j] + v1 * h1
    return out[1:]


def fit_acceleration_bound(targets, mask, offsets_s, *, quantile=0.99):
    """a_max from TRAINING targets only: the quantile of |second difference| over interior points
    whose three neighbours are observed (the anchor at time zero always is)."""
    targets, mask = np.asarray(targets, dtype=float), np.asarray(mask, dtype=bool)
    times = np.r_[0.0, np.asarray(offsets_s, dtype=float)]
    values = []
    for row, valid in zip(targets, mask, strict=True):
        count = next((j for j, good in enumerate(valid) if not good), len(valid))
        if count < 2:
            continue
        points = np.vstack((np.zeros(2), row[:count]))
        values.extend(np.hypot(*_second_differences(points, times[: count + 1]).T))
    if not values:
        raise ValueError("no training target has two consecutive observed steps")
    return float(np.quantile(values, quantile))
