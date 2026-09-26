"""Deterministic layout fit (Phase 14, Task 14.4): reach envelope -> scaled/translated Phase 04 layout.

Everything here is a pure function of its inputs (no clock, randomness or I/O): the same sweep,
template and settings always produce byte-identical zones (equal canonical-JSON hashes).

Transform ``p' = s * p + t`` in ROI-normalized coordinates (ADR-0005). Both normalized axes are
linear in pixels, so a uniform ``s`` is also a uniform scale in pixels: ellipse orientations, arc
parameter ranges and inward normals are invariant and are copied, never recomputed from rounded
values. Rotation is not supported (phase Open Question; default no). The identity transform
returns an exact deep copy of the template, which is the "zero drift" regression of the phase.

Overlap test: every zone outline is replaced by a *circumscribed* polygon (64 vertices by
default), which contains the true ellipse, so "outlines do not intersect" implies "zones do not
overlap". Two zones closer than ~0.1 % of a radius may be reported as touching; that is the
conservative side of the test.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from spacedrums.config import config_hash
from spacedrums.geometry import ZoneRegistry

ZoneDict = dict[str, Any]
OUTLINE_VERTICES = 64
TOLERANCE = 1e-9


class LayoutError(ValueError):
    """A layout request violated a hard rule (unknown zone, nudge out of bounds, overlap...)."""


@dataclass(frozen=True)
class Box:
    """Axis-aligned box ``[x0, y0, x1, y1]`` in ROI-normalized units (y down)."""

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        values = (self.x0, self.y0, self.x1, self.y1)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("box coordinates must be finite")
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("box needs x0 <= x1 and y0 <= y1")

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    @classmethod
    def from_list(cls, values: Sequence[float]) -> Box:
        x0, y0, x1, y1 = (float(v) for v in values)
        return cls(x0, y0, x1, y1)

    @classmethod
    def union(cls, boxes: Iterable[Box]) -> Box:
        items = list(boxes)
        if not items:
            raise ValueError("union of no boxes")
        return cls(
            min(b.x0 for b in items),
            min(b.y0 for b in items),
            max(b.x1 for b in items),
            max(b.y1 for b in items),
        )


@dataclass(frozen=True)
class ScaleTranslate:
    """``p' = scale * p + (tx, ty)``; no rotation (Open Question)."""

    scale: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    def __post_init__(self) -> None:
        if not (math.isfinite(self.scale) and self.scale > 0):
            raise ValueError("scale must be finite and > 0")
        if not (math.isfinite(self.tx) and math.isfinite(self.ty)):
            raise ValueError("translation must be finite")

    @property
    def is_identity(self) -> bool:
        return self.scale == 1.0 and self.tx == 0.0 and self.ty == 0.0

    def point(self, p: Sequence[float]) -> list[float]:
        return [self.scale * float(p[0]) + self.tx, self.scale * float(p[1]) + self.ty]

    def to_dict(self) -> dict[str, Any]:
        return {"scale": self.scale, "translate": [self.tx, self.ty]}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ScaleTranslate:
        return cls(float(d["scale"]), float(d["translate"][0]), float(d["translate"][1]))


