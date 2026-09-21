from __future__ import annotations

import pytest

from spacedrums.contracts import CommittedStrike
from spacedrums.geometry import Arc, Ellipse, Zone, ZoneRegistry


@pytest.fixture
def committed() -> CommittedStrike:
    return CommittedStrike(
        strike_id="s1",
        candidate_id="c1",
        frame_id=3,
        t_capture=1.0,
        hand_id="RIGHT",
        zone_id="snare",
        source="RULE",
        derivation="GEOMETRY",
        arm="B",
        shadow=False,
        t_commit=1.01,
        t_impact_target=1.1,
        intensity_proxy=2.0,
        gain=0.5,
        refractory_until=1.2,
        episode_id="e1",
        commit_policy_id="test",
    )


@pytest.fixture
def registry() -> ZoneRegistry:
    zone = Zone(
        "snare",
        "Snare",
        "HAND_TIP",
        Ellipse((0.5, 0.5), 0.2, 0.2),
        Arc((0.5, 0.5), 0.2, 0.2, 0.0, 3.141592653589793, 6.283185307179586),
        (0.0, 1.0),
        ("LEFT", "RIGHT"),
        "sample",
        "default",
    )
    return ZoneRegistry((zone,))
