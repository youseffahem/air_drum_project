"""Shared SYNTHETIC ``TrackState`` histories for the Phase 05 prediction tests (labelled synthetic)."""

from __future__ import annotations

import pytest

from spacedrums.contracts import HandId, HistoryRef, TrackState, TrackStatus

DT = 1.0 / 30.0


def track(
    frame_id: int,
    t: float,
    pos,
    vel,
    acc=None,
    *,
    status: TrackStatus = TrackStatus.VALID,
    confidence: float = 0.9,
    hand: HandId = HandId.RIGHT,
    reset=None,
) -> TrackState:
    live = status in (TrackStatus.VALID, TrackStatus.DEGRADED)
    return TrackState(
        frame_id=frame_id,
        t_capture=t,
        hand_id=hand,
        status=status,
        tracker_id="synthetic-tracker",
        tip_method="GEOM",
        tip_filtered=pos if live else None,
        tip_velocity=vel if live else None,
        tip_acceleration=acc if live else None,
        axis_angle=None,
        axis_angular_velocity=None,
        confidence=confidence if live else 0.0,
        frames_since_valid=0 if status is TrackStatus.VALID else 1,
        last_valid_t=t,
        history_ref=HistoryRef(1, frame_id) if live else None,
        reset_reason=reset,
    )


def parabolic_history(
    n: int,
    *,
    p0=(0.4, 0.3),
    v0=(0.0, 0.8),
    a=(0.0, 6.0),
    t0: float = 100.0,
    dt: float = DT,
    with_acc: bool = True,
) -> list[TrackState]:
    """Exact (noise-free) kinematic states along p = p0 + v0 t + 1/2 a t^2 (SYNTHETIC)."""
    out = []
    for k in range(n):
        t = k * dt
        pos = (p0[0] + v0[0] * t + 0.5 * a[0] * t * t, p0[1] + v0[1] * t + 0.5 * a[1] * t * t)
        vel = (v0[0] + a[0] * t, v0[1] + a[1] * t)
        out.append(track(k, t0 + t, pos, vel, a if with_acc else None))
    return out


@pytest.fixture
def parabola():
    return parabolic_history(12)
