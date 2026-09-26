"""Phase 12 orchestration: declared extension variants, train/export, cached replays with the
crossing-probability gate, offline calibration and the E5(b)/E4(b) evaluation-only rules.

Composes library code only; geometry, commit, matching and metrics are the unchanged Phase
04/05/09 implementations (the replay only gained the C-TT arm label). Every constant below is the
one declared in docs/experiments/phase-12-prereg.md before any run; development budgets are the
Phase 11 SYNTHETIC constants, never owner values.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
from _p10 import train_and_export, write_json
from _p11 import DEV_BUDGET, V_MIN, W_S, CachedPredictions, default_controls, point_row, replay_session

from spacedrums.eval.probabilistic import AnchorRecorder, calibration
from spacedrums.eval.selection import select_point
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.probabilistic import CrossingProbabilityGate, common_draws, intersect_prob
from spacedrums.models.temporal import TemporalConfig
from spacedrums.models.temporal.data import load_fold, sha
from spacedrums.models.temporal.export import export_model, latency, load_model
from spacedrums.models.temporal.ext import ExtensionConfig, load_extension_model
from spacedrums.models.temporal.ext.adapter import (
    EnsembleAnticipator,
    ExtensionAnticipator,
    decode_extension,
    extension_config,
)
from spacedrums.models.temporal.ext.decoding import bounded_acceleration, fit_acceleration_bound
from spacedrums.models.temporal.ext.long_horizon import select_grid
from spacedrums.models.temporal.ext.train import train_extension_fold, training_targets, validation_report
from spacedrums.models.temporal.ext.uncertainty import member_rows
from spacedrums.models.temporal.train import TrainConfig, diagnostics, predictions

ROOT = Path(__file__).resolve().parents[1]
NOT_CODEX = {
    "codex_model": "NOT CODEX: Claude Opus 5.5 (claude-opus-5-5) via Claude Code",
    "codex_reasoning_effort": "UNAVAILABLE to the agent; not asserted",
}
PREDECLARATION = ROOT / "experiments/phase-12/predeclaration/predeclaration.json"
DECLARED_DOCS = ("docs/experiments/phase-12-entry-decision.md", "docs/experiments/phase-12-prereg.md")

# Declared development settings (entry decision; identical to the Phase 11 development grid).
DEV = {"n": 8, "dt_step": 1 / 30, "hidden": 16, "epochs": 8, "identities": 5, "seconds": 24.0}
SEEDS, FOLDS, FAMILIES = (10, 11, 12), (0, 1, 2, 3), ("gru", "tcn")
TAUS = (0.02, 0.05, 0.10, 0.15, 0.20)
PROBABILITIES = (0.0, 0.3, 0.5, 0.7)
CROSSING = {"samples": 32, "seed": 1212, "correlation": "shared"}
SMOOTHING_QUANTILE = 0.99
F_CPU = 3.0
BAND_SIGMAS = 2.0

# Trained variants: ExtensionConfig keyword arguments beyond the development settings.
VARIANTS = {
    "ref": {"k": 4},
    "e1-k6": {"k": 6},
    "e1-k8": {"k": 8},
    "e1-2rate": {"k": 6, "steps": (1, 2, 3, 4, 6, 8)},
    "e2-vel": {"k": 4, "representation": "velocity"},
    "e2-poly": {"k": 4, "representation": "polynomial", "degree": 3},
    "e2-mix2": {"k": 4, "representation": "mixture", "modes": 2, "wta_epsilon": 0.05, "mode_weight": 0.5},
    "e3-tt": {"k": 4, "family": "tt", "layers": 2, "attention_heads": 2, "feedforward": 32},
    "e4-gauss": {"k": 4, "uncertainty": "gaussian"},
    "e5-resb": {"k": 4, "residual": "cv"},
}
# Evaluation-only rules over trained cells (no new training).
RULES = {
    "e2-mix2-agg": {"source": "e2-mix2", "gate": True},
    "e4-ens3": {"source": "ref", "gate": True, "ensemble": True},
    "e5-smooth": {"source": "ref", "smoothing": SMOOTHING_QUANTILE},
}
EXTENSIONS = {
    "ref": {"task": "12.2", "variants": ("ref",), "rules": ()},
    "e1": {"task": "12.3", "variants": ("e1-k6", "e1-k8", "e1-2rate"), "rules": ()},
    "e2": {"task": "12.4", "variants": ("e2-vel", "e2-poly", "e2-mix2"), "rules": ("e2-mix2-agg",)},
    "e3": {"task": "12.5", "variants": ("e3-tt",), "rules": ()},
    "e4": {"task": "12.6", "variants": ("e4-gauss",), "rules": ("e4-ens3",)},
    "e5": {"task": "12.7", "variants": ("e5-resb",), "rules": ("e5-smooth",)},
}
PROBABILISTIC = ("e4-gauss", "e2-mix2-agg", "e4-ens3")
# EXPLORATORY variants (not pre-declared; never in the go/no-go table) that use the crossing gate.
EXPLORATORY_PROBABILISTIC = ("x-e4-posthoc",)


def predeclaration_record():
    """Hashes of the archived pre-declaration and of the current documents (must still match)."""
    archived = json.loads(PREDECLARATION.read_text(encoding="utf-8"))
    current = {doc: sha(ROOT / doc) for doc in DECLARED_DOCS}
    return {
        "archive": str(PREDECLARATION.relative_to(ROOT)),
        "archive_hash": sha(PREDECLARATION),
        "archived_at": archived["archived_at"],
        "archived_files": archived["files"],
        "current_files": current,
        "unchanged_since_archive": current == archived["files"],
    }


def ext_config(variant, family, *, features, residual_features=()):
    kwargs = {"family": family, "features": features, "n": DEV["n"], "dt_step": DEV["dt_step"]}
    kwargs.update(hidden=DEV["hidden"], **VARIANTS[variant])
    if VARIANTS[variant].get("residual"):
        kwargs["residual_features"] = tuple(residual_features)
    return ExtensionConfig(**kwargs)


def arm_for(family):
    return {"gru": "MODEL:C-GRU", "tcn": "MODEL:C-TCN", "tt": "MODEL:C-TT"}[family]


def train_and_export_ext(fold_dir, output, config, training, *, context, variant, calls=60):
    model, manifest, _, val = train_extension_fold(
        fold_dir, output, config, training, provenance=context, variant=variant
    )
    parity = export_model(model, output, val)
    exported, manifest = load_extension_model(output)
    eager_report = validation_report(config, model, val)
    reloaded = validation_report(config, exported, val)
    np.testing.assert_allclose(
        eager_report["participant_macro_ade"], reloaded["participant_macro_ade"], atol=1e-6, rtol=1e-5
    )
    output = Path(output)
    write_json(output / "validation.json", reloaded)
    write_json(
        output / "reproduction.json",
        {"passed": True, "scope": "same environment export reload", "validated": False, "parity": parity},
    )
    benchmark = latency(exported, val, family="windowed", calls=calls, warmup=10, threads=training.threads)
    benchmark.update(
        evidence="DEVELOPMENT CPU COMPUTE on " + manifest["source_kind"] + " (contended grid timing)",
        hardware=context.get("hardware"),
        git_sha=context["git_sha"],
        git_dirty=context["git_dirty"],
    )
    write_json(output / "latency.json", benchmark)
    manifest["latency_report_id"] = sha(output / "latency.json")
    write_json(output / "manifest.json", manifest)
    return exported, manifest, val, reloaded


def train_reference(fold_dir, output, family, features, training, *, context):
    """The Phase 10 trajectory-only model, trained and exported by the unchanged Phase 10 path."""
    config = TemporalConfig(family, features, n=DEV["n"], k=VARIANTS["ref"]["k"], hidden=DEV["hidden"])
    exported, manifest, val, report = train_and_export(fold_dir, output, config, training, context=context)
    return exported, manifest, val, report


# ----------------------------------------------------------------------------- replay


def evaluate_sessions(
    model_fn_factory, manifest, fold, sessions, stats, cfg, output, *, probabilistic, family
):
    """The declared control grid on each validation session; model outputs cached per session."""
    registry = ZoneRegistry.from_config(cfg["zones"])
    points, gate_logs = [], {}
    probabilities = PROBABILITIES if probabilistic else (0.0,)
    for session in (s for s in sessions if s.table.participant in fold["val_participants"]):
        recorder = AnchorRecorder(CachedPredictions(model_fn_factory()))
        gate = (
            CrossingProbabilityGate(registry, v_min=V_MIN, anchor_of=recorder.anchor, **CROSSING)
            if probabilistic
            else None
        )
        index = 0
        for tau in TAUS:
            for p in probabilities:
                controls = default_controls(tau, p)
                _, evaluated = replay_session(
                    session,
                    cfg,
                    arm=arm_for(family),
                    controls=controls,
                    model_fn=recorder,
                    stats=stats,
                    feature_n=manifest["N"],
                    gate=gate,
                    validate_records=index == 0,
                )
                if gate is not None and index == 0:
                    gate_logs[session.table.session_id] = [
                        {k: e[k] for k in ("frame_id", "hand_id", "zone_id", "strike_probability")}
                        for e in gate.log
                    ]
                if gate is not None:
                    gate.log.clear()
                settings = {**controls, "family": family, "seed": manifest.get("seed"), "gate": bool(gate)}
                destination = output / "replay" / session.table.session_id / f"point-{index:03d}"
                points.append(point_row(evaluated, settings, destination=destination))
                index += 1
    if gate_logs:
        write_json(output / "crossing-probabilities.json", gate_logs)
    return points


# ----------------------------------------------------------------------------- offline outputs


def _track(meta, anchor):
    return SimpleNamespace(
        frame_id=meta["frame_id"],
        t_capture=meta["t_i"],
        hand_id=meta["hand_id"],
        tip_filtered=tuple(float(v) for v in anchor),
    )


def frame_predictions(config, sample, points, auxes=None, *, uncertainty_rows=None, kind=None, a_max=None):
    """TrajectoryPredictions for every validation window (offline; the same decoder as the replay)."""
    out = []
    for i, meta in enumerate(sample["meta"]):
        out.append(
            decode_extension(
                _track(meta, sample["anchor"][i]),
                points[i],
                np.zeros(1) if auxes is None else auxes[i],
                config,
                anticipator_id="p12-frame-evaluation",
                model_hash=None,
                a_max=a_max,
                uncertainty=None if uncertainty_rows is None else uncertainty_rows[i],
                kind=kind,
            )
        )
    return out


def crossing_calibration(predictions_, sample, cfg):
    """Crossing probability over all zones vs strike_within_H on strike_mask windows (reported only)."""
    registry = ZoneRegistry.from_config(cfg["zones"])
    draws = common_draws(CROSSING["samples"], seed=CROSSING["seed"])
    t = sample["tensors"]
    rows = np.flatnonzero(t["aux_mask"].numpy())
    probabilities = [
        intersect_prob(registry, predictions_[i], sample["anchor"][i], v_min=V_MIN, draws=draws).probability
        for i in rows
    ]
    outcomes = t["aux"].numpy()[rows].astype(int)
    report = calibration(probabilities, outcomes)
    report["mean_probability"] = float(np.mean(probabilities)) if len(rows) else None
    return report


def rule_models(rule, source_rows):
    """Trained cells a rule needs: all seeds of one family/fold for the ensemble, else one cell."""
    if RULES[rule].get("ensemble"):
        groups = {}
        for row in source_rows:
            groups.setdefault((row["family"], row["fold"]), []).append(row)
        return [sorted(rows, key=lambda r: r["seed"]) for _, rows in sorted(groups.items())]
    return [[row] for row in source_rows]


def load_any(model_dir):
    manifest = json.loads((Path(model_dir) / "manifest.json").read_text(encoding="utf-8"))
    return load_extension_model(model_dir) if "ext_config" in manifest else load_model(model_dir)


def smoothing_bound(fold_dir, config):
    train, _, _ = load_fold(fold_dir, config.data_view)
    select_grid(train, config)
    targets, mask, offsets = training_targets(train)
    return fit_acceleration_bound(targets, mask, offsets, quantile=SMOOTHING_QUANTILE)


def val_sample(fold_dir, config):
    _, val, _ = load_fold(fold_dir, config.data_view)
    return select_grid(val, config)


def run_rule(rule, rows, fold, fold_dir, sessions, stats, cfg, output):
    """One evaluation-only rule cell; returns its row and operating points."""
    models = [load_any(row["model_dir"]) for row in rows]
    manifests = [m for _, m in models]
    config = extension_config(manifests[0])
    sample = val_sample(fold_dir, config)
    family = manifests[0]["family"]
    a_max = None
    if rule == "e4-ens3":
        members = torch.stack([predictions(model, sample)[0] for model, _ in models])
        point = members.mean(0)

        def factory():
            return EnsembleAnticipator([m for m, _ in models], manifests, variant=rule)

        uncertainty = [member_rows(point[i].numpy(), members[:, i].numpy()) for i in range(sample["count"])]
        frames = frame_predictions(
            config, sample, point.numpy(), uncertainty_rows=uncertainty, kind="members_xy"
        )
    elif rule == "e5-smooth":
        a_max = smoothing_bound(fold_dir, config)
        raw = predictions(models[0][0], sample)[0].numpy()
        point = torch.tensor(np.stack([bounded_acceleration(p, config.offsets_s, a_max) for p in raw]))

        def factory():
            return ExtensionAnticipator(models[0][0], manifests[0], variant=rule, a_max=a_max)

        frames = None
    else:  # e2-mix2-agg: the trained M1 models, relabelled by the aggregated crossing probability
        point, aux = predictions(models[0][0], sample)

        def factory():
            return ExtensionAnticipator(models[0][0], manifests[0], variant=rule)

        frames = frame_predictions(config, sample, point.numpy(), aux.numpy())
    report = diagnostics(point, sample)
    points = evaluate_sessions(
        factory,
        manifests[0],
        fold,
        sessions,
        stats,
        cfg,
        output,
        probabilistic=rule in PROBABILISTIC,
        family=family,
    )
    row = {
        "variant": rule,
        "rule_of": RULES[rule]["source"],
        "model_dirs": [row["model_dir"] for row in rows],
        "fold": manifests[0]["fold"],
        "seed": "ensemble" if rule == "e4-ens3" else manifests[0]["seed"],
        "family": family,
        "source_kind": manifests[0]["source_kind"],
        "validation": {"trajectory": report},
        "harness": dev_pick(points),
        "a_max": a_max,
        "calibration": None if frames is None else crossing_calibration(frames, sample, cfg),
    }
    write_json(Path(output) / "rule.json", row)
    return row, points


def calibration_for_trained(variant, config, model, sample, cfg):
    """Deterministic indicator (reference, M1) or distribution (Gaussian) calibration."""
    point, aux = predictions(model, sample)
    if variant == "e4-gauss":
        frames = frame_predictions(config, sample, point.numpy(), aux.numpy())
    elif variant in ("ref", "e2-mix2"):
        plain = ExtensionConfig.from_dict({**config.to_dict(), "representation": "displacement", "modes": 1})
        frames = frame_predictions(plain, sample, point.numpy())
    else:
        return None
    return crossing_calibration(frames, sample, cfg)


def budget_note():
    return "SYNTHETIC development constants " + json.dumps(DEV_BUDGET) + f"; W {W_S} s; zero delay"


def dev_pick(points):
    """Development operating point along one model's curve (Phase 10 rule with DEV_BUDGET)."""
    choice = select_point(points, **DEV_BUDGET)
    point, feasible = choice["point"], choice["feasible"]

    def value(key):
        return point[key] if point and feasible else None

    return {
        "feasible": feasible,
        "median_lead_s": value("median_lead_s"),
        "fp_per_min": value("fp_per_min"),
        "fn_rate": value("fn_rate"),
        "timing_mae_s": value("timing_mae_s"),
        "zone_accuracy": value("zone_accuracy"),
        "matched": value("matched"),
        "settings": point["settings"] if point else None,
        "reason": choice["reason"],
        "budget": budget_note(),
    }


def training_config(seed, epochs):
    return TrainConfig(seed=seed, epochs=epochs, patience=epochs)


def load_run_rows(run_dir, *, extension=None):
    """Rows of a completed, validation-only Phase 12 grid run."""
    run_dir = Path(run_dir)
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    if record["status"] != "COMPLETED" or plan["test_access"]:
        raise ValueError(f"run incomplete or not validation-only: {run_dir}")
    if extension is not None and plan["extension"] != extension:
        raise ValueError(f"expected a {extension} run: {run_dir}")
    return plan, json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
