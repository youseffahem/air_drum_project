"""Anti-aliased UI text and icons for the AR HUD (Pillow + Windows Segoe fonts), cached as alpha sprites.

OpenCV's Hershey fonts cannot match the reference typography, and this OpenCV build has no FreeType.
Pillow renders each (text, size, weight) once into an alpha mask; drawing is an alpha blend of a small box.
Without Pillow or the fonts the cache falls back to Hershey masks, so the HUD still works everywhere.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

FONTS = Path("C:/Windows/Fonts")
FACES = {
    "regular": "segoeui.ttf",
    "semibold": "seguisb.ttf",
    "bold": "segoeuib.ttf",
    "icons": "SegoeIcons.ttf",
}
FALLBACK_ICONS = {"icons": "segmdl2.ttf"}
# Segoe Fluent / MDL2 icon code points.
ICONS = {"settings": "\ue713", "camera": "\ue722", "volume": "\ue995", "chevron": "\ue70d", "sync": "\ue895"}


class TextCache:
    def __init__(self, capacity: int = 768, font_dir: Path = FONTS):
        self.capacity = capacity
        self.sprites: OrderedDict = OrderedDict()
        self.fonts = {}
        self.pillow = self._load(font_dir)

    def _load(self, font_dir: Path) -> bool:
        try:
            from PIL import ImageFont  # noqa: F401
        except ImportError:
            return False
        for face, name in FACES.items():
            path = font_dir / name
            if not path.exists() and face in FALLBACK_ICONS:
                path = font_dir / FALLBACK_ICONS[face]
            if path.exists():
                self.fonts[face] = path
        return "regular" in self.fonts

    def mask(self, text: str, size: int, weight: str = "regular") -> np.ndarray:
        """float32 alpha mask (h, w) of ``text`` at ``size`` px; the box is the font's line box."""
        key = (text, int(size), weight)
        got = self.sprites.get(key)
        if got is not None:
            self.sprites.move_to_end(key)
            return got
        m = self._render(text, int(size), weight)
        self.sprites[key] = m
        if len(self.sprites) > self.capacity:
            self.sprites.popitem(last=False)
        return m

    def _render(self, text, size, weight):
        path = self.fonts.get(weight) or self.fonts.get("regular")
        if self.pillow and path is not None:
            from PIL import Image, ImageDraw, ImageFont

            font = ImageFont.truetype(str(path), size)
            ascent, descent = font.getmetrics()
            width = max(1, int(np.ceil(font.getlength(text))) + 2)
            img = Image.new("L", (width, ascent + descent))
            ImageDraw.Draw(img).text((1, 0), text, font=font, fill=255)
            return np.asarray(img, np.float32) / 255
        scale = size / 30
        (w, h), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        m = np.zeros((h + base + 4, w + 2), np.uint8)
        thick = 2 if weight in ("semibold", "bold") else 1
        cv2.putText(m, text, (1, h + 2), cv2.FONT_HERSHEY_SIMPLEX, scale, 255, thick, cv2.LINE_AA)
        return m.astype(np.float32) / 255

    def size(self, text, size, weight="regular") -> tuple[int, int]:
        m = self.mask(text, size, weight)
        return m.shape[1], m.shape[0]

    def sprite(self, text, size, weight, color):
        key = ("sprite", text, int(size), weight, tuple(int(c) for c in color))
        got = self.sprites.get(key)
        if got is None:
            got = make_sprite(color, self.mask(text, size, weight))
            self.sprites[key] = got
            if len(self.sprites) > self.capacity:
                self.sprites.popitem(last=False)
        else:
            self.sprites.move_to_end(key)
        return got

    def draw(self, img, text, org, size, color, weight="regular", *, anchor="lt"):
        """Blend ``text`` onto ``img``. ``anchor``: l/c/r horizontally, t/m/b vertically (line box)."""
        if not text:
            return 0, 0
        sprite = self.sprite(text, size, weight, color)
        h, w = sprite[0].shape[:2]
        x, y = org
        x -= {"l": 0, "c": w // 2, "r": w}[anchor[0]]
        y -= {"t": 0, "m": h // 2, "b": h}[anchor[1]]
        blit(img, sprite, round(x), round(y))
        return w, h

    def icon(self, img, name, center, size, color):
        if "icons" not in self.fonts or not self.pillow:
            cv2.circle(img, tuple(map(int, center)), max(2, size // 3), color, 1, cv2.LINE_AA)
            return
        self.draw(img, ICONS[name], center, size, color, "icons", anchor="cm")


def make_sprite(bgr, alpha):
    """A blit-ready sprite: (premultiplied BGR uint8, inverse alpha uint8 x3) from colour and alpha 0-1."""
    alpha = np.asarray(alpha, np.float32)
    bgr = np.broadcast_to(np.asarray(bgr, np.float32), alpha.shape + (3,))
    pre = np.clip(bgr * alpha[..., None] + 0.5, 0, 255).astype(np.uint8)
    inv = np.clip((1 - alpha) * 255 + 0.5, 0, 255).astype(np.uint8)
    return pre, cv2.merge((inv, inv, inv))


def blit(img, sprite, x, y):
    """img = img * (1 - alpha) + premultiplied colour, clipped to the image (uint8 SIMD ops)."""
    pre, inv = sprite
    h, w = pre.shape[:2]
    x, y = int(x), int(y)
    x0, y0, x1, y1 = max(0, x), max(0, y), min(img.shape[1], x + w), min(img.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sy, sx = slice(y0 - y, y1 - y), slice(x0 - x, x1 - x)
    patch = img[y0:y1, x0:x1]
    patch[:] = cv2.add(cv2.multiply(patch, inv[sy, sx], scale=1 / 255), pre[sy, sx])


__all__ = ["ICONS", "TextCache", "blit", "make_sprite"]
