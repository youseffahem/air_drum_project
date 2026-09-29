"""Playing-area "stand here" guide overlay (Task 02.6; REQ-019, REQ-026; prototype quality).

Draws, on a full camera frame: the fixed ROI rectangle, a translucent horizontal reference band
where the hands are expected (ROI-normalized ``y`` range), a dimmed surround so the box is
unmistakable, and the instruction text. Pure drawing on a copy (or in place when asked); no
detection, no tracking, no zones (Phase 04 adds zone drawing).

Coordinates: the band is given in ROI-normalized units and converted with the single
``norm_to_px`` helper (ADR-0005), so the overlay is a first consumer of that mapping. ``mirror``
(live windows) mirrors only the camera image; the box, band and text are then drawn on it in display
space through a :class:`~spacedrums.ui.canvas.Canvas`, so the text stays readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from spacedrums.capture.roi import Roi, norm_to_px_point
from spacedrums.ui.canvas import Canvas
from spacedrums.ui.preview import mirror_preview

DEFAULT_INSTRUCTION = "Stand so both hands and sticks stay inside the box"


@dataclass(frozen=True)
class GuideStyle:
    box_color: tuple[int, int, int] = (0, 220, 0)  # BGR
    box_thickness: int = 3
    band_color: tuple[int, int, int] = (0, 200, 255)
    band_alpha: float = 0.25
    dim_alpha: float = 0.45  # how much to darken outside the ROI (0 = off)
    text_color: tuple[int, int, int] = (255, 255, 255)
    text_scale: float = 0.7
    text_thickness: int = 2
    status_scale: float = 0.45
    status_thickness: int = 1
    font: int = cv2.FONT_HERSHEY_SIMPLEX
    extra_lines: tuple[str, ...] = field(default_factory=tuple)


DEFAULT_STYLE = GuideStyle()


def draw_guide(
    frame: np.ndarray,
    roi: Roi,
    *,
    band: tuple[float, float] | None = (0.45, 0.75),
    instruction: str = DEFAULT_INSTRUCTION,
    style: GuideStyle = DEFAULT_STYLE,
    status_lines: tuple[str, ...] | list[str] = (),
    inplace: bool = False,
    mirror: bool = False,
) -> np.ndarray:
    """Return the frame with the guide drawn. ``band`` is ``(y0, y1)`` in ROI-normalized y (down)."""
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("draw_guide expects an (h, w, 3) BGR frame")
    h, w = frame.shape[:2]
    if not roi.fits(w, h):
        raise ValueError(f"ROI {roi.as_tuple()} does not fit a {w}x{h} frame")
    if mirror and inplace:
        raise ValueError("a mirrored guide is drawn on a new display image, never in place")
    out = mirror_preview(frame) if mirror else (frame if inplace else frame.copy())
    canvas = Canvas.for_display(out, mirror)
    roi_cols = canvas.span(roi.x, roi.x1)

    if style.dim_alpha > 0:
        dark = (out.astype(np.float32) * (1.0 - style.dim_alpha)).astype(np.uint8)
        dark[roi.y:roi.y1, roi_cols] = out[roi.y:roi.y1, roi_cols]
        out[:] = dark

    if band is not None:
        y0, y1 = band
        if not (0.0 <= y0 < y1 <= 1.0):
            raise ValueError("band must satisfy 0 <= y0 < y1 <= 1 (ROI-normalized, y down)")
        _, py0 = norm_to_px_point(0.0, y0, roi)
        _, py1 = norm_to_px_point(0.0, y1, roi)
        py0i, py1i = int(round(py0)), int(round(py1))
        overlay = out[py0i:py1i, roi_cols].copy()
        overlay[:] = (
            overlay.astype(np.float32) * (1 - style.band_alpha)
            + np.array(style.band_color, dtype=np.float32) * style.band_alpha
        ).astype(np.uint8)
        out[py0i:py1i, roi_cols] = overlay
        canvas.upright(roi.x, roi.x1).put_text("hands here", (roi.x + 8, max(py0i - 6, 12)),
                                               style.font, 0.55, style.band_color, 1, cv2.LINE_AA)

    canvas.rectangle((roi.x, roi.y), (roi.x1 - 1, roi.y1 - 1), style.box_color,
                     style.box_thickness)

    y_text = 28
    main_lines = [(line, style.text_scale, style.text_thickness)
                  for line in (instruction, *style.extra_lines)]
    small_lines = [(line, style.status_scale, style.status_thickness) for line in status_lines]
    for line, scale, thick in main_lines + small_lines:
        if not line:
            continue
        (tw, th), _ = cv2.getTextSize(line, style.font, scale, thick)
        x_text = max((w - tw) // 2, 4)
        cv2.rectangle(out, (x_text - 6, y_text - th - 6), (x_text + tw + 6, y_text + 6),
                      (0, 0, 0), -1)
        cv2.putText(out, line, (x_text, y_text), style.font, scale, style.text_color,
                    thick, cv2.LINE_AA)
        y_text += th + 14
    return out


def guide_status_lines(stats: Any, negotiated: Any | None = None) -> list[str]:
    """Compact capture-stats line for the prototype window (drops must always be visible)."""
    fps = f"{stats.fps_measured:.1f}" if stats.fps_measured is not None else "--"
    lines = [f"measured {fps} fps | delivered {stats.delivered} dropped {stats.dropped} "
             f"dup {stats.duplicates} stalled {stats.stalled}"]
    if negotiated is not None:
        lines.append(f"{negotiated.backend} {negotiated.width}x{negotiated.height} "
                     f"driver-fps-prop {negotiated.fps_prop} (advertised, not measured)")
    return lines


__all__ = ["DEFAULT_INSTRUCTION", "GuideStyle", "draw_guide", "guide_status_lines"]
