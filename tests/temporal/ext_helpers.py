"""Controlled Phase 12 extension models for route and propagation tests (SYNTHETIC; no accuracy)."""

import math

import torch

from spacedrums.models.temporal.ext import ExtensionConfig, build_extension_model

VARIANT_KWARGS = {
    "ref": {},
    "two-rate": {"k": 3, "steps": (1, 2, 4)},
    "velocity": {"representation": "velocity"},
    "polynomial": {"representation": "polynomial"},
    "mixture": {"representation": "mixture", "modes": 2},
    "tt": {"family": "tt", "layers": 2},
    "gaussian": {"uncertainty": "gaussian"},
    "residual-cv": {"residual": "cv", "residual_features": (10, 11)},
    "residual-ca": {"residual": "ca", "residual_features": (10, 11, 20, 21)},
}


def ext_config(variant="ref", family="gru", *, features=56, n=2, k=4, dt=0.02, hidden=8):
    kwargs = {"family": family, "features": features, "n": n, "k": k, "dt_step": dt, "hidden": hidden}
    kwargs.update(VARIANT_KWARGS[variant])
    if kwargs["family"] == "tt":
        kwargs["attention_heads"] = 2
        kwargs["feedforward"] = 8
    return ExtensionConfig(**kwargs)


def _inner(model):
    return model.inner if hasattr(model, "inner") else model


def controlled(config, *, crossing=True, sigma=0.01, logits=(2.0, 0.0)):
    """Zero weights and chosen biases: the point trajectory steps 0.05 ROI per output step
    downwards (crossing) or upwards; the second mixture mode always moves upwards."""
    model = build_extension_model(config).eval()
    head = _inner(model).head
    sign = 1.0 if crossing else -1.0
    step = torch.cat([torch.tensor([0.0, 0.05 * sign * (j + 1)]) for j in range(config.k)])
    with torch.no_grad():
        if config.representation == "mixture":
            head.trajectories.weight.zero_()
            head.logits.weight.zero_()
            head.trajectories.bias.copy_(torch.cat((step, -step.abs())))
            head.logits.bias.copy_(torch.tensor(logits))
        elif config.representation == "displacement":
            head.trajectory.weight.zero_()
            head.trajectory.bias.copy_(step)
            if config.uncertainty == "gaussian":
                head.log_sigma.weight.zero_()
                head.log_sigma.bias.fill_(math.log(sigma))
        else:
            raise ValueError("controlled models cover displacement, Gaussian and mixture heads")
    return model


def manifest(config, *, variant="test", fold=0, seed=0, checkpoint="3"):
    return {
        "variant": variant,
        "extensions": list(config.extensions),
        "family": config.family,
        "N": config.n,
        "K": config.k,
        "F": config.features,
        "dt_step": config.dt_step,
        "offsets_s": list(config.offsets_s),
        "ext_config": config.to_dict(),
        "config_hash": config.config_hash,
        "fold": fold,
        "seed": seed,
        "feature_schema_hash": "sha256:" + "1" * 64,
        "norm_stats_id": "sha256:" + "2" * 64,
        "checkpoint_hash": "sha256:" + checkpoint * 64,
    }
