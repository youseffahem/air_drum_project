"""Freeze/compare full live records and Phase 09 harness results before retaining optimizations.

The participant fold is required for the full gate. The available synthetic validation fixture
and developer captures are explicitly separate development checks. No hidden test partition opens.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from _p08_fixture import synthetic_fixture
from _p10 import write_json
from _p10_eval import replay_one
from _p13 import parity, read_plan
from _p16 import CANDIDATES, candidate, evidence

from spacedrums.app.arms import build_model_arm
from spacedrums.app.main import Perception
from spacedrums.capture import ReplayFrameSource
from spacedrums.models.temporal.config import TemporalConfig
from spacedrums.models.temporal.data import read_samples, sha
from spacedrums.models.temporal.train import diagnostics, predictions
from spacedrums.timing import now

TOLERANCES = {
    "deterministic_atol": 0.0,
    "deterministic_rtol": 0.0,
    "prediction_atol": 1e-6,
    "prediction_rtol": 1e-5,
    "absolute_timestamp_atol_s": 1e-6,
    "lead_median_band_s": 0.001,
    "commit_set": "identical ordered full records (clock stamps excluded); no timing-shift waiver",
    "ignored_fields": ["t_candidate", "t_inference_done", "model_hash", "config_hash"],
    "delay_policy": "identical historical capture-to-available delay; no measured runtime feedback",
}


def compare(actual, expected, *, atol=0.0, rtol=0.0, path="root"):
    """Absolute timestamp tolerance never scales with the monotonic clock epoch."""
    maximum = 0.0
    if isinstance(actual, dict) and isinstance(expected, dict):
        if actual.keys() != expected.keys():
            raise AssertionError(f"{path}: keys differ")
        for key in actual:
            if key not in TOLERANCES["ignored_fields"]:
                maximum = max(
                    maximum, compare(actual[key], expected[key], atol=atol, rtol=rtol, path=f"{path}.{key}")
                )
    elif isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(actual) != len(expected):
            raise AssertionError(f"{path}: count {len(actual)} != {len(expected)}")
        for i, (a, b) in enumerate(zip(actual, expected, strict=True)):
            maximum = max(maximum, compare(a, b, atol=atol, rtol=rtol, path=f"{path}[{i}]"))
    elif (
        isinstance(actual, (float, int))
        and not isinstance(actual, bool)
        and isinstance(expected, (float, int))
    ):
        name = path.rsplit(".", 1)[-1]
        timestamp = name.startswith("t_") or name == "refractory_until"
        absolute = min(atol, TOLERANCES["absolute_timestamp_atol_s"]) if timestamp else atol
        relative = 0 if timestamp else rtol
        if (
            not np.isfinite(actual)
            or not np.isfinite(expected)
            or abs(actual - expected) > absolute + relative * abs(expected)
        ):
            raise AssertionError(f"{path}: {actual} != {expected}")
        maximum = abs(actual - expected)
    elif actual != expected:
        raise AssertionError(f"{path}: {actual!r} != {expected!r}")
    return maximum


def snapshot(cfg, plan, val_samples, *, causal=False):
    if cfg["anticipator"]["fallback"]["enabled"]:
        raise ValueError("regression needs the explicitly pinned no-fallback replay configuration")
    raw = []
    input_hashes = {}
    for session in plan["sessions"]:
        source = ReplayFrameSource(session["path"])
        input_hashes[session["id"]] = {
            "frames": sha(source.dir / "frames.jsonl"),
            "images": {s.image_ref.path: sha(source.dir / s.image_ref.path) for s in source},
        }
        perception = Perception(cfg)

        def frames(source=source, perception=perception):
            for sample in source:
                yield sample, perception(source.view(sample))

        try:
            report, results = parity(cfg, frames(), session_id=session["id"], measured_delay=False)
        finally:
            perception.close()
        if causal:
            from parity_test import causal_raw

            report["causality"] = causal_raw(cfg, source, results, session["id"])
        raw.append(
            {
                "id": session["id"],
                "kind": session["kind"],
                "harness_parity": report["passed"],
                "causality": report.get("causality"),
                "tracks": [hf.track.to_dict() for r in results for hf in r.hands.values()],
                "features": [hf.features.to_dict() for r in results for hf in r.hands.values()],
                "predictions": [
                    p.to_dict()
                    for r in results
                    for hf in r.hands.values()
                    for p in (hf.prediction, hf.model_prediction)
                    if p is not None
                ],
                "candidates": [
                    p.to_dict() for r in results for hf in r.hands.values() for p in hf.candidates
                ],
                "commits": [p.to_dict() for r in results for p in r.commits],
            }
        )
    model = build_model_arm(cfg, clock=now)
    m = model.manifest
    if sha(val_samples) != m["val_samples_hash"]:
        raise ValueError("sample archive differs from the model's pinned validation samples")
    sample = read_samples(val_samples, TemporalConfig(**m["config"]), aux_horizon_s=m["aux_horizon_s"])
    pred = predictions(model.adapter.model, sample)[0]
    validation = diagnostics(pred, sample)
    manifest, split, sessions = synthetic_fixture(cfg)
    if m["source_kind"] != "SYNTHETIC" or manifest["manifest_hash"] != m["dataset_hash"]:
        raise ValueError("this development metric fixture must match the synthetic model's dataset")
    controls = {
        "tti_commit_s": cfg["commit"]["tti_commit_s"],
        "p_commit": cfg["commit"]["p_commit"],
        "n_confirm_frames": cfg["commit"]["n_confirm_frames"],
        "v_min": cfg["geometry"]["v_min"],
        "refractory_zone_s": cfg["commit"]["refractory_zone_s"],
    }
    harness = []
    for session in sessions:
        if session.table.participant not in m["val_participants"]:
            continue
        result, metrics = replay_one(
            session,
            cfg,
            model=model.adapter.model,
            manifest=m,
            stats=model.stats,
            settings=controls,
            w_s=0.05,
        )
        harness.append(
            {
                "id": session.table.session_id,
                "metrics": metrics,
                "commits": [r.to_dict() for r in result.committed],
            }
        )
    return {
        "raw": raw,
        "validation": validation,
        "harness": harness,
        "inputs": input_hashes,
        "val_samples_hash": sha(val_samples),
        "model_hash": m["export_hash"],
        "synthetic_fold": m["fold"],
        "synthetic_split_hash": m["split_hash"],
        "participant_fold": "PENDING: reviewed ds-v1.0 unavailable",
    }


def compare_snapshot(current, reference):
    checks = []

    def check(name, a, b, floating=False):
        try:
            maximum = compare(a, b, atol=1e-6 if floating else 0, rtol=1e-5 if floating else 0)
            checks.append({"name": name, "passed": True, "max_abs_delta": maximum})
        except AssertionError as exc:
            checks.append({"name": name, "passed": False, "error": str(exc)})

    check("input_hashes", current["inputs"], reference["inputs"])
    for key in ("val_samples_hash", "synthetic_fold", "synthetic_split_hash"):
        check(key, current[key], reference[key])
    check("raw_session_roster", [r["id"] for r in current["raw"]], [r["id"] for r in reference["raw"]])
    for actual, expected in zip(current["raw"], reference["raw"], strict=True):
        for name in ("tracks", "features", "predictions", "candidates", "commits"):
            check(
                actual["id"] + ":" + name, actual[name], expected[name], name in ("predictions", "candidates")
            )
    check("validation_trajectory_metrics", current["validation"], reference["validation"], True)
    check("synthetic_harness", current["harness"], reference["harness"])
    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "participant_evidence": "PENDING",
        "tolerances": TOLERANCES,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--val-samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--candidate", choices=CANDIDATES, default="none")
    parser.add_argument("--opencv-threads", type=int)
    parser.add_argument("--causal", action="store_true")
    parser.add_argument("--slug", default="regression")
    args = parser.parse_args(argv)
    if args.opencv_threads is not None:
        if args.opencv_threads < 1:
            parser.error("positive OpenCV thread count required")
        cv2.setNumThreads(args.opencv_threads)
    with evidence(args.config, args.output, args.slug, "16.3") as (run, cfg):
        write_json(run.dir / "tolerances.json", TOLERANCES)
        plan = read_plan(args.plan)
        write_json(run.dir / "plan.json", plan)
        with candidate(args.candidate):
            result = snapshot(cfg.data, plan, args.val_samples, causal=args.causal)
        write_json(run.dir / "snapshot.json", result)
        if args.reference:
            reference = json.loads(args.reference.read_text(encoding="utf-8"))
            outcome = compare_snapshot(result, reference)
        else:
            outcome = {"passed": True, "reference_created": True, "tolerances": TOLERANCES}
        outcome.update(
            candidate=args.candidate, reference_hash=sha(args.reference) if args.reference else None
        )
        write_json(run.dir / "regression.json", outcome)
        print(f"REGRESSION: {'PASS' if outcome['passed'] else 'FAIL'}", flush=True)
    return 0 if outcome["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
