"""M3: software-stamped timing of a recorded live session (always an estimate; never decides H4).

Two products, both labelled **SOFTWARE ESTIMATE** (pre-registration §8):

* :func:`decomposition` gives the README §5.3 latency components per arm, from the session's
  ``timing.jsonl``. Each component is computed only where both of its stamps exist; the set of
  terms is always named and never summed into an unnamed "total latency".
* :func:`strike_estimates` gives per sounded strike ``t_out - t_impact_est``: ``L_sys`` for arm A,
  ``TE_audio`` for B / C. ``t_out`` is ``t_audio_out_est`` when the session carries an *accepted*
  Phase 04 output latency. Otherwise ``t_out`` is the scheduled play time ``t_target_play`` and the
  record says the DAC path is excluded; on HW-01 the output latency is PENDING.

Clock guard: a replayed session keeps the original ``t_capture`` but stamps processing on the
replay-time clock, so its components are meaningless. :func:`clock_consistent` rejects every record
whose stamps do not lie on one ``t_mono`` base, and the functions report how many were rejected.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

ESTIMATE_LABEL = "SOFTWARE ESTIMATE (README §5.3 software stamps; not an external measurement)"

# README §5.3 components: (name, start stamp, end stamp).
COMPONENTS: tuple[tuple[str, str, str], ...] = (
    ("camera_capture", "t_capture", "t_frame_available"),
    ("tracking", "t_frame_available", "t_tracking_done"),
    ("features", "t_tracking_done", "t_features_done"),
    ("inference", "t_features_done", "t_inference_done"),
    ("commit", "t_inference_done", "t_commit"),
    ("audio_scheduling", "t_commit", "t_audio_scheduled"),
    ("audio_output", "t_audio_scheduled", "t_audio_out_est"),
)
STAMPS = (
    "t_capture",
    "t_frame_available",
    "t_tracking_done",
    "t_features_done",
    "t_inference_done",
    "t_candidate",
    "t_commit",
    "t_audio_scheduled",
    "t_audio_out_est",
)
# A live stamp may lead t_capture by processing plus scheduling, never by minutes or run backwards.
MAX_AFTER_CAPTURE_S = 5.0
MAX_BEFORE_CAPTURE_S = 0.001


def read_stream(path: str | Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Header-first JSONL record stream -> (header or None, rows)."""
    lines = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if lines and "record_type" in lines[0]:
        return lines[0], lines[1:]
    return None, lines


def clock_consistent(record: Mapping[str, Any]) -> bool:
    t0 = record.get("t_capture")
    if t0 is None:
        return False
    for key in STAMPS[1:]:
        t = record.get(key)
        if t is None:
            continue
        if not (t0 - MAX_BEFORE_CAPTURE_S <= t <= t0 + MAX_AFTER_CAPTURE_S):
            return False
    return True


def _summary(values: Sequence[float]) -> dict[str, Any]:
    x = np.asarray(values, dtype=float)
    if not len(x):
        return {"n": 0, "p50_s": None, "p95_s": None, "max_s": None}
    return {
        "n": len(x),
        "p50_s": float(np.median(x)),
        "p95_s": float(np.percentile(x, 95)),
        "max_s": float(x.max()),
    }


