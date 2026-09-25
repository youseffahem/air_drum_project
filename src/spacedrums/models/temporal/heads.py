"""Displacement head, the Phase 10 optional logit, and the Phase 11 multi-task heads."""

import numpy as np
import torch
from torch import nn

from .losses import decode_tti


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


def _head(hidden: int, width: int, head_hidden: int) -> nn.Module:
    if head_hidden == 0:
        return nn.Linear(hidden, width)
    return nn.Sequential(nn.Linear(hidden, head_hidden), nn.ReLU(), nn.Linear(head_hidden, width))


class MultiTaskHead(nn.Module):
    """One shared encoder state feeds every enabled head; disabled heads return zeros.

    Output order is fixed for export: trajectory displacements [B,K,2], strike logit [B],
    TTI [B,W] (W=1, or bins), zone logits [B,Z], impact displacement from the current tip [B,2],
    standardised intensity [B]. The trajectory layer is created first, so a trajectory-only head
    draws parameters exactly like the Phase 10 head without its optional logit.
    """

    def __init__(self, hidden: int, config):
        super().__init__()
        heads = set(config.heads)
        self.k, self.zones, self.tti_width = config.base.k, max(1, len(config.zone_ids)), config.tti_width
        self.use_trajectory = "trajectory" in heads
        self.use_strike = "strike" in heads
        self.use_tti = "tti" in heads
        self.use_zone = "zone" in heads
        self.use_position = "position" in heads
        self.use_intensity = "intensity" in heads
        width = config.head_hidden
        self.trajectory = nn.Linear(hidden, 2 * self.k) if self.use_trajectory else nn.Identity()
        self.strike = _head(hidden, 1, width) if self.use_strike else nn.Identity()
        self.tti = _head(hidden, self.tti_width, width) if self.use_tti else nn.Identity()
        self.zone = _head(hidden, self.zones, width) if self.use_zone else nn.Identity()
        self.position = _head(hidden, 2, width) if self.use_position else nn.Identity()
        self.intensity = _head(hidden, 1, width) if self.use_intensity else nn.Identity()

    def forward(
        self, hidden: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        rows = hidden.shape[0]
        trajectory = (
            self.trajectory(hidden).reshape(-1, self.k, 2)
            if self.use_trajectory
            else hidden.new_zeros([rows, self.k, 2])
        )
        strike = self.strike(hidden).squeeze(-1) if self.use_strike else hidden.new_zeros([rows])
        tti = self.tti(hidden) if self.use_tti else hidden.new_zeros([rows, self.tti_width])
        zone = self.zone(hidden) if self.use_zone else hidden.new_zeros([rows, self.zones])
        position = self.position(hidden) if self.use_position else hidden.new_zeros([rows, 2])
        intensity = self.intensity(hidden).squeeze(-1) if self.use_intensity else hidden.new_zeros([rows])
        return trajectory, strike, tti, zone, position, intensity


def decode_heads(config, scaling, outputs, anchors):
    """Physical-unit head values for a batch; absent heads are absent keys.

    ``anchors`` are the current tips [B,2]: the position head predicts a displacement from the
    current tip like the trajectory head. Intensity is un-standardised with train-fold-only
    statistics and clipped at zero (the proxy is an inward speed, not force).
    """
    _, strike, tti, zone, position, intensity = (o.detach() for o in outputs)
    heads, out = set(config.heads), {}
    if "strike" in heads:
        out["strike_prob"] = torch.sigmoid(strike).numpy().astype(float)
    if "tti" in heads:
        out["tti_s"] = decode_tti(tti, mode=config.tti_mode, h_max_s=config.h_max_s).numpy().astype(float)
    if "zone" in heads:
        out["zone_logits"] = zone.numpy().astype(float)
        out["zone_index"] = zone.argmax(dim=-1).numpy()
    if "position" in heads:
        out["impact_pos"] = position.numpy().astype(float) + np.asarray(anchors, dtype=float)
    if "intensity" in heads:
        stats = scaling["intensity"]
        out["intensity"] = np.maximum(0.0, stats["center"] + stats["scale"] * intensity.numpy().astype(float))
    return out
