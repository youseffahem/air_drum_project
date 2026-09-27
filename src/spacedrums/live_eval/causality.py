"""TEST-CAUSAL-1 on the exact evaluated arm versions (pre-registration §4.4; causality-tests.md §2).

Before the confirmatory run, every arm (exact config, controls and model package) replays SYNTHETIC
fixture sessions through the frozen harness. Its outputs for frames ``<= i`` must not change when
the frames after ``i`` are:

* ``GARBAGE``: replaced by VALID track states at random positions, velocities and accelerations;
* ``REMOVED``: truncated;
* ``SHIFTED``: replaced by another session's tracks, re-timed onto the original frame ids and
  capture times.

Cut frames (declared): every 10th frame, plus every frame at which the reference run emitted a
candidate or the track carried a reset.

Records compared up to the cut: predictions, candidates and committed strikes.
``t_inference_done`` is a wall-clock stamp and is excluded. Deterministic arms must be
bit-identical; learned arms may differ by at most ``tolerance`` on numeric fields, with every
non-numeric field identical.

``run_arm`` receives the (perturbed) track list and must rebuild everything downstream of tracks
itself, including feature records for model arms. Otherwise a perturbation would never reach the
model and the check would pass vacuously. :func:`causal_check` also reports ``effective`` per kind:
whether any output *after* the cut changed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

import numpy as np

from spacedrums.contracts import TrackState

KINDS = ("GARBAGE", "REMOVED", "SHIFTED")
WALL_CLOCK_FIELDS = frozenset({"t_inference_done"})
RECORD_LISTS = ("predictions", "candidates", "committed")


def _frame(record: Any) -> int:
    return int(record.frame_id)


def default_cuts(tracks: Sequence[TrackState], reference: Any, *, every: int = 10) -> list[int]:
    frames = sorted({t.frame_id for t in tracks})
    cuts = set(frames[::every])
    cuts |= {_frame(c) for c in reference.candidates}
    cuts |= {t.frame_id for t in tracks if t.reset_reason is not None}
    return sorted(c for c in cuts if c != frames[-1])


def _garbage(t: TrackState, rng: np.random.Generator) -> TrackState:
    return replace(
        t,
        status="VALID",
        tip_filtered=(float(rng.uniform(0, 1)), float(rng.uniform(0, 1))),
        tip_velocity=(float(rng.normal(0, 2)), float(rng.normal(0, 2))),
        tip_acceleration=(float(rng.normal(0, 20)), float(rng.normal(0, 20))),
        confidence=float(rng.uniform(0.6, 1.0)),
        frames_since_valid=0,
        last_valid_t=t.t_capture,
        reset_reason=None,
    )


def perturb(
    tracks: Sequence[TrackState],
    cut_frame: int,
    kind: str,
    *,
    donor: Sequence[TrackState] | None = None,
    seed: int = 0,
) -> list[TrackState]:
    prefix = [t for t in tracks if t.frame_id <= cut_frame]
    suffix = [t for t in tracks if t.frame_id > cut_frame]
    if kind == "REMOVED":
        return prefix
    if kind == "GARBAGE":
        rng = np.random.default_rng(seed + cut_frame)
        return prefix + [_garbage(t, rng) for t in suffix]
    if kind == "SHIFTED":
        if not donor:
            raise ValueError("SHIFTED needs a donor session")
        out = list(prefix)
        for hand in sorted({str(t.hand_id) for t in suffix}):
            slots = [t for t in suffix if str(t.hand_id) == hand]
            source = [t for t in donor if str(t.hand_id) == hand]
            for slot, src in zip(slots, source, strict=False):
                last = None if src.last_valid_t is None else slot.t_capture
                out.append(
                    replace(
                        src,
                        frame_id=slot.frame_id,
                        t_capture=slot.t_capture,
                        last_valid_t=last,
                        reset_reason=None,
                    )
                )
        return sorted(out, key=lambda t: (t.t_capture, t.frame_id, str(t.hand_id)))
    raise ValueError(f"unknown perturbation kind {kind!r}")


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in WALL_CLOCK_FIELDS}


def _numeric_diff(a: Any, b: Any, path: str = "") -> tuple[float, list[str]]:
    """Max absolute numeric difference and the paths of non-numeric mismatches."""
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str):
        return 0.0, ([] if a == b else [path or "<root>"])
    if isinstance(a, int | float) and isinstance(b, int | float):
        if math.isnan(a) and math.isnan(b):
            return 0.0, []
        return abs(float(a) - float(b)), []
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return 0.0, [path + "/<keys>"]
        worst, bad = 0.0, []
        for k in a:
            d, m = _numeric_diff(a[k], b[k], f"{path}/{k}")
            worst, bad = max(worst, d), bad + m
        return worst, bad
    if isinstance(a, list | tuple) and isinstance(b, list | tuple):
        if len(a) != len(b):
            return 0.0, [path + "/<len>"]
        worst, bad = 0.0, []
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            d, m = _numeric_diff(x, y, f"{path}/{i}")
            worst, bad = max(worst, d), bad + m
        return worst, bad
    return 0.0, ([] if a == b else [path or "<root>"])


def compare_prefix(reference: Any, perturbed: Any, cut_frame: int, *, tolerance: float) -> dict[str, Any]:
    failures, worst = [], 0.0
    for name in RECORD_LISTS:
        ref = [_clean(r.to_dict()) for r in getattr(reference, name) if _frame(r) <= cut_frame]
        new = [_clean(r.to_dict()) for r in getattr(perturbed, name) if _frame(r) <= cut_frame]
        if len(ref) != len(new):
            failures.append({"records": name, "reason": f"count {len(ref)} != {len(new)}"})
            continue
        for r, n in zip(ref, new, strict=True):
            if tolerance == 0.0:
                if json.dumps(r, sort_keys=True) != json.dumps(n, sort_keys=True):
                    failures.append(
                        {"records": name, "frame_id": r.get("frame_id"), "reason": "not bit-identical"}
                    )
                continue
            d, bad = _numeric_diff(r, n)
            worst = max(worst, d)
            if bad or d > tolerance:
                failures.append(
                    {
                        "records": name,
                        "frame_id": r.get("frame_id"),
                        "reason": f"max |d| {d:.3g}",
                        "fields": bad[:5],
                    }
                )
    return {"failures": failures, "max_deviation": worst}


def _changed_after(reference: Any, perturbed: Any, cut_frame: int) -> bool:
    for name in RECORD_LISTS:
        a = [
            json.dumps(_clean(r.to_dict()), sort_keys=True)
            for r in getattr(reference, name)
            if _frame(r) > cut_frame
        ]
        b = [
            json.dumps(_clean(r.to_dict()), sort_keys=True)
            for r in getattr(perturbed, name)
            if _frame(r) > cut_frame
        ]
        if a != b:
            return True
    return False


def causal_check(
    run_arm: Callable[[Sequence[TrackState]], Any],
    tracks: Sequence[TrackState],
    *,
    donor: Sequence[TrackState],
    cuts: Sequence[int] | None = None,
    kinds: Sequence[str] = KINDS,
    tolerance: float = 0.0,
    seed: int = 0,
    max_cuts: int | None = None,
) -> dict[str, Any]:
    reference = run_arm(list(tracks))
    chosen = list(cuts) if cuts is not None else default_cuts(tracks, reference)
    if max_cuts is not None and len(chosen) > max_cuts:
        idx = np.linspace(0, len(chosen) - 1, max_cuts).round().astype(int)
        chosen = [chosen[i] for i in sorted(set(idx.tolist()))]
    failures: list[dict[str, Any]] = []
    effective = {k: 0 for k in kinds}
    worst = 0.0
    for cut in chosen:
        for kind in kinds:
            out = run_arm(perturb(tracks, cut, kind, donor=donor, seed=seed))
            result = compare_prefix(reference, out, cut, tolerance=tolerance)
            worst = max(worst, result["max_deviation"])
            failures.extend({"cut": cut, "kind": kind, **f} for f in result["failures"])
            if _changed_after(reference, out, cut):
                effective[kind] += 1
    return {
        "test": "TEST-CAUSAL-1",
        "cuts": len(chosen),
        "kinds": list(kinds),
        "tolerance": tolerance,
        "records": {name: len(getattr(reference, name)) for name in RECORD_LISTS},
        "effective_perturbations": effective,
        "max_deviation": worst,
        "failures": failures[:50],
        "n_failures": len(failures),
        "passed": not failures,
    }


__all__ = ["KINDS", "causal_check", "compare_prefix", "default_cuts", "perturb"]
