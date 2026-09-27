"""Phase 17 (Tasks 17.3 / 17.7): re-acquisition thresholds ``g_max_frames`` and ``age_max_s``.

    python scripts/reacquisition_experiment.py --executor-model M --executor-effort E [--quick]

Grid: ``tracking.g_max_frames`` in {1, 2, 3, 4, 6} x ``tracking.age_max_s`` in {0.25, 0.5, 1.0} s;
everything else as in ``configs/prototype.candidate.yaml`` (commits in VALID only, ADR-0039;
frame-drop guard 3, ADR-0040 D4). The time-gap reset threshold ``(g_max + 1.5) / fps`` follows
``g_max`` (ADR-0040 D3). One replay per case: arm A sounds, arm B shadows (an arm's decisions do not
depend on which arm sounds).

Evidence (all DEVELOPMENT; the participant confirmation is PENDING until ds-v1.0 exists):

(a) SYNTHETIC injection on the Phase 17 grid's six sequences (first two strikes each): the hand is
    lost (no observation) for 1, 2, 3, 4, 6, 9 or 15 frames; observed with DEGRADED-level confidence
    (0.45) for 3, 9, 15, 24 or 36 frames, with the true tip (LOW_CONF) or with Gaussian position
    jitter of 0.015 ROI units per frame (LOW_CONF_JITTER: a weak estimate is also an inaccurate one,
    an assumption of this experiment); or the camera stalls for 2, 3, 4 or 6 frames - during the
    approach, at the impact and during idle. Phase 09 matcher, W = 50 ms candidate: fault-induced FP
    and FN inside the attribution window (0.1 s before the fault to 0.3 s after it) against the
    unperturbed run of the same grid point, FPs split into fabricated / mistimed (``_p17.fp_kind``);
    time from the end of the fault to VALID and to the rule arm's next prediction.
(b) SYNTHETIC P07 labelled session (recorded observations through the live pipeline): Phase 09
    harness scoring (matched / FP / FN) for arms A and B - a no-regression check.
(c) Developer swing captures through real perception (computed once per capture, then replayed for
    every grid point): commits and track-status counts; no ground truth, informational only.
(d) Occluded fake-outs (a stroke stopping 2 or 10 mm above the surface - no strike exists -
    occluded 1, 3 or 6 frames from 8 frames before to 3 after the stop): commits added over the
    unoccluded stroke are fabricated strikes.

Decision rule, declared before the first run (2026-09-27, Phase 17): (1) only grid points with zero
invariant violations and zero crashes in every part are considered; (2) of those, only the points
with the fewest fabricated strikes - fault-induced fabricated FP in (a) plus commits added on the
fake-outs (d), arms A and B - are eligible (zero whenever any point achieves zero); (3) the best
eligible point minimises the fault-induced FP + FN of (a) summed over arms A and B (ties: the smaller
g_max, then the smaller age_max); (4) the current candidates (g_max_frames = 3, age_max_s = 0.5) are
kept unless they are not eligible, or the best point lowers that sum by at least 5 % without lowering
matched or raising FP + FN on (b) for either arm. The margin exists because the evidence is
SYNTHETIC only and a change also moves the time-gap threshold (D3) and the development model's
inputs. The development C-GRU is not part of the decision (failure catalogue F-9).

Post-hoc sensitivity, added 2026-09-27 after a preview run of the declared design (not part of the
declared decision; reported separately): the declared fake-out set (d) has no loss longer than the
largest grid g_max (6 frames), and the preview's fabricated counts differed by one arm-B commit on
one 6-frame placement (a reset at g_max <= 4, a bridge at 6). The post-hoc set occludes the same
fake-outs for 1, 2, 3, 4, 6, 9 or 15 frames ending 4 frames before to 3 frames after the stop, so
every grid point sees losses both within and beyond its bridge, and the declared rule is re-applied
with (d) replaced by this set.
"""

from __future__ import annotations

import argparse
import copy
import json
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from _p17 import (
    RULE_CONFIG,
    Ticker,
    W,
    add_executor_args,
    build_pipeline,
    distribution_ms,
    enable_fault_injection,
    evidence,
    idle_start,
    match,
    reacquisition,
    replay_frames,
    truth_frame,
    violations_of,
    window_delta,
)

