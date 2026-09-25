"""Phase 11 orchestration: MT train/export, cached-prediction replays, head-vs-geometry comparisons.

Composes library code only; geometry, commit, matching and metrics are the unchanged Phase
04/05/09 implementations. Development constants below are SYNTHETIC selection aids, never the
owner FP budget (ADR-0025) or a participant operating point.
"""

import json
import math
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
from _p10 import write_json

from spacedrums.commit import CommitSettings
from spacedrums.contracts import TrajectoryAux, TrajectoryPrediction
from spacedrums.contracts.schema import validate
from spacedrums.eval.replay import DelayPolicy, replay
from spacedrums.eval.report import evaluate_session, write_result
from spacedrums.eval.selection import select_point
from spacedrums.eval.temporal import temporal_candidate
from spacedrums.geometry import GeometryEngine, ZoneRegistry
from spacedrums.models.temporal.data import sha
from spacedrums.models.temporal.export import export_model, latency, load_mt_model
from spacedrums.models.temporal.mt_train import (
    agreement,
    mt_predictions,
    task_metrics,
    train_mt_fold,
    tti_strata,
)
from spacedrums.prediction import RuleSettings

# SYNTHETIC development constants (declared in every plan.json); not owner/participant values.
# The FP bound was set after a three-cell calibration smoke run on this fixture (lowest trained
# points ~5-25 FP/min) so that the development pick is not empty; it says nothing about playability.
DEV_BUDGET = {"fp_budget": 30.0, "fn_ceiling": 0.6}
TAUS = (0.02, 0.05, 0.10)
W_S = 0.05
V_MIN = 0.15


def assert_close_nested(a, b, *, atol=1e-6, rtol=1e-5):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a:
            assert_close_nested(a[key], b[key], atol=atol, rtol=rtol)
    elif isinstance(a, list):
        assert len(a) == len(b)
        for x, y in zip(a, b, strict=True):
            assert_close_nested(x, y, atol=atol, rtol=rtol)
    elif isinstance(a, bool) or a is None or isinstance(a, str):
        assert a == b
    else:
        np.testing.assert_allclose(a, b, atol=atol, rtol=rtol)


def train_and_export_mt(fold_dir, output, config, training, loss, *, context, aux_horizon_s, calls=60):
    model, manifest, val = train_mt_fold(
        fold_dir, output, config, training, loss, provenance=context, aux_horizon_s=aux_horizon_s
    )
    parity = export_model(model, output, val)
    exported, manifest = load_mt_model(output)
    scaling = manifest["target_scaling"]
    eager = task_metrics(config, scaling, mt_predictions(model, val), val)
    reloaded = task_metrics(config, scaling, mt_predictions(exported, val), val)
    assert_close_nested(eager, reloaded)
    output = Path(output)
    write_json(output / "validation.json", reloaded)
    write_json(
        output / "reproduction.json",
        {"passed": True, "scope": "same environment export reload", "validated": False, "parity": parity},
    )
    benchmark = latency(exported, val, family=config.family, calls=calls, warmup=10, threads=training.threads)
    benchmark.update(
        evidence="DEVELOPMENT CPU COMPUTE on " + manifest["source_kind"],
        hardware=context.get("hardware"),
        measured_at=datetime.now().astimezone().isoformat(),
        git_sha=context["git_sha"],
        git_dirty=context["git_dirty"],
    )
    write_json(output / "latency.json", benchmark)
    manifest["latency_report_id"] = sha(output / "latency.json")
    write_json(output / "manifest.json", manifest)
    return exported, manifest, val, reloaded


