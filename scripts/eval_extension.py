"""Phase 12 extension grids (Tasks 12.2-12.7) in an explicitly labelled synthetic mode, and the
exported-model reproduction the verifier runs.

Every trained cell: train on the fold's training identities only, TorchScript export and parity,
validation metrics, then the unchanged Phase 09 harness on the fold's validation sessions over the
declared control grid (docs/experiments/phase-12-prereg.md). Evaluation-only rules (E2 M2, E4 seed
ensemble, E5 bounded acceleration) reuse trained cells. The development budget is the SYNTHETIC
Phase 11 constant. No held-out partition is opened; participant plans are refused (PENDING).
"""

import argparse
import concurrent.futures
import itertools
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
from _p10 import hardware, provenance, source_hashes, write_json
from _p11 import fold_stats
from _p11_fixture import kinematic_fixture
from _p12 import (
    DEV,
    EXTENSIONS,
    FAMILIES,
    FOLDS,
    NOT_CODEX,
    PROBABILISTIC,
    RULES,
    SEEDS,
    TAUS,
    VARIANTS,
    budget_note,
    calibration_for_trained,
    dev_pick,
    evaluate_sessions,
    ext_config,
    load_run_rows,
    predeclaration_record,
    rule_models,
    run_rule,
    train_and_export_ext,
    train_reference,
    training_config,
)
from _runlog import RunLog

from spacedrums.config import load_config
from spacedrums.data.feature_dataset import export_folds
from spacedrums.eval.curves import plot_lead_fp
from spacedrums.features.windows import WindowParams
from spacedrums.models.temporal import TemporalConfig
from spacedrums.models.temporal.adapter import TemporalAnticipator
from spacedrums.models.temporal.data import read_samples, sha
from spacedrums.models.temporal.export import load_model
from spacedrums.models.temporal.ext import ExtensionConfig, load_extension_model
from spacedrums.models.temporal.ext.adapter import ExtensionAnticipator
from spacedrums.models.temporal.ext.long_horizon import select_grid
from spacedrums.models.temporal.ext.train import validation_report

ROOT = Path(__file__).resolve().parents[1]
H_MAX_S = 0.3
METRICS = {
    "ade": ("validation", "trajectory", "ade"),
    "fde": ("validation", "trajectory", "fde"),
    "macro_ade": ("validation", "trajectory", "participant_macro_ade"),
    "dev_lead_s": ("harness", "median_lead_s"),
    "dev_fp_per_min": ("harness", "fp_per_min"),
    "dev_fn_rate": ("harness", "fn_rate"),
    "dev_timing_mae_s": ("harness", "timing_mae_s"),
    "dev_zone_accuracy": ("harness", "zone_accuracy"),
    "ece": ("calibration", "ece"),
    "brier": ("calibration", "brier"),
    "roc_auc": ("calibration", "roc_auc"),
    "latency_p95_ms": ("latency_p95_ms",),
    "parameter_count": ("parameter_count",),
}


def get(tree, path):
    for key in path:
        if not isinstance(tree, dict):
            return None
        tree = tree.get(key)
    return tree


def summarize(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["variant"], row["family"]), []).append(row)
    summary = []
    for (variant, family), cells in sorted(groups.items()):
        entry = {"variant": variant, "family": family, "cells": len(cells), "metrics": {}}
        entry["feasible_cells"] = sum(bool(get(c, ("harness", "feasible"))) for c in cells)
        for name, path in METRICS.items():
            values = [v for v in (get(c, path) for c in cells) if v is not None and math.isfinite(v)]
            entry["metrics"][name] = {
                "n": len(values),
                "mean": float(np.mean(values)) if values else None,
                "sd": float(np.std(values, ddof=1)) if len(values) > 1 else None,
            }
        summary.append(entry)
    return summary


def horizon_params(max_step):
    horizon = max_step * DEV["dt_step"]
    return WindowParams(DEV["n"], math.ceil(horizon / 0.025) + 1, horizon, H_MAX_S, 1, 0)


_STATE = {}


def _init_worker(state):
    import torch

    torch.set_num_threads(1)
    _STATE.update(state)


def _fold(fold_id):
    return next(f for f in _STATE["cv"]["folds"] if f["fold"] == fold_id)


