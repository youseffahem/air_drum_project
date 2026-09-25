"""Multi-task fold training over the Phase 10 encoders (Tasks 11.1-11.3).

The loop is the Phase 10 loop with extra masked task losses: a trajectory-only configuration
with fixed weights reproduces ``train.train_fold`` exactly. Missing labels are masked per
sample per task (no imputation). Checkpoint selection keeps the Phase 10 criterion
(participant-macro validation ADE) whenever the trajectory head exists, so a head can change
the encoder but never the stopping rule; the no-trajectory diagnostic uses the unweighted
validation head loss instead.
"""

import copy
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch

from .config import build_mt_model
from .data import epoch_indices, load_fold, sha
from .heads import decode_heads
from .losses import (
    WEIGHTINGS,
    TaskWeighting,
    auxiliary_loss,
    masked_regression,
    trajectory_loss,
    tti_loss,
    zone_loss,
)
from .train import diagnostics, seed_everything


@dataclass(frozen=True)
class MultiTaskLossConfig:
    weighting: str = "fixed"
    lambdas: tuple[tuple[str, float], ...] = ()
    dominant_lambda: float = 0.05
    gradnorm_alpha: float = 1.5
    gradnorm_lr: float = 0.025
    tti_loss: str = "huber"
    position_loss: str = "l1"
    intensity_loss: str = "huber"
    conflict_every: int = 0

    def __post_init__(self):
        object.__setattr__(self, "lambdas", tuple((str(k), float(v)) for k, v in dict(self.lambdas).items()))
        if self.weighting not in WEIGHTINGS:
            raise ValueError(f"weighting must be one of {WEIGHTINGS}")
        if self.tti_loss not in ("l1", "huber") or self.intensity_loss not in ("l1", "huber"):
            raise ValueError("TTI/intensity regression must be L1 or Huber")
        if self.position_loss not in ("l1", "mse"):
            raise ValueError("position loss must be L1 or L2 (mse)")
        values = (self.dominant_lambda, self.gradnorm_alpha, self.gradnorm_lr)
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("weighting hyperparameters must be positive and finite")
        if type(self.conflict_every) is not int or self.conflict_every < 0:
            raise ValueError("conflict_every must be a nonnegative integer")

    def to_dict(self):
        return {**asdict(self), "lambdas": dict(self.lambdas)}


def _targets(sample, config, *, aux_horizon_s):
    heads, aux, n = set(config.heads), sample["aux_records"], sample["count"]
    base = config.base
    if "strike" in heads and (aux_horizon_s is None or abs(aux_horizon_s - base.k * base.dt_step) > 1e-9):
        raise ValueError("strike head requires the exported H to equal K * dt_step; regenerate windows")
    impact = np.array([bool(a["impact_mask"]) for a in aux])
    if any(bool(a["tti_mask"]) != m for a, m in zip(aux, impact, strict=True)):
        raise ValueError("Phase 08 TTI and impact masks disagree")
    tti = np.array([float(a["tti"]) for a in aux])
    if impact.any() and (
        not np.isfinite(tti[impact]).all()
        or (tti[impact] <= 0).any()
        or (tti[impact] > config.h_max_s + 1e-9).any()
    ):
        raise ValueError("labelled TTI outside (0, H_max]; declare the H_max used by Phase 08")
    zone = np.zeros(n, dtype=np.int64)
    if "zone" in heads:
        for i in np.flatnonzero(impact):
            if aux[i]["zone_id"] not in config.zone_ids:
                raise ValueError(f"label zone {aux[i]['zone_id']!r} outside declared zone_ids")
            zone[i] = config.zone_ids.index(aux[i]["zone_id"])
    position = np.zeros((n, 2))
    intensity = np.zeros(n)
    for i in np.flatnonzero(impact):
        position[i] = np.asarray(aux[i]["impact_pos"], dtype=float) - sample["anchor"][i]
        intensity[i] = float(aux[i]["intensity"])
    if not (np.isfinite(position[impact]).all() and np.isfinite(intensity[impact]).all()):
        raise ValueError("nonfinite labelled impact position/intensity")
    mask = torch.tensor(impact)
    return {
        "tti": torch.tensor(tti, dtype=torch.float32),
        "zone": torch.tensor(zone),
        "position": torch.tensor(position, dtype=torch.float32),
        "intensity": torch.tensor(intensity, dtype=torch.float32),
        "impact_mask": mask,
    }


