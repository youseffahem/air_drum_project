"""Extension fold training: the Phase 10 loop with the declared per-extension objective.

Selection keeps the Phase 10 criterion (participant-macro validation ADE of the point trajectory
that geometry consumes: the mean, or the most probable mode). A configuration without an extension
reproduces ``train.train_fold`` bit for bit (tested), so every difference is the extension's.
"""

import copy
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from ..data import epoch_indices, load_fold, sha
from ..losses import trajectory_loss
from ..train import diagnostics, predictions, seed_everything
from .long_horizon import error_by_offset, select_grid
from .model import build_extension_model
from .representations import mixture_loss, mixture_parts
from .uncertainty import gaussian_nll


def step_weights(training, k):
    if training.step_weighting == "near":
        return torch.arange(k, 0, -1, dtype=torch.float32)
    if training.step_weighting == "far":
        return torch.arange(1, k + 1, dtype=torch.float32)
    return torch.ones(k)


def extension_loss(config, training, outputs, target, mask, weights):
    point, aux = outputs
    if config.representation == "mixture":
        return mixture_loss(
            aux,
            target,
            mask,
            modes=config.modes,
            k=config.k,
            kind=training.loss,
            epsilon=config.wta_epsilon,
            mode_weight=config.mode_weight,
        )
    loss = trajectory_loss(
        point,
        target,
        mask,
        kind=training.loss,
        weights=weights,
        velocity_weight=training.velocity_weight,
        dt_step=config.dt_step,
    )
    if config.uncertainty == "gaussian":
        loss = loss + gaussian_nll(point.detach(), aux, target, mask)
    return loss


def residual_statistics(config, stats):
    """Train-fold centre/scale of the declared velocity (acceleration) features."""
    if not config.residual:
        return None, None
    names = stats.get("names")
    if (
        names is not None
        and [names[i] for i in config.residual_features]
        != ["vx", "vy", "ax", "ay"][: len(config.residual_features)]
    ):
        raise ValueError("residual features must be (vx, vy[, ax, ay]) of the fs-v1 layout")
    if not all(stats["usable"][i] for i in config.residual_features):
        raise ValueError("residual feature has no training statistics")
    return (
        [float(stats["center"][i]) for i in config.residual_features],
        [float(stats["scale"][i]) for i in config.residual_features],
    )


def mixture_diagnostics(config, aux, sample):
    """Best-of-M and most-probable displacement errors (reported, never deciding)."""
    logits, trajectories = mixture_parts(aux, modes=config.modes, k=config.k)
    t = sample["tensors"]
    distance = torch.linalg.vector_norm(trajectories - t["target"][:, None], dim=-1)
    mask = t["target_mask"]
    valid = mask.any(1)
    per_mode = (distance * mask[:, None]).sum(-1) / mask.sum(1).clamp_min(1)[:, None]
    best = per_mode.argmin(1)
    rows = torch.arange(len(best))
    probable = logits.argmax(1)
    final = mask[:, -1]
    out = {
        "best_of_m_ade": float(per_mode[rows, best][valid].mean()) if valid.any() else None,
        "most_probable_ade": float(per_mode[rows, probable][valid].mean()) if valid.any() else None,
        "best_of_m_fde": float(distance[rows, best, -1][final].mean()) if final.any() else None,
        "most_probable_fde": float(distance[rows, probable, -1][final].mean()) if final.any() else None,
        "mode_share": torch.bincount(probable, minlength=config.modes).tolist(),
    }
    return out


def validation_report(config, model, sample):
    point, aux = predictions(model, sample)
    report = diagnostics(point, sample)
    report["error_by_offset"] = error_by_offset(point.numpy(), sample)
    if config.representation == "mixture":
        report["mixture"] = mixture_diagnostics(config, aux, sample)
    return report


