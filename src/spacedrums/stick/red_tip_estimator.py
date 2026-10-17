"""``MARKER`` endpoint estimator over red-painted stick tips: the bridge into the existing contracts.

One detection + tracking pass per frame serves both hands (:meth:`RedTipEndpointEstimator.observe`);
``estimate(view, hand)`` keeps the ``TipEstimator`` protocol for per-hand callers. Per slot state:

* OBSERVED / WEAK / DARK -> present ``StickObservation`` + ``MEASURED`` evidence (``RED_TIP`` /
  ``RED_TIP_WEAK`` / ``RED_TIP_DARK``) with the configured confidence class, so the existing tracker treats
  it as VALID.
* AMBIGUOUS / CLIPPED / WEAK_LIMIT / LOW_EVIDENCE -> absent observation + ``UNCERTAIN`` evidence carrying the
  *observed* centre for diagnostics only: identity, centre or the cap itself is not trustworthy, so no stroke
  can use it.
* PREDICTED -> absent + ``UNCERTAIN`` with **no coordinates**: a prediction never reaches the pipeline.
* NO_TRACK -> absent + ``MISSING``.

The detector and tracker follow ``stick_tip.detector``: ``redness`` (stick/red_tip_caps.py +
stick/red_tip_evidence.py, the default) or ``colour`` (stick/red_tip.py + stick/red_tip_tracker.py).

Every record carries ``method_id = MARKER`` and the class logs :data:`MARKER_WARNING` (integrity I-7,
REQ-211): painted tips are a coloured-marker condition and no result may be presented as markerless.
Without hand evidence the axis fields are the blob's principal axis with ``axis_confidence = 0`` and the
origin is the tip itself; with hand assist they come from the grip (``hands.grip``).
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, replace

import numpy as np

from spacedrums.capture.roi import Roi
from spacedrums.contracts import FrameView, HandId, HandObservation, StickObservation, TipMethod
from spacedrums.contracts.perception import EndpointEvidence
from spacedrums.hands.grip import GripSettings, grip_reference
from spacedrums.stick.red_tip import RedBlob, RedTipDetector, RedTipSettings
from spacedrums.stick.red_tip_caps import CapDetector
from spacedrums.stick.red_tip_evidence import RedTipEvidenceTracker
from spacedrums.stick.red_tip_tracker import (
    MEASURED_STATES,
    SLOTS,
    Grip,
    RedTipTracker,
    SlotState,
    TrackerFrame,
)
from spacedrums.stick.search_region import unit_px_to_norm
from spacedrums.stick.tip_marker import MARKER_WARNING
from spacedrums.timing import now

log = logging.getLogger(__name__)

REASONS = {
    "OBSERVED": "RED_TIP",
    "WEAK": "RED_TIP_WEAK",
    "DARK": "RED_TIP_DARK",
    "AMBIGUOUS": "RED_TIP_AMBIGUOUS",
    "CLIPPED": "RED_TIP_CLIPPED",
    "WEAK_LIMIT": "RED_TIP_WEAK_LIMIT",
    "LOW_EVIDENCE": "RED_TIP_LOW_EVIDENCE",
    "PREDICTED": "RED_TIP_PREDICTED",
    "NO_TRACK": "RED_TIP_NOT_FOUND",
}


@dataclass(frozen=True)
class RedTipFrame:
    """Per-frame diagnostics for the HUD and ``observations.jsonl``; positions in ROI pixels."""

    frame_id: int
    t_capture: float
    roi_size: tuple[int, int]
    tracker: TrackerFrame
    candidates: tuple[RedBlob, ...]
    rejected: tuple[RedBlob, ...]
    reject_counts: dict
    mask: np.ndarray  # paint seeds, or redness regions at half res; HUD inset only (never serialized)
    ms: float  # detection + tracking wall time
    region: np.ndarray | None = None  # seeds + growth near seeds, diagnostics only (never serialized)

    @property
    def slots(self) -> dict[HandId, SlotState]:
        return self.tracker.slots

    @property
    def resets(self) -> frozenset[HandId]:
        return self.tracker.resets

    @property
    def ambiguous(self) -> bool:
        return self.tracker.ambiguous

    def to_record(self) -> dict:
        w, h = self.roi_size

        def norm(p):
            return None if p is None else [round(p[0] / w, 5), round(p[1] / h, 5)]

        return {
            "ms": round(self.ms, 3),
            "ambiguous": self.ambiguous,
            "resets": sorted(str(x) for x in self.resets),
            "slots": {
                str(x): {"state": st.state, "track_id": st.track_id, "tip": norm(st.tip),
                         "predicted": norm(st.predicted), "confidence": st.confidence, "misses": st.misses,
                         "area_px": None if st.area is None else round(st.area, 1)}
                for x, st in self.slots.items()
            },
            # [cap x, cap y, area, clipped, region-centroid x, region-centroid y, seed share, score]
            # (redness detector: region centre = the DoG peak, score = verifier quality, no seed share)
            "candidates": [[*norm(b.center), round(b.area, 1), b.clipped, *norm(b.region_center or b.center),
                            None if b.seed_fraction is None else round(b.seed_fraction, 3), round(b.score, 3)]
                           for b in self.candidates],
            "rejected": [[*norm(b.center), round(b.area, 1), b.reason] for b in self.rejected],
            "tracks": [{**t, "pos": norm(t["pos"])} for t in self.tracker.tracks],
            "reject_counts": dict(self.reject_counts),
        }


def _distribution(values) -> dict | None:
    if not values:
        return None
    p50, p95, top = np.percentile(values, [50, 95, 100])
    return {"n": len(values), "p50": float(p50), "p95": float(p95), "max": float(top)}


class RedTipStats:
    """Session counters for ``report.json``: per-slot continuity and detection-loss gaps."""

    def __init__(self) -> None:
        self.frames = 0
        self.states = {h: Counter() for h in SLOTS}
        self.gaps = {h: [] for h in SLOTS}  # non-measured runs between measured frames (frames)
        self.since_first = dict.fromkeys(SLOTS, 0)
        self.track_ids = {h: set() for h in SLOTS}
        self.rejects: Counter = Counter()
        self.resets: Counter = Counter()
        self.ms: list[float] = []
        self._run = dict.fromkeys(SLOTS, 0)
        self._seen = dict.fromkeys(SLOTS, False)

    def update(self, frame: RedTipFrame) -> None:
        self.frames += 1
        self.ms.append(frame.ms)
        self.rejects.update(frame.reject_counts)
        self.resets.update(str(h) for h in frame.resets)
        for h in SLOTS:
            st = frame.slots[h]
            self.states[h][st.state] += 1
            if st.track_id is not None:
                self.track_ids[h].add(st.track_id)
            if st.measured:
                if self._seen[h] and self._run[h]:
                    self.gaps[h].append(self._run[h])
                self._seen[h], self._run[h] = True, 0
            elif self._seen[h]:
                self._run[h] += 1
            if self._seen[h]:
                self.since_first[h] += 1

    def summary(self) -> dict:
        slots = {}
        for h in SLOTS:
            states = self.states[h]
            measured = sum(states[s] for s in MEASURED_STATES)
            after = self.since_first[h]
            slots[str(h)] = {
                "frames": self.frames,
                "measured_frames": measured,
                "measured_share": measured / self.frames if self.frames else None,
                # Loss rate counted from the slot's first measurement (before it the stick was not shown).
                "loss_rate_after_first": (1 - measured / after) if after else None,
                "states": dict(states),
                "gap_frames": _distribution(self.gaps[h]),
                "open_gap_frames": self._run[h],
                "track_ids": len(self.track_ids[h]),
            }
        return {"frames": self.frames, "slots": slots, "rejects": dict(self.rejects),
                "identity_resets": dict(self.resets), "ms": _distribution(self.ms)}


class RedTipEndpointEstimator:
    """``TipEstimator`` over red tips; one pass per frame for both hands (see module docstring)."""

    method_id = TipMethod.MARKER

    def __init__(self, settings: RedTipSettings | None = None,
                 grip_settings: GripSettings | None = None) -> None:
        self.settings = settings or RedTipSettings()
        self.grip_settings = grip_settings or GripSettings()
        self.redness = self.settings.detector == "redness"
        self.detector = CapDetector(self.settings) if self.redness else RedTipDetector(self.settings)
        self.tracker = RedTipEvidenceTracker(self.settings) if self.redness else RedTipTracker(self.settings)
        self.stats = RedTipStats()
        self.evidence: dict[HandId, EndpointEvidence] = {}
        self.observations: dict[HandId, StickObservation] = {}
        self.frame: RedTipFrame | None = None
        self.last_analysis = None  # Perception-compatible attribute; there is no stick analysis here
        self._key = None
        log.warning(MARKER_WARNING)

    @property
    def identity_resets(self) -> frozenset[HandId]:
        """Hands whose tip identity (re)started this frame: the pipeline must restart their strokes."""
        return self.frame.resets if self.frame is not None else frozenset()

    def reset(self) -> None:
        self.tracker.reset()
        self.evidence.clear()
        self.observations.clear()
        self.frame = None
        self._key = None

    def summary(self) -> dict:
        return {
            "method_id": str(self.method_id),
            "marker_condition": "RED_PAINTED_TIPS",
            "hand_assist": self.settings.hand_assist,
            "settings": self.settings.as_dict(),
            **self.stats.summary(),
            "events": dict(self.tracker.counters),
        }

    def observe(self, view: FrameView, hands: dict[HandId, HandObservation] | None = None) -> dict:
        s = view.sample
        started = now()
        roi = Roi.from_rect(s.roi_px)
        detection = self.detector.detect(view.roi)
        grips = self._grips(hands, roi) if self.settings.hand_assist and hands else {}
        if self.redness:  # grips only orient the emitted axis here (the evidence tracker binds by evidence)
            tracked = self.tracker.step(s.t_capture, detection.blobs, roi_size=(roi.w, roi.h))
            # Measured tips get the full-resolution cap point (association used the half-res one).
            slots = {h: replace(st, tip=self.detector.refined(st.tip)) if st.measured and st.tip else st
                     for h, st in tracked.slots.items()}
            tracked = replace(tracked, slots=slots)
        else:
            tracked = self.tracker.step(
                s.t_capture, detection.blobs, roi_size=(roi.w, roi.h), grips=grips,
                weak=lambda center, radius: self.detector.detect_weak(detection.hsv, center, radius),
                cores=detection.cores,
            )
        for h in SLOTS:
            self.observations[h], self.evidence[h] = self._emit(s, roi, tracked.slots[h], grips.get(h))
        self.frame = RedTipFrame(s.frame_id, s.t_capture, (roi.w, roi.h), tracked, detection.blobs,
                                 detection.rejected, dict(detection.reject_counts), detection.mask,
                                 (now() - started) * 1000, getattr(detection, "region", None))
        self.stats.update(self.frame)
        self._key = (s.frame_id, s.t_capture)
        return dict(self.observations)

    def estimate(self, view: FrameView, hand: HandObservation) -> StickObservation:
        if self._key != (view.sample.frame_id, view.sample.t_capture):
            self.observe(view)
        return self.observations[hand.hand_id]

    def _grips(self, hands, roi: Roi) -> dict[HandId, Grip]:
        out = {}
        for h, obs in hands.items():
            g = grip_reference(obs, self.grip_settings, roi_aspect=roi.aspect)
            if g is None:
                continue
            span = max(8.0, math.hypot(g.span_vec[0] * roi.w, g.span_vec[1] * roi.h))
            point = (g.point[0] * roi.w, g.point[1] * roi.h)
            reach = self.settings.hand_reach_spans * span
            out[HandId(h)] = Grip(point, reach, float(obs.handedness_score or 0.0))
        return out

    def _emit(self, s, roi: Roi, st: SlotState, grip: Grip | None):
        h, fid, t = st.hand_id, s.frame_id, s.t_capture
        reason = REASONS[st.state]
        if not st.measured:
            kind = "MISSING" if st.state == "NO_TRACK" else "UNCERTAIN"
            tip = None if st.tip is None else (st.tip[0] / roi.w, st.tip[1] / roi.h)
            return (StickObservation.absent(fid, t, h, self.method_id),
                    EndpointEvidence(fid, t, h, kind, reason, tip))
        tip = np.asarray(st.tip, float)
        origin, axis, axis_conf, length = tip, np.asarray(st.axis or (0.0, -1.0), float), 0.0, None
        if grip is not None:
            g = np.asarray(grip.point, float)
            d = float(np.linalg.norm(tip - g))
            if 2.0 < d <= grip.reach:
                origin, axis, length = g, (tip - g) / d, d / roi.h
                axis_conf = min(st.confidence, grip.score)
        tip_n = (float(tip[0] / roi.w), float(tip[1] / roi.h))
        origin_n = (float(origin[0] / roi.w), float(origin[1] / roi.h))
        obs = StickObservation(fid, t, h, True, self.method_id, origin_n, unit_px_to_norm(axis, roi), tip_n,
                               st.confidence, axis_conf, length)
        ev = EndpointEvidence(fid, t, h, "MEASURED", reason, tip_n, origin_n, st.confidence,
                              math.sqrt(st.area or 0.0))
        return obs, ev


__all__ = ["REASONS", "RedTipEndpointEstimator", "RedTipFrame", "RedTipStats"]
