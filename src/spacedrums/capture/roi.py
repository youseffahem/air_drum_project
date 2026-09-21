"""Fixed playing ROI and the single px <-> ROI-normalized coordinate mapping (ADR-0005; Task 02.6).

Convention (phases/README.md section 7): ``x = (x_px - roi.x) / roi.w``,
``y = (y_px - roi.y) / roi.h``; origin at the ROI's top-left; **y increases downward**;
values outside ``[0, 1]`` are legal and mean "outside the ROI". This module is the only
implementation of the mapping; every later module (hands, geometry, calib, eval) imports it.

The ROI crop is pure array slicing: no resampling, no copy (Phase 02 ROI policy).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

Number = float | int | np.ndarray


@dataclass(frozen=True)
class Roi:
    """Fixed playing ROI in full-frame pixels ``[x, y, w, h]`` (``rect_px`` of common.schema.json)."""

    x: int
    y: int
    w: int
    h: int

    def __post_init__(self) -> None:
        for name in ("x", "y", "w", "h"):
            v = getattr(self, name)
            if int(v) != v:
                raise ValueError(f"Roi.{name} must be an integer pixel value, got {v!r}")
            object.__setattr__(self, name, int(v))
        if self.x < 0 or self.y < 0:
            raise ValueError(f"Roi origin must be >= 0, got ({self.x}, {self.y})")
        if self.w < 1 or self.h < 1:
            raise ValueError(f"Roi size must be >= 1 px, got {self.w}x{self.h}")

    @classmethod
    def from_rect(cls, rect: Any) -> Roi:
        x, y, w, h = rect
        return cls(x, y, w, h)

    @classmethod
    def full_frame(cls, frame_w: int, frame_h: int) -> Roi:
        return cls(0, 0, int(frame_w), int(frame_h))

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def fits(self, frame_w: int, frame_h: int) -> bool:
        return self.x + self.w <= frame_w and self.y + self.h <= frame_h

    @property
    def aspect(self) -> float:
        """``w / h`` — needed to derive isotropic units from ROI-normalized ones (ADR-0005)."""
        return self.w / self.h

    @property
    def x1(self) -> int:
        return self.x + self.w

    @property
    def y1(self) -> int:
        return self.y + self.h


def px_to_norm(x_px: Number, y_px: Number, roi: Roi) -> tuple[Any, Any]:
    """Full-frame pixel -> ROI-normalized (y down). Works on scalars and NumPy arrays."""
    return ((np.asarray(x_px, dtype=float) - roi.x) / roi.w,
            (np.asarray(y_px, dtype=float) - roi.y) / roi.h)


def norm_to_px(x: Number, y: Number, roi: Roi) -> tuple[Any, Any]:
    """ROI-normalized -> full-frame pixel (float; callers round if they need integers)."""
    return (roi.x + np.asarray(x, dtype=float) * roi.w,
            roi.y + np.asarray(y, dtype=float) * roi.h)


def px_to_norm_point(x_px: float, y_px: float, roi: Roi) -> tuple[float, float]:
    """Scalar convenience returning plain floats (``point2`` of the contracts)."""
    nx, ny = px_to_norm(x_px, y_px, roi)
    return float(nx), float(ny)


def norm_to_px_point(x: float, y: float, roi: Roi) -> tuple[float, float]:
    px, py = norm_to_px(x, y, roi)
    return float(px), float(py)


def crop_roi(frame: np.ndarray, roi: Roi) -> np.ndarray:
    """ROI crop as a *view* (no copy, no resampling). ``frame`` is ``(h, w[, c])``."""
    h, w = frame.shape[:2]
    if not roi.fits(w, h):
        raise ValueError(f"ROI {roi.as_tuple()} does not fit a {w}x{h} frame")
    return frame[roi.y:roi.y1, roi.x:roi.x1]


__all__ = ["Roi", "crop_roi", "norm_to_px", "norm_to_px_point", "px_to_norm", "px_to_norm_point"]