def train_extension_fold(fold_dir, output, config, training, *, provenance, variant):
    if training.lambda_aux:
        raise ValueError("extension models carry no Phase 10 auxiliary logit")
    if training.velocity_weight and not config.uniform:
        raise ValueError("the velocity-consistency term assumes a uniform output grid")
    train, val, stats = load_fold(fold_dir, config.data_view)
    for sample in (train, val):
        select_grid(sample, config)
    center, scale = residual_statistics(config, stats)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    seed_everything(training.seed, training.threads)
    model = build_extension_model(config, residual_center=center, residual_scale=scale)
    optimizer = torch.optim.Adam(model.parameters(), lr=training.learning_rate)
    weights = step_weights(training, config.k)
    best, best_epoch, state, history = math.inf, -1, None, []
    t = train["tensors"]
    for epoch in range(training.epochs):
        model.train()
        indices = epoch_indices(train, seed=training.seed + epoch, positive_ratio=training.positive_ratio)
        total, batches = 0.0, 0
        for start in range(0, len(indices), training.batch_size):
            ix = indices[start : start + training.batch_size]
            optimizer.zero_grad(set_to_none=True)
            outputs = model(t["x"][ix], t["mask"][ix])
            loss = extension_loss(config, training, outputs, t["target"][ix], t["target_mask"][ix], weights)
            if not torch.isfinite(loss):
                raise ValueError("nonfinite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), training.grad_clip, error_if_nonfinite=True)
            optimizer.step()
            total, batches = total + float(loss.detach()), batches + 1
        report = validation_report(config, model, val)
        score = report["participant_macro_ade"]
        if score is None or not math.isfinite(score):
            raise ValueError("no finite validation criterion")
        history.append(
            {
                "epoch": epoch,
                "train_loss": total / batches,
                "validation": report,
                "sampled_windows": len(indices),
            }
        )
        if score < best:
            best, best_epoch, state = score, epoch, copy.deepcopy(model.state_dict())
        (output / "training.json").write_text(
            json.dumps(history, indent=2, allow_nan=False), encoding="utf-8"
        )
        if epoch - best_epoch >= training.patience:
            break
    model.load_state_dict(state)
    model.eval()
    torch.save(model.state_dict(), output / "checkpoint.pt")
    manifest = {
        **provenance,
        "variant": variant,
        "extensions": list(config.extensions),
        "family": config.family,
        "ext_config": config.to_dict(),
        "config_hash": config.config_hash,
        "training": asdict(training),
        "seed": training.seed,
        "N": config.n,
        "K": config.k,
        "dt_step": config.dt_step,
        "offsets_s": list(config.offsets_s),
        "horizon_s": config.horizon_s,
        "F": config.features,
        "representation": config.representation,
        "uncertainty_kind": config.uncertainty_kind,
        "residual": config.residual,
        "residual_statistics": None if center is None else {"center": center, "scale": scale},
        "feature_schema_id": stats["feature_schema_id"],
        "feature_schema_hash": stats["feature_schema_hash"],
        "norm_stats_id": sha(Path(fold_dir) / "norm_stats.json"),
        "fold": stats["fold"],
        "dataset_version": stats["dataset_version"],
        "dataset_hash": stats["dataset_hash"],
        "split_hash": stats["split_hash"],
        "source_kind": stats["source_kind"],
        "train_participants": stats["train_participants"],
        "val_participants": sorted({m["participant"] for m in val["meta"]}),
        "train_samples_hash": train["hash"],
        "val_samples_hash": val["hash"],
        "sample_counts": {"train": train["count"], "val": val["count"]},
        "positive_counts": {"train": train["positives"], "val": val["positives"]},
        "validation_criterion": "participant_macro_ADE of the point trajectory (Phase 10 criterion)",
        "best_epoch": best_epoch,
        "best_validation_score": best,
        "checkpoint_hash": sha(output / "checkpoint.pt"),
        "target_grid": "Phase 10 fixed grid up to the largest step; declared step columns selected",
        "normalization": "already applied by Phase 08; verified fold provenance; no second normalization",
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "parameter_bytes": sum(p.numel() * p.element_size() for p in model.parameters()),
    }
    manifest["model_id"] = (
        f"ext-{variant}-{config.family}-fold{stats['fold']}-seed{training.seed}-{manifest['checkpoint_hash'][7:19]}"
    )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    return model, manifest, train, val


def training_targets(sample):
    """Observed training targets for the train-only E5(b) acceleration bound."""
    t = sample["tensors"]
    return t["target"].numpy(), t["target_mask"].numpy(), np.asarray(sample["offsets_s"])
