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
from spacedrums.contracts import (
    CommittedStrike,
    HandId,
    HandObservation,
    StickObservation,
    StrikeCandidate,
    TipMethod,
    TrackState,
    TrackStatus,
    TrajectoryPrediction,
)
from spacedrums.ui.theme import DEFAULT_THEME, arm_color

HAND_COLOR = {HandId.LEFT: (0, 200, 255), HandId.RIGHT: (255, 120, 0)}  # BGR
TIP_COLOR = {
    TipMethod.GEOM: (0, 0, 255),
    TipMethod.AXIS_REFINED: (255, 0, 255),
    TipMethod.MARKER: (0, 200, 0),
}
STATUS_COLOR = {
    TrackStatus.VALID: (0, 220, 0),
    TrackStatus.DEGRADED: (0, 200, 255),
    TrackStatus.INVALID: (0, 0, 255),
    TrackStatus.STALE: (128, 128, 128),
}


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
    show_filtered_tip: bool = True
    show_velocity: bool = True
    show_tracking_badge: bool = True
    show_roi: bool = True


DEFAULT_STYLE = OverlayStyle()


@dataclass(frozen=True)
class OverlayConfig:
    """Individually toggleable Phase 15 elements.

    ``experiment`` intentionally keeps only the items needed to verify the active arm,
    tracking safety, target and capture/audio health during timed experiments.
    """

    landmarks: bool = True
    search_region: bool = True
    candidate_pixels: bool = True
    stick_axis: bool = True
    raw_tip: bool = True
    filtered_tip: bool = True
    velocity: bool = True
    tracking_badge: bool = True
    trajectories: bool = True
    crossing: bool = True
    zone_highlight: bool = True
    tti: bool = True
    intensity: bool = True
    probability: bool = True
    decisions: bool = True
    zones: bool = True
    roi: bool = True
    runtime_status: bool = True
    ground_truth: bool = True

    @classmethod
    def off(cls) -> OverlayConfig:
        return cls(**{name: False for name in cls.__dataclass_fields__})

    @classmethod
    def experiment(cls) -> OverlayConfig:
        return cls(
            landmarks=False,
            search_region=False,
            candidate_pixels=False,
            stick_axis=False,
            raw_tip=False,
            filtered_tip=True,
            velocity=False,
            tracking_badge=True,
            trajectories=False,
            crossing=True,
            zone_highlight=True,
            tti=True,
            intensity=False,
            probability=False,
            decisions=True,
            zones=True,
            roi=False,
            runtime_status=True,
            ground_truth=False,
        )

    @classmethod
    def for_mode(cls, mode: str) -> OverlayConfig:
        if mode == "off":
            return cls.off()
        if mode == "experiment":
            return cls.experiment()
        if mode == "full":
            return cls()
        raise ValueError("overlay mode must be off, experiment or full")


@dataclass(frozen=True)
class RuntimeStats:
    active_arm: str
    fallback_status: str | None = None
    capture_fps: float | None = None
    capture_drops: int = 0
    audio_underruns: int = 0
    ui_drops: int = 0


@dataclass(frozen=True)
class OverlayRecords:
    predictions: tuple[tuple[str, TrajectoryPrediction], ...] = ()
    candidates: tuple[StrikeCandidate, ...] = ()
    commits: tuple[CommittedStrike, ...] = ()
    decisions: tuple[dict[str, Any], ...] = ()
    ground_truth: tuple[dict[str, Any], ...] = ()
    runtime: RuntimeStats | None = None


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
    cv2.putText(
        img,
        f"{obs.hand_id.value} {obs.handedness_score:.2f}",
        _pt(obs.bbox[0], obs.bbox[1], roi),
        style.font,
        style.text_scale,
        col,
        1,
    )


