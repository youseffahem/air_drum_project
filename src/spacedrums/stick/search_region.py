"""Hand-anchored stick search region (Phase 03, Task 03.4).

A rotated rectangle in **ROI pixel coordinates** (origin = the ROI's top-left; the stick module works
on the ROI crop it receives in ``FrameView.roi``): it starts ``back_factor * span`` behind the grip
point, extends ``length_factor * span`` along the grip direction prior and is ``width_factor * span``
wide, where ``span`` is the hand's apparent size in pixels (wrist -> middle MCP, Task 03.3). Scaling
by the hand span makes the region follow the user distance without a distance parameter. The
rectangle is clipped to the ROI (Sutherland-Hodgman) and exposed as a polygon (debug overlay) plus
a boolean mask for the segmentation stage. All factors are tunable candidates (``stick.search_region``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from spacedrums.capture.roi import Roi
from spacedrums.hands.grip import GripReference


@dataclass(frozen=True)
class SearchRegionSettings:
    length_factor: float = 4.0  # x hand span, forward along the grip direction
    width_factor: float = 1.2  # x hand span, total width
    back_factor: float = 0.5  # x hand span, backwards from the grip point (covers the grip itself)
    min_span_px: float = 8.0  # smaller hands: region not computed (too little resolution)

    def __post_init__(self) -> None:
        for name in ("length_factor", "width_factor", "min_span_px"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.back_factor < 0:
            raise ValueError("back_factor must be >= 0")

    @classmethod
    def from_config(cls, stick_cfg: dict[str, Any]) -> SearchRegionSettings:
        r = stick_cfg["search_region"]
        return cls(length_factor=float(r["length_factor"]), width_factor=float(r["width_factor"]),
                   back_factor=float(r["back_factor"]), min_span_px=float(r["min_span_px"]))


@dataclass(frozen=True)
class SearchRegion:
    origin_px: tuple[float, float]  # grip point in ROI px
    dir_px: tuple[float, float]  # unit direction in px (image plane)
    span_px: float  # hand span in px
    length_px: float
    width_px: float
    corners_px: np.ndarray  # (4, 2) unclipped rotated rectangle
    polygon_px: np.ndarray  # (n, 2) clipped to the ROI (n may be 0 when fully outside)
    bbox_px: tuple[int, int, int, int]  # x0, y0, x1, y1 (exclusive) of the clipped polygon
    mask: np.ndarray  # (roi_h, roi_w) bool

    @property
    def empty(self) -> bool:
        return self.polygon_px.shape[0] < 3

    @property
    def area_px(self) -> float:
        return float(self.mask.sum())


def to_roi_px(point_norm: tuple[float, float], roi: Roi) -> tuple[float, float]:
    """ROI-normalized -> ROI-crop pixel coordinates (origin at the ROI's top-left)."""
    return (point_norm[0] * roi.w, point_norm[1] * roi.h)


def to_roi_norm(point_px: tuple[float, float], roi: Roi) -> tuple[float, float]:
    return (point_px[0] / roi.w, point_px[1] / roi.h)


def vec_norm_to_px(v: tuple[float, float], roi: Roi) -> np.ndarray:
    return np.array([v[0] * roi.w, v[1] * roi.h], dtype=float)


def unit_px_to_norm(u_px: np.ndarray, roi: Roi) -> tuple[float, float]:
    """Unit pixel direction -> unit vector in the ROI-normalized frame (the contract's unit_vector2)."""
    v = np.array([u_px[0] / roi.w, u_px[1] / roi.h], dtype=float)
    n = float(np.hypot(v[0], v[1]))
    return (float(v[0] / n), float(v[1] / n))


def clip_polygon(poly: np.ndarray, w: int, h: int) -> np.ndarray:
    """Sutherland-Hodgman clip of a convex polygon against [0, w] x [0, h]."""
    def clip_edge(points: list[np.ndarray], inside, intersect) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        n = len(points)
        for i in range(n):
            cur, prev = points[i], points[i - 1]
            cur_in, prev_in = inside(cur), inside(prev)
            if cur_in:
                if not prev_in:
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif prev_in:
                out.append(intersect(prev, cur))
        return out

    def isect_x(x0: float):
        def f(p: np.ndarray, q: np.ndarray) -> np.ndarray:
            t = (x0 - p[0]) / (q[0] - p[0])
            return np.array([x0, p[1] + t * (q[1] - p[1])])
        return f

    def isect_y(y0: float):
        def f(p: np.ndarray, q: np.ndarray) -> np.ndarray:
            t = (y0 - p[1]) / (q[1] - p[1])
            return np.array([p[0] + t * (q[0] - p[0]), y0])
        return f

    pts = [np.asarray(p, dtype=float) for p in poly]
    for inside, intersect in (
        (lambda p: p[0] >= 0, isect_x(0.0)),
        (lambda p: p[0] <= w, isect_x(float(w))),
        (lambda p: p[1] >= 0, isect_y(0.0)),
        (lambda p: p[1] <= h, isect_y(float(h))),
    ):
        if not pts:
            break
        pts = clip_edge(pts, inside, intersect)
    return np.array(pts, dtype=float).reshape(-1, 2)


def search_region(grip: GripReference, roi: Roi, settings: SearchRegionSettings) -> SearchRegion | None:
    """Rotated rectangle along the grip direction prior; ``None`` without a direction or a usable span."""
    if grip.direction is None:
        return None
    origin = np.array(to_roi_px(grip.point, roi))
    d = vec_norm_to_px(grip.direction, roi)
    dn = float(np.hypot(d[0], d[1]))
    if dn <= 0:
        return None
    d /= dn
    span_px = float(np.hypot(*vec_norm_to_px(grip.span_vec, roi)))
    if span_px < settings.min_span_px:
        return None
    length = settings.length_factor * span_px
    width = settings.width_factor * span_px
    back = settings.back_factor * span_px
    n = np.array([-d[1], d[0]])  # left normal
    p0 = origin - back * d
    p1 = origin + length * d
    corners = np.array([p0 + n * width / 2, p1 + n * width / 2, p1 - n * width / 2, p0 - n * width / 2])
    poly = clip_polygon(corners, roi.w, roi.h)
    mask = np.zeros((roi.h, roi.w), dtype=bool)
    if poly.shape[0] >= 3:
        cv2.fillPoly(mask.view(np.uint8), [np.round(poly).astype(np.int32)], 1)
        x0, y0 = np.floor(poly.min(axis=0)).astype(int)
        x1, y1 = np.ceil(poly.max(axis=0)).astype(int) + 1
        bbox = (max(0, int(x0)), max(0, int(y0)), min(roi.w, int(x1)), min(roi.h, int(y1)))
    else:
        bbox = (0, 0, 0, 0)
    return SearchRegion(origin_px=(float(origin[0]), float(origin[1])), dir_px=(float(d[0]), float(d[1])),
                        span_px=span_px, length_px=length, width_px=width, corners_px=corners,
                        polygon_px=poly, bbox_px=bbox, mask=mask)


__all__ = ["SearchRegion", "SearchRegionSettings", "clip_polygon", "search_region", "to_roi_norm",
           "to_roi_px", "unit_px_to_norm", "vec_norm_to_px"]
