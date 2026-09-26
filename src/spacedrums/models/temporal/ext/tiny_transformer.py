"""E3 Tiny Transformer encoder (arm C-TT): causal, windowed, CPU-sized.

Tokens are the Phase 10 masked inputs ``[x * mask, mask]`` of the last N frames; the time features
``dt`` and ``window_elapsed`` travel inside each token, relative position enters as a learned
attention bias. Pre-LayerNorm residual blocks; the last position (the current frame) is read out.
"""

import torch
from torch import nn

from ..heads import masked_inputs
from .attention import CausalSelfAttention


class Block(nn.Module):
    def __init__(self, width: int, heads: int, feedforward: int, n: int, dropout: float):
        super().__init__()
        self.norm_attention = nn.LayerNorm(width)
        self.attention = CausalSelfAttention(width, heads, n)
        self.norm_feedforward = nn.LayerNorm(width)
        self.feedforward = nn.Sequential(
            nn.Linear(width, feedforward), nn.GELU(), nn.Linear(feedforward, width), nn.Dropout(dropout)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attention(self.norm_attention(x))
        return x + self.feedforward(self.norm_feedforward(x))


class TinyTransformerPredictor(nn.Module):
    def __init__(self, config, head_factory):
        super().__init__()
        self.n = config.n
        self.embed = nn.Linear(config.features * 2, config.hidden)
        self.blocks = nn.ModuleList(
            [
                Block(config.hidden, config.attention_heads, config.feedforward, config.n, config.dropout)
                for _ in range(config.layers)
            ]
        )
        self.norm = nn.LayerNorm(config.hidden)
        self.head = head_factory()

    @torch.jit.export
    def encode(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        h = self.embed(masked_inputs(x, mask))
        for block in self.blocks:
            h = block(h)
        return self.norm(h)

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        encoded = self.encode(x[:, -self.n :], mask[:, -self.n :])
        return self.head(encoded[:, -1])
