"""Fixtures for the Phase 07 label tests: two zones with the two impact-surface kinds."""

from __future__ import annotations

import math

import pytest

from spacedrums.geometry import Arc, Ellipse, Polygon, Segment, Zone, ZoneRegistry


@pytest.fixture
def circle_zone() -> Zone:
    """Elliptical zone whose impact surface is the lower arc; inward normal points up-screen down."""
    return Zone(
        zone_id="snare",
        name="Snare",
        trigger_type="HAND_TIP",
        shape=Ellipse((0.5, 0.5), 0.2, 0.2),
        impact_surface=Arc((0.5, 0.5), 0.2, 0.2, 0.0, math.pi, 2 * math.pi),
        inward_normal=(0.0, 1.0),
        allowed_hands=("LEFT", "RIGHT"),
        sample_id="synth-snare-v1",
        gain_curve_id="default",
    )


@pytest.fixture
def segment_zone() -> Zone:
    """Rectangular zone whose impact surface is its top edge (a straight segment)."""
    return Zone(
        zone_id="tom1",
        name="Tom 1",
        trigger_type="HAND_TIP",
        shape=Polygon(((0.1, 0.3), (0.4, 0.3), (0.4, 0.6), (0.1, 0.6))),
        impact_surface=Segment((0.1, 0.3), (0.4, 0.3)),
        inward_normal=(0.0, 1.0),
        allowed_hands=("LEFT", "RIGHT"),
        sample_id="synth-tom1-v1",
        gain_curve_id="default",
    )


@pytest.fixture
def two_zone_registry(circle_zone: Zone, segment_zone: Zone) -> ZoneRegistry:
    return ZoneRegistry((circle_zone, segment_zone))
