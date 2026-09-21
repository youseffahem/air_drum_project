"""The ``hands`` coordinate boundary: estimator-native landmarks -> ROI-normalized (ADR-0005).

architecture.md section 9: "``hands`` converts the landmark library's native coordinates to
ROI-normalized at its boundary; no other module sees library coordinates." This module is that
boundary and the only place the native convention is spelled out.

Native convention (MediaPipe Tasks ``NormalizedLandmark``): ``x, y`` in ``[0, 1]`` relative to the
**image handed to the detector**, origin top-left, y down; values outside ``[0, 1]`` are possible for
landmarks inferred beyond the image edge. The image handed to the detector is either the ROI crop
(Phase 02 ROI policy; ``DetectorInput.ROI``) or the full frame (``DetectorInput.FULL``), so the
conversion goes native -> full-frame pixels -> ROI-normalized through the single px<->normalized
implementation of ``spacedrums.capture.roi`` (the only ``capture`` import ``hands`` is allowed,
architecture.md section 2.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from spacedrums.capture.roi import Roi, px_to_norm


class DetectorInput(StrEnum):
    """Which pixels the estimator sees; decides the native frame of its output."""

    ROI = "ROI"
    FULL = "FULL"


@dataclass(frozen=True)
class InputFrame:
    """Placement of the detector's input image inside the full frame, in pixels."""

    x0: int
    y0: int
    w: int
    h: int

    @classmethod
    def for_roi(cls, roi: Roi) -> InputFrame:
        return cls(roi.x, roi.y, roi.w, roi.h)

    @classmethod
    def for_full(cls, frame_w: int, frame_h: int) -> InputFrame:
        return cls(0, 0, int(frame_w), int(frame_h))


def native_to_full_px(xy_native: np.ndarray, inp: InputFrame) -> np.ndarray:
    """``(N, 2)`` native normalized -> ``(N, 2)`` full-frame pixel coordinates (float)."""
    xy = np.asarray(xy_native, dtype=float).reshape(-1, 2)
    out = np.empty_like(xy)
    out[:, 0] = inp.x0 + xy[:, 0] * inp.w
    out[:, 1] = inp.y0 + xy[:, 1] * inp.h
    return out


def native_to_roi_norm(xy_native: np.ndarray, inp: InputFrame, roi: Roi) -> np.ndarray:
    """``(N, 2)`` native normalized (relative to ``inp``) -> ``(N, 2)`` ROI-normalized, y-down.

    When the detector input *is* the ROI crop this is the identity up to floating point; the
    round trip through pixels is kept so that ROI and FULL inputs share one code path and one test.
    """
    px = native_to_full_px(xy_native, inp)
    nx, ny = px_to_norm(px[:, 0], px[:, 1], roi)
    return np.stack([nx, ny], axis=1)


def bbox_of(points_norm: np.ndarray) -> tuple[float, float, float, float]:
    """Axis-aligned ``[x, y, w, h]`` of a point set (ROI-normalized). The estimator returns no box."""
    p = np.asarray(points_norm, dtype=float).reshape(-1, 2)
    x0, y0 = p.min(axis=0)
    x1, y1 = p.max(axis=0)
    return (float(x0), float(y0), float(x1 - x0), float(y1 - y0))


__all__ = ["DetectorInput", "InputFrame", "bbox_of", "native_to_full_px", "native_to_roi_norm"]
