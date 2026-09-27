"""Experiment 1 analysis layer on top of the frozen Phase 09 harness (pre-registration §4-§6).

``spacedrums.eval`` is frozen. This module never changes a harness rule; it only combines harness
outputs.

* :func:`participant_metrics` / :func:`pooled_metrics`: the harness's per-session events regrouped
  per participant (sessions pooled within a participant) and over all participants. Counts and
  active time are summed; lead, timing and zone come from the MATCH events; impact position and
  intensity come from the joined strike and label rows. Spearman ρ is computed here; the harness
  reports Pearson r and MAE.
* :func:`strata`: by hand, zone, segment type and speed tercile, from events joined with labels.
  Stratum keys are properties of labels, never of an arm's output. Lighting and distance strata
  are pooled metrics over the sessions of each level.
* :func:`reference_time_evaluation`: sensitivity S1 (README §10.1 reference time). The frozen
  ``evaluate_session`` runs on rows whose matching time is ``t_ref``, then every lead is recomputed
  from the original ``t_commit``.
* :func:`trajectory_errors`: ADE / FDE against the future *causal tracker* output (Phase 08 target
  semantics), inside contiguous VALID spans only, without extrapolation.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from spacedrums.eval.metrics import distribution, trajectory_metrics
from spacedrums.eval.report import evaluate_session


def _median(values: Sequence[float]) -> float | None:
    return float(np.median(values)) if len(values) else None


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    rho = spearmanr(x, y).statistic
    return None if not math.isfinite(rho) else float(rho)


def _metrics(
    events: Iterable[Mapping[str, Any]],
    *,
    active_s: float,
    strikes: Mapping[str, Mapping],
    labels: Mapping[str, Mapping],
) -> dict[str, Any]:
    matches, fps, fns = [], [], []
    for e in events:
        {"MATCH": matches, "FP": fps, "FN": fns}[e["kind"]].append(e)
    lead = [float(e["lead_s"]) for e in matches]
    te = [
        float(e["t_impact_pred"]) - float(e["t_impact_est"])
        for e in matches
        if e.get("t_impact_pred") is not None
    ]
    zone_ok = [e["zone_pred"] == e["zone_gt"] for e in matches]
    pos_err, intensity = [], []
    for e in matches:
        s, g = strikes.get(e["strike_id"]), labels.get(e["label_id"])
        if s is None or g is None:
            continue
        if s.get("impact_position") is not None and g.get("impact_position") is not None:
            pos_err.append(math.dist(s["impact_position"], g["impact_position"]))
        if s.get("intensity_proxy") is not None and g.get("intensity_proxy_gt") is not None:
            intensity.append((float(s["intensity_proxy"]), float(g["intensity_proxy_gt"])))
    n_gt = len(matches) + len(fns)
    ix, iy = [a for a, _ in intensity], [b for _, b in intensity]
    lead_d = distribution(lead)
    return {
        "matched": len(matches),
        "fp": len(fps),
        "fn": len(fns),
        "ground_truth": n_gt,
        "strikes": len(matches) + len(fps),
        "active_time_s": active_s,
        "fp_per_min": len(fps) * 60.0 / active_s if active_s > 0 else None,
        "fp_fraction": len(fps) / (len(matches) + len(fps)) if (len(matches) + len(fps)) else None,
        "fn_rate": len(fns) / n_gt if n_gt else None,
        "lead_median_s": lead_d["median"],
        "lead_q1_s": lead_d["q1"],
        "lead_q3_s": lead_d["q3"],
        "lead_p10_s": lead_d["p10"],
        "lead_p90_s": lead_d["p90"],
        "lead_positive_fraction": sum(v > 0 for v in lead) / len(lead) if lead else None,
        "te_pred_n": len(te),
        "te_pred_mae_s": float(np.mean(np.abs(te))) if te else None,
        "te_pred_bias_s": float(np.mean(te)) if te else None,
        "te_pred_median_s": _median(te),
        "zone_accuracy": sum(zone_ok) / len(zone_ok) if zone_ok else None,
        "impact_position_error_median": _median(pos_err),
        "impact_position_error_n": len(pos_err),
        "intensity_n": len(intensity),
        "intensity_mae": float(np.mean([abs(a - b) for a, b in intensity])) if intensity else None,
        "intensity_pearson_r": float(np.corrcoef(ix, iy)[0, 1])
        if len(intensity) >= 3 and np.std(ix) > 0 and np.std(iy) > 0
        else None,
        "intensity_spearman_rho": spearman(ix, iy),
    }


def _index(sessions: Sequence[Mapping[str, Any]]) -> tuple[dict, dict]:
    strikes = {s["strike_id"]: s for r in sessions for s in r["strikes"]}
    labels = {g["label_id"]: g for r in sessions for g in r["labels"]}
    return strikes, labels


def participant_metrics(sessions: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """``sessions``: ``{"participant", "session_id", "evaluation", "strikes", "labels"}`` per session."""
    strikes, labels = _index(sessions)
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in sessions:
        grouped[str(r["participant"])].append(r)
    out = {}
    for p, rs in sorted(grouped.items()):
        events = [e for r in rs for e in r["evaluation"]["events"]]
        active = sum(float(r["evaluation"]["pooled"]["active_time_s"]) for r in rs)
        out[p] = {"sessions": len(rs), **_metrics(events, active_s=active, strikes=strikes, labels=labels)}
    return out


def pooled_metrics(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    strikes, labels = _index(sessions)
    events = [e for r in sessions for e in r["evaluation"]["events"]]
    active = sum(float(r["evaluation"]["pooled"]["active_time_s"]) for r in sessions)
    return {"sessions": len(sessions), **_metrics(events, active_s=active, strikes=strikes, labels=labels)}


def event_summary(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compact event data the report figures need: matched leads and timing errors, the zone
    confusion counts and FP counts by segment type, so every figure regenerates from stored results."""
    events = [e for r in sessions for e in r["evaluation"]["events"]]
    matches = [e for e in events if e["kind"] == "MATCH"]
    confusion: dict[tuple[str, str], int] = defaultdict(int)
    for e in matches:
        confusion[(str(e["zone_gt"]), str(e["zone_pred"]))] += 1
    fp_seg: dict[str, int] = defaultdict(int)
    for e in events:
        if e["kind"] == "FP":
            fp_seg[str(e.get("segment_type") or "UNATTRIBUTED")] += 1
    return {
        "lead_s": sorted(float(e["lead_s"]) for e in matches),
        "te_pred_s": sorted(
            float(e["t_impact_pred"]) - float(e["t_impact_est"])
            for e in matches
            if e.get("t_impact_pred") is not None
        ),
        "zone_confusion": [{"actual": a, "predicted": p, "n": n} for (a, p), n in sorted(confusion.items())],
        "fp_by_segment_type": dict(sorted(fp_seg.items())),
    }


