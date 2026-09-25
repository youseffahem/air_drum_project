"""Phase 11 candidate grids (loss weighting, head ablation) with an explicitly labelled synthetic mode.

Every cell: train on train folds only, export + parity, per-task validation metrics, then the
unchanged Phase 09 harness on the fold's validation sessions. The development selection rule and
budget are SYNTHETIC constants declared in plan.json; no held-out partition is opened.
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
from _p11 import (
    DEV_BUDGET,
    TAUS,
    CachedPredictions,
    default_controls,
    dev_selection,
    point_row,
    replay_session,
    train_and_export_mt,
)
from _p11_fixture import kinematic_fixture
from _runlog import RunLog

from spacedrums.config import load_config
from spacedrums.data.feature_dataset import export_folds
from spacedrums.eval.curves import plot_lead_fp
from spacedrums.features.normalize import NormStats
from spacedrums.features.windows import WindowParams
from spacedrums.models.temporal.config import TASKS, TTI_MODES, MultiTaskConfig, TemporalConfig
from spacedrums.models.temporal.consistency import AuxGate, AuxHeadSettings
from spacedrums.models.temporal.mt_adapter import DirectHeadDiagnostic, MultiTaskAnticipator
from spacedrums.models.temporal.mt_train import MultiTaskLossConfig
from spacedrums.models.temporal.train import TrainConfig

AUX = TASKS[1:]
H_MAX_S = 0.3
PROBABILITIES = (0.3, 0.5, 0.7)
# Declared before any run: a head "degrades" a primary metric when its mean paired change versus
# the trajectory-only reference exceeds DEGRADE_SIGMAS x the reference's pooled within-fold seed SD.
DEGRADE_SIGMAS = 2.0


def weighting_variants():
    return {
        "traj-only": (("trajectory",), {"weighting": "fixed"}),
        "fixed-1.0": (TASKS, {"weighting": "fixed"}),
        "fixed-0.3": (TASKS, {"weighting": "fixed", "lambdas": {t: 0.3 for t in AUX}}),
        "dominant-0.05": (TASKS, {"weighting": "trajectory_dominant", "dominant_lambda": 0.05}),
        "uncertainty": (TASKS, {"weighting": "uncertainty"}),
        "gradnorm": (TASKS, {"weighting": "gradnorm"}),
    }


SIMPLICITY = ("fixed-1.0", "fixed-0.3", "dominant-0.05", "uncertainty", "gradnorm")


def choose_weighting(summary):
    """Development rule declared in experiments/phase-11/weighting-choice-rule.json (applied mechanically)."""
    by = {}
    for entry in summary:
        by.setdefault(entry["variant"], []).append(entry)
    candidates = [v for v in SIMPLICITY if v in by]
    kept = [
        v
        for v in candidates
        if not any(e["paired_delta"]["ade"]["degrades_beyond_seed_variance"] for e in by[v])
    ]

    def mean(variant, metric):
        values = [
            e["metrics"][metric]["mean"] for e in by[variant] if e["metrics"][metric]["mean"] is not None
        ]
        return float(np.mean(values)) if values else None

    if not kept:
        chosen = min(candidates, key=lambda v: (np.mean([e["paired_delta"]["ade"]["mean"] for e in by[v]]),
                                                SIMPLICITY.index(v)))  # fmt: skip
        return chosen, "step 4: every scheme degraded ADE beyond seed variance"
    leads = {v: mean(v, "dev_lead_s") for v in kept}
    if any(value is not None for value in leads.values()):
        best = max(value for value in leads.values() if value is not None)
        tied = [v for v in kept if leads[v] is not None and abs(leads[v] - best) < 1e-12]
        reason = "step 2: highest mean development-budget lead"
    else:
        tied, reason = kept, "step 3: no feasible development lead"
    chosen = min(tied, key=lambda v: (mean(v, "ade"), SIMPLICITY.index(v)))
    return chosen, reason


def ablation_variants(chosen):
    variants = {"traj-only": (("trajectory",), {"weighting": "fixed"})}
    for task in AUX:
        variants["+" + task] = (("trajectory", task), chosen)
    variants["all"] = (TASKS, chosen)
    # No trajectory head: equal fixed weights; a trajectory-dominant scheme is undefined here.
    variants["no-traj"] = (AUX, {"weighting": "fixed"})
    return variants


def _get(tree, path):
    for key in path:
        if tree is None:
            return None
        tree = tree.get(key) if isinstance(tree, dict) else None
    return tree


METRICS = {
    "ade": ("validation", "trajectory", "ade"),
    "fde": ("validation", "trajectory", "fde"),
    "macro_ade": ("validation", "trajectory", "participant_macro_ade"),
    "strike_ap": ("validation", "strike", "average_precision"),
    "strike_auc": ("validation", "strike", "roc_auc"),
    "tti_mae_s": ("validation", "tti", "mae_s"),
    "tti_bias_s": ("validation", "tti", "bias_s"),
    "zone_accuracy": ("validation", "zone", "accuracy"),
    "position_median": ("validation", "position", "median"),
    "intensity_mae": ("validation", "intensity", "mae"),
    "intensity_r": ("validation", "intensity", "pearson_r"),
    "intensity_rho": ("validation", "intensity", "spearman_rho"),
    "dev_lead_s": ("harness", "median_lead_s"),
    "dev_fp_per_min": ("harness", "fp_per_min"),
    "dev_fn_rate": ("harness", "fn_rate"),
    "latency_p95_ms": ("latency_p95_ms",),
    "parameter_count": ("parameter_count",),
}
PRIMARY = {"ade": 1, "fde": 1, "dev_lead_s": -1, "dev_fp_per_min": 1}  # +1: higher is worse


def _stats(values):
    values = [v for v in values if v is not None and math.isfinite(v)]
    if not values:
        return {"n": 0, "mean": None, "sd": None}
    return {
        "n": len(values),
        "mean": float(np.mean(values)),
        "sd": float(np.std(values, ddof=1)) if len(values) > 1 else None,
    }


def summarize(rows):
    """Mean/SD over folds x seeds per variant/family, plus paired deltas versus traj-only."""
    groups = {}
    for row in rows:
        groups.setdefault((row["variant"], row["family"]), []).append(row)
    summary = []
    for (variant, family), cells in sorted(groups.items()):
        entry = {"variant": variant, "family": family, "cells": len(cells), "metrics": {}, "paired_delta": {}}
        for name, path in METRICS.items():
            entry["metrics"][name] = _stats([_get(c, path) for c in cells])
        reference = {(c["fold"], c["seed"]): c for c in groups.get(("traj-only", family), [])}
        for name, direction in PRIMARY.items():
            deltas, seed_sd = [], []
            for cell in cells:
                ref = reference.get((cell["fold"], cell["seed"]))
                a, b = _get(cell, METRICS[name]), _get(ref, METRICS[name]) if ref else None
                if a is not None and b is not None:
                    deltas.append(a - b)
            for fold in sorted({c["fold"] for c in reference.values()}):
                values = [_get(c, METRICS[name]) for c in reference.values() if c["fold"] == fold]
                values = [v for v in values if v is not None]
                if len(values) > 1:
                    seed_sd.append(float(np.std(values, ddof=1)))
            pooled_sd = float(np.sqrt(np.mean(np.square(seed_sd)))) if seed_sd else None
            mean = float(np.mean(deltas)) if deltas else None
            entry["paired_delta"][name] = {
                "n": len(deltas),
                "mean": mean,
                "sd": float(np.std(deltas, ddof=1)) if len(deltas) > 1 else None,
                "reference_seed_sd": pooled_sd,
                "degrades_beyond_seed_variance": bool(
                    mean is not None
                    and pooled_sd is not None
                    and direction * mean > DEGRADE_SIGMAS * pooled_sd
                ),
                "improves_beyond_seed_variance": bool(
                    mean is not None
                    and pooled_sd is not None
                    and -direction * mean > DEGRADE_SIGMAS * pooled_sd
                ),
            }
        entry["conflicts"] = _conflict_summary(cells)
        summary.append(entry)
    return summary


def _conflict_summary(cells):
    tasks = {}
    for cell in cells:
        path = Path(cell["model_dir"]) / "conflicts.json"
        if not path.exists():
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            for task, value in row["tasks"].items():
                if value["cosine"] is not None:
                    tasks.setdefault(task, []).append(value["cosine"])
    return {
        task: {
            "samples": len(v),
            "mean_cosine": float(np.mean(v)),
            "median_cosine": float(np.median(v)),
            "fraction_negative": float(np.mean(np.asarray(v) < 0)),
            "p10": float(np.percentile(v, 10)),
            "p90": float(np.percentile(v, 90)),
        }
        for task, v in sorted(tasks.items())
    }


def evaluate_cell(model, manifest, fold_dir, fold, sessions, dataset, cfg, output):
    stats = NormStats.read(
        Path(fold_dir) / "norm_stats.json",
        fold=fold["fold"],
        dataset_version=dataset["dataset_version"],
        dataset_hash=dataset["manifest_hash"],
        split_hash=dataset["split_hash"],
        schema=sessions[0].schema,
    )
    points = []
    for session in (s for s in sessions if s.table.participant in fold["val_participants"]):
        if manifest["live_eligible"]:
            cached = CachedPredictions(MultiTaskAnticipator(model, manifest))
            grid = [(default_controls(tau), False) for tau in TAUS]
        else:
            cached = CachedPredictions(DirectHeadDiagnostic(model, manifest, diagnostic=True))
            grid = [(default_controls(tau, p), True) for tau in TAUS for p in PROBABILITIES]
        for index, (controls, diagnostic) in enumerate(grid):
            gate = None if diagnostic else AuxGate(AuxHeadSettings(), manifest["heads"])
            _, evaluated = replay_session(
                session,
                cfg,
                arm="MODEL:C-MT",
                controls=controls,
                model_fn=cached,
                stats=stats,
                feature_n=manifest["N"],
                gate=gate,
                diagnostic=diagnostic,
                validate_records=index == 0,
            )
            settings = {
                **controls,
                "arm": "C-MT",
                "gate": "none" if not diagnostic else "direct-diagnostic",
                "family": manifest["family"],
                "heads": manifest["heads"],
                "seed": manifest["seed"],
            }
            points.append(
                point_row(
                    evaluated,
                    settings,
                    destination=output / "replay" / session.table.session_id / f"point-{index:03d}",
                )
            )
    return points


_STATE = {}


def _init_worker(state):
    import torch

    torch.set_num_threads(1)
    _STATE.update(state)


def run_cell(index, cell):
    """One grid cell; deterministic given the cell (its own seed), so workers may run in parallel."""
    s = _STATE
    config = MultiTaskConfig.from_dict(cell["mt_config"])
    training, loss = TrainConfig(**cell["training"]), MultiTaskLossConfig(**cell["loss"])
    output = s["run_dir"] / "models" / f"cell-{index:03d}"
    model, manifest, _, metrics = train_and_export_mt(
        cell["fold_dir"],
        output,
        config,
        training,
        loss,
        context=s["context"],
        aux_horizon_s=cell["aux_horizon_s"],
    )
    benchmark = json.loads((output / "latency.json").read_text(encoding="utf-8"))
    fold = next(f for f in s["cv"]["folds"] if f["fold"] == manifest["fold"])
    points = evaluate_cell(
        model, manifest, cell["fold_dir"], fold, s["sessions"], s["dataset"], s["cfg"], output
    )
    row = {
        "variant": cell["variant"],
        "model_dir": str(output),
        "fold": manifest["fold"],
        "seed": training.seed,
        "family": config.family,
        "heads": list(config.heads),
        "weighting": loss.weighting,
        "live_eligible": manifest["live_eligible"],
        "source_kind": manifest["source_kind"],
        "validation": metrics,
        "task_counts": manifest["task_counts"],
        "best_task_weights": manifest["best_task_weights"],
        "harness": dev_selection(points),
        "latency_p95_ms": benchmark["results"]["windowed"]["p95_ms"],
        "latency_note": "contended development timing (parallel grid workers); see Task 11.8 run",
        "parameter_count": manifest["parameter_count"],
        "parameter_bytes": manifest["parameter_bytes"],
    }
    return index, row, [{**p, "variant": cell["variant"]} for p in points]


def main(kind):
    ap = argparse.ArgumentParser(description=__doc__)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic-fixture", action="store_true")
    source.add_argument(
        "--plan", type=Path, help="JSON cells (mt_config, training, loss, fold_dir, aux_horizon_s)"
    )
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--seeds", type=int, nargs="+", default=[10, 11, 12])
    ap.add_argument("--folds", type=int, nargs="+", default=[0, 1, 2, 3])
    ap.add_argument("--families", nargs="+", default=["gru", "tcn"], choices=("gru", "tcn"))
    ap.add_argument("--variants", nargs="+", help="subset of variant names (default: all)")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--hidden", type=int, default=16)
    ap.add_argument("--conflict-every", type=int, default=5)
    ap.add_argument("--weighting-json", help="ablation: explicit loss settings (recorded)")
    ap.add_argument(
        "--weighting-from-run", type=Path, help="ablation: apply the declared rule to a weighting run"
    )
    ap.add_argument("--identities", type=int, default=5)
    ap.add_argument("--seconds", type=float, default=24.0)
    ap.add_argument("--workers", type=int, default=1, help="parallel cells (1 torch thread each)")
    args = ap.parse_args()
    if len(set(args.seeds)) < 3:
        ap.error("three distinct seeds per variant/fold are required (record a deviation otherwise)")
    if kind in ("ablation", "tti") and not (args.weighting_json or args.weighting_from_run):
        ap.error("the ablation uses the weighting chosen by the weighting comparison; pass --weighting-json")
    choice = None
    if args.weighting_from_run:
        summary = json.loads((args.weighting_from_run / "summary.json").read_text(encoding="utf-8"))
        name, reason = choose_weighting(summary)
        args.weighting_json = json.dumps(weighting_variants()[name][1])
        choice = {"run": str(args.weighting_from_run), "variant": name, "reason": reason}
    if not args.synthetic_fixture:
        ap.error("participant plans are PENDING: ds-v1.0 folds, Phase 09/10 gates and owner budgets")
    cfg = load_config("configs/prototype.candidate.yaml")
    with RunLog(
        phase="11",
        task={"weighting": "11.2", "tti": "11.1"}.get(kind, "11.6"),
        slug=("synthetic-" if args.synthetic_fixture else "") + kind,
        config=cfg,
        experiments_dir=args.output,
        description="Phase 11 candidate grid; no held-out evaluation or ship decision",
    ) as run:
        context = {**provenance(), "hardware": hardware()}
        context["codex_model"] = "NOT CODEX: Claude Opus 5.5 (claude-opus-5-5) via Claude Code"
        context["codex_reasoning_effort"] = "UNAVAILABLE to the agent; not asserted"
        write_json(run.dir / "source-hashes.json", source_hashes())
        write_json(run.dir / "execution.json", context)
        dataset, cv, sessions = kinematic_fixture(cfg, identities=args.identities, seconds=args.seconds)
        dataset = {**dataset, "split_hash": cv["split_hash"]}
        folder = run.dir / "features" / f"n{args.n}-k{args.k}"
        horizon = args.k / 30
        params = WindowParams(args.n, math.ceil(horizon / 0.025) + 1, horizon, H_MAX_S, 1, 0)
        export_folds(dataset, cv, sessions, folder, params)
        zone_ids = tuple(z["zone_id"] for z in cfg["zones"])
        if kind == "weighting":
            variants = weighting_variants()
        elif kind == "tti":
            chosen = json.loads(args.weighting_json)
            variants = {f"tti-{m}": (("trajectory", "tti"), chosen, {"tti_mode": m}) for m in TTI_MODES}
        else:
            chosen = json.loads(args.weighting_json)
            variants = ablation_variants(chosen)
        if args.variants:
            variants = {k: v for k, v in variants.items() if k in args.variants}
        cells = []
        for (name, (heads, loss, *extra)), family, fold, seed in itertools.product(
            variants.items(), args.families, args.folds, args.seeds
        ):
            base = TemporalConfig(
                family, sessions[0].schema.dimension, n=args.n, k=args.k, hidden=args.hidden
            )
            config = MultiTaskConfig(
                base,
                heads=heads,
                zone_ids=zone_ids if "zone" in heads else (),
                h_max_s=H_MAX_S,
                **(extra[0] if extra else {}),
            )
            cells.append(
                {
                    "variant": name,
                    "mt_config": config.to_dict(),
                    "training": {"seed": seed, "epochs": args.epochs, "patience": args.epochs},
                    "loss": {**loss, "conflict_every": args.conflict_every},
                    "fold_dir": str(folder / f"fold-{fold}"),
                    "aux_horizon_s": horizon,
                }
            )
        write_json(
            run.dir / "plan.json",
            {
                "kind": kind,
                "evidence": "SYNTHETIC kinematic fixture (scripts/_p11_fixture.py); not participant data",
                "fixture": {"identities": args.identities, "seconds": args.seconds},
                "window_params": asdict(params),
                "cells": cells,
                "test_access": False,
                "dev_budget": DEV_BUDGET,
                "taus": TAUS,
                "degrade_rule": f"mean paired delta > {DEGRADE_SIGMAS} x pooled within-fold seed SD "
                "of traj-only",
                "weighting_choice_input": args.weighting_json,
                "weighting_choice": choice,
            },
        )
        write_json(run.dir / "synthetic-split.json", cv)
        state = {
            "run_dir": run.dir,
            "context": context,
            "cv": cv,
            "sessions": sessions,
            "dataset": dataset,
            "cfg": cfg,
        }
        rows, curves_by_cell = {}, {}
        if args.workers > 1:
            with concurrent.futures.ProcessPoolExecutor(
                args.workers, initializer=_init_worker, initargs=(state,)
            ) as pool:
                futures = [pool.submit(run_cell, i, c) for i, c in enumerate(cells)]
                for future in concurrent.futures.as_completed(futures):
                    index, row, points = future.result()
                    rows[index], curves_by_cell[index] = row, points
                    _progress(len(rows), len(cells), row)
        else:
            _init_worker(state)
            for i, c in enumerate(cells):
                index, row, points = run_cell(i, c)
                rows[index], curves_by_cell[index] = row, points
                _progress(len(rows), len(cells), row)
        results = [rows[i] for i in range(len(cells))]
        curves = [p for i in range(len(cells)) for p in curves_by_cell[i]]
        write_json(run.dir / "results.json", results)
        write_json(run.dir / "curves.json", curves)
        summary = summarize(results)
        write_json(run.dir / "summary.json", summary)
        plot_lead_fp(
            [
                {**p, "settings": {**p["settings"], "arm": p["variant"], "K": p["settings"]["family"]}}
                for p in curves
            ],
            run.dir / "lead-vs-fp.png",
            title=f"SYNTHETIC development: {kind} (C-MT variants)",
        )
        for path in sorted(run.dir.rglob("*")):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            {"models": len(results), "operating_points": len(curves), "participant_claim": False},
            notes="SYNTHETIC kinematic fixture; development diagnostics only. Participant gate PENDING.",
        )
        print(run.dir)


def _progress(done, total, row):
    print(
        f"[{done}/{total}] {row['variant']} {row['family']} fold={row['fold']} seed={row['seed']} "
        f"ADE={_get(row, METRICS['ade'])} lead={row['harness']['median_lead_s']}",
        flush=True,
    )
