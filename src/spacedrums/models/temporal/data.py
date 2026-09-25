"""Read already-normalized Phase 08 folds; never refit or normalize them twice."""

import hashlib
import json
from pathlib import Path

import numpy as np
import torch


def sha(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixed_grid(target, offsets, mask, k, dt_step):
    """Interpolate contiguous valid targets from the known zero-displacement anchor.

    No extrapolation and no interpolation across a missing target/reset/segment gap.
    This is target-only processing; the input tensor is never touched.
    """
    if target.shape[:2] != offsets.shape or mask.shape != offsets.shape or target.shape[-1] != 2:
        raise ValueError("target offset/mask alignment mismatch")
    grid = np.arange(1, k + 1) * dt_step
    result, valid = np.zeros((len(target), k, 2), np.float32), np.zeros((len(target), k), bool)
    for i in range(len(target)):
        count = next((j for j, good in enumerate(mask[i]) if not good), len(mask[i]))
        if not count:
            continue
        times = np.r_[0.0, offsets[i, :count]]
        values = np.vstack((np.zeros(2), target[i, :count]))
        if not np.isfinite(times).all() or not np.isfinite(values).all() or (np.diff(times) <= 0).any():
            raise ValueError("valid targets require finite increasing offsets")
        ok = grid <= times[-1] + 1e-9
        valid[i] = ok
        for axis in range(2):
            result[i, ok, axis] = np.interp(grid[ok], times, values[:, axis])
    return result, valid


def read_samples(path, config, *, aux_horizon_s=None):
    with np.load(path, allow_pickle=False) as archive:
        d = {key: archive[key].copy() for key in archive.files}
    meta, aux = ([json.loads(str(v)) for v in d[key]] for key in ("meta", "aux"))
    x, mask = d["X"], d["M"]
    if x.ndim != 3 or x.shape != mask.shape or x.shape[1:] != (config.n, config.features):
        raise ValueError("exported N/F must exactly match configuration; rebuild Phase 08 windows")
    if len(meta) != len(x) or len(aux) != len(x) or not len(x) or not d["anticipation_eligible"].all():
        raise ValueError("empty, misaligned or safety-only training samples")
    if not np.isfinite(x[mask]).all():
        raise ValueError("unmasked nonfinite inputs")
    if config.auxiliary and (aux_horizon_s is None or abs(aux_horizon_s - config.k * config.dt_step) > 1e-9):
        raise ValueError("auxiliary supervision requires matching exported H; regenerate windows")
    target, target_mask = fixed_grid(d["T"], d["target_offsets_s"], d["T_mask"], config.k, config.dt_step)
    if not target_mask.any():
        raise ValueError("no valid fixed-grid targets")
    # Current tip = absolute minus displacement at the first observed target (eligible => one exists).
    first = d["T_mask"].argmax(axis=1)
    rows = np.arange(len(x))
    anchor = d["T_absolute"][rows, first] - d["T"][rows, first]
    tensors = {
        "x": torch.tensor(np.where(mask, x, 0), dtype=torch.float32),
        "mask": torch.tensor(mask, dtype=torch.bool),
        "target": torch.tensor(target),
        "target_mask": torch.tensor(target_mask),
        "aux": torch.tensor([a["strike_within_H"] for a in aux], dtype=torch.float32),
        "aux_mask": torch.tensor([a["strike_mask"] for a in aux], dtype=torch.bool),
    }
    return {
        "tensors": tensors,
        "meta": meta,
        "aux_records": aux,
        "anchor": anchor,
        "schema_hash": str(d["feature_schema_hash"]),
        "hash": sha(path),
        "count": len(x),
        "positives": int(tensors["aux"][tensors["aux_mask"]].sum()),
    }


def load_fold(path, config, *, aux_horizon_s=None):
    path = Path(path)
    # Explicit allowlist: held-out test samples are never opened by training.
    train, val = (
        read_samples(path / f"samples.{p}.npz", config, aux_horizon_s=aux_horizon_s) for p in ("train", "val")
    )
    stats = json.loads((path / "norm_stats.json").read_text(encoding="utf-8"))
    report = json.loads((path / "report.json").read_text(encoding="utf-8"))
    ids = [{m["participant"] for m in d["meta"]} for d in (train, val)]
    test_ids = set(report["parts"].get("test", {}).get("participants", []))
    if not all(ids) or ids[0] & ids[1] or (ids[0] | ids[1]) & test_ids:
        raise ValueError("participant fold leakage")
    kinds = {m["source_kind"] for d in (train, val) for m in d["meta"]}
    if kinds != {stats["source_kind"]} or train["schema_hash"] != val["schema_hash"]:
        raise ValueError("mixed evidence kind/schema")
    if stats["feature_schema_hash"] != train["schema_hash"] or stats["feature_schema_id"] != "fs-v1":
        raise ValueError("normalization schema mismatch")
    if (
        set(stats["train_participants"]) != ids[0]
        or report["fold"] != stats["fold"]
        or any(m["fold"] != stats["fold"] for d in (train, val) for m in d["meta"])
    ):
        raise ValueError("fold normalization provenance mismatch")
    for part, actual in zip(("train", "val"), ids, strict=True):
        if set(report["parts"][part]["participants"]) != actual:
            raise ValueError("report participant mismatch")
    if set(stats["train_sessions"]) != {m["session_id"] for m in train["meta"]}:
        raise ValueError("normalization training session mismatch")
    if len(stats["center"]) != config.features or len(stats["scale"]) != config.features:
        raise ValueError("normalization dimension mismatch")
    if (
        not np.isfinite(stats["center"]).all()
        or not np.isfinite(stats["scale"]).all()
        or min(stats["scale"]) <= 0
    ):
        raise ValueError("invalid normalization values")
    if stats["source_kind"] == "PARTICIPANT" and stats["dataset_version"] != "ds-v1.0":
        raise ValueError("Phase 10 requires ds-v1.0")
    if stats["source_kind"] != "PARTICIPANT" and not stats["dataset_version"].startswith("ds-v0.0-selftest"):
        raise ValueError("nonparticipant data requires selftest version")
    return train, val, stats


def epoch_indices(sample, *, seed, positive_ratio=None):
    rng = np.random.default_rng(seed)
    if positive_ratio is None:
        return rng.permutation(sample["count"])
    if not 0 < positive_ratio < 1:
        raise ValueError("positive sampling ratio must be in (0,1)")
    t = sample["tensors"]
    positive = (t["aux"] == 1) & t["aux_mask"]
    negative = (t["aux"] == 0) & t["aux_mask"]
    if not positive.any() or not negative.any():
        raise ValueError("oversampling needs both supervised classes")
    # Retain all samples once, then add positives/negatives to approach requested ratio.
    indices = list(rng.permutation(sample["count"]))
    p, n = int(positive.sum()), int(negative.sum())
    if p / (p + n) < positive_ratio:
        indices.extend(
            rng.choice(np.flatnonzero(positive), int(np.ceil(n * positive_ratio / (1 - positive_ratio) - p)))
        )
    else:
        indices.extend(
            rng.choice(np.flatnonzero(negative), int(np.ceil(p * (1 - positive_ratio) / positive_ratio - n)))
        )
    return rng.permutation(indices)
