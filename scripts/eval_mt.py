"""Per-task evaluation of Phase 11 models (Task 11.4) and exported-model reproduction.

--run: every selected grid cell is judged head by head against geometry on its OWN predicted
trajectory and against Baseline B (rule extrapolation -> same geometry), on validation
participants only. --model-dir/--samples/--expected: subprocess reproduction of validation.json.
--partition test is refused before any file is opened (Task 11.9 prerequisites PENDING).
"""

import argparse
import json
from pathlib import Path

import numpy as np
from _p10 import hardware, provenance, source_hashes, write_json
from _p11 import (
    assert_close_nested,
    baseline_b_frames,
    frame_geometry,
    load_grid_run,
    per_task_comparison,
)
from _runlog import RunLog

from spacedrums.config import load_config
from spacedrums.geometry import ZoneRegistry
from spacedrums.models.temporal.config import MultiTaskConfig
from spacedrums.models.temporal.data import sha
from spacedrums.models.temporal.export import load_mt_model
from spacedrums.models.temporal.mt_train import load_mt_fold, mt_predictions, task_metrics

COMPARED = (
    ("tti", "head_all_rows", "mae_s"),
    ("tti", "head_on_geometry_rows", "mae_s"),
    ("tti", "geometry", "mae_s"),
    ("tti", "baseline_b", "mae_s"),
    ("zone", "head_all_rows", "accuracy"),
    ("zone", "head_on_geometry_rows", "accuracy"),
    ("zone", "geometry", "accuracy"),
    ("zone", "baseline_b", "accuracy"),
    ("position", "head_all_rows", "median"),
    ("position", "head_on_geometry_rows", "median"),
    ("position", "geometry", "median"),
    ("position", "baseline_b", "median"),
    ("intensity", "head_all_rows", "mae"),
    ("intensity", "head_on_geometry_rows", "mae"),
    ("intensity", "geometry_inward", "mae"),
    ("intensity", "baseline_b_inward", "mae"),
    ("intensity", "head_all_rows", "pearson_r"),
    ("intensity", "geometry_inward", "pearson_r"),
    ("intensity", "baseline_b_inward", "pearson_r"),
)


