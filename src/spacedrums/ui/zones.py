"""Clear geometric zone overlay for Phase 04 (no realistic drum-kit visuals)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from functools import lru_cache

import cv2
import numpy as np

from spacedrums.geometry import Arc, Ellipse, Segment, ZoneRegistry
from spacedrums.ui.canvas import Canvas


def _px(point: tuple[float, float], width: int, height: int) -> tuple[int, int]:
    return (round(point[0] * (width - 1)), round(point[1] * (height - 1)))


@lru_cache(maxsize=128)
def _arc_pixels(arc: Arc, width: int, height: int) -> np.ndarray:
    """Bounded cache keyed by immutable geometry and image size; calibration changes invalidate it."""
    theta = np.linspace(arc.theta_start_rad, arc.theta_end_rad, 65)
    points = np.asarray([_px(arc.point_at(float(t)), width, height) for t in theta], np.int32)
    points.setflags(write=False)
    return points


def draw_zones(
    image: np.ndarray | Canvas,
    registry: ZoneRegistry,
    *,
    impact_points: Mapping[str, tuple[float, float]] | None = None,
    inplace: bool = False,
) -> np.ndarray:
    """Draw shapes, impact surfaces, inward normals and optional observed impact points.

    A :class:`Canvas` (such as a mirrored live ROI) is drawn on in place; zone names stay readable.
    """
    canvas = image if isinstance(image, Canvas) else Canvas(image if inplace else image.copy())
    out = canvas.image
    height, width = out.shape[:2]
    impact_points = impact_points or {}
    for zone in registry:
        color = (80, 210, 245)
        if isinstance(zone.shape, Ellipse):
            center = _px(zone.shape.center, width, height)
            axes = (max(1, round(zone.shape.rx * width)), max(1, round(zone.shape.ry * height)))
            canvas.ellipse(center, axes, math.degrees(zone.shape.angle_rad), 0, 360, color, 2, cv2.LINE_AA)
            label_at = (center[0] - axes[0], center[1] + axes[1] + 18)
        else:
            pts = np.asarray([_px(p, width, height) for p in zone.shape.points], np.int32)
            canvas.polylines([pts], True, color, 2, cv2.LINE_AA)
            label_at = tuple(pts[np.argmax(pts[:, 1])])
        if isinstance(zone.impact_surface, Segment):
            a, b = zone.impact_surface.p0, zone.impact_surface.p1
        else:
            arc: Arc = zone.impact_surface
            pts = _arc_pixels(arc, width, height)
            canvas.polylines([pts], False, (40, 70, 255), 3, cv2.LINE_AA)
            a, b = arc.point_at(arc.theta_start_rad), arc.point_at(arc.theta_end_rad)
        if isinstance(zone.impact_surface, Segment):
            canvas.line(_px(a, width, height), _px(b, width, height), (40, 70, 255), 3, cv2.LINE_AA)
        midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        end = (midpoint[0] + zone.inward_normal[0] * 0.045, midpoint[1] + zone.inward_normal[1] * 0.045)
        canvas.arrowed_line(
            _px(midpoint, width, height),
            _px(end, width, height),
            (60, 230, 90),
            2,
            cv2.LINE_AA,
            tip_length=0.35,
        )
        canvas.put_text(
            zone.name,
            (int(label_at[0]), int(label_at[1])),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (235, 235, 235),
            1,
            cv2.LINE_AA,
        )
        if zone.zone_id in impact_points:
            canvas.marker(
                _px(impact_points[zone.zone_id], width, height),
                (255, 255, 255),
                cv2.MARKER_CROSS,
                14,
                2,
                cv2.LINE_AA,
            )
    return out


__all__ = ["draw_zones"]
