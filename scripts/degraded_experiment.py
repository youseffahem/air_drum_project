"""Phase 17 Task 17.7: paired DEGRADED-commit experiment (commits in VALID only vs VALID + DEGRADED).

    python scripts/degraded_experiment.py --executor-model M --executor-effort E [--quick]

Policies (only ``commit.allow_degraded_commits`` differs; same sessions, same tracks):

    P0  VALID only (current default)          P1  VALID + DEGRADED (bridge <= g_max frames)

Evidence (all DEVELOPMENT; the participant confirmation is PENDING until ds-v1.0 exists):

(a) Phase 09 harness on the SYNTHETIC P07 labelled session (causal tracks, POSITIVE labels,
    OCCLUSION / TRACKING_INTERRUPTION segments), arms A and B: matched / FP / FN, FP by segment type.
(b) SYNTHETIC two-hand sequences with injected occlusions (2 and 3 frames: within the g_max = 3
    bridge; 6 frames: beyond it) and low-confidence intervals, during the approach, at the impact and
    during idle: FN reduction vs FP increase, FPs split into fabricated / mistimed (``_p17.fp_kind``);
    arms A, B and the development C-GRU. Plus a dense **fake-out** sweep (a stroke that stops just
    above the surface - no strike exists - occluded around the stop; every commit is fabricated).
(c) Developer captures through real perception, arms A and B active: commits added by P1 (no ground
    truth; informational only).

Decision rule, declared before the first P1 run (2026-09-26, Phase 17): P1 may become the default
only if on (a) and (b) it lowers FN **and** adds no fabricated FP (fabricated delta = 0, fake-outs
included) for every arm; otherwise the default stays P0 and the measured trade-off is recorded in
ADR-0039. Either way participant confirmation stays PENDING (Phase 18 must not rely on P1 without it).
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
from collections import defaultdict
from pathlib import Path

from _p17 import (
    MODEL_CONFIG,
    RULE_CONFIG,
    Ticker,
    add_executor_args,
    build_pipeline,
    enable_fault_injection,
    evidence,
    fp_kind,
    idle_start,
    match,
    replay_frames,
    truth_frame,
    truth_rows,
    violations_of,
)

enable_fault_injection()

from spacedrums.app import faults as F  # noqa: E402
from spacedrums.app.invariants import InvariantMonitor  # noqa: E402
from spacedrums.app.synthetic import Swing, build_sequence, scenario  # noqa: E402
from spacedrums.commit import CommitSettings  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import HandId  # noqa: E402
from spacedrums.data.feature_dataset import load_session  # noqa: E402
from spacedrums.eval.constants import W_CANDIDATE_DEFAULT_S  # noqa: E402
from spacedrums.eval.replay import replay  # noqa: E402
from spacedrums.eval.report import evaluate_session  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402
from spacedrums.prediction import RuleSettings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICIES = {"P0": False, "P1": True}
SETUPS = {
    "A": {"config": RULE_CONFIG, "active": "A", "shadows": ("B",)},
    "B": {"config": RULE_CONFIG, "active": "B", "shadows": ("A",)},
    "C-GRU": {"config": MODEL_CONFIG, "active": "C-GRU", "shadows": ("A", "B")},
}
SEQUENCES = (
    ("single", {"t_down": 0.2}),
    ("repeated", {"t_down": 0.2}),
    ("alternating_two_zones", {"t_down": 0.2}),
    ("repeated", {"t_down": 0.12, "noise": 0.003, "seed": 1}),
)


def with_policy(data, allow):
    d = copy.deepcopy(data)
    d["commit"]["allow_degraded_commits"] = bool(allow)
    return d


# ----------------------------------------------------------------------------- (a) harness


def harness_part():
    session_dir = ROOT / "data/raw/SYNTHETIC/synthetic-p07-labels"
    label_dir = ROOT / "data/labels/synthetic-p07-labels"
    if not session_dir.exists():
        return {"status": "PENDING: SYNTHETIC P07 session not present"}
    session = load_session(session_dir, label_dir, selftest=True)
    cfg = load_config(session_dir / "config.snapshot.yaml")
    registry = ZoneRegistry.from_config(cfg["zones"])
    base = CommitSettings.from_config(cfg)
    frames = [json.loads(line) for line in (session_dir / "frames.jsonl").read_text().splitlines()]
    drops = {row["frame_id"]: row["dropped_since_last"] for row in frames}
    status = {(t.frame_id, str(t.hand_id)): str(t.status) for t in session.tracks}
    out = {}
    for arm in ("A", "B"):
        for name, allow in POLICIES.items():
            result = replay(
                session.tracks,
                arm=arm,
                registry=registry,
                commit_settings=dataclasses.replace(base, allow_degraded_commits=allow),
                v_min=cfg["geometry"]["v_min"],
                session_id=session.table.session_id,
                rule_settings=RuleSettings.from_config(cfg) if arm == "B" else None,
                dropped_by_frame=drops,
            )
            evaluated = evaluate_session(
                result.strike_rows(session.table.session_id, session.table.participant),
                session.labels,
                session.segments,
                w_s=W_CANDIDATE_DEFAULT_S,
                include_unreviewed_selftest=True,
            )
            pooled = evaluated["pooled"]
            out[f"{arm}|{name}"] = {
                "commits": len(result.committed),
                "commits_on_degraded_frames": sum(
                    status[(c.frame_id, str(c.hand_id))] == "DEGRADED" for c in result.committed
                ),
                "summary": {
                    k: pooled.get(k) for k in ("matched", "fp", "fn", "ground_truth", "fp_by_segment_type")
                },
                "by_segment_type": {
                    seg: {k: v.get(k) for k in ("matched", "fp", "fn")}
                    for seg, v in evaluated["by_segment_type"].items()
                },
            }
    return {"label": "SYNTHETIC P07 session (harness replay of causal tracks)", "results": out}


# ----------------------------------------------------------------------------- (b) injection


def fakeout_part(quick):
    """Fake-outs: a stroke that stops just above the surface (no strike), occluded around the stop.

    A DEGRADED bridge extrapolates the downward velocity through the gap; with commits allowed in
    DEGRADED the reactive arm can commit a strike that never happened (Q34-Q35). Swept: stroke speed
    (``t_down``), stop height above the surface (``-depth``), occlusion length (1-3 frames, within
    ``g_max``) and its start frame (8 frames before to 3 after the stop). Arms A and B.
    """
    rows = []
    t_downs = (0.08, 0.12, 0.2) if not quick else (0.1,)
    depths = (-0.002, -0.005, -0.01, -0.02) if not quick else (-0.005,)
    for arm in ("A", "B"):
        setup = SETUPS[arm]
        base = load_config(setup["config"]).data
        registry = ZoneRegistry.from_config(base["zones"])
        for t_down in t_downs:
            for depth in depths:
                swings = [Swing(HandId.RIGHT, "snare", 0.5, t_down=t_down, depth=depth, kind="stop_short")]
                frames = list(build_sequence(registry, swings, duration_s=1.6, name="fakeout"))
                stop = round((0.5 + t_down) * 30)
                for duration in (1, 2, 3):
                    for start in range(stop - 8, stop + 4):
                        plan = F.FaultPlan().observations(
                            start, start + duration, "OCCLUSION", lambda o, _i: F.drop_hand(o, HandId.RIGHT)
                        )
                        counts = {}
                        for pname, allow in POLICIES.items():
                            pipe = build_pipeline(
                                with_policy(base, allow),
                                active=setup["active"],
                                shadows=setup["shadows"],
                                clock=Ticker(),
                            )
                            monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
                            out = replay_frames(pipe, frames, plan=plan, monitor=monitor)
                            monitor.finish()
                            counts[pname] = {
                                "audible_commits": sum(1 for c in out["commits"] if not c.shadow),
                                "violations": violations_of(monitor),
                            }
                        rows.append(
                            {
                                "arm": arm,
                                "t_down": t_down,
                                "stop_height": -depth,
                                "duration_frames": duration,
                                "start_offset": start - stop,
                                **{f"{p}_{k}": v for p, r in counts.items() for k, v in r.items()},
                            }
                        )
    summary = {
        arm: {p: sum(r[f"{p}_audible_commits"] for r in rows if r["arm"] == arm) for p in POLICIES}
        for arm in ("A", "B")
    }
    return {
        "label": "SYNTHETIC fake-outs (no strike exists): every audible commit is a fabricated strike",
        "fabricated_commits": summary,
        "placements": len(rows) // 2,
        "violations": sum(sum(r[f"{p}_violations"].values()) for r in rows for p in POLICIES),
        "rows": rows,
    }


def injection_part(quick):
    rows = []
    for setup_name, setup in SETUPS.items():
        base = load_config(setup["config"]).data
        registry = ZoneRegistry.from_config(base["zones"])
        sequences = [(n, scenario(n, registry, **p)) for n, p in (SEQUENCES[:2] if quick else SEQUENCES)]
        for seq_name, seq in sequences:
            frames = list(seq)
            truth = list(seq.truth)
            anchors = [(ev.hand, truth_frame(frames, ev.t_cross)) for ev in truth[:2]]
            for kind, durations in (("OCCLUSION", (2, 3, 6)), ("LOW_CONF", (3, 9))):
                for hand, k in anchors:
                    for duration in durations:
                        for position in ("approach", "impact", "idle"):
                            if position == "impact":
                                start = max(1, k - 1)
                            elif position == "approach":
                                start = max(1, k - 1 - duration)
                            else:
                                start = idle_start(frames, seq.truth, duration)
                                if start is None:
                                    continue
                            end = min(len(frames), start + duration)
                            plan = F.FaultPlan()
                            if kind == "OCCLUSION":
                                plan.observations(start, end, kind, lambda o, _i, h=hand: F.drop_hand(o, h))
                            else:
                                plan.observations(
                                    start, end, kind, lambda o, _i, h=hand: F.set_confidence(o, h, 0.45)
                                )
                            paired = {}
                            for pname, allow in POLICIES.items():
                                data = with_policy(base, allow)
                                pipe = build_pipeline(
                                    data, active=setup["active"], shadows=setup["shadows"], clock=Ticker()
                                )
                                monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
                                out = replay_frames(pipe, frames, plan=plan, monitor=monitor)
                                monitor.finish()
                                audible = [c for c in out["commits"] if not c.shadow]
                                m = match(audible, truth, seq_name)
                                trows = truth_rows(truth, seq_name)
                                paired[pname] = {
                                    "matched": m["matched"],
                                    "fn": len(m["fn"]),
                                    "fp_fabricated": sum(fp_kind(s, trows) == "fabricated" for s in m["fp"]),
                                    "fp_mistimed": sum(fp_kind(s, trows) == "mistimed" for s in m["fp"]),
                                    "violations": violations_of(monitor),
                                    "crash": out["crash"],
                                }
                            rows.append(
                                {
                                    "arm": setup_name,
                                    "sequence": seq_name,
                                    "fakeout": not truth,
                                    "kind": kind,
                                    "duration_frames": duration,
                                    "position": position,
                                    "hand": str(hand),
                                    **{f"{p}_{k}": v for p, r in paired.items() for k, v in r.items()},
                                }
                            )
    return rows


def summarize(rows):
    table = defaultdict(lambda: defaultdict(int))
    for r in rows:
        suffix = "|fakeout" if r["fakeout"] else ""
        key = f"{r['arm']}|{r['kind']}|{r['duration_frames']}f|{r['position']}{suffix}"
        for p in POLICIES:
            for k in ("matched", "fn", "fp_fabricated", "fp_mistimed"):
                table[key][f"{p}_{k}"] += r[f"{p}_{k}"]
        table[key]["runs"] += 1
    totals = defaultdict(int)
    for arm in SETUPS:
        for r in rows:
            if r["arm"] != arm:
                continue
            for p in POLICIES:
                for k in ("matched", "fn", "fp_fabricated", "fp_mistimed"):
                    totals[f"{arm}|{p}_{k}"] += r[f"{p}_{k}"]
    violations = sum(sum(r[f"{p}_violations"].values()) for r in rows for p in POLICIES)
    crashes = sum(1 for r in rows for p in POLICIES if r[f"{p}_crash"])
    return {
        "by_cell": {k: dict(v) for k, v in sorted(table.items())},
        "totals": dict(totals),
        "violations": violations,
        "crashes": crashes,
    }


# ----------------------------------------------------------------------------- (c) dev captures


def devcapture_part(quick):
    from spacedrums.app.main import Perception
    from spacedrums.capture import ReplayFrameSource

    out = {}
    sessions = (
        ("data/dev-captures/swing-L2-exp-5",)
        if quick
        else ("data/dev-captures/swing-L2-exp-5", "data/dev-captures/swing-L2-exp-6")
    )
    for session in sessions:
        src = ReplayFrameSource(ROOT / session)
        views = [(s, src.view(s)) for s in src]
        for arm in ("A", "B"):
            setup = SETUPS[arm]
            res = {}
            for pname, allow in POLICIES.items():
                data = with_policy(load_config(setup["config"]).data, allow)
                pipe = build_pipeline(data, active=setup["active"], shadows=setup["shadows"], clock=Ticker())
                monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
                perception = Perception(data)
                try:
                    run = replay_frames(pipe, views, perception=perception, monitor=monitor)
                finally:
                    perception.close()
                monitor.finish()
                audible = [c for c in run["commits"] if not c.shadow]
                res[pname] = {
                    "audible_commits": [(c.frame_id, str(c.hand_id), c.zone_id) for c in audible],
                    "violations": violations_of(monitor),
                    "degraded_frames": sum(
                        1 for row in run["trace"] for s in row["status"].values() if s == "DEGRADED"
                    ),
                }
            added = [c for c in res["P1"]["audible_commits"] if c not in res["P0"]["audible_commits"]]
            out[f"{session}|{arm}"] = {**res, "added_by_P1": added}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--skip-devcapture", action="store_true")
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-17")
    add_executor_args(ap)
    args = ap.parse_args()
    with evidence(
        RULE_CONFIG,
        args,
        slug="degraded-experiment" + ("-quick" if args.quick else ""),
        task="17.7",
        description="Paired DEGRADED-commit experiment (development evidence; participant part PENDING)",
        output=args.output,
    ) as (run, _cfg):
        rows = injection_part(args.quick)
        report = {
            "decision_rule": __doc__.split("Decision rule", 1)[1].split("\n\n", 1)[0],
            "harness": harness_part(),
            "injection": {"summary": summarize(rows), "rows": rows},
            "fakeouts": fakeout_part(args.quick),
            "devcapture": {} if args.skip_devcapture else devcapture_part(args.quick),
        }
        (run.dir / "degraded-experiment.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print(json.dumps(report["injection"]["summary"]["totals"], indent=2), flush=True)
        print(json.dumps(report["fakeouts"]["fabricated_commits"], indent=2), flush=True)
        print(json.dumps(report["harness"], indent=2, default=str)[:3000], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
