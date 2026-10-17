"""Native-resolution capture with a tracking frame of unchanged geometry (ADR-0047).

On HW-01 the 640x480 driver mode is the centre 960x720 window of the sensor's 1280x720 output,
scaled by 2/3 inside the camera (ECC registration of the two modes, scale 1.500-1.501, x offset
158.8-159.0 native px, y offset < 0.3 px; docs/perf/camera-quality-native-720p.md). Capturing the
native 1280x720 mode and cutting the same window therefore keeps every tracking coordinate (ROI,
zones, pixel thresholds) while the preview gets 1.5x the linear detail.

:class:`NativeCapture` is what is requested and how it is verified; :func:`tracking_frame` is the
only image operation: a crop and, when the crop is larger than the tracking size, an area-averaging
downscale. Upscaling is refused (it would invent pixels), and so is a crop whose aspect ratio
differs from the tracking frame (it would distort geometry). No temporal processing happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

FALLBACKS = ("STANDARD", "FAIL")


class NativeModeRejected(RuntimeError):
    """The requested native mode was not delivered as verified (size, frames or rate)."""

    def __init__(self, message: str, probe: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.probe = probe


@dataclass(frozen=True)
class NativeCapture:
    """``camera_profile.native_capture``: request, expected delivery, tracking window, fallback."""

    request_px: tuple[int, int]  # what is asked of the driver (may differ from what it delivers)
    expect_px: tuple[int, int]  # the delivered size this profile was verified with
    crop_px: tuple[int, int, int, int]  # x, y, w, h in the native frame = the tracking field of view
    min_fps: float | None = 25.0  # unique-frame rate the open probe must reach (MANUAL exposure only)
    probe_frames: int = 20
    fallback: str = "STANDARD"  # STANDARD: reopen at resolution_px; FAIL: raise

    @classmethod
    def from_config(cls, block: dict[str, Any]) -> NativeCapture:
        return cls(
            request_px=tuple(block["request_px"]),
            expect_px=tuple(block["expect_px"]),
            crop_px=tuple(block["crop_px"]),
            min_fps=block.get("min_fps", 25.0),
            probe_frames=int(block.get("probe_frames", 20)),
            fallback=block.get("fallback", "STANDARD"),
        )

    def check(self, tracking_px: tuple[int, int]) -> None:
        """Raise ``ValueError`` for a window that cannot reproduce ``tracking_px`` honestly."""
        x, y, w, h = self.crop_px
        ew, eh = self.expect_px
        tw, th = tracking_px
        if self.fallback not in FALLBACKS:
            raise ValueError(f"native_capture.fallback must be one of {FALLBACKS}")
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > ew or y + h > eh:
            raise ValueError(f"crop {self.crop_px} does not fit the expected native frame {self.expect_px}")
        if w < tw or h < th:
            raise ValueError(f"crop {w}x{h} is smaller than the tracking frame {tw}x{th}; "
                             "upscaling is refused")
        if abs(w * th - h * tw) > 0.01 * w * th:
            raise ValueError(f"crop {w}x{h} and tracking frame {tw}x{th} differ in aspect ratio")
        if self.probe_frames < 2:
            raise ValueError("native_capture.probe_frames must be at least 2")

    def to_dict(self) -> dict[str, Any]:
        return {"request_px": list(self.request_px), "expect_px": list(self.expect_px),
                "crop_px": list(self.crop_px), "min_fps": self.min_fps,
                "probe_frames": self.probe_frames, "fallback": self.fallback}


def crop_view(native: np.ndarray, crop_px: tuple[int, int, int, int]) -> np.ndarray:
    """The tracking field of view at native resolution (a view; no pixel is copied or changed)."""
    x, y, w, h = crop_px
    return native[y:y + h, x:x + w]


def tracking_frame(native: np.ndarray, crop_px: tuple[int, int, int, int],
                   tracking_px: tuple[int, int]) -> np.ndarray:
    """Crop, then area-average down to ``tracking_px`` (an independent, contiguous array)."""
    region = crop_view(native, crop_px)
    if region.shape[1] == tracking_px[0] and region.shape[0] == tracking_px[1]:
        return np.ascontiguousarray(region).copy()
    if region.shape[1] < tracking_px[0] or region.shape[0] < tracking_px[1]:
        raise ValueError("tracking frame larger than the native crop; upscaling is refused")
    return cv2.resize(region, tracking_px, interpolation=cv2.INTER_AREA)


__all__ = ["FALLBACKS", "NativeCapture", "NativeModeRejected", "crop_view", "tracking_frame"]
