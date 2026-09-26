"""E2 trajectory representations and the Phase 10 displacement head in the extension layout.

Every head returns ``(point [B,K,2], aux [B,A])`` so export parity, batching and latency reuse the
Phase 10 code. ``point`` is the displacement trajectory geometry consumes (for a mixture: the most
probable mode). ``aux`` layouts: displacement -> [B,1] zeros (the Phase 10 logit slot); velocity and
polynomial -> per-step velocities [B,2K] in ROI/s; mixture -> [mode logits (M) | modes (M*K*2)].
"""

import torch
from torch import nn
from torch.nn import functional as F


class DisplacementHead(nn.Module):
    """Phase 10 layout: the Linear(hidden, 2K) layer is created first, so parameters draw identically."""

    def __init__(self, hidden: int, k: int):
        super().__init__()
        self.k = k
        self.trajectory = nn.Linear(hidden, 2 * k)

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return self.trajectory(hidden).reshape(-1, self.k, 2), hidden[:, :1] * 0.0


class IncrementHead(nn.Module):
    """E2(a): per-step increments integrated by a cumulative sum; velocity = increment / interval."""

    def __init__(self, hidden: int, offsets_s: tuple[float, ...]):
        super().__init__()
        self.k = len(offsets_s)
        self.increments = nn.Linear(hidden, 2 * self.k)
        times = torch.tensor((0.0, *offsets_s), dtype=torch.float32)
        self.register_buffer("intervals", times[1:] - times[:-1])

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        increments = self.increments(hidden).reshape(-1, self.k, 2)
        velocities = increments / self.intervals.reshape(1, -1, 1)
        return torch.cumsum(increments, dim=1), velocities.reshape(-1, 2 * self.k)


class PolynomialHead(nn.Module):
    """E2(b): p(tau) = sum_{d=1..D} c_d (tau/H)^d per axis; zero at tau = 0; analytic velocities."""

    def __init__(self, hidden: int, offsets_s: tuple[float, ...], degree: int):
        super().__init__()
        self.k, self.degree = len(offsets_s), degree
        self.coefficients = nn.Linear(hidden, 2 * degree)
        horizon = offsets_s[-1]
        u = torch.tensor(offsets_s, dtype=torch.float64)[:, None] / horizon
        powers = torch.arange(1, degree + 1, dtype=torch.float64)[None, :]
        self.register_buffer("basis", (u**powers).float())
        self.register_buffer("velocity_basis", (powers * u ** (powers - 1) / horizon).float())

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        coefficients = self.coefficients(hidden).reshape(-1, 2, self.degree)
        point = torch.einsum("kd,bad->bka", self.basis, coefficients)
        velocities = torch.einsum("kd,bad->bka", self.velocity_basis, coefficients)
        return point, velocities.reshape(-1, 2 * self.k)


class MixtureHead(nn.Module):
    """E2(c): M displacement trajectories and their logits; the point is the most probable mode."""

    def __init__(self, hidden: int, k: int, modes: int):
        super().__init__()
        self.k, self.modes = k, modes
        self.trajectories = nn.Linear(hidden, modes * 2 * k)
        self.logits = nn.Linear(hidden, modes)

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        rows = hidden.shape[0]
        trajectories = self.trajectories(hidden).reshape(rows, self.modes, self.k, 2)
        logits = self.logits(hidden)
        best = torch.argmax(logits, dim=1)
        point = trajectories[torch.arange(rows), best]
        return point, torch.cat((logits, trajectories.reshape(rows, -1)), dim=1)


def mixture_parts(aux, *, modes, k):
    """(logits [B,M], trajectories [B,M,K,2]) from the mixture aux layout."""
    if aux.shape[-1] != modes + modes * k * 2:
        raise ValueError("mixture aux width does not match modes/K")
    return aux[:, :modes], aux[:, modes:].reshape(-1, modes, k, 2)


def _elementwise(pred, target, kind):
    if kind == "l1":
        return (pred - target).abs()
    if kind == "mse":
        return (pred - target).square()
    if kind == "huber":
        return F.smooth_l1_loss(pred, target, reduction="none")
    raise ValueError("unknown trajectory loss")


def mixture_loss(aux, target, mask, *, modes, k, kind="huber", epsilon=0.05, mode_weight=0.5):
    """Relaxed winner-takes-all over modes plus cross-entropy of the logits on the winning mode.

    Per sample and mode: the masked mean trajectory error (the Phase 10 elementwise loss). The winner
    (lowest error, first index on ties) gets weight 1 - epsilon, every other mode epsilon / (M - 1).
    Samples without any valid target step are excluded; masked NaN targets never reach arithmetic.
    """
    if target.shape != (aux.shape[0], k, 2) or mask.shape != target.shape[:-1]:
        raise ValueError("mixture target/mask shapes disagree")
    logits, trajectories = mixture_parts(aux, modes=modes, k=k)
    clean = torch.where(mask[:, None, :, None], target[:, None], trajectories.detach())
    error = _elementwise(trajectories, clean, kind).mean(-1)
    counts = mask.sum(1)
    per_mode = (error * mask[:, None, :].to(error.dtype)).sum(-1) / counts.clamp_min(1)[:, None]
    valid = counts > 0
    if not valid.any():
        return aux.sum() * 0.0
    winner = per_mode.detach().argmin(dim=1)
    weights = torch.full_like(per_mode, epsilon / (modes - 1))
    weights.scatter_(1, winner[:, None], 1.0 - epsilon)
    wta = (per_mode * weights).sum(1)[valid].mean()
    return wta + mode_weight * F.cross_entropy(logits[valid], winner[valid])


def mixture_weights(logits):
    return torch.softmax(logits, dim=-1)