enable_fault_injection()

from inject_faults import DT, SEQUENCES, stream_faults  # noqa: E402
from invariant_replay import SYNTHETIC_LABELS, SYNTHETIC_SESSION, recorded_observations  # noqa: E402

from spacedrums.app import faults as F  # noqa: E402
from spacedrums.app.invariants import InvariantMonitor  # noqa: E402
from spacedrums.app.synthetic import Swing, build_sequence, scenario  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import HandId  # noqa: E402
from spacedrums.data.feature_dataset import load_session  # noqa: E402
from spacedrums.eval.report import evaluate_session  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
G_MAX = (1, 2, 3, 4, 6)
AGE_MAX = (0.25, 0.5, 1.0)
CURRENT = (3, 0.5)
MARGIN = 0.05
ARMS = ("A", "B")
FAULTS = (
    ("OCCLUSION", (1, 2, 3, 4, 6, 9, 15)),
    ("LOW_CONF", (3, 9, 15, 24, 36)),
    ("LOW_CONF_JITTER", (3, 9, 15, 24, 36)),
    ("STALL", (2, 3, 4, 6)),
)
QUICK_FAULTS = (("OCCLUSION", (3, 6)), ("LOW_CONF_JITTER", (9, 24)), ("STALL", (4,)))
POSITIONS = ("approach", "impact", "idle")
LOW_CONFIDENCE = 0.45
JITTER_SIGMA = 0.015
DEV_CAPTURES = (
    "data/dev-captures/swing-L2-exp-5",
    "data/dev-captures/swing-L2-exp-6",
    "data/dev-captures/swing-L2-exp-7",
)


def key(g: int, age: float) -> str:
    return f"g{g}|age{age:.2f}"


def with_thresholds(data: dict[str, Any], g: int, age: float) -> dict[str, Any]:
    d = copy.deepcopy(data)
    d["tracking"]["g_max_frames"] = int(g)
    d["tracking"]["age_max_s"] = float(age)
    return d


def run_rule(data, frames, *, plan=None, stream=None):
    """One replay, A sounding and B shadow; monitor in ``collect`` mode."""
    pipe = build_pipeline(copy.deepcopy(data), active="A", shadows=("B",), clock=Ticker())
    monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
    delivered = F.apply_stream_faults(frames, stream)[0] if stream else frames
    out = replay_frames(pipe, delivered, plan=plan, monitor=monitor)
    monitor.finish()
    return out, violations_of(monitor)


def fault_plan(kind: str, hand: HandId, start: int, end: int, seed: int):
    plan = F.FaultPlan()
    if kind == "OCCLUSION":
        return plan.observations(start, end, kind, lambda o, _i, h=hand: F.drop_hand(o, h))
    if kind == "LOW_CONF":
        return plan.observations(
            start, end, kind, lambda o, _i, h=hand: F.set_confidence(o, h, LOW_CONFIDENCE)
        )
    rng = np.random.default_rng(seed)
    offsets = {i: rng.normal(0.0, JITTER_SIGMA, 2) for i in range(start, end)}
    return plan.observations(
        start,
        end,
        kind,
        lambda o, i, h=hand: F.translate_hand(
            F.set_confidence(o, h, LOW_CONFIDENCE), h, float(offsets[i][0]), float(offsets[i][1])
        ),
    )


# ----------------------------------------------------------------------------- (a) + (d) per point


