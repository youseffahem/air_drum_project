"""Phase 17 evidence helpers: failure injection, invariant replays, DEGRADED experiment, soak.

Every result produced with these helpers is DEVELOPMENT evidence (SYNTHETIC sequences, the three
developer swing captures, the SYNTHETIC P07 session, a synthetic-trained model); none is
participant evidence. Executor provenance is an explicit argument (``--executor-model`` /
``--executor-effort``): Phase 13 found a verifier that hard-coded its first executor.
"""

from __future__ import annotations

import argparse
import math
import os
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
from _p10 import provenance, source_hashes, write_json
from _runlog import RunLog, git_dirty, git_sha

from spacedrums.app import AudioOutput, DecisionPipeline, OutputLatency
from spacedrums.app.arms import build_model_arm
from spacedrums.app.invariants import InvariantMonitor
from spacedrums.config import load_config
from spacedrums.contracts import HandId, TrackStatus
from spacedrums.eval.constants import W_CANDIDATE_DEFAULT_S
from spacedrums.eval.matching import match_events
from spacedrums.geometry import ZoneRegistry
from spacedrums.timing import wall_clock_iso

ROOT = Path(__file__).resolve().parents[1]
RULE_CONFIG = ROOT / "configs" / "prototype.candidate.yaml"
MODEL_CONFIG = ROOT / "configs" / "live.arm-C.candidate.yaml"
OUTPUT = ROOT / "experiments" / "phase-17"
CONFIG_HASH = "sha256:" + "0" * 64  # evidence pipelines record the resolved config hash in run.json
W = W_CANDIDATE_DEFAULT_S
LIVE = (TrackStatus.VALID, TrackStatus.DEGRADED)


def enable_fault_injection() -> None:
    """Scripts that inject faults are test builds (``spacedrums.app.faults.require_test_build``)."""
    os.environ["SPACEDRUMS_FAULT_INJECTION"] = "1"


def add_executor_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--executor-model", default="UNVERIFIED", help="who runs this (recorded, never inferred)")
    ap.add_argument("--executor-effort", default="UNVERIFIED")


def execution(args) -> dict[str, Any]:
    p = provenance()
    p["codex_model"] = args.executor_model
    p["codex_reasoning_effort"] = args.executor_effort
    p["executor_note"] = "executor fields are command-line arguments (Phase 17); never inferred"
    return p


@contextmanager
def evidence(config_path, args, *, slug: str, task: str, description: str, output: Path = OUTPUT):
    cfg = load_config(config_path)
    with RunLog(
        phase="17", task=task, slug=slug, config=cfg, experiments_dir=Path(output), description=description
    ) as run:
        initial = source_hashes()
        write_json(run.dir / "execution.json", execution(args))
        write_json(run.dir / "source-hashes-start.json", initial)
        yield run, cfg
        final = source_hashes()
        audit = {
            "source_unchanged": initial == final,
            "git_sha_final": git_sha(),
            "git_dirty_final": git_dirty(),
            "finished_at": wall_clock_iso(),
        }
        write_json(run.dir / "audit.json", audit)
        if initial != final:
            raise RuntimeError("source changed during measurement")
        for p in sorted(run.dir.rglob("*")):
            if p.is_file() and p.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(p, "other")
        run.finish(audit, status="COMPLETED", notes="Dirty-tree values are development diagnostics only.")
        print(f"EVIDENCE: {run.dir}", flush=True)


class Ticker:
    """Deterministic ``timing.now`` substitute (strictly increasing)."""

    def __init__(self, start: float = 500.0, step: float = 0.0005) -> None:
        self.t, self.step = start, step

    def __call__(self) -> float:
        self.t += self.step
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def build_pipeline(
    data: dict[str, Any],
    *,
    active: str,
    shadows: Sequence[str],
    clock: Callable[[], float],
    model_factory=build_model_arm,
    session_id: str = "p17",
    audio: bool = True,
) -> DecisionPipeline:
    registry = ZoneRegistry.from_config(data["zones"])
    out = (
        AudioOutput(data, latency=OutputLatency.unmeasured(), device_enabled=False, clock=clock)
        if audio
        else None
    )
    return DecisionPipeline(
        data,
        registry=registry,
        session_id=session_id,
        active_arm=active,
        shadow_arms=tuple(shadows),
        hardware_id="HW-01",
        config_hash=CONFIG_HASH,
        audio=out,
        clock=clock,
        gain_fn=None if audio else (lambda _z, _v: 1.0),
        model_factory=model_factory,
    )


# ----------------------------------------------------------------------------- scoring


def strike_rows(commits, session_id: str) -> list[dict[str, Any]]:
    return [
        {
            "session_id": session_id,
            "hand_id": str(c.hand_id),
            "t_commit": float(c.t_commit),
            "zone_id": c.zone_id,
            "arm": str(c.arm),
            "shadow": bool(c.shadow),
            "strike_id": c.strike_id,
            "frame_id": c.frame_id,
        }
        for c in commits
    ]