def run_cell(index, cell):
    """One trained cell; deterministic given its seed, so workers may run in parallel."""
    s = _STATE
    output = s["run_dir"] / "models" / f"cell-{index:03d}"
    training = training_config(cell["seed"], cell["epochs"])
    features = s["sessions"][0].schema.dimension
    if cell["variant"] == "ref":
        model, manifest, val, metrics = train_reference(
            cell["fold_dir"], output, cell["family"], features, training, context=s["context"]
        )
        config = ExtensionConfig.from_reference(manifest["config"])

        def factory():
            return TemporalAnticipator(model, manifest)

    else:
        config = ExtensionConfig.from_dict(cell["ext_config"])
        model, manifest, val, metrics = train_and_export_ext(
            cell["fold_dir"], output, config, training, context=s["context"], variant=cell["variant"]
        )

        def factory():
            return ExtensionAnticipator(model, manifest, variant=cell["variant"])

    fold = _fold(manifest["fold"])
    stats = fold_stats(cell, fold, s["dataset"], s["sessions"])
    points = evaluate_sessions(
        factory,
        manifest,
        fold,
        s["sessions"],
        stats,
        s["cfg"],
        output,
        probabilistic=cell["variant"] in PROBABILISTIC,
        family=manifest["family"],
    )
    benchmark = json.loads((output / "latency.json").read_text(encoding="utf-8"))
    row = {
        "variant": cell["variant"],
        "extension": manifest.get("extensions", []),
        "model_dir": str(output),
        "fold_dir": cell["fold_dir"],
        "fold": manifest["fold"],
        "seed": training.seed,
        "family": manifest["family"],
        "source_kind": manifest["source_kind"],
        "offsets_s": list(config.offsets_s),
        "validation": {"trajectory": metrics},
        "harness": dev_pick(points),
        "calibration": calibration_for_trained(cell["variant"], config, model, val, s["cfg"]),
        "latency_p95_ms": benchmark["results"]["windowed"]["p95_ms"],
        "latency_note": "contended development timing (parallel grid workers); see the isolated latency run",
        "parameter_count": manifest["parameter_count"],
        "parameter_bytes": manifest["parameter_bytes"],
        "checkpoint_hash": manifest["checkpoint_hash"],
    }
    return index, row, [{**p, "variant": cell["variant"]} for p in points]


def run_rule_cell(index, rule, rows):
    s = _STATE
    output = s["run_dir"] / "rules" / f"{rule}-{index:03d}"
    fold = _fold(rows[0]["fold"])
    fold_dir = rows[0]["fold_dir"]
    stats = fold_stats({"fold_dir": fold_dir}, fold, s["dataset"], s["sessions"])
    row, points = run_rule(rule, rows, fold, fold_dir, s["sessions"], stats, s["cfg"], output)
    row["rule_dir"], row["fold_dir"] = str(output), fold_dir
    return index, row, [{**p, "variant": rule} for p in points]