def grid_point(g: int, age: float, quick: bool) -> dict[str, Any]:
    """Injection (a) and fake-outs (d) for one (g_max, age_max); runs in a worker process."""
    enable_fault_injection()
    data = with_thresholds(load_config(RULE_CONFIG).data, g, age)
    registry = ZoneRegistry.from_config(data["zones"])
    rows = []
    crashes = 0
    violations: Counter = Counter()
    sequences = SEQUENCES[:2] if quick else SEQUENCES
    for seq_name, params in sequences:
        seq = scenario(seq_name, registry, **params)
        frames = list(seq)
        truth = list(seq.truth)
        sid = f"{seq_name}-{'-'.join(f'{k}{v}' for k, v in sorted(params.items()))}"
        ref_out, ref_viol = run_rule(data, frames)
        violations.update(ref_viol)
        crashes += ref_out["crash"] is not None
        ref = {arm: match([c for c in ref_out["commits"] if str(c.arm) == arm], truth, sid) for arm in ARMS}
        for ev_i, ev in enumerate(truth[:2]):
            k = truth_frame(frames, ev.t_cross)
            for kind, durations in QUICK_FAULTS if quick else FAULTS:
                for duration in durations:
                    for position in POSITIONS:
                        if position == "impact":
                            start = max(1, k - 1)
                        elif position == "approach":
                            start = max(1, k - 1 - duration)
                        else:
                            start = idle_start(frames, truth, duration)
                            if start is None:
                                continue
                        end = min(len(frames), start + duration)
                        # same jitter for every grid point (paired comparison); str hash() is salted
                        seed = zlib.crc32(f"{sid}|{ev_i}|{kind}|{duration}|{position}".encode())
                        if kind == "STALL":
                            out, viol = run_rule(data, frames, stream=stream_faults(kind, start, duration))
                        else:
                            plan = fault_plan(kind, ev.hand, start, end, seed)
                            out, viol = run_rule(data, frames, plan=plan)
                        violations.update(viol)
                        crashes += out["crash"] is not None
                        t_start = frames[start][0].t_capture
                        t_end = frames[min(len(frames) - 1, end)][0].t_capture
                        window = (t_start - 0.1, t_end + 0.3)
                        per_arm = {}
                        for arm in ARMS:
                            m = match([c for c in out["commits"] if str(c.arm) == arm], truth, sid)
                            d = window_delta(m, ref[arm], window, truth)
                            per_arm[arm] = {
                                "fp": d["fp_delta"],
                                "fn": d["fn_delta"],
                                "fabricated": d["fp_fabricated_delta"],
                                "mistimed": d["fp_mistimed_delta"],
                                "matched": m["matched"],
                            }
                        row = {
                            "sequence": sid,
                            "event": ev_i,
                            "kind": kind,
                            "duration_frames": duration,
                            "position": position,
                            "per_arm": per_arm,
                        }
                        if kind != "STALL" and out["trace"]:
                            r = reacquisition(out["trace"], str(ev.hand), end)
                            row["reacquisition"] = {k2: r[k2] for k2 in ("valid_s", "rule_pred_s")}
                        rows.append(row)
    fakeouts = fakeout_rows(data, registry, quick, violations)
    crashes += sum(r["crash"] for r in fakeouts)
    posthoc_violations: Counter = Counter()
    posthoc = posthoc_fakeout_rows(data, registry, quick, posthoc_violations)
    return {
        "g_max_frames": g,
        "age_max_s": age,
        "rows": rows,
        "fakeouts": fakeouts,
        "violations": dict(violations),
        "crashes": crashes,
        "posthoc_fakeouts": posthoc,
        "posthoc_violations": dict(posthoc_violations),
        "posthoc_crashes": sum(r["crash"] for r in posthoc),
    }


def fakeout_rows(data, registry, quick, violations: Counter) -> list[dict[str, Any]]:
    rows = []
    t_downs = (0.08, 0.12, 0.2) if not quick else (0.12,)
    depths = (-0.002, -0.01) if not quick else (-0.005,)
    durations = (1, 3, 6) if not quick else (3, 6)
    for t_down in t_downs:
        for depth in depths:
            swings = [Swing(HandId.RIGHT, "snare", 0.5, t_down=t_down, depth=depth, kind="stop_short")]
            frames = list(build_sequence(registry, swings, duration_s=1.6, name="fakeout"))
            ref_out, ref_viol = run_rule(data, frames)
            violations.update(ref_viol)
            ref = Counter(str(c.arm) for c in ref_out["commits"])
            stop = round((0.5 + t_down) * 30)
            for duration in durations:
                for start in range(stop - 8, stop + 4):
                    plan = F.FaultPlan().observations(
                        start, start + duration, "OCCLUSION", lambda o, _i: F.drop_hand(o, HandId.RIGHT)
                    )
                    out, viol = run_rule(data, frames, plan=plan)
                    violations.update(viol)
                    counts = Counter(str(c.arm) for c in out["commits"])
                    rows.append(
                        {
                            "t_down": t_down,
                            "stop_height": -depth,
                            "duration_frames": duration,
                            "start_offset": start - stop,
                            "added": {arm: max(0, counts[arm] - ref[arm]) for arm in ARMS},
                            "crash": out["crash"] is not None,
                        }
                    )
    return rows


