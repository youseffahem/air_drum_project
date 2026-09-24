"""Candidate-grid runner with explicitly labelled synthetic development mode."""

import argparse
import itertools
import json
import math
from pathlib import Path

from _p08_fixture import synthetic_fixture
from _p10 import hardware, provenance, source_hashes, train_and_export, write_json
from _p10_eval import evaluate_grid, summarize_comparison
from _runlog import RunLog

from spacedrums.config import load_config
from spacedrums.data.feature_dataset import export_folds
from spacedrums.eval.curves import plot_lead_fp
from spacedrums.features.normalize import NormStats
from spacedrums.features.windows import WindowParams
from spacedrums.models.temporal import TemporalConfig
from spacedrums.models.temporal.train import TrainConfig


def main(kind):
    ap = argparse.ArgumentParser(description=__doc__)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic-fixture", action="store_true")
    source.add_argument("--plan", type=Path, help="JSON cells with model, fold_dir, training, aux_horizon_s")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--seeds", type=int, nargs="+", default=[10, 11, 12])
    ap.add_argument("--folds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--k", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--n", type=int, nargs="+", default=[4, 8, 16])
    args = ap.parse_args()
    if len(set(args.seeds)) < 3:
        ap.error(
            "this sweep requires three distinct seeds; record a compute-limited protocol before changing it"
        )
    cfg = load_config("configs/prototype.candidate.yaml")
    with RunLog(
        phase="10",
        task="10.8" if kind == "horizon" else "10.9",
        slug="synthetic-" + kind if args.synthetic_fixture else kind + "-sweep",
        config=cfg,
        experiments_dir=args.output,
        description="Candidate sweep; no held-out evaluation or model selection",
    ) as run:
        context = {**provenance(), "hardware": hardware()}
        write_json(run.dir / "source-hashes.json", source_hashes())
        write_json(run.dir / "execution.json", context)
        cells = []
        if args.synthetic_fixture:
            manifest, cv, sessions = synthetic_fixture(cfg)
            settings = (
                [(8, k, False) for k in args.k]
                if kind == "horizon"
                else [(n, 4, aux) for n in args.n for aux in (False, True)]
            )
            for n, k, aux in settings:
                folder = run.dir / "features" / f"n{n}-k{k}"
                if not folder.exists():
                    export_folds(
                        manifest,
                        cv,
                        sessions,
                        folder,
                        WindowParams(n, math.ceil(k / 30 / 0.025) + 1, k / 30, max(0.3, k / 30), 1, 0),
                    )
                for family, fold, seed in itertools.product(("gru", "tcn"), args.folds, args.seeds):
                    if fold not in {f["fold"] for f in cv["folds"]}:
                        ap.error("unknown fixture fold")
                    cells.append(
                        {
                            "model": TemporalConfig(
                                family, sessions[0].schema.dimension, n=n, k=k, hidden=12, auxiliary=aux
                            ).to_dict(),
                            "training": {
                                "seed": seed,
                                "epochs": args.epochs,
                                "patience": args.epochs,
                                "lambda_aux": 0.1 if aux else 0,
                            },
                            "fold_dir": str(folder / f"fold-{fold}"),
                            "aux_horizon_s": k / 30,
                        }
                    )
        else:
            cells = json.loads(args.plan.read_text(encoding="utf-8"))["cells"]
            # Preflight the complete plan before any training; no silent missing seed cells.
            groups = {}
            for cell in cells:
                key = (json.dumps(cell["model"], sort_keys=True), cell["fold_dir"])
                groups.setdefault(key, set()).add(cell["training"]["seed"])
            if not groups or any(len(seeds) < 3 for seeds in groups.values()):
                ap.error("each model/fold cell requires three distinct seeds")
        write_json(run.dir / "plan.json", {"kind": kind, "cells": cells, "test_access": False})
        results, curves = [], []
        for index, cell in enumerate(cells):
            config, training = TemporalConfig(**cell["model"]), TrainConfig(**cell["training"])
            output = run.dir / "models" / f"cell-{index:03d}"
            model, model_manifest, _, metrics = train_and_export(
                cell["fold_dir"],
                output,
                config,
                training,
                context=context,
                aux_horizon_s=cell.get("aux_horizon_s"),
                calls=60,
            )
            benchmark = json.loads((output / "latency.json").read_text())
            row = {
                "model_dir": str(output),
                "fold": model_manifest["fold"],
                "seed": training.seed,
                "family": config.family,
                "N": config.n,
                "K": config.k,
                "auxiliary": config.auxiliary,
                "source_kind": model_manifest["source_kind"],
                "validation": metrics,
                "latency_p95_ms": benchmark["results"]["windowed"]["p95_ms"],
                "parameter_count": model_manifest["parameter_count"],
                "parameter_bytes": model_manifest["parameter_bytes"],
            }
            if args.synthetic_fixture:
                fold = next(f for f in cv["folds"] if f["fold"] == model_manifest["fold"])
                stats = NormStats.read(
                    Path(cell["fold_dir"]) / "norm_stats.json",
                    fold=fold["fold"],
                    dataset_version=manifest["dataset_version"],
                    dataset_hash=manifest["manifest_hash"],
                    split_hash=cv["split_hash"],
                    schema=sessions[0].schema,
                )
                for session in (s for s in sessions if s.table.participant in fold["val_participants"]):
                    points = evaluate_grid(
                        session,
                        cfg,
                        model=model,
                        manifest=model_manifest,
                        stats=stats,
                        output=output / "replay" / session.table.session_id,
                    )
                    curves.extend({**p, "latency_p95_ms": row["latency_p95_ms"]} for p in points)
            else:
                row["event_evaluation"] = "PENDING: use eval_temporal.py on each validation session"
            results.append(row)
            write_json(run.dir / "results.json", results)
            print(
                f"[{index + 1}/{len(cells)}] {config.family} N={config.n} K={config.k} "
                f"aux={config.auxiliary} "
                f"fold={row['fold']} seed={training.seed} ADE={metrics['ade']:.6f}",
                flush=True,
            )
        write_json(run.dir / "curves.json", curves)
        write_json(run.dir / "comparison.json", summarize_comparison(curves))
        plot_lead_fp(
            curves,
            run.dir / "lead-vs-fp.png",
            title="SYNTHETIC development: " + kind if args.synthetic_fixture else kind,
        )
        for path in sorted(run.dir.rglob("*")):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            {"models": len(results), "operating_points": len(curves), "participant_claim": False},
            notes="Synthetic fixture results cannot select a research horizon/model. "
            "Participant phase gate PENDING.",
        )
        print(run.dir)


if __name__ == "__main__":
    main("horizon")
