"""Evaluate a trained fold's GBDT modes through causal geometry and commit replay."""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import replace
from pathlib import Path
from statistics import median

from spacedrums.commit import CommitSettings
from spacedrums.config import load_config
from spacedrums.data.feature_dataset import load_dataset
from spacedrums.data.labels.schema import sha256_file
from spacedrums.eval.constants import HARNESS_VERSION, W_CANDIDATE_DEFAULT_S, W_PRIMARY_S
from spacedrums.eval.curves import plot_lead_fp, plot_result_diagnostics
from spacedrums.eval.replay import DelayPolicy, replay
from spacedrums.eval.report import evaluate_session, write_result
from spacedrums.features.normalize import NormStats
from spacedrums.geometry import ZoneRegistry
from spacedrums.models.gbdt.adapter import GBDTAdapter
from spacedrums.models.gbdt.predict import GBDTPredictor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--splits-dir", type=Path, required=True)
    parser.add_argument("--fold-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--partition", choices=("val", "test"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--delay-s", type=float, default=0.0)
    parser.add_argument("--delay-evidence", type=Path)
    parser.add_argument(
        "--operating-point", type=Path, help="validation-selected commit settings; required for test"
    )
    parser.add_argument("--w-s", type=float, default=W_CANDIDATE_DEFAULT_S)
    args = parser.parse_args()
    if args.delay_s < 0 or args.delay_s and not args.delay_evidence:
        parser.error("nonzero delay requires measured --delay-evidence")
    if args.partition == "test" and args.operating_point is None:
        parser.error("held-out test requires a predeclared validation operating point")
    if args.partition == "test" and args.w_s != W_PRIMARY_S:
        parser.error("held-out test requires the frozen primary matching tolerance")
    manifest, cv, sessions = load_dataset(args.manifest, args.splits_dir, selftest=args.selftest)
    predictor = GBDTPredictor(args.model_dir)
    m = predictor.manifest
    fold = next((f for f in cv["folds"] if f["fold"] == int(m["fold"].split("-")[-1])), None)
    if fold is None or m["dataset_hash"] != manifest["manifest_hash"] or m["split_hash"] != cv["split_hash"]:
        raise ValueError("model/dataset/fold provenance mismatch")
    if set(m["train_participants"]) != set(fold["train_participants"]) or set(m["val_participants"]) != set(
        fold["val_participants"]
    ):
        raise ValueError("model participant split mismatch")
    schema = sessions[0].schema
    if schema.fingerprint != m["feature_schema_hash"]:
        raise ValueError("model feature schema mismatch")
    stats_path = args.fold_dir / "norm_stats.json"
    if sha256_file(stats_path) != m["norm_stats_hash"]:
        raise ValueError("normalization file hash mismatch")
    stats = NormStats.read(
        stats_path,
        fold=fold["fold"],
        dataset_version=manifest["dataset_version"],
        split_hash=cv["split_hash"],
        dataset_hash=manifest["manifest_hash"],
        schema=schema,
    )
    participants = set(fold["val_participants"] if args.partition == "val" else cv["test_participants"])
    selected = [s for s in sessions if s.table.participant in participants]
    if not selected or {s.table.participant for s in selected} != participants:
        raise ValueError("partition participant roster incomplete")
    point = json.loads(args.operating_point.read_text()) if args.operating_point else {}
    if args.partition == "test" and (
        point.get("model_hash") != predictor.model_hash or point.get("w_s") != args.w_s
    ):
        raise ValueError("test operating point was not selected for this model and W")
    delay = DelayPolicy("fixed", args.delay_s) if args.delay_s else DelayPolicy()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output directory is nonempty; use a new run path")
    args.output.mkdir(parents=True, exist_ok=True)
    curve = []
    for mode in ("direct", "trajectory"):
        mode_point = point.get(mode, {})
        grid = (
            [mode_point]
            if args.partition == "test"
            else [
                dict(zip(("tti_commit_s", "p_commit", "n_confirm_frames"), values, strict=True))
                for values in itertools.product((0.05, 0.10), (0.3, 0.5), (0, 2))
            ]
        )
        if args.partition == "test" and not mode_point:
            raise ValueError(f"test operating point lacks {mode} settings")
        for point_index, overrides in enumerate(grid):
            evaluations = []
            for session in selected:
                cfg = load_config(
                    Path(next(k for k in session.input_hashes if k.endswith("config.snapshot.yaml")))
                )
                registry = ZoneRegistry.from_config(cfg["zones"])
                commit = replace(CommitSettings.from_config(cfg), **overrides)
                adapter = GBDTAdapter(predictor, mode=mode, dt_step=m["dt_step_s"])
                frame_path = Path(next(k for k in session.input_hashes if k.endswith("frames.jsonl")))
                drops = {
                    row["frame_id"]: row["dropped_since_last"]
                    for row in (json.loads(line) for line in frame_path.read_text().splitlines())
                }
                result = replay(
                    session.tracks,
                    arm="MODEL:C-GBDT",
                    registry=registry,
                    commit_settings=commit,
                    v_min=cfg["geometry"]["v_min"],
                    session_id=session.table.session_id,
                    delay=delay,
                    model=adapter,
                    feature_schema=schema,
                    feature_window_n=m["feature_shape"][0],
                    norm_stats=stats,
                    feature_records=session.table.records,
                    dropped_by_frame=drops,
                )
                evaluated = evaluate_session(
                    result.strike_rows(session.table.session_id, session.table.participant),
                    session.labels,
                    session.segments,
                    w_s=args.w_s,
                    include_unreviewed_selftest=args.selftest,
                )
                evaluated.update(
                    {
                        "harness_version": HARNESS_VERSION,
                        "mode": mode,
                        "fold": fold["fold"],
                        "partition": args.partition,
                        "model_hash": predictor.model_hash,
                        "delay_s": args.delay_s,
                        "participant_id": session.table.participant,
                        "source_kind": session.table.source_kind,
                        "commit_settings": commit.full_id(),
                        "settings": overrides,
                    }
                )
                write_result(
                    args.output / mode / f"point-{point_index:03d}" / session.table.session_id, evaluated
                )
                if point_index == 0:
                    plot_result_diagnostics(
                        evaluated,
                        args.output / mode / f"point-{point_index:03d}" / session.table.session_id,
                    )
                evaluations.append(evaluated)
            matched = sum(r["pooled"]["matched"] for r in evaluations)
            fp = sum(r["pooled"]["fp"] for r in evaluations)
            fn = sum(r["pooled"]["fn"] for r in evaluations)
            active_s = sum(r["pooled"]["active_time_s"] for r in evaluations)
            lead = [e["lead_s"] for r in evaluations for e in r["events"] if e["kind"] == "MATCH"]
            curve.append(
                {
                    "settings": {
                        "arm": "C-GBDT",
                        "motion_model": mode,
                        "K": m["trajectory_steps"],
                        **overrides,
                    },
                    "mode": mode,
                    "point_index": point_index,
                    "matched": matched,
                    "fp": fp,
                    "fn": fn,
                    "active_time_s": active_s,
                    "median_lead_s": median(lead) if lead else None,
                    "fp_per_min": fp * 60 / active_s if active_s else None,
                    "fn_rate": fn / (matched + fn) if matched + fn else None,
                }
            )
    (args.output / "curve.json").write_text(json.dumps(curve, indent=2), encoding="utf-8")
    plot_lead_fp(
        curve,
        args.output / "lead-vs-fp.png",
        title=f"{m['evidence_kind']} fold {fold['fold']} {args.partition}",
    )
    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "harness_version": HARNESS_VERSION,
                "model_hash": predictor.model_hash,
                "dataset_hash": manifest["manifest_hash"],
                "dataset_version": manifest["dataset_version"],
                "labels_version": manifest["labels_version"],
                "split_hash": cv["split_hash"],
                "norm_stats_hash": m["norm_stats_hash"],
                "source_kind": m["evidence_kind"],
                "partition": args.partition,
                "fold": fold["fold"],
                "participants": sorted(participants),
                "w_s": args.w_s,
                "delay_s": args.delay_s,
                "delay_evidence_hash": sha256_file(args.delay_evidence) if args.delay_evidence else None,
                "w_frozen": W_PRIMARY_S is not None and args.w_s == W_PRIMARY_S,
                "artefacts": {
                    str(path.relative_to(args.output)): sha256_file(path)
                    for path in sorted(args.output.rglob("*"))
                    if path.is_file() and path.name != "manifest.json"
                },
            },
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
