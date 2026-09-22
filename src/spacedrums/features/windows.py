"""Model-ready histories and offline targets with safety-window retention."""

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from spacedrums.features.streaming import history_arrays
from spacedrums.features.targets import auxiliary_target, trajectory_target


@dataclass(frozen=True)
class WindowParams:
    n: int
    k: int
    h: float
    h_max: float
    stride: int = 1
    g_win: int = 0

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in (self.n, self.k, self.stride)):
            raise ValueError("N, K, stride must be positive integers")
        if type(self.g_win) is not int or not 0 <= self.g_win <= self.n:
            raise ValueError("g_win must be in [0,N]")
        if not all(math.isfinite(x) for x in (self.h, self.h_max)) or not 0 < self.h <= self.h_max:
            raise ValueError("require 0 < H <= H_max")


def segment_for(t, segments):
    matches = [
        s
        for s in segments
        if s["t_start"] is not None and s["t_end"] is not None and s["t_start"] <= t < s["t_end"]
    ]
    if len(matches) > 1:
        raise ValueError("overlapping segment intervals")
    return matches[0] if matches else None


def build_windows(
    tracks,
    records,
    labels,
    segments,
    schema,
    params,
    *,
    participant,
    session_id,
    source_kind,
    fold=None,
    stats=None,
):
    if len(tracks) != len(records):
        raise ValueError("track/feature alignment mismatch")
    if any(
        (t.frame_id, t.t_capture, str(t.hand_id)) != (r.frame_id, r.t_capture, r.hand_id)
        for t, r in zip(tracks, records, strict=True)
    ):
        raise ValueError("track/feature alignment mismatch")
    samples, reasons = [], Counter()
    for hand in sorted({str(t.hand_id) for t in tracks}):
        indices = [i for i, t in enumerate(tracks) if str(t.hand_id) == hand]
        ts, fs = [tracks[i] for i in indices], [records[i] for i in indices]
        segs = [segment_for(t.t_capture, segments) for t in ts]
        keys = [(s["segment_id"], s["take"]) if s and s.get("eligible", True) else None for s in segs]
        for i in range(params.n - 1, len(ts), params.stride):
            start = i - params.n + 1
            history = fs[start : i + 1]
            x, m = history_arrays(history, schema)
            if stats is not None:
                x, m = stats.apply(x, m, schema)
            bad = sum(r.track_status in ("INVALID", "STALE") for r in history)
            why = []
            if fs[i].track_status not in ("VALID", "DEGRADED"):
                why.append("invalid_anchor")
            if bad > params.g_win:
                why.append("gap_threshold")
            if keys[i] is None or any(key != keys[i] for key in keys[start : i + 1]):
                why.append("segment_or_quarantine")
            target, absolute, target_mask, offsets = trajectory_target(ts, i, params.k, keys)
            if not target_mask.any():
                why.append("no_future_target")
            seg = segs[i]
            aux = auxiliary_target(
                labels,
                t=ts[i].t_capture,
                hand_id=hand,
                session_id=session_id,
                segment_id=seg["segment_id"] if seg else "",
                segment_take=seg["take"] if seg else 0,
                end=min(seg["t_end"], ts[-1].t_capture) if seg else ts[i].t_capture,
                h=params.h,
                h_max=params.h_max,
            )
            if aux["ambiguous"]:
                why.append("ambiguous_target")
            if keys[i] is None:
                aux["strike_mask"] = aux["tti_mask"] = aux["impact_mask"] = False
            reasons.update(why)
            samples.append(
                {
                    "X": x,
                    "M": m,
                    "T": target,
                    "T_absolute": absolute,
                    "T_mask": target_mask,
                    "target_offsets_s": offsets,
                    "aux": aux,
                    "anticipation_eligible": not why,
                    "safety_reasons": why,
                    "meta": {
                        "t_i": ts[i].t_capture,
                        "frame_id": ts[i].frame_id,
                        "hand_id": hand,
                        "session_id": session_id,
                        "participant": participant,
                        "fold": fold,
                        "segment_id": seg["segment_id"] if seg else None,
                        "segment_take": seg["take"] if seg else None,
                        "source_kind": source_kind,
                    },
                }
            )
    eligible = [s for s in samples if s["anticipation_eligible"]]
    classes = Counter(
        "POSITIVE" if s["aux"]["strike_within_H"] else "NEGATIVE" for s in eligible if s["aux"]["strike_mask"]
    )
    return samples, {
        "total_windows": len(samples),
        "anticipation_windows": len(eligible),
        "safety_only_windows": len(samples) - len(eligible),
        "reasons": dict(reasons),
        "class_counts": dict(classes),
        "aux_masked": sum(not s["aux"]["strike_mask"] for s in eligible),
        "dropped_window_rate": 1 - len(eligible) / len(samples) if samples else None,
    }


def write_samples(path, samples, schema, params):
    """Numeric tensors + JSON strings, readable with allow_pickle=False, including empty parts."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    shapes = {
        "X": (params.n, schema.dimension),
        "M": (params.n, schema.dimension),
        "T": (params.k, 2),
        "T_absolute": (params.k, 2),
        "T_mask": (params.k,),
        "target_offsets_s": (params.k,),
    }
    arrays = {
        k: np.stack([s[k] for s in samples])
        if samples
        else np.empty((0, *shape), dtype=bool if k in ("M", "T_mask") else float)
        for k, shape in shapes.items()
    }
    arrays.update(
        {
            k: np.asarray([json.dumps(s[k], sort_keys=True, allow_nan=False) for s in samples], dtype=str)
            for k in ("meta", "aux", "safety_reasons")
        }
    )
    arrays["anticipation_eligible"] = np.asarray([s["anticipation_eligible"] for s in samples], dtype=bool)
    arrays["feature_schema_hash"] = np.asarray(schema.fingerprint)
    np.savez_compressed(path, **arrays)
