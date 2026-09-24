"""Exercise A/B/C-GBDT comparison on identical SYNTHETIC validation groups and fixed target grid."""

import argparse
import itertools
import json
import shutil
from dataclasses import replace
from pathlib import Path
from time import perf_counter_ns

import numpy as np
from _p08_fixture import synthetic_fixture
from _p10 import hardware, provenance, source_hashes, write_json
from _p10_eval import summarize_comparison
from _runlog import RunLog

from spacedrums.commit import CommitSettings
from spacedrums.config import load_config
from spacedrums.eval.curves import plot_lead_fp
from spacedrums.eval.replay import replay
from spacedrums.eval.report import evaluate_session, write_result
from spacedrums.features.normalize import NormStats
from spacedrums.geometry import ZoneRegistry
from spacedrums.models.gbdt.adapter import GBDTAdapter
from spacedrums.models.gbdt.predict import GBDTPredictor
from spacedrums.models.gbdt.train import train_fold
from spacedrums.models.temporal.data import fixed_grid, sha
from spacedrums.prediction import RuleSettings


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horizon-run", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    original = json.loads((args.horizon_run / "results.json").read_text())
    if {r["source_kind"] for r in original} != {"SYNTHETIC"}:
        ap.error("this development comparison is synthetic only; participant selection remains pending")
    cfg = load_config("configs/prototype.candidate.yaml")
    manifest, cv, sessions = synthetic_fixture(cfg)
    rows = [
        r
        for r in json.loads((args.horizon_run / "curves.json").read_text())
        if r["settings"]["N"] == 8 and r["settings"]["K"] == 4
    ]
    with RunLog(
        phase="10",
        task="10.10",
        slug="synthetic-comparison",
        config=cfg,
        experiments_dir=args.output,
        description="SYNTHETIC fixture comparison at candidate N8/K4; no participant-selected point",
    ) as run:
        write_json(
            run.dir / "execution.json",
            {**provenance(), "hardware": hardware(), "source_hashes": source_hashes()},
        )
        for fold in cv["folds"]:
            src = args.horizon_run / "features/n8-k4" / f"fold-{fold['fold']}"
            dst = run.dir / "fixed-grid" / src.name
            dst.mkdir(parents=True)
            for filename in ("norm_stats.json", "report.json"):
                shutil.copyfile(src / filename, dst / filename)
            # Adapt target-only representation to the same 4 x 1/30s grid, preserving X/M and fold stats.
            for part in ("train", "val"):
                with np.load(src / f"samples.{part}.npz", allow_pickle=False) as data:
                    arrays = {k: data[k].copy() for k in data.files}
                anchor = arrays["T_absolute"][:, 0] - arrays["T"][:, 0]
                target, mask = fixed_grid(
                    arrays["T"], arrays["target_offsets_s"], arrays["T_mask"], 4, 1 / 30
                )
                arrays.update(
                    T=target,
                    T_mask=mask,
                    T_absolute=target + anchor[:, None],
                    target_offsets_s=np.broadcast_to(np.arange(1, 5) / 30, mask.shape).copy(),
                )
                np.savez_compressed(dst / f"samples.{part}.npz", **arrays)
            stats = NormStats.read(
                dst / "norm_stats.json",
                fold=fold["fold"],
                dataset_version=manifest["dataset_version"],
                dataset_hash=manifest["manifest_hash"],
                split_hash=cv["split_hash"],
                schema=sessions[0].schema,
            )
            predictors = []
            for seed in (10, 11, 12):
                directory = run.dir / "gbdt" / f"seed-{seed}" / src.name
                train_fold(dst, directory, seed=seed)
                predictor = GBDTPredictor(directory)
                timing = []
                with np.load(dst / "samples.val.npz", allow_pickle=False) as sample:
                    x, mask = sample["X"][0], sample["M"][0]
                for i in range(70):
                    start = perf_counter_ns()
                    predictor.predict(x, mask)
                    if i >= 10:
                        timing.append((perf_counter_ns() - start) / 1e6)
                write_json(
                    directory / "latency.json",
                    {
                        "raw_ms": timing,
                        "threads": 1,
                        "p50_ms": float(np.percentile(timing, 50)),
                        "p95_ms": float(np.percentile(timing, 95)),
                        "p99_ms": float(np.percentile(timing, 99)),
                        "input_hash": sha(dst / "samples.val.npz"),
                    },
                )
                predictors.append((seed, predictor, float(np.percentile(timing, 95))))
            for session in (s for s in sessions if s.table.participant in fold["val_participants"]):
                arms = [("A", None, None, 0, None)] + [
                    ("B", motion, None, 0, None) for motion in ("CV", "CA")
                ]
                arms += [
                    ("MODEL:C-GBDT", mode, predictor, seed, cost)
                    for seed, predictor, cost in predictors
                    for mode in ("direct", "trajectory")
                ]
                for arm, mode, predictor, seed, cost in arms:
                    points = (
                        [(0.05, 0.0)]
                        if arm == "A"
                        else list(itertools.product((0.02, 0.05, 0.10), (0.3, 0.7)))
                    )
                    for ix, (tau, probability) in enumerate(points):
                        settings = replace(
                            CommitSettings.from_config(cfg),
                            tti_commit_s=tau,
                            p_commit=probability,
                            n_confirm_frames=0,
                        )
                        result = replay(
                            session.tracks,
                            arm=arm,
                            registry=ZoneRegistry.from_config(cfg["zones"]),
                            commit_settings=settings,
                            v_min=0.15,
                            session_id=session.table.session_id,
                            rule_settings=RuleSettings(motion_model=mode, K=4, dt_step=1 / 30)
                            if arm == "B"
                            else None,
                            model=GBDTAdapter(predictor, mode=mode, dt_step=1 / 30) if predictor else None,
                            feature_schema=session.schema,
                            feature_window_n=8,
                            norm_stats=stats,
                            feature_records=session.table.records,
                        )
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
                        segments = [
                            {**s, "type": "SYNTHETIC_UNIT", "hands": ["LEFT", "RIGHT"]}
                            for s in session.segments
                        ]
                        evaluated = evaluate_session(
                            result.strike_rows(session.table.session_id, session.table.participant),
                            labels,
                            segments,
                            w_s=0.05,
                            include_unreviewed_selftest=True,
                        )
                        folder = (
                            run.dir
                            / f"fold-{fold['fold']}"
                            / f"{arm.replace(':', '-')}-{mode}-{seed}"
                            / f"point-{ix}"
                        )
                        write_result(folder, {**evaluated, "source_kind": "SYNTHETIC"})
                        p = evaluated["pooled"]
                        rows.append(
                            {
                                "settings": {
                                    "arm": arm,
                                    "motion_model": mode,
                                    "K": 4,
                                    "N": 8,
                                    "seed": seed,
                                    "tti_commit_s": tau,
                                    "p_commit": probability,
                                },
                                "source_kind": "SYNTHETIC",
                                "participant": session.table.participant,
                                "median_lead_s": p["lead_s"]["median"],
                                "fp_per_min": p["fp_per_min"],
                                "fn_rate": p["fn_rate"],
                                "timing_mae_s": p["te_event_mae_s"],
                                "latency_p95_ms": cost,
                                "metrics": p,
                                "result_path": str(folder),
                            }
                        )
            print(f"synthetic comparison fold {fold['fold']} complete", flush=True)
        write_json(run.dir / "curves.json", rows)
        write_json(run.dir / "comparison.json", summarize_comparison(rows))
        plot_lead_fp(
            rows, run.dir / "lead-vs-fp.png", title="SYNTHETIC candidate comparison N8/K4; no selection"
        )
        for p in sorted(run.dir.rglob("*")):
            if p.is_file() and p.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(p, "other")
        run.finish(
            {"operating_points": len(rows), "participant_claim": False},
            notes="A/B inference latency and baseline trajectory/paired participant metrics remain pending; "
            "synthetic grouping CIs are not participant CIs. No selected operating points or winner.",
        )
        print(run.dir)


if __name__ == "__main__":
    main()