class CachedPredictions:
    """Replays of one session under different commit/gate settings reuse the model outputs.

    Outputs depend only on the causal window, so they are keyed by (hand, frame, t_capture)
    and every cache hit re-checks that the offered window is identical.
    """

    def __init__(self, model_fn):
        self.model_fn, self.cache = model_fn, {}

    def __call__(self, track, history, window):
        key = (str(track.hand_id), track.frame_id, track.t_capture)
        if key in self.cache:
            stored, output = self.cache[key]
            if (stored is None) != (window is None) or (
                window is not None
                and not all(np.array_equal(a, b) for a, b in zip(stored, window, strict=True))
            ):
                raise ValueError("cached replay received a different causal window")
            return output
        output = self.model_fn(track, history, window)
        self.cache[key] = (None if window is None else tuple(np.array(v) for v in window), output)
        return output


def harness_inputs(session):
    labels, segments = session.labels, session.segments
    if session.table.source_kind == "SYNTHETIC":
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
    return labels, segments


def replay_session(
    session,
    cfg,
    *,
    arm,
    controls,
    model_fn=None,
    stats=None,
    feature_n=8,
    gate=None,
    diagnostic=False,
    w_s=W_S,
    delay_s=0.0,
    validate_records=True,
):
    controls = dict(controls)
    speed = controls.pop("v_min")
    commit = replace(CommitSettings.from_config(cfg), **controls)
    model_arm = arm.startswith("MODEL:")
    result = replay(
        session.tracks,
        arm=arm,
        registry=ZoneRegistry.from_config(cfg["zones"]),
        commit_settings=commit,
        v_min=speed,
        session_id=session.table.session_id,
        delay=DelayPolicy("fixed", delay_s) if delay_s else DelayPolicy(),
        rule_settings=RuleSettings.from_config(cfg) if arm == "B" else None,
        model=model_fn,
        feature_schema=session.schema if model_arm else None,
        feature_window_n=feature_n,
        norm_stats=stats if model_arm else None,
        feature_records=session.table.records if model_arm else None,
        candidate_gate=gate,
        diagnostic_direct=diagnostic,
    )
    if validate_records:
        # Every commit, and a deterministic 1-in-25 sample of predictions/candidates (cost).
        for schema, rows, every in (
            ("trajectory-prediction", result.predictions, 25),
            ("strike-candidate", result.candidates, 25),
            ("committed-strike", result.committed, 1),
        ):
            for row in rows[::every]:
                validate(schema, row.to_dict())
    labels, segments = harness_inputs(session)
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
        w_s=w_s,
        delay_s=delay_s,
        diagnostic=result.diagnostic,
        label="direct / no-trajectory (diagnostic)" if result.diagnostic else None,
    )
    return result, evaluated


def point_row(evaluated, settings, *, destination=None):
    pooled = evaluated["pooled"]
    if destination is not None:
        write_result(destination, evaluated)
    return {
        "settings": settings,
        "participant": evaluated["participant"],
        "source_kind": evaluated["source_kind"],
        "diagnostic": evaluated["diagnostic"],
        "median_lead_s": pooled["lead_s"]["median"],
        "fp_per_min": pooled["fp_per_min"],
        "fn_rate": pooled["fn_rate"],
        "timing_mae_s": pooled["te_pred_mae_s"],
        "zone_accuracy": pooled["zone_accuracy"],
        "intensity_mae": pooled["intensity_mae"],
        "intensity_pearson_r": pooled["intensity_pearson_r"],
        "matched": pooled["matched"],
        "fp": pooled["fp"],
        "fn": pooled["fn"],
        "fp_by_segment_type": pooled["fp_by_segment_type"],
        "result_path": None if destination is None else str(destination),
    }


def dev_selection(points):
    """Development-only feasibility pick along one model's curve (DEV_BUDGET, not ADR-0025)."""
    choice = select_point(points, **DEV_BUDGET)
    point = choice["point"]
    return {
        "feasible": choice["feasible"],
        "median_lead_s": point["median_lead_s"] if point and choice["feasible"] else None,
        "fp_per_min": point["fp_per_min"] if point else None,
        "fn_rate": point["fn_rate"] if point else None,
        "settings": point["settings"] if point else None,
        "budget": "SYNTHETIC development constants " + json.dumps(DEV_BUDGET),
    }


