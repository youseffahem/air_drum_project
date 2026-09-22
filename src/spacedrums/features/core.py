"""Bounded causal feature extraction; no clock, file, label, or dataset access."""

from __future__ import annotations

import math
from collections import defaultdict, deque

import numpy as np
from scipy.optimize import minimize_scalar

from spacedrums.features.schema import KinematicFeatures
from spacedrums.geometry.zones import Segment, surface_midpoint


def closest_surface_point(surface, tip):
    """Segment projection; finite elliptical arc minimization incl. endpoints.

    Bracket each local basin on a 32-interval grid before bounded minimization.
    This avoids the radial-angle approximation for eccentric ellipses.
    """
    if isinstance(surface, Segment):
        a, b, p = np.asarray(surface.p0), np.asarray(surface.p1), np.asarray(tip)
        d = b - a
        return a + np.clip(np.dot(p - a, d) / np.dot(d, d), 0, 1) * d
    start = surface.theta_start_rad
    span = (surface.theta_end_rad - start) % math.tau
    if span == 0:
        span = math.tau
    grid = np.linspace(start, start + span, 33)

    def loss(theta):
        p = surface.point_at(theta)
        return (p[0] - tip[0]) ** 2 + (p[1] - tip[1]) ** 2

    values = [loss(t) for t in grid]
    candidates = [(values[0], grid[0]), (values[-1], grid[-1])]
    for i in range(1, len(grid) - 1):
        if values[i] <= values[i - 1] and values[i] <= values[i + 1]:
            result = minimize_scalar(
                loss, bounds=(grid[i - 1], grid[i + 1]), method="bounded", options={"xatol": 1e-12}
            )
            candidates.append((result.fun, result.x))
    return np.asarray(surface.point_at(min(candidates)[1]))


def _acceleration(current, previous):
    if current.tip_acceleration is not None:
        return np.asarray(current.tip_acceleration)
    if previous is not None and current.t_capture > previous.t_capture:
        return (np.asarray(current.tip_velocity) - previous.tip_velocity) / (
            current.t_capture - previous.t_capture
        )

    return None


