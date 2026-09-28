"""Phase 19 SYNTHETIC/DEV orchestration using the unchanged feature/model/evaluation code."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from _p10 import write_json
from _p11 import harness_inputs, replay_session
from _p11_fixture import kinematic_fixture
from _p18 import Arm as HarnessArm

from spacedrums.ablation.config import model_config, validate_plan
from spacedrums.ablation.statistics import compare, seed_band
from spacedrums.ablation.transforms import MaskedAdapter, mask_normalized, mask_spec, model_variant
from spacedrums.config import config_hash
from spacedrums.eval.selection import select_point
from spacedrums.features.batch import build_features
from spacedrums.features.normalize import fit_norm
from spacedrums.features.windows import WindowParams, build_windows, write_samples
from spacedrums.geometry import ZoneRegistry
from spacedrums.live_eval.causality import causal_check
from spacedrums.live_eval.offline import participant_metrics, pooled_metrics, trajectory_errors
from spacedrums.models.temporal.adapter import TemporalAnticipator
from spacedrums.models.temporal.config import MultiTaskConfig
from spacedrums.models.temporal.consistency import AuxGate, AuxHeadSettings
from spacedrums.models.temporal.export import export_model, load_model, load_mt_model
from spacedrums.models.temporal.mt_adapter import DirectHeadDiagnostic, MultiTaskAnticipator
from spacedrums.models.temporal.mt_train import MultiTaskLossConfig, train_mt_fold
from spacedrums.models.temporal.train import TrainConfig, train_fold
from spacedrums.prediction import RuleSettings

METRICS = ("lead_median_s", "fp_per_min", "fn_rate", "te_pred_mae_s", "zone_accuracy", "ade", "fde")


def export_cv(manifest, cv, sessions, fold, params, destination, spec=None):
    """Reuse Phase 08 window/normalization functions, exporting only CV train and validation.

    Reserved test sessions are not accepted as inputs. Full roster leakage is checked before
    fitting; fit_norm receives the CV-only roster and the original frozen dataset/split hashes.
    """
    reserved = set(cv["test_participants"])
    if any(s.table.participant in reserved for s in sessions):
        raise ValueError("reserved test session supplied to CV exporter")
    expected = set(fold["train_participants"]) | set(fold["val_participants"])
    if expected & reserved or set(fold["train_participants"]) & set(fold["val_participants"]):
        raise ValueError("participant split leakage")
    if {s.table.participant for s in sessions} != expected:
        raise ValueError("missing/unassigned CV participant")
    schema = sessions[0].schema
    if any(s.schema.fingerprint != schema.fingerprint for s in sessions):
        raise ValueError("mixed feature schema")
    stats = fit_norm(
        [s.table for s in sessions],
        schema,
        fold,
        [],
        dataset_version=manifest["dataset_version"],
        dataset_hash=manifest["manifest_hash"],
        split_hash=cv["split_hash"],
    )
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    stats.write(destination / "norm_stats.json")
    report = {
        "fold": fold["fold"],
        "evidence": "SYNTHETIC/DEV" if cv["source_kind"] == "SYNTHETIC" else "PARTICIPANT",
        "parts": {"test": {"participants": sorted(reserved), "status": "NOT OPENED / NOT EXPORTED"}},
    }
    for part in ("train", "val"):
        ids = fold[f"{part}_participants"]
        chosen = [s for s in sessions if s.table.participant in ids]
        if {s.table.session_id for s in chosen} != set(fold[f"{part}_sessions"]):
            raise ValueError("CV session assignment mismatch")
        samples, counts = [], []
        for session in chosen:
            rows, count = build_windows(
                session.tracks,
                session.table.records,
                session.labels,
                session.segments,
                schema,
                params,
                participant=session.table.participant,
                session_id=session.table.session_id,
                source_kind=session.table.source_kind,
                fold=fold["fold"],
                stats=stats,
            )
            rows = [r for r in rows if r["anticipation_eligible"]]
            if spec:
                for row in rows:
                    row["X"], row["M"] = mask_normalized(row["X"], row["M"], spec)
            samples.extend(rows)
            counts.append({"session_id": session.table.session_id, **count})
        write_samples(destination / f"samples.{part}.npz", samples, schema, params)
        report["parts"][part] = {"participants": ids, "sessions": counts}
    write_json(destination / "report.json", report)
    write_json(destination / "ablation-mask.json", {"evidence": report["evidence"], "mask": spec})
    return stats


def evaluate(sessions, cfg, *, arm, controls, adapter, stats, n, gate, heads, diagnostic, w_s, delay_s):
    """Same harness and participant aggregation as Phase 18; labels only after replay."""
    rows, trajectories = [], []
    for session in sessions:
        if adapter is not None:
            adapter.reset()
        replayed, evaluated = replay_session(
            session,
            cfg,
            arm=arm,
            controls=controls,
            model_fn=adapter,
            stats=stats,
            feature_n=n,
            gate=AuxGate(gate, heads) if arm == "MODEL:C-MT" and not diagnostic else None,
            diagnostic=diagnostic,
            w_s=w_s,
            delay_s=delay_s,
        )
        labels, _ = harness_inputs(session)
        rows.append(
            {
                "participant": session.table.participant,
                "session_id": session.table.session_id,
                "evaluation": evaluated,
                "labels": labels,
                "strikes": replayed.strike_rows(session.table.session_id, session.table.participant),
            }
        )
        trajectories.append(
            (session.table.participant, trajectory_errors(replayed.predictions, session.tracks))
        )
    participants = participant_metrics(rows)
    for pid, metric in participants.items():
        traj = [t for p, t in trajectories if p == pid]
        for name, count in (("ade", "valid_points"), ("fde", "valid_sequences")):
            pairs = [(t[name], t[count]) for t in traj if t[name] is not None and t[count]]
            metric[name] = sum(v * n for v, n in pairs) / sum(n for _, n in pairs) if pairs else None
        metric["latency_p95_ms"] = None
    return {
        "per_participant": participants,
        "pooled": pooled_metrics(rows),
        "events": [r["evaluation"]["events"] for r in rows],
    }


def run_synthetic(plan, cfg, destination, context):
    """Only generated fixture inputs. No arbitrary data/model/session paths are accepted."""
    plan = validate_plan(plan)
    if plan["evidence"] != "SYNTHETIC/DEV":
        raise ValueError("synthetic runner refuses non-SYNTHETIC/DEV plan")
    destination = Path(destination)
    manifest, cv, all_sessions = kinematic_fixture(cfg, **plan["fixture"])
    sessions = [s for s in all_sessions if s.table.participant not in cv["test_participants"]]
    if any(s.table.source_kind != "SYNTHETIC" for s in sessions):
        raise ValueError("synthetic runner received participant data")
    # Only the generated fixture is present, but even its reserved grouping is kept out of export.
    schema = sessions[0].schema
    reference = model_config(plan)
    base = reference.base if isinstance(reference, MultiTaskConfig) else reference
    if base.features != schema.dimension:
        raise ValueError("reference feature dimension mismatch")
    if set(plan["folds"]) - {f["fold"] for f in cv["folds"]}:
        raise ValueError("requested fold not in fixture")
    variants = [{"ablation_id": "REF", "changes": {}}, *plan["variants"]]
    cells, statuses = [], {}
    for variant in variants:
        aid = variant["ablation_id"]
        if aid in ("AB-FPS", "AB-TIP"):
            statuses[aid] = (
                "PENDING raw reference recordings; retracking/frame-drop machinery tested separately"
            )
            continue
        model, gate = model_variant(reference, variant, AuxHeadSettings(**plan["reference"]["gate"]))
        b = model.base if isinstance(model, MultiTaskConfig) else model
        params = WindowParams(
            b.n,
            b.k,
            b.k * b.dt_step,
            model.h_max_s if isinstance(model, MultiTaskConfig) else max(0.3, b.k * b.dt_step),
            stride=plan["stride"],
            g_win=0,
        )
        spec = (
            mask_spec(schema, aid)
            if aid in ("AB-VEL", "AB-ACC", "AB-AXIS", "AB-HAND", "AB-ZONE", "AB-CONF")
            else None
        )
        statuses[aid] = "SYNTHETIC/DEV ONLY — pipeline exercised"
        for fold in [f for f in cv["folds"] if f["fold"] in plan["folds"]]:
            root = destination / aid / f"fold-{fold['fold']}"
            stats = export_cv(manifest, cv, sessions, fold, params, root / "features", spec)
            val_sessions = [s for s in sessions if s.table.participant in fold["val_participants"]]
            for seed in plan["seeds"]:
                cell_dir = root / f"seed-{seed}"
                train_cfg = TrainConfig(
                    **{
                        **plan["reference"]["training"],
                        "seed": seed,
                        "lambda_aux": 0.0
                        if aid == "AB-AUX"
                        else plan["reference"]["training"].get("lambda_aux", 0.0),
                    }
                )
                adapter, diagnostic, arm, trained_manifest = None, aid == "AB-NOTRAJ", "A", None
                if aid not in ("AB-REACT", "AB-RULE"):
                    if isinstance(model, MultiTaskConfig):
                        trained, trained_manifest, val = train_mt_fold(
                            root / "features",
                            cell_dir,
                            model,
                            train_cfg,
                            MultiTaskLossConfig(),
                            provenance={**context, "evidence": "SYNTHETIC/DEV"},
                            aux_horizon_s=params.h,
                        )
                        export_model(trained, cell_dir, val)
                        trained, trained_manifest = load_mt_model(cell_dir)
                        adapter = (
                            DirectHeadDiagnostic(trained, trained_manifest, diagnostic=True)
                            if diagnostic
                            else MultiTaskAnticipator(trained, trained_manifest)
                        )
                        arm = "MODEL:C-MT"
                    else:
                        trained, trained_manifest, val = train_fold(
                            root / "features",
                            cell_dir,
                            model,
                            train_cfg,
                            provenance={**context, "evidence": "SYNTHETIC/DEV"},
                            aux_horizon_s=params.h,
                        )
                        export_model(trained, cell_dir, val)
                        trained, trained_manifest = load_model(cell_dir)
                        adapter, arm = (
                            TemporalAnticipator(trained, trained_manifest),
                            "MODEL:C-" + b.family.upper(),
                        )
                    if spec:
                        adapter = MaskedAdapter(adapter, schema, spec)
                else:
                    arm = "A" if aid == "AB-REACT" else "B"
                    cell_dir.mkdir(parents=True, exist_ok=False)
                outputs, points, causal_checks = [], [], []
                controls_grid = plan["reference"]["controls"]
                if aid == "AB-REACT":
                    controls_grid = [plan["baseline_controls"]]
                for controls in controls_grid:
                    runner = HarnessArm(
                        {"arm_id": aid, "replay_arm": arm, "controls": controls},
                        cfg,
                        ZoneRegistry.from_config(cfg["zones"]),
                        rule=RuleSettings.from_config(cfg) if arm == "B" else None,
                        model_fn=adapter,
                        stats=stats,
                        window_n=b.n,
                        gate_factory=(lambda gate=gate, model=model: AuxGate(gate, model.heads))
                        if arm == "MODEL:C-MT" and not diagnostic
                        else None,
                    )
                    if not diagnostic:
                        checked_session = val_sessions[0]

                        def run_checked(
                            tracks, runner=runner, checked_session=checked_session, adapter=adapter
                        ):
                            return runner.run(
                                tracks,
                                session_id=checked_session.table.session_id,
                                schema=schema,
                                delay_s=plan["delay_s"],
                                feature_records=build_features(list(tracks), schema) if adapter else None,
                            )

                        causal = causal_check(
                            run_checked,
                            checked_session.tracks,
                            donor=sessions[-1].tracks,
                            tolerance=1e-6,
                            max_cuts=2,
                        )
                    else:
                        # The diagnostic route uses the identical harness with its explicit safety flag.
                        def run_checked(
                            tracks,
                            original=val_sessions[0],
                            adapter=adapter,
                            arm=arm,
                            controls=controls,
                            stats=stats,
                            n=b.n,
                        ):
                            session = replace(
                                original,
                                tracks=list(tracks),
                                table=replace(original.table, records=build_features(list(tracks), schema)),
                            )
                            adapter.reset()
                            return replay_session(
                                session,
                                cfg,
                                arm=arm,
                                controls=controls,
                                model_fn=adapter,
                                stats=stats,
                                feature_n=n,
                                diagnostic=True,
                                w_s=plan["w_s"],
                                delay_s=plan["delay_s"],
                                validate_records=False,
                            )[0]

                        causal = causal_check(
                            run_checked,
                            val_sessions[0].tracks,
                            donor=sessions[-1].tracks,
                            tolerance=1e-6,
                            max_cuts=2,
                        )
                    if not causal["passed"]:
                        raise AssertionError("ablation TEST-CAUSAL-1 failed before metric collection")
                    causal_checks.append({"controls": controls, **causal})
                    out = evaluate(
                        val_sessions,
                        cfg,
                        arm=arm,
                        controls=controls,
                        adapter=adapter,
                        stats=stats,
                        n=b.n,
                        gate=gate,
                        heads=getattr(model, "heads", ()),
                        diagnostic=diagnostic,
                        w_s=plan["w_s"],
                        delay_s=plan["delay_s"],
                    )
                    outputs.append(out)
                    values = [
                        m["lead_median_s"]
                        for m in out["per_participant"].values()
                        if m["lead_median_s"] is not None
                    ]
                    points.append(
                        {
                            "settings": controls,
                            "median_lead_s": float(np.mean(values)) if values else None,
                            "fp_per_min": out["pooled"]["fp_per_min"],
                            "fn_rate": out["pooled"]["fn_rate"],
                        }
                    )
                selection = select_point(
                    points,
                    fp_budget=plan["dev_budget"]["fp_budget_per_min"],
                    fn_ceiling=plan["dev_budget"]["fn_ceiling"],
                )
                picked = points.index(selection["point"]) if selection["point"] else 0
                out = outputs[picked]
                cell = {
                    "evidence": "SYNTHETIC/DEV",
                    "ablation_id": aid,
                    "fold": fold["fold"],
                    "seed": seed,
                    "selection": selection,
                    "metrics": out["per_participant"],
                    "pooled": out["pooled"],
                    "diagnostic": diagnostic,
                    "latency": "PENDING: not timed in deterministic test",
                    "event_digest": config_hash(out["events"]),
                    "mask": spec,
                    "causality": {"passed": all(c["passed"] for c in causal_checks), "checks": causal_checks},
                }
                write_json(cell_dir / "evaluation.json", cell)
                write_json(
                    cell_dir / "binding.json",
                    {
                        "evidence": "SYNTHETIC/DEV",
                        "plan_sha256": config_hash(plan),
                        "variant": variant,
                        "model_config": model.to_dict(),
                        "gate": gate.to_dict(),
                        "model": trained_manifest,
                        "mask": spec,
                        "dataset": manifest,
                        "split": cv,
                    },
                )
                cells.append(cell)
                print(f"SYNTHETIC/DEV {aid} fold={fold['fold']} seed={seed}", flush=True)

    def rows(aid, metric):
        return [
            {
                "participant": p,
                "fold": c["fold"],
                "seed": c["seed"],
                "value": m[metric] if metric != "lead_median_s" or c["selection"]["feasible"] else None,
            }
            for c in cells
            if c["ablation_id"] == aid
            for p, m in c["metrics"].items()
        ]

    band = seed_band(rows("REF", "lead_median_s"))
    comparisons = {
        aid: {
            m: compare(
                rows("REF", m),
                rows(aid, m),
                band=band if m == "lead_median_s" else None,
                primary=m == "lead_median_s",
            )
            for m in METRICS
        }
        for aid in statuses
        if aid != "REF" and rows(aid, "lead_median_s")
    }
    return {
        "schema_version": "1.0",
        "evidence": "SYNTHETIC/DEV",
        "experimental_execution": False,
        "plan_sha256": config_hash(plan),
        "dataset": manifest,
        "split": cv,
        "cells": cells,
        "variant_status": statuses,
        "comparisons": comparisons,
        "operating_rule": "SYNTHETIC/DEV FP/FN-only machinery check; participant budgets remain PENDING",
    }
