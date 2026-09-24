"""Phase 10 orchestration/provenance helpers. No participant defaults are selected."""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
from _runlog import git_dirty, git_sha, hardware_snapshot

from spacedrums.eval.constants import HARNESS_VERSION
from spacedrums.models.temporal.data import sha
from spacedrums.models.temporal.export import export_model, latency, load_model
from spacedrums.models.temporal.train import diagnostics, predictions, train_fold

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def source_hashes():
    return {
        p.relative_to(ROOT).as_posix(): sha(p)
        for base in ("src", "scripts", "tests", "configs", "schemas")
        for p in sorted((ROOT / base).rglob("*"))
        if p.suffix in (".py", ".yaml", ".json")
    }


def provenance():
    return {
        "git_sha": git_sha(),
        "git_dirty": git_dirty(),
        "started_at": datetime.now().astimezone().isoformat(),
        "labels_version": "labels-v1.0",
        "harness_version": HARNESS_VERSION,
        "harness_hashes": {p.name: sha(p) for p in sorted((ROOT / "src/spacedrums/eval").glob("*.py"))},
        "lock_hash": sha(ROOT / "requirements.lock"),
        "codex_model": "GPT-6 family exposed by system; exact deployed variant unavailable",
        "codex_reasoning_effort": "UNAVAILABLE to the agent; picker setting not asserted",
    }


def train_and_export(fold_dir, output, config, training, *, context, aux_horizon_s=None, calls=100):
    model, manifest, val = train_fold(
        fold_dir, output, config, training, provenance=context, aux_horizon_s=aux_horizon_s
    )
    parity = export_model(model, output, val)
    exported, manifest = load_model(output)
    eager_result = diagnostics(predictions(model, val)[0], val)
    exported_result = diagnostics(predictions(exported, val)[0], val)
    # Full raw prediction parity above; metric reproduction allows documented float rounding.
    np.testing.assert_allclose(
        eager_result["participant_macro_ade"], exported_result["participant_macro_ade"], atol=1e-6, rtol=1e-5
    )
    write_json(Path(output) / "validation.json", exported_result)
    write_json(
        Path(output) / "reproduction.json",
        {
            "passed": True,
            "scope": "same environment export reload",
            "validated": False,
            "atol": 1e-6,
            "rtol": 1e-5,
            "parity": parity,
        },
    )
    benchmark = latency(exported, val, family=config.family, calls=calls, warmup=10, threads=training.threads)
    benchmark.update(
        evidence="DEVELOPMENT CPU COMPUTE on " + manifest["source_kind"],
        hardware=context.get("hardware"),
        measured_at=datetime.now().astimezone().isoformat(),
        git_sha=context["git_sha"],
        git_dirty=context["git_dirty"],
    )
    write_json(Path(output) / "latency.json", benchmark)
    manifest["latency_report_id"] = sha(Path(output) / "latency.json")
    write_json(Path(output) / "manifest.json", manifest)
    return exported, manifest, val, exported_result


def bootstrap_participants(rows, *, seed=10, repeats=2000):
    """Macro-participant CI. Caller must first aggregate repeats/seeds within participant."""
    values = np.asarray([v for v in rows.values() if v is not None], dtype=float)
    if len(values) < 2:
        return {
            "n": len(values),
            "estimate": float(values.mean()) if len(values) else None,
            "ci95": None,
            "reason": "fewer than two participants",
        }
    rng = np.random.default_rng(seed)
    boot = rng.choice(values, (repeats, len(values)), replace=True).mean(axis=1)
    return {
        "n": len(values),
        "estimate": float(values.mean()),
        "ci95": np.percentile(boot, [2.5, 97.5]).tolist(),
        "repeats": repeats,
        "seed": seed,
        "unit": "participant",
    }


def select_candidate(points, *, fp_budget, fn_ceiling, timing_bound_s, latency_bound_ms):
    """Neutral across arms; only feasible achieved points compete for lead time."""
    if any(not np.isfinite(v) or v < 0 for v in (fp_budget, fn_ceiling, timing_bound_s, latency_bound_ms)):
        raise ValueError("finite nonnegative predeclared budgets required")
    if fn_ceiling > 1:
        raise ValueError("FN ceiling must be in [0,1]")
    keys = ("median_lead_s", "fp_per_min", "fn_rate", "timing_mae_s", "latency_p95_ms")
    valid = [p for p in points if all(p.get(k) is not None and np.isfinite(p[k]) for k in keys)]
    feasible = [
        p
        for p in valid
        if p["fp_per_min"] <= fp_budget
        and p["fn_rate"] <= fn_ceiling
        and p["timing_mae_s"] <= timing_bound_s
        and p["latency_p95_ms"] <= latency_bound_ms
    ]
    if not feasible:
        return {"selected": None, "reason": "no feasible arm; no useful lead-time conclusion"}
    selected = min(
        feasible,
        key=lambda p: (
            -p["median_lead_s"],
            p["fp_per_min"],
            p["timing_mae_s"],
            p["latency_p95_ms"],
            json.dumps(p["settings"], sort_keys=True),
        ),
    )
    return {"selected": selected, "useful_positive_lead": selected["median_lead_s"] > 0}


def hardware():
    return hardware_snapshot(camera_model="none: offline replay", audio_device="none: offline replay")
