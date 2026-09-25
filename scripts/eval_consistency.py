"""Consistency gating (Task 11.5) and commit-time intensity sources (Task 11.7) for C-MT.

For every selected grid cell the unchanged harness replays the validation sessions once per
gate variant and tau_commit; model outputs are cached, so only the post-geometry gate and the
commit policy differ between points. Each variant reports lead/FP/FN, the gate's own decision
counts and the change in FP/FN against the ungated point (a gate may suppress valid strikes).
"""

import argparse
from pathlib import Path

import numpy as np
from _p10 import hardware, provenance, source_hashes, write_json
from _p11 import (
    TAUS,
    CachedPredictions,
    baseline_b_frames,
    commit_time_intensity,
    default_controls,
    dev_selection,
    fold_stats,
    load_grid_run,
    point_row,
    replay_session,
)
from _runlog import RunLog

from spacedrums.config import load_config
from spacedrums.eval.curves import plot_lead_fp
from spacedrums.geometry import ZoneRegistry
from spacedrums.models.temporal.consistency import AuxGate, AuxHeadSettings
from spacedrums.models.temporal.export import load_mt_model
from spacedrums.models.temporal.mt_adapter import MultiTaskAnticipator

TIGHT = {"tti_tolerance_s": 0.02, "position_tolerance": 0.03}
LOOSE = {"tti_tolerance_s": 0.05, "position_tolerance": 0.06}
CHECKS = ("zone", "tti", "position")


def gate_variants():
    """Candidate gate settings; names are stable keys in every output table."""
    variants = {"none": AuxHeadSettings()}
    for p in (0.3, 0.5, 0.7):
        variants[f"p_aux-{p}"] = AuxHeadSettings(use_p_aux=True, p_aux=p)
    for name, tol in (("tight", TIGHT), ("loose", LOOSE)):
        variants[f"agree-{name}"] = AuxHeadSettings(use_agreement=True, agreement_checks=CHECKS, **tol)
        variants[f"both-0.5-{name}"] = AuxHeadSettings(
            use_p_aux=True, p_aux=0.5, use_agreement=True, agreement_checks=CHECKS, **tol
        )
    variants["intensity-head"] = AuxHeadSettings(intensity_source="head")
    return variants


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True, help="completed Phase 11 grid run (e.g. ablation)")
    ap.add_argument("--variants", nargs="+", default=["all"], help="grid variants to evaluate")
    ap.add_argument("--synthetic-fixture", action="store_true")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if not args.synthetic_fixture:
        ap.error("participant gating evaluation is PENDING ds-v1.0; use --synthetic-fixture")
    cfg = load_config("configs/prototype.candidate.yaml")
    registry = ZoneRegistry.from_config(cfg["zones"])
    gates = gate_variants()
    with RunLog(
        phase="11",
        task="11.5",
        slug="synthetic-gating",
        config=cfg,
        experiments_dir=args.output,
        description="C-MT consistency gates and commit-time intensity sources (SYNTHETIC)",
    ) as run:
        context = {**provenance(), "hardware": hardware()}
        context["codex_model"] = "NOT CODEX: Claude Opus 5.5 (claude-opus-5-5) via Claude Code"
        context["codex_reasoning_effort"] = "UNAVAILABLE to the agent; not asserted"
        write_json(run.dir / "execution.json", {**context, "input_run": str(args.run)})
        write_json(run.dir / "source-hashes.json", source_hashes())
        write_json(
            run.dir / "plan.json",
            {"gates": {k: v.to_dict() for k, v in gates.items()}, "taus": TAUS, "test_access": False},
        )
        _, selected, dataset, cv, sessions = load_grid_run(args.run, cfg, variants=set(args.variants))
        curves, intensity, b_points, b_cache = [], [], [], {}
        for cell, row in selected:
            if not row["live_eligible"]:
                continue
            model, manifest = load_mt_model(row["model_dir"])
            fold = next(f for f in cv["folds"] if f["fold"] == manifest["fold"])
            stats = fold_stats(cell, fold, dataset, sessions)
            for session in (s for s in sessions if s.table.participant in fold["val_participants"]):
                sid = session.table.session_id
                if sid not in b_cache:
                    frames, _, _ = baseline_b_frames(session, cfg)
                    b_cache[sid] = frames
                    for tau in TAUS:
                        _, evaluated = replay_session(session, cfg, arm="B", controls=default_controls(tau))
                        b_points.append(
                            point_row(evaluated, {"arm": "B", "tti_commit_s": tau, "session": sid})
                        )
                cached = CachedPredictions(MultiTaskAnticipator(model, manifest))
                reference = {}
                for name, settings in gates.items():
                    for tau in TAUS:
                        gate = AuxGate(settings, manifest["heads"])
                        result, evaluated = replay_session(
                            session,
                            cfg,
                            arm="MODEL:C-MT",
                            controls=default_controls(tau),
                            model_fn=cached,
                            stats=stats,
                            feature_n=manifest["N"],
                            gate=gate,
                            validate_records=name == "none" and tau == TAUS[0],
                        )
                        point = point_row(
                            evaluated,
                            {
                                "arm": "C-MT",
                                "gate": name,
                                "tti_commit_s": tau,
                                "family": manifest["family"],
                                "fold": manifest["fold"],
                                "seed": manifest["seed"],
                            },
                        )
                        point["gate_decisions"] = dict(gate.decisions)
                        if name == "none":
                            reference[tau] = point
                        base = reference[tau]
                        point["delta_vs_none"] = {k: point[k] - base[k] for k in ("matched", "fp", "fn")}
                        curves.append(point)
                        if name in ("none", "intensity-head"):
                            scored = commit_time_intensity(result, evaluated, session, registry, b_cache[sid])
                            intensity.append(
                                {
                                    "source_setting": settings.intensity_source,
                                    "tau": tau,
                                    "family": manifest["family"],
                                    "fold": manifest["fold"],
                                    "seed": manifest["seed"],
                                    **{k: v for k, v in scored.items() if k != "rows"},
                                }
                            )
            print(f"[{cell['variant']}] {manifest['family']} fold={manifest['fold']} seed={manifest['seed']}")
        write_json(run.dir / "curves.json", curves)
        write_json(run.dir / "intensity.json", intensity)
        write_json(run.dir / "baseline-b.json", b_points)
        summary = summarize(curves, intensity, b_points)
        write_json(run.dir / "summary.json", summary)
        plot_lead_fp(
            [{**p, "settings": {"arm": p["settings"]["gate"], "K": p["settings"]["family"]}} for p in curves],
            run.dir / "lead-vs-fp-by-gate.png",
            title="SYNTHETIC development: C-MT consistency gates",
        )
        for path in sorted(run.dir.iterdir()):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            {"points": len(curves), "intensity_rows": len(intensity), "participant_claim": False},
            notes="SYNTHETIC development diagnostics; no gate or intensity source is selected here.",
        )
        print(run.dir)


