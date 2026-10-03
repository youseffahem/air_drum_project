"""Product view: metallic cymbals, drum heads, wooden sticks and standing guide.

All scene geometry goes through the same display-only mirror as the validated
preview. No confidence, FPS, tracker states or developer text is drawn here.
"""

from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

from spacedrums.ui.canvas import Canvas
from spacedrums.ui.preview import mirror_preview


@lru_cache(maxsize=32)
def pad_texture(width, height, cymbal):
    yy, xx = np.mgrid[0:height, 0:width]
    nx, ny = (xx - width / 2) / (width / 2), (yy - height / 2) / (height / 2)
    radius = np.sqrt(nx * nx + ny * ny)
    if cymbal:
        rings = np.sin(radius * 125) * 6
        light = 24 * np.cos(np.arctan2(ny, nx) - 1.2)
        base = np.stack((100 + rings + light, 165 + rings + light, 201 + rings + light), axis=-1)
    else:
        shade = 212 - 35 * radius + 12 * ny
        base = np.stack((shade + 7, shade + 4, shade), axis=-1)
    return np.clip(base, 0, 255).astype(np.uint8)


def render_kit(full, roi, registry=None, *, sticks=(), body=None, message="", target=None, mirror=True):
    img = mirror_preview(full) if mirror else full.copy()
    img = cv2.convertScaleAbs(img, alpha=0.60, beta=4)
    canvas = Canvas.for_display(img, mirror)
    scene = canvas.roi(roi)
    w, h = roi.w, roi.h

    def px(p):
        return round(p[0] * w), round(p[1] * h)

    if body is None:
        left, right, top, bottom = 0.35, 0.65, 0.18, 0.94
    else:
        left, right = body.left - 0.025, body.right + 0.025
        top, bottom = max(0.04, body.shoulder_y - 0.16), min(0.98, body.hip_y + 0.04)
    guide = (202, 185, 132)
    for x, sign_x in ((left, 1), (right, -1)):
        for y, sign_y in ((top, 1), (bottom, -1)):
            scene.line(px((x, y)), px((x + 0.035 * sign_x, y)), guide, 2, cv2.LINE_AA)
            scene.line(px((x, y)), px((x, y + 0.04 * sign_y)), guide, 2, cv2.LINE_AA)
    if registry is not None:
        for zone in registry:
            points = np.array([px(p) for p in zone.shape.points], np.int32)
            mapped = scene.points(points)
            x0, y0 = mapped.min(axis=0)
            x1, y1 = mapped.max(axis=0)
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w - 1, x1), min(h - 1, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            target_img = scene.image
            shadow = mapped + [0, 5]
            cv2.fillConvexPoly(target_img, shadow, (11, 12, 16), cv2.LINE_AA)
            cv2.fillConvexPoly(target_img, mapped, (72, 78, 87), cv2.LINE_AA)
            cv2.polylines(target_img, [mapped], True, (204, 204, 207), 2, cv2.LINE_AA)
            center = ((x0 + x1) // 2, (y0 + y1) // 2)
            axes = (max(1, (x1 - x0) // 2 - 4), max(1, (y1 - y0) // 2 - 4))
            mask = np.zeros((y1 - y0 + 1, x1 - x0 + 1), np.uint8)
            cv2.ellipse(mask, (center[0] - x0, center[1] - y0), axes, 0, 0, 360, 255, -1, cv2.LINE_AA)
            patch = target_img[y0 : y1 + 1, x0 : x1 + 1]
            texture = pad_texture(x1 - x0 + 1, y1 - y0 + 1, zone.zone_id in ("crash_ride", "hihat"))
            alpha = (mask / 255.0)[..., None]
            patch[:] = (patch * (1 - alpha) + texture * alpha).astype(np.uint8)
            cv2.ellipse(target_img, center, axes, 0, 0, 360, (229, 222, 209), 1, cv2.LINE_AA)
            if zone.zone_id in ("crash_ride", "hihat"):
                cv2.ellipse(
                    target_img,
                    center,
                    (max(2, axes[0] // 5), max(2, axes[1] // 4)),
                    0,
                    0,
                    360,
                    (137, 179, 210),
                    -1,
                    cv2.LINE_AA,
                )
                cv2.circle(target_img, center, 2, (44, 49, 61), -1, cv2.LINE_AA)
            else:
                for dx in (-axes[0], axes[0]):
                    cv2.circle(target_img, (center[0] + dx, center[1]), 2, (242, 242, 244), -1)
            if zone.zone_id == target:
                cv2.polylines(target_img, [mapped], True, (239, 218, 134), 2, cv2.LINE_AA)
            label = zone.name.upper()
            font = 0.30 if len(label) > 10 else 0.36
            tw = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font, 1)[0][0]
            cv2.putText(
                target_img,
                label,
                (center[0] - tw // 2, min(h - 4, y1 + 15)),
                cv2.FONT_HERSHEY_SIMPLEX,
                font,
                (235, 237, 240),
                1,
                cv2.LINE_AA,
            )
    for stick in sticks:
        if stick.present and stick.axis_origin and stick.tip:
            a, b = px(stick.axis_origin), px(stick.tip)
            scene.line(a, b, (51, 68, 83), 6, cv2.LINE_AA)
            scene.line(a, b, (145, 194, 225), 3, cv2.LINE_AA)
            scene.circle(b, 3, (184, 217, 239), -1, cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (img.shape[1], 48), (20, 23, 31), -1)
    cv2.putText(img, "SPACE DRUMS", (19, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (233, 236, 239), 1, cv2.LINE_AA)
    cv2.putText(
        img,
        "R  recalibrate     Esc  close",
        (img.shape[1] - 222, 29),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.36,
        (161, 173, 185),
        1,
        cv2.LINE_AA,
    )
    if message:
        font = min(
            0.45, (img.shape[1] - 24) / max(1, cv2.getTextSize(message, cv2.FONT_HERSHEY_SIMPLEX, 1, 1)[0][0])
        )
        cv2.rectangle(img, (0, img.shape[0] - 32), (img.shape[1], img.shape[0]), (20, 23, 31), -1)
        cv2.putText(
            img,
            message,
            (12, img.shape[0] - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            font,
            (233, 236, 239),
            1,
            cv2.LINE_AA,
        )
    return img
