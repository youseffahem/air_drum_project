"""EXPLORATORY (not pre-declared): a post-hoc per-step Gaussian variance head on frozen reference models.

The declared E4(a) variant (`e4-gauss`) fits log sigma by Gaussian NLL through the shared encoder,
starting from sigma ~ 1 at the development learning rate; on the SYNTHETIC fixture its mean
trajectory degraded, which confounds any effect of the crossing-probability gate. This diagnostic
isolates the gate: each reference model (encoder and mean head) is frozen, bit for bit, and only a
linear log-sigma head on the detached encoder state is fitted by Gaussian NLL of the training fold's
residuals (bias initialised at the log RMS residual per step and axis, weights zero, Adam 1e-2,
20 epochs, checkpoint by validation NLL). The candidate trajectory is therefore the reference's;
only the relabelled crossing probability differs.

Labelled EXPLORATORY: designed after the declared E4(a) result was seen, it never enters the
go/no-go table and may only inform the participant-stage pre-registration (an E4(a') declaration).
"""

import argparse
import copy
import json
import math
from pathlib import Path

import numpy as np
import torch
from _p10 import hardware, provenance, source_hashes, write_json
from _p11 import fold_stats
from _p11_fixture import kinematic_fixture
from _p12 import (
    DEV,
    NOT_CODEX,
    calibration_for_trained,
    dev_pick,
    evaluate_sessions,
    load_run_rows,
    predeclaration_record,
)
from _runlog import RunLog

from spacedrums.config import load_config
from spacedrums.models.temporal.data import load_fold, sha
from spacedrums.models.temporal.export import export_model, load_model
from spacedrums.models.temporal.ext import ExtensionConfig, build_extension_model, load_extension_model
from spacedrums.models.temporal.ext.adapter import ExtensionAnticipator
from spacedrums.models.temporal.ext.long_horizon import select_grid
from spacedrums.models.temporal.ext.train import validation_report
from spacedrums.models.temporal.ext.uncertainty import LOG_SIGMA_MAX, LOG_SIGMA_MIN, gaussian_nll
from spacedrums.models.temporal.train import predictions, seed_everything

ROOT = Path(__file__).resolve().parents[1]
VARIANT = "x-e4-posthoc"
FIT = {
    "optimizer": "Adam",
    "learning_rate": 0.01,
    "epochs": 20,
    "batch_size": 64,
    "selection": "validation NLL",
}


@torch.inference_mode()
def encoder_state(model, x, mask):
    """The hidden state the reference head reads (GRU last state, or TCN last position)."""
    x, mask = x[:, -model.n :], mask[:, -model.n :]
    if hasattr(model, "gru"):
        state = x.new_zeros((model.layers, x.shape[0], model.hidden))
        for i in range(x.shape[1]):
            state = model.step(x[:, i], mask[:, i], state)
        return state[-1]
    return model.encode(x, mask)[:, :, -1]


