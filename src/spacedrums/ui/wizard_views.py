"""Calibration Wizard views (Phase 14, Tasks 14.2-14.5 UI; REQ-019 / REQ-057; layer L7).

Pure drawing from a plain :class:`WizardView`. ``spacedrums.app.calibrate`` builds it from the
wizard's view model; the UI never imports ``spacedrums.calib`` (sibling L7 packages are independent,
architecture.md section 2.2). Coordinates follow ADR-0005 (ROI-normalized, y down); the zone overlay
reuses the Phase 04 ``draw_zones`` and the stand-here box/band reuse the Phase 02 ``draw_guide``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from spacedrums.capture.roi import Roi
from spacedrums.geometry import Ellipse, ZoneRegistry
from spacedrums.ui.guide import DEFAULT_INSTRUCTION, GuideStyle, draw_guide
from spacedrums.ui.zones import draw_zones


@dataclass(frozen=True)
class WizardView:
    step_number: int
    n_steps: int
    title: str
    stage: str
    lines: tuple[str, ...] = ()
    keys: str = ""
    progress: float | None = None
    ok: bool | None = None  # REVIEW outcome: True pass, False check failed, None not reviewed
    band: tuple[float, float] | None = None  # stand-here band (playing-area step)
    envelope: tuple[float, float, float, float] | None = None  # reach envelope x0, y0, x1, y1
    registry: ZoneRegistry | None = None
    highlight_zone: str | None = None
    status_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class WizardStyle:
    font: int = cv2.FONT_HERSHEY_SIMPLEX
    title_scale: float = 0.62
    text_scale: float = 0.48
    panel_alpha: float = 0.65
    ok_color: tuple[int, int, int] = (60, 220, 60)
    fail_color: tuple[int, int, int] = (40, 80, 255)
    text_color: tuple[int, int, int] = (240, 240, 240)
    highlight_color: tuple[int, int, int] = (0, 255, 255)
    envelope_color: tuple[int, int, int] = (255, 200, 0)
    bar_color: tuple[int, int, int] = (0, 200, 255)


DEFAULT_STYLE = WizardStyle()


def _px(p: tuple[float, float], roi: Roi) -> tuple[int, int]:
    return (int(round(roi.x + p[0] * (roi.w - 1))), int(round(roi.y + p[1] * (roi.h - 1))))


def _highlight(
    img: np.ndarray, roi: Roi, registry: ZoneRegistry, zone_id: str, color: tuple[int, int, int]
) -> None:
    try:
        zone = registry[zone_id]
    except KeyError:
        return
    overlay = img.copy()
    if isinstance(zone.shape, Ellipse):
        axes = (max(1, round(zone.shape.rx * roi.w)), max(1, round(zone.shape.ry * roi.h)))
        cv2.ellipse(
            overlay,
            _px(zone.shape.center, roi),
            axes,
            float(np.degrees(zone.shape.angle_rad)),
            0,
            360,
            color,
            -1,
            cv2.LINE_AA,
        )
    else:
        pts = np.asarray([_px(p, roi) for p in zone.shape.points], np.int32)
        cv2.fillPoly(overlay, [pts], color, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.35, img, 0.65, 0, dst=img)


def _panel(
    img: np.ndarray, lines: list[tuple[str, float, tuple[int, int, int]]], top: int, style: WizardStyle
) -> int:
    """Translucent text panel from ``top``; returns the next free y."""
    if not lines:
        return top
    h, w = img.shape[:2]
    sizes = [cv2.getTextSize(text, style.font, scale, 1)[0] for text, scale, _ in lines]
    height = sum(s[1] + 10 for s in sizes) + 10
    y0, y1 = top, min(h, top + height)
    region = img[y0:y1, 0:w]
    region[:] = (region.astype(np.float32) * (1 - style.panel_alpha)).astype(np.uint8)
    y = top + 8
    for (text, scale, color), (_tw, th) in zip(lines, sizes, strict=True):
        y += th
        cv2.putText(img, text, (10, y), style.font, scale, color, 1, cv2.LINE_AA)
        y += 10
    return y1


def draw_wizard(
    frame: np.ndarray | None,
    roi: Roi,
    view: WizardView,
    *,
    style: WizardStyle | None = None,
    frame_size: tuple[int, int] | None = None,
) -> np.ndarray:
    """Draw one wizard frame: stand-here box (+ band), zones (+ cue highlight), reach envelope,
    header with step/instructions, progress bar and key hints. Never mutates ``frame``."""
    style = style or DEFAULT_STYLE
    if frame is None:
        w, h = frame_size or (roi.x1 + roi.x, roi.y1 + roi.y)
        frame = np.zeros((h, w, 3), np.uint8)
    img = draw_guide(
        frame,
        roi,
        band=view.band,
        instruction="",
        style=GuideStyle(dim_alpha=0.45 if view.band is not None else 0.25),
    )
    if view.registry is not None:
        crop = img[roi.y : roi.y1, roi.x : roi.x1]
        img[roi.y : roi.y1, roi.x : roi.x1] = draw_zones(crop, view.registry)
        if view.highlight_zone:
            _highlight(img, roi, view.registry, view.highlight_zone, style.highlight_color)
    if view.envelope is not None:
        x0, y0, x1, y1 = view.envelope
        cv2.rectangle(img, _px((x0, y0), roi), _px((x1, y1), roi), style.envelope_color, 2, cv2.LINE_AA)
        cv2.putText(
            img, "reach envelope", _px((x0, y0), roi), style.font, 0.45, style.envelope_color, 1, cv2.LINE_AA
        )
    color = style.text_color if view.ok is None else (style.ok_color if view.ok else style.fail_color)
    header = [
        (
            f"Calibration {view.step_number}/{view.n_steps} - {view.title} [{view.stage}]",
            style.title_scale,
            color,
        )
    ]
    header += [(line, style.text_scale, style.text_color) for line in view.lines]
    y = _panel(img, header, 0, style)
    if view.progress is not None:
        w = img.shape[1]
        cv2.rectangle(img, (10, y + 4), (w - 10, y + 14), (90, 90, 90), 1)
        cv2.rectangle(img, (10, y + 4), (10 + int((w - 20) * view.progress), y + 14), style.bar_color, -1)
    footer = [(view.keys, style.text_scale, style.text_color)] if view.keys else []
    footer += [(line, 0.42, (200, 200, 200)) for line in view.status_lines]
    if footer:
        sizes = sum(cv2.getTextSize(t, style.font, s, 1)[0][1] + 10 for t, s, _ in footer) + 10
        _panel(img, footer, img.shape[0] - sizes, style)
    return img


PLAYING_AREA_INSTRUCTION = DEFAULT_INSTRUCTION

__all__ = ["PLAYING_AREA_INSTRUCTION", "WizardStyle", "WizardView", "draw_wizard"]
