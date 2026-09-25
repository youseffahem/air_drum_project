"""Masked primary trajectory objective, optional velocity/auxiliary losses and Phase 11 tasks."""

import math

import torch
from torch import nn
from torch.nn import functional as F


def trajectory_loss(pred, target, mask, *, kind="huber", weights=None, velocity_weight=0.0, dt_step=1.0):
    if pred.shape != target.shape or mask.shape != pred.shape[:-1]:
        raise ValueError("trajectory/mask shapes disagree")
    if dt_step <= 0 or velocity_weight < 0:
        raise ValueError("invalid velocity parameters")
    # Select before arithmetic, so a masked NaN/Inf target cannot poison gradients.
    clean = torch.where(mask[..., None], target, pred.detach())
    if kind == "l1":
        error = (pred - clean).abs()
    elif kind == "mse":
        error = (pred - clean).square()
    elif kind == "huber":
        error = F.smooth_l1_loss(pred, clean, reduction="none")
    else:
        raise ValueError("unknown trajectory loss")
    weight = torch.ones(pred.shape[1], device=pred.device) if weights is None else weights.to(pred)
    if weight.shape != (pred.shape[1],) or not torch.isfinite(weight).all() or (weight < 0).any():
        raise ValueError("invalid step weights")
    effective = mask.to(pred.dtype) * weight
    loss = (error.mean(-1) * effective).sum() / effective.sum().clamp_min(1e-12)
    if velocity_weight:
        pair = mask[:, 1:] & mask[:, :-1]
        residual = ((pred[:, 1:] - pred[:, :-1]) - (clean[:, 1:] - clean[:, :-1])) / dt_step
        speed_loss = torch.where(pair[..., None], residual.square(), torch.zeros_like(residual))
        loss = loss + velocity_weight * speed_loss.sum() / (2 * pair.sum()).clamp_min(1)
    return loss


def auxiliary_loss(logit, target, mask):
    if not mask.any():
        return logit.sum() * 0.0
    return F.binary_cross_entropy_with_logits(logit[mask], target[mask])


def _regression(pred, target, kind):
    if kind == "l1":
        return F.l1_loss(pred, target)
    if kind == "mse":
        return F.mse_loss(pred, target)
    if kind == "huber":
        return F.smooth_l1_loss(pred, target)
    raise ValueError("unknown regression loss")


def masked_regression(pred, target, mask, *, kind="huber"):
    """Mean over labelled rows only; indexing never touches unlabelled targets (no imputation)."""
    if pred.shape[0] != target.shape[0] or mask.shape != pred.shape[:1]:
        raise ValueError("regression rows/mask disagree")
    if not mask.any():
        return pred.sum() * 0.0
    return _regression(pred[mask], target[mask], kind)


def tti_loss(output, tti_s, mask, *, mode, h_max_s, kind="huber"):
    """Time-to-impact inside H_max, scaled by H_max: direct, log-time or bin classification."""
    if not mask.any():
        return output.sum() * 0.0
    scaled = tti_s[mask] / h_max_s
    if not torch.isfinite(scaled).all() or (scaled <= 0).any() or (scaled > 1 + 1e-6).any():
        raise ValueError("labelled TTI must lie in (0, H_max]")
    rows = output[mask]
    if mode == "direct":
        return _regression(rows[:, 0], scaled, kind)
    if mode == "log":
        return _regression(rows[:, 0], torch.log(scaled.clamp_min(1e-3)), kind)
    if mode == "bins":
        bins = rows.shape[1]
        index = (scaled * bins).floor().clamp(0, bins - 1).long()
        return F.cross_entropy(rows, index)
    raise ValueError("unknown TTI parameterisation")


def decode_tti(output, *, mode, h_max_s):
    """Seconds from t_ref, clipped to the supervised interval [0, H_max]."""
    if mode == "direct":
        scaled = output[:, 0].clamp(0.0, 1.0)
    elif mode == "log":
        scaled = torch.exp(output[:, 0]).clamp(max=1.0)
    elif mode == "bins":
        centres = (torch.arange(output.shape[1], dtype=output.dtype) + 0.5) / output.shape[1]
        scaled = torch.softmax(output, dim=-1) @ centres
    else:
        raise ValueError("unknown TTI parameterisation")
    return scaled * h_max_s


def zone_loss(logits, index, mask):
    if not mask.any():
        return logits.sum() * 0.0
    return F.cross_entropy(logits[mask], index[mask])


WEIGHTINGS = ("fixed", "trajectory_dominant", "uncertainty", "gradnorm")


class TaskWeighting(nn.Module):
    """Combines the present task losses of one batch.

    fixed: declared lambda per task. trajectory_dominant: lambda_traj = 1, every other task
    ``dominant_lambda``. uncertainty: learned log-variances s_t, sum exp(-s_t) L_t + s_t over the
    tasks labelled in the batch (the regulariser of an absent task is not applied, so masking
    cannot drive its weight up). gradnorm: positive weights updated only by the GradNorm step in
    ``mt_train``; the model loss uses them detached.
    """

    def __init__(self, tasks, scheme, *, lambdas=None, dominant_lambda=0.05):
        super().__init__()
        if scheme not in WEIGHTINGS:
            raise ValueError(f"weighting must be one of {WEIGHTINGS}")
        self.tasks, self.scheme = tuple(tasks), scheme
        lambdas = dict(lambdas or {})
        if set(lambdas) - set(self.tasks):
            raise ValueError("lambda for an absent task")
        if scheme == "trajectory_dominant":
            if "trajectory" not in self.tasks or not 0 < dominant_lambda <= 1:
                raise ValueError("trajectory-dominant weighting needs the trajectory task")
            lambdas = {t: 1.0 if t == "trajectory" else dominant_lambda for t in self.tasks}
        self.fixed = {t: float(lambdas.get(t, 1.0)) for t in self.tasks}
        if any(not math.isfinite(v) or v < 0 for v in self.fixed.values()):
            raise ValueError("task weights must be finite and nonnegative")
        self.log_vars = nn.Parameter(torch.zeros(len(self.tasks))) if scheme == "uncertainty" else None
        self.weights = nn.Parameter(torch.ones(len(self.tasks))) if scheme == "gradnorm" else None

    def weight(self, task):
        i = self.tasks.index(task)
        if self.scheme == "uncertainty":
            return torch.exp(-self.log_vars[i])
        if self.scheme == "gradnorm":
            return self.weights[i]
        return torch.tensor(self.fixed[task])

    def forward(self, losses):
        total = None
        for task in self.tasks:
            if task not in losses:
                continue
            if self.scheme == "uncertainty":
                i = self.tasks.index(task)
                term = torch.exp(-self.log_vars[i]) * losses[task] + self.log_vars[i]
            elif self.scheme == "gradnorm":
                term = self.weights[self.tasks.index(task)].detach() * losses[task]
            else:
                term = self.fixed[task] * losses[task]
            total = term if total is None else total + term
        if total is None:
            raise ValueError("no labelled task in batch")
        return total

    def renormalise(self):
        if self.scheme == "gradnorm":
            with torch.no_grad():
                self.weights.clamp_(min=1e-3)
                self.weights.mul_(len(self.tasks) / self.weights.sum())

    def current(self):
        return {t: float(self.weight(t).detach()) for t in self.tasks}