def fit_sigma(reference, train, val, k, seed):
    seed_everything(seed, 1)
    t, v = train["tensors"], val["tensors"]
    # Inference-mode outputs are cloned into ordinary tensors: the frozen state feeds a trained head.
    h_train = encoder_state(reference, t["x"], t["mask"]).clone()
    h_val = encoder_state(reference, v["x"], v["mask"]).clone()
    mean_train, mean_val = predictions(reference, train)[0].clone(), predictions(reference, val)[0].clone()
    residual = torch.where(
        t["target_mask"][..., None], t["target"] - mean_train, torch.zeros_like(mean_train)
    )
    counts = t["target_mask"].sum(0).clamp_min(1)[:, None]
    rms = (residual.square().sum(0) / counts).sqrt().clamp_min(1e-4)
    head = torch.nn.Linear(h_train.shape[1], 2 * k)
    with torch.no_grad():
        head.weight.zero_()
        head.bias.copy_(rms.log().reshape(-1).clamp(LOG_SIGMA_MIN, LOG_SIGMA_MAX))
    optimizer = torch.optim.Adam(head.parameters(), lr=FIT["learning_rate"])
    rng = np.random.default_rng(seed)

    def nll(h, mean, sample):
        log_sigma = head(h).clamp(LOG_SIGMA_MIN, LOG_SIGMA_MAX)
        return gaussian_nll(mean, log_sigma, sample["target"], sample["target_mask"])

    best, state, history = math.inf, None, []
    for epoch in range(FIT["epochs"]):
        order = rng.permutation(len(h_train))
        for start in range(0, len(order), FIT["batch_size"]):
            ix = order[start : start + FIT["batch_size"]]
            optimizer.zero_grad(set_to_none=True)
            loss = nll(
                h_train[ix], mean_train[ix], {"target": t["target"][ix], "target_mask": t["target_mask"][ix]}
            )
            loss.backward()
            optimizer.step()
        with torch.no_grad():
            score = float(nll(h_val, mean_val, v))
        history.append({"epoch": epoch, "validation_nll": score})
        if score < best:
            best, state = score, copy.deepcopy(head.state_dict())
    head.load_state_dict(state)
    return head, {
        "initial_log_rms": rms.log().reshape(-1).tolist(),
        "history": history,
        "best_validation_nll": best,
    }


