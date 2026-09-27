"""Phase 17 failure-injection campaign (Tasks 17.3-17.6): replay-from-file fault injection.

    python scripts/inject_faults.py --suite synthetic   [--quick] --executor-model M --executor-effort E
    python scripts/inject_faults.py --suite switch
    python scripts/inject_faults.py --suite model
    python scripts/inject_faults.py --suite capture-live
    python scripts/inject_faults.py --suite audio
    python scripts/inject_faults.py --suite devcapture   [--sessions ...]
    python scripts/inject_faults.py --suite all

Suites (all deterministic; every input is SYNTHETIC or a developer capture, never participant data):

* ``synthetic`` - labelled SYNTHETIC two-hand sequences (``app.synthetic``) with observation faults
  (occlusion, hand out of the ROI, identity swap, low confidence, background hand) and capture faults
  (stall, drop burst, forward timestamp jump, FPS dip) placed during the approach, at the impact and
  during idle, for 100 / 200 / 300 / 500 / 1000 ms; arms A (+B shadow, rule config) and C-GRU (+A, B
  shadow, synthetic-trained development model). Scored with the Phase 09 matcher (W = 50 ms
  candidate) against the analytic truth; FP/FN are attributed to a window around each injection and
  compared with the unperturbed run; the invariant monitor runs in ``collect`` mode.
* ``switch`` - runtime arm switch / model fallback 1..5 frames after the active arm's anticipatory
  commit, over the Phase 18 commit-threshold sweep range (p_commit, tti_commit_s).
* ``model`` - load faults (missing / corrupt / wrong schema / wrong hash / malformed manifest) and
  mid-session faults (slow, exceptions of several types, NaN / Inf outputs) on the C arm.
* ``capture-live`` - ``LiveFrameSource`` on the synthetic camera behind ``FaultyCamera``: driver
  timestamps lagging the grab, non-monotone driver and grab clocks, stalls, disconnect / re-attach.
* ``audio`` - the audio output behind a fake PortAudio stream: device removal / re-attach mid-session
  and underrun bursts.
* ``devcapture`` - the developer swing captures through real perception with image faults (occlusion
  masks around a hand, the hand's side of the ROI blanked, lighting gain/gamma, a background
  distractor) and capture faults; no ground truth exists, so outcomes are compared with the
  unperturbed replay of the same capture.

Outputs one evidence run under ``experiments/phase-17/`` (``injection-<suite>.json``).
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import math
import sys
import types
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from _p17 import (
    MODEL_CONFIG,
    RULE_CONFIG,
    Ticker,
    add_executor_args,
    build_pipeline,
    distribution_ms,
    enable_fault_injection,
    evidence,
    expected_loss_statuses,
    fp_kind,
    idle_start,
    match,
    reacquisition,
    replay_frames,
    status_sequence,
    truth_frame,
    truth_rows,
    violations_of,
    window_delta,
)

enable_fault_injection()

from _p10 import write_json  # noqa: E402

from spacedrums.app import faults as F  # noqa: E402
from spacedrums.app.arms import build_model_arm  # noqa: E402
from spacedrums.app.invariants import InvariantMonitor  # noqa: E402
from spacedrums.app.synthetic import scenario  # noqa: E402
from spacedrums.config import deep_merge, load_config  # noqa: E402
from spacedrums.contracts import HandId  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DT = 1.0 / 30.0
SEQUENCES = (
    ("single", {"t_down": 0.2}),
    ("repeated", {"t_down": 0.2}),
    ("alternating_two_zones", {"t_down": 0.2}),
    ("near_simultaneous", {"t_down": 0.2}),
    ("rapid", {}),
    ("repeated", {"t_down": 0.12, "noise": 0.003, "seed": 1}),
)
DURATIONS = (3, 6, 9, 15, 30)  # frames at 30 FPS: 100 / 200 / 300 / 500 / 1000 ms
POSITIONS = ("approach", "impact", "idle")
OBS_KINDS = ("OCCLUSION", "OUT_OF_ROI", "SWAP", "LOW_CONF", "BACKGROUND_HAND")
STREAM_KINDS = ("STALL", "DROP_BURST", "TIMESTAMP_JUMP", "FPS_CHANGE")
ARM_SETUPS = {
    "rule": {"config": RULE_CONFIG, "active": "A", "shadows": ("B",)},
    "model": {"config": MODEL_CONFIG, "active": "C-GRU", "shadows": ("A", "B")},
}


# ============================================================================ observation faults


def out_of_roi(hand: HandId, start: int, end: int):
    """The hand moves laterally out of the ROI over the interval; absent once the tip leaves it."""
    side = 1.0 if hand is HandId.RIGHT else -1.0
    span = max(1, end - start)

    def fn(obs, i):
        u = min(1.0, (i - start + 1) / max(1.0, span / 2))
        moved = F.translate_hand(obs, hand, side * 0.8 * u, 0.0)
        tip = moved[hand][1].tip
        if tip is None or not (0.0 <= tip[0] <= 1.0):
            return F.drop_hand(obs, hand)
        return moved

    return fn


def background_hand(hand: HandId):
    """A second person's hand reported as ``hand``: the same motion, offset above and to the side."""
    dx = -0.3 if hand is HandId.RIGHT else 0.3

    def fn(obs, _i):
        return F.replace_hand(obs, hand, F.translate_hand(obs, hand, dx, -0.25)[hand])

    return fn


def observation_plan(kind: str, hand: HandId, start: int, end: int) -> F.FaultPlan:
    plan = F.FaultPlan()
    if kind == "OCCLUSION":
        return plan.observations(start, end, kind, lambda o, _i: F.drop_hand(o, hand), hand=str(hand))
    if kind == "OUT_OF_ROI":
        return plan.observations(start, end, kind, out_of_roi(hand, start, end), hand=str(hand))
    if kind == "SWAP":
        return plan.observations(start, end, kind, lambda o, _i: F.swap_hands(o))
    if kind == "LOW_CONF":
        return plan.observations(
            start, end, kind, lambda o, _i: F.set_confidence(o, hand, 0.45), hand=str(hand), confidence=0.45
        )
    if kind == "BACKGROUND_HAND":
        return plan.observations(
            start, end, kind, background_hand(hand), hand=str(hand), offset=(-0.3, -0.25)
        )
    raise ValueError(kind)


