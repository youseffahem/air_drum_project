"""E4 predictive uncertainty on the model side: a per-step Gaussian head and the reserved layouts.

The model emits a distribution; it never judges a crossing (no zones here, import-linter
``no-peek``). Propagation through geometry lives in ``spacedrums.geometry.probabilistic``, which
reads the layouts below from ``TrajectoryPrediction.uncertainty`` (contracts.md section 3.6):

- ``sigma_xy``: per step ``(std_x, std_y)`` of an independent-axis Gaussian around ``positions``;
- ``members_xy``: per step ``(dx_1, dy_1, ..., dx_M, dy_M)``, member offsets from ``positions``,
  equal member weights;
- ``mixture_xy``: per step ``(w_1, dx_1, dy_1, ..., w_M, dx_M, dy_M)``, mode weights (repeated on
  every step) and mode offsets from ``positions`` (the most probable mode, offset zero).
"""

import math

import numpy as np
import torch
from torch import nn

LOG_SIGMA_MIN = math.log(1e-4)
LOG_SIGMA_MAX = 0.0
LAYOUTS = ("sigma_xy", "members_xy", "mixture_xy")


class GaussianHead(nn.Module):
    """Mean displacement (created first, Phase 10 order) and clamped per-step log standard deviation."""

    def __init__(self, hidden: int, k: int):
        super().__init__()
        self.k = k
        self.trajectory = nn.Linear(hidden, 2 * k)
        self.log_sigma = nn.Linear(hidden, 2 * k)
        self.bounds = (LOG_SIGMA_MIN, LOG_SIGMA_MAX)

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        mean = self.trajectory(hidden).reshape(-1, self.k, 2)
        return mean, self.log_sigma(hidden).clamp(self.bounds[0], self.bounds[1])


def gaussian_nll(mean, log_sigma, target, mask):
    """Masked Gaussian negative log-likelihood (constant dropped) of the targets.

    The caller passes ``mean.detach()`` for the declared E4(a) variant: the mean keeps the Phase 10
    objective and the variance head is fitted to its residuals.
    """
    log_sigma = log_sigma.reshape(mean.shape)
    if target.shape != mean.shape or mask.shape != mean.shape[:-1]:
        raise ValueError("Gaussian target/mask shapes disagree")
    if not mask.any():
        return log_sigma.sum() * 0.0
    clean = torch.where(mask[..., None], target, mean.detach())
    z = (clean - mean) * torch.exp(-log_sigma)
    nll = 0.5 * z.square() + log_sigma
    weight = mask[..., None].to(nll.dtype)
    return (nll * weight).sum() / (2 * mask.sum())


def sigma_rows(log_sigma, k):
    sigma = np.exp(np.asarray(log_sigma, dtype=float).reshape(k, 2))
    return tuple(map(tuple, sigma))


def member_rows(point, members):
    """Rows of the ``members_xy`` layout; ``point`` is the member mean, members [M,K,2]."""
    offsets = np.asarray(members, dtype=float) - np.asarray(point, dtype=float)[None]
    return tuple(tuple(offsets[:, j].reshape(-1)) for j in range(offsets.shape[1]))


def mixture_rows(point, logits, trajectories):
    """Rows of the ``mixture_xy`` layout from logits [M] and mode trajectories [M,K,2]."""
    logits = np.asarray(logits, dtype=float)
    weights = np.exp(logits - logits.max())
    weights /= weights.sum()
    offsets = np.asarray(trajectories, dtype=float) - np.asarray(point, dtype=float)[None]
    rows = []
    for j in range(offsets.shape[1]):
        row = []
        for m in range(len(weights)):
            row.extend((float(weights[m]), float(offsets[m, j, 0]), float(offsets[m, j, 1])))
        rows.append(tuple(row))
    return tuple(rows)