def package(row, output, reference, reference_manifest, head, fit, context, train, val):
    base = reference_manifest["config"]
    config = ExtensionConfig(
        base["family"],
        base["features"],
        n=base["n"],
        k=base["k"],
        dt_step=base["dt_step"],
        hidden=base["hidden"],
        layers=base["layers"],
        dropout=base["dropout"],
        kernel=base["kernel"],
        dilations=tuple(base["dilations"]),
        uncertainty="gaussian",
    )
    model = build_extension_model(config).eval()
    missing = model.load_state_dict(reference.state_dict(), strict=False)
    if (
        set(missing.missing_keys) != {"head.log_sigma.weight", "head.log_sigma.bias"}
        or missing.unexpected_keys
    ):
        raise ValueError(f"unexpected reference/extension key mismatch: {missing}")
    model.head.log_sigma.load_state_dict(head.state_dict())
    for sample in (train, val):  # the candidate trajectory is exactly the reference's
        torch.testing.assert_close(
            predictions(model, sample)[0], predictions(reference, sample)[0], atol=0, rtol=0
        )
    output.mkdir(parents=True)
    torch.save(model.state_dict(), output / "checkpoint.pt")
    manifest = {
        **context,
        "variant": VARIANT,
        "exploratory": True,
        "note": "EXPLORATORY post-hoc variance head on a frozen reference model; not pre-declared",
        "reference_model_dir": row["model_dir"],
        "reference_checkpoint_hash": reference_manifest["checkpoint_hash"],
        "fit": {**FIT, **{k: v for k, v in fit.items() if k != "history"}},
        "extensions": list(config.extensions),
        "family": config.family,
        "ext_config": config.to_dict(),
        "config_hash": config.config_hash,
        "seed": reference_manifest["seed"],
        "N": config.n,
        "K": config.k,
        "dt_step": config.dt_step,
        "offsets_s": list(config.offsets_s),
        "F": config.features,
        "uncertainty_kind": "sigma_xy",
        **{
            key: reference_manifest[key]
            for key in (
                "feature_schema_id",
                "feature_schema_hash",
                "norm_stats_id",
                "fold",
                "dataset_version",
                "dataset_hash",
                "split_hash",
                "source_kind",
                "train_participants",
                "val_participants",
                "train_samples_hash",
                "val_samples_hash",
            )
        },
        "checkpoint_hash": sha(output / "checkpoint.pt"),
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "parameter_bytes": sum(p.numel() * p.element_size() for p in model.parameters()),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    write_json(output / "fit.json", fit)
    parity = export_model(model, output, val)
    exported, manifest = load_extension_model(output)
    report = validation_report(config, exported, val)
    write_json(output / "validation.json", report)
    return exported, manifest, config, report, parity


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reference-run", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=ROOT / "experiments/phase-12")
    args = ap.parse_args()
    _, rows = load_run_rows(args.reference_run, extension="ref")
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    with RunLog(
        phase="12",
        task="12.6",
        slug="exploratory-e4-posthoc",
        config=cfg,
        experiments_dir=args.output,
        description="EXPLORATORY post-hoc Gaussian variance head on frozen references (not pre-declared)",
    ) as run:
        torch.set_num_threads(1)
        context = {**provenance(), "hardware": hardware(), **NOT_CODEX}
        write_json(run.dir / "execution.json", context)
        write_json(run.dir / "source-hashes.json", source_hashes())
        dataset, cv, sessions = kinematic_fixture(cfg, identities=DEV["identities"], seconds=DEV["seconds"])
        dataset = {**dataset, "split_hash": cv["split_hash"]}
        write_json(
            run.dir / "plan.json",
            {
                "extension": "exploratory-e4",
                "label": "EXPLORATORY (not pre-declared; never in the go/no-go table)",
                "reference_run": str(args.reference_run),
                "fit": FIT,
                "cells": [
                    {"variant": VARIANT, "family": r["family"], "fold_dir": r["fold_dir"]} for r in rows
                ],
                "test_access": False,
                "predeclaration": predeclaration_record(),
            },
        )
        results, curves = [], []
        for index, row in enumerate(rows):
            reference, reference_manifest = load_model(row["model_dir"], exported=False)
            base = ExtensionConfig.from_reference(reference_manifest["config"])
            train, val, _ = load_fold(row["fold_dir"], base.data_view)
            train, val = select_grid(train, base), select_grid(val, base)
            head, fit = fit_sigma(reference, train, val, base.k, reference_manifest["seed"])
            output = run.dir / "models" / f"cell-{index:03d}"
            model, manifest, config, report, _ = package(
                row, output, reference, reference_manifest, head, fit, context, train, val
            )
            fold = next(f for f in cv["folds"] if f["fold"] == manifest["fold"])
            stats = fold_stats(row, fold, dataset, sessions)

            def factory(model=model, manifest=manifest):
                return ExtensionAnticipator(model, manifest, variant=VARIANT)

            points = evaluate_sessions(
                factory,
                manifest,
                fold,
                sessions,
                stats,
                cfg,
                output,
                probabilistic=True,
                family=manifest["family"],
            )
            results.append(
                {
                    "variant": VARIANT,
                    "exploratory": True,
                    "model_dir": str(output),
                    "fold_dir": row["fold_dir"],
                    "fold": manifest["fold"],
                    "seed": manifest["seed"],
                    "family": manifest["family"],
                    "source_kind": manifest["source_kind"],
                    "validation": {"trajectory": report},
                    "harness": dev_pick(points),
                    "harness_gate_off": dev_pick([p for p in points if p["settings"]["p_commit"] == 0.0]),
                    "calibration": calibration_for_trained("e4-gauss", config, model, val, cfg),
                    "best_validation_nll": fit["best_validation_nll"],
                    "parameter_count": manifest["parameter_count"],
                }
            )
            curves += [{**p, "variant": VARIANT} for p in points]
            h = results[-1]["harness"]
            cell = f"{manifest['family']} fold={manifest['fold']} seed={manifest['seed']}"
            print(
                f"[{index + 1}/{len(rows)}] {cell} lead={h['median_lead_s']} feasible={h['feasible']}",
                flush=True,
            )
        write_json(run.dir / "results.json", results)
        write_json(run.dir / "curves.json", curves)
        for path in sorted(run.dir.rglob("*")):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            {"models": len(results), "exploratory": True},
            notes="EXPLORATORY; SYNTHETIC fixture; not pre-declared, never a go/no-go input.",
        )
        print(run.dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