def truth_rows(truth, session_id: str) -> list[dict[str, Any]]:
    return [
        {
            "session_id": session_id,
            "hand_id": str(t.hand),
            "t_impact_est": float(t.t_cross),
            "zone_id": t.zone_id,
        }
        for t in truth
    ]


def match(commits, truth, session_id: str, *, w: float = W) -> dict[str, Any]:
    """Phase 09 harness matching (``eval.matching``) of committed strikes to SYNTHETIC truth."""
    result = match_events(strike_rows(commits, session_id), truth_rows(truth, session_id), w_s=w)
    return {
        "matched": len(result.pairs),
        "fp": [dict(s) for s in result.false_positives],
        "fn": [dict(g) for g in result.false_negatives],
        "timing_s": [float(s["t_commit"]) - float(g["t_impact_est"]) for s, g in result.pairs],
    }


def in_window(t: float, window: tuple[float, float]) -> bool:
    return window[0] <= t <= window[1]


def fp_kind(strike: dict[str, Any], truth_rows_: Sequence[dict[str, Any]], *, near_s: float = 0.3) -> str:
    """``mistimed`` when a same-hand truth event lies within ``near_s`` (a real strike committed late
    or early), ``fabricated`` when nothing happened for that hand around the commit."""
    for g in truth_rows_:
        if g["hand_id"] == strike["hand_id"] and abs(float(g["t_impact_est"]) - strike["t_commit"]) <= near_s:
            return "mistimed"
    return "fabricated"


def window_delta(
    injected: dict[str, Any],
    reference: dict[str, Any],
    window: tuple[float, float],
    truth: Sequence[Any] = (),
) -> dict:
    """FP / FN inside the attribution window, injected run minus unperturbed reference run.

    FPs are split into *fabricated* (no same-hand truth within 0.3 s) and *mistimed* (a real strike
    committed outside the matching tolerance, which also produces an FN).
    """
    rows = truth_rows(truth, "x") if truth else []
    fp_i = [s for s in injected["fp"] if in_window(s["t_commit"], window)]
    fp_r = [s for s in reference["fp"] if in_window(s["t_commit"], window)]
    fn_i = [g for g in injected["fn"] if in_window(g["t_impact_est"], window)]
    fn_r = [g for g in reference["fn"] if in_window(g["t_impact_est"], window)]
    fab_i = sum(fp_kind(s, rows) == "fabricated" for s in fp_i)
    fab_r = sum(fp_kind(s, rows) == "fabricated" for s in fp_r)
    return {
        "fp_window": len(fp_i),
        "fp_window_reference": len(fp_r),
        "fp_delta": len(fp_i) - len(fp_r),
        "fp_fabricated_delta": fab_i - fab_r,
        "fp_mistimed_delta": (len(fp_i) - fab_i) - (len(fp_r) - fab_r),
        "fn_window": len(fn_i),
        "fn_window_reference": len(fn_r),
        "fn_delta": len(fn_i) - len(fn_r),
        "fp_outside_delta": (len(injected["fp"]) - len(fp_i)) - (len(reference["fp"]) - len(fp_r)),
        "fn_outside_delta": (len(injected["fn"]) - len(fn_i)) - (len(reference["fn"]) - len(fn_r)),
    }


def distribution_ms(values: Iterable[float]) -> dict[str, Any]:
    x = np.asarray([v for v in values if v is not None], dtype=float) * 1000.0
    if not len(x):
        return {"n": 0, "median_ms": None, "p90_ms": None, "max_ms": None}
    return {
        "n": int(len(x)),
        "median_ms": float(np.median(x)),
        "p90_ms": float(np.percentile(x, 90)),
        "max_ms": float(x.max()),
        "min_ms": float(x.min()),
    }


# ----------------------------------------------------------------------------- one replay