def frame_geometry(sample, trajectories, registry, *, k, dt_step, v_min=V_MIN):
    """Geometry on each sample's predicted trajectory: the per-frame trajectory-derived answer."""
    engine = GeometryEngine(registry, v_min=v_min, session_id="p11-frame-geometry")
    rows = []
    for i, meta in enumerate(sample["meta"]):
        anchor = tuple(float(v) for v in sample["anchor"][i])
        positions = np.asarray(trajectories[i], dtype=float) + np.asarray(anchor)
        prediction = TrajectoryPrediction(
            frame_id=meta["frame_id"],
            t_capture=meta["t_i"],
            hand_id=meta["hand_id"],
            anticipator_id="p11-frame-evaluation",
            model_hash=None,
            K=k,
            dt_step=dt_step,
            t_offsets_s=None,
            positions=tuple(map(tuple, positions)),
            velocities=None,
            uncertainty=None,
            uncertainty_kind=None,
            aux=TrajectoryAux(),
            t_inference_done=meta["t_i"],
        )
        candidate = temporal_candidate(
            engine.intersect_prediction(
                prediction, current_position=anchor, source="MODEL", t_candidate=meta["t_i"]
            ),
            registry,
        )
        rows.append(_candidate_fields(candidate))
    return rows


def _candidate_fields(candidate, registry=None):
    if candidate is None:
        return None
    speed = math.hypot(*candidate.crossing_velocity)
    inward = candidate.intensity_proxy
    if registry is not None:
        normal = registry[candidate.zone_id].inward_normal
        inward = max(0.0, sum(v * n for v, n in zip(candidate.crossing_velocity, normal, strict=True)))
    return {
        "zone_id": candidate.zone_id,
        "tti": candidate.tti,
        "impact_position": list(candidate.impact_position),
        "intensity_inward": inward,
        "intensity_speed": speed,
    }


def baseline_b_frames(session, cfg):
    """Baseline B (rule CV/CA extrapolation -> same geometry) candidate per (hand, frame)."""
    registry = ZoneRegistry.from_config(cfg["zones"])
    result, evaluated = replay_session(session, cfg, arm="B", controls=default_controls(0.05))
    frames = {(str(c.hand_id), c.frame_id): _candidate_fields(c, registry) for c in result.candidates}
    return frames, result, evaluated


def default_controls(tau, probability=0.0):
    """Reference commit controls around which Phase 11 varies one knob (candidates)."""
    return {
        "tti_commit_s": tau,
        "p_commit": probability,
        "n_confirm_frames": 0,
        "v_min": V_MIN,
        "refractory_zone_s": 0.10,
    }


