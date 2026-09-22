"""Labelling rules v1.0 (Phase 07, Task 07.1) — the decision functions and their thresholds.

``docs/dataset/labeling-rules-v1.0.md`` is the normative document; this module is its executable
form. Every rule has an id (``P07-R<n>``) that is written into each ``LabelRecord.label_rule_id``,
and every threshold lives in :class:`Thresholds`, whose canonical hash is written into the label
provenance — a threshold change is therefore visible in the artefacts, not only in a diff.

What the rules key on:

* The **reference** tip trajectory (Task 07.2, non-causal). Never the causal track: the live
  tracker's noise must not define ground truth.
* The **Phase 04 entry test, unchanged** (``spacedrums.geometry.first_impact``): an impact is the
  first outside-to-inside crossing of a zone's impact surface with inward speed >= ``v_min``, at
  the sub-frame interpolated crossing time. The lowest stick position, a velocity reversal and any
  model prediction are explicitly **not** the definition (README section 14; phase document 07.1).
* The **observation**, not the cue. A ``FAKE_SWING`` segment whose participant actually struck the
  zone produces a POSITIVE: the segment type is a prior recorded in the label, never the label
  itself (Phase 06 ``protocol.NEGATIVE_TYPES`` docstring).

All threshold values below are **candidates** (phase document: "thresholds tunable and recorded")
and are refined after the first review pass on real recordings; nothing here has been tuned on
participant data, because none exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from spacedrums.data.labels.schema import LabelClass, sha256_obj
from spacedrums.geometry.zones import Arc, Point, Segment, Surface, Zone, _local, _world

RULES: dict[str, dict[str, str]] = {
    "P07-R1": {
        "class": "POSITIVE",
        "title": "Valid impact (ground truth)",
        "text": (
            "First outside-to-inside crossing of a zone impact surface by the REFERENCE tip in an "
            "entry episode, with inward speed v.n_in >= v_min * (1 + ambiguous_band). t_impact_est "
            "is the sub-frame interpolated crossing time of the Phase 04 entry test."
        ),
    },
    "P07-R2": {
        "class": "POSITIVE",
        "title": "GT intensity proxy",
        "text": (
            "intensity_proxy_gt = component of the reference tip velocity along the zone inward "
            "normal at t_impact_est (primary). Secondary proxies (peak speed and peak inward speed "
            "in the preceding window) are stored beside it so Phase 11 can compare; they never "
            "silently replace the primary definition. A proxy, never a force (REQ-014)."
        ),
    },
    "P07-R3": {
        "class": "NEG_FAKE_SWING",
        "title": "Fake swing",
        "text": (
            "No entry in the episode, minimum distance to the surface <= fake_swing_max_distance, "
            "maximum inward speed during the approach >= fake_swing_min_inward_speed, and the tip "
            "is still moving at the closest approach (speed above stop_speed_max)."
        ),
    },
    "P07-R4": {
        "class": "NEG_STOP_BEFORE_IMPACT",
        "title": "Stop before impact",
        "text": (
            "No entry, minimum distance to the surface inside the band "
            "[stop_band_min, stop_band_max], and the inward speed at the closest approach has "
            "decelerated to <= stop_speed_max."
        ),
    },
    "P07-R5": {
        "class": "NEG_UPWARD_CROSSING",
        "title": "Upward / exit-direction crossing",
        "text": (
            "An outside-to-inside crossing of the impact surface with v.n_in <= 0 or "
            "v.n_in < v_min * (1 - ambiguous_band); and any inside-to-outside (exit-direction) "
            "crossing that is NOT the recovery of an entry episode already labelled by R1/R5/R6 - "
            "the stick leaving a zone after its own strike is part of that episode, not a second "
            "event. Not an impact and not a miss: an explicit negative the false-positive analysis "
            "can use."
        ),
    },
    "P07-R6": {
        "class": "AMBIGUOUS",
        "title": "Ambiguous event",
        "text": (
            "(a) |v.n_in - v_min| within the ambiguous band; (b) the reference tracking around the "
            "event is DEGRADED (valid fraction < min_valid_fraction, or reference quality < "
            "degraded_quality, or the window was bridged across a gap); (c) the first and second "
            "review passes disagree on presence, zone or class. An AMBIGUOUS label stays in the "
            "dataset and is counted in the statistics, and is excluded from every metric numerator "
            "and denominator."
        ),
    },
    "P07-R7": {
        "class": "*",
        "title": "Label confidence",
        "text": (
            "confidence = mean reference sample quality in the event window, multiplied by the "
            "fraction of non-interpolated valid samples. It describes how well the reference "
            "trajectory is known around the event, not how likely a strike was."
        ),
    },
    "P07-R8": {
        "class": "NEG_TRACKING_LOSS",
        "title": "Tracking loss interval",
        "text": (
            "A gap in the reference trajectory longer than the smoother bridging bound max_gap_s, "
            "or an interval with no valid observation. Stored as an INTERVAL label; no event label "
            "is produced inside it."
        ),
    },
    "P07-R9": {
        "class": "NEG_NO_STRIKE_MOTION",
        "title": "No-strike motion interval",
        "text": (
            "An interval of at least no_strike_min_s in which the tip is tracked and moving "
            "(mean speed >= motion_min_speed) and no zone entry episode occurs anywhere."
        ),
    },
    "P07-R10": {
        "class": "NEG_BETWEEN_ZONES",
        "title": "Movement between zones",
        "text": (
            "An interval of at least between_zones_min_s during which the tip leaves the "
            "neighbourhood of one zone and reaches the neighbourhood of another (distance to some "
            "surface <= near_zone_distance at both ends) without any entry in between."
        ),
    },
    "P07-R11": {
        "class": "EXCLUDED",
        "title": "Quarantined material",
        "text": (
            "Any label whose time falls inside a segment or session quarantined by the Phase 06 "
            "unusable-recording policy. The label is kept with excluded = true and the "
            "exclusion_id, counted in the statistics, and never used in any metric."
        ),
    },
}


@dataclass(frozen=True)
class Thresholds:
    """Tunable labelling thresholds. Every value is a CANDIDATE until a review pass on real
    recordings refines it (phase document, Decisions That Must Be Experimentally Validated)."""

    v_min: float = 0.0
    """Phase 04 minimum inward speed of the entry test (ROI-norm/s); taken from the session config."""

    ambiguous_band: float = 0.15
    """Relative band around ``v_min`` in which a crossing is AMBIGUOUS rather than POSITIVE."""

    fake_swing_max_distance: float = 0.06
    """ROI-norm: how close a non-entering approach must come to count as a fake swing."""

    fake_swing_min_inward_speed: float = 0.25
    """ROI-norm/s: minimum peak inward speed during a fake-swing approach."""

    stop_band_min: float = 0.0
    stop_band_max: float = 0.08
    """ROI-norm distance band above the surface for the stop-before-impact rule."""

    stop_speed_max: float = 0.10
    """ROI-norm/s: 'decelerated to near-zero' at the closest approach."""

    approach_window_s: float = 0.40
    """Window before the closest approach used for the peak-inward-speed statistic."""

    intensity_window_s: float = 0.15
    """Window before the impact used for the secondary intensity proxies."""

    min_valid_fraction: float = 0.60
    """Fraction of valid (non-interpolated) reference samples required in an event window."""

    degraded_quality: float = 0.50
    """Mean reference-sample quality below which an event is AMBIGUOUS."""

    event_window_s: float = 0.20
    """Half-width of the window around an event over which quality and validity are summarised."""

    max_gap_s: float = 0.20
    """Reference-smoother bridging bound; a longer gap is a NEG_TRACKING_LOSS interval."""

    no_strike_min_s: float = 0.50
    motion_min_speed: float = 0.05
    between_zones_min_s: float = 0.30
    near_zone_distance: float = 0.12
    """ROI-norm: 'near a zone' for the movement-between-zones rule."""

    def __post_init__(self) -> None:
        if self.v_min < 0:
            raise ValueError("v_min must be non-negative")
        if not 0.0 <= self.ambiguous_band < 1.0:
            raise ValueError("ambiguous_band must lie in [0, 1)")
        if self.stop_band_max <= self.stop_band_min:
            raise ValueError("stop_band_max must exceed stop_band_min")
        for name in ("fake_swing_max_distance", "fake_swing_min_inward_speed", "stop_speed_max",
                     "approach_window_s", "intensity_window_s", "event_window_s", "max_gap_s",
                     "no_strike_min_s", "between_zones_min_s", "near_zone_distance"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if not 0.0 <= self.min_valid_fraction <= 1.0 or not 0.0 <= self.degraded_quality <= 1.0:
            raise ValueError("min_valid_fraction and degraded_quality must lie in [0, 1]")

    def with_v_min(self, v_min: float) -> Thresholds:
        return replace(self, v_min=float(v_min))

    def to_dict(self) -> dict[str, Any]:
        return {
            "v_min": float(self.v_min),
            "ambiguous_band": float(self.ambiguous_band),
            "fake_swing_max_distance": float(self.fake_swing_max_distance),
            "fake_swing_min_inward_speed": float(self.fake_swing_min_inward_speed),
            "stop_band_min": float(self.stop_band_min),
            "stop_band_max": float(self.stop_band_max),
            "stop_speed_max": float(self.stop_speed_max),
            "approach_window_s": float(self.approach_window_s),
            "intensity_window_s": float(self.intensity_window_s),
            "min_valid_fraction": float(self.min_valid_fraction),
            "degraded_quality": float(self.degraded_quality),
            "event_window_s": float(self.event_window_s),
            "max_gap_s": float(self.max_gap_s),
            "no_strike_min_s": float(self.no_strike_min_s),
            "motion_min_speed": float(self.motion_min_speed),
            "between_zones_min_s": float(self.between_zones_min_s),
            "near_zone_distance": float(self.near_zone_distance),
        }

    @property
    def thresholds_hash(self) -> str:
        return sha256_obj(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Thresholds:
        known = {f for f in cls().to_dict()}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown threshold keys: {sorted(unknown)}")
        return cls(**{k: float(v) for k, v in data.items()})


def rules_hash() -> str:
    """Hash of the rule table: a changed rule text is a changed label machinery."""
    return sha256_obj(RULES)


# ----------------------------------------------------------------------------- surface geometry


def closest_point_on_surface(surface: Surface, p: Point) -> Point:
    """Closest point of an impact surface to ``p`` (exact for a segment, angle-clamped for an arc).

    The arc case projects ``p`` into the arc's local ellipse frame, takes the angle of the
    projection, clamps it into the arc's angular span and evaluates the arc there. That is the
    closest point for a circular arc and a close approximation for an eccentric ellipse; the
    quantity is only used for threshold comparisons (rules R3/R4/R10), never for a crossing time.
    """
    if isinstance(surface, Segment):
        ax, ay = surface.p0
        bx, by = surface.p1
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        u = 0.0 if denom <= 0 else ((p[0] - ax) * dx + (p[1] - ay) * dy) / denom
        u = min(1.0, max(0.0, u))
        return (ax + u * dx, ay + u * dy)
    arc: Arc = surface
    x, y = _local(p, arc.center, arc.angle_rad)
    theta = math.atan2(y / arc.ry, x / arc.rx) if (x or y) else arc.theta_start_rad
    if not arc.includes_angle(theta):
        ends = (arc.theta_start_rad, arc.theta_end_rad)
        theta = min(ends, key=lambda th: math.dist(_world((arc.rx * math.cos(th), arc.ry * math.sin(th)),
                                                          arc.center, arc.angle_rad), p))
    return arc.point_at(theta)


def distance_to_surface(zone: Zone, p: Point) -> float:
    """Euclidean distance (ROI-norm) from ``p`` to the zone's impact surface."""
    return math.dist(p, closest_point_on_surface(zone.impact_surface, p))


