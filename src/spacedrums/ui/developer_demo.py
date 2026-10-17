"""Camera diagnostics for the explicit developer demo; no event generation here.

With red painted tips (``tip_diagnostics``, app.play --red-tips) the view also shows the red mask (inset:
paint seeds, or the redness detector's candidate regions), candidates (yellow; with the redness detector the
cap outline and the verifier quality ``q``) and rejected candidates (grey, with the reason), each hand's
slot id/state/confidence (filled = measured; orange ring = seen but not trusted: ambiguous, cut by the
border or low evidence; thin ring = prediction, never used for a hit), strike candidates (magenta) and
per-hand stroke reasons. Without it the rendering is unchanged.
"""

import math
from collections import Counter, deque

import cv2
import numpy as np

from spacedrums.contracts import HandId
from spacedrums.ui.canvas import Canvas
from spacedrums.ui.preview import mirror_preview
from spacedrums.ui.theme import DEFAULT_THEME

REJECT_SHORT = {"OFF_COLOUR": "OFF", "TOO_LARGE": "LARGE", "TOO_ELONGATED": "LONG", "SAME_CAP": "SAME",
                "IGNORED_REGION": "IGN"}
SHORT_STATE = {"OBSERVED": "OBS", "WEAK": "WEAK", "DARK": "DARK", "AMBIGUOUS": "AMBIG", "CLIPPED": "EDGE",
               "WEAK_LIMIT": "WEAK!", "LOW_EVIDENCE": "LOW", "PREDICTED": "PRED", "NO_TRACK": "--"}
INSET = (160, 120)


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
        self.tip_frames = 0
        self.tip_measured = Counter()

    def render(self, full, roi, registry, evidence, result, *, dropped, perception_ms, audio_state,
               stroke_diagnostics, cue=None, tip_diagnostics=None, px_scale=1.0):
        """``full``/``roi`` may be the native-resolution preview and the ROI scaled to it; ``px_scale``
        (display / tracking pixels) then maps the red-tip tracker's ROI-pixel coordinates."""
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
        if tip_diagnostics is not None:
            lines.extend(self._tip_lines(tip_diagnostics, stroke_diagnostics))
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
        if tip_diagnostics is not None:
            self._draw_tips(img, scene, roi, tip_diagnostics, result, px_scale)
        return img

    def _tip_lines(self, d, stroke_diagnostics):
        self.tip_frames += 1
        parts, strokes = [], []
        for hand in HandId:
            st = d.slots[hand]
            self.tip_measured[hand] += st.measured
            ident = f"#{st.track_id}" if st.track_id is not None else ""
            share = 100 * self.tip_measured[hand] / self.tip_frames
            parts.append(f"{str(hand)[0]} {SHORT_STATE[st.state]}{ident} {share:.0f}%")
            reason = (stroke_diagnostics or {}).get(hand, {}).get("reason", "-")
            strokes.append(f"{str(hand)[0]} {reason}")
        flags = " AMBIG" if d.ambiguous else ""
        flags += " RESET " + "".join(str(h)[0] for h in sorted(d.resets)) if d.resets else ""
        return [f"RED {d.ms:.1f}ms | " + " | ".join(parts) + flags, "STROKE " + " | ".join(strokes)]

    def _draw_tips(self, img, scene, roi, d, result, scale=1.0):
        def px(p):  # tracker ROI pixels -> display ROI pixels
            return round(p[0] * scale), round(p[1] * scale)

        def label(p, text, color):
            q = scene.point(px(p))
            cv2.putText(scene.image, text, (q[0] + 9, q[1] - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1,
                        cv2.LINE_AA)

        for b in d.rejected:  # grey ring + why (OFF = off colour, LARGE, LONG)
            scene.circle(px(b.center), 7, (130, 130, 130), 1, cv2.LINE_AA)
            label(b.center, REJECT_SHORT.get(b.reason, str(b.reason)), (150, 150, 150))
        for b in d.candidates:  # ring = cap point (yellow red paint, violet dark paint + its context share)
            colour = (255, 120, 200) if b.dark else (0, 220, 255)
            if b.outline:  # redness detector: the cap region's outline and the verifier quality
                scene.polylines([np.array([px(p) for p in b.outline])], True, colour, 1, cv2.LINE_AA)
                scene.circle(px(b.center), 2, colour, -1, cv2.LINE_AA)
                label(b.center, f"q {b.score:.2f}", colour)
            else:
                scene.circle(px(b.center), 11, colour, 1, cv2.LINE_AA)
            if b.dark and b.surround is not None:
                label(b.center, f"ctx {b.surround:.2f}", colour)
            if not b.outline and b.region_center is not None and math.dist(b.region_center, b.center) > 2:
                scene.circle(px(b.region_center), 3, (160, 160, 160), -1, cv2.LINE_AA)
        for hf in result.hands.values():
            for c in hf.candidates:  # normalised -> already display ROI pixels
                x, y = c.impact_position[0] * roi.w, c.impact_position[1] * roi.h
                scene.line((round(x - 6), round(y)), (round(x + 6), round(y)), (255, 0, 255), 2, cv2.LINE_AA)
                scene.line((round(x), round(y - 6)), (round(x), round(y + 6)), (255, 0, 255), 2, cv2.LINE_AA)
        for hand, st in d.slots.items():
            color = DEFAULT_THEME.left if hand is HandId.LEFT else DEFAULT_THEME.right
            name = f"{str(hand)[0]}#{st.track_id}"
            if st.measured:
                scene.circle(px(st.tip), 7, color, -1, cv2.LINE_AA)
                label(st.tip, f"{name} {SHORT_STATE[st.state]} {st.confidence:.2f}", color)
            elif st.tip is not None:  # seen but not trusted: no stroke uses it
                scene.circle(px(st.tip), 8, (0, 140, 255), 2, cv2.LINE_AA)
                label(st.tip, f"{name} {SHORT_STATE[st.state]}", (0, 140, 255))
            elif st.predicted is not None:  # coasting prediction: drawn, never measured
                scene.circle(px(st.predicted), 9, color, 1, cv2.LINE_AA)
                label(st.predicted, f"{name} PRED {st.misses}", color)
        w, h = INSET
        rows, cols = img.shape[:2]
        if d.mask is not None and rows > h + 16 and cols > w + 16:
            # INTER_AREA keeps a small blob visible after the 4x reduction; the display is mirrored.
            inset = cv2.flip(cv2.resize(d.mask, INSET, interpolation=cv2.INTER_AREA), 1)
            y0, x0 = rows - h - 8, cols - w - 8
            patch = img[y0:y0 + h, x0:x0 + w]
            patch[:] = patch // 3
            if d.region is not None:  # growth near seeds (dark red), seeds = paint core (red)
                grown = cv2.flip(cv2.resize(d.region, INSET, interpolation=cv2.INTER_AREA), 1)
                patch[grown > 0] = (40, 40, 140)
            patch[inset > 0] = (60, 60, 255)
            cv2.rectangle(img, (x0 - 1, y0 - 1), (x0 + w, y0 + h), (200, 200, 200), 1)
            title = "RED MASK" if d.mask.shape[:2] == (d.roi_size[1], d.roi_size[0]) else "REDNESS"
            cv2.putText(img, title, (x0 + 4, y0 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (235, 235, 235), 1,
                        cv2.LINE_AA)
