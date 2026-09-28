"""Phase 18 frozen-inputs locks (pre-registration §0): build, validate, archive, or print a template.

    python scripts/confirmatory_lock.py template --kind offline|live      # skeleton; PENDING fields
    python scripts/confirmatory_lock.py validate <lock.json>              # schema + semantic check
    python scripts/confirmatory_lock.py archive <lock.json>               # append its digest to the
                                                                           # tracked hash record
    python scripts/confirmatory_lock.py build-rehearsal --executor-model M --executor-effort E

A **participant** lock (``evidence: PARTICIPANT``) is assembled once the upstream values exist:

* ``ds-v1.0``, ``W``, ``Δ_proc``, the owner budgets, the operating-point selection files and the
  shipped model packages;
* the Phase 18 live pilot, for a live lock.

``archive`` refuses it while any field is missing or ``PENDING``, while the pre-registration is not
the latest archived version, or while the tree is dirty.

``build-rehearsal`` makes a **SYNTHETIC rehearsal** lock on the Phase 11 kinematic fixture. It:

1. uses 12 identities, so the test roster holds 3;
2. trains a fold-0 GRU and GBDT with the unchanged Phase 10 / 09 code;
3. picks every arm's operating point on the fold-0 validation identities with
   ``eval.selection.select_point`` under the development budget, at the development ``Δ_proc``;
4. writes the lock, and archives it in a run-local *copy* of the hash record.

It is machinery only: the tracked record never lists a rehearsal lock.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from _p10 import hardware, provenance, train_and_export, write_json
from _p11_fixture import kinematic_fixture
from _p18 import (
    CURVE_PROBABILITIES,
    CURVE_TAUS,
    PREREG_DOC,
    PREREG_PATH,
    RECORD_PATH,
    REHEARSAL,
    REHEARSAL_NOTE,
    ROOT,
    add_executor_args,
    build_arm,
    evaluate_arm_session,
    evidence,
    harness_sources,
    pipeline_sources,
    point,
)
from _runlog import git_dirty, git_sha

from spacedrums.commit import CommitSettings
from spacedrums.data.feature_dataset import export_folds
from spacedrums.eval.constants import HARNESS_VERSION
from spacedrums.eval.selection import select_point
from spacedrums.features.windows import WindowParams
from spacedrums.live_eval.counterbalance import arm_sequences
from spacedrums.live_eval.prereg import (
    PreregError,
    archive_lock,
    file_digest,
    lock_errors,
    verify_document,
)
from spacedrums.live_eval.protocol import LIVE_PROTOCOL_ID, LIVE_PROTOCOL_VERSION
from spacedrums.models.gbdt.train import train_fold as train_gbdt_fold
from spacedrums.models.temporal.config import TemporalConfig
from spacedrums.models.temporal.train import TrainConfig
from spacedrums.timing import wall_clock_iso

P = "PENDING"


def template(kind: str) -> dict[str, Any]:
    """Every field a lock needs; ``PENDING`` marks what upstream phases must supply."""
    prov = {"source": P, "decided_by": P, "date": P, "rationale": P}
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "lock_kind": kind,
        "evidence": "PARTICIPANT",
        "created_at": P,
        "created_by": P,
        "git_sha": P,
        "git_dirty": False,
        "prereg": {"path": PREREG_DOC, "version": P, "sha256": P},
        "notes": P,
    }
    controls = {"tti_commit_s": P, "p_commit": P, "n_confirm_frames": P, "v_min": P, "refractory_zone_s": P}
    op = {"feasible": P, "selection_path": P, "selection_sha256": P, "validation": P}
    model = {
        "kind": P,
        "path": P,
        "manifest_sha256": P,
        "export_sha256": P,
        "norm_stats_path": P,
        "norm_stats_sha256": P,
        "fold": P,
    }
    if kind == "offline":
        base["offline"] = {
            "dataset": {
                "version": "ds-v1.0 (PENDING)",
                "kind": "PARTICIPANT",
                "manifest_path": P,
                "manifest_sha256": P,
                "labels_version": P,
                "split_path": P,
                "split_sha256": P,
                "test_participants": [P],
                "p_test": P,
                "sessions": [{"session_id": P, "participant_id": P}],
            },
            "harness": {"version": P, "source_sha256": {P: P}},
            "sources": {P: P},
            "matching": {"rule": "ADR-0023", "w_primary_s": P, "provenance": prov},
            "delay": {"primary_s": {P: P}, "appendix_s": 0, "provenance": prov},
            "budgets": {
                "fp_budget_per_min": P,
                "fn_ceiling": P,
                "delta_audio_s": P,
                "delta_te_s": P,
                "delta_lead_s": P,
                "cpu_p95_ms": P,
                "provenance": prov,
            },
            "acoustic": {"status": P, "s_phys_s": P, "source": P},
            "arms": [
                {
                    "arm_id": "A",
                    "role": "reference",
                    "replay_arm": "A",
                    "controls": controls,
                    "rule": None,
                    "model": None,
                    "operating_point": op,
                },
                {
                    "arm_id": "B-CV",
                    "role": "baseline",
                    "replay_arm": "B",
                    "controls": controls,
                    "rule": {"motion_model": "CV", "K": P},
                    "model": None,
                    "operating_point": op,
                },
                {
                    "arm_id": "B-CA",
                    "role": "baseline",
                    "replay_arm": "B",
                    "controls": controls,
                    "rule": {"motion_model": "CA", "K": P},
                    "model": None,
                    "operating_point": op,
                },
                {
                    "arm_id": "C-GBDT-direct",
                    "role": "baseline",
                    "replay_arm": "MODEL:C-GBDT",
                    "controls": controls,
                    "rule": None,
                    "model": {**model, "kind": "gbdt", "mode": "direct"},
                    "operating_point": op,
                },
                {
                    "arm_id": "C-GBDT-traj",
                    "role": "baseline",
                    "replay_arm": "MODEL:C-GBDT",
                    "controls": controls,
                    "rule": None,
                    "model": {**model, "kind": "gbdt", "mode": "trajectory"},
                    "operating_point": op,
                },
                {
                    "arm_id": "C",
                    "role": "primary",
                    "replay_arm": P,
                    "controls": controls,
                    "rule": None,
                    "model": model,
                    "operating_point": op,
                },
            ],
            "b_primary": P,
            "c_primary": "C",
            "curves": {"tau_commit_s": list(CURVE_TAUS), "p_commit": list(CURVE_PROBABILITIES)},
            "statistics": {"repeats": 10000, "seed": 18, "level": 0.95},
        }
    else:
        method = {"status": P, "u_s": P, "report": "docs/reports/phase-18-external-methods.md"}
        base["live"] = {
            "offline_lock_path": P,
            "offline_lock_sha256": P,
            "offline_config_path": P,
            "offline_config_sha256": P,
            "config_path": P,
            "config_sha256": P,
            "model": model,
            "arms": {"A": "A", "B": P, "C": "C"},
            "design": {"rule": "Williams-3", "sequences": [list(s) for s in arm_sequences()]},
            "protocol": {
                "protocol_id": LIVE_PROTOCOL_ID,
                "version": LIVE_PROTOCOL_VERSION,
                "duration_scale": 1.0,
            },
            "methods": {
                "M1": method,
                "M2": dict(method),
                "M3": {"status": "ESTIMATE_ONLY", "output_latency_run_id": P},
            },
            "primary_method": P,
            "questionnaire_included": P,
        }
    return base


# ----------------------------------------------------------------------------- rehearsal


def _base_controls(cfg) -> dict[str, Any]:
    cs = CommitSettings.from_config(cfg)
    return {
        "tti_commit_s": cs.tti_commit_s,
        "p_commit": cs.p_commit,
        "n_confirm_frames": cs.n_confirm_frames,
        "v_min": float(cfg["geometry"]["v_min"]),
        "refractory_zone_s": cs.refractory_zone_s,
    }


def _candidates(cfg) -> dict[str, dict[str, Any]]:
    """Development candidate grids (ADR-0024 / Phase 10 forms, reduced for the rehearsal)."""
    base = _base_controls(cfg)
    b_grid = [
        ({"motion_model": m, "K": k}, {**base, "tti_commit_s": t, "p_commit": p, "n_confirm_frames": nc})
        for m in ("CV",)
        for k, t, p, nc in itertools.product((3, 6), (0.05, 0.10), (0.3, 0.5), (0, 2))
    ]
    return {
        "A": {"replay_arm": "A", "role": "reference", "grid": [(None, base)]},
        "B-CV": {"replay_arm": "B", "role": "baseline", "grid": b_grid},
        "B-CA": {
            "replay_arm": "B",
            "role": "baseline",
            "grid": [({**r, "motion_model": "CA"}, c) for r, c in b_grid],
        },
        "C-GBDT-direct": {
            "replay_arm": "MODEL:C-GBDT",
            "role": "baseline",
            "grid": [
                (None, {**base, "tti_commit_s": t, "p_commit": p, "n_confirm_frames": 0})
                for t, p in itertools.product((0.05, 0.10), (0.3, 0.5, 0.7))
            ],
        },
        "C-GBDT-traj": {
            "replay_arm": "MODEL:C-GBDT",
            "role": "baseline",
            "grid": [
                (None, {**base, "tti_commit_s": t, "p_commit": 0.0, "n_confirm_frames": 0})
                for t in (0.02, 0.05, 0.10)
            ],
        },
        "C-GRU": {
            "replay_arm": "MODEL:C-GRU",
            "role": "primary",
            "grid": [
                (None, {**base, "tti_commit_s": t, "p_commit": 0.0, "n_confirm_frames": nc})
                for t, nc in itertools.product((0.02, 0.05, 0.10), (0, 2))
            ],
        },
    }


def build_rehearsal(args: argparse.Namespace) -> int:
    check = verify_document(PREREG_PATH, RECORD_PATH, document=PREREG_DOC)
    if not check["ok"]:
        print(f"[lock] pre-registration not verified: {check['reason']}")
        return 2
    R = REHEARSAL
    with evidence(
        args,
        slug="rehearsal-lock",
        task="18.1",
        description="SYNTHETIC rehearsal frozen-inputs lock: fixture models, validation picks "
        "(machinery only)",
        output=args.output,
    ) as (run, cfg):
        dataset, cv, sessions = kinematic_fixture(cfg, identities=R["identities"], seconds=R["seconds"])
        ds = {**dataset, "split_hash": cv["split_hash"]}
        horizon = R["k"] / 30
        params = WindowParams(R["n"], math.ceil(horizon / 0.025) + 1, horizon, 0.3, 1, 0)
        export_folds(ds, cv, sessions, run.dir / "features", params)
        fold = cv["folds"][R["fold"]]
        fold_dir = run.dir / "features" / f"fold-{fold['fold']}"
        context = {**provenance(), "hardware": hardware()}
        context["codex_model"], context["codex_reasoning_effort"] = args.executor_model, args.executor_effort
        schema = sessions[0].schema
        gru_dir = run.dir / "models" / "c-gru"  # train_fold creates it (and refuses an existing one)
        _, gru_manifest, _, gru_val = train_and_export(
            fold_dir,
            gru_dir,
            TemporalConfig("gru", schema.dimension, n=R["n"], k=R["k"], hidden=R["hidden"]),
            TrainConfig(seed=R["train_seed"], epochs=R["epochs"], patience=R["epochs"]),
            context=context,
        )
        gbdt_dir = run.dir / "models" / "c-gbdt"
        gbdt_dir.mkdir(parents=True)
        train_gbdt_fold(fold_dir, gbdt_dir, seed=R["gbdt_seed"])
        rel = lambda p: Path(p).relative_to(ROOT).as_posix()  # noqa: E731
        stats_path = fold_dir / "norm_stats.json"
        lock_dataset = {
            "version": dataset["dataset_version"],
            "kind": "SELFTEST",
            "manifest_sha256": dataset["manifest_hash"],
            "labels_version": "labels-v1.0 (SYNTHETIC fixture targets)",
            "split_sha256": cv["split_hash"],
            "test_participants": sorted(cv["test_participants"]),
            "p_test": len(cv["test_participants"]),
            "sessions": [
                {
                    "session_id": s.table.session_id,
                    "participant_id": s.table.participant,
                    "lighting_id": None,
                    "distance_mark": None,
                }
                for s in sessions
                if s.table.participant in cv["test_participants"]
            ],
            "fixture": {
                "generator": "scripts/_p11_fixture.kinematic_fixture",
                "identities": R["identities"],
                "seconds": R["seconds"],
                "seed": 1100,
            },
        }
        models = {
            "C-GBDT-direct": {
                "kind": "gbdt",
                "path": rel(gbdt_dir),
                "manifest_sha256": file_digest(gbdt_dir / "manifest.json"),
                "norm_stats_path": rel(stats_path),
                "norm_stats_sha256": file_digest(stats_path),
                "fold": fold["fold"],
                "mode": "direct",
            },
            "C-GRU": {
                "kind": "temporal",
                "path": rel(gru_dir),
                "manifest_sha256": file_digest(gru_dir / "manifest.json"),
                "export_sha256": file_digest(gru_dir / "export.pt"),
                "norm_stats_path": rel(stats_path),
                "norm_stats_sha256": file_digest(stats_path),
                "fold": fold["fold"],
                "window_n": R["n"],
            },
        }
        models["C-GBDT-traj"] = {**models["C-GBDT-direct"], "mode": "trajectory"}
        val_sessions = [s for s in sessions if s.table.participant in fold["val_participants"]]
        arms, selections = [], {}
        for arm_id, cand in _candidates(cfg).items():
            points = []
            for rule, controls in cand["grid"]:
                spec = {
                    "arm_id": arm_id,
                    "replay_arm": cand["replay_arm"],
                    "controls": controls,
                    "rule": rule,
                    "model": models.get(arm_id),
                }
                arm = build_arm(spec, cfg, dataset=lock_dataset, schema=schema)
                evaluated = [
                    evaluate_arm_session(arm, s, delay_s=R["delta_proc_s"], w_s=R["w_s"])
                    for s in val_sessions
                ]
                points.append(point(evaluated, {"rule": rule, **controls}))
            choice = select_point(points, fp_budget=R["fp_budget_per_min"], fn_ceiling=R["fn_ceiling"])
            if arm_id == "A":
                choice = {
                    "feasible": True,
                    "point": points[0],
                    "reason": "reference: Phase 05 settings, no selection",
                }
            selection = {
                "arm_id": arm_id,
                "validation_participants": fold["val_participants"],
                "fold": fold["fold"],
                "delta_proc_s": R["delta_proc_s"],
                "w_s": R["w_s"],
                "budget": {k: R[k] for k in ("fp_budget_per_min", "fn_ceiling")},
                "points": points,
                "choice": choice,
                "evidence": "SYNTHETIC development selection",
            }
            sel_path = run.dir / "selections" / f"{arm_id}.json"
            write_json(sel_path, selection)
            chosen = choice["point"] or {**points[0], "diagnostic": "no point with matched validation events"}
            settings = dict(chosen["settings"])
            rule = settings.pop("rule")
            arms.append(
                {
                    "arm_id": arm_id,
                    "role": cand["role"],
                    "replay_arm": cand["replay_arm"],
                    "controls": settings,
                    "rule": rule,
                    "model": models.get(arm_id),
                    "operating_point": {
                        "feasible": bool(choice["feasible"]),
                        "selection_path": rel(sel_path),
                        "selection_sha256": file_digest(sel_path),
                        "validation": {
                            k: chosen[k]
                            for k in (
                                "median_lead_s",
                                "fp_per_min",
                                "fn_rate",
                                "timing_mae_s",
                                "zone_accuracy",
                                "matched",
                                "fp",
                                "fn",
                            )
                        },
                    },
                    "inference_latency": json.loads((gru_dir / "latency.json").read_text(encoding="utf-8"))
                    if arm_id == "C-GRU"
                    else None,
                }
            )
            selections[arm_id] = choice
            print(f"[lock] {arm_id}: feasible={choice['feasible']} settings={chosen['settings']}", flush=True)
        b_options = [a for a in arms if a["arm_id"] in ("B-CV", "B-CA") and a["operating_point"]["feasible"]]
        b_primary = (
            min(
                b_options,
                key=lambda a: (
                    -(a["operating_point"]["validation"]["median_lead_s"] or -1e9),
                    a["operating_point"]["validation"]["fp_per_min"],
                    a["arm_id"] != "B-CV",
                ),
            )["arm_id"]
            if b_options
            else "B-CV"
        )
        today = wall_clock_iso()[:10]
        dev = {
            "source": "SYNTHETIC development constant (scripts/_p18.py REHEARSAL)",
            "decided_by": "Phase 18 rehearsal (not the owner)",
            "date": today,
        }
        lock = {
            "schema_version": "1.0",
            "lock_kind": "offline",
            "evidence": "SYNTHETIC_REHEARSAL",
            "created_at": wall_clock_iso(),
            "created_by": args.executor_model,
            "git_sha": git_sha(),
            "git_dirty": git_dirty(),
            "prereg": {"path": PREREG_DOC, "version": check["version"], "sha256": check["sha256"]},
            "notes": REHEARSAL_NOTE,
            "offline": {
                "dataset": lock_dataset,
                "harness": {"version": HARNESS_VERSION, "source_sha256": harness_sources()},
                "sources": pipeline_sources(),
                "matching": {
                    "rule": "ADR-0023",
                    "w_primary_s": R["w_s"],
                    "provenance": {**dev, "source": "W_CANDIDATE_DEFAULT_S (ADR-0023 rule not applied)"},
                },
                "delay": {
                    "primary_s": {a["arm_id"]: R["delta_proc_s"] for a in arms},
                    "appendix_s": 0,
                    "provenance": dev,
                },
                "budgets": {
                    "fp_budget_per_min": R["fp_budget_per_min"],
                    "fn_ceiling": R["fn_ceiling"],
                    "delta_audio_s": R["delta_audio_s"],
                    "delta_te_s": R["delta_audio_s"],
                    "delta_lead_s": R["delta_lead_s"],
                    "cpu_p95_ms": R["cpu_p95_ms"],
                    "provenance": dev,
                },
                "acoustic": {
                    "status": "NOT_MEASURED",
                    "s_phys_s": None,
                    "source": "docs/reports/phase-07-acoustic-validation.md (not validated)",
                },
                "arms": arms,
                "b_primary": b_primary,
                "c_primary": "C-GRU",
                "curves": {"tau_commit_s": list(CURVE_TAUS), "p_commit": list(CURVE_PROBABILITIES)},
                "statistics": {"repeats": 10000, "seed": 18, "level": 0.95},
            },
        }
        errs = lock_errors(lock)
        if errs:
            raise ValueError("rehearsal lock invalid: " + "; ".join(errs))
        lock_path = run.dir / "lock.json"
        write_json(lock_path, lock)
        record = run.dir / "rehearsal-record.json"
        shutil.copyfile(RECORD_PATH, record)
        entry = archive_lock(
            lock_path,
            record,
            document=PREREG_DOC,
            doc_path=PREREG_PATH,
            archived_at=wall_clock_iso(),
            git_head=git_sha(),
        )
        write_json(
            run.dir / "summary.json",
            {
                "evidence": "SYNTHETIC rehearsal (machinery only)",
                "lock": str(lock_path),
                "record": str(record),
                "archived": entry,
                "window_params": asdict(params),
                "gru_validation": gru_val.get("participant_macro_ade") if isinstance(gru_val, dict) else None,
                "gru_manifest_hash": gru_manifest.get("export_hash"),
                "selections": {
                    k: {"feasible": v["feasible"], "reason": v.get("reason")} for k, v in selections.items()
                },
                "b_primary": b_primary,
            },
        )
        print(f"[lock] rehearsal lock {lock_path} archived in {record}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    t = sub.add_parser("template")
    t.add_argument("--kind", choices=("offline", "live"), required=True)
    t.add_argument("--output", type=Path)
    v = sub.add_parser("validate")
    v.add_argument("lock", type=Path)
    a = sub.add_parser("archive")
    a.add_argument("lock", type=Path)
    b = sub.add_parser("build-rehearsal")
    b.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-18")
    add_executor_args(b)
    args = ap.parse_args()
    if args.command == "template":
        text = json.dumps(template(args.kind), indent=2) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(text)
        return 0
    if args.command == "validate":
        errs = lock_errors(json.loads(args.lock.read_text(encoding="utf-8")))
        print("\n".join(errs) if errs else "lock valid (archivable)")
        return 1 if errs else 0
    if args.command == "archive":
        lock = json.loads(args.lock.read_text(encoding="utf-8"))
        if lock.get("evidence") != "PARTICIPANT":
            print("[lock] only PARTICIPANT locks enter the tracked hash record")
            return 2
        if git_dirty():
            print("[lock] archive a participant lock from the owner-committed (clean) tree")
            return 2
        try:
            entry = archive_lock(
                args.lock,
                RECORD_PATH,
                document=PREREG_DOC,
                doc_path=PREREG_PATH,
                archived_at=wall_clock_iso(),
                git_head=git_sha(),
                require_approval=True,
            )
        except PreregError as exc:
            print(f"[lock] refused: {exc}")
            return 2
        print(json.dumps(entry, indent=2))
        return 0
    return build_rehearsal(args)


if __name__ == "__main__":
    raise SystemExit(main())
