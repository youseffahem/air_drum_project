"""Synthetic physical actions through automatic calibration; no camera claims."""

from types import SimpleNamespace

import pytest

from spacedrums.calib.automatic import AutomaticCalibration
from spacedrums.calib.reach import ReachSettings, StrokeCollector
from spacedrums.contracts import HandId
from spacedrums.contracts.perception import BodyReference, EndpointEvidence
from spacedrums.geometry.four_pad import DISPLAY_ORDER


def test_automatic_stand_reach_validation_ready_without_manual_positions():
    cal = AutomaticCalibration((560, 440), provenance="SYNTHETIC")
    frame = 0

    def step(positions, hits=(), body=False):
        nonlocal frame
        frame += 1
        t = frame / 30
        ev = {
            h: EndpointEvidence(frame, t, h, "MEASURED", "SYNTHETIC", p, (p[0], p[1] + 0.2), 0.95, 88.0)
            for h, p in positions.items()
        }
        cal.update(t, ev, BodyReference(t, 0.36, 0.64, 0.20, 0.82, 0.95) if body else None, hits)

    for _ in range(65):
        step({HandId.LEFT: (0.2, 0.4), HandId.RIGHT: (0.8, 0.4)}, body=True)
        if cal.state != "STAND":
            break
    assert cal.state == "REACH"
    for stage in ("REACH", "VERIFY"):
        for index, target in enumerate(DISPLAY_ORDER):
            assert cal.target == target, (cal.state, cal.failures)
            x, bottom = (0.8, 0.2)[index % 2], (0.35, 0.70)[index // 2]
            for repeat in range(6):
                hand = HandId.LEFT if repeat % 2 else HandId.RIGHT
                for offset in (-0.15, -0.13, -0.09, -0.04, 0.0, -0.02, -0.1):
                    positions = {h: (x, bottom - 0.15) for h in HandId}
                    positions[hand] = (x, bottom + offset)
                    hits = ()
                    if stage == "VERIFY" and offset == 0:
                        hits = (
                            SimpleNamespace(hand_id=hand, t_impact_target=(frame + 1) / 30, zone_id=target),
                        )
                    step(positions, hits)
                    if cal.target != target:
                        break
    assert cal.state == "READY", (cal.state, cal.fit, cal.report())
    assert len(cal.zones) == 4
    assert all(v["hits"] == 6 for v in cal.validation.values())


def test_missing_sticks_never_advance_standing_step():
    cal = AutomaticCalibration((560, 440), provenance="SYNTHETIC")
    for f in range(90):
        t = f / 30
        ev = {h: EndpointEvidence(f, t, h, "MISSING", "HAND_MISSING") for h in HandId}
        cal.update(t, ev, BodyReference(t, 0.36, 0.64, 0.20, 0.82, 0.95))
    assert cal.state == "STAND"
    assert not cal.zones


def test_standing_requires_two_current_tips_and_expires_body_history():
    cal = AutomaticCalibration((560, 440), provenance="SYNTHETIC")
    for f in range(65):
        t = f / 30
        cal.update(t, {}, BodyReference(t, 0.36, 0.64, 0.20, 0.82, 0.95))
    assert cal.state == "STAND"
    cal.update(6.0, {})
    assert not cal.bodies
    with pytest.raises(ValueError, match="current-frame"):
        cal.update(7.0, {HandId.LEFT: EndpointEvidence(70, 6.0, HandId.LEFT, "MISSING", "SYNTHETIC")})


@pytest.mark.parametrize(
    "missing,approach,expected", [(1, True, 1), (2, True, 1), (4, True, 0), (1, False, 0)]
)
def test_calibration_gap_needs_bounded_measured_approach(missing, approach, expected):
    collector = StrokeCollector(ReachSettings())
    ys = [0.20, 0.23 if approach else 0.20] + [None] * missing + [0.30, 0.28]
    for frame, y in enumerate(ys):
        e = (
            EndpointEvidence(frame, frame / 30, HandId.LEFT, "MISSING", "SYNTHETIC")
            if y is None
            else EndpointEvidence(
                frame, frame / 30, HandId.LEFT, "MEASURED", "SYNTHETIC", (0.2, y), (0.2, y + 0.2), 0.95, 88
            )
        )
        collector.add(e, "crash_ride")
    assert len(collector.strokes) == expected
    if expected:
        assert len(collector.strokes[0].points) == 3  # No synthesized gap samples.
