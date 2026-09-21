"""SYNTHETIC observation sequences for deterministic development and unit tests (Phase 05).

**Everything produced here is synthetic.** It is never a recording, never participant data and never
evidence of real-world behaviour; it exists so the decision pipeline, the commit logic and the
metrics machinery can be exercised deterministically (integrity I-4: labelled synthetic in the file
name, the ids and every report that quotes it).

A *swing* is a downward stroke from ``y_top`` to ``y_bottom`` (constant acceleration from rest over
``t_down``), then a symmetric rebound to ``y_top``; ``x`` stays at the zone's mid-surface ``x``. The
analytic crossing time of a horizontal impact surface at ``y_s`` is ``t_cross = t_start +
sqrt(2 (y_s - y_top) / a)`` with ``a = 2 (y_bottom - y_top) / t_down^2``. Sequences are sampled at a
fixed frame period (optionally jittered), with optional Gaussian tip noise, dropped/occluded frames
and per-frame confidences, all from a seeded generator.

Coordinates: ROI-normalized, y down (ADR-0005). Zones: any ``ZoneRegistry``; the surface height at the
zone's mid-surface ``x`` is taken from the registry (upper arc/segment midpoint).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

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

DT = 1.0 / 30.0
T0 = 100.0
ROI_PX = (40, 20, 560, 440)
FRAME_PX = (640, 480)
DETECTOR_ID = "synthetic-hands"
CAMERA_PROFILE_ID = "synthetic-camera"


@dataclass(frozen=True)
class Swing:
    """One synthetic stroke of ``hand`` onto ``zone_id`` (or a non-striking motion)."""

    hand: HandId
    zone_id: str
    t_start: float  # seconds relative to sequence start
    t_down: float = 0.20  # duration of the downward phase (rest -> y_bottom)
    depth: float = 0.05  # how far below the impact surface y_bottom lies (> 0 strikes; < 0 stops short)
    height: float = 0.10  # y_top = y_surface - height (small enough to start outside neighbouring zones)
    x_offset: float = 0.0  # lateral offset of the stroke from the surface midpoint
    kind: str = "strike"  # strike | stop_short | lateral | upward | hover

    @property
    def t_up_end(self) -> float:
        return self.t_start + 2.0 * self.t_down


@dataclass(frozen=True)
class TruthEvent:
    """SYNTHETIC ground truth: the analytic crossing of the impact surface by the noise-free path."""

    hand: HandId
    zone_id: str
    t_cross: float
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "hand_id": str(self.hand),
            "zone_id": self.zone_id,
            "t_cross": self.t_cross,
            "kind": self.kind,
            "label": "SYNTHETIC",
        }


@dataclass
class SyntheticSequence:
    frames: list[tuple[FrameSample, dict[HandId, tuple[HandObservation, StickObservation]]]]
    truth: list[TruthEvent]
    label: str = "SYNTHETIC"
    params: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.frames)

    def __iter__(self):
        return iter(self.frames)


def _surface_top(registry: ZoneRegistry, zone_id: str) -> tuple[float, float]:
    """(x, y) of the impact-surface midpoint (the top of a drum-like zone)."""
    return surface_midpoint(registry[zone_id].impact_surface)


def _hand_obs(
    frame_id: int, t: float, hand: HandId, present: bool, tip: tuple[float, float] | None
) -> HandObservation:
    if not present or tip is None:
        return HandObservation.absent(frame_id, t, hand, DETECTOR_ID)
    cx, cy = tip[0], min(0.98, tip[1] + 0.25)  # a hand below the tip (y down)
    lm = tuple((cx + 0.004 * (i % 5) - 0.008, cy - 0.006 * (i // 5)) for i in range(21))
    return HandObservation(
        frame_id=frame_id,
        t_capture=t,
        hand_id=hand,
        present=True,
        detector_id=DETECTOR_ID,
        landmarks=lm,
        landmark_visibility=None,
        handedness_score=0.95,
        bbox=(cx - 0.05, cy - 0.05, 0.1, 0.1),
    )


def _stick_obs(
    frame_id: int, t: float, hand: HandId, tip: tuple[float, float] | None, conf: float
) -> StickObservation:
    if tip is None:
        return StickObservation.absent(frame_id, t, hand, TipMethod.GEOM)
    return StickObservation(
        frame_id=frame_id,
        t_capture=t,
        hand_id=hand,
        present=True,
        method_id=TipMethod.GEOM,
        axis_origin=(tip[0], min(0.98, tip[1] + 0.25)),
        axis_dir=(0.0, -1.0),
        tip=tip,
        tip_confidence=conf,
        axis_confidence=min(1.0, conf + 0.05),
        stick_length_est=0.27,
    )


def swing_position(sw: Swing, registry: ZoneRegistry, t_rel: float) -> tuple[float, float]:
    """Noise-free tip position of one swing at ``t_rel`` (seconds since sequence start)."""
    xs, ys = _surface_top(registry, sw.zone_id)
    x = xs + sw.x_offset
    y_top = ys - sw.height
    if sw.kind == "hover":
        return (x, y_top)
    if sw.kind == "lateral":  # moves along x at y_top, never down
        u = min(1.0, max(0.0, (t_rel - sw.t_start) / (2 * sw.t_down)))
        return (x - 0.15 + 0.30 * u, y_top)
    if sw.kind == "upward":  # starts inside the zone (below the surface) and moves up
        y_in = ys + abs(sw.depth)
        u = min(1.0, max(0.0, (t_rel - sw.t_start) / sw.t_down))
        return (x, y_in - (y_in - y_top) * u)
    y_bottom = ys + sw.depth  # strike: depth > 0 ; stop_short: depth < 0
    a = 2.0 * (y_bottom - y_top) / (sw.t_down**2)
    if t_rel <= sw.t_start:
        return (x, y_top)
    if t_rel <= sw.t_start + sw.t_down:
        tau = t_rel - sw.t_start
        return (x, y_top + 0.5 * a * tau * tau)
    if t_rel <= sw.t_up_end:
        tau = sw.t_up_end - t_rel
        return (x, y_top + 0.5 * a * tau * tau)
    return (x, y_top)


def swing_truth(sw: Swing, registry: ZoneRegistry) -> TruthEvent | None:
    if sw.kind != "strike" or sw.depth <= 0:
        return None
    _, ys = _surface_top(registry, sw.zone_id)
    a = 2.0 * (sw.depth + sw.height) / (sw.t_down**2)
    return TruthEvent(sw.hand, sw.zone_id, sw.t_start + math.sqrt(2.0 * sw.height / a), "strike")


def swing_crossing_speed(sw: Swing, registry: ZoneRegistry) -> float:
    """Analytic downward speed (ROI-norm/s) at the surface crossing (for threshold choices in tests)."""
    a = 2.0 * (sw.depth + sw.height) / (sw.t_down**2)
    return math.sqrt(2.0 * a * sw.height)


def rest_position(registry: ZoneRegistry, hand: HandId) -> tuple[float, float]:
    """Where an idle hand's tip rests: outside every zone, near the bottom corners."""
    return (0.08, 0.90) if hand is HandId.LEFT else (0.92, 0.90)