def draw_stick(
    img: np.ndarray, analysis: Any, stick: StickObservation | None, roi: Roi, style: OverlayStyle
) -> None:
    """``analysis`` is a ``spacedrums.stick.StickAnalysis`` (duck-typed: ui reads, never imports stick)."""
    rx, ry = roi.x, roi.y
    if analysis is not None:
        if style.show_region and analysis.region is not None and not analysis.region.empty:
            poly = (analysis.region.polygon_px + [rx, ry]).astype(np.int32)
            cv2.polylines(img, [poly], True, (0, 255, 255), 1)
        if style.show_region and analysis.grip_px is not None:
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
    elif stick is not None and stick.present and style.show_axis:
        # The in-process support pixels are not recorded, but the axis and tip are.
        cv2.line(
            img,
            _pt(*stick.axis_origin, roi),
            _pt(*stick.tip, roi),
            (0, 255, 0),
            style.axis_thickness,
            cv2.LINE_AA,
        )
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
    txt = (
        f"{state.hand_id.value}: {state.status.value} c={state.confidence:.2f} fsv={state.frames_since_valid}"
    )
    if state.reset_reason is not None:
        txt += f" RESET:{state.reset_reason.value}"
    if style.show_tracking_badge:
        cv2.putText(img, txt, (roi.x + 6, roi.y + y), style.font, style.text_scale, col, 1)
    if style.show_track and state.tip_filtered is not None:
        p = _pt(state.tip_filtered[0], state.tip_filtered[1], roi)
        if style.show_filtered_tip:
            cv2.drawMarker(img, p, col, cv2.MARKER_CROSS, 12, 2)
        if style.show_velocity and state.tip_velocity is not None:
            vx, vy = state.tip_velocity
            q = _pt(
                state.tip_filtered[0] + vx * style.velocity_scale_s,
                state.tip_filtered[1] + vy * style.velocity_scale_s,
                roi,
            )
            cv2.arrowedLine(img, p, q, col, 2, tipLength=0.25)


def draw_debug_overlay(
    full: np.ndarray,
    roi: Roi,
    hands: dict[HandId, HandObservation] | None = None,
    analyses: dict[HandId, Any] | None = None,
    sticks: dict[HandId, StickObservation] | None = None,
    tracks: dict[HandId, TrackState] | None = None,
    title: str | None = None,
    style: OverlayStyle | None = None,
    copy: bool = True,
) -> np.ndarray:
    style = style or DEFAULT_STYLE
    img = full.copy() if copy else full
    if style.show_roi:
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


