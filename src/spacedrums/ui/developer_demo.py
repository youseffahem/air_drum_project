"""Camera diagnostics for the explicit developer demo; no event generation here."""

from collections import Counter, deque

import cv2
import numpy as np

from spacedrums.contracts import HandId
from spacedrums.ui.canvas import Canvas
from spacedrums.ui.preview import mirror_preview


def draw_status(img, lines):
    """Draw a content-sized, translucent HUD without resizing/dimming the camera."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = cv2.getFontScaleFromHeight(font, 14, 1)
    sizes = [cv2.getTextSize(line, font, scale, 1) for line in lines]
    margin, padding, leading = 6, 6, 20
    width = max(size[0][0] for size in sizes) + 2 * padding
    height = (len(lines) - 1) * leading + 14 + sizes[0][1] + 2 * padding
    patch = img[margin:margin + height, margin:margin + width]
    shade = np.full_like(patch, (20, 23, 31))
    cv2.addWeighted(patch, 0.45, shade, 0.55, 0, dst=patch)
    for i, line in enumerate(lines):
        cv2.putText(img, line, (margin + padding, margin + padding + 14 + i * leading),
                    font, scale, (245, 247, 250), 1, cv2.LINE_AA)


class DemoOverlay:
    def __init__(self):
        self.counts = Counter()
        self.last_hits = {}
        self.trails = {h: deque(maxlen=8) for h in HandId}
        self.times = deque(maxlen=60)
        self.last_hit = None

    def render(self, full, roi, registry, evidence, result, *, dropped, perception_ms, audio_state,
               stroke_diagnostics, cue=None):
        t = result.sample.t_capture
        self.times.append(t)
        fps = (len(self.times) - 1) / (t - self.times[0]) if len(self.times) > 1 else 0
        img = mirror_preview(full)
        scene = Canvas.for_display(img, True).roi(roi)

        def px(p):
            return round(p[0] * roi.w), round(p[1] * roi.h)

        for commit in result.commits:
            self.counts[commit.zone_id] += 1
            self.last_hits[commit.zone_id] = t
            self.last_hit = commit.zone_id
        audio_label = {"RUNNING": "OK", "DISABLED": "OFF", "NOT_STARTED": "WAIT"}.get(
            audio_state, audio_state)
        tips = [f"{str(hand)[0]}: {'TIP OK' if evidence[hand].kind == 'MEASURED' else 'NO TIP'}"
                for hand in HandId]
        # Hershey fonts are ASCII-only; avoid unsupported bullet/checkmark glyphs.
        lines = ["DEV DEMO | FIXED GUIDE",
                 f"FPS {fps:.1f} | P {perception_ms:.1f}ms | AUDIO {audio_label}",
                 " | ".join(tips)]
        if cue:
            lines.append(cue)
        elif self.last_hit is not None:
            name = registry[self.last_hit].name.upper()
            lines.append(f"HIT: {name} {self.counts[self.last_hit]}")
        # Draw first so measured stick tips/trails and drum outlines stay visible.
        draw_status(img, lines)
        for zone in registry:
            hit = t - self.last_hits.get(zone.zone_id, -float("inf")) < 0.22
            color = (50, 255, 90) if hit else (230, 180, 90)
            points = scene.points(np.array([px(p) for p in zone.shape.points], np.int32))
            cv2.polylines(scene.image, [points], True, color, 3 if hit else 1, cv2.LINE_AA)
            a, b = zone.impact_surface.p0, zone.impact_surface.p1
            scene.line(px(a), px(b), (50, 235, 255), 3, cv2.LINE_AA)
            x, y = points.min(axis=0)
            cv2.putText(scene.image, zone.name, (x + 4, y + 27),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.31, color, 1, cv2.LINE_AA)
        for hand, e in evidence.items():
            trail = self.trails[hand]
            if e.kind != "MEASURED":
                trail.clear()
                continue
            if trail and t - trail[-1][0] > 0.115:
                trail.clear()
            trail.append((t, e.tip))
            for (_, a), (_, b) in zip(list(trail), list(trail)[1:], strict=False):
                scene.line(px(a), px(b), (100, 200, 100), 1, cv2.LINE_AA)
            scene.line(px(e.origin), px(e.tip), (140, 190, 225), 2, cv2.LINE_AA)
            scene.circle(px(e.tip), 5, (60, 255, 100), -1, cv2.LINE_AA)
        return img
