"""Participant-disjoint fold training for the flattened-window baseline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np


def load_samples(path: str | Path) -> dict:
    with np.load(path, allow_pickle=False) as d:
        sample = {k: d[k].copy() for k in d.files}
    sample["aux_decoded"] = [json.loads(str(v)) for v in sample["aux"]]
    sample["meta_decoded"] = [json.loads(str(v)) for v in sample["meta"]]
    return sample


def flat_features(sample: dict) -> np.ndarray:
    x, m = sample["X"], sample["M"]
    if x.ndim != 3 or x.shape != m.shape:
        raise ValueError("X/M must be equal [samples, history, features] tensors")
    return np.concatenate((x.reshape(len(x), -1), m.reshape(len(m), -1).astype(float)), axis=1)


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _fit(x, y, *, objective, seed, n_estimators, num_leaves, learning_rate, weight=None, num_class=None):
    params = dict(
        objective=objective,
        verbosity=-1,
        num_threads=1,
        seed=seed,
        deterministic=True,
        force_row_wise=True,
        num_leaves=num_leaves,
        learning_rate=learning_rate,
        max_bin=63,
    )
    if num_class is not None:
        params["num_class"] = num_class
    data = lgb.Dataset(x, label=y, weight=weight, free_raw_data=False)
    return lgb.train(params, data, num_boost_round=n_estimators)


def _predict_binary(booster, x):
    return np.asarray(booster.predict(x, num_threads=1), dtype=float)


def train_fold(
    fold_dir: str | Path, output: str | Path, *, seed: int = 9, search: tuple[dict, ...] | None = None
) -> dict:
    """Train only on fold train, select binary hyperparameters on val, never inspect test."""
    fold_dir, output = Path(fold_dir), Path(output)
    train, val = (load_samples(fold_dir / f"samples.{part}.npz") for part in ("train", "val"))
    if str(train["feature_schema_hash"]) != str(val["feature_schema_hash"]):
        raise ValueError("feature schema mismatch")
    train_ids = {m["participant"] for m in train["meta_decoded"]}
    val_ids = {m["participant"] for m in val["meta_decoded"]}
    if not train_ids or not val_ids or train_ids & val_ids:
        raise ValueError("train/validation participants must be nonempty and disjoint")
    kinds = {m["source_kind"] for d in (train, val) for m in d["meta_decoded"]}
    if len(kinds) != 1:
        raise ValueError("mixed evidence kinds")
    stats_path, report_path = fold_dir / "norm_stats.json", fold_dir / "report.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        set(stats["train_participants"]) != train_ids
        or stats["feature_schema_hash"] != str(train["feature_schema_hash"])
        or stats["source_kind"] != next(iter(kinds))
        or report["fold"] != stats["fold"]
        or set(report["parts"]["train"]["participants"]) != train_ids
        or set(report["parts"]["val"]["participants"]) != val_ids
    ):
        raise ValueError("fold normalization/report provenance mismatch")
    if any(m["fold"] != stats["fold"] for d in (train, val) for m in d["meta_decoded"]):
        raise ValueError("sample fold mismatch")
    if next(iter(kinds)) == "PARTICIPANT" and not stats["dataset_version"].startswith("ds-v1."):
        raise ValueError("participant model requires participant dataset provenance")
    x, xv = flat_features(train), flat_features(val)
    y = np.asarray([int(a["strike_within_H"]) for a in train["aux_decoded"]])
    yv = np.asarray([int(a["strike_within_H"]) for a in val["aux_decoded"]])
    mask = np.asarray([bool(a["strike_mask"]) for a in train["aux_decoded"]])
    maskv = np.asarray([bool(a["strike_mask"]) for a in val["aux_decoded"]])
    if len(np.unique(y[mask])) < 2 or not maskv.any():
        raise ValueError("training needs both strike classes and validation needs unmasked labels")
    search = search or (
        {"n_estimators": 40, "num_leaves": 7, "learning_rate": 0.05},
        {"n_estimators": 80, "num_leaves": 15, "learning_rate": 0.05},
        {"n_estimators": 80, "num_leaves": 7, "learning_rate": 0.1},
    )
    trials = []
    best = None
    for params in search:
        balance = np.bincount(y[mask], minlength=2)
        weights = np.asarray([len(y[mask]) / (2 * balance[class_id]) for class_id in y[mask]])
        model = _fit(x[mask], y[mask], objective="binary", seed=seed, weight=weights, **params)
        p = np.clip(_predict_binary(model, xv[maskv]), 1e-9, 1 - 1e-9)
        loss = float(-np.mean(yv[maskv] * np.log(p) + (1 - yv[maskv]) * np.log(1 - p)))
        trials.append({"params": params, "val_logloss": loss})
        if best is None or loss < best[0]:
            best = (loss, params, model)
    assert best is not None
    params = best[1]
    models = {"strike": best[2]}
    positives = np.asarray([bool(a["tti_mask"]) and bool(a["strike_within_H"]) for a in train["aux_decoded"]])
    if positives.sum() >= 2:
        models["tti"] = _fit(
            x[positives],
            np.asarray([a["tti"] for a in train["aux_decoded"]])[positives],
            objective="regression",
            seed=seed,
            **params,
        )
        zones = [a["zone_id"] for a in train["aux_decoded"] if a["tti_mask"] and a["strike_within_H"]]
        zone_ids = sorted(set(zones))
        if len(zone_ids) > 1 and min(zones.count(z) for z in zone_ids) >= 2:
            zi = np.asarray([zone_ids.index(z) for z in zones])
            objective = "binary" if len(zone_ids) == 2 else "multiclass"
            zone_params = {**params}
            models["zone"] = _fit(
                x[positives],
                zi,
                objective=objective,
                seed=seed,
                num_class=len(zone_ids) if len(zone_ids) > 2 else None,
                **zone_params,
            )
    else:
        zone_ids = []
    k = int(train["T"].shape[1])
    steps = sorted(set((max(0, k // 2 - 1), k - 1)))
    for step in steps:
        valid = train["T_mask"][:, step].astype(bool)
        if valid.sum() < 2:
            continue
        for axis in range(2):
            models[f"displacement_{step}_{axis}"] = _fit(
                x[valid],
                train["T"][valid, step, axis],
                objective="regression",
                seed=seed,
                **params,
            )
    if output.exists() and any(output.iterdir()):
        raise ValueError("model output directory is nonempty; use a new run path")
    output.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, model in models.items():
        path = output / f"{name}.txt"
        model.save_model(str(path))
        hashes[name] = _sha(path)
    manifest = {
        "version": "p09-gbdt-v1",
        "evidence_kind": next(iter(kinds)),
        "fold": fold_dir.name,
        "seed": seed,
        "threads": 1,
        "train_participants": sorted(train_ids),
        "val_participants": sorted(val_ids),
        "feature_schema_hash": str(train["feature_schema_hash"]),
        "dataset_version": stats["dataset_version"],
        "dataset_hash": stats["dataset_hash"],
        "split_hash": stats["split_hash"],
        "norm_stats_hash": _sha(stats_path),
        "feature_report_hash": _sha(report_path),
        "feature_shape": list(train["X"].shape[1:]),
        "trajectory_steps": k,
        "dt_step_s": float(np.median(train["target_offsets_s"][:, 0])),
        "displacement_steps": steps,
        "zone_ids": zone_ids,
        "search": trials,
        "selected": params,
        "input_hashes": {part: _sha(fold_dir / f"samples.{part}.npz") for part in ("train", "val")},
        "model_hashes": hashes,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    return manifest
