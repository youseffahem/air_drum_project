"""The single camera -> AR display mapping.

Zones, evidence and records stay in ROI-normalised camera coordinates. The AR display is the mirrored
camera image, either the tracking frame upscaled by ``scale`` (standard capture) or the full native frame,
in which the tracking field of view is a ``scale`` x larger window with ``pad`` mirrored display pixels to
its left (native 1280x720 capture: crop x 159, width 960, so ``pad`` = 1280 - 159 - 960 = 161).
With ``pad == 0`` the mapping equals ``StageRenderer.to_display``.
"""

from __future__ import annotations

from dataclasses import dataclass

from spacedrums.capture.roi import Roi


@dataclass(frozen=True)
class DisplayMap:
    out_w: int  # composed AR image width (display pixels)
    out_h: int
    tracking_w: int  # tracking frame width (camera pixels)
    scale: float  # display pixels per tracking pixel
    pad: float = 0.0  # mirrored display pixels left of the tracking field of view

    @classmethod
    def upscaled(cls, tracking_w: int, tracking_h: int, scale: float) -> DisplayMap:
        """Standard capture: the mirrored tracking frame, ``scale`` x larger."""
        return cls(round(tracking_w * scale), round(tracking_h * scale), tracking_w, scale)

    @classmethod
    def native(cls, frame_w: int, frame_h: int, crop_px, tracking_w: int) -> DisplayMap:
        """Full native frame; ``crop_px`` = [x, y, w, h] of the tracking field of view in it."""
        x, _, w, _ = crop_px
        return cls(frame_w, frame_h, tracking_w, w / tracking_w, frame_w - x - w)

    def to_display(self, p, roi: Roi) -> tuple[float, float]:
        """ROI-normalised camera point -> display pixel (mirrored)."""
        return (
            (self.tracking_w - 1 - (roi.x + p[0] * roi.w)) * self.scale + self.pad,
            (roi.y + p[1] * roi.h) * self.scale,
        )

    def roi_box(self, roi: Roi) -> tuple[int, int, int, int]:
        """Display box (x0, y0, x1, y1) of the tracking ROI."""
        xa, y0 = self.to_display((1.0, 0.0), roi)
        xb, y1 = self.to_display((0.0, 1.0), roi)
        return round(min(xa, xb)), round(y0), round(max(xa, xb)), round(y1)


__all__ = ["DisplayMap"]