def per_task_comparison(config, scaling, outputs, sample, geometry_rows, b_frames):
    """Each head judged against the trajectory-derived answer and Baseline B (Task 11.4)."""
    from spacedrums.models.temporal.heads import decode_heads

    values = decode_heads(config, scaling, outputs, sample["anchor"])
    m, heads = sample["mt"], set(config.heads)
    impact = m["impact_mask"].numpy()
    truth_tti = m["tti"].numpy().astype(float)
    truth_zone = [config.zone_ids[i] if config.zone_ids else None for i in m["zone"].numpy()]
    truth_pos = m["position"].numpy() + sample["anchor"]
    truth_int = m["intensity"].numpy().astype(float)
    keys = [(meta["hand_id"], meta["frame_id"]) for meta in sample["meta"]]
    b_rows = [b_frames.get(key) for key in keys]
    rows = np.flatnonzero(impact)
    geo_rows = [i for i in rows if geometry_rows[i] is not None]
    b_cover = [i for i in rows if b_rows[i] is not None]
    report = {
        "impact_rows": len(rows),
        "coverage": {
            "geometry": len(geo_rows) / len(rows) if len(rows) else None,
            "baseline_b": len(b_cover) / len(rows) if len(rows) else None,
        },
        "note": "geometry/B answer only when their horizon predicts a crossing; compare on covered rows",
    }
    if "tti" in heads:
        report["tti"] = {
            "head_all_rows": _tti_error(values["tti_s"][rows], truth_tti[rows]),
            "head_on_geometry_rows": _tti_error(values["tti_s"][geo_rows], truth_tti[geo_rows]),
            "geometry": _tti_error([geometry_rows[i]["tti"] for i in geo_rows], truth_tti[geo_rows]),
            "head_on_b_rows": _tti_error(values["tti_s"][b_cover], truth_tti[b_cover]),
            "baseline_b": _tti_error([b_rows[i]["tti"] for i in b_cover], truth_tti[b_cover]),
            "strata": [
                {
                    "true_tti_s": [lo, hi],
                    "head": _tti_error(values["tti_s"][s], truth_tti[s]),
                    "geometry": _tti_error(
                        [geometry_rows[i]["tti"] for i in s if geometry_rows[i]],
                        [truth_tti[i] for i in s if geometry_rows[i]],
                    ),
                    "geometry_coverage": sum(geometry_rows[i] is not None for i in s) / len(s)
                    if len(s)
                    else None,
                }
                for lo, hi in tti_strata(config)
                for s in [[i for i in rows if lo < truth_tti[i] <= hi + 1e-9]]
            ],
        }
    if "zone" in heads:
        head_zone = [config.zone_ids[j] for j in values["zone_index"]]
        report["zone"] = {
            "head_all_rows": _accuracy([head_zone[i] for i in rows], [truth_zone[i] for i in rows]),
            "head_on_geometry_rows": _accuracy(
                [head_zone[i] for i in geo_rows], [truth_zone[i] for i in geo_rows]
            ),
            "geometry": _accuracy(
                [geometry_rows[i]["zone_id"] for i in geo_rows], [truth_zone[i] for i in geo_rows]
            ),
            "baseline_b": _accuracy(
                [b_rows[i]["zone_id"] for i in b_cover], [truth_zone[i] for i in b_cover]
            ),
        }
    if "position" in heads:
        report["position"] = {
            "head_all_rows": _position_error(values["impact_pos"][rows], truth_pos[rows]),
            "head_on_geometry_rows": _position_error(values["impact_pos"][geo_rows], truth_pos[geo_rows]),
            "geometry": _position_error(
                [geometry_rows[i]["impact_position"] for i in geo_rows], truth_pos[geo_rows]
            ),
            "baseline_b": _position_error(
                [b_rows[i]["impact_position"] for i in b_cover], truth_pos[b_cover]
            ),
        }
    if "intensity" in heads:
        report["intensity"] = {
            "head_all_rows": agreement(values["intensity"][rows], truth_int[rows]),
            "head_on_geometry_rows": agreement(values["intensity"][geo_rows], truth_int[geo_rows]),
            "geometry_inward": agreement(
                [geometry_rows[i]["intensity_inward"] for i in geo_rows], truth_int[geo_rows]
            ),
            "baseline_b_inward": agreement(
                [b_rows[i]["intensity_inward"] for i in b_cover], truth_int[b_cover]
            ),
            "baseline_b_speed": agreement(
                [b_rows[i]["intensity_speed"] for i in b_cover], truth_int[b_cover]
            ),
        }
    return report


def _tti_error(pred, truth):
    pred, truth = np.asarray(pred, dtype=float), np.asarray(truth, dtype=float)
    if not len(pred):
        return {"n": 0, "mae_s": None, "bias_s": None}
    return {
        "n": len(pred),
        "mae_s": float(np.abs(pred - truth).mean()),
        "bias_s": float((pred - truth).mean()),
    }


def _accuracy(pred, truth):
    return {
        "n": len(pred),
        "accuracy": float(np.mean([a == b for a, b in zip(pred, truth, strict=True)])) if pred else None,
    }


