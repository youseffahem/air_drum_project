"""Masked primary trajectory objective; optional velocity and auxiliary losses."""

import torch
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
