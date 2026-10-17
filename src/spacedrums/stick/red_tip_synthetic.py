"""SYNTHETIC red-tip images for unit tests and offline self-checks (integrity I-4).

**Nothing produced here is a recording or evidence of real-world behaviour.** It renders a glossy red
stick tip roughly as the developer photo describes: saturated red paint, a small bright unsaturated
reflection, optional motion blur (the tip's time-averaged coverage along its exposure path, so a fast
streak loses saturation exactly as a real long exposure does), brightness changes, occluders and red
distractors (speckles, large red surfaces, skin-hue blobs). :func:`draw_stick` adds the wooden shaft and
the paint run down it seen in the owner's photo (2026-10-16); ``REAL_CAP`` is the cap size measured there
at tracking scale.

All coordinates are pixels of the image passed in (camera orientation). Shapes are drawn with 1/16 px
sub-pixel precision so centre errors in tests measure the detector, not the renderer.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from dataclasses import replace

import cv2
import numpy as np

from spacedrums.contracts import FrameView, HandId, ImageRef

SHIFT = 4
SCALE = 1 << SHIFT
BACKGROUND_BGR = (92, 100, 108)
FRAME_SIZE = (640, 480)
# Owner photo at tracking scale: caps ~28 x 37 px. Paint H ~179 / S ~190; a paint run on the shaft H ~5 /
# S ~144 / V ~0.85 of the cap; the wood H ~15 / S ~150.
REAL_CAP = {"length": 34.0, "radius": 13.0}
WOOD_HSV = (15, 150, 170)
RUN_HSV = (5, 144, 175)


def hsv_bgr(h: float, s: float, v: float) -> np.ndarray:
    """One OpenCV-HSV colour (H 0-179) as a float BGR triple."""
    px = np.array([[[h, s, v]]], np.uint8)
    return cv2.cvtColor(px, cv2.COLOR_HSV2BGR)[0, 0].astype(np.float32)


def background(size: tuple[int, int] = FRAME_SIZE, *, rng: np.random.Generator | None = None,
               noise: float = 3.0, bgr: tuple[int, int, int] = BACKGROUND_BGR) -> np.ndarray:
    w, h = size
    img = np.empty((h, w, 3), np.float32)
    img[:] = bgr
    if noise and rng is not None:
        img += rng.normal(0.0, noise, img.shape).astype(np.float32)
    return np.clip(img, 0, 255).astype(np.uint8)


def _ellipse(layer: np.ndarray, center, axes, angle_deg: float, value: float = 1.0) -> None:
    c = (int(round(center[0] * SCALE)), int(round(center[1] * SCALE)))
    a = (max(1, int(round(axes[0] * SCALE))), max(1, int(round(axes[1] * SCALE))))
    cv2.ellipse(layer, c, a, angle_deg, 0, 360, value, -1, cv2.LINE_AA, SHIFT)


def draw_tip(img: np.ndarray, center: tuple[float, float], *, length: float = 16.0, radius: float = 6.0,
             angle_deg: float = -70.0, hue: float = 177, sat: float = 215, val: float = 205,
             brightness: float = 1.0, highlight: float = 0.35,
             highlight_offset: tuple[float, float] = (0.0, 0.0),
             blur_from: tuple[float, float] | None = None) -> None:
    """Draw one glossy tip in place. ``blur_from``: start of the exposure path (the tip moves to ``center``).

    ``highlight`` is the reflection radius as a fraction of ``radius`` (0 = matte paint).
    """
    end = np.asarray(center, float)
    start = end if blur_from is None else np.asarray(blur_from, float)
    steps = max(1, int(math.ceil(float(np.linalg.norm(end - start)) / 1.0)) + 1)
    reach = max(length / 2, radius) + 3
    lo = np.floor(np.minimum(start, end) - reach).astype(int)
    hi = np.ceil(np.maximum(start, end) + reach).astype(int) + 1
    h, w = img.shape[:2]
    x0, y0 = max(0, lo[0]), max(0, lo[1])
    x1, y1 = min(w, hi[0]), min(h, hi[1])
    if x1 <= x0 or y1 <= y0:
        return
    cover = np.zeros((y1 - y0, x1 - x0), np.float32)
    shine = np.zeros_like(cover)
    for k in range(steps):
        u = k / (steps - 1) if steps > 1 else 1.0
        p = start + (end - start) * u - (x0, y0)
        layer = np.zeros_like(cover)
        _ellipse(layer, p, (length / 2, radius), angle_deg)
        cover += layer
        if highlight > 0:
            spot = np.zeros_like(cover)
            _ellipse(spot, p + highlight_offset, (radius * highlight, radius * highlight), 0.0)
            shine += np.minimum(spot, layer)
    cover /= steps
    shine /= steps
    paint = hsv_bgr(hue, sat, min(255.0, val * brightness))
    gloss = hsv_bgr(hue, 25, min(255.0, 250 * min(1.0, brightness * 1.1)))
    patch = img[y0:y1, x0:x1].astype(np.float32)
    body = (cover - shine)[..., None]
    out = patch * (1 - cover[..., None]) + paint * body + gloss * shine[..., None]
    img[y0:y1, x0:x1] = np.clip(out, 0, 255).astype(np.uint8)


def draw_stick(img: np.ndarray, center: tuple[float, float], *, angle_deg: float = -80.0,
               length: float = REAL_CAP["length"], radius: float = REAL_CAP["radius"], shaft_px: float = 0.0,
               run_px: float = 0.0, run_hsv: tuple[float, float, float] = RUN_HSV,
               run_jitter: tuple[float, float] = (3.0, 25.0), wood_hsv: tuple[float, float, float] = WOOD_HSV,
               seed: int = 0, **tip_kw) -> tuple[float, float]:
    """A painted cap at ``center`` on a wooden shaft that runs away from it, optionally with paint run
    ``run_px`` down the shaft below the cap. The run is mottled like the photo's: hue / saturation noise of
    ``run_jitter`` standard deviations in ~2 px patches, so parts of it have paint-core colour. Returns the
    shaft's unit direction (pointing down the image)."""
    a = math.radians(angle_deg)
    u = np.array([math.cos(a), math.sin(a)])
    if u[1] < 0 or (u[1] == 0 and u[0] < 0):
        u = -u
    c = np.asarray(center, float)
    neck = c + u * (length / 2 - radius * 0.3)
    width = radius * 0.85
    if shaft_px > 0:
        _band(img, neck, neck + u * (shaft_px + run_px), width, wood_hsv)
    if run_px > 0:
        _band(img, neck, neck + u * run_px, width * 0.95, run_hsv, jitter=run_jitter,
              rng=np.random.default_rng(seed))
    draw_tip(img, center, length=length, radius=radius, angle_deg=angle_deg, **tip_kw)
    return float(u[0]), float(u[1])


