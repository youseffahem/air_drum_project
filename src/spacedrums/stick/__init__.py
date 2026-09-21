"""Layer L2 (perception): markerless stick detection / axis / tip (Phase 03, Tasks 03.4-03.9).

Produces ``StickObservation`` through the pluggable ``TipEstimator`` implementations ``GEOM``
(primary markerless candidate), ``AXIS_REFINED`` and ``MARKER`` (fallback / benchmark only).
Imports L0, ``spacedrums.capture`` (ROI helper) and ``spacedrums.hands`` (grip), architecture.md 2.2.
"""

from spacedrums.stick.axis import AxisEstimate, AxisMethod, AxisSettings, fit_axis
from spacedrums.stick.estimator import (
    AxisRefinedSettings,
    GeomSettings,
    MarkerSettings,
    StickAnalysis,
    StickSettings,
    analyse,
    geom_tip,
    make_tip_estimator,
)
from spacedrums.stick.search_region import (
    SearchRegion,
    SearchRegionSettings,
    clip_polygon,
    search_region,
    to_roi_norm,
    to_roi_px,
    unit_px_to_norm,
)
from spacedrums.stick.segment import ComponentInfo, SegmentResult, SegmentSettings, segment_stick
from spacedrums.stick.tip_axis_refined import AxisRefinedTipEstimator
from spacedrums.stick.tip_geom import GeomTipEstimator
from spacedrums.stick.tip_marker import MARKER_WARNING, MarkerTipEstimator

__all__ = [
    "MARKER_WARNING",
    "AxisEstimate",
    "AxisMethod",
    "AxisRefinedSettings",
    "AxisRefinedTipEstimator",
    "AxisSettings",
    "ComponentInfo",
    "GeomSettings",
    "GeomTipEstimator",
    "MarkerSettings",
    "MarkerTipEstimator",
    "SearchRegion",
    "SearchRegionSettings",
    "SegmentResult",
    "SegmentSettings",
    "StickAnalysis",
    "StickSettings",
    "analyse",
    "clip_polygon",
    "fit_axis",
    "geom_tip",
    "make_tip_estimator",
    "search_region",
    "segment_stick",
    "to_roi_norm",
    "to_roi_px",
    "unit_px_to_norm",
]
