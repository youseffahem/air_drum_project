"""``AXIS_REFINED`` — visual axis refinement tip (Phase 03, Task 03.8).

Tip = far endpoint of the axis support (last inlier along ``axis_dir`` from the origin), gated
against the ``GEOM`` estimate: rejected when farther than ``max_deviation_factor * L`` from the GEOM
tip or when the support is shorter than ``min_support_factor * L`` (truncation by blur / occlusion /
the region boundary). On rejection or without an axis the method **falls back to GEOM** with
``tip_confidence`` multiplied by ``fallback_confidence_factor``; the fallback is counted
(``counters["fallback"]``) because the fallback rate is a benchmark quantity (Task 03.10).

``tip_confidence = handedness_score * (0.5 + 0.5 * axis_confidence)`` when the refined tip is used.
"""

from __future__ import annotations

import numpy as np

from spacedrums.contracts import FrameView, HandObservation, StickObservation, TipMethod
from spacedrums.stick.estimator import StickSettings, _BaseEstimator, analyse, geom_tip, record_from
from spacedrums.stick.tip_geom import roi_of


class AxisRefinedTipEstimator(_BaseEstimator):
    method_id = TipMethod.AXIS_REFINED

    def __init__(self, settings: StickSettings) -> None:
        super().__init__(settings)
        self.last_used_refined: bool | None = None

    def estimate(self, frame_roi: FrameView, hand_obs: HandObservation) -> StickObservation:
        self.counters["frames"] += 1
        s = frame_roi.sample
        self.last_used_refined = None
        if not hand_obs.present:
            self.last_analysis = None
            return StickObservation.absent(s.frame_id, s.t_capture, hand_obs.hand_id, self.method_id)
        an = analyse(frame_roi, hand_obs, self.settings, self._l_px(hand_obs.hand_id, roi_of(frame_roi)))
        self.last_analysis = an
        g = geom_tip(an)
        if g is None:
            return StickObservation.absent(s.frame_id, s.t_capture, hand_obs.hand_id, self.method_id)
        geom_px, dir_px, factor, src = g
        hs = float(hand_obs.handedness_score or 0.0)
        a = self.settings.axis_refined
        if an.axis is not None:
            far = np.asarray(an.axis.support_far_px)
            dev = float(np.hypot(*(far - np.asarray(geom_px))))
            long_enough = an.axis.support_len_px >= a.min_support_factor * an.l_px
            if long_enough and dev <= a.max_deviation_factor * an.l_px:
                self.last_used_refined = True
                self._refine(hand_obs.hand_id, an)
                self.counters["present"] += 1
                conf = hs * (0.5 + 0.5 * an.axis.confidence)
                return record_from(frame_roi, hand_obs, self.method_id, an, (float(far[0]), float(far[1])),
                                   dir_px, conf, an.axis.support_len_px)
        # fallback to GEOM with reduced confidence
        self.last_used_refined = False
        self.counters["fallback"] += 1
        if src == "prior":
            self.counters["no_axis"] += 1
            factor = self.settings.geom.no_axis_confidence_factor
        conf = hs * factor * a.fallback_confidence_factor
        self.counters["present"] += 1
        return record_from(frame_roi, hand_obs, self.method_id, an, geom_px, dir_px, conf, an.l_px)


__all__ = ["AxisRefinedTipEstimator"]