def reproduce(args, ap):
    model, manifest = load_mt_model(args.model_dir)
    if sha(args.samples) != manifest["val_samples_hash"]:
        ap.error("only this model's hashed validation samples are authorized")
    config = MultiTaskConfig.from_dict(manifest["mt_config"])
    _, val, _ = load_mt_fold(args.samples.parent, config, aux_horizon_s=manifest["aux_horizon_s"])
    if val["hash"] != manifest["val_samples_hash"]:
        ap.error("fold directory does not hold the model's validation archive")
    metrics = task_metrics(config, manifest["target_scaling"], mt_predictions(model, val), val)
    if args.expected:
        assert_close_nested(metrics, json.loads(args.expected.read_text(encoding="utf-8")))
    write_json(
        args.output,
        {
            "metrics": metrics,
            "export_hash": manifest["export_hash"],
            "reproduced": bool(args.expected),
            "atol": 1e-6,
            "rtol": 1e-5,
            "validated": False,
            "scope": "same environment subprocess",
        },
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--partition", choices=("val", "test"), default="val")
    ap.add_argument("--run", type=Path, help="completed Phase 11 grid run")
    ap.add_argument("--variants", nargs="+", default=["all"])
    ap.add_argument("--synthetic-fixture", action="store_true")
    ap.add_argument("--model-dir", type=Path)
    ap.add_argument("--samples", type=Path)
    ap.add_argument("--expected", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.partition == "test":
        ap.error(
            "PENDING: Phase 09/10 gates, reviewed ds-v1.0 participant folds, owner FP budget and the "
            "archived Phase 11 pre-registration must exist before the single confirmatory run"
        )
    if args.output.exists() and args.model_dir:
        ap.error("output exists; evaluation artifacts are immutable")
    if args.model_dir:
        if not args.samples:
            ap.error("--model-dir needs --samples")
        return reproduce(args, ap)
    if not (args.run and args.synthetic_fixture):
        ap.error("participant per-task evaluation is PENDING ds-v1.0; use --run with --synthetic-fixture")
    cfg = load_config("configs/prototype.candidate.yaml")
    registry = ZoneRegistry.from_config(cfg["zones"])
    with RunLog(
        phase="11",
        task="11.4",
        slug="synthetic-per-task",
        config=cfg,
        experiments_dir=args.output,
        description="Per-task head vs geometry vs Baseline B on validation participants (SYNTHETIC)",
    ) as run:
        context = {**provenance(), "hardware": hardware()}
        context["codex_model"] = "NOT CODEX: Claude Opus 5.5 (claude-opus-5-5) via Claude Code"
        context["codex_reasoning_effort"] = "UNAVAILABLE to the agent; not asserted"
        write_json(run.dir / "execution.json", {**context, "input_run": str(args.run)})
        write_json(run.dir / "source-hashes.json", source_hashes())
        _, selected, _, cv, sessions = load_grid_run(args.run, cfg, variants=set(args.variants))
        b_cache, rows = {}, []
        for cell, row in selected:
            if not row["live_eligible"]:
                continue
            model, manifest = load_mt_model(row["model_dir"])
            config = MultiTaskConfig.from_dict(manifest["mt_config"])
            _, val, _ = load_mt_fold(cell["fold_dir"], config, aux_horizon_s=manifest["aux_horizon_s"])
            if val["hash"] != manifest["val_samples_hash"]:
                raise ValueError("validation archive changed since training")
            outputs = mt_predictions(model, val)
            geometry = frame_geometry(
                val, outputs[0].numpy(), registry, k=config.base.k, dt_step=config.base.dt_step
            )
            b_frames = {}
            for session in sessions:
                if session.table.participant not in manifest["val_participants"]:
                    continue
                if session.table.session_id not in b_cache:
                    frames, _, _ = baseline_b_frames(session, cfg)
                    b_cache[session.table.session_id] = frames
                b_frames.update(b_cache[session.table.session_id])
            comparison = per_task_comparison(
                config, manifest["target_scaling"], outputs, val, geometry, b_frames
            )
            rows.append(
                {
                    "variant": cell["variant"],
                    "family": config.family,
                    "fold": manifest["fold"],
                    "seed": manifest["seed"],
                    "model_dir": row["model_dir"],
                    "val_participants": manifest["val_participants"],
                    "head_metrics": task_metrics(config, manifest["target_scaling"], outputs, val),
                    "comparison": comparison,
                }
            )
            print(
                f"[{len(rows)}] {cell['variant']} {config.family} "
                f"fold={manifest['fold']} seed={manifest['seed']}"
            )
        write_json(run.dir / "per-task.json", rows)
        summary = {}
        for family in sorted({r["family"] for r in rows}):
            group = [r for r in rows if r["family"] == family]
            summary[family] = {
                "cells": len(group),
                "coverage_geometry": _mean([r["comparison"]["coverage"]["geometry"] for r in group]),
                "coverage_baseline_b": _mean([r["comparison"]["coverage"]["baseline_b"] for r in group]),
                "strike_ap": _mean(
                    [r["head_metrics"].get("strike", {}).get("average_precision") for r in group]
                ),
                "strike_auc": _mean([r["head_metrics"].get("strike", {}).get("roc_auc") for r in group]),
                "compared": {
                    "/".join(key): _mean(
                        [r["comparison"].get(key[0], {}).get(key[1], {}).get(key[2]) for r in group]
                    )
                    for key in COMPARED
                },
                "tti_strata": _strata(group),
            }
        write_json(run.dir / "summary.json", summary)
        for path in sorted(run.dir.iterdir()):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            {"cells": len(rows), "participant_claim": False}, notes="SYNTHETIC development diagnostics."
        )
        print(run.dir)


def _mean(values):
    values = [v for v in values if v is not None]
    return {
        "n": len(values),
        "mean": float(np.mean(values)) if values else None,
        "sd": float(np.std(values, ddof=1)) if len(values) > 1 else None,
    }


def _strata(group):
    strata = group[0]["comparison"].get("tti", {}).get("strata", [])
    return [
        {
            "true_tti_s": s["true_tti_s"],
            "head_mae_s": _mean([r["comparison"]["tti"]["strata"][i]["head"]["mae_s"] for r in group]),
            "geometry_mae_s": _mean(
                [r["comparison"]["tti"]["strata"][i]["geometry"]["mae_s"] for r in group]
            ),
            "geometry_coverage": _mean(
                [r["comparison"]["tti"]["strata"][i]["geometry_coverage"] for r in group]
            ),
        }
        for i, s in enumerate(strata)
    ]


if __name__ == "__main__":
    main()