@dataclass(frozen=True)
class FitSettings:
    """Layout-fit tunables (all *candidates*, phase "Decisions That Must Be Experimentally Validated")."""

    margin: float = 0.02  # ROI-normalized inset of the reach envelope on every side
    scale_min: float = 0.7  # below / above: clamp and warn (a sweep this small/large is suspect)
    scale_max: float = 1.3
    roi_inset: float = 0.01  # the fitted layout must stay inside [inset, 1 - inset]^2

    def __post_init__(self) -> None:
        if not (0 <= self.margin < 0.5 and 0 <= self.roi_inset < 0.5):
            raise ValueError("margin and roi_inset must lie in [0, 0.5)")
        if not (0 < self.scale_min <= 1.0 <= self.scale_max):
            raise ValueError("scale bounds need 0 < scale_min <= 1 <= scale_max")

    def to_dict(self) -> dict[str, float]:
        return {
            "margin": self.margin,
            "scale_min": self.scale_min,
            "scale_max": self.scale_max,
            "roi_inset": self.roi_inset,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> FitSettings:
        return cls(**{k: float(d[k]) for k in ("margin", "scale_min", "scale_max", "roi_inset")})


@dataclass(frozen=True)
class FitResult:
    transform: ScaleTranslate
    target: Box | None
    template_bbox: Box
    fitted_bbox: Box
    clamped: bool
    warnings: tuple[str, ...]


# ----------------------------------------------------------------------------- extents


def zone_bbox(zone: Mapping[str, Any]) -> Box:
    """Exact axis-aligned extent of a config zone's shape (rotated ellipse or polygon)."""
    shape = zone["shape"]
    if shape["type"] == "ELLIPSE":
        cx, cy = (float(v) for v in shape["center"])
        rx, ry, a = float(shape["rx"]), float(shape["ry"]), float(shape["angle_rad"])
        c, s = math.cos(a), math.sin(a)
        hw, hh = math.hypot(rx * c, ry * s), math.hypot(rx * s, ry * c)
        return Box(cx - hw, cy - hh, cx + hw, cy + hh)
    xs = [float(p[0]) for p in shape["points"]]
    ys = [float(p[1]) for p in shape["points"]]
    return Box(min(xs), min(ys), max(xs), max(ys))


def layout_bbox(zones: Sequence[Mapping[str, Any]]) -> Box:
    return Box.union(zone_bbox(z) for z in zones)


def percentile_box(points: Sequence[Sequence[float]], lo: float, hi: float) -> Box:
    """Reach envelope: per-axis percentile box of tip positions (numpy 'linear' percentiles)."""
    if not (0 <= lo < hi <= 100):
        raise ValueError("percentiles need 0 <= lo < hi <= 100")
    arr = np.asarray(points, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) == 0 or not np.isfinite(arr).all():
        raise ValueError("points must be a non-empty finite (n, 2) array")
    x0, x1 = (float(v) for v in np.percentile(arr[:, 0], [lo, hi]))
    y0, y1 = (float(v) for v in np.percentile(arr[:, 1], [lo, hi]))
    return Box(x0, y0, x1, y1)


# ----------------------------------------------------------------------------- transforms


def transform_zone(zone: Mapping[str, Any], transform: ScaleTranslate) -> ZoneDict:
    """Apply ``transform`` to a config zone. Normals, angles and arc ranges are invariant (copied)."""
    out: ZoneDict = copy.deepcopy(dict(zone))
    if transform.is_identity:
        return out
    s = transform.scale
    shape = out["shape"]
    if shape["type"] == "ELLIPSE":
        shape["center"] = transform.point(shape["center"])
        shape["rx"] = s * float(shape["rx"])
        shape["ry"] = s * float(shape["ry"])
    else:
        shape["points"] = [transform.point(p) for p in shape["points"]]
    surface = out["impact_surface"]
    if surface["type"] == "ARC":
        surface["center"] = transform.point(surface["center"])
        surface["rx"] = s * float(surface["rx"])
        surface["ry"] = s * float(surface["ry"])
    else:
        surface["p0"] = transform.point(surface["p0"])
        surface["p1"] = transform.point(surface["p1"])
    return out


def transform_layout(zones: Sequence[Mapping[str, Any]], transform: ScaleTranslate) -> list[ZoneDict]:
    return [transform_zone(z, transform) for z in zones]


def apply_nudges(
    zones: Sequence[Mapping[str, Any]], nudges: Mapping[str, Sequence[float]], max_nudge: float
) -> list[ZoneDict]:
    """Bounded manual nudge: translate single zones by ``(dx, dy)`` with ``|dx|, |dy| <= max_nudge``."""
    ids = [z["zone_id"] for z in zones]
    unknown = sorted(set(nudges) - set(ids))
    if unknown:
        raise LayoutError(f"nudge for unknown zone(s) {unknown}")
    out = []
    for zone in zones:
        d = nudges.get(zone["zone_id"])
        if d is None:
            out.append(copy.deepcopy(dict(zone)))
            continue
        dx, dy = float(d[0]), float(d[1])
        if not (math.isfinite(dx) and math.isfinite(dy)) or max(abs(dx), abs(dy)) > max_nudge + TOLERANCE:
            raise LayoutError(f"nudge {zone['zone_id']} ({dx}, {dy}) exceeds max_nudge {max_nudge}")
        out.append(transform_zone(zone, ScaleTranslate(1.0, dx, dy)))
    return out


def apply_sample_overrides(
    zones: Sequence[Mapping[str, Any]],
    overrides: Mapping[str, str],
    available: Iterable[str] | None = None,
) -> list[ZoneDict]:
    """Per-zone drum sound choice (REQ-056, config-stage sound change); geometry untouched."""
    ids = [z["zone_id"] for z in zones]
    unknown = sorted(set(overrides) - set(ids))
    if unknown:
        raise LayoutError(f"sample override for unknown zone(s) {unknown}")
    allowed = None if available is None else set(available)
    out = []
    for zone in zones:
        z = copy.deepcopy(dict(zone))
        if zone["zone_id"] in overrides:
            sample = str(overrides[zone["zone_id"]])
            if not sample or (allowed is not None and sample not in allowed):
                raise LayoutError(f"sample {sample!r} for zone {zone['zone_id']} is not in the sample bank")
            z["sample_id"] = sample
        out.append(z)
    return out


# ----------------------------------------------------------------------------- fit


def fit_layout(
    template_zones: Sequence[Mapping[str, Any]], envelope: Box | None, settings: FitSettings
) -> FitResult:
    """Uniform scale + translation of the template's bounding box into the inset reach envelope.

    Scale = the largest that fits the template box inside the envelope minus ``margin`` on every
    side, clamped to ``[scale_min, scale_max]`` and to what fits the ROI inset box; the scaled box is
    centred on the envelope and then shifted (never scaled again) to stay inside the ROI inset box.
    """
    template_bbox = layout_bbox(template_zones)
    if envelope is None:
        return FitResult(ScaleTranslate(), None, template_bbox, template_bbox, False, ("no reach envelope",))
    warnings: list[str] = []
    clamped = False
    m = settings.margin
    target = Box(
        envelope.x0 + min(m, envelope.width / 2),
        envelope.y0 + min(m, envelope.height / 2),
        envelope.x1 - min(m, envelope.width / 2),
        envelope.y1 - min(m, envelope.height / 2),
    )
    if target.width <= 0 or target.height <= 0:
        warnings.append("reach envelope is not larger than the margins; scale clamped to scale_min")
        raw = settings.scale_min
    else:
        raw = min(target.width / template_bbox.width, target.height / template_bbox.height)
    scale = min(max(raw, settings.scale_min), settings.scale_max)
    if scale != raw:
        clamped = True
        warnings.append(
            f"envelope-derived scale {raw:.3f} outside [{settings.scale_min}, {settings.scale_max}]; "
            f"clamped to {scale:.3f} (check the sweep; move closer/farther)"
        )
    lo, hi = settings.roi_inset, 1.0 - settings.roi_inset
    s_roi = min((hi - lo) / template_bbox.width, (hi - lo) / template_bbox.height)
    if scale > s_roi:
        clamped = True
        warnings.append(f"scale {scale:.3f} does not fit the ROI; reduced to {s_roi:.3f}")
        scale = s_roi
    cx, cy = target.center
    tcx, tcy = template_bbox.center
    tx, ty = cx - scale * tcx, cy - scale * tcy
    x0, x1 = scale * template_bbox.x0 + tx, scale * template_bbox.x1 + tx
    y0, y1 = scale * template_bbox.y0 + ty, scale * template_bbox.y1 + ty
    shift_x = (lo - x0) if x0 < lo else ((hi - x1) if x1 > hi else 0.0)
    shift_y = (lo - y0) if y0 < lo else ((hi - y1) if y1 > hi else 0.0)
    if shift_x or shift_y:
        clamped = True
        warnings.append("layout shifted to stay inside the ROI (reach envelope extends past the ROI)")
        tx, ty = tx + shift_x, ty + shift_y
    transform = ScaleTranslate(scale, tx, ty)
    fitted = Box(
        scale * template_bbox.x0 + tx,
        scale * template_bbox.y0 + ty,
        scale * template_bbox.x1 + tx,
        scale * template_bbox.y1 + ty,
    )
    return FitResult(transform, target, template_bbox, fitted, clamped, tuple(warnings))


# ----------------------------------------------------------------------------- checks


def zone_outline(zone: Mapping[str, Any], n: int = OUTLINE_VERTICES) -> np.ndarray:
    """(n, 2) outline; ellipses as a circumscribed n-gon (contains the ellipse)."""
    shape = zone["shape"]
    if shape["type"] != "ELLIPSE":
        return np.asarray(shape["points"], dtype=float)
    k = np.arange(n) * (2.0 * math.pi / n)
    r = 1.0 / math.cos(math.pi / n)
    local = np.stack([float(shape["rx"]) * r * np.cos(k), float(shape["ry"]) * r * np.sin(k)], axis=1)
    a = float(shape["angle_rad"])
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return local @ rot.T + np.asarray(shape["center"], dtype=float)


def _cross(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    return u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]


def _edges(poly: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return poly, np.roll(poly, -1, axis=0)


def _points_in_polygon(points: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Ray casting (even-odd), vectorized over points."""
    a, b = _edges(poly)
    px, py = points[:, None, 0], points[:, None, 1]
    ay, by = a[None, :, 1], b[None, :, 1]
    straddle = (ay > py) != (by > py)
    with np.errstate(divide="ignore", invalid="ignore"):
        x_cross = a[None, :, 0] + (py - ay) * (b[None, :, 0] - a[None, :, 0]) / (by - ay)
    hits = straddle & (px < x_cross)
    return (hits.sum(axis=1) % 2) == 1


def polygons_intersect(p: np.ndarray, q: np.ndarray) -> bool:
    """True when the polygon areas overlap or touch (edge crossing/contact or containment)."""
    a0, a1 = _edges(p)
    b0, b1 = _edges(q)
    A0, A1 = a0[:, None, :], a1[:, None, :]
    B0, B1 = b0[None, :, :], b1[None, :, :]
    d1 = _cross(B1 - B0, A0 - B0)
    d2 = _cross(B1 - B0, A1 - B0)
    d3 = _cross(A1 - A0, B0 - A0)
    d4 = _cross(A1 - A0, B1 - A0)
    crossing = (d1 * d2 <= 0) & (d3 * d4 <= 0)
    collinear = (d1 == 0) & (d2 == 0)
    if collinear.any():  # collinear pairs intersect only when their extents overlap
        lo_a, hi_a = np.minimum(A0, A1), np.maximum(A0, A1)
        lo_b, hi_b = np.minimum(B0, B1), np.maximum(B0, B1)
        overlap = np.all((lo_a <= hi_b) & (lo_b <= hi_a), axis=-1)
        crossing = np.where(collinear, overlap, crossing)
    if crossing.any():
        return True
    return bool(_points_in_polygon(p[:1], q)[0] or _points_in_polygon(q[:1], p)[0])


def _point_segment_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    P = points[:, None, :]
    A, B = a[None, :, :], b[None, :, :]
    ab = B - A
    denom = np.maximum((ab * ab).sum(axis=-1), 1e-300)
    t = np.clip(((P - A) * ab).sum(axis=-1) / denom, 0.0, 1.0)
    return np.linalg.norm(P - (A + t[..., None] * ab), axis=-1)


def polygon_gap(p: np.ndarray, q: np.ndarray) -> float:
    """Minimum boundary distance (0 when the polygons intersect or touch)."""
    if polygons_intersect(p, q):
        return 0.0
    qa, qb = _edges(q)
    pa, pb = _edges(p)
    return float(min(_point_segment_distance(p, qa, qb).min(), _point_segment_distance(q, pa, pb).min()))


def overlap_report(
    zones: Sequence[Mapping[str, Any]], *, ambiguity_gap: float = 0.0, n: int = OUTLINE_VERTICES
) -> dict[str, Any]:
    """Pairwise overlap (blocks save) and near-neighbour ambiguity (gap < ``ambiguity_gap``, flag only)."""
    outlines = [zone_outline(z, n) for z in zones]
    overlaps, near = [], []
    for i in range(len(zones)):
        for j in range(i + 1, len(zones)):
            pair = [zones[i]["zone_id"], zones[j]["zone_id"]]
            gap = polygon_gap(outlines[i], outlines[j])
            if gap == 0.0:
                overlaps.append(pair)
            elif gap < ambiguity_gap:
                near.append({"zones": pair, "gap": gap})
    return {
        "passed": not overlaps,
        "overlapping_pairs": overlaps,
        "near_pairs": near,
        "ambiguity_gap": ambiguity_gap,
        "method": f"circumscribed {n}-gon outlines; edge crossing/containment test",
    }


def inside_roi_report(zones: Sequence[Mapping[str, Any]], *, inset: float = 0.0) -> dict[str, Any]:
    """Zones whose extent leaves ``[inset, 1 - inset]^2`` (warning: tips outside the ROI are unseen)."""
    outside = []
    for z in zones:
        b = zone_bbox(z)
        if (
            b.x0 < inset - TOLERANCE
            or b.y0 < inset - TOLERANCE
            or b.x1 > 1 - inset + TOLERANCE
            or b.y1 > 1 - inset + TOLERANCE
        ):
            outside.append({"zone_id": z["zone_id"], "bbox": b.as_list()})
    return {"passed": not outside, "outside": outside, "inset": inset}


def zones_hash(zones: Sequence[Mapping[str, Any]]) -> str:
    """``config_hash`` of the zones list (the same canonical JSON the config loader hashes)."""
    return config_hash([dict(z) for z in zones])


def validate_zones(zones: Sequence[Mapping[str, Any]]) -> None:
    """Authoritative Phase 04 object-level validation (surface on boundary, normal into shape...)."""
    ZoneRegistry.from_config([dict(z) for z in zones])


def compose_layout(
    template_zones: Sequence[Mapping[str, Any]],
    transform: ScaleTranslate,
    nudges: Mapping[str, Sequence[float]],
    max_nudge: float,
    sample_overrides: Mapping[str, str],
    available_samples: Iterable[str] | None = None,
) -> list[ZoneDict]:
    """template -> transform -> nudges -> sample overrides (the order the loader recomputes)."""
    zones = transform_layout(template_zones, transform)
    zones = apply_nudges(zones, nudges, max_nudge)
    zones = apply_sample_overrides(zones, sample_overrides, available_samples)
    validate_zones(zones)
    return zones


__all__ = [
    "OUTLINE_VERTICES",
    "Box",
    "FitResult",
    "FitSettings",
    "LayoutError",
    "ScaleTranslate",
    "apply_nudges",
    "apply_sample_overrides",
    "compose_layout",
    "fit_layout",
    "inside_roi_report",
    "layout_bbox",
    "overlap_report",
    "percentile_box",
    "polygon_gap",
    "polygons_intersect",
    "transform_layout",
    "transform_zone",
    "validate_zones",
    "zone_bbox",
    "zone_outline",
    "zones_hash",
]