class FeatureCore:
    def __init__(self, schema):
        self.schema = schema
        self._history = defaultdict(lambda: deque(maxlen=2))
        self._last = {}

    def reset(self, hand_id=None):
        if hand_id is None:
            self._history.clear()
            self._last.clear()
        else:
            self._history.pop(str(hand_id), None)
            self._last.pop(str(hand_id), None)

    def update(self, track, *, hand=None, stick=None, frame=None):
        key = str(track.hand_id)
        last = self._last.get(key)
        if not math.isfinite(track.t_capture):
            raise ValueError("non-finite capture time")
        if last and (track.t_capture <= last.t_capture or track.frame_id <= last.frame_id):
            raise ValueError("per-hand frame ids and capture times must strictly increase")
        for obs in (hand, stick, frame):
            if obs is not None and (
                obs.frame_id != track.frame_id
                or obs.t_capture != track.t_capture
                or (hasattr(obs, "hand_id") and obs.hand_id != track.hand_id)
            ):
                raise ValueError("observations must belong to exactly the same frame and hand")
        dt = track.t_capture - last.t_capture if last else 0.0
        values = np.zeros(self.schema.dimension)
        mask = np.zeros(self.schema.dimension, dtype=bool)

        def put(name, value):
            if name in self.schema.index and value is not None:
                if not math.isfinite(float(value)):
                    raise ValueError(f"non-finite source for {name}")
                j = self.schema.index[name]
                values[j], mask[j] = value, True

        history = self._history[key]
        if track.reset_reason is not None:
            history.clear()
        if str(track.status) in ("INVALID", "STALE"):
            history.clear()
        else:
            previous = history[-1] if history else None
            tip, velocity = np.asarray(track.tip_filtered), np.asarray(track.tip_velocity)
            speed = float(np.linalg.norm(velocity))
            direction = velocity / speed if speed > self.schema.epsilon else None
            put("tip_x", tip[0])
            put("tip_y", tip[1])
            put("vx", velocity[0])
            put("vy", velocity[1])
            put("vertical_velocity", velocity[1])
            put("speed", speed)
            if direction is not None:
                put("direction_x", direction[0])
                put("direction_y", direction[1])
            acceleration = _acceleration(track, previous)
            if acceleration is not None:
                put("ax", acceleration[0])
                put("ay", acceleration[1])
                put("acceleration", np.linalg.norm(acceleration))
                if direction is not None:
                    put("acc_tangent", np.dot(acceleration, direction))
                    put("acc_normal", -direction[1] * acceleration[0] + direction[0] * acceleration[1])
                if previous is not None and "JERK" in self.schema.groups:
                    old_acc = _acceleration(previous, history[-2] if len(history) > 1 else None)
                    if old_acc is not None:
                        jerk = (acceleration - old_acc) / (track.t_capture - previous.t_capture)
                        put("jx", jerk[0])
                        put("jy", jerk[1])
                        put("jerk", np.linalg.norm(jerk))
            angle = track.axis_angle
            if angle is not None:
                put("axis_sin", math.sin(angle))
                put("axis_cos", math.cos(angle))
                omega = track.axis_angular_velocity
                if omega is None and previous is not None and previous.axis_angle is not None:
                    delta = math.atan2(
                        math.sin(angle - previous.axis_angle), math.cos(angle - previous.axis_angle)
                    )
                    omega = delta / (track.t_capture - previous.t_capture)
                put("axis_omega", omega)
            if stick is not None and stick.present:
                put("axis_confidence", stick.axis_confidence)
                put("stick_length", stick.stick_length_est)
            if hand is not None and hand.present:
                wrist = np.asarray(hand.landmarks[0])
                scale = np.linalg.norm(np.asarray(hand.landmarks[9]) - wrist)
                if scale > self.schema.epsilon:
                    for idx in (0, 5, 9, 4):
                        if hand.landmark_visibility is not None and any(
                            hand.landmark_visibility[k] <= 0 for k in (0, 9, idx)
                        ):
                            continue
                        point = (np.asarray(hand.landmarks[idx]) - wrist) / scale
                        put(f"landmark_{idx}_x", point[0])
                        put(f"landmark_{idx}_y", point[1])
                put("bbox_width", hand.bbox[2])
                put("bbox_height", hand.bbox[3])
                put("handedness_score", hand.handedness_score)
            for zone in self.schema.zones:
                rel = tip - surface_midpoint(zone.impact_surface)
                put(f"relative_{zone.zone_id}_x", rel[0])
                put(f"relative_{zone.zone_id}_y", rel[1])
                inward = float(np.dot(velocity, zone.inward_normal))
                put(f"inward_{zone.zone_id}", inward)
                if "ZONE" in self.schema.groups:
                    closest = closest_surface_point(zone.impact_surface, tip)
                    distance = float(np.dot(closest - tip, zone.inward_normal))
                    put(f"distance_{zone.zone_id}", distance)
                    put(
                        f"tts_{zone.zone_id}",
                        min(self.schema.tts_clip_s, max(0.0, distance / max(inward, self.schema.epsilon))),
                    )
            put("valid", str(track.status) == "VALID")
            put("degraded", str(track.status) == "DEGRADED")
            put("tip_confidence", track.confidence)
            put("frames_since_valid", track.frames_since_valid)
            put("dropped_since_last", frame.dropped_since_last if frame else None)
            if last:
                put("dt", dt)
            history.append(track)
        self._last[key] = track
        return KinematicFeatures(
            track.frame_id,
            track.t_capture,
            key,
            self.schema.feature_schema_id,
            tuple(values.tolist()),
            tuple(mask.tolist()),
            dt,
            str(track.status),
        )