def posthoc_fakeout_rows(data, registry, quick, violations: Counter) -> list[dict[str, Any]]:
    """Post-hoc fake-out set: every loss length, ending at the same phases around the stop."""
    rows = []
    t_downs = (0.08, 0.12, 0.2) if not quick else (0.12,)
    depths = (-0.002, -0.01) if not quick else (-0.01,)
    lengths = (1, 2, 3, 4, 6, 9, 15) if not quick else (3, 9)
    for t_down in t_downs:
        for depth in depths:
            swings = [Swing(HandId.RIGHT, "snare", 0.5, t_down=t_down, depth=depth, kind="stop_short")]
            frames = list(build_sequence(registry, swings, duration_s=1.6, name="fakeout"))
            ref_out, ref_viol = run_rule(data, frames)
            violations.update(ref_viol)
            ref = Counter(str(c.arm) for c in ref_out["commits"])
            stop = round((0.5 + t_down) * 30)
            for length in lengths:
                for end_offset in range(-4, 4):
                    end = stop + end_offset
                    start = max(1, end - length)
                    plan = F.FaultPlan().observations(
                        start, end, "OCCLUSION", lambda o, _i: F.drop_hand(o, HandId.RIGHT)
                    )
                    out, viol = run_rule(data, frames, plan=plan)
                    violations.update(viol)
                    counts = Counter(str(c.arm) for c in out["commits"])
                    rows.append(
                        {
                            "t_down": t_down,
                            "stop_height": -depth,
                            "duration_frames": end - start,
                            "end_offset": end_offset,
                            "added": {arm: max(0, counts[arm] - ref[arm]) for arm in ARMS},
                            "crash": out["crash"] is not None,
                        }
                    )
    return rows


def summarize_point(p: dict[str, Any]) -> dict[str, Any]:
    by_kind: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    reacq: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in p["rows"]:
        cell = by_kind[f"{r['kind']}|{r['duration_frames']}f"]
        cell["runs"] += 1
        for arm, v in r["per_arm"].items():
            for k in ("fp", "fn", "fabricated", "mistimed"):
                cell[f"{arm}_{k}"] += v[k]
                totals[f"{arm}_{k}"] += v[k]
        if "reacquisition" in r:
            for k in ("valid_s", "rule_pred_s"):
                reacq[r["kind"]][k].append(r["reacquisition"][k])
    fake = {arm: sum(r["added"][arm] for r in p["fakeouts"]) for arm in ARMS}
    posthoc = {arm: sum(r["added"][arm] for r in p["posthoc_fakeouts"]) for arm in ARMS}
    posthoc_by_length: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in p["posthoc_fakeouts"]:
        for arm in ARMS:
            posthoc_by_length[r["duration_frames"]][arm] += r["added"][arm]
    injected_fabricated = sum(totals[f"{a}_fabricated"] for a in ARMS)
    return {
        "objective_fp_plus_fn": sum(totals[f"{a}_fp"] + totals[f"{a}_fn"] for a in ARMS),
        "fabricated": injected_fabricated + sum(fake.values()),
        "posthoc_fabricated": injected_fabricated + sum(posthoc.values()),
        "totals": dict(totals),
        "fakeout_added": fake,
        "fakeout_placements": len(p["fakeouts"]),
        "posthoc_fakeout_added": posthoc,
        "posthoc_fakeout_added_by_length": {str(k): dict(v) for k, v in sorted(posthoc_by_length.items())},
        "posthoc_fakeout_placements": len(p["posthoc_fakeouts"]),
        "posthoc_violations": p["posthoc_violations"],
        "posthoc_crashes": p["posthoc_crashes"],
        "runs": len(p["rows"]),
        "by_kind": {k: dict(v) for k, v in sorted(by_kind.items())},
        "reacquisition_ms": {
            kind: {k: distribution_ms(v) for k, v in d.items()} for kind, d in sorted(reacq.items())
        },
        "violations": p["violations"],
        "crashes": p["crashes"],
    }


