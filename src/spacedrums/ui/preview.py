"""Presentation boundary for live camera windows.

Live renderers (``mirror=True``) mirror only the camera image here, then draw every overlay on that
copy through a mirrored :class:`~spacedrums.ui.canvas.Canvas`, so shapes follow the image and text
stays readable. Never send the display image back to capture, perception, calibration or a recorder.
Offline renderers and replay/annotation windows retain camera coordinates.
"""

from __future__ import annotations

import cv2
import numpy as np


def mirror_preview(camera_frame: np.ndarray) -> np.ndarray:
    """Return an independent, horizontally mirrored copy of a camera image.

    The input can be a frame or an ROI view sharing capture memory. The returned
    array always owns separate storage, so subsequent display drawing cannot
    alter the source pixels. No coordinates or records enter this boundary.
    ``cv2.flip`` gives the same pixels as ``[:, ::-1].copy()`` at about a quarter
    of the cost on HW-01 (T2 display-path measurement, 2026-09-28).
    """
    return cv2.flip(camera_frame, 1)


__all__ = ["mirror_preview"]
