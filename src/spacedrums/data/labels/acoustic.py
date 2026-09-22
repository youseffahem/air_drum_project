"""Acoustic onset ground truth on the pad + microphone subset (Phase 07, Task 07.6).

ADR-0002 makes the practice pad plus a microphone the **only physical reference** for an impact
instant. This module detects onsets in the session's microphone track (reusing the Phase 06
detector ``spacedrums.data.audio_capture.detect_onsets``), maps them onto ``t_mono``, pairs each
onset with the geometric label of the same pad zone, and reports the distribution of
``t_impact_phys - t_impact_est``.

What the result is and is not:

* It is a **measured offset** between two differently defined instants - the geometric surface
  crossing of the stick tip and the acoustic onset of the sound the pad made. It is never a claim
  that the two are the same instant, and never a correction applied silently to labels.
* The microphone path has its own latency (acoustic travel plus capture). The bound is recorded
  per session in ``mic_latency_bound_s`` and stated with every residual; a residual smaller than
  the bound is not evidence of anything.
* The sync residual from the Phase 06 clap check (``verify.json -> sync``) bounds how well the
  audio track is aligned to ``t_mono`` at all, and is carried into every paired label.

The three-level ``has_phys_gt`` invariant of ``contracts.md`` section 6 is enforced here: a label
receives ``t_impact_phys`` only when its session has a microphone track, its segment condition is
``PAD``, its zone is that segment's ``pad_zone_id`` and an onset paired inside the window.

**Status without recordings.** No pad and no microphone are inventoried and no session with a
person exists (Phase 06 conditions C-06-3 / C-06-4), so ``pair_session`` returns the explicit
``available = false`` result with the reason, and every ``t_impact_phys`` stays null. That is the
PENDING branch the phase document's acceptance criterion 4 provides for; it is not a measurement.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spacedrums.data.audio_capture import detect_onsets
from spacedrums.data.labels.schema import LabelClass
from spacedrums.data.metadata import SessionMetadata
from spacedrums.data.validation import VERIFY_FILENAME

DEFAULT_PAIR_WINDOW_S = 0.15
"""How far an onset may lie from a geometric label to be paired with it (candidate)."""

DEFAULT_MIC_LATENCY_BOUND_S = 0.005
"""Candidate upper bound on the microphone path: ~1 m of air (about 3 ms) plus capture buffering.
Replaced by a measured bound when a microphone is inventoried (C-06-3)."""


@dataclass(frozen=True)
class Pairing:
    label_id: str
    onset_index: int
    onset_t_mono: float
    t_impact_est: float
    residual_s: float
    zone_id: str
    segment_id: str


@dataclass(frozen=True)
class PairResult:
    """Outcome of pairing one session; ``available = False`` is a first-class, explained outcome."""

    available: bool
    reason: str | None
    n_pad_positives: int
    n_onsets: int
    n_paired: int
    pairings: tuple[Pairing, ...]
    mic_latency_bound_s: float | None
    sync_residual_rms_s: float | None
    evidence_label: str

    @property
    def residuals_s(self) -> tuple[float, ...]:
        return tuple(p.residual_s for p in self.pairings)

    def stats(self) -> dict[str, float | None]:
        r = sorted(self.residuals_s)
        if not r:
            return {"bias_s": None, "iqr_s": None, "min_s": None, "max_s": None,
                    "fraction_paired": 0.0 if not self.n_pad_positives else 0.0}
        n = len(r)
        med = r[n // 2] if n % 2 else 0.5 * (r[n // 2 - 1] + r[n // 2])
        if n >= 4:
            lo_h, hi_h = r[: n // 2], r[(n + 1) // 2 :]
            q1 = lo_h[len(lo_h) // 2] if len(lo_h) % 2 else 0.5 * (lo_h[len(lo_h) // 2 - 1]
                                                                   + lo_h[len(lo_h) // 2])
            q3 = hi_h[len(hi_h) // 2] if len(hi_h) % 2 else 0.5 * (hi_h[len(hi_h) // 2 - 1]
                                                                   + hi_h[len(hi_h) // 2])
            iqr = q3 - q1
        else:
            iqr = r[-1] - r[0]
        return {
            "bias_s": float(med),
            "iqr_s": float(iqr),
            "min_s": float(r[0]),
            "max_s": float(r[-1]),
            "fraction_paired": float(self.n_paired / self.n_pad_positives)
            if self.n_pad_positives
            else 0.0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "n_pad_positives": self.n_pad_positives,
            "n_onsets": self.n_onsets,
            "n_paired": self.n_paired,
            "mic_latency_bound_s": self.mic_latency_bound_s,
            "sync_residual_rms_s": self.sync_residual_rms_s,
            "evidence_label": self.evidence_label,
            **self.stats(),
        }


def pad_segments(meta: SessionMetadata) -> list[dict[str, Any]]:
    """Recorded segments whose condition is PAD (each with its single ``pad_zone_id``)."""
    return [s for s in meta.data["segments"] if s["condition"] == "PAD" and s["pad_zone_id"]]


def pair_onsets(
    labels: Sequence[dict[str, Any]],
    onset_times: Sequence[float],
    meta: SessionMetadata,
    *,
    window_s: float = DEFAULT_PAIR_WINDOW_S,
) -> list[Pairing]:
    """Greedy nearest one-to-one pairing of onsets with POSITIVE labels on the pad zone.

    A label is eligible only if it satisfies the ``has_phys_gt`` invariant: it lies inside a PAD
    segment and its zone is that segment's ``pad_zone_id``. Strikes on other zones during a pad
    segment have no physical ground truth and are never paired.
    """
    segs = {(str(s["segment_id"]), int(s.get("take") or 1)): s for s in pad_segments(meta)}
    eligible = [
        rec
        for rec in labels
        if rec["label_class"] == str(LabelClass.POSITIVE)
        and rec["t_impact_est"] is not None
        and not rec["excluded"]
        and (rec["segment_id"], int(rec["segment_take"] or 1)) in segs
        and rec["zone_id"] == segs[(rec["segment_id"], int(rec["segment_take"] or 1))]["pad_zone_id"]
    ]
    candidates = sorted(
        (abs(float(o) - float(rec["t_impact_est"])), i, k)
        for i, rec in enumerate(eligible)
        for k, o in enumerate(onset_times)
        if abs(float(o) - float(rec["t_impact_est"])) <= window_s
    )
    used_labels: set[int] = set()
    used_onsets: set[int] = set()
    out: list[Pairing] = []
    for _, i, k in candidates:
        if i in used_labels or k in used_onsets:
            continue
        used_labels.add(i)
        used_onsets.add(k)
        rec = eligible[i]
        out.append(
            Pairing(
                label_id=rec["label_id"],
                onset_index=k,
                onset_t_mono=float(onset_times[k]),
                t_impact_est=float(rec["t_impact_est"]),
                residual_s=float(onset_times[k]) - float(rec["t_impact_est"]),
                zone_id=rec["zone_id"],
                segment_id=rec["segment_id"],
            )
        )
    out.sort(key=lambda p: p.onset_t_mono)
    return out


def onsets_on_t_mono(
    session_dir: Path, meta: SessionMetadata, **detect_kwargs: Any
) -> tuple[list[float], float | None] | None:
    """Onset instants of the session's microphone track mapped onto ``t_mono``.

    ``None`` when the session has no usable audio track. The mapping is
    ``t_mono = t_mono_at_audio_start + sample_offset``; the Phase 06 recorder stores the audio start
    on ``t_mono`` beside the WAV (``audio_track_ref``), and the clap sync residual from
    ``verify.json`` bounds how good that mapping is.
    """
    ref = meta.data.get("audio_track_ref")
    if not ref:
        return None
    wav = session_dir / ref
    if not wav.exists():
        return None
    try:
        import soundfile as sf
    except ImportError:  # pragma: no cover - soundfile is a pinned runtime dependency
        return None
    samples, rate = sf.read(str(wav), always_2d=False)
    t0 = float(meta.data.get("pad_mic", {}).get("t_mono_at_audio_start", meta.data["t_mono_at_start"]))
    onsets = [t0 + t for t in detect_onsets(samples, int(rate), **detect_kwargs)]
    residual = None
    verify = session_dir / VERIFY_FILENAME
    if verify.exists():
        sync = json.loads(verify.read_text(encoding="utf-8")).get("sync") or {}
        residual = sync.get("residual_rms_s")
    return onsets, residual


def pair_session(
    session_dir: str | Path,
    labels: Sequence[dict[str, Any]],
    *,
    window_s: float = DEFAULT_PAIR_WINDOW_S,
    mic_latency_bound_s: float = DEFAULT_MIC_LATENCY_BOUND_S,
    onset_times: Sequence[float] | None = None,
) -> PairResult:
    """Pair a session's labels with its acoustic onsets, or explain why it cannot be done."""
    session_dir = Path(session_dir)
    meta = SessionMetadata.read(session_dir)
    segs = pad_segments(meta)
    n_pad_pos = sum(
        1
        for rec in labels
        if rec["label_class"] == str(LabelClass.POSITIVE) and rec["segment_type"] == "PAD_MIC"
    )
    label = f"{meta.kind} session"
    if not meta.data["has_phys_gt"]:
        return PairResult(False, "session has_phys_gt is false (no microphone track / no PAD segment)",
                          n_pad_pos, 0, 0, (), None, None, label)
    if not segs:
        return PairResult(False, "no PAD segment recorded", n_pad_pos, 0, 0, (), None, None, label)
    residual = None
    if onset_times is None:
        got = onsets_on_t_mono(session_dir, meta)
        if got is None:
            return PairResult(False, "no usable microphone track for this session", n_pad_pos, 0, 0,
                              (), None, None, label)
        onset_times, residual = got
    pairings = pair_onsets(labels, onset_times, meta, window_s=window_s)
    return PairResult(
        available=True,
        reason=None,
        n_pad_positives=n_pad_pos,
        n_onsets=len(onset_times),
        n_paired=len(pairings),
        pairings=tuple(pairings),
        mic_latency_bound_s=float(mic_latency_bound_s),
        sync_residual_rms_s=residual,
        evidence_label=label,
    )