def _mean(values):
    values = [v for v in values if v is not None]
    return float(np.mean(values)) if values else None


def summarize(curves, intensity, b_points):
    out = {"gates": {}, "intensity": {}, "baseline_b": {}}
    for family in sorted({p["settings"]["family"] for p in curves}):
        for gate in dict.fromkeys(p["settings"]["gate"] for p in curves):
            for tau in TAUS:
                group = [
                    p
                    for p in curves
                    if p["settings"]["family"] == family
                    and p["settings"]["gate"] == gate
                    and p["settings"]["tti_commit_s"] == tau
                ]
                if not group:
                    continue
                decisions = {}
                for p in group:
                    for k, v in p["gate_decisions"].items():
                        decisions[k] = decisions.get(k, 0) + v
                out["gates"].setdefault(family, {}).setdefault(gate, {})[str(tau)] = {
                    "cells": len(group),
                    "median_lead_s": _mean([p["median_lead_s"] for p in group]),
                    "fp_per_min": _mean([p["fp_per_min"] for p in group]),
                    "fn_rate": _mean([p["fn_rate"] for p in group]),
                    "timing_mae_s": _mean([p["timing_mae_s"] for p in group]),
                    "zone_accuracy": _mean([p["zone_accuracy"] for p in group]),
                    "delta_fp": _mean([p["delta_vs_none"]["fp"] for p in group]),
                    "delta_fn": _mean([p["delta_vs_none"]["fn"] for p in group]),
                    "gate_decisions": decisions,
                }
            picks = [
                dev_selection(
                    [
                        p
                        for p in curves
                        if p["settings"]["gate"] == gate
                        and p["settings"]["family"] == family
                        and p["settings"]["fold"] == f
                        and p["settings"]["seed"] == s
                    ]
                )
                for f, s in {(p["settings"]["fold"], p["settings"]["seed"]) for p in curves}
            ]
            out["gates"][family][gate]["dev_selection"] = {
                "feasible_fraction": _mean([float(x["feasible"]) for x in picks]),
                "median_lead_s": _mean([x["median_lead_s"] for x in picks]),
            }
        for setting in ("geometry", "head"):
            for tau in TAUS:
                group = [
                    r
                    for r in intensity
                    if r["family"] == family and r["source_setting"] == setting and r["tau"] == tau
                ]
                if not group:
                    continue
                out["intensity"].setdefault(family, {}).setdefault(setting, {})[str(tau)] = {
                    source: {
                        metric: _mean([r[source][metric] for r in group])
                        for metric in ("n", "mae", "pearson_r", "spearman_rho", "coverage")
                    }
                    for source in (
                        "geometry_inward",
                        "head",
                        "baseline_b_inward_same_frame",
                        "committed_value",
                    )
                }
    for tau in TAUS:
        group = [p for p in b_points if p["settings"]["tti_commit_s"] == tau]
        out["baseline_b"][str(tau)] = {
            k: _mean([p[k] for p in group])
            for k in ("median_lead_s", "fp_per_min", "fn_rate", "intensity_mae", "intensity_pearson_r")
        }
        out["baseline_b"][str(tau)]["intensity_definition"] = "Phase 04 speed magnitude (committed value)"
    return out


if __name__ == "__main__":
    main()
