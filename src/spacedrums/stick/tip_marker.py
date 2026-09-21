"""``MARKER`` — coloured-marker tip: **fallback / benchmark condition only** (Phase 03, Task 03.9).

HSV in-range segmentation of a coloured tape band near the tip inside the search region (or the whole
ROI), tip = centroid of the largest blob (>= ``min_area_px``), optionally rejected when farther than
``axis_consistency_px`` from the fitted axis. The colour range **must be calibrated** per tape and
lighting (``stick.marker.hsv_low/high``); the defaults are placeholders for a green band, not a
calibration. No marker-equipped recording exists in the repository: the method is implemented and
unit-tested on synthetic images, and its benchmark row is PENDING (Task 03.10).

Integrity item I-7 / REQ-211: every instantiation logs a WARNING that the marker condition is active
and every record carries ``method_id = MARKER`` so no result can be presented as markerless.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from spacedrums.contracts import FrameView, HandObservation, StickObservation, TipMethod
from spacedrums.stick.estimator import StickSettings, _BaseEstimator, analyse, record_from
from spacedrums.stick.tip_geom import roi_of

log = logging.getLogger(__name__)
MARKER_WARNING = ("MARKER tip method active: coloured-marker FALLBACK / BENCHMARK condition, not the "
                  "markerless system (REQ-009, REQ-211, integrity I-7). Label every result derived from it.")


class MarkerTipEstimator(_BaseEstimator):
    method_id = TipMethod.MARKER

    def __init__(self, settings: StickSettings) -> None:
        super().__init__(settings)
        log.warning(MARKER_WARNING)
        self.warning_emitted = True
        self.counters["no_blob"] = 0
        self.counters["axis_inconsistent"] = 0

    def estimate(self, frame_roi: FrameView, hand_obs: HandObservation) -> StickObservation:
        self.counters["frames"] += 1
        s = frame_roi.sample
        if not hand_obs.present:
            self.last_analysis = None
            return StickObservation.absent(s.frame_id, s.t_capture, hand_obs.hand_id, self.method_id)
        an = analyse(frame_roi, hand_obs, self.settings, self._l_px(hand_obs.hand_id, roi_of(frame_roi)))
        self.last_analysis = an
        m = self.settings.marker
        if an.grip_px is None or an.prior_dir_px is None:
            return StickObservation.absent(s.frame_id, s.t_capture, hand_obs.hand_id, self.method_id)
        hsv = cv2.cvtColor(frame_roi.roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(m.hsv_low, np.uint8), np.array(m.hsv_high, np.uint8))
        if m.search == "SEARCH_REGION":
            if an.region is None or an.region.empty:
                self.counters["no_blob"] += 1
                return StickObservation.absent(s.frame_id, s.t_capture, hand_obs.hand_id, self.method_id)
            mask[~an.region.mask] = 0
        n, _labels, stats, cents = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8),
                                                                    connectivity=8)
        best = None
        for lab in range(1, n):
            area = int(stats[lab, cv2.CC_STAT_AREA])
            if area >= m.min_area_px and (best is None or area > best[0]):
                best = (area, (float(cents[lab][0]), float(cents[lab][1])))
        if best is None:
            self.counters["no_blob"] += 1
            return StickObservation.absent(s.frame_id, s.t_capture, hand_obs.hand_id, self.method_id)
        area, tip_px = best
        if an.axis is not None and m.axis_consistency_px is not None:
            o, d = np.asarray(an.axis.origin_px), np.asarray(an.axis.dir_px)
            rel = np.asarray(tip_px) - o
            if abs(float(rel[0] * d[1] - rel[1] * d[0])) > m.axis_consistency_px:
                self.counters["axis_inconsistent"] += 1
                return StickObservation.absent(s.frame_id, s.t_capture, hand_obs.hand_id, self.method_id)
        if an.axis is not None:  # direction: along the axis if present, else grip -> blob
            dir_px = an.axis.dir_px
        else:
            v = np.asarray(tip_px) - np.asarray(an.grip_px)
            nv = float(np.hypot(v[0], v[1]))
            dir_px = an.prior_dir_px if nv < 1e-6 else (float(v[0] / nv), float(v[1] / nv))
        length = float(np.hypot(*(np.asarray(tip_px) - np.asarray(an.grip_px))))
        conf = float(hand_obs.handedness_score or 0.0) * min(1.0, area / m.reference_area_px)
        self.counters["present"] += 1
        return record_from(frame_roi, hand_obs, self.method_id, an, tip_px, dir_px, conf, length)


__all__ = ["MARKER_WARNING", "MarkerTipEstimator"]
