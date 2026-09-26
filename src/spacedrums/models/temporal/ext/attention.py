"""Causal multi-head self-attention with a learned relative-position bias (E3).

Position i attends to positions j <= i only; every future position is masked before the softmax.
The bias depends on the distance i - j in frames, so it is independent of the absolute window
start. No bidirectional or future-attending path exists; LayerNorm acts per token (no time mixing).
"""

import math

import torch
from torch import nn


class CausalSelfAttention(nn.Module):
    def __init__(self, width: int, heads: int, n: int):
        super().__init__()
        if width % heads:
            raise ValueError("width must be divisible by the head count")
        self.heads, self.head_width, self.n = heads, width // heads, n
        self.qkv = nn.Linear(width, 3 * width)
        self.out = nn.Linear(width, width)
        self.relative_bias = nn.Parameter(torch.zeros(heads, n))
        index = torch.arange(n)
        distance = index[:, None] - index[None, :]
        self.register_buffer("future", distance < 0)
        self.register_buffer("distance", distance.clamp_min(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        rows, length, width = x.shape
        if length > self.n:
            raise ValueError("sequence longer than the declared history N")
        qkv = self.qkv(x).reshape(rows, length, 3, self.heads, self.head_width).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        scores = q @ k.transpose(-2, -1) / math.sqrt(self.head_width)
        scores = scores + self.relative_bias[:, self.distance[:length, :length]][None]
        scores = scores.masked_fill(self.future[:length, :length][None, None], float("-inf"))
        attended = torch.softmax(scores, dim=-1) @ v
        return self.out(attended.transpose(1, 2).reshape(rows, length, width))
