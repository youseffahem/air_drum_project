from __future__ import annotations

import math

import pytest

from spacedrums.geometry import Arc, Ellipse, Zone, ZoneRegistry


@pytest.fixture
def circle_zone() -> Zone:
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
def registry(circle_zone: Zone) -> ZoneRegistry:
    return ZoneRegistry((circle_zone,))