# ----------------------------------------------------------------------------- (b) P07 session


def p07_part(grid) -> dict[str, Any]:
    session_dir, label_dir = ROOT / SYNTHETIC_SESSION, ROOT / SYNTHETIC_LABELS
    if not session_dir.exists():
        return {"status": "PENDING: SYNTHETIC P07 session not present"}
    session = load_session(session_dir, label_dir, selftest=True)
    frames = recorded_observations(session_dir)
    base = load_config(RULE_CONFIG).data
    out = {}
    for g, age in grid:
        run, viol = run_rule(with_thresholds(base, g, age), frames)
        arms = {}
        for arm in ARMS:
            rows = [
                {
                    **c.to_dict(),
                    "session_id": session.table.session_id,
                    "participant_id": session.table.participant,
                    "t_impact_pred": float(c.t_impact_target),
                }
                for c in run["commits"]
                if str(c.arm) == arm
            ]
            pooled = evaluate_session(
                rows, session.labels, session.segments, w_s=W, include_unreviewed_selftest=True
            )["pooled"]
            arms[arm] = {k: pooled.get(k) for k in ("matched", "fp", "fn")}
        statuses = Counter(s for row in run["trace"] for s in row["status"].values())
        out[key(g, age)] = {
            "arms": arms,
            "status_counts": dict(statuses),
            "violations": viol,
            "crash": run["crash"],
        }
    return {"label": "SYNTHETIC P07 session, recorded observations through the live pipeline", "points": out}


# ----------------------------------------------------------------------------- (c) dev captures


def devcapture_part(grid, quick) -> dict[str, Any]:
    from spacedrums.app.main import Perception
    from spacedrums.capture import ReplayFrameSource

    base = load_config(RULE_CONFIG).data
    out = {}
    for session in DEV_CAPTURES[:1] if quick else DEV_CAPTURES:
        src = ReplayFrameSource(ROOT / session)
        perception = Perception(base)
        try:
            frames = [(s, perception(src.view(s))) for s in src]
        finally:
            perception.close()
        points = {}
        for g, age in grid:
            run, viol = run_rule(with_thresholds(base, g, age), frames)
            points[key(g, age)] = {
                "commits": {
                    arm: [
                        (c.frame_id, str(c.hand_id), c.zone_id) for c in run["commits"] if str(c.arm) == arm
                    ]
                    for arm in ARMS
                },
                "status_counts": dict(Counter(s for row in run["trace"] for s in row["status"].values())),
                "violations": viol,
                "crash": run["crash"],
            }
        current = points.get(key(*CURRENT))
        if current is not None:
            for p in points.values():
                p["vs_current"] = {
                    arm: {
                        "added": [c for c in p["commits"][arm] if c not in current["commits"][arm]],
                        "removed": [c for c in current["commits"][arm] if c not in p["commits"][arm]],
                    }
                    for arm in ARMS
                }
        out[session] = points
    return out


# ----------------------------------------------------------------------------- decision