def stream_faults(kind: str, start: int, duration: int):
    if kind == "STALL":
        return [F.Stall(at=start, frames=duration)]
    if kind == "DROP_BURST":
        return [F.DropBurst(at=start, frames=duration)]
    if kind == "TIMESTAMP_JUMP":
        return [F.TimestampJump(at=start, delta_s=duration * DT)]
    if kind == "FPS_CHANGE":
        return [F.FpsChange(at=start, keep_every=2, until=start + duration)]
    raise ValueError(kind)


# ============================================================================ synthetic suite


def synthetic_suite(args, quick: bool) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    references: dict[str, Any] = {}
    sequences = SEQUENCES[:2] if quick else SEQUENCES
    durations = DURATIONS[:3] if quick else DURATIONS
    for setup_name, setup in ARM_SETUPS.items():
        data = load_config(setup["config"]).data
        registry = ZoneRegistry.from_config(data["zones"])
        for seq_name, params in sequences:
            seq = scenario(seq_name, registry, **params)
            frames = list(seq)
            sid = f"synthetic-{seq_name}-{'-'.join(f'{k}{v}' for k, v in sorted(params.items()))}"
            ref = run_one(data, setup, frames, seq.truth, sid)
            references[f"{setup_name}|{sid}"] = summarize_reference(ref)
            events = list(seq.truth)[:2]  # the first two strikes of each sequence (both hands where present)
            for ev_i, ev in enumerate(events):
                k = truth_frame(frames, ev.t_cross)
                for kind in (*OBS_KINDS, *STREAM_KINDS):
                    for duration in durations:
                        for position in POSITIONS:
                            if position == "impact":
                                start = max(1, k - 1)
                            elif position == "approach":
                                start = max(1, k - 1 - duration)
                            else:
                                start = idle_start(frames, seq.truth, duration)
                                if start is None:
                                    continue
                            end = min(len(frames), start + duration)
                            row = injected_run(
                                data, setup, frames, seq.truth, sid, kind, ev.hand, start, end, duration, ref
                            )
                            row.update(
                                setup=setup_name,
                                sequence=sid,
                                event=ev_i,
                                kind=kind,
                                position=position,
                                duration_frames=duration,
                                duration_ms=round(duration * DT * 1000),
                            )
                            rows.append(row)
    return {"rows": rows, "references": references, "aggregate": aggregate(rows)}


def run_one(data, setup, frames, truth, sid, *, plan=None, stream=None, model_factory=build_model_arm):
    clock = Ticker()
    pipe = build_pipeline(
        copy.deepcopy(data),
        active=setup["active"],
        shadows=setup["shadows"],
        clock=clock,
        model_factory=model_factory,
    )
    monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
    delivered = frames
    events: list[F.FaultEvent] = []
    if stream:
        delivered, events = F.apply_stream_faults(frames, stream)
    out = replay_frames(pipe, delivered, plan=plan, monitor=monitor)
    monitor.finish()
    audible = [c for c in out["commits"] if not c.shadow]
    per_arm = {}
    for arm in sorted({str(c.arm) for c in out["commits"]} | {setup["active"], *setup["shadows"]}):
        per_arm[arm] = match([c for c in out["commits"] if str(c.arm) == arm], truth, sid)
    return {
        "out": out,
        "delivered": delivered,
        "audible": match(audible, truth, sid),
        "per_arm": per_arm,
        "violations": violations_of(monitor),
        "checks": monitor.summary()["checks"],
        "fallbacks": list(pipe.fallback_events),
        "stream_events": [e.to_dict() for e in events],
    }


def summarize_reference(ref):
    return {
        "matched": ref["audible"]["matched"],
        "fp": len(ref["audible"]["fp"]),
        "fn": len(ref["audible"]["fn"]),
        "violations": ref["violations"],
        "crash": ref["out"]["crash"],
    }


def injected_run(data, setup, frames, truth, sid, kind, hand, start, end, duration, ref) -> dict[str, Any]:
    plan = stream = None
    if kind in OBS_KINDS:
        plan = observation_plan(kind, hand, start, end)
    else:
        stream = stream_faults(kind, start, duration)
    t_start = frames[start][0].t_capture
    t_end = frames[min(len(frames) - 1, end)][0].t_capture
    window = (t_start - 0.1, t_end + 0.3)
    if kind == "TIMESTAMP_JUMP":
        # a clock jump changes timestamps, not motion: truth after the jump moves with the clock
        delta = duration * DT
        truth = [
            dataclasses.replace(t, t_cross=t.t_cross + delta) if t.t_cross >= t_start else t for t in truth
        ]
        ref = {**ref, "audible": match([c for c in ref["out"]["commits"] if not c.shadow], truth, sid)}
        ref["per_arm"] = {
            arm: match([c for c in ref["out"]["commits"] if str(c.arm) == arm], truth, sid)
            for arm in ref["per_arm"]
        }
        window = (t_start - 0.1, t_end + delta + 0.3)
    res = run_one(data, setup, frames, truth, sid, plan=plan, stream=stream)
    row: dict[str, Any] = {
        "hand": str(hand),
        "start": start,
        "end": end,
        "crash": res["out"]["crash"],
        "violations": res["violations"],
        "audible": window_delta(res["audible"], ref["audible"], window, truth),
        "per_arm": {
            arm: window_delta(m, ref["per_arm"].get(arm, {"fp": [], "fn": []}), window, truth)
            for arm, m in res["per_arm"].items()
        },
        "fallbacks": len(res["fallbacks"]),
        "timing_s": res["audible"]["timing_s"],
    }
    trace = res["out"]["trace"]
    h = str(hand)
    if kind in ("OCCLUSION", "OUT_OF_ROI", "SWAP", "LOW_CONF", "BACKGROUND_HAND"):
        row["reacquisition"] = reacquisition(trace, h, end)
        if kind == "OCCLUSION" and start > 0 and trace and trace[start - 1]["status"][h] == "VALID":
            statuses = status_sequence(trace, h, start, end)
            t_valid = trace[start - 1]["t"]
            times = [r["t"] - t_valid for r in trace if start <= r["i"] < end]
            g_max = data["tracking"]["g_max_frames"]
            row["status_check"] = expected_loss_statuses(
                statuses, times, g_max, data["tracking"]["age_max_s"]
            )
            row["statuses"] = "".join(s[0] for s in statuses)
    else:
        row["reacquisition"] = reacquisition(trace, h, start)
        row["resets"] = sum(1 for r in trace if r["reset"][h] is not None)
    return row