def replay_frames(
    pipeline: DecisionPipeline,
    frames: Sequence[tuple[Any, Any]],
    *,
    plan=None,
    perception=None,
    monitor: InvariantMonitor | None = None,
    on_frame: Callable[[int, Any], None] | None = None,
    delta_proc_s: float = 0.0,
) -> dict[str, Any]:
    """Frame-ordered replay: (sample, observations | FrameView) -> pipeline -> monitor.

    ``plan`` (``faults.FaultPlan``) perturbs images before perception and observations after it.
    Returns per-frame traces (statuses, commits, predictions) and whether the run crashed.
    """
    trace: list[dict[str, Any]] = []
    commits = []
    crash = None
    for i, (sample, payload) in enumerate(frames):
        try:
            if perception is not None:
                view = plan.apply_image(payload, i) if plan is not None else payload
                obs = perception(view)
            else:
                obs = payload
            if plan is not None:
                obs = plan.apply_observations(obs, i)
            result = pipeline.step(sample, obs, t_now=sample.t_frame_available + delta_proc_s)
            if monitor is not None:
                monitor.observe(result, pipeline)
        except Exception as exc:  # noqa: BLE001 - a crash is an outcome the report must record
            crash = {"frame": i, "type": type(exc).__name__, "message": str(exc)[:300]}
            break
        commits.extend(result.commits)
        trace.append(
            {
                "i": i,
                "frame_id": sample.frame_id,
                "t": sample.t_capture,
                "status": {str(h): str(hf.track.status) for h, hf in result.hands.items()},
                "reset": {
                    str(h): (str(hf.track.reset_reason) if hf.track.reset_reason else None)
                    for h, hf in result.hands.items()
                },
                "rule_pred": {str(h): hf.prediction is not None for h, hf in result.hands.items()},
                "model_pred": {str(h): hf.model_prediction is not None for h, hf in result.hands.items()},
                "commits": len(result.commits),
            }
        )
        if on_frame is not None:
            on_frame(i, result)
    return {"trace": trace, "commits": commits, "crash": crash}


def reacquisition(trace: Sequence[dict[str, Any]], hand: str, end_index: int) -> dict[str, Any]:
    """Time from the first frame after the fault interval to the first VALID state / predictions."""
    after = [row for row in trace if row["i"] >= end_index]
    if not after:
        return {"valid_s": None, "rule_pred_s": None, "model_pred_s": None, "first_after_status": None}
    t0 = after[0]["t"]

    def first(pred):
        return next((row["t"] - t0 for row in after if pred(row)), None)

    return {
        "first_after_status": after[0]["status"][hand],
        "valid_s": first(lambda r: r["status"][hand] == "VALID"),
        "rule_pred_s": first(lambda r: r["rule_pred"][hand]),
        "model_pred_s": first(lambda r: r["model_pred"][hand]),
    }


def status_sequence(trace: Sequence[dict[str, Any]], hand: str, start: int, end: int) -> list[str]:
    return [row["status"][hand] for row in trace if start <= row["i"] < end]


def expected_loss_statuses(
    statuses: Sequence[str], times: Sequence[float], g_max: int, age_max: float
) -> bool:
    """README section 8 for a hand with no usable observation from the first listed frame on:
    DEGRADED bridge for at most g_max frames, then INVALID, STALE once last-valid is older than age_max.
    ``times`` are relative to the last VALID frame before the loss."""
    for k, (s, t) in enumerate(zip(statuses, times, strict=True)):
        if k < g_max:
            ok = s == "DEGRADED" or (s == "STALE" and t > age_max)
        else:
            ok = s == ("STALE" if t > age_max else "INVALID") or (s == "INVALID" and t <= age_max)
        if not ok:
            return False
    return True


def violations_of(monitor: InvariantMonitor | None) -> dict[str, int]:
    if monitor is None:
        return {}
    return {k: v for k, v in monitor.counts.items() if v}


def truth_frame(frames, t_cross: float) -> int:
    """Index of the first delivered frame at/after an analytic crossing."""
    for i, (sample, _payload) in enumerate(frames):
        if sample.t_capture >= t_cross:
            return i
    return len(frames) - 1


def idle_start(frames, truth, duration: int, *, clearance_s: float = 0.3) -> int | None:
    """First start index whose whole interval stays ``clearance_s`` away from every crossing."""
    times = [s.t_capture for s, _ in frames]
    crossings = [t.t_cross for t in truth]
    for start in range(1, len(frames) - duration):
        a, b = times[start], times[min(len(times) - 1, start + duration)]
        if all(c < a - clearance_s or c > b + clearance_s for c in crossings):
            return start
    return None


def count_by(rows: Iterable[dict[str, Any]], *keys: str) -> dict[str, int]:
    return dict(sorted(Counter("|".join(str(r[k]) for k in keys) for r in rows).items()))


def hand_side_dx(hand: HandId | str) -> float:
    return 1.0 if str(hand) == "RIGHT" else -1.0


def finite(x: float | None) -> bool:
    return x is not None and math.isfinite(x)


__all__ = [
    "LIVE",
    "MODEL_CONFIG",
    "OUTPUT",
    "RULE_CONFIG",
    "W",
    "Ticker",
    "add_executor_args",
    "build_pipeline",
    "count_by",
    "distribution_ms",
    "enable_fault_injection",
    "evidence",
    "execution",
    "expected_loss_statuses",
    "finite",
    "fp_kind",
    "hand_side_dx",
    "idle_start",
    "in_window",
    "match",
    "reacquisition",
    "replay_frames",
    "status_sequence",
    "strike_rows",
    "truth_frame",
    "truth_rows",
    "violations_of",
    "window_delta",
]
