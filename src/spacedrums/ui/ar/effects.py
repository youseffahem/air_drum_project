"""Hit feedback and stick glow for the AR view, driven only by committed strikes and endpoint evidence.

Nothing here generates or filters events: every flash, ripple, wobble and spark starts from a
``CommittedStrike`` of the shared pipeline, and every tip marker or trail from current ``EndpointEvidence``.
Animation time is the frame's capture clock. Screen-space glow is returned as pixel-space triangles
(x, y, b, g, r, a, emit) for the renderer's additive overlay pass.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from spacedrums.contracts import HandId
from spacedrums.ui.ar.gl import PieceDraw
from spacedrums.ui.ar.palette import LEFT, RIGHT, WARN
from spacedrums.ui.ar.scene import rot_axis

TRAIL_GAP_S = 0.115  # the developer views' rule: a gap this long breaks the trail
COMET_S = 0.25
REST_NEON = 0.6
NEON_TAU, HIT_LIFE_S = 0.12, 1.0
WOBBLE_TAU = {"cymbal": 0.45, "hihat": 0.18}
GRAVITY = 1100.0  # px/s^2 at 720 px height
LEVELS = {"full": 1.0, "low": 0.4, "off": 0.0}
WHITE = (255, 255, 255)


@dataclass
class Hit:
    t: float
    strength: float
    local: np.ndarray  # head-plane impact point (local units)
    axis: np.ndarray  # cymbal wobble axis (local)


def hand_color(hand) -> tuple[int, int, int]:
    return LEFT if hand is HandId.LEFT else RIGHT


def _disc(cx, cy, r, color, alpha, emit, n=24):
    a = np.linspace(0, 2 * math.pi, n + 1)
    x, y = cx + r * np.cos(a), cy + r * np.sin(a)
    tris = np.empty((n, 3, 7), np.float32)
    tris[:, 0, :2] = cx, cy
    tris[:, 1, 0], tris[:, 1, 1] = x[:-1], y[:-1]
    tris[:, 2, 0], tris[:, 2, 1] = x[1:], y[1:]
    tris[..., 2:5], tris[..., 5], tris[..., 6] = color, alpha, emit
    return tris.reshape(-1, 7)


def _ring(cx, cy, r0, r1, color, alpha, emit, n=32):
    a = np.linspace(0, 2 * math.pi, n + 1)
    c, s = np.cos(a), np.sin(a)
    inner = np.stack((cx + r0 * c, cy + r0 * s), -1)
    outer = np.stack((cx + r1 * c, cy + r1 * s), -1)
    quads = np.stack((inner[:-1], outer[:-1], inner[1:], inner[1:], outer[:-1], outer[1:]), axis=1)
    out = np.empty((n, 6, 7), np.float32)
    out[..., :2] = quads
    out[..., 2:5], out[..., 5], out[..., 6] = color, alpha, emit
    return out.reshape(-1, 7)


def _ribbon(points, widths, colors, alphas, emit):
    """Quad strip through ``points`` (N, 2) with per-point width, colour (N, 3) and alpha."""
    p = np.asarray(points, np.float32)
    if len(p) < 2:
        return np.empty((0, 7), np.float32)
    d = np.gradient(p, axis=0)
    d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-6
    nrm = np.stack((-d[:, 1], d[:, 0]), -1) * (np.asarray(widths, np.float32)[:, None] / 2)
    left, right = p + nrm, p - nrm
    v = np.empty((len(p), 2, 7), np.float32)
    v[:, 0, :2], v[:, 1, :2] = left, right
    v[..., 2:5] = np.asarray(colors, np.float32)[:, None, :]
    v[..., 5] = np.asarray(alphas, np.float32)[:, None]
    v[..., 6] = emit
    a, b, c, d2 = v[:-1, 0], v[:-1, 1], v[1:, 0], v[1:, 1]
    return np.stack((a, b, c, c, b, d2), axis=1).reshape(-1, 7)


def _segment(p0, p1, width, color, alpha, emit):
    return _ribbon([p0, p1], [width, width], [color, color], [alpha, alpha], emit)


class Effects:
    def __init__(self, *, seed: int = 0, max_sparks: int = 400):
        self.rng = np.random.default_rng(seed)
        self.max_sparks = max_sparks
        self.hits: dict[str, Hit] = {}
        self.sparks = np.empty((0, 9), np.float32)  # x0 y0 vx vy t0 life b g r
        self.trails = {h: deque(maxlen=24) for h in HandId}
        self.level = "full"
        self.trails_on = True
        self.total = 0

    def reset(self):
        self.hits.clear()
        self.sparks = self.sparks[:0]
        for trail in self.trails.values():
            trail.clear()

    # -- events ----------------------------------------------------------------------------------
    def on_commits(self, commits, evidence, pieces, camera, dmap, roi, t):
        by_id = {p.zone_id: p for p in pieces}
        scale = dmap.out_h / 720
        for commit in commits:
            piece = by_id.get(commit.zone_id)
            if piece is None:
                continue
            self.total += 1
            strength = float(np.clip(getattr(commit, "gain", 1.0), 0.35, 1.0))
            (ax, ay), (bx, by) = piece.segment
            e = evidence.get(commit.hand_id) if evidence else None
            x = dmap.to_display(e.tip, roi)[0] if e is not None and e.kind == "MEASURED" else (ax + bx) / 2
            local = piece.head_point(camera, (min(max(x, ax), bx), (ay + by) / 2))
            axis = np.array([local[2], 0.0, -local[0]])
            n = np.linalg.norm(axis)
            axis = axis / n if n > 1e-3 else np.array([1.0, 0.0, 0.0])
            self.hits[piece.zone_id] = Hit(t, strength, local, axis)
            count = round((14 + 26 * strength) * (1.4 if piece.cymbal else 1.0) * LEVELS[self.level])
            if count:
                origin = camera.project(piece.to_world(local)[None])[0]
                self._spawn(origin, count, piece.accent, strength, t, scale)

    def _spawn(self, origin, count, color, strength, t, scale):
        angle = self.rng.uniform(math.radians(185), math.radians(355), count)
        speed = self.rng.uniform(350, 950, count) * (0.6 + 0.4 * strength) * scale
        life = self.rng.uniform(0.25, 0.5, count)
        new = np.empty((count, 9), np.float32)
        new[:, 0], new[:, 1] = origin
        new[:, 2], new[:, 3] = np.cos(angle) * speed, np.sin(angle) * speed
        new[:, 4], new[:, 5], new[:, 6:9] = t, life, color
        self.sparks = np.concatenate((self.sparks, new))[-self.max_sparks :]

    # -- per-frame state -------------------------------------------------------------------------
    def draws(self, pieces, t, *, target=None) -> list[PieceDraw]:
        out = []
        for p in pieces:
            d = PieceDraw(p, neon=REST_NEON)
            if p.zone_id == target:  # calibration target: a slow pulse
                d.neon += 0.6 * (0.5 + 0.5 * math.sin(2 * math.pi * 1.5 * t))
            hit = self.hits.get(p.zone_id)
            if hit is not None and LEVELS[self.level] > 0:
                age = t - hit.t
                if 0 <= age < HIT_LIFE_S:
                    d.neon += 2.4 * hit.strength * math.exp(-age / NEON_TAU)
                    d.hit = (float(hit.local[0]), 0.0, float(hit.local[2]), hit.strength * LEVELS[self.level])
                    d.hit_age = age
                    tau = WOBBLE_TAU.get(p.family)
                    if tau is not None:
                        angle = (
                            math.radians(6)
                            * hit.strength
                            * math.exp(-age / tau)
                            * math.sin(2 * math.pi * 5 * age)
                        )
                        d.wobble = rot_axis(hit.axis, angle)
            out.append(d)
        return out

    def overlay(self, evidence, roi, dmap, t) -> np.ndarray:
        parts = [self._spark_tris(t, dmap.out_h / 720)]
        k = dmap.out_h / 720
        for hand, e in (evidence or {}).items():
            trail = self.trails[hand]
            color = hand_color(hand)
            if e.kind == "UNCERTAIN" and e.tip is not None:
                trail.clear()
                x, y = dmap.to_display(e.tip, roi)
                parts.append(_ring(x, y, 9 * k, 11.5 * k, WARN, 0.85, 0.8))
                continue
            if e.kind != "MEASURED":
                trail.clear()
                continue
            tip = dmap.to_display(e.tip, roi)
            if trail and t - trail[-1][0] > TRAIL_GAP_S:
                trail.clear()
            trail.append((t, tip))
            if e.origin is not None:
                origin = dmap.to_display(e.origin, roi)
                parts.append(self._stick(origin, tip, color, k))
            if self.trails_on:
                pts = [q for s, q in trail if t - s <= COMET_S]
                if len(pts) >= 2:
                    w = np.linspace(0, 1, len(pts))
                    parts.append(_ribbon(pts, 1 + 10 * k * w, [color] * len(pts), 0.55 * w, 1.2))
            parts.append(_disc(*tip, 12 * k, color, 0.22, 0.8))
            parts.append(_ring(*tip, 6 * k, 9 * k, color, 1.0, 1.8))
            parts.append(_disc(*tip, 4 * k, WHITE, 1.0, 0.6))
        return np.concatenate(parts) if parts else np.empty((0, 7), np.float32)

    @staticmethod
    def _stick(origin, tip, color, k):
        o, p = np.asarray(origin, float), np.asarray(tip, float)
        length = np.linalg.norm(p - o)
        if length < 8 * k:
            return np.empty((0, 7), np.float32)
        d = (p - o) / length
        parts = [_segment(o, p, 7 * k, color, 0.10, 0.5)]  # a faint glow along the visible stick
        for f in (0.58, 0.68):  # two neon bands, as on the reference sticks
            c = o + (p - o) * f
            parts.append(_segment(c - d * 2.5 * k, c + d * 2.5 * k, 12 * k, color, 0.9, 2.2))
        return np.concatenate(parts)

    def _spark_tris(self, t, k):
        s = self.sparks
        if not len(s):
            return np.empty((0, 7), np.float32)
        age = t - s[:, 4]
        live = (age >= 0) & (age < s[:, 5])
        self.sparks = s = s[live | (age < 0)]
        age = age[live | (age < 0)]
        draw = age >= 0
        s, age = s[draw], age[draw]
        if not len(s):
            return np.empty((0, 7), np.float32)
        g = GRAVITY * k
        x = s[:, 0] + s[:, 2] * age
        y = s[:, 1] + s[:, 3] * age + 0.5 * g * age * age
        vx, vy = s[:, 2], s[:, 3] + g * age
        head = np.stack((x, y), -1)
        tail = head - np.stack((vx, vy), -1) * 0.045
        life = 1 - age / s[:, 5]
        d = head - tail
        n = np.stack((-d[:, 1], d[:, 0]), -1) / (np.linalg.norm(d, axis=1, keepdims=True) + 1e-6)
        w = ((0.6 + 2.0 * life) * k)[:, None] / 2
        hot = np.clip(1 - (1 - life) * 1.6, 0, 1)[:, None]
        color = hot * 255 + (1 - hot) * s[:, 6:9]
        quad = np.stack(
            (head + n * w, head - n * w, tail + n * w, tail + n * w, head - n * w, tail - n * w), 1
        )
        out = np.empty((len(s), 6, 7), np.float32)
        out[..., :2] = quad
        out[..., 2:5] = color[:, None, :]
        out[..., 5] = life[:, None]
        out[..., 6] = 1.6
        return out.reshape(-1, 7)


__all__ = ["Effects", "Hit", "hand_color"]
