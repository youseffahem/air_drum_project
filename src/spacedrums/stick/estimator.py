"""Shared per-frame stick analysis and the ``TipEstimator`` factory (Phase 03, Checkpoint 03.C).

Every tip method runs the same causal, per-frame analysis on (``FrameView``, ``HandObservation``):

    grip reference (hands.grip) -> search region (03.4) -> candidate pixels (03.5) -> axis (03.6)

and then derives its tip (``tip_geom``, ``tip_axis_refined``, ``tip_marker``). ``StickAnalysis`` is
the in-process debugging/benchmark object (region polygon, candidate pixels, axis); it is never
stored — only the ``StickObservation`` record is.

Units: the analysis works in ROI pixel coordinates; the record is ROI-normalized (ADR-0005).
``stick_length_est`` and ``l_prior`` are expressed in **ROI-height units** (px / roi.h), the
isotropic pixel length divided by the ROI height, matching the Phase 02 distance protocol's
``stick_roi_norm`` column; this is documented because the ROI-normalized frame is anisotropic.

Confidence rule (contracts.md section 1 "Labels"; ADR-0014 section 10): every method's
``tip_confidence`` is bounded by the hand's ``handedness_score`` (identity confidence), so an
ambiguous identity can only be DEGRADED downstream.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from spacedrums.capture.roi import Roi
from spacedrums.contracts import FrameView, HandId, HandObservation, StickObservation, TipMethod
from spacedrums.hands.grip import GripReference, GripSettings, grip_reference
from spacedrums.stick.axis import AxisEstimate, AxisSettings, fit_axis
from spacedrums.stick.search_region import (
    SearchRegion,
    SearchRegionSettings,
    search_region,
    to_roi_norm,
    to_roi_px,
    unit_px_to_norm,
    vec_norm_to_px,
)
from spacedrums.stick.segment import SegmentResult, SegmentSettings, segment_stick

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeomSettings:
    l_prior: float = 0.27  # apparent stick length in ROI-height units (Phase 02 d100: 120 px / 440)
    no_axis_confidence_factor: float = 0.4  # tip from the grip prior alone (no axis found)
    refine_online: bool = False  # causal running estimate of L from the axis support (per hand)
    refine_alpha: float = 0.05
    refine_min_axis_confidence: float = 0.7
    refine_support_range: tuple[float, float] = (0.6, 1.4)  # accepted support / L ratio
    # Phase 14 calibration (ADR-0037): per-hand L in ROI-height units; empty = shared l_prior
    l_prior_by_hand: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if self.l_prior <= 0:
            raise ValueError("l_prior must be > 0")
        by_hand = tuple(sorted((HandId(k).value, float(v)) for k, v in dict(self.l_prior_by_hand).items()))
        if any(not v > 0 for _k, v in by_hand):
            raise ValueError("l_prior_by_hand values must be > 0")
        object.__setattr__(self, "l_prior_by_hand", by_hand)
        if not (0.0 <= self.no_axis_confidence_factor <= 1.0):
            raise ValueError("no_axis_confidence_factor in [0, 1]")
        if not (0.0 < self.refine_alpha <= 1.0):
            raise ValueError("refine_alpha in (0, 1]")
        lo, hi = self.refine_support_range
        if not (0 < lo < hi):
            raise ValueError("refine_support_range must be 0 < lo < hi")

    @classmethod
    def from_config(cls, stick_cfg: dict[str, Any]) -> GeomSettings:
        g = stick_cfg["geom"]
        lo, hi = g["refine_support_range"]
        return cls(l_prior=float(g["l_prior"]),
                   no_axis_confidence_factor=float(g["no_axis_confidence_factor"]),
                   refine_online=bool(g["refine_online"]), refine_alpha=float(g["refine_alpha"]),
                   refine_min_axis_confidence=float(g["refine_min_axis_confidence"]),
                   refine_support_range=(float(lo), float(hi)),
                   l_prior_by_hand=tuple(
                       (str(k), float(v)) for k, v in (g.get("l_prior_by_hand") or {}).items()))

    def prior(self, hand: HandId | str) -> float:
        """The calibrated per-hand prior (Phase 14) when present, else the shared ``l_prior``."""
        return dict(self.l_prior_by_hand).get(HandId(hand).value, self.l_prior)


@dataclass(frozen=True)
class AxisRefinedSettings:
    max_deviation_factor: float = 0.35  # x L: reject the support endpoint farther than this from the GEOM tip
    min_support_factor: float = 0.5  # x L: shorter support = truncated stick -> fall back
    fallback_confidence_factor: float = 0.6  # GEOM fallback confidence multiplier

    def __post_init__(self) -> None:
        if self.max_deviation_factor <= 0 or self.min_support_factor <= 0:
            raise ValueError("factors must be > 0")
        if not (0.0 <= self.fallback_confidence_factor <= 1.0):
            raise ValueError("fallback_confidence_factor in [0, 1]")

    @classmethod
    def from_config(cls, stick_cfg: dict[str, Any]) -> AxisRefinedSettings:
        a = stick_cfg["axis_refined"]
        return cls(max_deviation_factor=float(a["max_deviation_factor"]),
                   min_support_factor=float(a["min_support_factor"]),
                   fallback_confidence_factor=float(a["fallback_confidence_factor"]))


@dataclass(frozen=True)
class MarkerSettings:
    """Colour-marker fallback / benchmark condition ONLY (REQ-211, integrity I-7)."""

    hsv_low: tuple[int, int, int] = (35, 80, 80)  # candidate for a green tape band; must be calibrated
    hsv_high: tuple[int, int, int] = (85, 255, 255)
    min_area_px: int = 12
    search: str = "SEARCH_REGION"  # SEARCH_REGION | ROI
    axis_consistency_px: float | None = 12.0  # reject a blob farther than this from the axis (None: off)
    reference_area_px: int = 120  # blob area at which the area term of the confidence saturates

    def __post_init__(self) -> None:
        if self.search not in ("SEARCH_REGION", "ROI"):
            raise ValueError("marker.search must be SEARCH_REGION or ROI")
        if self.min_area_px < 1 or self.reference_area_px < 1:
            raise ValueError("areas must be >= 1")

    @classmethod
    def from_config(cls, stick_cfg: dict[str, Any]) -> MarkerSettings:
        m = stick_cfg["marker"]
        return cls(hsv_low=tuple(int(v) for v in m["hsv_low"]), hsv_high=tuple(int(v) for v in m["hsv_high"]),
                   min_area_px=int(m["min_area_px"]), search=str(m["search"]),
                   axis_consistency_px=(None if m["axis_consistency_px"] is None
                                        else float(m["axis_consistency_px"])),
                   reference_area_px=int(m["reference_area_px"]))


@dataclass(frozen=True)
class StickSettings:
    """The ``stick`` config block (schema 1.2, ADR-0015)."""

    method_id: TipMethod = TipMethod.GEOM
    grip: GripSettings = GripSettings()
    search_region: SearchRegionSettings = SearchRegionSettings()
    segment: SegmentSettings = SegmentSettings()
    axis: AxisSettings = AxisSettings()
    geom: GeomSettings = GeomSettings()
    axis_refined: AxisRefinedSettings = AxisRefinedSettings()
    marker: MarkerSettings = MarkerSettings()

    def __post_init__(self) -> None:
        object.__setattr__(self, "method_id", TipMethod(self.method_id))

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> StickSettings:
        try:
            st = cfg["stick"]
        except KeyError as exc:
            raise ValueError("config has no 'stick' block (config schema 1.2, ADR-0015)") from exc
        has_grip = "hands" in cfg and "grip" in cfg["hands"]
        grip = GripSettings.from_config(cfg["hands"]) if has_grip else GripSettings()
        return cls(method_id=TipMethod(st["method_id"]), grip=grip,
                   search_region=SearchRegionSettings.from_config(st),
                   segment=SegmentSettings.from_config(st),
                   axis=AxisSettings.from_config(st), geom=GeomSettings.from_config(st),
                   axis_refined=AxisRefinedSettings.from_config(st), marker=MarkerSettings.from_config(st))


@dataclass(frozen=True)
class StickAnalysis:
    """Everything one frame's analysis produced for one hand (debug / benchmark; never stored)."""

    roi: Roi
    grip: GripReference | None
    region: SearchRegion | None
    segment: SegmentResult | None
    axis: AxisEstimate | None
    grip_px: tuple[float, float] | None
    prior_dir_px: tuple[float, float] | None
    l_px: float  # the L used this frame (px)
    notes: tuple[str, ...] = field(default_factory=tuple)


