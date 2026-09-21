"""One deterministic trajectory-to-candidate implementation for all candidate sources."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import count

from spacedrums.contracts import (
    CandidateDerivation,
    CandidateSource,
    HandId,
    StrikeCandidate,
    TrackStatus,
    TrajectoryPrediction,
)
from spacedrums.geometry.impact import crossing_time, segment_surface
from spacedrums.geometry.zones import Point, Zone, ZoneRegistry
from spacedrums.timing import now


@dataclass(frozen=True)
class TrajectoryPoint:
    t: float
    position: Point


@dataclass(frozen=True)
class Impact:
    zone: Zone
    t_cross: float
    position: Point
    velocity: Point
    segment_index: int


def first_impact(trajectory: tuple[TrajectoryPoint, ...], zone: Zone, v_min: float) -> Impact | None:
    """First valid outside-to-inside impact; no samples outside this trajectory are consulted."""
    if len(trajectory) < 2:
        return None
    for i, (previous, current) in enumerate(zip(trajectory, trajectory[1:], strict=False), start=1):
        dt = current.t - previous.t
        if dt <= 0:
            raise ValueError("trajectory times must be strictly increasing")
        if zone.shape.contains(previous.position) or not zone.shape.contains(
            current.position, include_boundary=False
        ):
            continue
        crossing = segment_surface(previous.position, current.position, zone.impact_surface)
        if crossing is None or crossing.s <= 1e-9:
            continue
        velocity = (
            (current.position[0] - previous.position[0]) / dt,
            (current.position[1] - previous.position[1]) / dt,
        )
        inward_speed = velocity[0] * zone.inward_normal[0] + velocity[1] * zone.inward_normal[1]
        if inward_speed + 1e-12 < v_min:
            continue
        return Impact(zone, crossing_time(previous.t, current.t, crossing.s), crossing.point, velocity, i - 1)
    return None


class GeometryEngine:
    """Registry-bound geometry plus observed entry-episode state (not Phase 05 refractory)."""

    def __init__(self, registry: ZoneRegistry, *, v_min: float, session_id: str = "geometry") -> None:
        if v_min < 0:
            raise ValueError("v_min must be non-negative")
        self.registry = registry
        self.v_min = float(v_min)
        self.session_id = session_id
        self._previous: dict[HandId, TrajectoryPoint] = {}
        self._inside: dict[tuple[HandId, str], bool] = {}
        self._candidate_counter = count(1)
        self._episode_counter: dict[tuple[HandId, str], int] = {}

    def reset_hand(self, hand_id: HandId | str) -> None:
        hand = HandId(hand_id)
        self._previous.pop(hand, None)
        for zone in self.registry:
            self._inside[(hand, zone.zone_id)] = False

    def _candidate(
        self,
        impact: Impact,
        *,
        source: CandidateSource,
        frame_id: int,
        hand: HandId,
        t_capture: float,
        anticipator_id: str | None,
        strike_probability: float | None,
        intensity_proxy: float | None,
        t_candidate: float | None,
    ) -> StrikeCandidate:
        speed = math.hypot(*impact.velocity)
        predicted = source is not CandidateSource.REACTIVE
        return StrikeCandidate(
            candidate_id=f"{self.session_id}-{hand}-c{next(self._candidate_counter):06d}",
            frame_id=frame_id,
            t_capture=t_capture,
            hand_id=hand,
            zone_id=impact.zone.zone_id,
            source=source,
            derivation=CandidateDerivation.GEOMETRY,
            anticipator_id=anticipator_id if predicted else None,
            t_impact_pred=impact.t_cross if predicted else None,
            t_impact_est=None if predicted else impact.t_cross,
            tti=impact.t_cross - t_capture if predicted else None,
            impact_position=impact.position,
            crossing_velocity=impact.velocity,
            strike_probability=strike_probability,
            intensity_proxy=speed if intensity_proxy is None else float(intensity_proxy),
            t_candidate=now() if t_candidate is None else float(t_candidate),
        )

    def intersect(
        self,
        trajectory: tuple[TrajectoryPoint, ...],
        *,
        source: CandidateSource | str,
        frame_id: int,
        hand_id: HandId | str,
        t_capture: float,
        anticipator_id: str | None = None,
        strike_probability: float | None = None,
        intensity_proxy: float | None = None,
        t_candidate: float | None = None,
    ) -> StrikeCandidate | None:
        source, hand = CandidateSource(source), HandId(hand_id)
        impacts = [
            impact
            for zone in self.registry
            if hand in zone.allowed_hands
            if (impact := first_impact(trajectory, zone, self.v_min)) is not None
        ]
        if not impacts:
            return None
        impact = min(impacts, key=lambda item: (item.t_cross, item.zone.zone_id))
        return self._candidate(
            impact,
            source=source,
            frame_id=frame_id,
            hand=hand,
            t_capture=t_capture,
            anticipator_id=anticipator_id,
            strike_probability=strike_probability,
            intensity_proxy=intensity_proxy,
            t_candidate=t_candidate,
        )

    def intersect_prediction(
        self,
        prediction: TrajectoryPrediction,
        *,
        current_position: Point,
        strike_probability: float | None = None,
        t_candidate: float | None = None,
        source: CandidateSource | str = CandidateSource.RULE,
    ) -> StrikeCandidate | None:
        points = (TrajectoryPoint(prediction.t_capture, current_position),) + tuple(
            TrajectoryPoint(t, p)
            for t, p in zip(prediction.sample_times(), prediction.positions, strict=True)
        )
        probability = (
            prediction.aux.strike_prob_within_H if strike_probability is None else strike_probability
        )
        return self.intersect(
            points,
            source=source,
            frame_id=prediction.frame_id,
            hand_id=prediction.hand_id,
            t_capture=prediction.t_capture,
            anticipator_id=prediction.anticipator_id,
            strike_probability=probability,
            intensity_proxy=prediction.aux.intensity_proxy,
            t_candidate=prediction.t_inference_done if t_candidate is None else t_candidate,
        )

    def observe(
        self,
        *,
        frame_id: int,
        t_capture: float,
        hand_id: HandId | str,
        position: Point | None,
        status: TrackStatus | str,
        t_candidate: float | None = None,
    ) -> tuple[StrikeCandidate, ...]:
        hand, status = HandId(hand_id), TrackStatus(status)
        if status in (TrackStatus.INVALID, TrackStatus.STALE) or position is None:
            self.reset_hand(hand)
            return ()
        current = TrajectoryPoint(float(t_capture), (float(position[0]), float(position[1])))
        previous = self._previous.get(hand)
        self._previous[hand] = current
        candidates: list[StrikeCandidate] = []
        for zone in self.registry:
            if hand not in zone.allowed_hands:
                continue
            key = (hand, zone.zone_id)
            currently_inside = zone.shape.contains(current.position)
            episode_active = self._inside.get(key, False)
            self._inside[key] = currently_inside
            if (
                not currently_inside
                or episode_active
                or previous is None
                or zone.shape.contains(previous.position)
            ):
                continue
            impact = first_impact((previous, current), zone, self.v_min)
            if impact is None:
                continue
            self._episode_counter[key] = self._episode_counter.get(key, 0) + 1
            candidates.append(
                self._candidate(
                    impact,
                    source=CandidateSource.REACTIVE,
                    frame_id=frame_id,
                    hand=hand,
                    t_capture=t_capture,
                    anticipator_id=None,
                    strike_probability=None,
                    intensity_proxy=None,
                    t_candidate=t_candidate,
                )
            )
        return tuple(sorted(candidates, key=lambda c: (c.t_impact_est or 0.0, c.zone_id)))

    def episode_id(self, hand_id: HandId | str, zone_id: str) -> str | None:
        key = (HandId(hand_id), zone_id)
        n = self._episode_counter.get(key)
        return f"{self.session_id}-{key[0]}-{zone_id}-e{n:06d}" if n else None


__all__ = ["GeometryEngine", "Impact", "TrajectoryPoint", "first_impact"]
