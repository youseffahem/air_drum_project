"""Run trained GBDT heads through event replay on the Phase 08 synthetic unit fixture."""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import replace
from pathlib import Path
from statistics import median

from _p08_fixture import synthetic_fixture

from spacedrums.commit import CommitSettings
from spacedrums.config import load_config
from spacedrums.eval.curves import plot_lead_fp, plot_result_diagnostics
from spacedrums.eval.replay import replay
from spacedrums.eval.report import evaluate_session, write_result
from spacedrums.features.normalize import NormStats
from spacedrums.geometry import ZoneRegistry
from spacedrums.models.gbdt.adapter import GBDTAdapter
from spacedrums.models.gbdt.predict import GBDTPredictor

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--fold-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output directory is nonempty")
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    manifest, cv, sessions = synthetic_fixture(cfg)
    predictor = GBDTPredictor(args.model_dir)
    model_manifest = predictor.manifest
    fold = next(f for f in cv["folds"] if f"fold-{f['fold']}" == model_manifest["fold"])
    if (
        model_manifest["dataset_hash"] != manifest["manifest_hash"]
        or model_manifest["split_hash"] != cv["split_hash"]
    ):
        raise ValueError("synthetic fixture/model split mismatch")
    session = next(s for s in sessions if s.table.participant in fold["val_participants"])
    schema = session.schema
    stats = NormStats.read(
        args.fold_dir / "norm_stats.json",
        fold=fold["fold"],
        dataset_version=manifest["dataset_version"],
        split_hash=cv["split_hash"],
        dataset_hash=manifest["manifest_hash"],
        schema=schema,
    )
    registry = ZoneRegistry.from_config(cfg["zones"])
    labels = [
        {
            **g,
            "qc_status": "PENDING_REVIEW",
            "review": {"reviewed": False},
            "segment_type": "SYNTHETIC_UNIT",
            "t_start": None,
            "t_end": None,
        }
        for g in session.labels
    ]
    segments = [{**s, "type": "SYNTHETIC_UNIT", "hands": ["LEFT", "RIGHT"]} for s in session.segments]
    args.output.mkdir(parents=True, exist_ok=True)
    curve = []
    for mode in ("direct", "trajectory"):
        adapter = GBDTAdapter(predictor, mode=mode, dt_step=model_manifest["dt_step_s"])
        for i, (tau, p) in enumerate(itertools.product((0.05, 0.10), (0.1, 0.3, 0.5))):
            commit = replace(
                CommitSettings.from_config(cfg), tti_commit_s=tau, p_commit=p, n_confirm_frames=0
            )
            result = replay(
                session.tracks,
                arm="MODEL:C-GBDT",
                registry=registry,
                commit_settings=commit,
                v_min=cfg["geometry"]["v_min"],
                session_id=session.table.session_id,
                model=adapter,
                feature_schema=schema,
                feature_window_n=model_manifest["feature_shape"][0],
                norm_stats=stats,
                feature_records=session.table.records,
            )
            evaluated = evaluate_session(
                result.strike_rows(session.table.session_id, session.table.participant),
                labels,
                segments,
                w_s=0.05,
                include_unreviewed_selftest=True,
            )
            evaluated.update(
                {
                    "mode": mode,
                    "source_kind": "SYNTHETIC",
                    "evidence_label": "IN-MEMORY UNIT FIXTURE - NOT PARTICIPANT RESULT",
                    "model_hash": predictor.model_hash,
                    "settings": {"tti_commit_s": tau, "p_commit": p, "n_confirm_frames": 0},
                }
            )
            write_result(args.output / mode / f"point-{i:03d}", evaluated)
            if i == 0:
                plot_result_diagnostics(evaluated, args.output / mode / f"point-{i:03d}")
            leads = [e["lead_s"] for e in evaluated["events"] if e["kind"] == "MATCH"]
            curve.append(
                {
                    "settings": {
                        "arm": "C-GBDT",
                        "motion_model": mode,
                        "K": model_manifest["trajectory_steps"],
                        "tti_commit_s": tau,
                        "p_commit": p,
                    },
                    "mode": mode,
                    "matched": evaluated["pooled"]["matched"],
                    "fp": evaluated["pooled"]["fp"],
                    "fn": evaluated["pooled"]["fn"],
                    "median_lead_s": median(leads) if leads else None,
                    "fp_per_min": evaluated["pooled"]["fp_per_min"],
                    "fn_rate": evaluated["pooled"]["fn_rate"],
                }
            )
    (args.output / "curve.json").write_text(json.dumps(curve, indent=2), encoding="utf-8")
    plot_lead_fp(curve, args.output / "lead-vs-fp.png", title="GBDT synthetic unit fixture")
    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "evidence_kind": "SYNTHETIC",
                "fixture": "Phase 08 in-memory unit fixture",
                "model_hash": predictor.model_hash,
                "dataset_hash": manifest["manifest_hash"],
                "split_hash": cv["split_hash"],
                "fold": fold["fold"],
                "participant": session.table.participant,
                "w_s": 0.05,
                "w_frozen": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"runs": len(curve), "participant": session.table.participant, "evidence_kind": "SYNTHETIC"}
        )
    )


if __name__ == "__main__":
    main()