def hand_position(
    registry: ZoneRegistry, swings: list[Swing], hand: HandId, t_rel: float
) -> tuple[float, float]:
    """Noise-free tip of one hand: hold the first swing's start, swing, glide between swings, hold the last.

    No jumps: between two swings the tip moves linearly from the end point of one to the start point
    of the next (this is the "movement between zones without striking" case); a hand without swings
    rests in a corner outside every zone.
    """
    if not swings:
        return rest_position(registry, hand)
    ordered = sorted(swings, key=lambda sw: sw.t_start)
    if t_rel <= ordered[0].t_start:
        return swing_position(ordered[0], registry, ordered[0].t_start)
    current = max((sw for sw in ordered if sw.t_start <= t_rel), key=lambda sw: sw.t_start)
    if t_rel <= current.t_up_end:
        return swing_position(current, registry, t_rel)
    later = [sw for sw in ordered if sw.t_start > current.t_start]
    if not later:
        return swing_position(current, registry, current.t_up_end)
    nxt = later[0]
    a, b = swing_position(current, registry, current.t_up_end), swing_position(nxt, registry, nxt.t_start)
    span = nxt.t_start - current.t_up_end
    u = 1.0 if span <= 0 else min(1.0, max(0.0, (t_rel - current.t_up_end) / span))
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)


