"""Phase 18 Task 18.2: Experiment 1, the offline confirmatory run (held-out participants, **once**).

    python scripts/run_offline_confirmatory.py --lock docs/experiments/phase-18-lock-offline.json \
        --require-clean --executor-model "<actual>" --executor-effort "<actual>"      # PARTICIPANT (PENDING)
    python scripts/run_offline_confirmatory.py --rehearsal --lock <run>/lock.json \
        --record <run>/rehearsal-record.json --executor-model M --executor-effort E   # SYNTHETIC rehearsal

Order (pre-registration §4.4 and §11). Any refusal happens before test data is read.

1. The lock is valid, archived after the latest archived pre-registration version, and names that
   version. A participant lock also needs ``--require-clean`` and a clean tree.
2. Every locked pipeline source (``eval``, ``live_eval``, ``geometry``, ``commit``, ``prediction``,
   ``models``, ``features``) still has its locked digest.
3. The ledger reserves the run: the tracked ledger for participant data, a run-local one for a
   rehearsal. A second participant execution for the same lock is refused unless a reviewed
   ``--retry-after-review`` reason is given.
4. Self-checks: ``pytest tests/eval`` and ``pytest tests/live_eval`` pass; TEST-CAUSAL-1 on every
   locked arm, with its exact settings and model, on two SYNTHETIC fixture sessions. A failure
   aborts the run, and the ledger keeps the ABORTED entry.
5. The held-out sessions of the locked roster are loaded. A rehearsal regenerates the fixture and
   checks its manifest and split digests; participant data goes through ``load_dataset``.
6. Every arm runs at the primary ``Δ_proc`` (with S1) and at ``Δ_proc = 0``, then the declared
   curve sweep. Per-participant, pooled and stratified metrics, trajectory error and the
   hypotheses follow. ``results.json`` and the per-session harness records are written, then the
   report (tables and figures) through ``_p18_report.render``.

Nothing is tuned here: every setting comes from the lock.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from _p10 import write_json
from _p11_fixture import kinematic_fixture
from _p18 import (
    LEDGER_PATH,
    PREREG_DOC,
    PREREG_PATH,
    RECORD_PATH,
    ROOT,
    add_executor_args,
    build_arm,
    curve_grid,
    evaluate_arm_session,
    evidence,
    point,
    read_json,
)
from _p18_report import render
from _runlog import git_dirty, git_sha

from spacedrums.eval.report import write_result
from spacedrums.features.batch import build_features
from spacedrums.features.schema import FeatureSchema
from spacedrums.live_eval import hypotheses as hyp
from spacedrums.live_eval import offline
from spacedrums.live_eval.causality import causal_check
from spacedrums.live_eval.prereg import Ledger, PreregError, file_digest, verify_lock
from spacedrums.live_eval.stats import bootstrap_paired
from spacedrums.timing import wall_clock_iso

CAUSAL_MAX_CUTS = 40
CAUSAL_FIXTURE = {"identities": 2, "seconds": 8.0, "seed": 1800}
PAIRED_METRICS = ("lead_median_s", "fp_per_min", "fn_rate", "te_pred_mae_s", "zone_accuracy")


def frozen_source_mismatches(lock: dict[str, Any]) -> list[str]:
    off = lock["offline"]
    expected = {**off["sources"], **off["harness"]["source_sha256"]}
    bad = [p for p, d in sorted(expected.items()) if not (ROOT / p).exists() or file_digest(ROOT / p) != d]
    # The inventory also freezes configuration files. Only Python package paths
    # participate in the scan for source files added after the lock.
    locked_pkgs = {
        parts[2]
        for p in off["sources"]
        if len(parts := Path(p).parts) >= 4 and parts[:2] == ("src", "spacedrums")
    }
    current = {
        p.relative_to(ROOT).as_posix()
        for pkg in locked_pkgs
        for p in (ROOT / "src" / "spacedrums" / pkg).rglob("*.py")
    }
    bad += [f"{p} (added after the lock)" for p in sorted(current - set(off["sources"]))]
    return bad


def pytest_checks() -> list[dict[str, Any]]:
    out = []
    for target in ("tests/eval", "tests/live_eval"):
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "-p", "no:cacheprovider", target],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        tail = [line for line in proc.stdout.strip().splitlines() if line.strip()][-1:] or [""]
        out.append({"target": target, "exit_code": proc.returncode, "summary": tail[0]})
    return out


def causality_checks(lock: dict[str, Any], cfg: Any, arms: dict[str, Any]) -> dict[str, Any]:
    _, _, fixture = kinematic_fixture(cfg, **CAUSAL_FIXTURE)
    reports = {}
    for arm_id, arm in arms.items():
        delay = float(lock["offline"]["delay"]["primary_s"][arm_id])
        per_session = []
        for i, session in enumerate(fixture):
            donor = fixture[1 - i].tracks
            schema, sid = session.schema, session.table.session_id

            def run_arm(tracks, arm=arm, schema=schema, sid=sid, delay=delay):
                features = build_features(list(tracks), schema) if arm.is_model else None
                return arm.run(tracks, session_id=sid, schema=schema, delay_s=delay, feature_records=features)

            per_session.append(
                {
                    "session_id": sid,
                    **causal_check(
                        run_arm,
                        session.tracks,
                        donor=donor,
                        tolerance=1e-6 if arm.is_model else 0.0,
                        max_cuts=CAUSAL_MAX_CUTS,
                    ),
                }
            )
        reports[arm_id] = {
            "passed": all(r["passed"] for r in per_session),
            "sessions": per_session,
            "evidence": "SYNTHETIC fixture sessions (never test data)",
        }
        print(f"[confirm] TEST-CAUSAL-1 {arm_id}: passed={reports[arm_id]['passed']}", flush=True)
    return reports


def load_test_sessions(lock: dict[str, Any], cfg: Any) -> list[Any]:
    ds = lock["offline"]["dataset"]
    if ds["kind"] == "SELFTEST":
        fx = ds["fixture"]
        dataset, cv, sessions = kinematic_fixture(
            cfg, identities=fx["identities"], seconds=fx["seconds"], seed=fx["seed"]
        )
        if dataset["manifest_hash"] != ds["manifest_sha256"] or cv["split_hash"] != ds["split_sha256"]:
            raise ValueError("regenerated fixture differs from the locked manifest / split")
        if sorted(cv["test_participants"]) != sorted(ds["test_participants"]):
            raise ValueError("regenerated test roster differs from the lock")
    else:
        from spacedrums.data.feature_dataset import load_dataset

        manifest, cv, sessions = load_dataset(ROOT / ds["manifest_path"], ROOT / ds["split_path"])
        if (
            file_digest(ROOT / ds["manifest_path"]) != ds["manifest_sha256"]
            or cv["split_hash"] != ds["split_sha256"]
        ):
            raise ValueError("dataset manifest / split differs from the lock")
    test = [s for s in sessions if s.table.participant in set(ds["test_participants"])]
    locked = {(s["session_id"], s["participant_id"]) for s in ds["sessions"]}
    if {(s.table.session_id, s.table.participant) for s in test} != locked:
        raise ValueError("held-out sessions differ from the locked session list")
    return sorted(test, key=lambda s: s.table.session_id)


def _trajectory(evaluated: list[dict[str, Any]], sessions: list[Any]) -> dict[str, Any]:
    tracks = {s.table.session_id: s.tracks for s in sessions}
    per = [offline.trajectory_errors(e["result"].predictions, tracks[e["session_id"]]) for e in evaluated]
    pts = sum(r["valid_points"] for r in per)
    seqs = sum(r["valid_sequences"] for r in per)
    if not pts:
        return {"ade": None, "fde": None, "valid_points": 0, "valid_sequences": 0}
    return {
        "ade": sum((r["ade"] or 0) * r["valid_points"] for r in per) / pts,
        "fde": sum((r["fde"] or 0) * r["valid_sequences"] for r in per) / seqs if seqs else None,
        "valid_points": pts,
        "valid_sequences": seqs,
        "predictions": sum(r["predictions"] for r in per),
        "target": "future causal tracker output (Phase 08 target semantics); not the physical tip",
    }


def _strip(evaluated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in e.items() if k not in ("result", "s1")} for e in evaluated]


def confirmatory(
    lock: dict[str, Any], cfg: Any, sessions: list[Any], arms: dict[str, Any], out: Path
) -> dict[str, Any]:
    off = lock["offline"]
    w = float(off["matching"]["w_primary_s"])
    edges = offline.speed_tercile_edges(g for s in sessions for g in s.labels)
    levels = {
        s["session_id"]: {"lighting_id": s.get("lighting_id"), "distance_mark": s.get("distance_mark")}
        for s in off["dataset"]["sessions"]
    }
    per_arm: dict[str, Any] = {}
    for spec in off["arms"]:
        arm_id = spec["arm_id"]
        arm = arms[arm_id]
        delay = float(off["delay"]["primary_s"][arm_id])
        primary = [
            evaluate_arm_session(arm, s, delay_s=delay, w_s=w, s1=True, keep_result=True) for s in sessions
        ]
        zero = [evaluate_arm_session(arm, s, delay_s=0.0, w_s=w) for s in sessions]
        for e in primary:
            write_result(out / "sessions" / arm_id / "primary" / e["session_id"], e["evaluation"])
            write_result(out / "sessions" / arm_id / "s1" / e["session_id"], e["s1"]["evaluation"])
        for e in zero:
            write_result(out / "sessions" / arm_id / "zero" / e["session_id"], e["evaluation"])
        curve = []
        for controls in curve_grid(spec):
            evaluated = (
                _strip(primary)
                if controls == spec["controls"]
                else [evaluate_arm_session(arm, s, delay_s=delay, w_s=w, controls=controls) for s in sessions]
            )
            curve.append(
                {**point(evaluated, {"arm": arm_id, **controls}), "frozen": controls == spec["controls"]}
            )
        s1 = [e["s1"] for e in primary]
        per_arm[arm_id] = {
            "spec": {
                k: spec[k] for k in ("arm_id", "role", "replay_arm", "controls", "rule", "operating_point")
            },
            "delay_primary_s": delay,
            "primary": {
                "per_participant": offline.participant_metrics(primary),
                "pooled": offline.pooled_metrics(primary),
                "strata": offline.strata(primary, speed_edges=edges, session_levels=levels),
                "trajectory": _trajectory(primary, sessions) if spec["replay_arm"] != "A" else None,
            },
            "s1": {"per_participant": offline.participant_metrics(s1), "pooled": offline.pooled_metrics(s1)},
            "zero_delay": {
                "per_participant": offline.participant_metrics(zero),
                "pooled": offline.pooled_metrics(zero),
            },
            "curve": curve,
            "events": offline.event_summary(primary),
            "validation": spec["operating_point"]["validation"],
            "inference_latency": spec.get("inference_latency"),
        }
        pooled = per_arm[arm_id]["primary"]["pooled"]
        print(
            f"[confirm] {arm_id}: matched={pooled['matched']} fp={pooled['fp']} fn={pooled['fn']} "
            f"lead_median={pooled['lead_median_s']}",
            flush=True,
        )
    a_id = next(s["arm_id"] for s in off["arms"] if s["replay_arm"] == "A")
    decisions = hypothesis_block(off, per_arm, a_id, "primary")
    sensitivity = hypothesis_block(off, per_arm, a_id, "s1")
    boot = {k: off["statistics"][k] for k in ("repeats", "seed", "level")}
    paired = {}
    for x, y in ((off["c_primary"], off["b_primary"]), (off["c_primary"], a_id), (off["b_primary"], a_id)):
        px, py = per_arm[x]["primary"]["per_participant"], per_arm[y]["primary"]["per_participant"]
        paired[f"{x} - {y}"] = {
            m: bootstrap_paired({p: v[m] for p, v in px.items()}, {p: v[m] for p, v in py.items()}, **boot)
            for m in PAIRED_METRICS
        }
    return {
        "evidence": lock["evidence"],
        "label": "SYNTHETIC REHEARSAL (machinery only; never evidence)"
        if lock["evidence"] == "SYNTHETIC_REHEARSAL"
        else "PARTICIPANT (held-out test participants; confirmatory, run once)",
        "dataset": {k: off["dataset"][k] for k in ("version", "kind", "test_participants", "p_test")},
        "sessions": [s.table.session_id for s in sessions],
        "w_primary_s": w,
        "speed_tercile_edges": edges,
        "budgets": off["budgets"],
        "b_primary": off["b_primary"],
        "c_primary": off["c_primary"],
        "a_arm": a_id,
        "arms": per_arm,
        "hypotheses": decisions,
        "sensitivity_s1": sensitivity,
        "paired": paired,
    }


def hypothesis_block(
    off: dict[str, Any], per_arm: dict[str, Any], a_id: str, which: str
) -> list[dict[str, Any]]:
    c, b = off["c_primary"], off["b_primary"]
    boot = {k: off["statistics"][k] for k in ("repeats", "seed", "level")}
    feasible = {s["arm_id"]: s["operating_point"]["feasible"] for s in off["arms"]}

    def col(arm_id: str, metric: str) -> dict[str, Any]:
        return {p: m[metric] for p, m in per_arm[arm_id][which]["per_participant"].items()}

    budgets = off["budgets"]
    return [
        hyp.h1a(col(c, "lead_median_s"), c_feasible=feasible[c], **boot),
        hyp.h1b(col(c, "lead_median_s"), col(a_id, "lead_median_s"), c_feasible=feasible[c], **boot),
        hyp.cb(
            col(c, "lead_median_s"),
            col(b, "lead_median_s"),
            delta_lead=budgets["delta_lead_s"],
            c_feasible=feasible[c],
            b_feasible=feasible[b],
            **boot,
        ),
        hyp.h2(
            col(c, "fp"),
            col(c, "active_time_s"),
            fp_budget_per_min=budgets["fp_budget_per_min"],
            c_feasible=feasible[c],
            **boot,
        ),
        hyp.h3(col(c, "te_pred_mae_s"), delta_te_s=budgets["delta_te_s"], c_feasible=feasible[c], **boot),
        hyp.pending("H4", "Experiment 2 (live): decided by scripts/analyze_live.py"),
        hyp.pending("H4-B", "Experiment 2 (live): decided by scripts/analyze_live.py"),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lock", type=Path, required=True)
    ap.add_argument("--record", type=Path, default=RECORD_PATH)
    ap.add_argument("--rehearsal", action="store_true", help="required for a SYNTHETIC_REHEARSAL lock")
    ap.add_argument("--require-clean", action="store_true", help="required for a PARTICIPANT lock")
    ap.add_argument("--retry-after-review", default=None, help="reviewed reason for a repeat (recorded)")
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-18")
    add_executor_args(ap)
    args = ap.parse_args()
    lock = read_json(args.lock)
    participant = lock.get("evidence") == "PARTICIPANT"
    if participant == args.rehearsal:
        ap.error(
            "--rehearsal is required for a SYNTHETIC_REHEARSAL lock and forbidden for a PARTICIPANT lock"
        )
    if participant and (not args.require_clean or git_dirty()):
        ap.error("a participant confirmatory run needs --require-clean and the owner-committed clean tree")
    if participant and args.record != RECORD_PATH:
        ap.error("a participant lock is verified against the tracked hash record only")
    check = verify_lock(
        lock, args.record, document=PREREG_DOC, doc_path=PREREG_PATH, require_approval=participant
    )
    if not check["ok"]:
        print(f"[confirm] refused: {check['reason']}")
        return 2
    bad = frozen_source_mismatches(lock)
    if bad:
        print("[confirm] refused: frozen sources changed since the lock: " + ", ".join(bad[:8]))
        return 2
    with evidence(
        args,
        slug="offline-confirmatory" if participant else "offline-rehearsal",
        task="18.2",
        description=(
            "Experiment 1 confirmatory run (held-out participants)"
            if participant
            else "Experiment 1 SYNTHETIC rehearsal (machinery only)"
        ),
        output=args.output,
    ) as (run, cfg):
        ledger = Ledger(LEDGER_PATH if participant else run.dir / "ledger.jsonl")
        try:
            ledger.reserve(
                lock_sha256=check["sha256"],
                run_id=run.run_id,
                evidence=lock["evidence"],
                at=wall_clock_iso(),
                git_head=git_sha(),
                retry_reason=args.retry_after_review,
            )
        except PreregError as exc:
            print(f"[confirm] refused: {exc}")
            raise SystemExit(2) from exc
        status, detail = "FAILED", ""
        try:
            off = lock["offline"]
            schema = FeatureSchema(cfg["zones"])
            arms = {
                s["arm_id"]: build_arm(s, cfg, dataset=off["dataset"], schema=schema) for s in off["arms"]
            }
            checks = {
                "pytest": pytest_checks(),
                "causality": causality_checks(lock, cfg, arms),
                "lock": check,
                "sources": "all locked digests match",
            }
            write_json(run.dir / "self-checks.json", checks)
            if any(c["exit_code"] for c in checks["pytest"]) or not all(
                r["passed"] for r in checks["causality"].values()
            ):
                status, detail = "ABORTED", "self-checks failed before test data was read"
                print(f"[confirm] {detail}")
                raise SystemExit(1)
            sessions = load_test_sessions(lock, cfg)
            results = confirmatory(lock, cfg, sessions, arms, run.dir)
            results["self_checks"] = {
                "pytest": checks["pytest"],
                "causality": {k: {"passed": v["passed"]} for k, v in checks["causality"].items()},
            }
            results["lock"] = {
                "path": str(args.lock),
                "sha256": check["sha256"],
                "archived_at": check["archived_at"],
            }
            results["prereg"] = check["prereg"]
            results["run_id"] = run.run_id
            write_json(run.dir / "results.json", results)
            written = render(results, run.dir / "report")
            write_json(run.dir / "report-manifest.json", written)
            status, detail = "COMPLETED", f"{len(results['arms'])} arms, {len(sessions)} sessions"
        finally:
            ledger.finish(
                lock_sha256=check["sha256"],
                run_id=run.run_id,
                status=status,
                at=wall_clock_iso(),
                detail=detail,
            )
    return 0 if status == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
