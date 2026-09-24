"""Compose the unchanged Phase 09 metrics with the temporal MODEL-arm replay."""

import itertools
from dataclasses import replace

from _p10 import write_json

from spacedrums.commit import CommitSettings
from spacedrums.contracts.schema import validate
from spacedrums.eval.replay import DelayPolicy, replay
from spacedrums.eval.report import evaluate_session, write_result
from spacedrums.geometry import ZoneRegistry
from spacedrums.models.temporal.adapter import TemporalAnticipator


def control_grid(auxiliary=False):
    # Candidate one-knob perturbations around each tau avoid a needlessly huge Cartesian sweep.
    for tau in (0.02, 0.05, 0.10):
        for probability in (0.3, 0.7) if auxiliary else (0.0,):
            for confirm, speed, refractory in (
                (0, 0.15, 0.10),
                (2, 0.15, 0.10),
                (0, 0.30, 0.10),
                (0, 0.15, 0.20),
            ):
                yield {
                    "tti_commit_s": tau,
                    "p_commit": probability,
                    "n_confirm_frames": confirm,
                    "v_min": speed,
                    "refractory_zone_s": refractory,
                }


def replay_one(session, cfg, *, model, manifest, stats, settings, w_s, delay_s=0.0):
    controls = dict(settings)
    speed = controls.pop("v_min")
    commit = replace(CommitSettings.from_config(cfg), **controls)
    result = replay(
        session.tracks,
        arm="MODEL:C-" + manifest["family"].upper(),
        registry=ZoneRegistry.from_config(cfg["zones"]),
        commit_settings=commit,
        v_min=speed,
        session_id=session.table.session_id,
        delay=DelayPolicy("fixed", delay_s) if delay_s else DelayPolicy(),
        model=TemporalAnticipator(model, manifest),
        feature_schema=session.schema,
        feature_window_n=manifest["N"],
        norm_stats=stats,
        feature_records=session.table.records,
    )
    synthetic = session.table.source_kind == "SYNTHETIC"
    labels, segments = session.labels, session.segments
    if synthetic:
        labels = [
            {
                **g,
                "qc_status": g.get("qc_status", "PENDING_REVIEW"),
                "review": g.get("review", {"reviewed": False}),
                "segment_type": "SYNTHETIC_UNIT",
                "t_start": g.get("t_start"),
                "t_end": g.get("t_end"),
            }
            for g in labels
        ]
        segments = [
            {**s, "type": s.get("type", "SYNTHETIC_UNIT"), "hands": ["LEFT", "RIGHT"]} for s in segments
        ]
    for schema, rows in (
        ("trajectory-prediction", result.predictions),
        ("strike-candidate", result.candidates),
        ("committed-strike", result.committed),
    ):
        for row in rows:
            validate(schema, row.to_dict())
    evaluated = evaluate_session(
        result.strike_rows(session.table.session_id, session.table.participant),
        labels,
        segments,
        w_s=w_s,
        include_unreviewed_selftest=session.table.source_kind != "PARTICIPANT",
    )
    evaluated.update(
        source_kind=session.table.source_kind,
        participant=session.table.participant,
        session_id=session.table.session_id,
        model_hash=manifest["export_hash"],
        settings=settings,
        w_s=w_s,
        delay_s=delay_s,
    )
    return result, evaluated


def evaluate_grid(session, cfg, *, model, manifest, stats, output, w_s=0.05, delay_s=0.0, controls=None):
    rows = []
    controls = list(controls) if controls is not None else list(control_grid(manifest["config"]["auxiliary"]))
    for index, settings in enumerate(controls):
        result, evaluated = replay_one(
            session,
            cfg,
            model=model,
            manifest=manifest,
            stats=stats,
            settings=settings,
            w_s=w_s,
            delay_s=delay_s,
        )
        destination = output / f"point-{index:03d}"
        write_result(destination, evaluated)
        if index == 0:
            write_json(destination / "predictions.json", [p.to_dict() for p in result.predictions])
            write_json(destination / "candidates.json", [p.to_dict() for p in result.candidates])
            write_json(destination / "committed.json", [p.to_dict() for p in result.committed])
            write_json(destination / "decisions.json", result.decisions)
        pooled = evaluated["pooled"]
        rows.append(
            {
                "settings": {
                    **settings,
                    "arm": "C-" + manifest["family"].upper(),
                    "K": manifest["K"],
                    "N": manifest["N"],
                    "seed": manifest["seed"],
                    "auxiliary": manifest["config"]["auxiliary"],
                },
                "participant": session.table.participant,
                "source_kind": session.table.source_kind,
                "median_lead_s": pooled["lead_s"]["median"],
                "fp_per_min": pooled["fp_per_min"],
                "fn_rate": pooled["fn_rate"],
                "timing_mae_s": pooled["te_pred_mae_s"],
                "metrics": pooled,
                "result_path": str(destination),
            }
        )
    return rows


def summarize_comparison(rows):
    # All settings remain separate; never choose the largest observed test/seed lead.
    groups = {}
    for row in rows:
        s = row["settings"]
        key = tuple((k, s[k]) for k in sorted(s) if k != "seed")
        groups.setdefault(key, []).append(row)
    summary = []
    from _p10 import bootstrap_participants

    for settings, values in groups.items():
        participant_rows = {}
        for participant, group in itertools.groupby(
            sorted(values, key=lambda r: r["participant"]), key=lambda r: r["participant"]
        ):
            participant_rows[participant] = list(group)
        metrics = {}
        for field in ("median_lead_s", "fp_per_min", "fn_rate", "timing_mae_s", "latency_p95_ms"):
            per_participant = {}
            for participant, data in participant_rows.items():
                observed = [r[field] for r in data if r.get(field) is not None]
                per_participant[participant] = sum(observed) / len(observed) if observed else None
            metrics[field] = bootstrap_participants(per_participant)
        summary.append(
            {
                "settings": dict(settings),
                "participant_CIs": metrics,
                "interpretation": "SYNTHETIC fixture grouping CIs only"
                if values[0]["source_kind"] == "SYNTHETIC"
                else "participant bootstrap; seeds averaged within participant",
            }
        )
    return summary
