"""Displacement head and the sole optional strike-within-horizon logit."""

import torch
from torch import nn


def masked_inputs(x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    # Missing values cannot leak through a nonzero payload, including NaN sentinels.
    return torch.cat((torch.where(mask, x, torch.zeros_like(x)), mask.to(x.dtype)), dim=-1)


class TrajectoryHead(nn.Module):
    def __init__(self, hidden: int, k: int, auxiliary: bool):
        super().__init__()
        self.k, self.auxiliary = k, auxiliary
        self.trajectory = nn.Linear(hidden, 2 * k)
        self.aux = nn.Linear(hidden, 1) if auxiliary else nn.Identity()

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        trajectory = self.trajectory(hidden).reshape(-1, self.k, 2)
        logit = self.aux(hidden).squeeze(-1) if self.auxiliary else hidden[:, 0] * 0.0
        return trajectory, logit