def decomposition(timing: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Per arm (STRIKE records, active and shadow) and per frame (FRAME records): §5.3 components."""
    by_arm: dict[str, dict[str, list[float]]] = {}
    frames: dict[str, list[float]] = {name: [] for name, _, _ in COMPONENTS[:2]}
    rejected = {"FRAME": 0, "STRIKE": 0}
    for rec in timing:
        kind = rec.get("kind")
        if kind not in ("FRAME", "STRIKE"):
            continue
        if not clock_consistent(rec):
            rejected[kind] += 1
            continue
        if kind == "FRAME":
            for name, a, b in COMPONENTS[:2]:
                if rec.get(a) is not None and rec.get(b) is not None:
                    frames[name].append(rec[b] - rec[a])
            continue
        arm = str(rec.get("arm"))
        slot = by_arm.setdefault(arm, {name: [] for name, _, _ in COMPONENTS})
        for name, a, b in COMPONENTS:
            if rec.get(a) is not None and rec.get(b) is not None:
                slot[name].append(rec[b] - rec[a])
    return {
        "label": ESTIMATE_LABEL,
        "components": [{"name": n, "from": a, "to": b} for n, a, b in COMPONENTS],
        "frames": {name: _summary(v) for name, v in frames.items()},
        "by_arm": {
            arm: {name: _summary(v) for name, v in comps.items()} for arm, comps in sorted(by_arm.items())
        },
        "rejected_mixed_clock": rejected,
        "note": "components exist only where both stamps are recorded; no unnamed total is formed",
    }


def strike_estimates(
    committed: Iterable[Mapping[str, Any]],
    audio_events: Iterable[Mapping[str, Any]],
    *,
    output_latency_accepted: bool,
    impact_reference: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Per sounded strike: ``t_out - t_impact_est`` (``L_sys`` for A, ``TE_audio`` for B / C).

    ``impact_reference`` maps ``strike_id`` to the matched reviewed label's ``t_impact_est``
    (harness matching on the recorded session). Without it only arm A has a reference (its own
    detected crossing), so B / C strikes are listed without a value.
    """
    audio = {a["strike_id"]: a for a in audio_events}
    rows, missing_audio = [], 0
    for s in committed:
        if s.get("shadow"):
            continue
        event = audio.get(s["strike_id"])
        if event is None:
            missing_audio += 1
            continue
        if output_latency_accepted and event.get("t_audio_out_est") is not None:
            t_out, dac = float(event["t_audio_out_est"]), "included (accepted output-latency run)"
        else:
            t_out, dac = (
                float(event["t_target_play"]),
                "EXCLUDED (scheduled play time; output latency PENDING)",
            )
        ref = None if impact_reference is None else impact_reference.get(s["strike_id"])
        source = "reviewed label (harness match)" if ref is not None else None
        if ref is None and str(s["arm"]) == "A" and s.get("t_impact_est") is not None:
            ref, source = float(s["t_impact_est"]), "detected crossing (causal track)"
        rows.append(
            {
                "strike_id": s["strike_id"],
                "arm": str(s["arm"]),
                "zone_id": s.get("zone_id"),
                "t_commit": s.get("t_commit"),
                "t_out": t_out,
                "t_impact_reference": ref,
                "reference_source": source,
                "estimate_s": None if ref is None else t_out - ref,
                "quantity": "L_sys" if str(s["arm"]) == "A" else "TE_audio",
                "dac_path": dac,
            }
        )
    by_arm: dict[str, list[float]] = {}
    for r in rows:
        if r["estimate_s"] is not None:
            by_arm.setdefault(r["arm"], []).append(r["estimate_s"])
    return {
        "label": ESTIMATE_LABEL,
        "strikes": rows,
        "by_arm": {arm: _summary(v) for arm, v in sorted(by_arm.items())},
        "sound_before_reference_fraction": {
            arm: float(np.mean(np.asarray(v) < 0)) for arm, v in sorted(by_arm.items()) if v
        },
        "missing_audio_events": missing_audio,
        "output_latency_accepted": output_latency_accepted,
    }


def load_session_streams(session_dir: str | Path) -> dict[str, list[dict[str, Any]]]:
    """``timing.jsonl`` plus the CommittedStrike / AudioEvent record streams of a recorded session."""
    d = Path(session_dir)
    out: dict[str, list[dict[str, Any]]] = {"timing": [], "committed": [], "audio": []}
    if (d / "timing.jsonl").exists():
        out["timing"] = read_stream(d / "timing.jsonl")[1]
    for key, name in (("committed", "CommittedStrike"), ("audio", "AudioEvent")):
        path = d / "records" / f"{name}.jsonl"
        if path.exists():
            out[key] = read_stream(path)[1]
    return out


__all__ = [
    "COMPONENTS",
    "ESTIMATE_LABEL",
    "clock_consistent",
    "decomposition",
    "load_session_streams",
    "read_stream",
    "strike_estimates",
]