def _position_error(pred, truth):
    pred, truth = np.asarray(pred, dtype=float).reshape(-1, 2), np.asarray(truth, dtype=float).reshape(-1, 2)
    error = np.linalg.norm(pred - truth, axis=1)
    if not len(error):
        return {"n": 0, "mean": None, "median": None, "p90": None}
    return {
        "n": len(error),
        "mean": float(error.mean()),
        "median": float(np.median(error)),
        "p90": float(np.percentile(error, 90)),
    }


def commit_time_intensity(result, evaluated, session, registry, b_frames):
    """Task 11.7: intensity sources scored at the COMMIT of matched C-MT strikes.

    (a) geometry inward crossing speed on the predicted trajectory (the committed candidate),
    (b) the intensity head at the commit frame, (c) Baseline B's extrapolated crossing at the
    same hand/frame and zone. All against the label's intensity_proxy_gt. Proxy, never force.
    """
    strikes = {s.strike_id: s for s in result.committed}
    candidates = {c.candidate_id: c for c in result.candidates}
    predictions = {(str(p.hand_id), p.frame_id): p for p in result.predictions}
    labels = {g["label_id"]: g for g in session.labels}
    rows = []
    for event in evaluated["events"]:
        if event["kind"] != "MATCH":
            continue
        strike = strikes[event["strike_id"]]
        candidate = candidates[strike.candidate_id]
        label = labels[event["label_id"]]
        key = (str(strike.hand_id), candidate.frame_id)
        head = predictions[key].aux.intensity_proxy if key in predictions else None
        b = b_frames.get(key)
        normal = registry[candidate.zone_id].inward_normal
        rows.append(
            {
                "strike_id": strike.strike_id,
                "gt": label["intensity_proxy_gt"],
                "committed": strike.intensity_proxy,
                "geometry_inward": max(
                    0.0, sum(v * n for v, n in zip(candidate.crossing_velocity, normal, strict=True))
                ),
                "head": head,
                "baseline_b_inward": b["intensity_inward"]
                if b and b["zone_id"] == candidate.zone_id
                else None,
            }
        )

    def score(field):
        pairs = [(r[field], r["gt"]) for r in rows if r[field] is not None and r["gt"] is not None]
        result = agreement([p for p, _ in pairs], [g for _, g in pairs])
        return {**result, "coverage": len(pairs) / len(rows) if rows else None}

    return {
        "matched_commits": len(rows),
        "geometry_inward": score("geometry_inward"),
        "head": score("head"),
        "baseline_b_inward_same_frame": score("baseline_b_inward"),
        "committed_value": score("committed"),
        "rows": rows,
    }


def load_grid_run(run_dir, cfg, *, variants=None):
    """Rebuild a grid run's SYNTHETIC fixture and verify it against the recorded fold hashes."""
    from _p11_fixture import kinematic_fixture

    run_dir = Path(run_dir)
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    rows = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if record["status"] != "COMPLETED" or plan["test_access"]:
        raise ValueError("grid run incomplete or not validation-only")
    fixture = plan.get("fixture", {"identities": 5, "seconds": 24.0})
    dataset, cv, sessions = kinematic_fixture(cfg, **fixture)
    for cell in plan["cells"]:
        stats = json.loads((Path(cell["fold_dir"]) / "norm_stats.json").read_text(encoding="utf-8"))
        if stats["dataset_hash"] != dataset["manifest_hash"] or stats["split_hash"] != cv["split_hash"]:
            raise ValueError("rebuilt fixture differs from the grid run's recorded fold provenance")
    selected = [
        (cell, row)
        for cell, row in zip(plan["cells"], rows, strict=True)
        if variants is None or cell["variant"] in variants
    ]
    return plan, selected, {**dataset, "split_hash": cv["split_hash"]}, cv, sessions


def fold_stats(cell, fold, dataset, sessions):
    from spacedrums.features.normalize import NormStats

    return NormStats.read(
        Path(cell["fold_dir"]) / "norm_stats.json",
        fold=fold["fold"],
        dataset_version=dataset["dataset_version"],
        dataset_hash=dataset["manifest_hash"],
        split_hash=dataset["split_hash"],
        schema=sessions[0].schema,
    )
