"""Evaluate an exported temporal model on one authorized validation session or sample archive."""

import argparse
import json
from pathlib import Path

import numpy as np
from _p10 import write_json
from _p10_eval import evaluate_grid

from spacedrums.config import load_config
from spacedrums.data.feature_dataset import load_session
from spacedrums.features.normalize import NormStats
from spacedrums.models.temporal import TemporalConfig
from spacedrums.models.temporal.data import read_samples, sha
from spacedrums.models.temporal.export import load_model
from spacedrums.models.temporal.train import diagnostics, predictions


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--partition", choices=("val", "test"), default="val")
    ap.add_argument("--samples", type=Path)
    ap.add_argument("--session-dir", type=Path)
    ap.add_argument("--label-dir", type=Path)
    ap.add_argument("--fold-dir", type=Path)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--w-s", type=float, default=0.05)
    ap.add_argument("--delay-s", type=float, default=0)
    ap.add_argument("--delay-evidence", type=Path)
    ap.add_argument("--expected", type=Path, help="Reproduce validation.json from exported model")
    args = ap.parse_args()
    if args.partition == "test":
        ap.error(
            "PENDING: Phase 09 frozen W/gate, participant CV selection, "
            "owner FP budget and single-run preregistration"
        )
    if args.delay_s < 0 or not np.isfinite(args.delay_s) or args.delay_s and args.delay_evidence is None:
        ap.error("nonnegative finite delay and measured delay evidence required")
    if args.output.exists():
        ap.error("output exists; evaluation artifacts are immutable")
    model, m = load_model(args.model_dir)
    if args.samples:
        if sha(args.samples) != m["val_samples_hash"]:
            ap.error("only this model's hashed validation samples are authorized")
        sample = read_samples(args.samples, TemporalConfig(**m["config"]), aux_horizon_s=m["aux_horizon_s"])
        metrics = diagnostics(predictions(model, sample)[0], sample)
        if args.expected:
            expected = json.loads(args.expected.read_text(encoding="utf-8"))

            # Compare every numeric metric, denominator and participant identity, not just a mean.
            def compare(a, b):
                if isinstance(a, dict):
                    assert a.keys() == b.keys()
                    for k in a:
                        compare(a[k], b[k])
                elif isinstance(a, list):
                    assert len(a) == len(b)
                    for x, y in zip(a, b, strict=True):
                        compare(x, y)
                elif isinstance(a, (float, int)):
                    np.testing.assert_allclose(a, b, atol=1e-6, rtol=1e-5)
                else:
                    assert a == b

            compare(metrics, expected)
        write_json(
            args.output,
            {
                "metrics": metrics,
                "export_hash": m["export_hash"],
                "reproduced": bool(args.expected),
                "atol": 1e-6,
                "rtol": 1e-5,
                "validated": False,
                "scope": "same environment subprocess",
            },
        )
        return
    if not all((args.session_dir, args.label_dir, args.fold_dir)):
        ap.error("provide --samples or --session-dir, --label-dir and --fold-dir")
    # Check identity BEFORE opening labels/tracks of a possible held-out participant.
    metadata = json.loads((args.session_dir / "metadata.json").read_text(encoding="utf-8"))
    if metadata["participant_id"] not in m["val_participants"]:
        ap.error("session is outside the model's validation participant roster")
    session = load_session(args.session_dir, args.label_dir, selftest=args.selftest)
    if session.table.source_kind != m["source_kind"]:
        ap.error("model/session evidence kind mismatch")
    stats_path = args.fold_dir / "norm_stats.json"
    if sha(stats_path) != m["norm_stats_id"]:
        ap.error("normalization hash mismatch")
    stats = NormStats.read(
        stats_path,
        fold=m["fold"],
        dataset_version=m["dataset_version"],
        dataset_hash=m["dataset_hash"],
        split_hash=m["split_hash"],
        schema=session.schema,
    )
    cfg = load_config(args.session_dir / "config.snapshot.yaml")
    rows = evaluate_grid(
        session,
        cfg,
        model=model,
        manifest=m,
        stats=stats,
        output=args.output,
        w_s=args.w_s,
        delay_s=args.delay_s,
    )
    write_json(args.output / "curves.json", rows)
    write_json(
        args.output / "provenance.json",
        {
            "inputs": session.input_hashes,
            "export_hash": m["export_hash"],
            "delay_evidence_hash": sha(args.delay_evidence) if args.delay_evidence else None,
            "w_s": args.w_s,
            "partition": "val",
        },
    )


if __name__ == "__main__":
    main()