def _bar(
    image: np.ndarray, origin: tuple[int, int], value: float, color: tuple[int, int, int], label: str
) -> None:
    x, y = origin
    bounded = max(0.0, min(1.0, float(value)))
    cv2.rectangle(image, (x, y), (x + 92, y + 10), (80, 80, 84), 1)
    cv2.rectangle(image, (x + 1, y + 1), (x + 1 + round(90 * bounded), y + 9), color, -1)
    cv2.putText(image, label, (x, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.34, color, 1, cv2.LINE_AA)


def draw_scientific_overlay(
    full: np.ndarray,
    roi: Roi,
    *,
    config: OverlayConfig | None = None,
    hands: dict[HandId, HandObservation] | None = None,
    analyses: dict[HandId, Any] | None = None,
    sticks: dict[HandId, StickObservation] | None = None,
    tracks: dict[HandId, TrackState] | None = None,
    records: OverlayRecords | None = None,
    registry: Any = None,
) -> np.ndarray:
    """Render all scientific/debug quantities without mutating the input frame."""
    cfg = config or OverlayConfig()
    records = records or OverlayRecords()
    style = OverlayStyle(
        show_landmarks=cfg.landmarks,
        show_region=cfg.search_region,
        show_candidates=cfg.candidate_pixels,
        show_axis=cfg.stick_axis,
        show_tip=cfg.raw_tip,
        show_track=cfg.filtered_tip or cfg.velocity,
        show_filtered_tip=cfg.filtered_tip,
        show_velocity=cfg.velocity,
        show_tracking_badge=cfg.tracking_badge,
        show_roi=cfg.roi,
    )
    image = full.copy()
    if any(
        (
            cfg.landmarks,
            cfg.search_region,
            cfg.candidate_pixels,
            cfg.stick_axis,
            cfg.raw_tip,
            cfg.filtered_tip,
            cfg.velocity,
            cfg.tracking_badge,
            cfg.roi,
        )
    ):
        image = draw_debug_overlay(
            image,
            roi,
            hands=hands,
            analyses=analyses,
            sticks=sticks,
            tracks=tracks,
            style=style,
            copy=False,
        )
    if cfg.zones and registry is not None:
        from spacedrums.ui.zones import draw_zones

        draw_zones(image[roi.y : roi.y1, roi.x : roi.x1], registry, inplace=True)
    for arm, prediction in records.predictions:
        if not cfg.trajectories:
            break
        color = arm_color(arm)
        points = [_pt(x, y, roi) for x, y in prediction.positions]
        if len(points) > 1:
            cv2.polylines(image, [np.asarray(points, np.int32)], False, color, 2, cv2.LINE_AA)
        for point in points:
            cv2.circle(image, point, 2, color, -1)
    candidate_by_id = {c.candidate_id: c for c in records.candidates}
    y_text = roi.y + 72
    for candidate in records.candidates:
        point = _pt(*candidate.impact_position, roi)
        color = arm_color(
            "A" if str(candidate.source) == "REACTIVE" else "B" if str(candidate.source) == "RULE" else "C"
        )
        if cfg.crossing:
            cv2.drawMarker(image, point, color, cv2.MARKER_TILTED_CROSS, 16, 2, cv2.LINE_AA)
        if cfg.zone_highlight and registry is not None:
            zone = registry[candidate.zone_id]
            # A compact halo communicates the predicted target without redrawing a drum kit.
            cv2.circle(image, point, 21, color, 2, cv2.LINE_AA)
            cv2.putText(
                image,
                zone.name,
                (point[0] + 8, point[1] + 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.40,
                color,
                1,
                cv2.LINE_AA,
            )
        details: list[str] = []
        if cfg.tti and candidate.tti is not None:
            details.append(f"TTI {candidate.tti * 1000:.0f}ms")
        if cfg.probability and candidate.strike_probability is not None:
            details.append(f"p={candidate.strike_probability:.2f}")
        if details:
            cv2.putText(
                image,
                f"{candidate.hand_id} {candidate.zone_id} " + " ".join(details),
                (roi.x + 6, y_text),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                color,
                1,
                cv2.LINE_AA,
            )
            y_text += 17
        if cfg.intensity:
            _bar(
                image,
                (point[0] + 10, point[1] + 28),
                candidate.intensity_proxy,
                color,
                f"intensity {candidate.intensity_proxy:.2f}",
            )
    if cfg.decisions:
        for decision in records.decisions:
            candidate = candidate_by_id.get(str(decision.get("candidate_id", "")))
            if candidate is None:
                continue
            point = _pt(*candidate.impact_position, roi)
            reason = str(decision.get("decision", "UNKNOWN"))
            if reason != "COMMITTED":
                cv2.circle(image, point, 7, DEFAULT_THEME.error, 1, cv2.LINE_AA)
                cv2.putText(
                    image,
                    reason.removeprefix("REJECT_"),
                    (point[0] + 8, point[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.32,
                    DEFAULT_THEME.error,
                    1,
                    cv2.LINE_AA,
                )
    for commit in records.commits:
        candidate = candidate_by_id.get(commit.candidate_id)
        if candidate is not None and cfg.decisions:
            point = _pt(*candidate.impact_position, roi)
            cv2.circle(image, point, 25, DEFAULT_THEME.ok, 3, cv2.LINE_AA)
            cv2.putText(
                image,
                "COMMIT",
                (point[0] - 24, point[1] - 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                DEFAULT_THEME.ok,
                2,
                cv2.LINE_AA,
            )
    if cfg.ground_truth:
        for label in records.ground_truth:
            position = label.get("impact_position")
            if position is None:
                continue
            point = _pt(float(position[0]), float(position[1]), roi)
            status = label.get("match_status", "GT")
            cv2.drawMarker(image, point, DEFAULT_THEME.ground_truth, cv2.MARKER_STAR, 24, 2, cv2.LINE_AA)
            cv2.putText(
                image,
                f"GT {label.get('zone_id') or '-'} {status}",
                (point[0] + 9, point[1] - 9),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.40,
                DEFAULT_THEME.ground_truth,
                1,
                cv2.LINE_AA,
            )
    if cfg.runtime_status and records.runtime is not None:
        runtime = records.runtime
        fps = "n/a" if runtime.capture_fps is None else f"{runtime.capture_fps:.1f}"
        text = (
            f"arm {runtime.active_arm} | capture {fps} fps "
            f"drops {runtime.capture_drops} | audio underruns {runtime.audio_underruns} | "
            f"UI drops {runtime.ui_drops}"
        )
        if runtime.fallback_status:
            text += f" | FALLBACK {runtime.fallback_status}"
        cv2.rectangle(
            image, (0, image.shape[0] - 28), (image.shape[1], image.shape[0]), DEFAULT_THEME.background, -1
        )
        cv2.putText(
            image,
            text,
            (8, image.shape[0] - 9),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            DEFAULT_THEME.text,
            1,
            cv2.LINE_AA,
        )
    return image


__all__ = [
    "HAND_COLOR",
    "STATUS_COLOR",
    "TIP_COLOR",
    "OverlayConfig",
    "OverlayRecords",
    "OverlayStyle",
    "RuntimeStats",
    "draw_debug_overlay",
    "draw_hand",
    "draw_scientific_overlay",
    "draw_stick",
    "draw_track",
]
