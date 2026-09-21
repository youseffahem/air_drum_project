"""Minimal per-hand debug overlay (Phase 03, Task 03.15; the full dashboard is Phase 15).

Draws, on a copy of the full frame: hand landmarks (per hand colour), grip point + direction prior,
the stick search-region polygon, candidate pixels (sparse), the fitted axis with its support, the
tip coloured **by method** (``GEOM`` red, ``AXIS_REFINED`` magenta, ``MARKER`` green — MARKER is
additionally tagged *FALLBACK/BENCHMARK*, integrity I-7), the filtered tip and velocity vector, and
the tracking status per hand. Pure drawing; reads records and the in-process ``StickAnalysis``.
Coordinates go through the single ``norm_to_px`` helper (ADR-0005).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from spacedrums.capture.roi import Roi, norm_to_px, norm_to_px_point
from spacedrums.contracts import HandId, HandObservation, StickObservation, TipMethod, TrackState, TrackStatus

HAND_COLOR = {HandId.LEFT: (0, 200, 255), HandId.RIGHT: (255, 120, 0)}  # BGR
TIP_COLOR = {TipMethod.GEOM: (0, 0, 255), TipMethod.AXIS_REFINED: (255, 0, 255),
             TipMethod.MARKER: (0, 200, 0)}
STATUS_COLOR = {TrackStatus.VALID: (0, 220, 0), TrackStatus.DEGRADED: (0, 200, 255),
                TrackStatus.INVALID: (0, 0, 255), TrackStatus.STALE: (128, 128, 128)}


@dataclass(frozen=True)
class OverlayStyle:
    landmark_radius: int = 2
    axis_thickness: int = 2
    tip_radius: int = 5
    velocity_scale_s: float = 0.15  # seconds of motion the velocity arrow represents
    candidate_stride: int = 4
    font: int = cv2.FONT_HERSHEY_SIMPLEX
    text_scale: float = 0.45
    show_landmarks: bool = True
    show_region: bool = True
    show_candidates: bool = True
    show_axis: bool = True
    show_tip: bool = True
    show_track: bool = True


DEFAULT_STYLE = OverlayStyle()


def _pt(x: float, y: float, roi: Roi) -> tuple[int, int]:
    px, py = norm_to_px_point(x, y, roi)
    return int(round(px)), int(round(py))


def draw_hand(img: np.ndarray, obs: HandObservation, roi: Roi, style: OverlayStyle) -> None:
    if not obs.present or obs.landmarks is None or not style.show_landmarks:
        return
    col = HAND_COLOR[obs.hand_id]
    xs, ys = norm_to_px(np.array([p[0] for p in obs.landmarks]), np.array([p[1] for p in obs.landmarks]), roi)
    for x, y in zip(xs, ys, strict=True):
        cv2.circle(img, (int(round(x)), int(round(y))), style.landmark_radius, col, -1)
    cv2.putText(img, f"{obs.hand_id.value} {obs.handedness_score:.2f}", _pt(obs.bbox[0], obs.bbox[1], roi),
                style.font, style.text_scale, col, 1)


def draw_stick(img: np.ndarray, analysis: Any, stick: StickObservation | None, roi: Roi,
               style: OverlayStyle) -> None:
    """``analysis`` is a ``spacedrums.stick.StickAnalysis`` (duck-typed: ui reads, never imports stick)."""
    rx, ry = roi.x, roi.y
    if analysis is not None:
        if style.show_region and analysis.region is not None and not analysis.region.empty:
            poly = (analysis.region.polygon_px + [rx, ry]).astype(np.int32)
            cv2.polylines(img, [poly], True, (0, 255, 255), 1)
        if analysis.grip_px is not None:
            g = (int(analysis.grip_px[0] + rx), int(analysis.grip_px[1] + ry))
            cv2.circle(img, g, 4, (255, 255, 0), -1)
            if analysis.prior_dir_px is not None and analysis.region is not None:
                d = np.asarray(analysis.prior_dir_px) * 0.5 * analysis.region.span_px
                cv2.arrowedLine(img, g, (int(g[0] + d[0]), int(g[1] + d[1])), (255, 255, 0), 1, tipLength=0.3)
        if style.show_candidates and analysis.segment is not None and len(analysis.segment.candidate_px):
            for x, y in analysis.segment.candidate_px[:: style.candidate_stride]:
                cv2.circle(img, (int(x + rx), int(y + ry)), 1, (255, 0, 255), -1)
        if style.show_axis and analysis.axis is not None:
            o = np.asarray(analysis.axis.origin_px) + [rx, ry]
            f = np.asarray(analysis.axis.support_far_px) + [rx, ry]
            cv2.line(img, tuple(o.astype(int)), tuple(f.astype(int)), (0, 255, 0), style.axis_thickness)
    if stick is not None and stick.present and style.show_tip:
        col = TIP_COLOR[stick.method_id]
        cv2.circle(img, _pt(stick.tip[0], stick.tip[1], roi), style.tip_radius, col, 2)
        tag = f"{stick.method_id.value} {stick.tip_confidence:.2f}"
        if stick.method_id is TipMethod.MARKER:
            tag += " FALLBACK/BENCHMARK"
        p = _pt(stick.tip[0], stick.tip[1], roi)
        cv2.putText(img, tag, (p[0] + 8, p[1] - 6), style.font, style.text_scale, col, 1)


def draw_track(img: np.ndarray, state: TrackState, roi: Roi, style: OverlayStyle, row: int) -> None:
    col = STATUS_COLOR[state.status]
    y = 20 + 18 * row
    txt = (f"{state.hand_id.value}: {state.status.value} c={state.confidence:.2f} "
           f"fsv={state.frames_since_valid}")
    if state.reset_reason is not None:
        txt += f" RESET:{state.reset_reason.value}"
    cv2.putText(img, txt, (roi.x + 6, roi.y + y), style.font, style.text_scale, col, 1)
    if style.show_track and state.tip_filtered is not None:
        p = _pt(state.tip_filtered[0], state.tip_filtered[1], roi)
        cv2.drawMarker(img, p, col, cv2.MARKER_CROSS, 12, 2)
        if state.tip_velocity is not None:
            vx, vy = state.tip_velocity
            q = _pt(state.tip_filtered[0] + vx * style.velocity_scale_s,
                    state.tip_filtered[1] + vy * style.velocity_scale_s, roi)
            cv2.arrowedLine(img, p, q, col, 2, tipLength=0.25)


def draw_debug_overlay(full: np.ndarray, roi: Roi, hands: dict[HandId, HandObservation] | None = None,
                       analyses: dict[HandId, Any] | None = None,
                       sticks: dict[HandId, StickObservation] | None = None,
                       tracks: dict[HandId, TrackState] | None = None, title: str | None = None,
                       style: OverlayStyle | None = None) -> np.ndarray:
    style = style or DEFAULT_STYLE
    img = full.copy()
    cv2.rectangle(img, (roi.x, roi.y), (roi.x1, roi.y1), (200, 200, 200), 1)
    for hid in (HandId.LEFT, HandId.RIGHT):
        if hands and hid in hands:
            draw_hand(img, hands[hid], roi, style)
        draw_stick(img, (analyses or {}).get(hid), (sticks or {}).get(hid), roi, style)
    for row, hid in enumerate((HandId.LEFT, HandId.RIGHT)):
        if tracks and hid in tracks:
            draw_track(img, tracks[hid], roi, style, row)
    if title:
        cv2.putText(img, title, (8, full.shape[0] - 10), style.font, 0.5, (255, 255, 255), 1)
    return img


__all__ = ["HAND_COLOR", "STATUS_COLOR", "TIP_COLOR", "OverlayStyle", "draw_debug_overlay", "draw_hand",
           "draw_stick", "draw_track"]
