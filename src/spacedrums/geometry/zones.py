"""Zone shapes, impact surfaces and schema-backed candidate layout registry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from spacedrums.contracts import HandId, TriggerType

Point = tuple[float, float]
EPS = 1e-9


def _point(value: Any, name: str) -> Point:
    if len(value) != 2:
        raise ValueError(f"{name} must have two components")
    p = (float(value[0]), float(value[1]))
    if not all(math.isfinite(v) for v in p):
        raise ValueError(f"{name} must be finite")
    return p


def _local(point: Point, center: Point, angle_rad: float) -> Point:
    dx, dy = point[0] - center[0], point[1] - center[1]
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return (c * dx + s * dy, -s * dx + c * dy)


def _world(point: Point, center: Point, angle_rad: float) -> Point:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return (center[0] + c * point[0] - s * point[1], center[1] + s * point[0] + c * point[1])


class Shape(Protocol):
    def contains(self, point: Point, *, include_boundary: bool = True) -> bool: ...
    def on_boundary(self, point: Point, *, tolerance: float = 1e-6) -> bool: ...


@dataclass(frozen=True)
class Ellipse:
    center: Point
    rx: float
    ry: float
    angle_rad: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", _point(self.center, "ellipse.center"))
        if self.rx <= 0 or self.ry <= 0:
            raise ValueError("ellipse radii must be positive")

    def implicit(self, point: Point) -> float:
        x, y = _local(point, self.center, self.angle_rad)
        return (x / self.rx) ** 2 + (y / self.ry) ** 2

    def contains(self, point: Point, *, include_boundary: bool = True) -> bool:
        q = self.implicit(point)
        return q <= 1.0 + EPS if include_boundary else q < 1.0 - EPS

    def on_boundary(self, point: Point, *, tolerance: float = 1e-6) -> bool:
        return abs(self.implicit(point) - 1.0) <= tolerance


def _point_on_segment(p: Point, a: Point, b: Point, tolerance: float) -> bool:
    cross = (p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])
    if abs(cross) > tolerance:
        return False
    return (
        min(a[0], b[0]) - tolerance <= p[0] <= max(a[0], b[0]) + tolerance
        and min(a[1], b[1]) - tolerance <= p[1] <= max(a[1], b[1]) + tolerance
    )


@dataclass(frozen=True)
class Polygon:
    points: tuple[Point, ...]

    def __post_init__(self) -> None:
        pts = tuple(_point(p, "polygon.points") for p in self.points)
        if len(pts) < 3:
            raise ValueError("polygon needs at least three points")
        area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1], strict=True))
        if abs(area2) <= EPS:
            raise ValueError("polygon area must be non-zero")
        object.__setattr__(self, "points", pts)

    def on_boundary(self, point: Point, *, tolerance: float = 1e-6) -> bool:
        return any(
            _point_on_segment(point, a, b, tolerance)
            for a, b in zip(self.points, self.points[1:] + self.points[:1], strict=True)
        )

    def contains(self, point: Point, *, include_boundary: bool = True) -> bool:
        if self.on_boundary(point):
            return include_boundary
        x, y = point
        inside = False
        for a, b in zip(self.points, self.points[1:] + self.points[:1], strict=True):
            if (a[1] > y) != (b[1] > y):
                x_cross = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                if x < x_cross:
                    inside = not inside
        return inside


@dataclass(frozen=True)
class Segment:
    p0: Point
    p1: Point

    def __post_init__(self) -> None:
        object.__setattr__(self, "p0", _point(self.p0, "segment.p0"))
        object.__setattr__(self, "p1", _point(self.p1, "segment.p1"))
        if math.dist(self.p0, self.p1) <= EPS:
            raise ValueError("impact segment must have non-zero length")


@dataclass(frozen=True)
class Arc:
    center: Point
    rx: float
    ry: float
    angle_rad: float
    theta_start_rad: float
    theta_end_rad: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", _point(self.center, "arc.center"))
        if self.rx <= 0 or self.ry <= 0:
            raise ValueError("arc radii must be positive")

    def point_at(self, theta: float) -> Point:
        return _world((self.rx * math.cos(theta), self.ry * math.sin(theta)), self.center, self.angle_rad)

    def includes_angle(self, theta: float, tolerance: float = 1e-9) -> bool:
        tau = 2.0 * math.pi
        span = (self.theta_end_rad - self.theta_start_rad) % tau
        if abs(span) <= tolerance and abs(self.theta_end_rad - self.theta_start_rad) > tolerance:
            span = tau
        rel = (theta - self.theta_start_rad) % tau
        return rel <= span + tolerance


Surface = Segment | Arc


@dataclass(frozen=True)
class Zone:
    zone_id: str
    name: str
    trigger_type: TriggerType
    shape: Ellipse | Polygon
    impact_surface: Surface
    inward_normal: Point
    allowed_hands: tuple[HandId, ...]
    sample_id: str
    gain_curve_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger_type", TriggerType(self.trigger_type))
        object.__setattr__(self, "allowed_hands", tuple(HandId(v) for v in self.allowed_hands))
        nx, ny = _point(self.inward_normal, "inward_normal")
        if abs(math.hypot(nx, ny) - 1.0) > 1e-3:
            raise ValueError(f"zone {self.zone_id}: inward_normal must be unit length")
        object.__setattr__(self, "inward_normal", (nx, ny))
        if not self.zone_id or not self.name or not self.sample_id or not self.gain_curve_id:
            raise ValueError("zone identifiers must be non-empty")
        self.validate_surface()
        m = surface_midpoint(self.impact_surface)
        scale = max(getattr(self.shape, "rx", 0.1), getattr(self.shape, "ry", 0.1), 0.1)
        if not self.shape.contains((m[0] + nx * scale * 1e-4, m[1] + ny * scale * 1e-4)):
            raise ValueError(f"zone {self.zone_id}: inward_normal does not point into shape")

    def validate_surface(self, tolerance: float = 1e-6) -> None:
        if isinstance(self.impact_surface, Segment):
            samples = (self.impact_surface.p0, surface_midpoint(self.impact_surface), self.impact_surface.p1)
        else:
            arc = self.impact_surface
            samples = tuple(
                arc.point_at(arc.theta_start_rad + (arc.theta_end_rad - arc.theta_start_rad) * f)
                for f in (0.0, 0.5, 1.0)
            )
        if not all(self.shape.on_boundary(p, tolerance=tolerance) for p in samples):
            raise ValueError(f"zone {self.zone_id}: impact surface must lie on shape boundary")


def surface_midpoint(surface: Surface) -> Point:
    if isinstance(surface, Segment):
        return ((surface.p0[0] + surface.p1[0]) / 2, (surface.p0[1] + surface.p1[1]) / 2)
    return surface.point_at((surface.theta_start_rad + surface.theta_end_rad) / 2)


def _shape(data: dict[str, Any]) -> Ellipse | Polygon:
    if data["type"] == "ELLIPSE":
        return Ellipse(tuple(data["center"]), float(data["rx"]), float(data["ry"]), float(data["angle_rad"]))
    if data["type"] == "POLYGON":
        return Polygon(tuple(tuple(p) for p in data["points"]))
    raise ValueError(f"unsupported shape {data['type']!r}")


def _surface(data: dict[str, Any]) -> Surface:
    if data["type"] == "SEGMENT":
        return Segment(tuple(data["p0"]), tuple(data["p1"]))
    if data["type"] == "ARC":
        return Arc(
            tuple(data["center"]),
            float(data["rx"]),
            float(data["ry"]),
            float(data["angle_rad"]),
            float(data["theta_start_rad"]),
            float(data["theta_end_rad"]),
        )
    raise ValueError(f"unsupported impact surface {data['type']!r}")


class ZoneRegistry:
    def __init__(self, zones: tuple[Zone, ...]) -> None:
        if not zones:
            raise ValueError("zone registry must not be empty")
        ids = [z.zone_id for z in zones]
        if len(set(ids)) != len(ids):
            raise ValueError("zone_id values must be unique")
        self._zones = zones
        self._by_id = {zone.zone_id: zone for zone in zones}

    def __iter__(self):
        return iter(self._zones)

    def __len__(self) -> int:
        return len(self._zones)

    def __getitem__(self, zone_id: str) -> Zone:
        return self._by_id[zone_id]

    @classmethod
    def from_config(cls, zones: list[dict[str, Any]]) -> ZoneRegistry:
        return cls(
            tuple(
                Zone(
                    zone_id=str(data["zone_id"]),
                    name=str(data["name"]),
                    trigger_type=TriggerType(data["trigger_type"]),
                    shape=_shape(data["shape"]),
                    impact_surface=_surface(data["impact_surface"]),
                    inward_normal=tuple(data["inward_normal"]),
                    allowed_hands=tuple(data.get("allowed_hands", ("LEFT", "RIGHT"))),
                    sample_id=str(data["sample_id"]),
                    gain_curve_id=str(data["gain_curve_id"]),
                )
                for data in zones
            )
        )

    @classmethod
    def load(cls, path: str | Path) -> ZoneRegistry:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("zones"), list):
            raise ValueError("layout must contain a zones list")
        return cls.from_config(data["zones"])


__all__ = ["Arc", "Ellipse", "Point", "Polygon", "Segment", "Surface", "Zone", "ZoneRegistry"]