def build_sequence(
    registry: ZoneRegistry,
    swings: Iterable[Swing],
    *,
    duration_s: float,
    dt: float = DT,
    t0: float = T0,
    noise: float = 0.0,
    seed: int = 0,
    conf: float = 0.9,
    jitter_dt: float = 0.0,
    occluded: dict[HandId, set[int]] | None = None,
    low_conf: dict[HandId, dict[int, float]] | None = None,
    dropped: dict[int, int] | None = None,
    image: bool = False,
    label: str = "SYNTHETIC",
    name: str = "synthetic",
) -> SyntheticSequence:
    """Sample the swings of both hands into per-frame observations (deterministic for a seed)."""
    rng = np.random.default_rng(seed)
    swings = list(swings)
    occluded = occluded or {}
    low_conf = low_conf or {}
    dropped = dropped or {}
    n = int(round(duration_s / dt))
    frames: list[tuple[FrameSample, dict[HandId, tuple[HandObservation, StickObservation]]]] = []
    t = t0
    for k in range(n):
        if k > 0:
            t += dt + (float(rng.uniform(-jitter_dt, jitter_dt)) if jitter_dt else 0.0)
        t_rel = t - t0
        obs: dict[HandId, tuple[HandObservation, StickObservation]] = {}
        for hand in (HandId.LEFT, HandId.RIGHT):
            p = hand_position(registry, [sw for sw in swings if sw.hand is hand], hand, t_rel)
            if noise:
                p = (p[0] + float(rng.normal(0, noise)), p[1] + float(rng.normal(0, noise)))
            if k in occluded.get(hand, set()):
                obs[hand] = (_hand_obs(k, t, hand, False, None), _stick_obs(k, t, hand, None, 0.0))
            else:
                c = low_conf.get(hand, {}).get(k, conf)
                obs[hand] = (_hand_obs(k, t, hand, True, p), _stick_obs(k, t, hand, p, c))
        img = np.zeros((FRAME_PX[1], FRAME_PX[0], 3), np.uint8) if image else None
        sample = FrameSample(
            frame_id=k,
            t_capture=t,
            t_frame_available=t + 0.004,
            timestamp_source=TimestampSource.REPLAY,
            frame_size_px=FRAME_PX,
            roi_px=ROI_PX,
            image_ref=ImageRef.memory(img),
            camera_profile_id=CAMERA_PROFILE_ID,
            dropped_since_last=dropped.get(k, 0),
        )
        frames.append((sample, obs))
    truth = [ev for sw in swings if (ev := swing_truth(sw, registry)) is not None]
    truth = [TruthEvent(e.hand, e.zone_id, t0 + e.t_cross, e.kind) for e in truth]
    return SyntheticSequence(
        frames=frames,
        truth=sorted(truth, key=lambda e: e.t_cross),
        label=label,
        params={
            "name": name,
            "dt": dt,
            "t0": t0,
            "noise": noise,
            "seed": seed,
            "conf": conf,
            "jitter_dt": jitter_dt,
            "n_frames": n,
            "swings": len(swings),
        },
    )


# ----------------------------------------------------------------------------- scenario catalogue


def scenario(
    name: str,
    registry: ZoneRegistry,
    *,
    zone: str = "snare",
    zone2: str = "hihat",
    t_down: float | None = None,
    **kwargs: Any,
) -> SyntheticSequence:
    """Named SYNTHETIC scenarios used by tests, the playability self-test and the induced-loss self-test.

    ``t_down`` overrides every swing's downward duration (shorter = faster stroke).
    """
    L, R = HandId.LEFT, HandId.RIGHT
    if name == "single":
        sw, dur = [Swing(R, zone, 0.5)], 1.6
    elif name == "repeated":
        sw, dur = [Swing(R, zone, 0.4 + 0.6 * i) for i in range(4)], 3.4
    elif name == "rapid":
        sw, dur = [Swing(R, zone, 0.4 + 0.30 * i, t_down=0.10) for i in range(6)], 2.8
    elif name == "alternating_one_zone":
        sw, dur = [Swing(R if i % 2 == 0 else L, zone, 0.4 + 0.5 * i) for i in range(4)], 3.0
    elif name == "alternating_two_zones":
        sw, dur = (
            [
                Swing(R, zone, 0.4 + 0.5 * i) if i % 2 == 0 else Swing(L, zone2, 0.4 + 0.5 * i)
                for i in range(4)
            ],
            3.0,
        )
    elif name == "near_simultaneous":
        sw, dur = [Swing(R, zone, 0.5), Swing(L, zone2, 0.5 + kwargs.pop("delta_s", 0.01))], 1.6
    elif name == "stop_short":  # fake swing: decelerates and stops above the surface
        sw, dur = [Swing(R, zone, 0.5, depth=-0.03)], 1.6
    elif name == "hover":  # stopped stick above the zone
        sw, dur = [Swing(R, zone, 0.2, kind="hover")], 1.2
    elif name == "lateral":  # moves sideways above the zone
        sw, dur = [Swing(R, zone, 0.3, kind="lateral")], 1.6
    elif name == "upward":  # starts inside the zone and leaves upward
        sw, dur = [Swing(R, zone, 0.3, kind="upward")], 1.2
    elif name == "slow":  # very slow approach (low velocity)
        sw, dur = [Swing(R, zone, 0.3, t_down=1.2, height=0.10)], 3.0
    elif name == "between_zones":  # moves from above one zone to above the other without striking
        sw, dur = [Swing(R, zone, 0.3, kind="lateral")], 1.6
    else:
        raise ValueError(f"unknown synthetic scenario {name!r}")
    if t_down is not None:
        sw = [dataclasses.replace(x, t_down=t_down) for x in sw]
    return build_sequence(registry, sw, duration_s=dur, name=name, **kwargs)


SCENARIOS = (
    "single",
    "repeated",
    "rapid",
    "alternating_one_zone",
    "alternating_two_zones",
    "near_simultaneous",
    "stop_short",
    "hover",
    "lateral",
    "upward",
    "slow",
    "between_zones",
)


__all__ = [
    "CAMERA_PROFILE_ID",
    "DETECTOR_ID",
    "DT",
    "FRAME_PX",
    "ROI_PX",
    "SCENARIOS",
    "T0",
    "Swing",
    "SyntheticSequence",
    "TruthEvent",
    "build_sequence",
    "hand_position",
    "rest_position",
    "scenario",
    "swing_crossing_speed",
    "swing_position",
    "swing_truth",
]
