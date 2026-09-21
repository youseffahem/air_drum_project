"""Robust segment/surface intersections and linear sub-frame timing."""

from __future__ import annotations

import math
from dataclasses import dataclass

from spacedrums.geometry.zones import Arc, Point, Segment, Surface, _local

EPS = 1e-9


@dataclass(frozen=True)
class Crossing:
    s: float
    point: Point


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def segment_segment(a: Point, b: Point, surface: Segment, *, eps: float = EPS) -> Crossing | None:
    """Return the first proper point intersection; collinear overlap is not a unique crossing."""
    r = (b[0] - a[0], b[1] - a[1])
    q, q2 = surface.p0, surface.p1
    d = (q2[0] - q[0], q2[1] - q[1])
    denom = _cross(r, d)
    qa = (q[0] - a[0], q[1] - a[1])
    if abs(denom) <= eps:
        return None
    s = _cross(qa, d) / denom
    u = _cross(qa, r) / denom
    if -eps <= s <= 1 + eps and -eps <= u <= 1 + eps:
        s = min(1.0, max(0.0, s))
        return Crossing(s, (a[0] + s * r[0], a[1] + s * r[1]))
    return None


def segment_arc(a: Point, b: Point, arc: Arc, *, eps: float = EPS) -> Crossing | None:
    a0 = _local(a, arc.center, arc.angle_rad)
    b0 = _local(b, arc.center, arc.angle_rad)
    dx, dy = b0[0] - a0[0], b0[1] - a0[1]
    aa = (dx / arc.rx) ** 2 + (dy / arc.ry) ** 2
    if aa <= eps:
        return None
    bb = 2 * (a0[0] * dx / arc.rx**2 + a0[1] * dy / arc.ry**2)
    cc = (a0[0] / arc.rx) ** 2 + (a0[1] / arc.ry) ** 2 - 1
    disc = bb * bb - 4 * aa * cc
    if disc < -eps:
        return None
    disc = max(0.0, disc)
    roots = sorted(((-bb - math.sqrt(disc)) / (2 * aa), (-bb + math.sqrt(disc)) / (2 * aa)))
    for s in roots:
        if -eps <= s <= 1 + eps:
            s = min(1.0, max(0.0, s))
            x, y = a0[0] + s * dx, a0[1] + s * dy
            theta = math.atan2(y / arc.ry, x / arc.rx)
            if arc.includes_angle(theta):
                return Crossing(s, (a[0] + s * (b[0] - a[0]), a[1] + s * (b[1] - a[1])))
    return None


def segment_surface(a: Point, b: Point, surface: Surface) -> Crossing | None:
    return segment_segment(a, b, surface) if isinstance(surface, Segment) else segment_arc(a, b, surface)


def crossing_time(t0: float, t1: float, s: float) -> float:
    if t1 <= t0:
        raise ValueError("trajectory times must be strictly increasing")
    if not 0.0 <= s <= 1.0:
        raise ValueError("intersection parameter s must lie in [0, 1]")
    return t0 + s * (t1 - t0)


__all__ = ["Crossing", "crossing_time", "segment_arc", "segment_segment", "segment_surface"]
