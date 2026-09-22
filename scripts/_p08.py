"""Phase 08 CLI composition and provenance; no separate experiment-log implementation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from _runlog import RunLog  # noqa: E402

from spacedrums.config import load_config  # noqa: E402
from spacedrums.data.feature_dataset import (  # noqa: E402
    descriptive_stats,
    export_folds,
    load_dataset,
    load_session,
)
from spacedrums.features.windows import WindowParams, build_windows, write_samples  # noqa: E402


def main(argv=None, *, stats_only=False):
    ap = argparse.ArgumentParser(description="Build fs-v1 samples or train-only fold statistics")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest", type=Path)
    src.add_argument("--session", type=Path, help="existing DEV/SYNTHETIC diagnostic session only")
    src.add_argument("--synthetic-fixture", action="store_true", help="in-memory unit fixture; no recordings")
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--splits", type=Path)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--experiments-dir", type=Path, default=ROOT / "experiments/phase-08")
    for name in ("n", "k", "stride", "g-win"):
        ap.add_argument("--" + name, type=int, required=True)
    for name in ("h", "h-max"):
        ap.add_argument("--" + name, type=float, required=True)
    args = ap.parse_args(argv)
    params = WindowParams(args.n, args.k, args.h, args.h_max, args.stride, args.g_win)
    if args.out.exists() and any(args.out.iterdir()):
        ap.error("output directory is nonempty; preserve existing evidence and choose a new output")
    if args.session and (not args.selftest or not args.labels or stats_only):
        ap.error("single-session diagnostics require --selftest --labels; normalization requires a fold")
    if args.manifest and not args.splits:
        ap.error("--manifest requires --splits")
    # Read-only checks happen before creating any output directory or reporting success.
    if args.synthetic_fixture:
        from _p08_fixture import synthetic_fixture

        manifest, cv, sessions = synthetic_fixture(load_config(ROOT / "configs/prototype.candidate.yaml"))
        args.selftest = True
    elif args.session:
        session = load_session(args.session, args.labels, selftest=True)
        sessions = [session]
        manifest = cv = None
    else:
        manifest, cv, sessions = load_dataset(args.manifest, args.splits, selftest=args.selftest)
    schema = sessions[0].schema
    config = load_config(
        ROOT / "configs/prototype.candidate.yaml",
        ROOT / "configs/features/fs-v1.candidate.yaml",
        overrides={"zones": schema.zones_config, "features": {"window": asdict(params)}},
    )
    slug = "p08-norm-stats" if stats_only else "p08-build-features"
    if args.session:
        slug += "-" + sessions[0].table.source_kind.lower().replace("_", "")
    with RunLog(
        phase="08",
        task="08.4" if stats_only else "08.5",
        slug=slug,
        config=config,
        description="Feature extraction/targets only; no model. Evidence classes remain separate.",
        experiments_dir=args.experiments_dir,
    ) as run:
        args.out.mkdir(parents=True, exist_ok=True)
        if args.session:
            samples, count = build_windows(
                session.tracks,
                session.table.records,
                session.labels,
                session.segments,
                schema,
                params,
                participant=session.table.participant,
                session_id=session.table.session_id,
                source_kind=session.table.source_kind,
            )
            write_samples(args.out / "samples.selftest.npz", samples, schema, params)
            report = {
                "source_kind": session.table.source_kind,
                "session_id": session.table.session_id,
                "counts": count,
                "parity": session.parity,
                "normalization": "NOT FITTED: no participant fold; raw diagnostic features",
                "descriptive_scope": "single-session diagnostic; NOT participant/train-fold statistics",
                "descriptive": descriptive_stats(sessions, samples, schema),
            }
        else:
            report = {
                "dataset_version": manifest["dataset_version"],
                "folds": export_folds(manifest, cv, sessions, args.out, params, stats_only=stats_only),
                "parity": {s.table.session_id: s.parity for s in sessions},
            }
            if args.synthetic_fixture:
                run.add_artefact(ROOT / "scripts/_p08_fixture.py", "other")
                run.write_json_artefact("synthetic-split.json", cv, "other")
            else:
                run.add_artefact(args.manifest, "other")
                for name in ("test_participants.json", "cv_folds.json"):
                    run.add_artefact(args.splits / name, "other")
            if not args.selftest:
                run.record["dataset_version"] = manifest["dataset_version"]
                run.record["dataset_hash"] = manifest["manifest_hash"]
                run.record["split"] = {"scheme": cv["split_hash"], "test": cv["test_participants"]}
        for name, doc in (
            ("feature-schema.json", schema.descriptor()),
            ("report.json", report),
            ("inputs.json", {s.table.session_id: s.input_hashes for s in sessions}),
        ):
            (args.out / name).write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        for path in sorted(args.out.rglob("*")):
            if path.is_file():
                run.add_artefact(path, "other")
        run.finish(
            report,
            notes="Selftest input, when selected, is existing SYNTHETIC or DEV CAPTURE; "
            "ds-none-v0.0 means no participant dataset consumed. No participant statistics claimed. "
            "Input hashes, feature schema and window parameters are retained.",
        )
        print(json.dumps(report, indent=2))
    return 0
