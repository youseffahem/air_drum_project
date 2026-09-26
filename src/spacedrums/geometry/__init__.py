"""Deterministic virtual-drum geometry (Phase 04)."""

from spacedrums.geometry.impact import Crossing, crossing_time, segment_arc, segment_segment, segment_surface
from spacedrums.geometry.intersect import GeometryEngine, Impact, TrajectoryPoint, first_impact
from spacedrums.geometry.zones import Arc, Ellipse, Polygon, Segment, Zone, ZoneRegistry

# Identity of the zone / impact semantics. Bump it whenever a change alters where or when a
# trajectory produces an impact: Phase 14 calibrations record it and a mismatch is a
# re-calibration trigger. Phase 07 labels carry the same value (data.labels.schema).
GEOMETRY_VERSION = "p04-geometry-v1"

__all__ = [
    "GEOMETRY_VERSION",
    "Arc",
    "Crossing",
    "Ellipse",
    "GeometryEngine",
    "Impact",
    "Polygon",
    "Segment",
    "TrajectoryPoint",
    "Zone",
    "ZoneRegistry",
    "crossing_time",
    "first_impact",
    "segment_arc",
    "segment_segment",
    "segment_surface",
]
