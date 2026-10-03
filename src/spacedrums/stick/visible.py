"""Current-image stick support anchored by hand landmarks, with no length fallback.

The default fits a line through connected image support in a broad grip-centred
patch and requires the visible end to lie inside the patch. The experimental
paired mode uses LSD edge pairs; it remains available for replay comparisons.
Temporal checks reject isolated axis/length jumps but never carry an old tip
forward as measured. Consistent current-image evidence can reacquire.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, replace

import cv2
import numpy as np

from spacedrums.capture.roi import Roi
from spacedrums.contracts import StickObservation, TipMethod
from spacedrums.contracts.perception import EndpointEvidence
from spacedrums.hands.grip import grip_reference
from spacedrums.stick.estimator import analyse
from spacedrums.stick.search_region import to_roi_norm, unit_px_to_norm


@dataclass(frozen=True)
class VisibleSettings:
    search_spans: float = 7.0
    max_search_spans: float = 14.0
    search_width_spans: float = 2.4
    min_length_px: float = 18.0
    max_angle_change_rad: float = 1.15
    max_length_ratio: float = 1.8
    memory_s: float = 0.12
    min_confidence: float = 0.65


def edge_pairs(lines, grip, prior, span, bounds, min_length):
    """Rank image-supported paired edges. All distances in ROI pixels."""
    candidates = []
    for line in lines:
        a, b = line[:2], line[2:]
        length = float(np.linalg.norm(b - a))
        if length < max(min_length, 0.75 * span):
            continue
        d = (b - a) / length
        if np.dot(d, prior) < 0:
            a, b, d = b, a, -d
        alignment = float(np.dot(d, prior))
        if alignment < 0.2:
            continue
        near, far = float(np.dot(a - grip, d)), float(np.dot(b - grip, d))
        offset = float(np.cross(d, a - grip))
        if abs(offset) > max(8, 0.55 * span) or near > 0.9 * span or far < min_length:
            continue
        if far > 6 * span or near < -2 * span:
            continue
        if min(b[0] - bounds[0], b[1] - bounds[1], bounds[2] - b[0], bounds[3] - b[1]) < 4:
            continue  # clipped support is not a visible endpoint
        candidates.append((a, b, d, near, far, offset, alignment))
    pairs = []
    for i, one in enumerate(candidates):
        for two in candidates[i + 1 :]:
            a, b, d, near, far, off, align = one
            aa, bb, dd, nn, ff, oo, al = two
            cosine = float(np.dot(d, dd))
            width = abs(float(np.cross(d, aa - a)))
            endpoint_delta = abs(float(np.dot(bb - b, d)))
            if cosine < 0.985 or not 1.5 <= width <= max(12, 0.5 * span):
                continue
            if endpoint_delta > max(9, 0.28 * span):
                continue
            tip = (b + bb) / 2
            direction = d + dd
            direction /= np.linalg.norm(direction)
            origin = grip + np.array([-direction[1], direction[0]]) * (off + oo) / 2
            length = float(np.linalg.norm(tip - origin))
            # Geometric evidence score, not a calibrated probability of correctness.
            score = (
                0.75
                + 0.15 * min(align, al)
                + 0.1 * min(1, length / (2 * span))
                - 0.15 * endpoint_delta / max(9, 0.28 * span)
                - 0.12 * abs((off + oo) / 2) / max(8, 0.55 * span)
            )
            pairs.append((score, tip, origin, direction, length))
    return sorted(pairs, key=lambda p: p[0], reverse=True)


class VisibleEndpointEstimator:
    method_id = TipMethod.AXIS_REFINED

    def __init__(self, stick_settings, settings=None, *, mode="support"):
        self.stick_settings = stick_settings
        self.mode = mode
        self.settings = settings or VisibleSettings()
        self.detector = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        self.memory = {}
        self.pending = {}
        self.evidence = {}
        self.counters = Counter()
        self.last_analysis = None

    def reset(self):
        self.memory.clear()
        self.pending.clear()
        self.evidence.clear()

    def estimate(self, view, hand):
        s, h = view.sample, hand.hand_id
        roi = Roi.from_rect(s.roi_px)

        def reject(reason, kind="UNCERTAIN"):
            self.counters[reason] += 1
            self.evidence[h] = EndpointEvidence(s.frame_id, s.t_capture, h, kind, reason)
            return StickObservation.absent(s.frame_id, s.t_capture, h, self.method_id)

        grip = grip_reference(hand, self.stick_settings.grip, roi_aspect=roi.aspect)
        if grip is None:
            return reject("HAND_MISSING", "MISSING")
        if grip.direction is None:
            return reject("GRIP_DIRECTION_UNCERTAIN")
        scale = np.array([roi.w, roi.h])
        anchor = np.array(grip.point) * scale
        prior = np.array(grip.direction) * scale
        prior /= np.linalg.norm(prior)
        span = max(8.0, float(np.linalg.norm(np.array(grip.span_vec) * scale)))
        radius = min(roi.h * 0.48, span * self.settings.search_spans)
        x0, y0 = np.maximum(0, np.floor(anchor - radius)).astype(int)
        x1, y1 = np.minimum([roi.w, roi.h], np.ceil(anchor + radius)).astype(int)
        if x1 - x0 < 12 or y1 - y0 < 12:
            return reject("HAND_OUTSIDE_ROI")
        if self.mode == "paired":
            patch = view.roi[y0:y1, x0:x1]
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if patch.ndim == 3 else patch
            detected = self.detector.detect(gray)[0]
            if detected is None:
                return reject("NO_VISIBLE_EDGES", "MISSING")
            lines = detected.reshape(-1, 4).astype(float) + [x0, y0, x0, y0]
            pairs = edge_pairs(lines, anchor, prior, span, (x0, y0, x1, y1), self.settings.min_length_px)
            if not pairs:
                return reject("NO_SUPPORTED_ENDPOINT", "MISSING")
            score, tip, origin, direction, length = pairs[0]
            if len(pairs) > 1 and pairs[1][0] > score - 0.035 and np.linalg.norm(tip - pairs[1][1]) > span:
                return reject("AMBIGUOUS_STICK_EDGES")
            reason = "PAIRED_EDGES"
        else:
            search_spans = self.settings.search_spans
            axis_hint = None
            while True:
                region = replace(
                    self.stick_settings.search_region,
                    length_factor=search_spans,
                    width_factor=self.settings.search_width_spans,
                )
                settings = replace(self.stick_settings, search_region=region)
                an = analyse(view, hand, settings, settings.geom.prior(h) * roi.h, axis_hint_px=axis_hint)
                self.last_analysis = an
                if an.axis is None:
                    return reject("NO_VISIBLE_AXIS", "MISSING")
                axis = an.axis
                if axis.confidence < 0.4 or axis.support_len_px < max(
                    self.settings.min_length_px, 0.75 * span
                ):
                    return reject("WEAK_OR_SHORT_SUPPORT")
                tip, origin, direction = map(np.asarray, (axis.support_far_px, axis.origin_px, axis.dir_px))
                # Follow the current fitted axis when the hand prior clipped it.
                # The endpoint at an image edge remains uncertain, even at maximum reach.
                boundary = cv2.pointPolygonTest(an.region.polygon_px.astype(np.float32), tuple(tip), True)
                if boundary >= 3:
                    break
                if (
                    search_spans >= self.settings.max_search_spans
                    or min(tip[0], tip[1], roi.w - tip[0], roi.h - tip[1]) < 3
                ):
                    return reject("CLIPPED_ENDPOINT")
                search_spans = min(search_spans * 1.5, self.settings.max_search_spans)
                axis_hint = tuple(axis.dir_px)
                self.counters["SEARCH_EXTENDED"] += 1
            length = axis.support_len_px
            score = 0.5 + 0.5 * axis.confidence
            reason = "CONNECTED_AXIS_ENDPOINT"
        confidence = min(float(hand.handedness_score or 0), score)
        if confidence < self.settings.min_confidence:
            return reject("LOW_CONFIDENCE")
        previous = self.memory.get(h)
        current = (s.t_capture, tip, origin, direction, length)
        if previous and 0 < s.t_capture - previous[0] <= self.settings.memory_s:
            angle = math.acos(float(np.clip(np.dot(direction, previous[3]), -1, 1)))
            ratio = max(length / previous[4], previous[4] / length)
            displacement = np.linalg.norm((tip - previous[1]) - (origin - previous[2]))
            suspicious = (
                angle > self.settings.max_angle_change_rad
                or ratio > self.settings.max_length_ratio
                or displacement > 3 * span
            )
            if suspicious:
                pending = self.pending.get(h)
                self.pending[h] = current
                consistent = (
                    pending is not None
                    and 0 < s.t_capture - pending[0] < 0.08
                    and np.linalg.norm(tip - pending[1]) < span
                )
                if not consistent:
                    return reject("TEMPORAL_OUTLIER")
        self.memory[h] = current
        self.pending.pop(h, None)
        pn, on = to_roi_norm(tuple(tip), roi), to_roi_norm(tuple(origin), roi)
        self.evidence[h] = EndpointEvidence(
            s.frame_id, s.t_capture, h, "MEASURED", reason, pn, on, confidence, length
        )
        self.counters["MEASURED"] += 1
        return StickObservation(
            s.frame_id,
            s.t_capture,
            h,
            True,
            self.method_id,
            on,
            unit_px_to_norm(direction, roi),
            pn,
            confidence,
            confidence,
            length / roi.h,
        )