def _patches(rng: np.random.Generator, shape, sigma: float = 2.0) -> np.ndarray:
    """Unit-variance noise correlated over ~``sigma`` px: paint mottles in patches, not single pixels."""
    noise = cv2.GaussianBlur(rng.normal(0.0, 1.0, shape).astype(np.float32), (0, 0), sigma)
    return noise / max(1e-6, float(noise.std()))


def _band(img: np.ndarray, p0, p1, half_width: float, hsv: tuple[float, float, float], *,
          jitter: tuple[float, float] = (0.0, 0.0), rng: np.random.Generator | None = None) -> None:
    layer = np.zeros(img.shape[:2], np.float32)
    d = np.asarray(p1, float) - np.asarray(p0, float)
    n = np.array([-d[1], d[0]]) / max(1e-6, float(np.linalg.norm(d))) * half_width
    poly = np.array([p0 + n, p1 + n, p1 - n, p0 - n]) * SCALE
    cv2.fillConvexPoly(layer, np.round(poly).astype(np.int32), 1.0, cv2.LINE_AA, SHIFT)
    if rng is not None and any(jitter):
        field = np.empty(img.shape, np.float32)
        field[..., 0] = (hsv[0] + jitter[0] * _patches(rng, img.shape[:2])) % 180
        field[..., 1] = np.clip(hsv[1] + jitter[1] * _patches(rng, img.shape[:2]), 0, 255)
        field[..., 2] = hsv[2]
        colour = cv2.cvtColor(np.round(field).astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
    else:
        colour = hsv_bgr(*hsv)
    out = img.astype(np.float32) * (1 - layer[..., None]) + colour * layer[..., None]
    img[:] = np.clip(out, 0, 255).astype(np.uint8)


def draw_blob(img: np.ndarray, center: tuple[float, float], radius: float, *, hue: float, sat: float,
              val: float, axes: tuple[float, float] | None = None, angle_deg: float = 0.0) -> None:
    """A flat-coloured distractor (skin tone, a red object, ...)."""
    layer = np.zeros(img.shape[:2], np.float32)
    _ellipse(layer, center, axes or (radius, radius), angle_deg)
    colour = hsv_bgr(hue, sat, val)
    out = img.astype(np.float32) * (1 - layer[..., None]) + colour * layer[..., None]
    img[:] = np.clip(out, 0, 255).astype(np.uint8)


def speckles(img: np.ndarray, rng: np.random.Generator, n: int, *, hue: float = 178, sat: float = 220,
             val: float = 200) -> None:
    """Isolated red pixels (sensor noise, tiny reflections)."""
    h, w = img.shape[:2]
    colour = hsv_bgr(hue, sat, val).astype(np.uint8)
    ys, xs = rng.integers(0, h, n), rng.integers(0, w, n)
    img[ys, xs] = colour


def occlude(img: np.ndarray, rect: tuple[int, int, int, int],
            bgr: tuple[int, int, int] = (70, 80, 95)) -> None:
    x, y, w, h = rect
    img[max(0, y):y + h, max(0, x):x + w] = bgr


def tip_frames(sequence, *, size: tuple[int, int] = FRAME_SIZE, exposure_fraction: float = 0.5,
               hidden: dict[HandId, set[int]] | None = None, seed: int = 0, noise: float = 3.0,
               decorate=None, tip_kw: dict | None = None) -> Iterator[tuple[FrameView, dict]]:
    """Render ``app.synthetic.build_sequence`` tips as red tips on full-frame (ROI = frame) images.

    Yields ``(FrameView, truth)`` where ``truth`` maps each hand to its rendered tip (pixels) or ``None``.
    ``exposure_fraction`` of the motion since the previous frame is integrated as blur. ``hidden``
    frames omit a tip (occlusion). ``decorate(img, k)`` may add distractors to frame ``k``.
    """
    rng = np.random.default_rng(seed)
    hidden = hidden or {}
    w, h = size
    previous: dict[HandId, np.ndarray] = {}
    for k, (sample, observations) in enumerate(sequence.frames if hasattr(sequence, "frames") else sequence):
        img = background(size, rng=rng, noise=noise)
        if decorate is not None:
            decorate(img, k)
        truth: dict[HandId, tuple[float, float] | None] = {}
        for hand, (_, stick) in observations.items():
            if not stick.present or k in hidden.get(hand, set()):
                truth[hand] = None
                previous.pop(hand, None)
                continue
            p = np.array(stick.tip, float) * (w, h)
            prev = previous.get(hand)
            start = None if prev is None else p + (prev - p) * exposure_fraction
            draw_tip(img, tuple(p), blur_from=None if start is None else tuple(start), **(tip_kw or {}))
            truth[hand] = (float(p[0]), float(p[1]))
            previous[hand] = p
        sample = replace(sample, roi_px=(0, 0, w, h), frame_size_px=(w, h), image_ref=ImageRef.memory(img))
        yield FrameView(sample, img, img), truth


def path_frames(paths: dict[str, Iterable], *, size: tuple[int, int] = FRAME_SIZE, t0: float = 100.0,
                dt: float = 1 / 30, exposure_fraction: float = 0.5, seed: int = 0, noise: float = 3.0,
                decorate=None, tip_kw: dict | None = None) -> list[tuple[FrameView, dict]]:
    """Frames from explicit per-tip pixel paths (``None`` entries = tip hidden); for tracker tests."""
    from spacedrums.contracts import FrameSample, TimestampSource

    rng = np.random.default_rng(seed)
    series = {name: list(points) for name, points in paths.items()}
    n = max(len(v) for v in series.values())
    previous: dict[str, np.ndarray] = {}
    frames = []
    for k in range(n):
        img = background(size, rng=rng, noise=noise)
        if decorate is not None:
            decorate(img, k)
        truth = {}
        for name, points in series.items():
            p = points[k] if k < len(points) else None
            if p is None:
                truth[name] = None
                previous.pop(name, None)
                continue
            p = np.asarray(p, float)
            prev = previous.get(name)
            start = None if prev is None else p + (prev - p) * exposure_fraction
            draw_tip(img, tuple(p), blur_from=None if start is None else tuple(start), **(tip_kw or {}))
            truth[name] = (float(p[0]), float(p[1]))
            previous[name] = p
        t = t0 + k * dt
        sample = FrameSample(frame_id=k, t_capture=t, t_frame_available=t + 0.004,
                             timestamp_source=TimestampSource.REPLAY, frame_size_px=size,
                             roi_px=(0, 0, size[0], size[1]), image_ref=ImageRef.memory(img),
                             camera_profile_id="synthetic-camera", dropped_since_last=0)
        frames.append((FrameView(sample, img, img), truth))
    return frames


__all__ = ["BACKGROUND_BGR", "REAL_CAP", "background", "draw_blob", "draw_stick", "draw_tip", "hsv_bgr",
           "occlude", "path_frames", "speckles", "tip_frames"]
