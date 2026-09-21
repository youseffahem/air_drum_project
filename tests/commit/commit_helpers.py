"""Shared SYNTHETIC fixtures for the Phase 05 commit tests (labelled synthetic; never evidence)."""

from __future__ import annotations

import math
from itertools import count

import pytest

from spacedrums.commit import CommitSettings, PerHandCommitPolicy
from spacedrums.contracts import (
    CandidateSource,
    HandId,
    HistoryRef,
    StrikeCandidate,
    TrackState,
    TrackStatus,
)
from spacedrums.geometry import Arc, Ellipse, Zone, ZoneRegistry

_ids = count(1)


def zone(zone_id: str, cy: float) -> Zone:
    return Zone(
        zone_id,
        zone_id,
        "HAND_TIP",
        Ellipse((0.5, cy), 0.2, 0.1),
        Arc((0.5, cy), 0.2, 0.1, 0.0, math.pi, 2 * math.pi),
        (0.0, 1.0),
        ("LEFT", "RIGHT"),
        "sample",
        "default",
    )


@pytest.fixture
def registry() -> ZoneRegistry:
    return ZoneRegistry((zone("snare", 0.7), zone("tom1", 0.3)))


def track(
    frame_id: int,
    t: float,
    *,
    status: TrackStatus = TrackStatus.VALID,
    pos=(0.5, 0.4),
    hand: HandId = HandId.RIGHT,
    confidence: float = 0.9,
) -> TrackState:
    live = status in (TrackStatus.VALID, TrackStatus.DEGRADED)
    return TrackState(
        frame_id=frame_id,
        t_capture=t,
        hand_id=hand,
        status=status,
        tracker_id="synthetic",
        tip_method="GEOM",
        tip_filtered=pos if live else None,
        tip_velocity=(0.0, 1.0) if live else None,
        tip_acceleration=None,
        axis_angle=None,
        axis_angular_velocity=None,
        confidence=confidence if live else 0.0,
        frames_since_valid=0 if status is TrackStatus.VALID else 1,
        last_valid_t=t,
        history_ref=HistoryRef(3, max(0, frame_id - 2)) if live else None,
        reset_reason=None,
    )


def candidate(
    frame_id: int,
    t_capture: float,
    *,
    source: str = "RULE",
    zone_id: str = "snare",
    t_impact: float,
    prob: float | None = 0.9,
    hand: HandId = HandId.RIGHT,
    cid: str | None = None,
) -> StrikeCandidate:
    src = CandidateSource(source)
    reactive = src is CandidateSource.REACTIVE
    return StrikeCandidate(
        candidate_id=cid or f"c{next(_ids):05d}",
        frame_id=frame_id,
        t_capture=t_capture,
        hand_id=hand,
        zone_id=zone_id,
        source=src,
        derivation="GEOMETRY",
        anticipator_id=None if reactive else "rule-test",
        t_impact_pred=None if reactive else t_impact,
        t_impact_est=t_impact if reactive else None,
        tti=None if reactive else t_impact - t_capture,
        impact_position=(0.5, 0.6),
        crossing_velocity=(0.0, 1.5),
        strike_probability=None if reactive else prob,
        intensity_proxy=1.5,
        t_candidate=t_capture + 0.01,
    )


def policy(
    registry: ZoneRegistry, *, arm: str = "B", shadow: bool = False, hand: HandId = HandId.RIGHT, **settings
) -> PerHandCommitPolicy:
    s = CommitSettings(**settings)
    return PerHandCommitPolicy(
        hand, s, registry, arm=arm, shadow=shadow, gain_fn=lambda z, p: 0.5, session_id="syn"
    )


@pytest.fixture
def make_policy(registry):
    def _make(**kw):
        return policy(registry, **kw)

    return _make
