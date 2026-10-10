"""Animated stage view for the full-kit demo.

Display only: the camera frame is mirrored once (``cv2.flip``), dimmed and upscaled, then every
overlay is drawn straight in display pixels. Zone and fingertip coordinates stay in camera ROI
space everywhere else; ``StageRenderer.to_display`` is the single place that maps them. No event is
generated here, and animations are driven only by the frame capture clock and the committed strikes
of the shared pipeline.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from spacedrums.contracts import HandId
from spacedrums.geometry.kit_layout import CYMBALS
from spacedrums.ui.kit import pad_texture
from spacedrums.ui.theme import DEFAULT_THEME

SCALE = 1.5
AA = cv2.LINE_AA
FONT = cv2.FONT_HERSHEY_DUPLEX
BAR = (20, 23, 31)
TEXT = (240, 242, 246)
MUTED = (165, 172, 186)
DIM = 0.62
TRAIL_GAP_S = 0.115
FLASH_S, RIPPLE_S, PARTICLE_S, POP_S, COMBO_GAP_S = 0.30, 0.45, 0.35, 0.12, 0.6
# BGR accents per drum; anything else falls back to steel.
ACCENTS = {
    "crash": (60, 190, 255),
    "ride": (140, 230, 120),
    "hihat": (80, 235, 255),
    "snare": (90, 90, 255),
    "tom1": (255, 150, 60),
    "tom2": (225, 205, 70),
    "floor_tom": (210, 110, 255),
    "crash_ride": (60, 190, 255),
}
STEEL = (200, 200, 205)
WOBBLE_S = {"crash": 0.40, "crash_ride": 0.40, "ride": 0.28, "hihat": 0.18}


def _scaled(color, k):
    return tuple(int(c * k) for c in color)


def _rounded(img, x0, y0, x1, y1, r, color):
    cv2.rectangle(img, (x0 + r, y0), (x1 - r, y1), color, -1)
    cv2.rectangle(img, (x0, y0 + r), (x1, y1 - r), color, -1)
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        cv2.circle(img, (cx, cy), r, color, -1, AA)


@dataclass
class Pad:
    zone_id: str
    name: str
    x: int
    y: int
    w: int
    h: int
    edge: tuple[tuple[int, int], tuple[int, int]]
    accent: tuple[int, int, int]
    cymbal: bool
    last_hit: float = -1e9
    strength: float = 0.0
    sprite: np.ndarray | None = None
    mask: np.ndarray | None = None

    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2


# BGR head tint multipliers: the snare keeps the coated white head, toms get darker clear heads.
HEAD_TINT = {"tom1": (1.0, 0.82, 0.62), "tom2": (1.0, 0.82, 0.62), "floor_tom": (0.95, 0.72, 0.52)}


def _decorate(body, mask, pad, c):
    """Per-piece detail drawn inside the rounded footprint; nothing here moves the footprint."""
    w, h = pad.w, pad.h
    zid = pad.zone_id
    if pad.cymbal:
        for k in (0.86, 0.68, 0.50) if zid != "hihat" else (0.80, 0.55):
            cv2.ellipse(body, c, (int(w / 2 * k), int(h / 2 * k)), 0, 0, 360, (70, 110, 140), 1, AA)
        bell = 0.16 if zid == "ride" else 0.11
        cv2.ellipse(body, c, (max(3, int(w * bell)), max(2, int(h * bell * 1.6))), 0, 0, 360, (95, 150, 190),
            -1, AA)
        cv2.ellipse(body, c, (max(3, int(w * bell)), max(2, int(h * bell * 1.6))), 0, 0, 360, (60, 95, 125),
            1, AA)
        if zid == "hihat":  # the bottom plate peeks out under the top one
            cv2.ellipse(body, (c[0], c[1] + max(2, h // 8)), (int(w * 0.46), int(h * 0.40)), 0, 20, 160,
                        (60, 95, 125), 2, AA)
        return
    cv2.ellipse(body, c, (int(w * 0.40), int(h * 0.34)), 0, 0, 360, (150, 150, 158), 1, AA)
    if zid == "snare":  # snare wires across the lower half of the head
        for k in (0.06, 0.16, 0.26):
            y = c[1] + int(h * k)
            cv2.line(body, (c[0] - int(w * 0.36), y), (c[0] + int(w * 0.36), y), (170, 170, 176), 1, AA)
    else:  # a visible shell band along the lower edge reads as a deeper drum
        cv2.line(body, (4, h - 5), (w - 5, h - 5), (90, 90, 100), 2, AA)
    for dx in (-int(w * 0.43), int(w * 0.43)):
        cv2.circle(body, (c[0] + dx, c[1]), 2, (235, 235, 240), -1, AA)


def build_sprite(pad: Pad):
    """Pad body with rim, decoration and its label baked in; the mask is the rounded footprint."""
    w, h = pad.w, pad.h
    body = pad_texture(w, h, pad.cymbal).copy()
    tint = HEAD_TINT.get(pad.zone_id)
    if tint is not None:
        body = np.clip(body.astype(np.float32) * tint, 0, 255).astype(np.uint8)
    mask = np.zeros((h, w), np.uint8)
    r = max(3, int(min(w, h) * 0.16))
    _rounded(mask, 0, 0, w - 1, h - 1, r, 255)
    inner = np.zeros_like(mask)
    _rounded(inner, 3, 3, w - 4, h - 4, max(2, r - 3), 255)
    body[(mask > 0) & (inner == 0)] = pad.accent
    c = (w // 2, h // 2)
    _decorate(body, mask, pad, c)
    cv2.line(body, (r, 1), (w - r - 1, 1), _scaled(pad.accent, 1.0), 2, AA)  # the strike edge
    label = pad.name.upper()
    scale = min(0.5, (w - 16) / max(1, cv2.getTextSize(label, FONT, 1.0, 1)[0][0]))
    tw, th = cv2.getTextSize(label, FONT, scale, 1)[0]
    cv2.putText(body, label, (c[0] - tw // 2, c[1] + th // 2), FONT, scale, (38, 40, 48), 1, AA)
    pad.sprite, pad.mask = body, (mask > 0)[..., None]


def blit(img, sprite, mask, x, y):
    h, w = mask.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(img.shape[1], x + w), min(img.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    np.copyto(img[y0:y1, x0:x1], sprite[y0 - y : y1 - y, x0 - x : x1 - x],
              where=mask[y0 - y : y1 - y, x0 - x : x1 - x])


class StageRenderer:
    def __init__(self, scale: float = SCALE):
        self.scale = scale
        self.pads: dict[str, Pad] = {}
        self._key = None
        self._vignette = {}
        self.trails = {h: deque(maxlen=12) for h in HandId}
        self.particles: list[tuple[float, float, float, float, float, tuple[int, int, int]]] = []
        self.rng = np.random.default_rng(0)
        self.times = deque(maxlen=60)
        self.total = 0
        self.combo = 0
        self.last_name = None
        self.last_color = TEXT
        self.last_t = -1e9

    # -- geometry ------------------------------------------------------------------------------
    def to_display(self, p, roi, frame_w):
        """ROI-normalised camera point -> pixel in the mirrored, upscaled display."""
        return (
            (frame_w - 1 - (roi.x + p[0] * roi.w)) * self.scale,
            (roi.y + p[1] * roi.h) * self.scale,
        )

    def _layout(self, registry, roi, frame_w):
        key = (id(registry), roi.as_tuple(), frame_w)
        if key == self._key:
            return
        self._key = key
        self.pads = {}
        for zone in registry:
            pts = np.array([self.to_display(p, roi, frame_w) for p in zone.shape.points])
            x0, y0 = np.floor(pts.min(axis=0)).astype(int)
            x1, y1 = np.ceil(pts.max(axis=0)).astype(int)
            a, b = (tuple(round(v) for v in self.to_display(q, roi, frame_w))
                    for q in (zone.impact_surface.p0, zone.impact_surface.p1))
            pad = Pad(zone.zone_id, zone.name, int(x0), int(y0), int(x1 - x0), int(y1 - y0), (a, b),
                      ACCENTS.get(zone.zone_id, STEEL), zone.zone_id in CYMBALS)
            build_sprite(pad)
            self.pads[zone.zone_id] = pad

    def _vignette_for(self, shape):
        if shape not in self._vignette:
            h, w = shape[:2]
            yy, xx = np.mgrid[0:h, 0:w]
            d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
            v = np.clip(1.15 - 0.45 * d**2, 0.45, 1.0) * DIM
            self._vignette[shape] = np.repeat((v * 255).astype(np.uint8)[..., None], 3, axis=2)
        return self._vignette[shape]

    # -- drawing -------------------------------------------------------------------------------
    @staticmethod
    def _panel(img, x0, y0, x1, y1, alpha=0.6):
        patch = img[y0:y1, x0:x1]
        cv2.addWeighted(patch, 1 - alpha, np.full_like(patch, BAR), alpha, 0, dst=patch)

    @staticmethod
    def _text(img, text, org, scale, color=TEXT, thickness=1):
        cv2.putText(img, text, (org[0] + 1, org[1] + 1), FONT, scale, (8, 9, 12), thickness + 1, AA)
        cv2.putText(img, text, org, FONT, scale, color, thickness, AA)

    def _pill(self, img, right, y, text, color):
        """Right-aligned status pill; returns its left edge."""
        tw = cv2.getTextSize(text, FONT, 0.46, 1)[0][0]
        x0 = right - tw - 34
        _rounded(img, x0, y - 13, right, y + 13, 13, (52, 57, 70))
        cv2.circle(img, (x0 + 14, y), 5, color, -1, AA)
        self._text(img, text, (x0 + 26, y + 5), 0.46)
        return x0 - 10

    def _hits(self, result, registry, evidence, roi, frame_w, t):
        for commit in result.commits:
            pad = self.pads.get(commit.zone_id)
            if pad is None:
                continue
            strength = float(np.clip(getattr(commit, "gain", 1.0), 0.35, 1.0))
            self.combo = self.combo + 1 if t - self.last_t < COMBO_GAP_S else 1
            self.total += 1
            pad.last_hit, pad.strength = t, strength
            self.last_name, self.last_color, self.last_t = pad.name, pad.accent, t
            e = evidence.get(commit.hand_id)
            if e is not None and e.kind == "MEASURED":
                ox, oy = self.to_display(e.tip, roi, frame_w)
            else:
                ox, oy = (pad.edge[0][0] + pad.edge[1][0]) / 2, pad.edge[0][1]
            for _ in range(10):
                angle = self.rng.uniform(math.radians(200), math.radians(340))
                speed = self.rng.uniform(120, 340) * (0.6 + 0.4 * strength)
                vx, vy = math.cos(angle) * speed, math.sin(angle) * speed
                self.particles.append((ox, oy, vx, vy, t, pad.accent))
        self.particles = [p for p in self.particles if t - p[4] < PARTICLE_S][-80:]

    def _draw_pads(self, img, t):
        for pad in self.pads.values():
            age = t - pad.last_hit
            sprite, mask, x, y = pad.sprite, pad.mask, pad.x, pad.y
            if age < FLASH_S:
                k = pad.strength * math.exp(-age / 0.07)
                sprite = cv2.add(sprite, (*_scaled(pad.accent, 0.8 * k), 0))
                if pad.cymbal:
                    tau = WOBBLE_S.get(pad.zone_id, 0.25)
                    angle = 7 * pad.strength * math.exp(-age / tau) * math.sin(age * 2 * math.pi * 8)
                    m = cv2.getRotationMatrix2D((pad.w / 2, pad.h / 2), angle, 1.0)
                    sprite = cv2.warpAffine(sprite, m, (pad.w, pad.h))
                    mask = cv2.warpAffine(mask.astype(np.uint8), m, (pad.w, pad.h)).astype(bool)[..., None]
                else:
                    y += round(7 * pad.strength * math.exp(-age / 0.09) * math.cos(age * 45))
            blit(img, sprite, mask, x, y)

    def _draw_effects(self, fx, evidence, roi, frame_w, t):
        drawn = False
        for pad in self.pads.values():
            age = t - pad.last_hit
            for delay in (0.0, 0.12):
                a = age - delay
                if 0 <= a < RIPPLE_S:
                    e = 1 - (1 - a / RIPPLE_S) ** 2
                    glow = (1 - a / RIPPLE_S) ** 1.5 * pad.strength
                    cv2.ellipse(fx, pad.center, (int(pad.w / 2 + 60 * e), int(pad.h / 2 + 30 * e)),
                                0, 0, 360, _scaled(pad.accent, glow), 2, AA)
                    drawn = True
        for hand, e in evidence.items():
            trail = self.trails[hand]
            color = DEFAULT_THEME.left if hand is HandId.LEFT else DEFAULT_THEME.right
            if e.kind != "MEASURED":
                trail.clear()
                continue
            point = self.to_display(e.tip, roi, frame_w)
            if trail and t - trail[-1][0] > TRAIL_GAP_S:
                trail.clear()
            trail.append((t, point))
            pts = [p for _, p in trail]
            for i in range(1, len(pts)):
                k = i / len(pts)
                cv2.line(fx, tuple(map(round, pts[i - 1])), tuple(map(round, pts[i])),
                         _scaled(color, 0.9 * k), 2 + round(3 * k), AA)
            tip = tuple(map(round, point))
            cv2.circle(fx, tip, 14, _scaled(color, 0.5), -1, AA)
            cv2.circle(fx, tip, 8, _scaled(color, 0.9), -1, AA)
            drawn = True
            for pad in self.pads.values():
                (ex0, ey), (ex1, _) = pad.edge
                gap = ey - tip[1]
                if min(ex0, ex1) - 10 <= tip[0] <= max(ex0, ex1) + 10 and 0 < gap < 0.10 * roi.h * self.scale:
                    k = 1 - gap / (0.10 * roi.h * self.scale)
                    cv2.line(fx, pad.edge[0], pad.edge[1], _scaled(pad.accent, 0.4 + 0.6 * k), 4, AA)
        for x, y, vx, vy, t0, color in self.particles:
            a = t - t0
            if a < 0:
                continue
            life = 1 - a / PARTICLE_S
            cv2.circle(fx, (round(x + vx * a), round(y + vy * a + 450 * a * a)), max(1, round(3 * life)),
                       _scaled(color, life), -1, AA)
            drawn = True
        return drawn

    def _hud(self, img, evidence, audio, latency_ms, fps, t):
        h, w = img.shape[:2]
        self._panel(img, 0, 0, w, 56)
        self._panel(img, 0, h - 28, w, h, 0.5)
        self._text(img, "SPACE DRUMS", (18, 36), 0.75)
        self._text(img, "FULL KIT", (186, 36), 0.45, MUTED)
        # last hit, popping in
        if self.last_name is not None:
            age = t - self.last_t
            scale = 0.8 + 0.45 * math.exp(-age / POP_S)
            color = self.last_color if age < 1.5 else MUTED
            tw = cv2.getTextSize(self.last_name.upper(), FONT, scale, 2)[0][0]
            self._text(img, self.last_name.upper(), ((w - tw) // 2, 38), scale, color, 2)
            if self.combo >= 3 and age < 1.0:
                text = f"x{self.combo} COMBO"
                k = 1 + 0.35 * math.exp(-age / POP_S)
                cw = cv2.getTextSize(text, FONT, 0.7 * k, 2)[0][0]
                self._text(img, text, ((w - cw) // 2, 92), 0.7 * k, (90, 215, 255), 2)
        # status cluster, right aligned
        state = getattr(audio, "device_state", "NOT_STARTED") if audio is not None else "NOT_STARTED"
        device = getattr(audio, "device", None)
        api = getattr(device, "opened_host_api", None)
        stream_ms = getattr(device, "opened_latency_s", None)
        if state == "RUNNING":
            label = (api or "AUDIO").replace("Windows ", "").replace(" (shared)", "")
            label = label.replace(" (exclusive)", " EXCL").upper()
            label += f" {stream_ms * 1000:.0f}ms" if stream_ms else ""
            color = DEFAULT_THEME.ok
        else:
            idle = state in ("DISABLED", "NOT_STARTED")
            label = {"DISABLED": "AUDIO OFF", "NOT_STARTED": "AUDIO WAIT"}.get(state, f"AUDIO {state}")
            color = DEFAULT_THEME.warning if idle else DEFAULT_THEME.error
        x = self._pill(img, w - 14, 28, label, color)
        if latency_ms is not None:
            x = self._pill(img, x, 28, f"LAG {latency_ms + (stream_ms or 0) * 1000:.0f}ms", (200, 170, 90))
        for i, hand in enumerate(HandId):
            ok = evidence[hand].kind == "MEASURED"
            base = DEFAULT_THEME.left if hand is HandId.LEFT else DEFAULT_THEME.right
            cv2.circle(img, (292 + 24 * i, 30), 8, base if ok else (70, 74, 86), -1 if ok else 2, AA)
        self._text(img, f"{fps:.0f} FPS   D diagnostics   Esc quit", (14, h - 9), 0.4, MUTED)
        count = f"HITS {self.total}"
        self._text(img, count, (w - 14 - cv2.getTextSize(count, FONT, 0.4, 1)[0][0], h - 9), 0.4, MUTED)

    def render(self, full, roi, registry, evidence, result, *, audio=None, latency_ms=None):
        t = result.sample.t_capture
        self.times.append(t)
        span = t - self.times[0]
        fps = (len(self.times) - 1) / span if span > 0 else 0.0
        frame_w = full.shape[1]
        small = cv2.flip(full, 1)
        cv2.multiply(small, self._vignette_for(small.shape), dst=small, scale=1 / 255)  # dim + vignette
        size = (round(small.shape[1] * self.scale), round(small.shape[0] * self.scale))
        img = cv2.resize(small, size, interpolation=cv2.INTER_LINEAR)
        self._layout(registry, roi, frame_w)
        self._hits(result, registry, evidence, roi, frame_w, t)
        self._draw_pads(img, t)
        fx = np.zeros_like(img)
        if self._draw_effects(fx, evidence, roi, frame_w, t):
            cv2.add(img, fx, dst=img)  # additive: faded colours glow and vanish without alpha math
        for trail in self.trails.values():
            if trail and trail[-1][0] == t:  # bright core over the glow
                cv2.circle(img, tuple(map(round, trail[-1][1])), 4, (255, 255, 255), -1, AA)
        self._hud(img, evidence, audio, latency_ms, fps, t)
        return img


__all__ = ["StageRenderer", "build_sprite"]