def signed_distance_to_surface(zone: Zone, p: Point) -> float:
    """Distance to the impact surface, positive outside the zone shape and negative inside it."""
    d = distance_to_surface(zone, p)
    return -d if zone.shape.contains(p, include_boundary=False) else d


def inward_speed(zone: Zone, velocity: Point) -> float:
    """Velocity component along the zone's inward normal (the Phase 04 entry-test quantity)."""
    return velocity[0] * zone.inward_normal[0] + velocity[1] * zone.inward_normal[1]


# ----------------------------------------------------------------------------- classification


@dataclass(frozen=True)
class EventEvidence:
    """Everything the rules need about one candidate event, measured on the reference trajectory.

    Separating the measurement (``generate.py``) from the decision (here) is what makes every rule
    testable on a synthetic trajectory without a session on disk (Task 07.1 evidence).
    """

    direction: str
    """ENTRY (outside-to-inside crossing), EXIT (inside-to-outside crossing) or APPROACH (no crossing)."""

    inward_speed: float
    min_distance: float
    max_inward_speed: float
    speed_at_min_distance: float
    valid_fraction: float
    mean_quality: float
    interpolated: bool
    in_quarantine: bool = False
    recovery_of_entry: bool = False
    """EXIT only: true when this crossing is the recovery of an entry episode that was itself
    labelled. The stick leaving a zone after a strike is not a separate negative event."""

    def __post_init__(self) -> None:
        if self.direction not in ("ENTRY", "EXIT", "APPROACH"):
            raise ValueError("direction must be ENTRY, EXIT or APPROACH")


