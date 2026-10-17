"""Preview brightness for the live window only (ADR-0048). Tracking never sees these pixels.

``product.preview`` (or ``app.play --preview``) controls three display-only steps:

* ``dim`` / ``vignette``: the artistic darkening the stage (x0.62 plus a vignette down to x0.28 in
  the corners) and the product kit view (x0.60 + 4) used to apply unconditionally. ``natural`` and
  ``raw`` turn both off; ``legacy`` keeps the previous look.
* ``tone``: ``OFF`` shows the camera pixels; ``GAMMA`` applies a fixed gamma; ``AUTO`` picks a gamma
  each frame so the mean preview luminance approaches ``target_luminance`` (smoothed, never below
  ``min_gamma``, never darker than the camera: gamma <= 1). A gamma curve keeps black at 0 and white
  at 255, so nothing clips that the camera did not clip; it brightens shadows and mid-tones.

A gamma curve redistributes the camera's own levels: it cannot add light, so dark-scene noise
becomes more visible. Brightness that tracking can use only comes from exposure (``--exposure``).
:class:`PreviewTone` returns a new array and never writes into the frame it is given.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any

import cv2
import numpy as np

TONES = ("OFF", "GAMMA", "AUTO")
PRESETS = ("natural", "raw", "legacy")


@dataclass(frozen=True)
class PreviewSettings:
    """``product.preview``. ``dim`` None = each view's legacy darkening (stage 0.62, kit 0.60)."""

    dim: float | None = 1.0
    vignette: bool = False
    tone: str = "AUTO"
    gamma: float = 1.0  # GAMMA only
    target_luminance: float = 115.0  # AUTO: mean grey level the preview approaches
    min_gamma: float = 0.5  # AUTO: strongest brightening allowed
    smoothing: float = 0.15  # AUTO: share of the new estimate per frame (no flicker)

    def __post_init__(self) -> None:
        if self.tone not in TONES:
            raise ValueError(f"preview tone must be one of {TONES}")
        if self.dim is not None and not 0 < self.dim <= 1:
            raise ValueError("preview dim must be in (0, 1]")
        if not 0 < self.gamma <= 3 or not 0 < self.min_gamma <= 1 or not 0 < self.smoothing <= 1:
            raise ValueError("preview gamma, min_gamma and smoothing are out of range")
        if not 0 < self.target_luminance < 255:
            raise ValueError("preview target_luminance must be in (0, 255)")

    @classmethod
    def from_config(cls, block: dict[str, Any] | None) -> PreviewSettings:
        return cls(**(block or {}))

    def preset(self, name: str | None) -> PreviewSettings:
        """``natural`` = this configuration; ``raw`` = camera pixels; ``legacy`` = the previous look."""
        if name in (None, "natural"):
            return self
        if name == "raw":
            return replace(self, dim=1.0, vignette=False, tone="OFF")
        if name == "legacy":
            return replace(self, dim=None, vignette=True, tone="OFF")
        raise ValueError(f"preview preset must be one of {PRESETS}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def gamma_lut(gamma: float) -> np.ndarray:
    return np.clip(np.rint(255.0 * (np.arange(256) / 255.0) ** gamma), 0, 255).astype(np.uint8)


def mean_luminance(img: np.ndarray) -> float:
    """BT.601 luma of a strided sample (about 1/64 of the pixels)."""
    s = img[::8, ::8].reshape(-1, 3).astype(np.float32)
    return float(np.mean(s @ np.array([0.114, 0.587, 0.299], np.float32)))


class PreviewTone:
    def __init__(self, settings: PreviewSettings) -> None:
        self.settings = settings
        self.gamma = settings.gamma if settings.tone == "GAMMA" else 1.0
        self._luts: dict[float, np.ndarray] = {}
        self.history: list[tuple[float, float]] = []  # (camera mean luminance, gamma) per frame

    def target_gamma(self, luminance: float) -> float:
        s = self.settings
        m = min(max(luminance / 255.0, 1e-3), 0.999)
        t = s.target_luminance / 255.0
        return min(1.0, max(s.min_gamma, math.log(t) / math.log(m)))

    def __call__(self, img: np.ndarray) -> np.ndarray:
        s = self.settings
        if s.tone == "OFF":
            return img
        if s.tone == "AUTO":
            lum = mean_luminance(img)
            self.gamma += s.smoothing * (self.target_gamma(lum) - self.gamma)
            self.history.append((lum, self.gamma))
        g = round(self.gamma, 2)
        if g >= 1.0:
            return img
        lut = self._luts.get(g)
        if lut is None:
            lut = self._luts[g] = gamma_lut(g)
        return cv2.LUT(img, lut)

    def report(self) -> dict[str, Any]:
        rep: dict[str, Any] = {"settings": self.settings.to_dict()}
        if self.history:
            lum, gam = np.array(self.history).T
            rep["camera_luminance"] = {"p50": float(np.median(lum)), "min": float(lum.min()),
                                       "max": float(lum.max())}
            rep["gamma"] = {"p50": float(np.median(gam)), "min": float(gam.min()), "max": float(gam.max())}
        return rep


__all__ = ["PRESETS", "TONES", "PreviewSettings", "PreviewTone", "gamma_lut", "mean_luminance"]
