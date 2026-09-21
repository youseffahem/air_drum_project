"""``GEOM`` — markerless geometric tip (Phase 03, Task 03.7): ``tip = grip_point + L * axis_dir``.

``L`` starts at ``stick.geom.l_prior`` (ROI-height units; initial value from the Phase 02 distance
benchmark: 120 px / 440 px at 1.0 m) and may be refined online from the axis support length when
``axis_confidence`` is high (causal running estimate per hand; ``refine_online``, default off so the
estimator is a pure per-frame function as the ``TipEstimator`` Protocol describes). When no axis is
found the tip is placed along the grip direction prior with a reduced confidence — GEOM therefore
works when the far stick end is blurred or outside the search region (its design purpose).

``tip_confidence = handedness_score * (0.5 + 0.5 * axis_confidence)`` with an axis, or
``handedness_score * no_axis_confidence_factor`` without one (producer-defined, contracts.md 1).
"""

from __future__ import annotations

from spacedrums.capture.roi import Roi
from spacedrums.contracts import FrameView, HandObservation, StickObservation, TipMethod
from spacedrums.stick.estimator import StickSettings, _BaseEstimator, analyse, geom_tip, record_from


def roi_of(view: FrameView) -> Roi:
    return Roi.from_rect(view.sample.roi_px)


class GeomTipEstimator(_BaseEstimator):
    method_id = TipMethod.GEOM

    def __init__(self, settings: StickSettings) -> None:
        super().__init__(settings)

    def estimate(self, frame_roi: FrameView, hand_obs: HandObservation) -> StickObservation:
        self.counters["frames"] += 1
        s = frame_roi.sample
        if not hand_obs.present:
            self.last_analysis = None
            return StickObservation.absent(s.frame_id, s.t_capture, hand_obs.hand_id, self.method_id)
        an = analyse(frame_roi, hand_obs, self.settings, self._l_px(hand_obs.hand_id, roi_of(frame_roi)))
        self.last_analysis = an
        g = geom_tip(an)
        if g is None:
            return StickObservation.absent(s.frame_id, s.t_capture, hand_obs.hand_id, self.method_id)
        tip_px, dir_px, factor, src = g
        if src == "prior":
            self.counters["no_axis"] += 1
            factor = self.settings.geom.no_axis_confidence_factor
        conf = float(hand_obs.handedness_score or 0.0) * factor
        self._refine(hand_obs.hand_id, an)
        self.counters["present"] += 1
        return record_from(frame_roi, hand_obs, self.method_id, an, tip_px, dir_px, conf, an.l_px)


__all__ = ["GeomTipEstimator", "roi_of"]