def speed_tercile_edges(labels: Iterable[Mapping[str, Any]]) -> list[float] | None:
    """Tercile edges of the ground-truth inward crossing speed over eligible POSITIVE labels."""
    speeds = [
        float(g["intensity_proxy_gt"])
        for g in labels
        if g.get("label_class") == "POSITIVE"
        and not g.get("excluded")
        and g.get("intensity_proxy_gt") is not None
    ]
    if len(speeds) < 3:
        return None
    return [float(v) for v in np.percentile(speeds, [100 / 3, 200 / 3])]


def _tercile(value: float | None, edges: Sequence[float] | None) -> str | None:
    if value is None or edges is None:
        return None
    return "slow" if value <= edges[0] else ("medium" if value <= edges[1] else "fast")


def strata(
    sessions: Sequence[Mapping[str, Any]],
    *,
    speed_edges: Sequence[float] | None,
    session_levels: Mapping[str, Mapping[str, str | None]] | None = None,
) -> dict[str, Any]:
    """By hand, zone, segment type, speed tercile; lighting / distance where two or more levels exist."""
    strikes, labels = _index(sessions)
    events = [e for r in sessions for e in r["evaluation"]["events"]]
    active = sum(float(r["evaluation"]["pooled"]["active_time_s"]) for r in sessions)
    out: dict[str, Any] = {"by_hand": {}, "by_zone": {}, "by_segment_type": {}, "by_speed_tercile": {}}
    hand_active: dict[str, float] = defaultdict(float)
    for r in sessions:
        for hand, m in r["evaluation"]["by_hand"].items():
            hand_active[hand] += float(m["active_time_s"])
    for hand in sorted({e["hand_id"] for e in events} | set(hand_active)):
        out["by_hand"][hand] = _metrics(
            [e for e in events if e["hand_id"] == hand],
            active_s=hand_active[hand],
            strikes=strikes,
            labels=labels,
        )

    def zone_of(e):
        if e["kind"] == "MATCH":
            return e["zone_gt"]
        if e["kind"] == "FN":
            return labels.get(e["label_id"], {}).get("zone_id")
        return strikes.get(e["strike_id"], {}).get("zone_id")

    for zone in sorted({z for z in map(zone_of, events) if z is not None}):
        out["by_zone"][zone] = _metrics(
            [e for e in events if zone_of(e) == zone], active_s=active, strikes=strikes, labels=labels
        )
        out["by_zone"][zone]["fp_per_min_note"] = "FP of this predicted zone per pooled active minute"

    seg_active: dict[str, float] = defaultdict(float)
    for r in sessions:
        for kind, m in r["evaluation"]["by_segment_type"].items():
            seg_active[kind] += float(m["active_time_s"])

    def segment_of(e):
        if e["kind"] in ("MATCH", "FP"):
            return e.get("segment_type")
        return labels.get(e["label_id"], {}).get("segment_type")

    for kind in sorted({k for k in map(segment_of, events) if k is not None} | set(seg_active)):
        out["by_segment_type"][kind] = _metrics(
            [e for e in events if segment_of(e) == kind],
            active_s=seg_active.get(kind, 0.0),
            strikes=strikes,
            labels=labels,
        )

    def speed_of(e):
        if e["kind"] == "FP":
            return None
        g = labels.get(e["label_id"])
        return _tercile(None if g is None else g.get("intensity_proxy_gt"), speed_edges)

    for tercile in ("slow", "medium", "fast"):
        m = _metrics(
            [e for e in events if speed_of(e) == tercile], active_s=0.0, strikes=strikes, labels=labels
        )
        m["fp_per_min"] = None
        m["fp_note"] = "n/a: a false positive has no ground-truth speed"
        out["by_speed_tercile"][tercile] = m
    out["speed_tercile_edges"] = None if speed_edges is None else list(speed_edges)
    for dim in ("lighting_id", "distance_mark"):
        levels: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for r in sessions:
            level = (session_levels or {}).get(r["session_id"], {}).get(dim)
            if level is not None:
                levels[str(level)].append(r)
        key = "by_lighting" if dim == "lighting_id" else "by_distance"
        out[key] = (
            {level: pooled_metrics(rs) for level, rs in sorted(levels.items())}
            if len(levels) >= 2
            else {"note": "fewer than two levels: not stratified"}
        )
    return out


