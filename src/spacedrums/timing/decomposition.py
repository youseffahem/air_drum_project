"""Latency components from ``TimingRecord``s (README section 5.3; Phase 05, Tasks 05.4 / 05.9).

Every quantity here is a **difference of software stamps** on ``t_mono``. Nothing is a measurement of
the physical action-to-sound latency: the audio-output term needs the MEASURED output latency of
the audio profile (``t_audio_out_est`` non-null), and the true ``t_audio_out`` / ``t_acoustic_onset``
exist only after Phase 18's external measurement. Names follow contracts.md section 3.10: a quantity
derived from ``t_audio_out_est`` carries the ``_est`` suffix and the label *software-estimated*;
``L_sys`` without suffix is never produced by this module.

Terms (each is reported only when both stamps are present):

    capture            = t_frame_available - t_capture                     (FRAME)
    tracking           = t_tracking_done   - t_frame_available             (FRAME)
    inference          = t_inference_done  - t_tracking_done               (FRAME; rule arm; no feature
                                                                            stage in Phase 05, so the
                                                                            predecessor is tracking)
    frame_quantization = t_capture(commit frame) - t_impact_est            (STRIKE, reactive only)
    commit             = t_commit - (t_inference_done | t_tracking_done)   (STRIKE; predecessor named)
    audio_dispatch     = t_audio_scheduled - t_commit                      (STRIKE, non-shadow)
    audio_out_est      = t_audio_out_est   - t_audio_scheduled             (STRIKE; software-estimated)
    L_sys_est          = t_audio_out_est   - t_impact_est                  (STRIKE, reactive; = sum of
                                                                            frame_quantization + capture +
                                                                            tracking + commit +
                                                                            audio_dispatch + audio_out_est)
    L_pred             = t_impact_est - t_commit                           (only when t_impact_est is
                                                                            known for the strike)
    TE_pred            = t_impact_pred - t_impact_est                      (idem, anticipatory)

Replay / synthetic runs (``live=False``): ``t_capture`` / ``t_frame_available`` / ``t_impact_*`` /
``t_commit`` are on the *recorded* clock while processing-done and audio stamps are re-stamped live
(architecture.md section 12.1), so every term that mixes the two clocks (``tracking``, ``commit``,
``audio_dispatch``, ``audio_out_est``, ``L_sys_est``) is not computable and is reported as N/A;
``capture``, ``inference`` (live - live), ``frame_quantization``, ``L_pred`` and ``TE_pred`` remain valid.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from spacedrums.contracts import TimingRecord

L_SYS_EST_TERMS = ("frame_quantization", "capture", "tracking", "commit", "audio_dispatch", "audio_out_est")


@dataclass(frozen=True)
class Stats:
    n: int
    median_s: float | None
    p10_s: float | None
    p90_s: float | None
    iqr_s: float | None
    min_s: float | None
    max_s: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "median_s": self.median_s,
            "p10_s": self.p10_s,
            "p90_s": self.p90_s,
            "iqr_s": self.iqr_s,
            "min_s": self.min_s,
            "max_s": self.max_s,
        }


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0, 100]) on an already sorted sequence."""
    if not sorted_vals:
        raise ValueError("empty")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (len(sorted_vals) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac)


def stats(values: Iterable[float]) -> Stats:
    vals = sorted(float(v) for v in values)
    if not vals:
        return Stats(0, None, None, None, None, None, None)
    return Stats(
        len(vals),
        _percentile(vals, 50),
        _percentile(vals, 10),
        _percentile(vals, 90),
        _percentile(vals, 75) - _percentile(vals, 25),
        vals[0],
        vals[-1],
    )


def frame_components(rec: TimingRecord) -> dict[str, float]:
    out: dict[str, float] = {"capture": rec.t_frame_available - rec.t_capture}
    if rec.t_tracking_done is not None:
        out["tracking"] = rec.t_tracking_done - rec.t_frame_available
        if rec.t_inference_done is not None:
            out["inference"] = rec.t_inference_done - rec.t_tracking_done
    return out


