"""Developer layout preview for the full-kit demo: see and nudge the kit where you actually stand.

Draws pad coordinates, each hand's measured fingertip reach (p5-p95 box) and per-pad hit counts on
top of the :class:`~spacedrums.ui.stage.StageRenderer` image. Keys shift (``i k j l``) or scale
(``[`` ``]``) the whole kit in the mirrored display, ``s`` saves it. A nudge is only accepted when the
caller's ``validate`` (product pad/gap floors, ROI, overlap) passes; nothing here emits a strike.
Evidence and zones stay in camera ROI space everywhere else; ``StageRenderer.to_display`` maps them.
"""

from __future__ import annotations

from collections import Counter, deque

import cv2
import numpy as np

from spacedrums.contracts import HandId
from spacedrums.geometry.kit_layout import kit_layout, save_pads, transform_pads
from spacedrums.ui.stage import AA, FONT, MUTED, TEXT
from spacedrums.ui.theme import DEFAULT_THEME

STEP, SCALE_STEP = 0.01, 0.03
KEYS = {ord("i"): (0.0, -STEP, 1.0), ord("k"): (0.0, STEP, 1.0), ord("j"): (-STEP, 0.0, 1.0),
        ord("l"): (STEP, 0.0, 1.0), ord("["): (0.0, 0.0, 1 - SCALE_STEP), ord("]"): (0.0, 0.0,
        1 + SCALE_STEP)}
HELP = "i/k up/down  j/l left/right  [ ] smaller/larger  s save"
MAX_TIPS = 6000


def reach_report(pads, tips_display, *, lead: float = 0.10) -> dict[str, dict]:
    """Per pad: measured fingertip samples above its top edge (within ``lead``) and inside it.

    ``tips_display`` are (x, y) points in mirrored-display ROI units. A pad is ``reached`` only when
    the finger was measured both above the top edge and inside the pad, inside the pad's x span.
    """
    pts = np.asarray(tips_display, float).reshape(-1, 2)
    out = {}
    for p in pads:
        x0, x1 = p["x"] - p["width"] / 2, p["x"] + p["width"] / 2
        col = pts[(pts[:, 0] >= x0) & (pts[:, 0] <= x1)] if len(pts) else pts
        above = int(((col[:, 1] >= p["y"] - lead) & (col[:, 1] < p["y"])).sum()) if len(col) else 0
        inside = int(((col[:, 1] >= p["y"]) & (col[:, 1] <= p["y"] + p["height"])).sum()) if len(col) else 0
        out[p["zone_id"]] = {"above": above, "inside": inside, "reached": above > 0 and inside > 0}
    return out


class LayoutPreview:
    def __init__(self, pads, validate, *, save_dir=None):
        """``validate(pads)`` raises ValueError for a layout the product floors reject."""
        self.pads = [dict(p) for p in pads]
        self.validate = validate
        self.save_dir = save_dir
        self.tips = {h: deque(maxlen=MAX_TIPS) for h in HandId}  # camera ROI-normalised, layout independent
        self.hits: Counter = Counter()
        self.message = HELP

    def observe(self, evidence, result) -> None:
        for hand, e in evidence.items():
            if e.kind == "MEASURED" and e.tip is not None:
                self.tips[hand].append(tuple(e.tip))
        if result is not None:
            self.hits.update(c.zone_id for c in result.commits)

    def display_tips(self, hand) -> np.ndarray:
        """Tips in mirrored-display ROI units (x flipped; the preview uses the full-frame ROI)."""
        a = np.asarray(self.tips[hand], float).reshape(-1, 2)
        return np.column_stack((1 - a[:, 0], a[:, 1])) if len(a) else a

    def handle_key(self, key: int):
        """Return a new valid pads list when ``key`` moved the kit, else ``None`` (message explains)."""
        if key == ord("s"):
            self.save()
            return None
        if key not in KEYS:
            return None
        dx, dy, scale = KEYS[key]
        try:
            candidate = transform_pads(self.pads, dx, dy, scale)
            kit_layout(candidate)  # ROI + overlap
            self.validate(candidate)  # product floors
        except ValueError as exc:
            self.message = f"REJECTED: {exc}"
            return None
        self.pads = candidate
        self.message = HELP
        return candidate

    def save(self):
        if self.save_dir is None:
            self.message = "No output directory to save into"
            return None
        path = self.save_dir / "kit-layout.yaml"
        save_pads(path, self.pads, note="load with: --demo --kit full --kit-layout <this file>")
        self.message = f"Saved {path}"
        return path

    def draw(self, img, renderer, roi, frame_w) -> None:
        """Overlay on the already-rendered stage image."""
        for hand in HandId:
            if not len(self.tips[hand]):
                continue
            pts = np.array([renderer.to_display(t, roi, frame_w) for t in self.tips[hand]])
            color = DEFAULT_THEME.left if hand is HandId.LEFT else DEFAULT_THEME.right
            (x0, y0), (x1, y1) = np.percentile(pts, 5, axis=0), np.percentile(pts, 95, axis=0)
            cv2.rectangle(img, (round(x0), round(y0)), (round(x1), round(y1)), color, 1, AA)
            for x, y in pts[-400::4]:
                cv2.circle(img, (round(x), round(y)), 1, color, -1)
        report = reach_report(self.pads, np.vstack([self.display_tips(h) for h in HandId]))
        for p in self.pads:
            pad = renderer.pads.get(p["zone_id"])
            if pad is None:
                continue
            r = report[p["zone_id"]]
            text = f"{p['x']:.2f},{p['y']:.2f} {round(p['width'] * roi.w)}x{round(p['height'] * roi.h)}px"
            text += f" n={self.hits[p['zone_id']]}"
            ok = r["reached"] or not any(len(t) for t in self.tips.values())
            cv2.putText(img, text, (pad.x, max(70, pad.y - 6)), FONT, 0.38, TEXT if ok else (80, 80, 255), 1,
                AA)
        h, w = img.shape[:2]
        cv2.rectangle(img, (0, h - 56), (w, h - 28), (20, 23, 31), -1)
        cv2.putText(img, self.message[:120], (14, h - 36), FONT, 0.45,
            MUTED if self.message == HELP else TEXT, 1, AA)


__all__ = ["LayoutPreview", "reach_report"]