def aggregate(rows):
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r["setup"], r["kind"], r["position"], r["duration_ms"])].append(r)
    table = []
    for (setup, kind, position, ms), rs in sorted(groups.items()):
        reacq = [r["reacquisition"]["valid_s"] for r in rs if r.get("reacquisition")]
        checks = [r["status_check"] for r in rs if "status_check" in r]
        table.append(
            {
                "setup": setup,
                "kind": kind,
                "position": position,
                "duration_ms": ms,
                "runs": len(rs),
                "crashes": sum(1 for r in rs if r["crash"]),
                "violations": sum(sum(r["violations"].values()) for r in rs),
                "audible_fp_delta": sum(r["audible"]["fp_delta"] for r in rs),
                "audible_fp_delta_positive": sum(max(0, r["audible"]["fp_delta"]) for r in rs),
                "audible_fabricated_delta_positive": sum(
                    max(0, r["audible"]["fp_fabricated_delta"]) for r in rs
                ),
                "audible_mistimed_delta_positive": sum(max(0, r["audible"]["fp_mistimed_delta"]) for r in rs),
                "audible_fn_delta": sum(r["audible"]["fn_delta"] for r in rs),
                "audible_outside_fp_delta": sum(r["audible"]["fp_outside_delta"] for r in rs),
                "reacquisition_valid": distribution_ms(v for v in reacq if v is not None),
                "reacquisition_never": sum(1 for v in reacq if v is None),
                "status_checks": f"{sum(checks)}/{len(checks)}" if checks else None,
                "per_arm_fp_delta_positive": {
                    arm: sum(max(0, r["per_arm"].get(arm, {}).get("fp_delta", 0)) for r in rs)
                    for arm in sorted({a for r in rs for a in r["per_arm"]})
                },
                "per_arm_fabricated_delta_positive": {
                    arm: sum(max(0, r["per_arm"].get(arm, {}).get("fp_fabricated_delta", 0)) for r in rs)
                    for arm in sorted({a for r in rs for a in r["per_arm"]})
                },
                "per_arm_fn_delta": {
                    arm: sum(r["per_arm"].get(arm, {}).get("fn_delta", 0) for r in rs)
                    for arm in sorted({a for r in rs for a in r["per_arm"]})
                },
            }
        )
    totals = {
        "runs": len(rows),
        "crashes": sum(1 for r in rows if r["crash"]),
        "violations": sum(sum(r["violations"].values()) for r in rows),
        "violations_by_invariant": _sum_dicts(r["violations"] for r in rows),
        "audible_fp_delta_positive": sum(max(0, r["audible"]["fp_delta"]) for r in rows),
        "audible_fabricated_delta_positive": sum(max(0, r["audible"]["fp_fabricated_delta"]) for r in rows),
        "fabricated_delta_positive_by_arm": _sum_dicts(
            {a: max(0, w["fp_fabricated_delta"]) for a, w in r["per_arm"].items()} for r in rows
        ),
        "audible_fp_delta_positive_loss_faults": sum(
            max(0, r["audible"]["fp_delta"])
            for r in rows
            if r["kind"] in ("OCCLUSION", "OUT_OF_ROI", "STALL")
        ),
    }
    return {"totals": totals, "table": table}


# ============================================================================ switch suite


def switch_suite(args, quick: bool) -> dict[str, Any]:
    base = load_config(RULE_CONFIG).data
    registry = ZoneRegistry.from_config(base["zones"])
    rows = []
    for p_commit in (0.5, 0.3, 0.1):
        for tti in (0.05, 0.1, 0.15):
            data = deep_merge(base, {"commit": {"tti_commit_s": tti, "p_commit": p_commit}})
            for name, params in (
                ("single", {"t_down": 0.12}),
                ("single", {}),
                ("repeated", {"t_down": 0.12}),
                ("repeated", {}),
                ("rapid", {}),
                ("alternating_two_zones", {"t_down": 0.12}),
            ):
                seq = scenario(name, registry, **params)
                frames = list(seq)
                for a, b in (("B", "A"), ("A", "B")):
                    for k in range(1, 6):
                        clock = Ticker()
                        pipe = build_pipeline(copy.deepcopy(data), active=a, shadows=(b,), clock=clock)
                        monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
                        first = None
                        audible = []
                        crash = None
                        for i, (sample, obs) in enumerate(frames):
                            try:
                                if first is not None and i == first + k:
                                    pipe.set_active_arm(b, sample.t_capture)
                                r = pipe.step(sample, obs, t_now=sample.t_frame_available)
                                monitor.observe(r, pipe)
                            except Exception as exc:  # noqa: BLE001
                                crash = f"{type(exc).__name__}: {exc}"
                                break
                            for c in r.commits:
                                if not c.shadow:
                                    audible.append(c)
                                if c.arm == a and not c.shadow and first is None:
                                    first = i
                        monitor.finish()
                        sid = f"{name}-{params}"
                        m = match(audible, seq.truth, sid)
                        rows.append(
                            {
                                "p_commit": p_commit,
                                "tti_commit_s": tti,
                                "sequence": sid,
                                "switch": f"{a}->{b}",
                                "offset_frames": k,
                                "switched": first is not None,
                                "crash": crash,
                                "violations": violations_of(monitor),
                                "audible_matched": m["matched"],
                                "audible_fp": len(m["fp"]),
                                "audible_fn": len(m["fn"]),
                                "truth": len(seq.truth),
                            }
                        )
    return {
        "rows": rows,
        "totals": {
            "runs": len(rows),
            "switched_runs": sum(r["switched"] for r in rows),
            "runs_with_violations": sum(1 for r in rows if r["violations"]),
            "violations_by_invariant": _sum_dicts(r["violations"] for r in rows),
            "crashes": sum(1 for r in rows if r["crash"]),
            "audible_fp": sum(r["audible_fp"] for r in rows),
        },
    }


def _sum_dicts(dicts):
    out: dict[str, int] = defaultdict(int)
    for d in dicts:
        for k, v in d.items():
            out[k] += v
    return dict(sorted(out.items()))


# ============================================================================ model suite


