"""AR heads-up display drawn on the composed frame: brand card, status card, Stick Tracking panel, piece
callouts, the bottom control bar and its menus. Geometry follows the reference screen (1672 x 941) scaled
by ``k = height / 941``; the bar's right group compresses when the window is narrower than 16:9.

Every number shown traces to a logged measurement (``UiStatus``) or to current endpoint evidence;
nothing here is estimated or smoothed beyond display easing of the tracking panel's framing.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import NamedTuple

import cv2
import numpy as np

from spacedrums.contracts import HandId
from spacedrums.ui.ar import palette as P
from spacedrums.ui.ar.scene import VIEW_NAMES
from spacedrums.ui.ar.text import TextCache, blit, make_sprite

AA = cv2.LINE_AA
REF_H = 941
WOOD, WOOD_EDGE = (150, 200, 232), (70, 110, 150)
PANEL_TRAIL_S = 1.5


@dataclass
class UiStatus:
    fps: float | None = None
    latency_ms: float | None = None  # software capture -> audio schedule p50 + opened stream latency
    message: str = ""


class Rect(NamedTuple):
    x0: int
    y0: int
    x1: int
    y1: int

    def contains(self, x, y) -> bool:
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1

    def intersects(self, o) -> bool:
        return self.x0 < o.x1 and o.x0 < self.x1 and self.y0 < o.y1 and o.y0 < self.y1

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0


def _r(*v):
    return Rect(*(int(round(c)) for c in v))


def rounded_mask(w, h, r, thickness=-1):
    """uint8 mask of a rounded rectangle (filled, or an outline of ``thickness`` px)."""
    s = 4
    big = np.zeros((h * s, w * s), np.uint8)
    rr = max(1, r * s)
    x0, y0, x1, y1 = 0, 0, w * s - 1, h * s - 1
    if thickness < 0:
        cv2.rectangle(big, (x0 + rr, y0), (x1 - rr, y1), 255, -1)
        cv2.rectangle(big, (x0, y0 + rr), (x1, y1 - rr), 255, -1)
        for cx, cy in ((x0 + rr, y0 + rr), (x1 - rr, y0 + rr), (x0 + rr, y1 - rr), (x1 - rr, y1 - rr)):
            cv2.circle(big, (cx, cy), rr, 255, -1)
    else:
        t = thickness * s
        h2 = t // 2
        x0, y0, x1, y1 = x0 + h2, y0 + h2, x1 - h2, y1 - h2
        cv2.line(big, (x0 + rr, y0), (x1 - rr, y0), 255, t)
        cv2.line(big, (x0 + rr, y1), (x1 - rr, y1), 255, t)
        cv2.line(big, (x0, y0 + rr), (x0, y1 - rr), 255, t)
        cv2.line(big, (x1, y0 + rr), (x1, y1 - rr), 255, t)
        for (cx, cy), a in (
            ((x0 + rr, y0 + rr), 180),
            ((x1 - rr, y0 + rr), 270),
            ((x1 - rr, y1 - rr), 0),
            ((x0 + rr, y1 - rr), 90),
        ):
            cv2.ellipse(big, (cx, cy), (rr, rr), a, 0, 90, 255, t)
    return cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)


class Sprites:
    """Cached blit-ready panels and icons (see ``text.make_sprite``)."""

    def __init__(self):
        self.cache = {}

    def panel(self, w, h, r, fill=P.PANEL, alpha=P.PANEL_ALPHA, border=P.BORDER, border_w=1):
        key = ("panel", w, h, r, fill, alpha, border, border_w)
        if key not in self.cache:
            color = np.empty((h, w, 3), np.float32)
            color[:] = fill
            a = rounded_mask(w, h, r).astype(np.float32) / 255 * alpha
            if border is not None:
                b = rounded_mask(w, h, r, border_w).astype(np.float32) / 255
                color = color * (1 - b[..., None]) + np.asarray(border, np.float32) * b[..., None]
                a = np.maximum(a, b * 0.95)
            self.cache[key] = make_sprite(color, a)
        return self.cache[key]

    def drum_icon(self, size, color):
        key = ("drum", size, color)
        if key not in self.cache:
            s = 8
            n = size * s
            m = np.zeros((n, n), np.uint8)
            t = max(1, round(n * 0.055))
            cx, top, bot, rx, ry = n // 2, int(n * 0.42), int(n * 0.86), int(n * 0.36), int(n * 0.10)
            cv2.ellipse(m, (cx, top), (rx, ry), 0, 0, 360, 255, t)
            cv2.ellipse(m, (cx, bot), (rx, ry), 0, 0, 180, 255, t)
            cv2.line(m, (cx - rx, top), (cx - rx, bot), 255, t)
            cv2.line(m, (cx + rx, top), (cx + rx, bot), 255, t)
            for f in (-0.6, -0.2, 0.2, 0.6):
                x = int(cx + rx * f)
                cv2.line(m, (x, top + int(ry * 0.9)), (x, bot + int(ry * 0.6)), 255, max(1, t // 2))
            cv2.line(m, (int(n * 0.18), int(n * 0.06)), (int(n * 0.62), int(n * 0.36)), 255, t)
            cv2.line(m, (int(n * 0.82), int(n * 0.06)), (int(n * 0.38), int(n * 0.36)), 255, t)
            a = cv2.resize(m, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
            self.cache[key] = make_sprite(color, a)
        return self.cache[key]


class HudLayout:
    """Rectangles of every HUD element for an image size; also the controls' hit-testing."""

    def __init__(self, w, h, controls):
        self.w, self.h = w, h
        k = self.k = h / REF_H
        self.brand = _r(18 * k, 12 * k, 302 * k, 86 * k)
        self.status = _r(24 * k, 100 * k, 270 * k, 268 * k)
        self.tracking = _r(w - 386 * k, 16 * k, w - 15 * k, 292 * k)
        t = self.tracking
        self.stick_panels = {
            HandId.LEFT: _r(t.x0 + 13 * k, t.y0 + 53 * k, t.x0 + 179 * k, t.y1 - 15 * k),
            HandId.RIGHT: _r(t.x0 + 192 * k, t.y0 + 53 * k, t.x1 - 13 * k, t.y1 - 15 * k),
        }
        y0 = self.bar_y = round(h - 93 * k)
        self.bar = Rect(0, y0, w, h)
        self.settings_button = _r(18 * k, y0 + 13 * k, 193 * k, y0 + 80 * k)
        self.camera_caption = (233 * k, y0 + 10 * k)
        self.camera_button = _r(231 * k, y0 + 32 * k, 472 * k, y0 + 74 * k)
        # Right group, laid out from the right edge; sliders shrink when the bar is narrow.
        avail = w - 20 * k - (self.camera_button.x1 + 40 * k)
        natural = 855 * k
        f = min(1.0, max(0.45, avail / natural))
        x = w - 32 * k
        self.volume_value = (x, y0 + 47 * k)
        x -= 42 * k
        self.volume_track = _r(x - 155 * k * f, y0 + 43 * k, x, y0 + 51 * k)
        x = self.volume_track.x0 - 22 * k
        self.volume_label = (x, y0 + 47 * k)
        x -= 66 * k + 22 * k
        self.volume_icon = (x, y0 + 47 * k)
        x -= 120 * k * f
        self.sens_value = (x, y0 + 47 * k)
        x -= 23 * k
        self.sens_track = _r(x - 200 * k * f, y0 + 43 * k, x, y0 + 51 * k)
        self.sens_label = (self.sens_track.x0 - 16 * k, y0 + 47 * k)
        self.items: list[tuple[Rect, str]] = []
        self.menu_rect = None
        self._menus(controls)

    def _menus(self, controls):
        k = self.k
        row = round(34 * k)
        if controls.menu == "camera":
            entries = [("VIEWPOINT", None)] + [(VIEW_NAMES[v], f"viewpoint:{v}") for v in VIEW_NAMES]
            entries += [("CAMERA", None)] + [(name, f"device:{i}") for i, name in controls.devices]
            x0 = self.camera_button.x0
            width = max(self.camera_button.w + round(60 * k), round(300 * k))
        elif controls.menu == "settings":
            entries = [(label, f"setting:{key}") for key, label, _ in controls.settings.items()]
            x0 = self.settings_button.x0
            width = round(340 * k)
        else:
            return
        height = row * len(entries) + round(16 * k)
        y1 = self.bar_y - round(8 * k)
        self.menu_rect = Rect(x0, y1 - height, x0 + width, y1)
        y = self.menu_rect.y0 + round(8 * k)
        for label, target in entries:
            rect = Rect(x0 + round(6 * k), y, x0 + width - round(6 * k), y + row)
            self.items.append((rect, target or f"header:{label}"))
            y += row

    def hit(self, x, y, controls):
        if self.menu_rect is not None and self.menu_rect.contains(x, y):
            for rect, target in self.items:
                if rect.contains(x, y) and not target.startswith("header:"):
                    return target
            return "menu"
        if self.settings_button.contains(x, y):
            return "settings_button"
        if self.camera_button.contains(x, y):
            return "camera_button"
        pad = round(14 * self.k)
        for name, track in (("sensitivity", self.sens_track), ("volume", self.volume_track)):
            if track.x0 - pad <= x <= track.x1 + pad and track.y0 - pad <= y <= track.y1 + pad:
                return name
        return None

    def slider_value(self, name, x):
        track = self.sens_track if name == "sensitivity" else self.volume_track
        return (x - track.x0) / max(1, track.w)

    def panels(self, controls):
        """Boxes the callouts must avoid."""
        boxes = [self.bar]
        if controls.settings.panels:
            boxes += [self.brand, self.status, self.tracking]
        return boxes