def apply_pairings(
    labels: Sequence[dict[str, Any]], result: PairResult, meta: SessionMetadata
) -> list[dict[str, Any]]:
    """Return the labels with ``t_impact_phys`` / ``phys`` filled for the paired events only.

    Labels of other zones, other segments or unpaired events keep ``t_impact_phys = null``; that is
    the per-strike level of the ``has_phys_gt`` invariant and it is what every metric that uses
    physical ground truth must count against.
    """
    by_id = {p.label_id: p for p in result.pairings}
    segs = {(str(s["segment_id"]), int(s.get("take") or 1)): s for s in pad_segments(meta)}
    out = []
    for rec in labels:
        rec = json.loads(json.dumps(rec))
        p = by_id.get(rec["label_id"])
        if p is not None:
            seg = segs[(rec["segment_id"], int(rec["segment_take"] or 1))]
            rec["t_impact_phys"] = p.onset_t_mono
            rec["phys"] = {
                "onset_index": p.onset_index,
                "onset_t_mono": p.onset_t_mono,
                "residual_s": p.residual_s,
                "mic_latency_bound_s": float(result.mic_latency_bound_s or 0.0),
                "pad_zone_id": seg["pad_zone_id"],
                "sync_residual_rms_s": result.sync_residual_rms_s,
            }
        out.append(rec)
    return out


__all__ = [
    "DEFAULT_MIC_LATENCY_BOUND_S",
    "DEFAULT_PAIR_WINDOW_S",
    "PairResult",
    "Pairing",
    "apply_pairings",
    "onsets_on_t_mono",
    "pad_segments",
    "pair_onsets",
    "pair_session",
]