def analyse(view: FrameView, obs: HandObservation, settings: StickSettings, l_px: float) -> StickAnalysis:
    roi = Roi.from_rect(view.sample.roi_px)
    grip = grip_reference(obs, settings.grip, roi_aspect=roi.aspect)
    if grip is None:
        return StickAnalysis(roi, None, None, None, None, None, None, l_px, ("hand_absent",))
    grip_px = to_roi_px(grip.point, roi)
    if grip.direction is None:
        return StickAnalysis(roi, grip, None, None, None, grip_px, None, l_px, ("degenerate_grip_direction",))
    d = vec_norm_to_px(grip.direction, roi)
    d /= float(np.hypot(d[0], d[1]))
    prior = (float(d[0]), float(d[1]))
    region = search_region(grip, roi, settings.search_region)
    if region is None or region.empty:
        return StickAnalysis(roi, grip, region, None, None, grip_px, prior, l_px, ("no_search_region",))
    gray = cv2.cvtColor(view.roi, cv2.COLOR_BGR2GRAY) if view.roi.ndim == 3 else view.roi
    seg = segment_stick(gray, region, settings.segment)
    axis = fit_axis(seg.candidate_px, grip_px, prior, region.span_px, settings.axis, mask=seg.mask)
    notes = () if axis is not None else ("no_axis",)
    return StickAnalysis(roi, grip, region, seg, axis, grip_px, prior, l_px, notes)


