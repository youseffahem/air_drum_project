"""Left-padded residual dilated convolutions, without time-mixing normalization."""

import torch
from torch import nn
from torch.nn import functional as F

from .heads import MultiTaskHead, TrajectoryHead, masked_inputs


class CausalConv(nn.Module):
    def __init__(self, channels, kernel, dilation):
        super().__init__()
        self.left = (kernel - 1) * dilation
        self.conv = nn.Conv1d(channels, channels, kernel, dilation=dilation)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv(F.pad(x, (self.left, 0)))


class ResidualBlock(nn.Module):
    def __init__(self, channels, kernel, dilation, dropout):
        super().__init__()
        self.first = CausalConv(channels, kernel, dilation)
        self.second = CausalConv(channels, kernel, dilation)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.dropout(torch.relu(self.first(x)))
        return torch.relu(x + self.dropout(self.second(y)))


class TCNPredictor(nn.Module):
    def __init__(self, config, head_factory=None):
        super().__init__()
        self.n = config.n
        self.receptive_field = config.receptive_field
        if self.receptive_field < self.n:
            raise ValueError("receptive field smaller than declared N")
        self.project = nn.Conv1d(config.features * 2, config.hidden, 1)
        self.blocks = nn.Sequential(
            *[ResidualBlock(config.hidden, config.kernel, d, config.dropout) for d in config.dilations]
        )
        # The factory runs at the Phase 10 position, so parameter draws keep their order.
        if head_factory is None:
            self.head = TrajectoryHead(config.hidden, config.k, config.auxiliary)
        else:
            self.head = head_factory()

    @torch.jit.export
    def encode(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        return self.blocks(self.project(masked_inputs(x, mask).transpose(1, 2)))

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        encoded = self.encode(x[:, -self.n :], mask[:, -self.n :])
        return self.head(encoded[:, :, -1])


class MultiTaskTCN(TCNPredictor):
    """The Phase 10 causal TCN encoder shared by every Phase 11 head."""

    def __init__(self, config):
        super().__init__(config.base, head_factory=lambda: MultiTaskHead(config.base.hidden, config))

    def forward(
        self, x: torch.Tensor, mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        encoded = self.encode(x[:, -self.n :], mask[:, -self.n :])
        return self.head(encoded[:, :, -1])
