"""Unidirectional GRU and exact finite-window recurrent inference.

A single indefinitely carried hidden state is NOT equivalent to rolling N-frame
training. The bounded cache carries one hidden state per surviving window start.
Window-relative feature changes trigger rebuilding those states, preserving parity.
"""

import torch
from torch import nn

from .heads import TrajectoryHead, masked_inputs


class GRUPredictor(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.n, self.hidden, self.layers = config.n, config.hidden, config.layers
        self.gru = nn.GRU(
            config.features * 2,
            config.hidden,
            config.layers,
            batch_first=True,
            dropout=config.dropout if config.layers > 1 else 0.0,
        )
        self.head = TrajectoryHead(config.hidden, config.k, config.auxiliary)

    @torch.jit.export
    def step(self, x: torch.Tensor, mask: torch.Tensor, state: torch.Tensor) -> torch.Tensor:
        live = mask.any(dim=-1).reshape(1, -1, 1)
        state = torch.where(live, state, torch.zeros_like(state))
        _, state = self.gru(masked_inputs(x, mask).unsqueeze(1), state)
        return torch.where(live, state, torch.zeros_like(state))

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x, mask = x[:, -self.n :], mask[:, -self.n :]
        state = x.new_zeros((self.layers, x.shape[0], self.hidden))
        for i in range(x.shape[1]):
            state = self.step(x[:, i], mask[:, i], state)
        return self.head(state[-1])


class BoundedGRUState:
    """Inference-only cache for ONE hand, with at most N cold-start lanes."""

    def __init__(self, model):
        self.model = model
        self.reset()
        self.rebuilds = 0
        self.incremental_steps = 0

    def reset(self):
        self.state = self.previous_x = self.previous_mask = None

    @torch.inference_mode()
    def __call__(self, x, mask):
        if self.model.training:
            raise ValueError("state cache requires eval mode")
        x, mask = x[-self.model.n :], mask[-self.model.n :]
        # Compare only meaningful values; masked sentinels have no influence.
        x = torch.where(mask, x, torch.zeros_like(x))
        reusable = (
            self.previous_x is not None
            and len(x) == len(self.previous_x)
            and torch.equal(x[:-1], self.previous_x[1:])
            and torch.equal(mask[:-1], self.previous_mask[1:])
        )
        if reusable:
            zero = x.new_zeros((self.model.layers, 1, self.model.hidden))
            self.state = torch.cat((self.state[:, 1:], zero), dim=1)
            self.state = self.model.step(x[-1:].expand(len(x), -1), mask[-1:].expand(len(x), -1), self.state)
            self.incremental_steps += 1
        else:
            self.state = x.new_zeros((self.model.layers, 0, self.model.hidden))
            for i in range(len(x)):
                zero = x.new_zeros((self.model.layers, 1, self.model.hidden))
                self.state = torch.cat((self.state, zero), dim=1)
                self.state = self.model.step(
                    x[i : i + 1].expand(i + 1, -1), mask[i : i + 1].expand(i + 1, -1), self.state
                )
            self.rebuilds += 1
        self.previous_x, self.previous_mask = x.clone(), mask.clone()
        return self.model.head(self.state[-1, :1])