def classify(evidence: EventEvidence, thresholds: Thresholds) -> tuple[LabelClass, str] | None:
    """Label class and rule id for one candidate event, or ``None`` if it is not a labelled event.

    Order of decision (each step is a rule of the document, in this order): quarantine (R11) ->
    exit-direction crossing (R5) -> entry crossing (R5 / R6a / R1, with the R6b quality veto) ->
    non-crossing approach (R4 stop-short before R3 fake swing, because the stop rule is the more
    specific one).
    """
    if evidence.in_quarantine:
        return LabelClass.EXCLUDED, "P07-R11"
    degraded = (
        evidence.valid_fraction < thresholds.min_valid_fraction
        or evidence.mean_quality < thresholds.degraded_quality
        or evidence.interpolated
    )
    if evidence.direction == "EXIT":
        # The recovery stroke of a labelled entry is part of that episode, not a second event.
        return None if evidence.recovery_of_entry else (LabelClass.NEG_UPWARD_CROSSING, "P07-R5")
    if evidence.direction == "ENTRY":
        lower = thresholds.v_min * (1.0 - thresholds.ambiguous_band)
        upper = thresholds.v_min * (1.0 + thresholds.ambiguous_band)
        if evidence.inward_speed <= 0.0 or evidence.inward_speed < lower:
            return LabelClass.NEG_UPWARD_CROSSING, "P07-R5"
        if evidence.inward_speed <= upper:
            return LabelClass.AMBIGUOUS, "P07-R6a"
        if degraded:
            return LabelClass.AMBIGUOUS, "P07-R6b"
        return LabelClass.POSITIVE, "P07-R1"
    if degraded:
        return LabelClass.AMBIGUOUS, "P07-R6b"
    near = thresholds.stop_band_min <= evidence.min_distance <= thresholds.stop_band_max
    if near and evidence.speed_at_min_distance <= thresholds.stop_speed_max:
        return LabelClass.NEG_STOP_BEFORE_IMPACT, "P07-R4"
    if (
        evidence.min_distance <= thresholds.fake_swing_max_distance
        and evidence.max_inward_speed >= thresholds.fake_swing_min_inward_speed
    ):
        return LabelClass.NEG_FAKE_SWING, "P07-R3"
    return None


def label_confidence(mean_quality: float, valid_fraction: float) -> float:
    """Rule R7: reference-tracking quality around the event, clipped into [0, 1]."""
    return float(min(1.0, max(0.0, mean_quality * valid_fraction)))


def intensity_proxy_gt(zone: Zone, velocity: Point) -> float:
    """Rule R2 primary definition: inward-normal component of the reference velocity at impact."""
    return inward_speed(zone, velocity)


__all__ = [
    "RULES",
    "EventEvidence",
    "Thresholds",
    "classify",
    "closest_point_on_surface",
    "distance_to_surface",
    "intensity_proxy_gt",
    "inward_speed",
    "label_confidence",
    "rules_hash",
    "signed_distance_to_surface",
]