class Hud:
    def __init__(self, text: TextCache | None = None):
        self.text = text or TextCache()
        self.sprites = Sprites()
        self.layout: HudLayout | None = None
        self.tips = {h: deque(maxlen=64) for h in HandId}
        self.framing = {}

    def update_layout(self, w, h, controls) -> HudLayout:
        self.layout = HudLayout(w, h, controls)
        return self.layout

    # -- primitives ------------------------------------------------------------------------------
    def _panel(self, img, rect, r, **kw):
        blit(img, self.sprites.panel(rect.w, rect.h, r, **kw), rect.x0, rect.y0)

    def _dot(self, img, center, r, color):
        cv2.circle(img, tuple(map(round, center)), max(1, round(r)), color, -1, AA)

    # -- sections --------------------------------------------------------------------------------
    def draw(self, img, *, status: UiStatus, evidence, roi, dmap, camera, pieces, controls, t):
        lay = self.update_layout(img.shape[1], img.shape[0], controls)
        k = lay.k
        self._track(evidence, roi, dmap, t)
        self._callouts(img, pieces, camera, lay, controls)
        if controls.settings.panels:
            self._brand(img, lay)
            self._status(img, lay, status, evidence)
            self._tracking(img, lay, evidence, roi, dmap, t)
        if status.message:
            self._toast(img, lay, status.message)
        self._bar(img, lay, controls)
        if controls.menu:
            self._menu(img, lay, controls)
        return k

    def _brand(self, img, lay):
        k, b = lay.k, lay.brand
        self._panel(img, b, round(10 * k))
        size = round(44 * k)
        blit(img, self.sprites.drum_icon(size, P.TEXT), round(b.x0 + 18 * k), round(b.y0 + 14 * k))
        self.text.draw(img, "SpaceDrums", (b.x0 + 78 * k, b.y0 + 8 * k), round(30 * k), P.TEXT, "semibold")
        self.text.draw(img, "AI Air Drumming", (b.x0 + 79 * k, b.y0 + 44 * k), round(17 * k), P.MUTED)

    def _status(self, img, lay, status, evidence):
        k, r = lay.k, lay.status
        self._panel(img, r, round(10 * k))
        x_label, x_value = r.x0 + 18 * k, r.x0 + 137 * k
        rows = [r.y0 + (27 + 30 * i) * k for i in range(5)]
        size = round(18 * k)
        fps = status.fps
        fps_color = P.IDLE if fps is None else P.OK if fps >= 24 else P.WARN if fps >= 15 else P.BAD
        lat = status.latency_ms
        lat_color = P.IDLE if lat is None else P.OK if lat < 60 else P.WARN if lat < 100 else P.BAD
        measured = sum(e.kind == "MEASURED" for e in (evidence or {}).values())
        sticks = {2: ("Detected", P.OK), 1: ("Partial", P.WARN)}.get(measured, ("Not detected", P.BAD))
        values = [
            ("FPS", "—" if fps is None else f"{fps:.0f}", fps_color, None),
            ("Latency", "—" if lat is None else f"{lat:.0f} ms", lat_color, None),
            ("Sticks", sticks[0], P.TEXT, sticks[1]),
        ]
        for hand, name in ((HandId.LEFT, "Left Hand"), (HandId.RIGHT, "Right Hand")):
            e = (evidence or {}).get(hand)
            kind = e.kind if e is not None else "MISSING"
            text, dot = {
                "MEASURED": ("Active", P.LEFT if hand is HandId.LEFT else P.RIGHT),
                "UNCERTAIN": ("Tracking", P.WARN),
            }.get(kind, ("Lost", P.IDLE))
            values.append((name, text, P.TEXT, dot))
        for y, (label, value, color, dot) in zip(rows, values, strict=True):
            self.text.draw(img, label, (x_label, y), size, P.MUTED, anchor="lm")
            x = x_value
            if dot is not None:
                self._dot(img, (x + 6 * k, y + 1), 6 * k, dot)
                x += 20 * k
            self.text.draw(
                img, value, (x, y), size, color, "semibold" if dot is None else "regular", anchor="lm"
            )

    def _track(self, evidence, roi, dmap, t):
        for hand in HandId:
            e = (evidence or {}).get(hand)
            trail = self.tips[hand]
            if e is None or e.kind != "MEASURED":
                trail.clear()
                continue
            trail.append((t, dmap.to_display(e.tip, roi)))
            while trail and t - trail[0][0] > PANEL_TRAIL_S:
                trail.popleft()

    def _tracking(self, img, lay, evidence, roi, dmap, t):
        k, r = lay.k, lay.tracking
        self._panel(img, r, round(10 * k))
        self.text.icon(img, "sync", (r.x0 + 30 * k, r.y0 + 28 * k), round(20 * k), P.TEXT)
        self.text.draw(
            img,
            "Stick Tracking",
            (r.x0 + 50 * k, r.y0 + 28 * k),
            round(19 * k),
            P.TEXT,
            "semibold",
            anchor="lm",
        )
        for hand, title in ((HandId.LEFT, "Left Stick"), (HandId.RIGHT, "Right Stick")):
            self._stick_panel(img, lay, hand, title, (evidence or {}).get(hand), roi, dmap)

    def _stick_panel(self, img, lay, hand, title, e, roi, dmap):
        k = lay.k
        box = lay.stick_panels[hand]
        color = P.LEFT if hand is HandId.LEFT else P.RIGHT
        tab = round(33 * k)
        self._panel(img, box, round(4 * k), fill=(48, 30, 20), alpha=0.92, border=(110, 82, 62))
        view = img[box.y0 + tab : box.y1 - 1, box.x0 + 1 : box.x1 - 1]
        step = max(6, round(18 * k))
        view[:, ::step] = (view[:, ::step] * 0.55 + np.array(P.GRID) * 0.45).astype(np.uint8)
        view[::step, :] = (view[::step, :] * 0.55 + np.array(P.GRID) * 0.45).astype(np.uint8)
        tab_fill = tuple(int(c * 0.35) for c in color)
        blit(
            img,
            self.sprites.panel(box.w, tab, round(4 * k), fill=tab_fill, alpha=0.95, border=None),
            box.x0,
            box.y0,
        )
        cv2.line(img, (box.x0 + 1, box.y0 + tab), (box.x1 - 2, box.y0 + tab), color, max(1, round(2 * k)), AA)
        light = tuple(min(255, int(c * 0.6 + 110)) for c in color)
        self.text.draw(
            img,
            title,
            ((box.x0 + box.x1) / 2, box.y0 + tab / 2),
            round(16 * k),
            light,
            "semibold",
            anchor="cm",
        )
        vh, vw = view.shape[:2]
        if e is None or e.kind != "MEASURED":
            self.framing.pop(hand, None)
            self.text.draw(view, "No stick", (vw / 2, vh / 2), round(15 * k), P.IDLE, anchor="cm")
            return
        tip = np.array(dmap.to_display(e.tip, roi))
        origin = np.array(dmap.to_display(e.origin, roi)) if e.origin is not None else tip
        length = float(np.linalg.norm(tip - origin))
        center = (tip + origin) / 2
        scale = min(2.5, 0.78 * vh / length) if length > 4 else 1.0
        # Ease the framing so the stick does not jitter with the panel; the data itself is not smoothed.
        prev = self.framing.get(hand)
        if prev is not None:
            center = prev[0] * 0.7 + center * 0.3
            scale = prev[1] * 0.8 + scale * 0.2
        self.framing[hand] = (center, scale)
        anchor = np.array([vw / 2, vh / 2 + 4 * k])

        def to_panel(p):
            q = anchor + (np.asarray(p) - center) * scale
            return int(round(q[0] * 16)), int(round(q[1] * 16))

        trail = [to_panel(p) for _, p in self.tips[hand]]
        if len(trail) >= 2:
            cv2.polylines(view, [np.array(trail, np.int32)], False, color, max(1, round(1.5 * k)), AA, 4)
        tp = to_panel(tip)
        if length > 4:
            op = to_panel(origin)
            d = np.subtract(tp, op).astype(float)
            n = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-6)
            w0, w1 = 4.0 * k * 16, 2.3 * k * 16
            quad = np.array([op + n * w0, tp + n * w1, tp - n * w1, op - n * w0], np.int32)
            cv2.fillConvexPoly(view, quad, WOOD, AA, 4)
            cv2.polylines(view, [quad], True, WOOD_EDGE, 1, AA, 4)
            for f in (0.12, 0.2):
                c = np.add(op, d * f)
                cv2.line(
                    view,
                    tuple((c - n * w0 * 1.3).astype(int)),
                    tuple((c + n * w0 * 1.3).astype(int)),
                    color,
                    max(1, round(2 * k)),
                    AA,
                    4,
                )
        r = round(7 * k)
        cv2.circle(
            view, tp, r * 16 + 8 * 16, tuple(int(c * 0.35) for c in color), max(1, round(3 * k)), AA, 4
        )
        cv2.circle(view, tp, r * 16, color, max(1, round(2.5 * k)), AA, 4)
        cv2.circle(view, tp, max(1, round(3 * k)) * 16, (255, 255, 255), -1, AA, 4)

    def _callouts(self, img, pieces, camera, lay, controls):
        k = lay.k
        avoid = lay.panels(controls)
        size = round(23 * k)
        for p in pieces:
            (ax, ay), (bx, by) = p.segment
            width = bx - ax
            side = -1 if (ax + bx) / 2 < lay.w / 2 else 1
            if p.cymbal:
                local = (0.0, 0.13, 0.0) if side < 0 else (0.45, 0.02, 0.15)
                offset = (side * 0.09 * width, -0.175 * width)
            else:
                local = (0.3 * side, 0.0, 0.55)
                offset = (side * 0.2 * width, 0.2 * width)
            anchor = camera.project(p.to_world(local)[None])[0]
            tw, th = self.text.size(p.label, size, "semibold")
            bw, bh = tw + round(26 * k), th + round(10 * k)
            cx, cy = anchor[0] + offset[0], anchor[1] + offset[1]
            box = _r(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
            box = self._place(box, avoid, lay)
            near = (min(max(anchor[0], box.x0), box.x1), box.y1 if anchor[1] > box.y1 else box.y0)
            cv2.line(
                img, tuple(map(round, near)), tuple(map(round, anchor)), (235, 235, 235), max(1, round(k)), AA
            )
            self._dot(img, anchor, 4.5 * k, p.accent)
            cv2.circle(img, tuple(map(round, anchor)), max(2, round(4.5 * k)), (255, 255, 255), 1, AA)
            self._panel(img, box, round(7 * k), alpha=0.86, border=p.accent, border_w=max(1, round(2 * k)))
            self.text.draw(
                img,
                p.label,
                ((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2),
                size,
                P.TEXT,
                "semibold",
                anchor="cm",
            )
            avoid.append(box)

    @staticmethod
    def _place(box, avoid, lay):
        dx = max(0, -box.x0) - max(0, box.x1 - lay.w)
        dy = max(0, -box.y0) - max(0, box.y1 - lay.bar_y + 4)
        box = Rect(box.x0 + dx, box.y0 + dy, box.x1 + dx, box.y1 + dy)
        for _ in range(8):  # nudge down/up out of panels and earlier callouts
            hit = next((a for a in avoid if a.intersects(box)), None)
            if hit is None:
                break
            down = hit.y1 - box.y0 + 4
            up = box.y1 - hit.y0 + 4
            shift = down if (box.y1 + down < lay.bar_y and down <= up) or box.y0 - up < 0 else -up
            box = Rect(box.x0, box.y0 + shift, box.x1, box.y1 + shift)
        return box

    def _toast(self, img, lay, message):
        k = lay.k
        size = round(19 * k)
        tw, th = self.text.size(message, size)
        bw, bh = tw + round(40 * k), th + round(14 * k)
        box = _r(lay.w / 2 - bw / 2, lay.bar_y - bh - 16 * k, lay.w / 2 + bw / 2, lay.bar_y - 16 * k)
        self._panel(img, box, bh // 2, alpha=0.86)
        self.text.draw(img, message, (lay.w / 2, (box.y0 + box.y1) / 2), size, P.TEXT, anchor="cm")

    def _bar(self, img, lay, controls):
        k = lay.k
        bar = lay.bar
        blit(img, self.sprites.panel(bar.w, bar.h, 1, fill=(34, 22, 14), alpha=0.9, border=None), 0, bar.y0)
        cv2.line(img, (0, bar.y0), (bar.w, bar.y0), (80, 62, 48), 1, AA)
        hover = controls.hover
        b = lay.settings_button
        fill = (70, 50, 36) if hover == "settings_button" or controls.menu == "settings" else (52, 36, 26)
        self._panel(img, b, round(8 * k), fill=fill, alpha=0.95, border=(100, 78, 62))
        self.text.icon(img, "settings", (b.x0 + 36 * k, (b.y0 + b.y1) / 2), round(30 * k), P.TEXT)
        self.text.draw(
            img, "Settings", (b.x0 + 67 * k, (b.y0 + b.y1) / 2), round(21 * k), P.TEXT, anchor="lm"
        )
        self.text.draw(img, "Camera View", lay.camera_caption, round(17 * k), P.MUTED)
        c = lay.camera_button
        fill = (70, 50, 36) if hover == "camera_button" or controls.menu == "camera" else (46, 32, 23)
        self._panel(img, c, round(7 * k), fill=fill, alpha=0.95, border=(110, 86, 68))
        mid = (c.y0 + c.y1) / 2
        self.text.icon(img, "camera", (c.x0 + 25 * k, mid), round(20 * k), P.TEXT)
        label = controls.camera_label
        size = round(18 * k)
        while self.text.size(label, size)[0] > c.w - 85 * k and len(label) > 4:
            label = label[:-2] + "…" if not label.endswith("…") else label[:-2] + "…"
        self.text.draw(img, label, (c.x0 + 49 * k, mid), size, P.TEXT, anchor="lm")
        self.text.icon(img, "chevron", (c.x1 - 22 * k, mid), round(13 * k), P.TEXT)
        self.text.draw(img, "Sensitivity", lay.sens_label, round(20 * k), P.TEXT, anchor="rm")
        self._slider(img, lay.sens_track, controls.sensitivity, k)
        self.text.draw(img, _fmt(controls.sensitivity), lay.sens_value, round(19 * k), P.TEXT, anchor="lm")
        self.text.icon(img, "volume", lay.volume_icon, round(30 * k), P.TEXT)
        self.text.draw(img, "Volume", lay.volume_label, round(20 * k), P.TEXT, anchor="rm")
        self._slider(img, lay.volume_track, controls.volume, k)
        self.text.draw(img, _fmt(controls.volume), lay.volume_value, round(19 * k), P.TEXT, anchor="lm")

    def _slider(self, img, track, value, k):
        r = max(2, track.h // 2)
        blit(
            img,
            self.sprites.panel(track.w, track.h, r, fill=(110, 92, 80), alpha=0.9, border=None),
            track.x0,
            track.y0,
        )
        fx = track.x0 + round(track.w * value)
        if fx - track.x0 > 2 * r:
            blit(
                img,
                self.sprites.panel(fx - track.x0, track.h, r, fill=P.TRACK, alpha=1.0, border=None),
                track.x0,
                track.y0,
            )
        cy = (track.y0 + track.y1) / 2
        cv2.circle(img, (fx, round(cy + 1.5 * k)), round(12 * k), (20, 14, 10), -1, AA)
        cv2.circle(img, (fx, round(cy)), round(11 * k), (255, 255, 255), -1, AA)
        cv2.circle(img, (fx, round(cy)), round(5 * k), P.TRACK, -1, AA)

    def _menu(self, img, lay, controls):
        k = lay.k
        m = lay.menu_rect
        if m is None:
            return
        self._panel(img, m, round(9 * k), alpha=0.95, border=(110, 86, 68))
        values = {f"setting:{key}": value for key, _, value in controls.settings.items()}
        for rect, target in lay.items:
            mid = (rect.y0 + rect.y1) / 2
            if target.startswith("header:"):
                self.text.draw(
                    img, target[7:], (rect.x0 + 10 * k, mid), round(13 * k), P.MUTED, "semibold", anchor="lm"
                )
                continue
            if target == controls.hover:
                blit(
                    img,
                    self.sprites.panel(
                        rect.w, rect.h, round(5 * k), fill=(80, 58, 42), alpha=0.9, border=None
                    ),
                    rect.x0,
                    rect.y0,
                )
            kind, _, arg = target.partition(":")
            selected = (kind == "viewpoint" and arg == controls.viewpoint) or (
                kind == "device" and int(arg) == controls.device
            )
            label = self._item_label(target, controls)
            if selected:
                self._dot(img, (rect.x0 + 16 * k, mid), 4.5 * k, P.TRACK)
            self.text.draw(img, label, (rect.x0 + 30 * k, mid), round(17 * k), P.TEXT, anchor="lm")
            if target in values and values[target]:
                self.text.draw(
                    img, values[target], (rect.x1 - 12 * k, mid), round(16 * k), P.MUTED, anchor="rm"
                )

    @staticmethod
    def _item_label(target, controls):
        kind, _, arg = target.partition(":")
        if kind == "viewpoint":
            return VIEW_NAMES[arg]
        if kind == "device":
            return dict(controls.devices).get(int(arg), f"Camera {arg}")
        if kind == "setting":
            return next(label for key, label, _ in controls.settings.items() if key == arg)
        return target


def _fmt(v):
    return f"{v:.1f}" if math.isclose(v * 10, round(v * 10), abs_tol=1e-6) else f"{v:.2f}"


__all__ = ["Hud", "HudLayout", "Rect", "UiStatus"]
