"""Record delay materiality and same-model synthetic sensitivity; never invent a live constant."""

import argparse
import json
from pathlib import Path

import numpy as np
from _p08_fixture import synthetic_fixture
from _p10 import write_json
from _p10_eval import replay_one
from _p16 import evidence

from spacedrums.app.arms import build_model_arm
from spacedrums.commit import CommitSettings
from spacedrums.eval.constants import DELTA_PROC_LIVE_S, DELTA_PROC_MATERIAL_CHANGE_S
from spacedrums.eval.replay import DelayPolicy, replay
from spacedrums.eval.report import evaluate_session
from spacedrums.geometry import ZoneRegistry
from spacedrums.models.temporal.data import sha
from spacedrums.prediction import RuleSettings
from spacedrums.timing import now


def profile_value(directory):
    profile = json.loads((directory / "profile.json").read_text(encoding="utf-8"))
    if profile["kind"] != "wall-time profile" or profile["source"] != "replay":
        raise ValueError("this diagnostic expects a replay wall-time profile")
    values = [
        json.loads(p.read_text(encoding="utf-8"))["application"]["counters"]["per_frame_processing_s"]["p95"]
        for p in sorted(directory.glob("sample-*.json"))
    ]
    if not values or any(v is None or not np.isfinite(v) or v < 0 for v in values):
        raise ValueError("missing or invalid processing measurements")
    return float(np.median(values))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--before-profile", type=Path, required=True)
    parser.add_argument("--after-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    before, after = profile_value(args.before_profile), profile_value(args.after_profile)
    with evidence(args.config, args.output, "delay-reconciliation", "16.7") as (run, cfg):
        model = build_model_arm(cfg.data, clock=now)
        if model.manifest["source_kind"] != "SYNTHETIC":
            raise ValueError("diagnostic fixture must not stand in for participant evaluation")
        _, _, sessions = synthetic_fixture(cfg.data)
        controls = {
            k: cfg["commit"][k] for k in ("tti_commit_s", "p_commit", "n_confirm_frames", "refractory_zone_s")
        }
        controls["v_min"] = cfg["geometry"]["v_min"]
        registry = ZoneRegistry.from_config(cfg["zones"])
        results = []
        rule_cfg = {**cfg.data, "anticipator": {**cfg["anticipator"], "type": "rule"}}
        for version, delay in (
            ("Historical-zero", 0.0),
            ("Historical-replay-proxy", before),
            ("Current-replay-proxy", after),
        ):
            for session in sessions:
                if session.table.participant not in model.manifest["val_participants"]:
                    continue
                for arm in ("A", "B", "C"):
                    if arm == "C":
                        replayed, metrics = replay_one(
                            session,
                            cfg.data,
                            model=model.adapter.model,
                            manifest=model.manifest,
                            stats=model.stats,
                            settings=controls,
                            w_s=0.05,
                            delay_s=delay,
                        )
                    else:
                        replayed = replay(
                            session.tracks,
                            arm=arm,
                            registry=registry,
                            commit_settings=CommitSettings.from_config(cfg.data),
                            v_min=controls["v_min"],
                            session_id=session.table.session_id,
                            delay=DelayPolicy("fixed", delay),
                            rule_settings=RuleSettings.from_config(rule_cfg) if arm == "B" else None,
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
                        metrics = evaluate_session(
                            replayed.strike_rows(session.table.session_id),
                            labels,
                            segments,
                            w_s=0.05,
                            include_unreviewed_selftest=True,
                        )
                    row = {
                        "version": version,
                        "arm": arm,
                        "fixed_delay_s": delay,
                        "session": session.table.session_id,
                        "source_kind": "SYNTHETIC",
                        "metrics": metrics,
                        "commits": [r.to_dict() for r in replayed.committed],
                    }
                    results.append(row)
        write_json(
            run.dir / "rerun-manifest.json",
            {
                "before_profile": str(args.before_profile),
                "after_profile": str(args.after_profile),
                "before_hash": sha(args.before_profile / "profile.json"),
                "after_hash": sha(args.after_profile / "profile.json"),
                "before_proxy_s": before,
                "after_proxy_s": after,
                "proxy_method": "median per-run perception+decision p95; excludes overlay/decode",
                "materiality_candidate_s": DELTA_PROC_MATERIAL_CHANGE_S,
                "material_by_p95": abs(after - before) >= DELTA_PROC_MATERIAL_CHANGE_S,
                "accepted_live_delta_proc_s": DELTA_PROC_LIVE_S,
                "live_policy": "PENDING representative live strokes and reviewer acceptance",
                "headline_participant_reruns": "PENDING reviewed ds-v1.0 and shipped model",
                "model_hash_unchanged": model.manifest["export_hash"],
                "interpretation": "Synthetic sensitivity; replay proxies omit live queue/capture effects.",
                "evaluations": results,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
