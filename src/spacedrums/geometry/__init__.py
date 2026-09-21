"""Deterministic virtual-drum geometry (Phase 04)."""

from spacedrums.geometry.impact import Crossing, crossing_time, segment_arc, segment_segment, segment_surface
from spacedrums.geometry.intersect import GeometryEngine, Impact, TrajectoryPoint, first_impact
from spacedrums.geometry.zones import Arc, Ellipse, Polygon, Segment, Zone, ZoneRegistry

__all__ = [
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
