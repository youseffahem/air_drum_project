"""Controlled Phase 11 multi-task models for route tests (SYNTHETIC; no learned accuracy)."""

import torch

from spacedrums.contracts import TrackState
from spacedrums.models.temporal.config import TASKS, MultiTaskConfig, TemporalConfig, build_mt_model

ZONES = ("hihat", "snare", "tom1", "crash_ride")


def track(i, y, hand="LEFT", status="VALID"):
    live = status in ("VALID", "DEGRADED")
    return TrackState(
        i,
        10 + i * 0.02,
        hand,
        status,
        "synthetic",
        None,
        (0.4, y) if live else None,
        (0.0, 1.0) if live else None,
        (0.0, 0.0) if live else None,
        None,
        None,
        1.0,
        0 if status == "VALID" else 1,
        10 + i * 0.02,
        None,
        None,
    )


def mt_config(family="gru", heads=TASKS, *, features=56, n=2, k=4, dt=0.02, tti_mode="direct", h_max=0.3):
    base = TemporalConfig(family, features, n=n, k=k, dt_step=dt, hidden=8)
    return MultiTaskConfig(
        base, heads=heads, zone_ids=ZONES if "zone" in heads else (), tti_mode=tti_mode, h_max_s=h_max
    )


def controlled(
    config, *, crossing=True, p_logit=10.0, tti_scaled=0.1, zone="snare", impact=(0.0, 0.1), intensity=0.0
):
    """Zero weights, chosen biases: every head emits a fixed, known value."""
    model = build_mt_model(config).eval()
    head = model.head
    with torch.no_grad():
        if head.use_trajectory:
            head.trajectory.weight.zero_()
            step = torch.tensor([0.0, 0.05]) * (1 if crossing else -1)
            head.trajectory.bias.copy_(torch.cat([step * (j + 1) for j in range(config.base.k)]))
        if head.use_strike:
            head.strike.weight.zero_()
            head.strike.bias.fill_(p_logit)
        if head.use_tti:
            head.tti.weight.zero_()
            head.tti.bias.fill_(tti_scaled)
        if head.use_zone:
            head.zone.weight.zero_()
            head.zone.bias.copy_(torch.tensor([5.0 if z == zone else 0.0 for z in ZONES]))
        if head.use_position:
            head.position.weight.zero_()
            head.position.bias.copy_(torch.tensor(impact))
        if head.use_intensity:
            head.intensity.weight.zero_()
            head.intensity.bias.fill_(intensity)
    return model


def manifest(config, *, scale=1.0, center=0.0):
    return {
        "family": config.family,
        "N": config.base.n,
        "K": config.base.k,
        "F": config.base.features,
        "dt_step": config.base.dt_step,
        "config": config.base.to_dict(),
        "mt_config": config.to_dict(),
        "heads": list(config.heads),
        "live_eligible": config.live_eligible,
        "target_scaling": {"intensity": {"center": center, "scale": scale, "n": 0, "fit": "test"}},
        "checkpoint_hash": "sha256:" + "3" * 64,
        "seed": 0,
    }