def _counts(sample, targets, config):
    t, impact = sample["tensors"], targets["impact_mask"]
    counts = {
        "samples": sample["count"],
        "strike_labelled": int(t["aux_mask"].sum()),
        "strike_positive": int(t["aux"][t["aux_mask"]].sum()),
        "impact_labelled": int(impact.sum()),
        "participants": len({m["participant"] for m in sample["meta"]}),
    }
    if "zone" in config.heads:
        zones = targets["zone"][impact].tolist()
        counts["zone_labelled"] = {z: zones.count(i) for i, z in enumerate(config.zone_ids)}
    return counts


def target_scaling(train):
    """Train-fold-only intensity standardisation; never fitted on validation or test."""
    impact = train["mt"]["impact_mask"]
    values = train["mt"]["intensity"][impact].numpy().astype(float)
    center = float(np.median(values)) if len(values) else 0.0
    scale = float(np.std(values)) if len(values) >= 2 else 0.0
    return {
        "intensity": {
            "center": center,
            "scale": scale if scale > 1e-9 else 1.0,
            "n": len(values),
            "fit": "train fold impact rows only",
        }
    }


def load_mt_fold(fold_dir, config, *, aux_horizon_s=None):
    train, val, stats = load_fold(fold_dir, config.base)
    for sample in (train, val):
        sample["mt"] = _targets(sample, config, aux_horizon_s=aux_horizon_s)
        sample["mt_counts"] = _counts(sample, sample["mt"], config)
    return train, val, stats


def task_losses(outputs, sample, ix, config, loss, training, scaling, step_weights):
    """Losses of every enabled task that has at least one label in the rows ``ix``."""
    trajectory, strike, tti, zone, position, intensity = outputs
    t, m, heads, losses = sample["tensors"], sample["mt"], set(config.heads), {}
    if "trajectory" in heads:
        losses["trajectory"] = trajectory_loss(
            trajectory,
            t["target"][ix],
            t["target_mask"][ix],
            kind=training.loss,
            weights=step_weights,
            velocity_weight=training.velocity_weight,
            dt_step=config.base.dt_step,
        )
    if "strike" in heads and t["aux_mask"][ix].any():
        losses["strike"] = auxiliary_loss(strike, t["aux"][ix], t["aux_mask"][ix])
    impact = m["impact_mask"][ix]
    if not impact.any():
        return losses
    if "tti" in heads:
        losses["tti"] = tti_loss(
            tti, m["tti"][ix], impact, mode=config.tti_mode, h_max_s=config.h_max_s, kind=loss.tti_loss
        )
    if "zone" in heads:
        losses["zone"] = zone_loss(zone, m["zone"][ix], impact)
    if "position" in heads:
        losses["position"] = masked_regression(position, m["position"][ix], impact, kind=loss.position_loss)
    if "intensity" in heads:
        s = scaling["intensity"]
        target = (m["intensity"][ix] - s["center"]) / s["scale"]
        losses["intensity"] = masked_regression(intensity, target, impact, kind=loss.intensity_loss)
    return losses


def encoder_parameters(model):
    return [p for name, p in model.named_parameters() if not name.startswith("head.")]


def last_shared_parameters(model):
    """GradNorm's shared layer: the last GRU layer, or the last TCN residual convolution."""
    if hasattr(model, "gru"):
        suffix = f"_l{model.layers - 1}"
        return [p for name, p in model.gru.named_parameters() if name.endswith(suffix)]
    return list(model.blocks[-1].second.parameters())


def _flat_grad(loss, params):
    grads = torch.autograd.grad(loss, params, retain_graph=True, allow_unused=True)
    flat = [(torch.zeros_like(p) if g is None else g).reshape(-1) for p, g in zip(params, grads, strict=True)]
    return torch.cat(flat)


