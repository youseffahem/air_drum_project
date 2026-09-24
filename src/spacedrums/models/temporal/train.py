"""CPU fold training; participant-macro validation ADE selects the checkpoint."""

import copy
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch

from .config import build_model
from .data import epoch_indices, load_fold, sha
from .losses import auxiliary_loss, trajectory_loss


@dataclass(frozen=True)
class TrainConfig:
    seed: int = 10
    epochs: int = 20
    patience: int = 5
    batch_size: int = 64
    learning_rate: float = 0.001
    grad_clip: float = 1.0
    loss: str = "huber"
    step_weighting: str = "uniform"
    velocity_weight: float = 0.0
    lambda_aux: float = 0.0
    positive_ratio: float | None = None
    threads: int = 1

    def __post_init__(self):
        if any(
            type(v) is not int or v < 1 for v in (self.epochs, self.patience, self.batch_size, self.threads)
        ):
            raise ValueError("positive training counts required")
        if self.learning_rate <= 0 or self.grad_clip <= 0 or self.velocity_weight < 0 or self.lambda_aux < 0:
            raise ValueError("invalid optimizer/loss settings")
        if not all(
            math.isfinite(v)
            for v in (self.learning_rate, self.grad_clip, self.velocity_weight, self.lambda_aux)
        ):
            raise ValueError("nonfinite training settings")
        if self.loss not in ("l1", "mse", "huber") or self.step_weighting not in ("uniform", "near", "far"):
            raise ValueError("unknown loss/weighting")


def seed_everything(seed, threads=1):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(True)


@torch.inference_mode()
def predictions(model, sample, batch_size=128):
    model.eval()
    t = sample["tensors"]
    outputs = [
        model(t["x"][i : i + batch_size], t["mask"][i : i + batch_size])
        for i in range(0, sample["count"], batch_size)
    ]
    return torch.cat([o[0] for o in outputs]), torch.cat([o[1] for o in outputs])


def diagnostics(predicted, sample):
    t = sample["tensors"]
    distance = torch.linalg.vector_norm(predicted - t["target"], dim=-1)
    mask = t["target_mask"]
    by_participant = {}
    for participant in sorted({m["participant"] for m in sample["meta"]}):
        rows = torch.tensor([m["participant"] == participant for m in sample["meta"]])
        valid = mask[rows]
        values = distance[rows]
        # Fixed-horizon FDE: only sequences actually observed at the final grid point.
        by_participant[participant] = {
            "ade": float(values[valid].mean()) if valid.any() else None,
            "fde": float(values[:, -1][valid[:, -1]].mean()) if valid[:, -1].any() else None,
            "valid_points": int(valid.sum()),
            "full_horizons": int(valid[:, -1].sum()),
        }
    ades = [r["ade"] for r in by_participant.values() if r["ade"] is not None]
    return {
        "participant_macro_ade": float(np.mean(ades)) if ades else None,
        "by_participant": by_participant,
        "ade": float(distance[mask].mean()) if mask.any() else None,
        "fde": float(distance[:, -1][mask[:, -1]].mean()) if mask[:, -1].any() else None,
        "by_step": [
            {
                "step": j + 1,
                "n": int(mask[:, j].sum()),
                "error": float(distance[:, j][mask[:, j]].mean()) if mask[:, j].any() else None,
            }
            for j in range(mask.shape[1])
        ],
    }


def train_fold(fold_dir, output, config, training, *, provenance, aux_horizon_s=None):
    if config.auxiliary != (training.lambda_aux > 0):
        raise ValueError("auxiliary head must be enabled exactly when lambda_aux > 0")
    train, val, stats = load_fold(fold_dir, config, aux_horizon_s=aux_horizon_s)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    seed_everything(training.seed, training.threads)
    model = build_model(config)
    optimizer = torch.optim.Adam(model.parameters(), lr=training.learning_rate)
    weights = torch.ones(config.k)
    if training.step_weighting == "near":
        weights = torch.arange(config.k, 0, -1, dtype=torch.float32)
    elif training.step_weighting == "far":
        weights = torch.arange(1, config.k + 1, dtype=torch.float32)
    best, best_epoch, state, history = math.inf, -1, None, []
    t = train["tensors"]
    for epoch in range(training.epochs):
        model.train()
        indices = epoch_indices(train, seed=training.seed + epoch, positive_ratio=training.positive_ratio)
        total, batches = 0.0, 0
        for start in range(0, len(indices), training.batch_size):
            ix = indices[start : start + training.batch_size]
            optimizer.zero_grad(set_to_none=True)
            pred, logit = model(t["x"][ix], t["mask"][ix])
            loss = trajectory_loss(
                pred,
                t["target"][ix],
                t["target_mask"][ix],
                kind=training.loss,
                weights=weights,
                velocity_weight=training.velocity_weight,
                dt_step=config.dt_step,
            )
            if training.lambda_aux:
                loss = loss + training.lambda_aux * auxiliary_loss(logit, t["aux"][ix], t["aux_mask"][ix])
            if not torch.isfinite(loss):
                raise ValueError("nonfinite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), training.grad_clip, error_if_nonfinite=True)
            optimizer.step()
            total, batches = total + float(loss.detach()), batches + 1
        pred, _ = predictions(model, val)
        report = diagnostics(pred, val)
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
        "family": config.family,
        "config": config.to_dict(),
        "config_hash": config.config_hash,
        "training": asdict(training),
        "seed": training.seed,
        "N": config.n,
        "K": config.k,
        "dt_step": config.dt_step,
        "F": config.features,
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
        "validation_criterion": "participant_macro_ADE (not training loss); "
        "candidate, not event-level selection",
        "best_epoch": best_epoch,
        "best_validation_score": best,
        "checkpoint_hash": sha(output / "checkpoint.pt"),
        "target_grid": "linear interpolation on contiguous observed causal targets; no extrapolation",
        "normalization": "already applied by Phase 08; verified fold provenance; no second normalization",
        "aux_horizon_s": aux_horizon_s,
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "parameter_bytes": sum(p.numel() * p.element_size() for p in model.parameters()),
    }
    manifest["model_id"] = (
        f"{config.family}-fold{stats['fold']}-seed{training.seed}-{manifest['checkpoint_hash'][7:19]}"
    )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    return model, manifest, val