def reference_time_rows(strike_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """S1: rows whose matching time is ``t_ref`` (``t_impact_pred``; detected ``t_impact_est`` for A)."""
    out = []
    for s in strike_rows:
        t_ref = s.get("t_impact_pred") if s.get("t_impact_pred") is not None else s.get("t_impact_est")
        if t_ref is None:
            raise ValueError(f"strike {s['strike_id']} has neither t_impact_pred nor t_impact_est")
        out.append({**s, "t_commit_original": s["t_commit"], "t_commit": float(t_ref)})
    return out


def reference_time_evaluation(
    strike_rows: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    *,
    w_s: float,
    include_unreviewed_selftest: bool = False,
) -> dict[str, Any]:
    """The frozen harness on ``t_ref`` rows; leads then recomputed from the original commit times."""
    rows = reference_time_rows(strike_rows)
    original = {r["strike_id"]: float(r["t_commit_original"]) for r in rows}
    evaluated = evaluate_session(
        rows, list(labels), list(segments), w_s=w_s, include_unreviewed_selftest=include_unreviewed_selftest
    )
    for e in evaluated["events"]:
        if e["kind"] in ("MATCH", "FP"):
            e["t_ref"] = e["t_commit"]
            e["t_commit"] = original[e["strike_id"]]
        if e["kind"] == "MATCH":
            e["lead_s"] = float(e["t_impact_est"]) - e["t_commit"]
    evaluated["matching"] = "S1: README 10.1 reference time (t_impact_pred; detected t_impact_est for A)"
    evaluated["note"] = (
        "pooled/by_* blocks were computed by the harness on t_ref; use the events (leads recomputed "
        "from t_commit) for lead metrics"
    )
    return evaluated


def trajectory_errors(
    predictions: Sequence[Any], tracks: Sequence[Any], *, roi_px: Sequence[int] | None = None
) -> dict[str, Any]:
    """ADE / FDE of predicted points against the future causal track (interpolated inside VALID spans).

    A target point exists only when the track is VALID without reset on both sides of its time and
    on every frame from the prediction's frame up to it. There is no extrapolation beyond the last
    VALID frame, and no bridging of a reset or a loss.
    """
    lanes: dict[str, dict[str, np.ndarray]] = {}
    grouped: dict[str, list[Any]] = defaultdict(list)
    for t in tracks:
        grouped[str(t.hand_id)].append(t)
    for hand, seq in grouped.items():
        ok = np.asarray(
            [t.status == "VALID" and t.reset_reason is None and t.tip_filtered is not None for t in seq]
        )
        run_end = np.arange(len(seq))  # last index of the contiguous VALID run that follows each frame
        for j in range(len(seq) - 2, -1, -1):
            if ok[j + 1]:
                run_end[j] = run_end[j + 1]
        lanes[hand] = {
            "t": np.asarray([t.t_capture for t in seq], dtype=float),
            "xy": np.asarray(
                [t.tip_filtered if t.tip_filtered is not None else (np.nan, np.nan) for t in seq]
            ),
            "run_end": run_end,
        }
    rows_pred, rows_tgt, rows_mask = [], [], []
    k_max = max((len(p.positions) for p in predictions), default=0)
    for p in predictions:
        lane = lanes.get(str(p.hand_id))
        if lane is None:
            continue
        i0 = int(np.searchsorted(lane["t"], p.t_capture))
        if i0 >= len(lane["t"]) or lane["t"][i0] != p.t_capture:
            continue
        valid_until = int(lane["run_end"][i0])
        offsets = p.t_offsets_s or tuple((k + 1) * p.dt_step for k in range(len(p.positions)))
        pred = np.full((k_max, 2), np.nan)
        tgt = np.full((k_max, 2), np.nan)
        mask = np.zeros(k_max, dtype=bool)
        span_t = lane["t"][i0 : valid_until + 1]
        span_xy = lane["xy"][i0 : valid_until + 1]
        for k, (dt, xy) in enumerate(zip(offsets, p.positions, strict=True)):
            t = p.t_capture + dt
            pred[k] = xy
            if valid_until > i0 and span_t[0] <= t <= span_t[-1]:
                tgt[k] = [np.interp(t, span_t, span_xy[:, 0]), np.interp(t, span_t, span_xy[:, 1])]
                mask[k] = True
        rows_pred.append(pred)
        rows_tgt.append(tgt)
        rows_mask.append(mask)
    if not rows_pred:
        return {
            "ade": None,
            "fde": None,
            "valid_points": 0,
            "valid_sequences": 0,
            "predictions": len(predictions),
        }
    pred_a, tgt_a, mask_a = np.stack(rows_pred), np.stack(rows_tgt), np.stack(rows_mask)
    pred_a = np.where(mask_a[..., None], pred_a, 0.0)
    tgt_a = np.where(mask_a[..., None], tgt_a, 0.0)
    result = trajectory_metrics(pred_a, tgt_a, mask_a)
    result["predictions"] = len(predictions)
    result["target"] = "future causal tracker output (Phase 08 target semantics); not the physical tip"
    if roi_px is not None and result["ade"] is not None:
        scale = float(np.hypot(roi_px[2], roi_px[3]) / math.sqrt(2))
        result["pixel_note"] = "pixels = ROI units x mean ROI side (anisotropic ROI: approximate)"
        result["ade_px"] = result["ade"] * scale
        result["fde_px"] = result["fde"] * scale
    return result


__all__ = [
    "participant_metrics",
    "pooled_metrics",
    "reference_time_evaluation",
    "reference_time_rows",
    "spearman",
    "speed_tercile_edges",
    "strata",
    "trajectory_errors",
]
