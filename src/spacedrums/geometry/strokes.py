"""Causal measured-stroke geometry for the four-pad product (ADR-0045).

Missing observations leave bounded measured history intact. They never advance
the stroke. A gap crossing needs a measured downward approach before the gap.
Rebound, not a long refractory timer, permits rapid repetitions. At most one
pad sounds per uninterrupted downstroke, including through both rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from spacedrums.contracts import CandidateSource, HandId, TrackStatus
from spacedrums.geometry.impact import crossing_time, segment_surface
from spacedrums.geometry.intersect import GeometryEngine, Impact, TrajectoryPoint


@dataclass(frozen=True)
class StrokeSettings:
    max_gap_s: float = 0.115  # up to two missing samples at nominal 30 Hz
    min_travel: float = 0.018
    rebound: float = 0.014
    downward_ratio: float = 0.5
    max_speed: float = 12.0
    # Look-ahead for a fast, sustained downstroke (seconds). 0 keeps strict observed crossings.
    lead_s: float = 0.0


class MeasuredStrokeGeometry(GeometryEngine):
    def __init__(self, registry, *, v_min, session_id="product", settings=None):
        super().__init__(registry, v_min=v_min, session_id=session_id)
        self.settings = settings or StrokeSettings()
        self.motion = {}
        self.diagnostics = {}

    def reset_hand(self, hand_id):
        super().reset_hand(hand_id)
        self.motion.pop(HandId(hand_id), None)
        self.diagnostics.pop(HandId(hand_id), None)

    def observe(self, *, frame_id, t_capture, hand_id, position, status, t_candidate=None):
        h, status = HandId(hand_id), TrackStatus(status)
        s = self.settings
        diagnostic = {"reason": "NO_MEASURED_TIP", "velocity": None, "travel": None}

        def no_strike(reason):
            diagnostic["reason"] = reason
            self.diagnostics[h] = diagnostic
            return ()

        m = self.motion.get(h)
        if m and t_capture <= m["last"].t:
            raise ValueError("stroke evidence must have increasing timestamps")
        if m and t_capture - m["last"].t > s.max_gap_s:
            self.reset_hand(h)
            m = None
        if status is not TrackStatus.VALID or position is None:
            if status in (TrackStatus.INVALID, TrackStatus.STALE):
                self.reset_hand(h)
            elif m:
                m["gap"] = True
            return no_strike("NO_MEASURED_TIP")
        current = TrajectoryPoint(t_capture, tuple(position))
        if m is None:
            self.motion[h] = {
                "last": current,
                "top": position[1],
                "bottom": position[1],
                "fired": False,
                "down": False,
                "gap": False,
            }
            return no_strike("NEED_RECENT_TRAJECTORY")
        previous = m["last"]
        dt = t_capture - previous.t
        vx = (position[0] - previous.position[0]) / dt
        vy = (position[1] - previous.position[1]) / dt
        if (vx * vx + vy * vy) ** 0.5 > s.max_speed:
            self.reset_hand(h)
            # Do not let a rejected teleport seed the next crossing.
            return no_strike("SPEED_DISCONTINUITY")
        dy = position[1] - previous.position[1]
        m["last"] = current
        if dy < 0:
            if m["bottom"] - position[1] >= s.rebound:
                m["fired"] = False
                m["top"] = position[1]
            m["top"] = min(m["top"], position[1])
        else:
            m["bottom"] = position[1]
        gap_ok = not (m["gap"] or dt > 0.05) or m["down"]
        was_down = m["down"]
        m["gap"] = False
        m["down"] = vy >= self.v_min and vy >= abs(vx) * s.downward_ratio
        diagnostic.update(velocity=[vx, vy], travel=position[1] - m["top"])
        if m["fired"]:
            return no_strike("WAIT_FOR_REBOUND")
        if not gap_ok:
            return no_strike("GAP_WITHOUT_MEASURED_APPROACH")
        if not m["down"]:
            return no_strike("NOT_DOWNWARD")
        if position[1] - m["top"] < s.min_travel:
            return no_strike("INSUFFICIENT_TRAVEL")
        impacts = []
        for zone in self.registry:
            if h not in zone.allowed_hands or zone.shape.contains(previous.position):
                continue
            crossing = segment_surface(previous.position, position, zone.impact_surface)
            if crossing is None or crossing.s <= 1e-9:
                continue
            # Crossing can pass entirely through a pad between delivered frames.
            impacts.append(
                Impact(zone, crossing_time(previous.t, t_capture, crossing.s), crossing.point, (vx, vy), 0)
            )
        reason = "CROSSING"
        if not impacts and s.lead_s > 0 and was_down:
            # Two consecutive downward samples: the edge the finger will reach within lead_s counts now.
            ahead = (position[0] + vx * s.lead_s, position[1] + vy * s.lead_s)
            for zone in self.registry:
                if h not in zone.allowed_hands or zone.shape.contains(position):
                    continue
                crossing = segment_surface(position, ahead, zone.impact_surface)
                if crossing is not None and crossing.s > 1e-9:
                    impacts.append(Impact(zone, t_capture, crossing.point, (vx, vy), 0))
            reason = "LEAD_CROSSING"
        if not impacts:
            return no_strike("NO_TOP_EDGE_CROSSING")
        impact = min(impacts, key=lambda x: (x.t_cross, x.zone.zone_id))
        m["fired"] = True
        key = (h, impact.zone.zone_id)
        self._episode_counter[key] = self._episode_counter.get(key, 0) + 1
        diagnostic.update(reason=reason, zone_id=impact.zone.zone_id)
        self.diagnostics[h] = diagnostic
        return (
            self._candidate(
                impact,
                source=CandidateSource.REACTIVE,
                frame_id=frame_id,
                hand=h,
                t_capture=t_capture,
                anticipator_id=None,
                strike_probability=None,
                intensity_proxy=max(0.0, vy),
                t_candidate=t_candidate,
            ),
        )