def _package_copy(data, tmp: Path, mutate) -> dict[str, Any]:
    """Copy the configured model package to ``tmp`` and apply ``mutate(dir, cfg)``."""
    import shutil

    cfg = copy.deepcopy(data)
    src = ROOT / cfg["anticipator"]["model"]["path"]
    dst = tmp / "model"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    cfg["anticipator"]["model"]["path"] = str(dst)
    mutate(dst, cfg)
    return cfg


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def model_suite(args, quick: bool, tmp: Path) -> dict[str, Any]:
    base = load_config(MODEL_CONFIG).data
    registry = ZoneRegistry.from_config(base["zones"])
    seq = scenario("alternating_two_zones", registry, t_down=0.2)
    frames = list(seq)
    setup = ARM_SETUPS["model"]
    reference = run_one(base, setup, frames, seq.truth, "model-ref")
    rows = []

    def corrupt_export(d: Path, cfg):
        blob = bytearray((d / "export.pt").read_bytes())
        blob[len(blob) // 2 : len(blob) // 2 + 64] = b"\x00" * 64
        (d / "export.pt").write_bytes(bytes(blob))
        cfg["anticipator"]["model"]["hash"] = _sha(d / "export.pt")
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        manifest["export_hash"] = cfg["anticipator"]["model"]["hash"]
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        cfg["anticipator"]["model"]["manifest_hash"] = _sha(d / "manifest.json")

    def malformed_manifest(d: Path, cfg):
        (d / "manifest.json").write_text("{not json", encoding="utf-8")
        cfg["anticipator"]["model"]["manifest_hash"] = _sha(d / "manifest.json")

    def wrong_schema(d: Path, cfg):
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        manifest["F"] = manifest["F"] + 1
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        cfg["anticipator"]["model"]["manifest_hash"] = _sha(d / "manifest.json")

    def wrong_types(d: Path, cfg):
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        manifest["dt_step"] = "fast"
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        cfg["anticipator"]["model"]["manifest_hash"] = _sha(d / "manifest.json")

    def wrong_hash(_d: Path, cfg):
        cfg["anticipator"]["model"]["hash"] = "sha256:" + "0" * 64

    def missing(d: Path, cfg):
        cfg["anticipator"]["model"]["path"] = str(d / "missing")

    load_faults = {
        "missing_package": missing,
        "wrong_export_hash": wrong_hash,
        "corrupt_export_rehashed": corrupt_export,
        "malformed_manifest_json": malformed_manifest,
        "wrong_feature_schema": wrong_schema,
        "manifest_wrong_types": wrong_types,
    }
    for name, mutate in load_faults.items():
        cfg = _package_copy(base, tmp, mutate)
        res = _guarded_run(cfg, setup, frames, seq.truth, f"model-{name}")
        res["fault"] = name
        res["phase"] = "load"
        rows.append(res)
    mid = [
        ("slow_after_20", {"kind": "slow", "after_calls": 20, "delay_s": 0.05}),
        ("runtime_error_after_20", {"kind": "raise", "after_calls": 20, "exception": RuntimeError}),
        ("type_error_after_20", {"kind": "raise", "after_calls": 20, "exception": TypeError}),
        ("index_error_after_20", {"kind": "raise", "after_calls": 20, "exception": IndexError}),
        ("key_error_after_20", {"kind": "raise", "after_calls": 20, "exception": KeyError}),
        (
            "floating_point_error_after_20",
            {"kind": "raise", "after_calls": 20, "exception": FloatingPointError},
        ),
        ("nan_outputs_after_20", {"kind": "nan", "after_calls": 20}),
        ("inf_outputs_after_20", {"kind": "inf", "after_calls": 20}),
        ("nan_outputs_from_start", {"kind": "nan", "after_calls": 0}),
    ]
    for name, spec in mid:
        clock = Ticker()

        def factory(cfg, clock, spec=spec, clock_ref=clock):
            arm = build_model_arm(cfg, clock=clock)
            F.ModelFault(arm, advance_clock=clock_ref.advance if spec["kind"] == "slow" else None, **spec)
            return arm

        res = _guarded_run(
            base, setup, frames, seq.truth, f"model-{name}", model_factory=factory, clock=clock
        )
        res["fault"] = name
        res["phase"] = "mid-session"
        rows.append(res)
    ref_audible = reference["audible"]
    for r in rows:
        r["audible_fp_vs_reference"] = r.get("audible_fp", 0) - len(ref_audible["fp"])
    return {
        "rows": rows,
        "reference": {"audible_fp": len(ref_audible["fp"]), "matched": ref_audible["matched"]},
        "totals": {
            "cases": len(rows),
            "crashes": sum(1 for r in rows if r["crash"]),
            "violations": sum(sum(r["violations"].values()) for r in rows),
            "fallback_observed": sum(1 for r in rows if r["fallbacks"]),
            "silent_failures": sum(1 for r in rows if not r["crash"] and not r["fallbacks"]),
        },
    }


def _guarded_run(cfg, setup, frames, truth, sid, *, model_factory=build_model_arm, clock=None):
    clock = clock or Ticker()
    try:
        pipe = build_pipeline(
            copy.deepcopy(cfg),
            active=setup["active"],
            shadows=setup["shadows"],
            clock=clock,
            model_factory=model_factory,
        )
    except Exception as exc:  # noqa: BLE001 - construction failure is an outcome
        return {
            "crash": {"frame": None, "type": type(exc).__name__, "message": str(exc)[:300]},
            "violations": {},
            "fallbacks": [],
        }
    monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
    out = replay_frames(pipe, frames, monitor=monitor)
    monitor.finish()
    audible = [c for c in out["commits"] if not c.shadow]
    m = match(audible, truth, sid)
    model_commits_after = []
    if pipe.fallback_events:
        t_fb = pipe.fallback_events[0]["t"]
        model_commits_after = [
            c.strike_id for c in out["commits"] if str(c.arm) == "C-GRU" and c.t_commit >= t_fb
        ]
    return {
        "crash": out["crash"],
        "violations": violations_of(monitor),
        "fallbacks": pipe.fallback_events,
        "active_arm_final": str(pipe.active_arm),
        "model_error": pipe.model_error,
        "audible_matched": m["matched"],
        "audible_fp": len(m["fp"]),
        "audible_fn": len(m["fn"]),
        "model_commits_after_fallback": model_commits_after,
        "frames_processed": len(out["trace"]),
    }


# ============================================================================ capture-live suite


def capture_live_suite(args, quick: bool) -> dict[str, Any]:
    from spacedrums.capture import CaptureSettings, LiveFrameSource, Roi, SyntheticCamera
    from spacedrums.capture.backend import CameraOpenSpec
    from spacedrums.contracts import HandObservation, StickObservation, TimestampSource, TipMethod

    data = load_config(RULE_CONFIG).data

    def settings(ts):
        return CaptureSettings(
            camera_profile_id="synthetic-p17",
            spec=CameraOpenSpec(),
            roi=Roi(8, 8, 40, 30),
            timestamp_source=ts,
            nominal_fps=100.0,
            queue_max_frames=2,
            warmup_frames=3,
            mapper_warmup_n=10,
        )

    cases = [
        ("driver_lag_exceeds_interval", TimestampSource.DRIVER_MAPPED, {"lag_s": 0.05}, {}),
        ("driver_clock_backward_jump", TimestampSource.DRIVER_MAPPED, {}, {"driver_shift": {60: -5.0}}),
        ("driver_clock_forward_jump", TimestampSource.DRIVER_MAPPED, {}, {"driver_shift": {60: 2.0}}),
        ("grab_clock_backward_step", TimestampSource.GRAB_RETURN, {}, {"grab_shift": {60: -0.05}}),
        ("camera_stall_300ms", TimestampSource.GRAB_RETURN, {}, {"stall_at": {60: 0.3}}),
        ("camera_disconnect_reattach", TimestampSource.GRAB_RETURN, {}, {"disconnect": (60, 40)}),
    ]
    rows = []
    for name, ts, cam_kw, fault_kw in cases:
        cam = F.FaultyCamera(SyntheticCamera(fps=100.0, n_frames=200, paced=True, **cam_kw), **fault_kw)
        src = LiveFrameSource(cam, settings(ts))
        clock = Ticker()
        pipe = build_pipeline(copy.deepcopy(data), active="A", shadows=("B",), clock=clock)
        monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
        delivered = 0
        crash = None
        try:
            with src:
                for sample in src:
                    obs = {
                        h: (
                            HandObservation.absent(sample.frame_id, sample.t_capture, h, "none"),
                            StickObservation.absent(sample.frame_id, sample.t_capture, h, TipMethod.GEOM),
                        )
                        for h in (HandId.LEFT, HandId.RIGHT)
                    }
                    r = pipe.step(sample, obs, t_now=sample.t_frame_available)
                    monitor.observe(r, pipe)
                    delivered += 1
        except Exception as exc:  # noqa: BLE001
            crash = {"type": type(exc).__name__, "message": str(exc)[:300], "after_frames": delivered}
        stats = src.stats().to_dict()
        rows.append(
            {
                "case": name,
                "timestamp_source": str(ts),
                "delivered_to_pipeline": delivered,
                "crash": crash,
                "violations": violations_of(monitor),
                "capture_stats": stats,
                "timestamp_report": src.timestamp_report(),
            }
        )
    return {
        "rows": rows,
        "totals": {"cases": len(rows), "crashes": sum(1 for r in rows if r["crash"])},
    }


# ============================================================================ audio suite


def audio_suite(args, quick: bool) -> dict[str, Any]:
    """Fake PortAudio stream behind ``SoundDeviceOutput``: removal / re-attach and underrun bursts."""
    from spacedrums.app import audio_out

    data = load_config(RULE_CONFIG).data
    registry = ZoneRegistry.from_config(data["zones"])
    seq = scenario("repeated", registry, t_down=0.2)
    frames = list(seq)
    rows = []
    for case in ("reference", "device_removed_mid_session", "removed_and_reattached", "underrun_burst"):
        clock = Ticker(step=0.0)
        backend = F.FakeAudioBackend(clock)
        fake_module = types.SimpleNamespace(OutputStream=backend)
        saved = sys.modules.get("sounddevice")
        sys.modules["sounddevice"] = fake_module
        crash = out = monitor = None
        removed_at = reattach_at = None
        try:
            out = _make_audio_output(audio_out, data, clock, backend)
            pipe = build_pipeline(copy.deepcopy(data), active="A", shadows=("B",), clock=clock, audio=False)
            pipe.audio = out
            pipe.gain_fn = out.gain
            for pol in pipe.policies.values():
                for p in pol.values():
                    p.gain_fn = out.gain
            monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
            out.start()
            for i, (sample, obs) in enumerate(frames):
                clock.t = sample.t_frame_available
                if case in ("device_removed_mid_session", "removed_and_reattached") and i == len(frames) // 3:
                    backend.remove()
                    removed_at = i
                if case == "removed_and_reattached" and i == 2 * len(frames) // 3:
                    backend.reattach()
                    reattach_at = i
                if case == "underrun_burst" and i == len(frames) // 3:
                    backend.underruns(10)
                check = getattr(out, "check_health", None)
                if check is not None:
                    check(sample.t_frame_available)
                r = pipe.step(sample, obs, t_now=sample.t_frame_available)
                monitor.observe(r, pipe)
                backend.pump(3)  # ~ one 33 ms frame of 128-sample callbacks at 48 kHz
            out.stop()
        except Exception as exc:  # noqa: BLE001
            crash = {"type": type(exc).__name__, "message": str(exc)[:300]}
        finally:
            if saved is None:
                sys.modules.pop("sounddevice", None)
            else:
                sys.modules["sounddevice"] = saved
        stats = out.stats() if out is not None else {}
        rows.append(
            {
                "case": case,
                "crash": crash,
                "violations": violations_of(monitor),
                "removed_at_frame": removed_at,
                "reattached_at_frame": reattach_at,
                "streams_opened": backend.opened,
                "open_failures": backend.open_failures,
                "callbacks": sum(s.callbacks for s in backend.streams),
                "audio_stats": stats,
            }
        )
    return {"rows": rows, "totals": {"cases": len(rows), "crashes": sum(1 for r in rows if r["crash"])}}


def _make_audio_output(audio_out, data, clock, backend):
    kwargs = dict(latency=audio_out.OutputLatency.unmeasured(), device_enabled=True, clock=clock)
    try:
        return audio_out.AudioOutput(data, stream_factory=backend, **kwargs)
    except TypeError:  # pre-hardening AudioOutput has no stream_factory; sounddevice is faked instead
        return audio_out.AudioOutput(data, **kwargs)


# ============================================================================ devcapture suite


def devcapture_suite(args, quick: bool) -> dict[str, Any]:
    from spacedrums.app.main import Perception
    from spacedrums.capture import ReplayFrameSource

    data = load_config(MODEL_CONFIG).data
    setups = {"rule": ARM_SETUPS["rule"], "model": ARM_SETUPS["model"]}
    sessions = args.sessions or [
        "data/dev-captures/swing-L2-exp-5",
        "data/dev-captures/swing-L2-exp-6",
        "data/dev-captures/swing-L2-exp-7",
    ]
    rows = []
    references = {}
    for session in sessions:
        src = ReplayFrameSource(ROOT / session)
        views = [(s, src.view(s)) for s in src]
        for setup_name, setup in setups.items():
            cfg = load_config(setup["config"]).data
            ref, ref_obs = _capture_run(cfg, setup, views, Perception)
            references[f"{setup_name}|{session}"] = {
                "commits": [
                    (c.frame_id, str(c.hand_id), str(c.arm), c.zone_id, c.shadow) for c in ref["commits"]
                ],
                "violations": ref["violations"],
                "crash": ref["crash"],
            }
            plans = _devcapture_plans(views, ref_obs, quick)
            for name, plan, stream, hand, start, end in plans:
                res, _ = _capture_run(cfg, setup, views, Perception, plan=plan, stream=stream)
                rows.append(
                    {
                        "session": session,
                        "setup": setup_name,
                        "fault": name,
                        "hand": hand,
                        "start": start,
                        "end": end,
                        "crash": res["crash"],
                        "violations": res["violations"],
                        "audible_commits": len([c for c in res["commits"] if not c.shadow]),
                        "commit_diff": _commit_diff(ref, res, start, end),
                        "reacquisition": reacquisition(res["trace"], hand, end) if hand else None,
                        "valid_fraction": _valid_fraction(res["trace"]),
                    }
                )
    del data
    return {"rows": rows, "references": references, "totals": _dev_totals(rows)}


def _capture_run(cfg, setup, views, perception_cls, *, plan=None, stream=None):
    clock = Ticker()
    pipe = build_pipeline(copy.deepcopy(cfg), active=setup["active"], shadows=setup["shadows"], clock=clock)
    monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
    frames = views
    index = list(range(len(views)))
    if stream:
        index = []
        frames, _ = F.apply_stream_faults(views, stream, index_map=index)
    perception = perception_cls(cfg)
    observations = []

    def keep(i, result):
        observations.append({str(h): hf.track for h, hf in result.hands.items()})

    try:
        out = replay_frames(pipe, frames, plan=plan, perception=perception, monitor=monitor, on_frame=keep)
    finally:
        perception.close()
    monitor.finish()
    out["original_index"] = {c.strike_id: index[c.frame_id] for c in out["commits"]}
    return {**out, "violations": violations_of(monitor)}, observations


def _hand_box(tracks_by_frame, i, hand, margin=0.08):
    """Occluder box around a hand's filtered tip and the reference hand position (ROI-normalized)."""
    track = tracks_by_frame[i].get(hand)
    if track is None or track.tip_filtered is None:
        return None
    x, y = track.tip_filtered
    return (x - 0.12 - margin, y - 0.1 - margin, x + 0.12 + margin, y + 0.35 + margin)


def _devcapture_plans(views, ref_tracks, quick):
    plans = []
    n = len(views)
    for hand in ("LEFT", "RIGHT"):
        live = [i for i in range(n) if ref_tracks[i][hand].status in ("VALID", "DEGRADED")]
        if not live:
            continue
        anchors = [live[len(live) // 3], live[(2 * len(live)) // 3]]
        for anchor in anchors[: 1 if quick else 2]:
            for duration in (3, 6, 9, 30) if not quick else (3, 9):
                start, end = anchor, min(n, anchor + duration)
                boxes = {}
                last = None
                for i in range(start, end):
                    last = _hand_box(ref_tracks, i, hand) or last
                    boxes[i] = last
                if last is None:
                    continue
                plan = F.FaultPlan().image(
                    start,
                    end,
                    "OCCLUSION_MASK",
                    lambda v, i, boxes=boxes: F.mask_region(v, boxes[i]) if boxes.get(i) else v,
                    hand=hand,
                )
                plans.append((f"occlusion-{hand}-{duration}f", plan, None, hand, start, end))
                xs = [ref_tracks[i][hand].tip_filtered[0] for i in live if ref_tracks[i][hand].tip_filtered]
                # the half of the ROI where this hand was observed in the unperturbed replay
                side = (0.0, 0.0, 0.5, 1.0) if float(np.mean(xs)) < 0.5 else (0.5, 0.0, 1.0, 1.0)
                plan2 = F.FaultPlan().image(
                    start, end, "OUT_OF_ROI", lambda v, i, b=side: F.mask_region(v, b), hand=hand
                )
                plans.append((f"out-of-roi-{hand}-{duration}f", plan2, None, hand, start, end))
    mid = n // 2
    for gain, gamma, label in ((0.35, 1.0, "dim"), (0.2, 1.6, "very-dim"), (1.8, 0.7, "bright")):
        plan = F.FaultPlan().image(
            mid, min(n, mid + 30), "LIGHTING", lambda v, i, g=gain, y=gamma: F.adjust_lighting(v, g, y)
        )
        plans.append((f"lighting-{label}-step", plan, None, None, mid, min(n, mid + 30)))
        plan_all = F.FaultPlan().image(
            0, n, "LIGHTING", lambda v, i, g=gain, y=gamma: F.adjust_lighting(v, g, y)
        )
        plans.append((f"lighting-{label}-session", plan_all, None, None, 0, n))
    for kind, dur in (
        ("STALL", 3),
        ("STALL", 9),
        ("DROP_BURST", 3),
        ("TIMESTAMP_JUMP", 6),
        ("FPS_CHANGE", 30),
    ):
        plans.append((f"{kind.lower()}-{dur}f", None, stream_faults(kind, mid, dur), None, mid, mid + dur))
    plan_bg = F.FaultPlan().image(0, n, "BACKGROUND_DISTRACTOR", _distractor)
    plans.append(("background-distractor-session", plan_bg, None, None, 0, n))
    return plans


def _distractor(view, i):
    """A dark stick-like bar sweeping across the upper background of the ROI (SYNTHETIC composite)."""
    out = F.mask_region(view, (0.0, 0.0, 0.0, 0.0))
    h, w = out.roi.shape[:2]
    x = int((0.1 + 0.8 * ((i % 60) / 60.0)) * w)
    y0, y1 = int(0.05 * h), int(0.25 * h)
    out.roi[y0:y1, max(0, x - 3) : min(w, x + 3)] = (40, 30, 20)
    return out


def _commit_diff(ref, res, start, end, *, before=3, after=15):
    """Audible commits added / removed vs the unperturbed replay, inside [start - 3, end + 15] frames.

    Frames are original capture indices (stream faults renumber delivered frames); a commit matches
    when hand, zone and arm agree within +-2 frames.
    """

    def rows(run):
        return [
            (run["original_index"][c.strike_id], str(c.hand_id), c.zone_id, str(c.arm))
            for c in run["commits"]
            if not c.shadow
        ]

    lo, hi = start - before, end + after
    ref_rows = [r for r in rows(ref) if lo <= r[0] <= hi]
    new_rows = [r for r in rows(res) if lo <= r[0] <= hi]
    unmatched = list(new_rows)
    removed = []
    for r in ref_rows:
        hit = next((n for n in unmatched if n[1:] == r[1:] and abs(n[0] - r[0]) <= 2), None)
        if hit is None:
            removed.append(r)
        else:
            unmatched.remove(hit)
    return {"window_frames": [lo, hi], "added": unmatched, "removed": removed}


def _valid_fraction(trace):
    out = {}
    for h in ("LEFT", "RIGHT"):
        s = [r["status"][h] for r in trace]
        out[h] = round(sum(x == "VALID" for x in s) / len(s), 4) if s else None
    return out


def _dev_totals(rows):
    return {
        "runs": len(rows),
        "crashes": sum(1 for r in rows if r["crash"]),
        "violations": sum(sum(r["violations"].values()) for r in rows),
        "added_audible_commits": sum(len(r["commit_diff"]["added"]) for r in rows),
        "removed_audible_commits": sum(len(r["commit_diff"]["removed"]) for r in rows),
        "reacquisition_valid": distribution_ms(
            r["reacquisition"]["valid_s"]
            for r in rows
            if r["reacquisition"] and r["fault"].startswith("occlusion")
        ),
    }


# ============================================================================ fast-hit suite


def fasthit_suite(args, quick: bool) -> dict[str, Any]:
    """Maximum separable hit rate machinery (Phase 17 Open Question; SYNTHETIC, noise-free kinematics).

    Eight strokes at a fixed inter-onset interval (IOI) per pattern: one hand on one zone, alternating
    hands on one zone, alternating hands on two zones. ``t_down = 0.4 * IOI`` (capped at 0.2 s) so a
    same-hand stroke always ends before the next. Per arm: matched fraction and FP with the Phase 09
    matcher. The developer-played measurement with real sticks stays PENDING.
    """
    from spacedrums.app.synthetic import Swing, build_sequence

    rows = []
    iois = (0.4, 0.3, 0.2, 0.15, 0.12, 0.1, 0.08) if not quick else (0.3, 0.12)
    for setup_name, setup in ARM_SETUPS.items():
        data = load_config(setup["config"]).data
        registry = ZoneRegistry.from_config(data["zones"])
        for pattern in ("one_hand_one_zone", "alternating_hands_one_zone", "alternating_hands_two_zones"):
            for ioi in iois:
                t_down = min(0.2, 0.4 * ioi)
                swings = []
                for k in range(8):
                    t = 0.4 + k * ioi
                    if pattern == "one_hand_one_zone":
                        swings.append(Swing(HandId.RIGHT, "snare", t, t_down=t_down))
                    elif pattern == "alternating_hands_one_zone":
                        swings.append(
                            Swing(HandId.RIGHT if k % 2 == 0 else HandId.LEFT, "snare", t, t_down=t_down)
                        )
                    else:
                        hand, zone = (HandId.RIGHT, "snare") if k % 2 == 0 else (HandId.LEFT, "hihat")
                        swings.append(Swing(hand, zone, t, t_down=t_down))
                seq = build_sequence(
                    registry, swings, duration_s=1.2 + 8 * ioi, name=f"fasthit-{pattern}-{ioi}"
                )
                res = run_one(data, setup, list(seq), seq.truth, seq.params["name"])
                for arm, m in res["per_arm"].items():
                    rows.append(
                        {
                            "setup": setup_name,
                            "pattern": pattern,
                            "ioi_s": ioi,
                            "arm": arm,
                            "truth": len(seq.truth),
                            "matched": m["matched"],
                            "fp": len(m["fp"]),
                            "matched_fraction": m["matched"] / len(seq.truth) if seq.truth else None,
                            "violations": res["violations"],
                        }
                    )
    limits = {}
    for r in rows:
        key = f"{r['setup']}|{r['pattern']}|{r['arm']}"
        if r["matched_fraction"] is not None and r["matched_fraction"] >= 0.95 and r["fp"] == 0:
            limits[key] = min(limits.get(key, 9.9), r["ioi_s"])
    return {
        "rows": rows,
        "totals": {
            "runs": len(rows),
            "violations": sum(sum(r["violations"].values()) for r in rows),
            "smallest_separable_ioi_s": dict(sorted(limits.items())),
            "note": "SYNTHETIC noise-free strokes; r_zone = 0.10 s blocks faster same-hand same-zone hits",
        },
    }


# ============================================================================ guard suite


GUARD_RULE = (
    "Declared before the first run (Phase 17, Task 17.4): choose the commit.max_dropped_since_last value "
    "that minimises FP + FN (Phase 09 matcher, W = 50 ms) summed over arms A and B on the injected set "
    "(stalls and drop bursts of 1-3 frames placed around each crossing, sustained 15 and 10 FPS); ties "
    "go to the stricter guard; the chosen value must also produce zero fabricated FPs."
)


def guard_suite(args, quick: bool) -> dict[str, Any]:
    """Frame-drop commit guard threshold experiment (Task 17.4 decision). SYNTHETIC sequences."""
    base = load_config(RULE_CONFIG).data
    registry = ZoneRegistry.from_config(base["zones"])
    thresholds = (0, 1, 2, 3, 99)
    sequences = [("single", 0.12), ("single", 0.2), ("repeated", 0.2), ("alternating_two_zones", 0.2)]
    if not quick:
        sequences += [("single", 0.3), ("repeated", 0.3), ("alternating_two_zones", 0.12)]
    rows = []
    for name, t_down in sequences:
        seq = scenario(name, registry, t_down=t_down)
        frames = list(seq)
        cases: list[tuple[str, list]] = [("none", [])]
        for ev in list(seq.truth)[:2]:
            k = truth_frame(frames, ev.t_cross)
            for n in (1, 2, 3):
                for back in range(0, n + 1):
                    start = max(1, k - back)
                    cases.append((f"STALL{n}@-{back}", [F.Stall(at=start, frames=n)]))
                    cases.append((f"DROP{n}@-{back}", [F.DropBurst(at=start, frames=n)]))
        cases.append(("FPS15", [F.FpsChange(at=1, keep_every=2)]))
        cases.append(("FPS10", [F.FpsChange(at=1, keep_every=3)]))
        for case, faults in cases:
            delivered = F.apply_stream_faults(frames, faults)[0] if faults else frames
            for threshold in thresholds:
                data = deep_merge(base, {"commit": {"max_dropped_since_last": threshold}})
                for active, shadows in (("A", ("B",)), ("B", ("A",))):
                    pipe = build_pipeline(copy.deepcopy(data), active=active, shadows=shadows, clock=Ticker())
                    monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
                    out = replay_frames(pipe, delivered, monitor=monitor)
                    monitor.finish()
                    audible = [c for c in out["commits"] if not c.shadow]
                    m = match(audible, seq.truth, f"{name}-{t_down}")
                    trows = truth_rows(seq.truth, "x")
                    rows.append(
                        {
                            "sequence": f"{name}-t_down{t_down}",
                            "case": case,
                            "threshold": threshold,
                            "arm": active,
                            "truth": len(seq.truth),
                            "matched": m["matched"],
                            "fp": len(m["fp"]),
                            "fn": len(m["fn"]),
                            "fabricated": sum(fp_kind(s, trows) == "fabricated" for s in m["fp"]),
                            "timing_abs_ms": [abs(t) * 1000 for t in m["timing_s"]],
                            "violations": violations_of(monitor),
                        }
                    )
    table = {}
    for threshold in thresholds:
        for arm in ("A", "B"):
            rs = [r for r in rows if r["threshold"] == threshold and r["arm"] == arm and r["case"] != "none"]
            t = [v for r in rs for v in r["timing_abs_ms"]]
            table[f"{threshold}|{arm}"] = {
                "runs": len(rs),
                "matched": sum(r["matched"] for r in rs),
                "fp": sum(r["fp"] for r in rs),
                "fn": sum(r["fn"] for r in rs),
                "fabricated": sum(r["fabricated"] for r in rs),
                "matched_timing_abs_ms_p90": float(np.percentile(t, 90)) if t else None,
            }
    score = {
        th: sum(table[f"{th}|{a}"]["fp"] + table[f"{th}|{a}"]["fn"] for a in ("A", "B")) for th in thresholds
    }
    fabricated = {th: sum(table[f"{th}|{a}"]["fabricated"] for a in ("A", "B")) for th in thresholds}
    eligible = [th for th in thresholds if fabricated[th] == 0]
    chosen = min(eligible, key=lambda th: (score[th], th)) if eligible else None
    return {
        "rule": GUARD_RULE,
        "rows": rows,
        "table": table,
        "totals": {
            "fp_plus_fn_by_threshold": score,
            "fabricated_by_threshold": fabricated,
            "chosen_threshold": chosen,
            "violations": sum(sum(r["violations"].values()) for r in rows),
            "label": "SYNTHETIC development evidence; participant confirmation PENDING",
        },
    }


# ============================================================================ main


SUITES = ("synthetic", "switch", "model", "capture-live", "audio", "devcapture", "fasthit", "guard")
TASK = {
    "synthetic": "17.3",
    "devcapture": "17.3",
    "capture-live": "17.4",
    "switch": "17.5",
    "model": "17.5",
    "audio": "17.5",
    "fasthit": "17.3",
    "guard": "17.4",
    "all": "17.3",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", choices=(*SUITES, "all"), nargs="+", required=True)
    ap.add_argument("--quick", action="store_true", help="reduced grid (tests)")
    ap.add_argument("--sessions", nargs="*", default=None)
    ap.add_argument("--slug", default=None)
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-17")
    add_executor_args(ap)
    args = ap.parse_args()
    suites = SUITES if "all" in args.suite else tuple(args.suite)
    name = "all" if "all" in args.suite else "-".join(suites)
    slug = args.slug or f"inject-{name}{'-quick' if args.quick else ''}"[:40]
    with evidence(
        RULE_CONFIG,
        args,
        slug=slug,
        task=TASK["all" if len(suites) > 1 else suites[0]],
        description="Failure injection (SYNTHETIC sequences / developer captures); development evidence",
        output=args.output,
    ) as (run, _cfg):
        summary = {}
        for suite in suites:
            print(f"[suite] {suite}", flush=True)
            if suite == "synthetic":
                result = synthetic_suite(args, args.quick)
            elif suite == "switch":
                result = switch_suite(args, args.quick)
            elif suite == "model":
                result = model_suite(args, args.quick, run.dir / "tmp")
            elif suite == "capture-live":
                result = capture_live_suite(args, args.quick)
            elif suite == "audio":
                result = audio_suite(args, args.quick)
            elif suite == "fasthit":
                result = fasthit_suite(args, args.quick)
            elif suite == "guard":
                result = guard_suite(args, args.quick)
            else:
                result = devcapture_suite(args, args.quick)
            result["label"] = (
                "DEVELOPMENT: SYNTHETIC sequences / developer captures; not participant evidence"
            )
            write_json(run.dir / f"injection-{suite}.json", _jsonable(result))
            totals = result.get("totals") or result.get("aggregate", {}).get("totals")
            summary[suite] = totals
            print(f"[suite] {suite}: {json.dumps(_jsonable(totals))}", flush=True)
        write_json(run.dir / "summary.json", _jsonable(summary))
        tmp = run.dir / "tmp"
        if tmp.exists():
            import shutil

            shutil.rmtree(tmp)
    return 0


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (np.floating, np.integer)):
        return _jsonable(obj.item())
    if dataclasses.is_dataclass(obj):
        return _jsonable(dataclasses.asdict(obj))
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    return str(obj)


if __name__ == "__main__":
    raise SystemExit(main())