def strike_components(rec: TimingRecord) -> dict[str, float]:
    if rec.kind != "STRIKE" or rec.t_commit is None:
        raise ValueError("strike_components needs a STRIKE record")
    out: dict[str, float] = {"capture": rec.t_frame_available - rec.t_capture}
    if rec.t_tracking_done is not None:
        out["tracking"] = rec.t_tracking_done - rec.t_frame_available
    if rec.t_inference_done is not None and rec.t_tracking_done is not None:
        out["inference"] = rec.t_inference_done - rec.t_tracking_done
    pred = rec.t_inference_done if rec.t_inference_done is not None else rec.t_tracking_done
    if pred is not None:
        out["commit"] = rec.t_commit - pred
    if rec.t_impact_est is not None and rec.t_impact_pred is None:
        out["frame_quantization"] = rec.t_capture - rec.t_impact_est
    if rec.t_audio_scheduled is not None:
        out["audio_dispatch"] = rec.t_audio_scheduled - rec.t_commit
        if rec.t_audio_out_est is not None:
            out["audio_out_est"] = rec.t_audio_out_est - rec.t_audio_scheduled
    if rec.t_impact_est is not None:
        out["L_pred"] = rec.t_impact_est - rec.t_commit
        if rec.t_impact_pred is not None:
            out["TE_pred"] = rec.t_impact_pred - rec.t_impact_est
        if rec.t_audio_out_est is not None and rec.t_impact_pred is None:
            out["L_sys_est"] = rec.t_audio_out_est - rec.t_impact_est
    return out


CROSS_CLOCK_TERMS = ("tracking", "commit", "audio_dispatch", "audio_out_est", "L_sys_est")


def decompose(records: Sequence[TimingRecord], *, live: bool = True) -> dict[str, Any]:
    """Per-component distributions for FRAME and STRIKE records (per arm), with the term lists."""
    frames = [r for r in records if r.kind == "FRAME"]
    strikes = [r for r in records if r.kind == "STRIKE"]
    frame_vals: dict[str, list[float]] = {}
    for r in frames:
        for k, v in frame_components(r).items():
            if live or k not in CROSS_CLOCK_TERMS:
                frame_vals.setdefault(k, []).append(v)
    per_arm: dict[str, dict[str, list[float]]] = {}
    for r in strikes:
        arm = str(r.arm) if r.arm is not None else "NA"
        for k, v in strike_components(r).items():
            if live or k not in CROSS_CLOCK_TERMS:
                per_arm.setdefault(arm, {}).setdefault(k, []).append(v)
    return {
        "label": "software-stamped estimate (t_mono stamp differences); not an external measurement",
        "live": live,
        "not_computable": [] if live else list(CROSS_CLOCK_TERMS),
        "n_frames": len(frames),
        "n_strikes": len(strikes),
        "frame": {k: stats(v).to_dict() for k, v in frame_vals.items()},
        "strike_by_arm": {
            arm: {k: stats(v).to_dict() for k, v in comps.items()} for arm, comps in per_arm.items()
        },
        "L_sys_est_terms": list(L_SYS_EST_TERMS),
        "L_sys_est_rule": "L_sys_est = t_audio_out_est - t_impact_est (reactive strikes only); requires a "
        "MEASURED audio output latency for t_audio_out_est; PENDING otherwise",
        "audio_out_est_available": any(r.t_audio_out_est is not None for r in strikes),
    }


def decomposition_table(dec: dict[str, Any]) -> str:
    """README section 5.3-style Markdown table of the decomposition (values in ms, labelled)."""
    lines = [
        "| Component (term) | Scope | n | median ms | p10 ms | p90 ms | Label |",
        "|---|---|---|---|---|---|---|",
    ]

    def row(name: str, scope: str, st: dict[str, Any], label: str) -> None:
        if st["n"] == 0:
            lines.append(f"| {name} | {scope} | 0 | n/a | n/a | n/a | {label} |")
        else:
            lines.append(
                f"| {name} | {scope} | {st['n']} | {1000 * st['median_s']:.2f} | {1000 * st['p10_s']:.2f} | "
                f"{1000 * st['p90_s']:.2f} | {label} |"
            )

    for k, st in dec["frame"].items():
        row(k, "FRAME", st, "software-stamped")
    for arm, comps in dec["strike_by_arm"].items():
        for k, st in comps.items():
            label = "software-estimated" if k.endswith("_est") else "software-stamped"
            row(k, f"STRIKE arm {arm}", st, label)
    if not dec["audio_out_est_available"]:
        lines.append(
            "| audio_out_est / L_sys_est | STRIKE | 0 | n/a | n/a | n/a | PENDING: no MEASURED audio output "
            "latency for the audio profile (Phase 04 criterion 6) |"
        )
    if dec.get("not_computable"):
        lines.append(
            f"| {', '.join(dec['not_computable'])} | FRAME/STRIKE | 0 | n/a | n/a | n/a | N/A in replay/"
            "synthetic runs: recorded clock vs live re-stamped clock (architecture.md 12.1) |"
        )
    return "\n".join(lines)


__all__ = [
    "CROSS_CLOCK_TERMS",
    "L_SYS_EST_TERMS",
    "Stats",
    "decompose",
    "decomposition_table",
    "frame_components",
    "stats",
    "strike_components",
]