def _conflicts(losses, params, weighting, *, epoch, step):
    reference = _flat_grad(losses["trajectory"], params)
    row = {"epoch": epoch, "step": step, "trajectory_norm": float(reference.norm()), "tasks": {}}
    for task, value in losses.items():
        if task == "trajectory":
            continue
        grad = _flat_grad(value, params)
        denominator = float(grad.norm() * reference.norm())
        row["tasks"][task] = {
            "cosine": float(grad @ reference) / denominator if denominator > 0 else None,
            "norm_ratio": float(grad.norm() / reference.norm()) if float(reference.norm()) > 0 else None,
            "weight": float(weighting.weight(task).detach()),
        }
    row["trajectory_weight"] = float(weighting.weight("trajectory").detach())
    return row


def _gradnorm_step(model, losses, weighting, initial, alpha):
    present = [t for t in weighting.tasks if t in losses]
    for task in present:
        initial.setdefault(task, max(float(losses[task].detach()), 1e-12))
    if len(present) < 2:
        return None
    shared = last_shared_parameters(model)
    raw = torch.stack([_flat_grad(losses[t], shared).norm() for t in present]).detach()
    index = torch.tensor([weighting.tasks.index(t) for t in present])
    norms = weighting.weights[index] * raw
    ratios = torch.tensor([float(losses[t].detach()) / initial[t] for t in present])
    target = norms.mean().detach() * (ratios / ratios.mean()) ** alpha
    balance = (norms - target).abs().sum()
    weighting.weights.grad = torch.autograd.grad(balance, weighting.weights)[0]
    return float(balance.detach())


@torch.inference_mode()
def mt_predictions(model, sample, batch_size=128):
    model.eval()
    t = sample["tensors"]
    parts = [
        model(t["x"][i : i + batch_size], t["mask"][i : i + batch_size])
        for i in range(0, sample["count"], batch_size)
    ]
    return tuple(torch.cat([p[j] for p in parts]) for j in range(6))


def binary_metrics(y, p):
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    positives, n = int(y.sum()), len(y)
    out = {"n": n, "positives": positives, "base_rate": positives / n if n else None}
    out["brier"] = float(np.mean((p - y) ** 2)) if n else None
    if not positives or positives == n:
        return {**out, "roc_auc": None, "average_precision": None}
    from scipy.stats import rankdata

    ranks = rankdata(p)
    auc = (ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * (n - positives))
    order = np.argsort(-p, kind="stable")
    hits = np.cumsum(y[order])
    precision_at_hit = hits[y[order] == 1] / (np.flatnonzero(y[order] == 1) + 1)
    return {**out, "roc_auc": float(auc), "average_precision": float(precision_at_hit.mean())}


def agreement(pred, truth):
    pred, truth = np.asarray(pred, dtype=float), np.asarray(truth, dtype=float)
    out = {"n": len(pred), "mae": float(np.mean(np.abs(pred - truth))) if len(pred) else None}
    if len(pred) >= 3 and np.std(pred) > 0 and np.std(truth) > 0:
        from scipy.stats import rankdata

        out["pearson_r"] = float(np.corrcoef(pred, truth)[0, 1])
        out["spearman_rho"] = float(np.corrcoef(rankdata(pred), rankdata(truth))[0, 1])
    else:
        out["pearson_r"] = out["spearman_rho"] = None
    return out


def _distribution(values):
    x = np.asarray(values, dtype=float)
    if not len(x):
        return {"n": 0, "mean": None, "median": None, "p90": None}
    return {
        "n": len(x),
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "p90": float(np.percentile(x, 90)),
    }


def tti_strata(config):
    horizon = config.base.k * config.base.dt_step
    edges = sorted({0.0, horizon / 2, horizon, config.h_max_s})
    return list(zip(edges, edges[1:], strict=False))