def decide(
    summary: dict[str, Any], p07: dict[str, Any], dev: dict[str, Any], *, posthoc: bool = False
) -> dict[str, Any]:
    """The declared rule; ``posthoc`` swaps the declared fake-out set (d) for the post-hoc one."""
    fab = "posthoc_fabricated" if posthoc else "fabricated"

    def clean(k: str) -> bool:
        s = summary[k]
        ok = not sum(s["violations"].values()) and not s["crashes"]
        if posthoc:
            ok = ok and not sum(s["posthoc_violations"].values()) and not s["posthoc_crashes"]
        if "points" in p07:
            ok = ok and not sum(p07["points"][k]["violations"].values()) and p07["points"][k]["crash"] is None
        for points in dev.values():
            ok = ok and not sum(points[k]["violations"].values()) and points[k]["crash"] is None
        return ok

    considered = [k for k in summary if clean(k)]
    if not considered:
        return {"chosen": key(*CURRENT), "changed": False, "reason": "no grid point without violations"}
    fewest = min(summary[k][fab] for k in considered)
    eligible = [k for k in considered if summary[k][fab] == fewest]

    def order(k: str):
        g = int(k.split("|")[0][1:])
        age = float(k.split("|")[1][3:])
        return (summary[k]["objective_fp_plus_fn"], g, age)

    best = min(eligible, key=order)
    current = key(*CURRENT)
    result = {
        "considered": considered,
        "fewest_fabricated": fewest,
        "eligible": eligible,
        "best": best,
        "current": current,
        "objective": {k: summary[k]["objective_fp_plus_fn"] for k in summary},
    }
    if current not in eligible:
        return {**result, "chosen": best, "changed": best != current, "reason": "current not eligible"}
    if best == current:
        return {**result, "chosen": current, "changed": False, "reason": "current is best"}
    gain = 1.0 - summary[best]["objective_fp_plus_fn"] / max(1, summary[current]["objective_fp_plus_fn"])
    p07_ok = True
    if "points" in p07:
        for arm in ARMS:
            b, c = p07["points"][best]["arms"][arm], p07["points"][current]["arms"][arm]
            p07_ok = p07_ok and b["matched"] >= c["matched"] and b["fp"] + b["fn"] <= c["fp"] + c["fn"]
    changed = gain >= MARGIN and p07_ok
    return {
        **result,
        "relative_gain": gain,
        "p07_not_worse": p07_ok,
        "chosen": best if changed else current,
        "changed": changed,
        "reason": "best lowers FP + FN by >= 5 % and P07 not worse"
        if changed
        else "margin not reached or P07 worse; current kept",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-17")
    add_executor_args(ap)
    args = ap.parse_args()
    grid = [(g, a) for g in G_MAX for a in AGE_MAX]
    if args.quick:
        grid = [(2, 0.5), CURRENT, (3, 0.25), (4, 1.0)]
    with evidence(
        RULE_CONFIG,
        args,
        slug="reacquisition-experiment" + ("-quick" if args.quick else ""),
        task="17.3",
        description="Re-acquisition thresholds g_max / age_max sweep (development evidence)",
        output=args.output,
    ) as (run, _cfg):
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {key(g, a): pool.submit(grid_point, g, a, args.quick) for g, a in grid}
            points = {k: f.result() for k, f in futures.items()}
        summary = {k: summarize_point(p) for k, p in points.items()}
        p07 = p07_part(grid)
        dev = devcapture_part(grid, args.quick)
        decision = decide(summary, p07, dev)
        posthoc = decide(summary, p07, dev, posthoc=True)
        rule_text, posthoc_text = __doc__.split("Decision rule", 1)[1].split("\nPost-hoc sensitivity", 1)
        report = {
            "label": "DEVELOPMENT: SYNTHETIC injection / P07 / developer captures; not participant evidence",
            "decision_rule": rule_text.strip(),
            "posthoc_note": "Post-hoc sensitivity" + posthoc_text.rstrip(),
            "posthoc_decision": {
                **posthoc,
                "label": "POST-HOC sensitivity (added after the preview run); not the declared decision",
            },
            "grid": [key(g, a) for g, a in grid],
            "assumptions": {
                "low_confidence": LOW_CONFIDENCE,
                "jitter_sigma_roi": JITTER_SIGMA,
                "frame_interval_s": DT,
                "matching_w_s": W,
            },
            "summary": summary,
            "p07": p07,
            "devcapture": dev,
            "decision": decision,
            "rows": {k: p["rows"] for k, p in points.items()},
            "fakeout_rows": {k: p["fakeouts"] for k, p in points.items()},
            "posthoc_fakeout_rows": {k: p["posthoc_fakeouts"] for k, p in points.items()},
        }
        (run.dir / "reacquisition-experiment.json").write_text(
            json.dumps(report, indent=1, default=str), encoding="utf-8"
        )
        for k, s in summary.items():
            print(
                f"{k}: FP+FN {s['objective_fp_plus_fn']} fabricated {s['fabricated']} "
                f"(post-hoc {s['posthoc_fabricated']}) violations {sum(s['violations'].values())} "
                f"crashes {s['crashes']}",
                flush=True,
            )
        print(
            "declared:", json.dumps({k: decision.get(k) for k in ("chosen", "changed", "reason")}), flush=True
        )
        print(
            "post-hoc:", json.dumps({k: posthoc.get(k) for k in ("chosen", "changed", "reason")}), flush=True
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
