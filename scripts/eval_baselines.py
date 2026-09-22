"""Replay A/B on one verified session. Self-test outputs are diagnostic only."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import yaml

from spacedrums.commit import CommitSettings
from spacedrums.config import config_hash, load_config
from spacedrums.data.feature_dataset import load_session
from spacedrums.data.labels.schema import sha256_file
from spacedrums.eval.constants import HARNESS_VERSION, W_CANDIDATE_DEFAULT_S, W_PRIMARY_S
from spacedrums.eval.curves import plot_lead_fp, plot_result_diagnostics
from spacedrums.eval.replay import DelayPolicy, replay
from spacedrums.eval.report import curve_points, evaluate_session, write_result
from spacedrums.geometry import ZoneRegistry
from spacedrums.prediction import RuleSettings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--label-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selftest", action="store_true", help="allow synthetic/developer unreviewed labels")
    parser.add_argument("--delay-s", type=float, default=0.0)
    parser.add_argument("--delay-evidence", type=Path, help="measurement document for nonzero delay")
    parser.add_argument("--w-s", type=float, default=W_CANDIDATE_DEFAULT_S)
    args = parser.parse_args()
    if args.delay_s < 0 or args.delay_s and not args.delay_evidence:
        parser.error("nonzero delay requires --delay-evidence")
    session = load_session(args.session_dir, args.label_dir, selftest=args.selftest)
    frames = [json.loads(line) for line in (args.session_dir / "frames.jsonl").read_text().splitlines()]
    drops = {row["frame_id"]: row["dropped_since_last"] for row in frames}
    config_path = args.session_dir / "config.snapshot.yaml"
    cfg = load_config(config_path)
    registry = ZoneRegistry.from_config(cfg["zones"])
    base_commit = CommitSettings.from_config(cfg)
    base_rule = RuleSettings.from_config(cfg)
    delay = DelayPolicy("fixed", args.delay_s) if args.delay_s else DelayPolicy()
    output = args.output
    if output.exists() and any(output.iterdir()):
        parser.error("output directory is nonempty; use a new run path")
    output.mkdir(parents=True, exist_ok=True)
    settings = [
        {
            "arm": "A",
            "motion_model": None,
            "K": None,
            "tti_commit_s": base_commit.tti_commit_s,
            "p_commit": base_commit.p_commit,
            "n_confirm_frames": base_commit.n_confirm_frames,
        }
    ]
    for mode in ("CV", "CA"):
        for k in (3, 6):
            for tau in (0.05, 0.10):
                for p in (0.3, 0.5):
                    for n in (0, 2):
                        settings.append(
                            {
                                "arm": "B",
                                "motion_model": mode,
                                "K": k,
                                "tti_commit_s": tau,
                                "p_commit": p,
                                "n_confirm_frames": n,
                            }
                        )
    curve_input = []
    for index, choice in enumerate(settings):
        commit = replace(
            base_commit,
            tti_commit_s=choice["tti_commit_s"],
            p_commit=choice["p_commit"],
            n_confirm_frames=choice["n_confirm_frames"],
        )
        rule = (
            replace(base_rule, motion_model=choice["motion_model"], K=choice["K"])
            if choice["arm"] == "B"
            else None
        )
        replayed = replay(
            session.tracks,
            arm=choice["arm"],
            registry=registry,
            commit_settings=commit,
            v_min=cfg["geometry"]["v_min"],
            session_id=session.table.session_id,
            delay=delay,
            rule_settings=rule,
            dropped_by_frame=drops,
        )
        evaluated = evaluate_session(
            replayed.strike_rows(session.table.session_id, session.table.participant),
            session.labels,
            session.segments,
            w_s=args.w_s,
            include_unreviewed_selftest=args.selftest,
        )
        evaluated.update(
            {
                "settings": choice,
                "source_kind": session.table.source_kind,
                "session_id": session.table.session_id,
                "participant_id": session.table.participant,
                "w_s": args.w_s,
                "delay_s": args.delay_s,
                "harness_version": HARNESS_VERSION,
            }
        )
        run_cfg = copy.deepcopy(cfg.data)
        run_cfg["commit"].update(
            {
                "tti_commit_s": choice["tti_commit_s"],
                "p_commit": choice["p_commit"],
                "n_confirm_frames": choice["n_confirm_frames"],
            }
        )
        if choice["arm"] == "B":
            run_cfg["anticipator"]["K"] = choice["K"]
            run_cfg["anticipator"]["rule"]["motion_model"] = choice["motion_model"]
        evaluated["config_hash"] = config_hash(run_cfg)
        run_dir = output / f"run-{index:03d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "config.snapshot.yaml").write_text(
            yaml.safe_dump(run_cfg, sort_keys=True), encoding="utf-8"
        )
        write_result(run_dir, evaluated)
        if index in (0, 1):
            plot_result_diagnostics(evaluated, run_dir)
        if choice["arm"] == "B":
            curve_input.append(evaluated)
    (output / "curve.json").write_text(json.dumps(curve_points(curve_input), indent=2), encoding="utf-8")
    plot_lead_fp(
        curve_points(curve_input),
        output / "lead-vs-fp.png",
        title=f"{session.table.source_kind} diagnostic: {session.table.session_id}",
    )
    harness_files = sorted(Path("src/spacedrums/eval").glob("*.py"))
    h = hashlib.sha256()
    for path in harness_files:
        h.update(path.name.encode())
        h.update(path.read_bytes())
    manifest = {
        "harness_version": HARNESS_VERSION,
        "harness_hash": "sha256:" + h.hexdigest(),
        "source_kind": session.table.source_kind,
        "session_id": session.table.session_id,
        "participant_id": session.table.participant,
        "selftest": args.selftest,
        "dataset_version": session.labels[0]["dataset_version"] if session.labels else None,
        "labels_version": session.labels[0]["labels_version"] if session.labels else None,
        "labels_hash": session.labels[0]["provenance"]["labels_hash"] if session.labels else None,
        "config_hash": cfg.config_hash,
        "config_file_hash": sha256_file(config_path),
        "input_hashes": session.input_hashes,
        "w_s": args.w_s,
        "w_frozen": W_PRIMARY_S is not None and args.w_s == W_PRIMARY_S,
        "delay_policy": delay.name,
        "delay_s": args.delay_s,
        "delay_evidence_hash": sha256_file(args.delay_evidence) if args.delay_evidence else None,
        "seed": None,
        "n_runs": len(settings),
        "artefacts": {
            str(path.relative_to(output)): sha256_file(path)
            for path in sorted(output.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        },
        "evidence_label": "SELFTEST DIAGNOSTIC - NOT PARTICIPANT RESULTS"
        if args.selftest
        else "PARTICIPANT MEASUREMENT",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {"output": str(output), "runs": len(settings), "evidence_label": manifest["evidence_label"]}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
