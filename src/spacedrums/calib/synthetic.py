"""SYNTHETIC wizard actor (Phase 14 self-tests). **Everything here is synthetic - never evidence.**

A scripted, seeded "user" that reacts to the wizard like a cooperative developer would: stands in
the band, sweeps both hands across it, holds the sticks still (true per-hand stick lengths known to
the script), sweeps the tips over a scripted reach box and strikes each cued zone. It emits the same
records the live runner builds from the camera (``FrameSample``, per-hand ``HandObservation`` /
``StickObservation`` and the Phase 03 axis support as :class:`~spacedrums.calib.steps.StickSample`),
so the wizard, the Arm-A pipeline and the save/load path run unchanged. It exists to exercise the
machinery deterministically; its numbers say nothing about real users (integrity I-4).

Validation strikes: one downward stroke per cue, crossing the cued zone's impact surface at the
middle of the cue window (constant acceleration from rest, symmetric rebound). The striking hand is
the one on the zone's side of the ROI; when it changes zone it is briefly occluded (absent frames)
and re-appears above the next zone, so no stroke is ever fabricated across other zones.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from spacedrums.calib.steps import HANDS, StickSample
from spacedrums.calib.wizard import CalibrationWizard, Stage, Step
from spacedrums.contracts import (
    FrameSample,
    HandId,
    HandObservation,
    ImageRef,
    StickObservation,
    TimestampSource,
    TipMethod,
)
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.zones import surface_midpoint

DETECTOR_ID = "synthetic-calibration-actor"
Observations = dict[HandId, tuple[HandObservation, StickObservation]]
Sticks = dict[HandId, StickSample]
LABEL = "SYNTHETIC"


@dataclass
class SyntheticUser:
    """Scripted actor. ``l_true`` (ROI-height units) and ``reach_box`` are its hidden 'body'."""

    cfg: Mapping[str, Any]
    seed: int = 0
    noise: float = 0.0  # Gaussian noise on tip positions (ROI units)
    support_noise: float = 0.0  # Gaussian noise on the measured stick support (ROI-height units)
    l_true: Mapping[str, float] = field(default_factory=lambda: {"LEFT": 0.29, "RIGHT": 0.26})
    reach_box: Sequence[float] = (0.10, 0.24, 0.90, 0.80)  # x0, y0, x1, y1 of the tip sweep
    span_px: float = 30.0  # hand span (Task 03.3) the landmarks are drawn with
    presence: float = 1.0  # probability a hand is detected in a frame (< 1: tracking trouble)
    dt: float = 1.0 / 30.0
    t0: float = 100.0
    camera_profile_id: str | None = None  # default: the config's (a different id -> mismatch test)
    roi_mean_gray: float = 120.0
    strike_height: float = 0.08
    strike_depth: float = 0.04
    t_down: float = 0.20

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.k = 0
        self.roi = [int(v) for v in self.cfg["roi"]["px"]]
        self.frame_size = [int(v) for v in self.cfg["camera_profile"]["resolution_px"]]
        self.profile = self.camera_profile_id or self.cfg["camera_profile"]["profile_id"]
        self.hand_zone: dict[HandId, str | None] = {h: None for h in HANDS}  # target zone or 'rest'
        self.hidden_until: dict[HandId, float] = {h: -1.0 for h in HANDS}
        self._collector: Any = None
        self._registry: ZoneRegistry | None = None

    # ------------------------------------------------------------------ poses
    @staticmethod
    def rest(hand: HandId) -> tuple[float, float]:
        return (0.05, 0.95) if hand is HandId.LEFT else (0.95, 0.95)

    def _tips(self, wizard: CalibrationWizard, t: float) -> dict[HandId, tuple[float, float] | None]:
        step, stage = wizard.step, wizard.stage
        rel = t - self.t0
        if step is Step.PLAYING_AREA:
            w = 2.0 * math.pi / 2.5
            wx = {
                HandId.LEFT: 0.35 + 0.30 * math.sin(w * rel),
                HandId.RIGHT: 0.65 + 0.30 * math.sin(w * rel + 1.0),
            }
            return {h: (wx[h], 0.60 - 0.02 - float(self.l_true[str(h)])) for h in HANDS}
        if step is Step.STICK_PRIOR:
            grip = {HandId.LEFT: (0.35, 0.62), HandId.RIGHT: (0.65, 0.62)}
            return {h: (grip[h][0], grip[h][1] - float(self.l_true[str(h)])) for h in HANDS}
        if step is Step.ZONE_PLACEMENT and stage in (Stage.COUNTDOWN, Stage.COLLECT):
            x0, y0, x1, y1 = self.reach_box
            w = 0.6 * (x1 - x0)
            out = {}
            for i, h in enumerate(HANDS):
                u = 0.5 + 0.5 * math.sin(2 * math.pi * 0.37 * rel + 1.3 * i)
                v = 0.5 + 0.5 * math.sin(2 * math.pi * 0.23 * rel + 0.7 * i)
                left = x0 if h is HandId.LEFT else x1 - w
                out[h] = (left + w * u, y0 + (y1 - y0) * v)
            return out
        if step is Step.VALIDATION and stage is Stage.COLLECT and wizard.collector is not None:
            return self._strike_tips(wizard, t)
        if step in (Step.CAMERA_CHECK, Step.PLAYING_AREA, Step.STICK_PRIOR, Step.ZONE_PLACEMENT):
            grip = {HandId.LEFT: (0.35, 0.62), HandId.RIGHT: (0.65, 0.62)}
            return {h: (grip[h][0], grip[h][1] - float(self.l_true[str(h)])) for h in HANDS}
        return {h: self.rest(h) for h in HANDS}

    def _strike_tips(self, wizard: CalibrationWizard, t: float) -> dict[HandId, tuple[float, float] | None]:
        if wizard.collector is not self._collector:
            self._collector = wizard.collector
            self._registry = ZoneRegistry.from_config(wizard.required_zones())
        cue = wizard.collector.schedule.at(t)
        target: dict[HandId, str] = {h: "rest" for h in HANDS}
        surface = None
        if cue is not None:
            surface = surface_midpoint(self._registry[cue.zone_id].impact_surface)
            target[HandId.LEFT if surface[0] < 0.5 else HandId.RIGHT] = cue.zone_id
        out: dict[HandId, tuple[float, float] | None] = {}
        for h in HANDS:
            if self.hand_zone[h] != target[h]:
                if self.hand_zone[h] is not None:  # moving hands are occluded: no stroke across other zones
                    self.hidden_until[h] = t + 0.2
                self.hand_zone[h] = target[h]
            if t < self.hidden_until[h]:
                out[h] = None
            elif target[h] == "rest" or surface is None or cue is None:
                out[h] = self.rest(h)
            else:
                out[h] = self._stroke(surface, cue, t)
        return out

    def _stroke(self, surface: tuple[float, float], cue: Any, t: float) -> tuple[float, float]:
        xs, ys = surface
        y_top, y_bottom = ys - self.strike_height, ys + self.strike_depth
        a = 2.0 * (y_bottom - y_top) / self.t_down**2
        t_cross = 0.5 * (cue.t0 + cue.t1)
        t_start = t_cross - math.sqrt(2.0 * self.strike_height / a)
        if t <= t_start:
            y = y_top
        elif t <= t_start + self.t_down:
            y = y_top + 0.5 * a * (t - t_start) ** 2
        elif t <= t_start + 2 * self.t_down:
            y = y_top + 0.5 * a * (t_start + 2 * self.t_down - t) ** 2
        else:
            y = y_top
        return (xs, y)

    # ------------------------------------------------------------------ records
    def _hand(self, k: int, t: float, hand: HandId, wrist: tuple[float, float]) -> HandObservation:
        wx, wy = wrist
        sy = self.span_px / self.roi[3]
        sx = 0.35 * self.span_px / self.roi[2]
        lm = [(wx + (i % 5 - 2) * sx * 0.5, wy - sy * (0.4 + 0.15 * (i // 5))) for i in range(21)]
        lm[0] = (wx, wy)  # wrist
        lm[9] = (wx, wy - sy)  # middle MCP: wrist -> middle MCP = span
        lm[5] = (wx - sx, wy - 0.95 * sy)  # index MCP
        lm[17] = (wx + sx, wy - 0.85 * sy)  # pinky MCP
        xs = [p[0] for p in lm]
        ys = [p[1] for p in lm]
        return HandObservation(
            frame_id=k,
            t_capture=t,
            hand_id=hand,
            present=True,
            detector_id=DETECTOR_ID,
            landmarks=tuple(lm),
            landmark_visibility=None,
            handedness_score=0.95,
            bbox=(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)),
        )

    def frame(self, wizard: CalibrationWizard) -> tuple[FrameSample, Observations, Sticks, float]:
        """Next SYNTHETIC frame: (sample, observations, stick samples, ROI mean gray)."""
        k = self.k
        self.k += 1
        t = self.t0 + k * self.dt
        tips = self._tips(wizard, t)
        obs: dict[HandId, tuple[HandObservation, StickObservation]] = {}
        sticks: dict[HandId, StickSample] = {}
        for h in HANDS:
            tip = tips[h]
            present = tip is not None and (self.presence >= 1.0 or float(self.rng.random()) < self.presence)
            if not present:
                obs[h] = (
                    HandObservation.absent(k, t, h, DETECTOR_ID),
                    StickObservation.absent(k, t, h, TipMethod.GEOM),
                )
                sticks[h] = StickSample(None, 0.0)
                continue
            assert tip is not None
            if self.noise:
                dx, dy = (float(v) for v in self.rng.normal(0, self.noise, 2))
                tip = (tip[0] + dx, tip[1] + dy)
            length = float(self.l_true[str(h)])
            if wizard.step in (Step.PLAYING_AREA, Step.STICK_PRIOR, Step.CAMERA_CHECK):
                wrist = (tip[0], tip[1] + length + 0.02)
            else:
                wrist = (tip[0], min(0.97, tip[1] + 0.15))
            grip = (wrist[0], wrist[1] - 0.02)
            d = (tip[0] - grip[0], tip[1] - grip[1])
            n = math.hypot(*d)
            if n < 1e-6:  # tip at the grip (rest pose at the ROI edge): point the stick up
                d, n = (0.0, -1.0), 1.0
            stick = StickObservation(
                frame_id=k,
                t_capture=t,
                hand_id=h,
                present=True,
                method_id=TipMethod.GEOM,
                axis_origin=grip,
                axis_dir=(d[0] / n, d[1] / n),
                tip=tip,
                tip_confidence=0.9,
                axis_confidence=0.85,
                stick_length_est=length,
            )
            obs[h] = (self._hand(k, t, h, wrist), stick)
            support = length + (float(self.rng.normal(0, self.support_noise)) if self.support_noise else 0.0)
            sticks[h] = StickSample(support, 0.85)
        sample = FrameSample(
            frame_id=k,
            t_capture=t,
            t_frame_available=t + 0.004,
            timestamp_source=TimestampSource.REPLAY,
            frame_size_px=tuple(self.frame_size),
            roi_px=tuple(self.roi),
            image_ref=ImageRef.memory(None),
            camera_profile_id=self.profile,
            dropped_since_last=0,
        )
        return sample, obs, sticks, self.roi_mean_gray


__all__ = ["DETECTOR_ID", "LABEL", "SyntheticUser"]