def task_metrics(config, scaling, outputs, sample):
    """Frame-level metrics per head on labelled rows only (Task 11.4). SYNTHETIC unless stated."""
    values = decode_heads(config, scaling, outputs, sample["anchor"])
    t, m, heads = sample["tensors"], sample["mt"], set(config.heads)
    participants = np.array([meta["participant"] for meta in sample["meta"]])
    impact = m["impact_mask"].numpy()
    report = {}
    if "trajectory" in heads:
        report["trajectory"] = diagnostics(outputs[0], sample)
    if "strike" in heads:
        rows = t["aux_mask"].numpy()
        report["strike"] = binary_metrics(t["aux"].numpy()[rows], values["strike_prob"][rows])
    truth_tti = m["tti"].numpy().astype(float)
    if "tti" in heads:
        error = values["tti_s"] - truth_tti
        report["tti"] = {
            "n": int(impact.sum()),
            "mae_s": float(np.abs(error[impact]).mean()) if impact.any() else None,
            "bias_s": float(error[impact].mean()) if impact.any() else None,
            "strata": [
                {
                    "true_tti_s": [lo, hi],
                    "n": int(rows.sum()),
                    "mae_s": float(np.abs(error[rows]).mean()) if rows.any() else None,
                    "bias_s": float(error[rows].mean()) if rows.any() else None,
                }
                for lo, hi in tti_strata(config)
                for rows in [impact & (truth_tti > lo) & (truth_tti <= hi + 1e-9)]
            ],
            "by_participant": {
                p: float(np.abs(error[impact & (participants == p)]).mean())
                for p in sorted(set(participants[impact]))
            },
        }
    if "zone" in heads:
        truth, pred = m["zone"].numpy()[impact], values["zone_index"][impact]
        pairs, counts = np.unique(np.c_[truth, pred], axis=0, return_counts=True)
        report["zone"] = {
            "n": int(impact.sum()),
            "accuracy": float(np.mean(truth == pred)) if impact.any() else None,
            "confusion": [
                {"actual": config.zone_ids[a], "predicted": config.zone_ids[b], "n": n}
                for (a, b), n in zip(pairs.tolist(), counts.tolist(), strict=True)
            ],
        }
    if "position" in heads:
        truth = m["position"].numpy() + sample["anchor"]
        report["position"] = _distribution(np.linalg.norm(values["impact_pos"] - truth, axis=1)[impact])
    if "intensity" in heads:
        report["intensity"] = agreement(values["intensity"][impact], m["intensity"].numpy()[impact])
    return report


def validation_head_loss(outputs, sample, config, loss, training, scaling):
    everything = torch.arange(sample["count"])
    losses = task_losses(outputs, sample, everything, config, loss, training, scaling, None)
    return float(sum(float(v) for k, v in losses.items() if k != "trajectory"))