def record_from(view: FrameView, obs: HandObservation, method: TipMethod, an: StickAnalysis,
                tip_px: tuple[float, float] | None, dir_px: tuple[float, float] | None,
                tip_confidence: float, length_px: float | None) -> StickObservation:
    s = view.sample
    if tip_px is None or dir_px is None or an.grip_px is None:
        return StickObservation.absent(s.frame_id, s.t_capture, obs.hand_id, method)
    origin_px = an.axis.origin_px if an.axis is not None else an.grip_px
    axis_conf = an.axis.confidence if an.axis is not None else 0.0
    conf = min(float(tip_confidence), float(obs.handedness_score or 0.0))
    return StickObservation(
        frame_id=s.frame_id, t_capture=s.t_capture, hand_id=obs.hand_id, present=True, method_id=method,
        axis_origin=to_roi_norm(origin_px, an.roi), axis_dir=unit_px_to_norm(np.asarray(dir_px), an.roi),
        tip=to_roi_norm(tip_px, an.roi), tip_confidence=max(0.0, min(1.0, conf)),
        axis_confidence=max(0.0, min(1.0, axis_conf)),
        stick_length_est=(length_px / an.roi.h) if length_px is not None else None,
    )


class _BaseEstimator:
    """Common state: per-hand L (px) for the optional causal online refinement."""

    method_id: TipMethod

    def __init__(self, settings: StickSettings) -> None:
        self.settings = settings
        self._l_units: dict[HandId, float] = {}  # per-hand L in ROI-height units
        self.last_analysis: StickAnalysis | None = None
        self.counters: dict[str, int] = {"frames": 0, "present": 0, "no_axis": 0, "fallback": 0}

    def _l_px(self, hand: HandId, roi: Roi) -> float:
        return self._l_units.get(hand, self.settings.geom.prior(hand)) * roi.h

    def _refine(self, hand: HandId, an: StickAnalysis) -> None:
        g = self.settings.geom
        if not g.refine_online or an.axis is None or an.axis.confidence < g.refine_min_axis_confidence:
            return
        lo, hi = g.refine_support_range
        ratio = an.axis.support_len_px / an.l_px
        if lo <= ratio <= hi:
            cur = self._l_units.get(hand, g.prior(hand))
            new_units = an.axis.support_len_px / an.roi.h
            self._l_units[hand] = (1 - g.refine_alpha) * cur + g.refine_alpha * new_units

    def reset(self) -> None:
        self._l_units.clear()

    def estimate(self, frame_roi: FrameView, hand_obs: HandObservation) -> StickObservation:
        raise NotImplementedError


def geom_tip(an: StickAnalysis) -> tuple[tuple[float, float], tuple[float, float], float, str] | None:
    """(tip_px, dir_px, confidence_factor, source) of the GEOM rule; None when there is no anchor."""
    if an.grip_px is None or an.prior_dir_px is None:
        return None
    if an.axis is not None:
        d = np.asarray(an.axis.dir_px)
        origin = np.asarray(an.axis.origin_px)
        conf_factor = 0.5 + 0.5 * an.axis.confidence
        src = "axis"
    else:
        d = np.asarray(an.prior_dir_px)
        origin = np.asarray(an.grip_px)
        conf_factor = None  # filled by the caller from settings (no_axis factor)
        src = "prior"
    tip = origin + an.l_px * d
    return (float(tip[0]), float(tip[1])), (float(d[0]), float(d[1])), conf_factor, src


def make_tip_estimator(method: TipMethod | str, settings: StickSettings):
    """Factory by ``method_id`` (README section 14)."""
    from spacedrums.stick.tip_axis_refined import AxisRefinedTipEstimator
    from spacedrums.stick.tip_geom import GeomTipEstimator
    from spacedrums.stick.tip_marker import MarkerTipEstimator

    m = TipMethod(method)
    if m is TipMethod.GEOM:
        return GeomTipEstimator(settings)
    if m is TipMethod.AXIS_REFINED:
        return AxisRefinedTipEstimator(settings)
    return MarkerTipEstimator(settings)


__all__ = [
    "AxisRefinedSettings",
    "GeomSettings",
    "MarkerSettings",
    "StickAnalysis",
    "StickSettings",
    "analyse",
    "geom_tip",
    "make_tip_estimator",
    "record_from",
]