def reproduce(args):
    """Exported-model validation metrics, compared numerically with an archived validation.json."""
    manifest = json.loads((args.reproduce / "manifest.json").read_text(encoding="utf-8"))
    if sha(args.samples) != manifest["val_samples_hash"]:
        raise SystemExit("only this model's hashed validation samples are authorized")
    if "ext_config" in manifest:
        model, manifest = load_extension_model(args.reproduce)
        config = ExtensionConfig.from_dict(manifest["ext_config"])
    else:
        model, manifest = load_model(args.reproduce)
        config = ExtensionConfig.from_reference(manifest["config"])
    val = select_grid(read_samples(args.samples, config.data_view), config)
    metrics = validation_report(config, model, val)
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    compared = {k: metrics[k] for k in expected}

    def compare(a, b):
        if isinstance(a, dict):
            assert a.keys() == b.keys()
            for key in a:
                compare(a[key], b[key])
        elif isinstance(a, list):
            assert len(a) == len(b)
            for x, y in zip(a, b, strict=True):
                compare(x, y)
        elif isinstance(a, (float, int)) and not isinstance(a, bool):
            np.testing.assert_allclose(a, b, atol=1e-6, rtol=1e-5)
        else:
            assert a == b

    compare(compared, expected)
    write_json(
        args.result,
        {
            "model_dir": str(args.reproduce),
            "export_hash": manifest["export_hash"],
            "reproduced": True,
            "atol": 1e-6,
            "rtol": 1e-5,
            "validated": False,
            "scope": "same environment subprocess",
        },
    )
    print(f"REPRODUCED {args.reproduce}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extension", choices=sorted(EXTENSIONS))
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--synthetic-fixture", action="store_true")
    source.add_argument("--plan", type=Path, help="participant CV plan (PENDING; refused)")
    ap.add_argument("--partition", choices=("val", "test"), default="val")
    ap.add_argument("--output", type=Path, default=ROOT / "experiments/phase-12")
    ap.add_argument("--reference-run", type=Path, help="completed ref run (E4 ensemble, E5 smoothing)")
    ap.add_argument(
        "--feasibility-run", type=Path, help="E3: completed feasibility run with verdict FEASIBLE"
    )
    ap.add_argument("--epochs", type=int, default=DEV["epochs"])
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    ap.add_argument("--folds", type=int, nargs="+", default=list(FOLDS))
    ap.add_argument("--families", nargs="+", default=list(FAMILIES), choices=FAMILIES)
    ap.add_argument("--workers", type=int, default=1, help="parallel cells (1 torch thread each)")
    ap.add_argument("--reproduce", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--samples", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--expected", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.partition == "test":
        ap.error("PENDING: held-out access needs adopted extensions and the archived protocol (Task 12.8)")
    if args.reproduce:
        return reproduce(args)
    if args.plan:
        ap.error("participant plans are PENDING: ds-v1.0 folds, Phase 09/10/11 gates and owner budgets")
    if not args.synthetic_fixture or not args.extension:
        ap.error("--extension and --synthetic-fixture are required")
    if len(set(args.seeds)) < 3:
        ap.error("three distinct seeds per variant/fold are declared")
    spec = EXTENSIONS[args.extension]
    needs_reference = any(RULES[r]["source"] == "ref" for r in spec["rules"])
    if needs_reference and not args.reference_run:
        ap.error("this extension's evaluation-only rules need --reference-run")
    feasibility = None
    if args.extension == "e3":
        if not args.feasibility_run:
            ap.error("E3 trains only after its CPU feasibility gate: pass --feasibility-run")
        feasibility = json.loads((args.feasibility_run / "feasibility.json").read_text(encoding="utf-8"))
        record = json.loads((args.feasibility_run / "run.json").read_text(encoding="utf-8"))
        if record["status"] != "COMPLETED" or feasibility["verdict"] != "FEASIBLE":
            ap.error(f"E3 feasibility verdict is {feasibility['verdict']}: training is not justified")
    declared = predeclaration_record()
    if not declared["unchanged_since_archive"]:
        ap.error("the pre-declared documents changed after archiving; record a deviation first")
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    with RunLog(
        phase="12",
        task=spec["task"],
        slug=f"synthetic-{args.extension}",
        config=cfg,
        experiments_dir=args.output,
        description="Phase 12 extension grid on the SYNTHETIC fixture; no held-out evaluation or adoption",
    ) as run:
        context = {**provenance(), "hardware": hardware(), **NOT_CODEX}
        write_json(run.dir / "source-hashes.json", source_hashes())
        write_json(run.dir / "execution.json", context)
        dataset, cv, sessions = kinematic_fixture(cfg, identities=DEV["identities"], seconds=DEV["seconds"])
        dataset = {**dataset, "split_hash": cv["split_hash"]}
        schema = sessions[0].schema
        residual = (schema.index["vx"], schema.index["vy"])
        cells, folders = [], {}
        for variant in spec["variants"]:
            families = ("tt",) if VARIANTS[variant].get("family") == "tt" else args.families
            for family, fold, seed in itertools.product(families, args.folds, args.seeds):
                if variant == "ref":
                    config = TemporalConfig(family, schema.dimension, n=DEV["n"], k=4, hidden=DEV["hidden"])
                    entry, max_step = {"config": config.to_dict()}, config.k
                else:
                    config = ext_config(
                        variant, family, features=schema.dimension, residual_features=residual
                    )
                    entry, max_step = {"ext_config": config.to_dict()}, config.max_step
                if max_step not in folders:
                    folder = run.dir / "features" / f"n{DEV['n']}-k{max_step}"
                    export_folds(dataset, cv, sessions, folder, horizon_params(max_step))
                    folders[max_step] = folder
                cells.append(
                    {
                        "variant": variant,
                        "family": family,
                        "fold": fold,
                        "seed": seed,
                        "epochs": args.epochs,
                        "fold_dir": str(folders[max_step] / f"fold-{fold}"),
                        **entry,
                    }
                )
        reference_rows = []
        if needs_reference:
            _, rows = load_run_rows(args.reference_run, extension="ref")
            reference_rows = [r for r in rows if r["variant"] == "ref"]
        write_json(
            run.dir / "plan.json",
            {
                "extension": args.extension,
                "task": spec["task"],
                "evidence": "SYNTHETIC kinematic fixture (scripts/_p11_fixture.py); not participant data",
                "fixture": {"identities": DEV["identities"], "seconds": DEV["seconds"]},
                "window_params": {str(k): asdict(horizon_params(k)) for k in folders},
                "cells": cells,
                "rules": list(spec["rules"]),
                "reference_run": None if not args.reference_run else str(args.reference_run),
                "feasibility_run": None if not args.feasibility_run else str(args.feasibility_run),
                "feasibility": feasibility,
                "test_access": False,
                "taus": TAUS,
                "budget": budget_note(),
                "predeclaration": declared,
            },
        )
        write_json(run.dir / "synthetic-split.json", cv)
        state = {"run_dir": run.dir, "context": context, "cv": cv, "sessions": sessions, "dataset": dataset}
        state["cfg"] = cfg
        rows, curves = {}, {}
        _execute(args.workers, state, [(run_cell, (i, c)) for i, c in enumerate(cells)], rows, curves)
        results = [rows[i] for i in range(len(cells))]
        rule_tasks = []
        for rule in spec["rules"]:
            source_rows = (
                reference_rows
                if RULES[rule]["source"] == "ref"
                else [r for r in results if r["variant"] == RULES[rule]["source"]]
            )
            for group in rule_models(rule, source_rows):
                rule_tasks.append((rule, group))
        offset = len(cells)
        tasks = [(run_rule_cell, (offset + i, rule, group)) for i, (rule, group) in enumerate(rule_tasks)]
        _execute(args.workers, state, tasks, rows, curves)
        results += [rows[offset + i] for i in range(len(rule_tasks))]
        all_curves = [p for i in sorted(curves) for p in curves[i]]
        write_json(run.dir / "results.json", results)
        write_json(run.dir / "curves.json", all_curves)
        write_json(run.dir / "summary.json", summarize(results))
        plot_lead_fp(
            [
                {**p, "settings": {**p["settings"], "arm": p["variant"], "K": p["settings"]["family"]}}
                for p in all_curves
            ],
            run.dir / "lead-vs-fp.png",
            title=f"SYNTHETIC development: Phase 12 {args.extension}",
        )
        for path in sorted(run.dir.rglob("*")):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            {"models": len(cells), "rules": len(rule_tasks), "operating_points": len(all_curves)},
            notes="SYNTHETIC kinematic fixture; development diagnostics only; no adoption. "
            "Participant gate PENDING.",
        )
        print(run.dir)
    return 0


def _execute(workers, state, tasks, rows, curves):
    if not tasks:
        return
    if workers > 1:
        with concurrent.futures.ProcessPoolExecutor(
            workers, initializer=_init_worker, initargs=(state,)
        ) as pool:
            futures = [pool.submit(fn, *task_args) for fn, task_args in tasks]
            for future in concurrent.futures.as_completed(futures):
                index, row, points = future.result()
                rows[index], curves[index] = row, points
                _progress(len(rows), row)
    else:
        _init_worker(state)
        for fn, task_args in tasks:
            index, row, points = fn(*task_args)
            rows[index], curves[index] = row, points
            _progress(len(rows), row)


def _progress(done, row):
    print(
        f"[{done}] {row['variant']} {row['family']} fold={row['fold']} seed={row['seed']} "
        f"ADE={get(row, METRICS['ade'])} lead={get(row, ('harness', 'median_lead_s'))} "
        f"feasible={get(row, ('harness', 'feasible'))}",
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