def train_mt_fold(fold_dir, output, config, training, loss, *, provenance, aux_horizon_s=None):
    if training.lambda_aux:
        raise ValueError("multi-task training uses the strike head; the Phase 10 lambda_aux must be 0")
    if loss.weighting == "trajectory_dominant" and not config.has_trajectory:
        raise ValueError("trajectory-dominant weighting needs the trajectory head")
    train, val, stats = load_mt_fold(fold_dir, config, aux_horizon_s=aux_horizon_s)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    seed_everything(training.seed, training.threads)
    model = build_mt_model(config)
    weighting = TaskWeighting(
        config.heads, loss.weighting, lambdas=dict(loss.lambdas), dominant_lambda=loss.dominant_lambda
    )
    scaling = target_scaling(train)
    parameters = list(model.parameters())
    if weighting.log_vars is not None:
        parameters.append(weighting.log_vars)
    optimizer = torch.optim.Adam(parameters, lr=training.learning_rate)
    balancer = (
        torch.optim.Adam([weighting.weights], lr=loss.gradnorm_lr) if weighting.weights is not None else None
    )
    step_weights = torch.ones(config.base.k)
    if training.step_weighting == "near":
        step_weights = torch.arange(config.base.k, 0, -1, dtype=torch.float32)
    elif training.step_weighting == "far":
        step_weights = torch.arange(1, config.base.k + 1, dtype=torch.float32)
    best, best_epoch, state, best_weights, history, conflicts, initial = math.inf, -1, None, None, [], [], {}
    t, step = train["tensors"], 0
    shared = encoder_parameters(model)
    for epoch in range(training.epochs):
        model.train()
        indices = epoch_indices(train, seed=training.seed + epoch, positive_ratio=training.positive_ratio)
        totals, counts, batches = {}, {}, 0
        for start in range(0, len(indices), training.batch_size):
            ix = indices[start : start + training.batch_size]
            optimizer.zero_grad(set_to_none=True)
            outputs = model(t["x"][ix], t["mask"][ix])
            losses = task_losses(outputs, train, ix, config, loss, training, scaling, step_weights)
            if not losses:  # only possible without the trajectory head: no label in this batch
                continue
            total = weighting(losses)
            if not torch.isfinite(total):
                raise ValueError("nonfinite loss")
            if loss.conflict_every and step % loss.conflict_every == 0 and "trajectory" in losses:
                conflicts.append(_conflicts(losses, shared, weighting, epoch=epoch, step=step))
            if balancer is not None:
                balancer.zero_grad(set_to_none=True)
                _gradnorm_step(model, losses, weighting, initial, loss.gradnorm_alpha)
            total.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), training.grad_clip, error_if_nonfinite=True)
            optimizer.step()
            if balancer is not None and weighting.weights.grad is not None:
                balancer.step()
                weighting.renormalise()
            for task, value in losses.items():
                totals[task] = totals.get(task, 0.0) + float(value.detach())
                counts[task] = counts.get(task, 0) + 1
            batches, step = batches + 1, step + 1
        outputs = mt_predictions(model, val)
        metrics = task_metrics(config, scaling, outputs, val)
        if config.has_trajectory:
            score = metrics["trajectory"]["participant_macro_ade"]
        else:
            score = validation_head_loss(outputs, val, config, loss, training, scaling)
        if score is None or not math.isfinite(score):
            raise ValueError("no finite validation criterion")
        history.append(
            {
                "epoch": epoch,
                "train_loss": {k: totals[k] / counts[k] for k in totals},
                "labelled_batches": counts,
                "batches": batches,
                "task_weights": weighting.current(),
                "validation_score": score,
                "validation": metrics,
                "sampled_windows": len(indices),
            }
        )
        if score < best:
            best, best_epoch = score, epoch
            state, best_weights = copy.deepcopy(model.state_dict()), weighting.current()
        text = json.dumps(history, indent=2, allow_nan=False)
        (output / "training.json").write_text(text, encoding="utf-8")
        if epoch - best_epoch >= training.patience:
            break
    model.load_state_dict(state)
    model.eval()
    torch.save(model.state_dict(), output / "checkpoint.pt")
    if conflicts:
        (output / "conflicts.json").write_text(json.dumps(conflicts, indent=2), encoding="utf-8")
    base = config.base
    manifest = {
        **provenance,
        "family": base.family,
        "config": base.to_dict(),
        "base_config_hash": base.config_hash,
        "mt_config": config.to_dict(),
        "config_hash": config.config_hash,
        "heads": list(config.heads),
        "live_eligible": config.live_eligible,
        "training": asdict(training),
        "loss_config": loss.to_dict(),
        "seed": training.seed,
        "N": base.n,
        "K": base.k,
        "dt_step": base.dt_step,
        "F": base.features,
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
        "task_counts": {"train": train["mt_counts"], "val": val["mt_counts"]},
        "target_scaling": scaling,
        "selection_criterion": "participant_macro_ADE (Phase 10 criterion)"
        if config.has_trajectory
        else "unweighted validation head loss (no-trajectory diagnostic only)",
        "best_epoch": best_epoch,
        "best_validation_score": best,
        "best_task_weights": best_weights,
        "conflict_samples": len(conflicts),
        "checkpoint_hash": sha(output / "checkpoint.pt"),
        "target_grid": "linear interpolation on contiguous observed causal targets; no extrapolation",
        "normalization": "already applied by Phase 08; verified fold provenance; no second normalization",
        "aux_horizon_s": aux_horizon_s,
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "parameter_bytes": sum(p.numel() * p.element_size() for p in model.parameters()),
    }
    manifest["model_id"] = (
        f"mt-{base.family}-fold{stats['fold']}-seed{training.seed}-{manifest['checkpoint_hash'][7:19]}"
    )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    return model, manifest, val
