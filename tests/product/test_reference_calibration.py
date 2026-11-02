"""SYNTHETIC automatic calibration of the reference four-piece kit (AR view); no camera claims."""

from types import SimpleNamespace

import numpy as np
import pytest

from spacedrums.calib.automatic import AutomaticCalibration
from spacedrums.calib.developer_demo import check_kit_pads
from spacedrums.calib.reach import ReachSettings, ReachStroke, fit_reach_reference
from spacedrums.contracts import HandId
from spacedrums.contracts.perception import BodyReference, EndpointEvidence
from spacedrums.geometry.four_pad import DISPLAY_ORDER
from spacedrums.geometry.reference_kit import reference_guide_pads

ROI = (560, 440)
BODY = (0.36, 0.64, 0.20, 0.82)


def edge(zone):
    """Camera-space centre x and strike-edge y of a zone."""
    (x0, y), (x1, _) = zone["impact_surface"]["p0"], zone["impact_surface"]["p1"]
    return (x0 + x1) / 2, y


def calibrate(arrangement):
    cal = AutomaticCalibration(ROI, provenance="SYNTHETIC", arrangement=arrangement)
    frame = 0

    def step(positions, hits=(), body=False):
        nonlocal frame
        frame += 1
        t = frame / 30
        ev = {
            h: EndpointEvidence(frame, t, h, "MEASURED", "SYNTHETIC", p, (p[0], p[1] + 0.2), 0.95, 88.0)
            for h, p in positions.items()
        }
        cal.update(t, ev, BodyReference(t, *BODY, 0.95) if body else None, hits)

    for _ in range(65):
        step({HandId.LEFT: (0.2, 0.3), HandId.RIGHT: (0.8, 0.3)}, body=True)
        if cal.state != "STAND":
            break
    assert cal.state == "REACH", cal.failures
    guide = {z["zone_id"]: edge(z) for z in cal.guide_zones}
    for stage in ("REACH", "VERIFY"):
        for target in DISPLAY_ORDER:
            assert cal.target == target, (cal.state, cal.failures, cal.fit)
            zones = cal.zones if stage == "VERIFY" else cal.guide_zones
            x, y = (
                edge(next(z for z in zones if z["zone_id"] == target)) if stage == "VERIFY" else guide[target]
            )
            bottom = y + 0.03
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
    return cal


def test_reference_arrangement_calibrates_with_the_same_flow():
    cal = calibrate("reference")
    assert cal.state == "READY", (cal.failures, cal.fit and cal.fit["reasons"])
    assert cal.fit["arrangement"] == "reference" and cal.report()["settings"]["arrangement"] == "reference"
    zones = {z["zone_id"]: z for z in cal.zones}
    display_x = {z: 1 - edge(zones[z])[0] for z in zones}
    assert display_x["crash_ride"] < display_x["tom1"] < display_x["snare"] < display_x["hihat"]
    body = BodyReference(0, *BODY, 0.95)
    assert edge(zones["tom1"])[1] == pytest.approx(body.navel_y, abs=0.05)
    assert edge(zones["crash_ride"])[1] < edge(zones["tom1"])[1] - 0.1
    assert all(v["hits"] == 6 for v in cal.validation.values())


def test_grid_arrangement_report_is_unchanged():
    cal = AutomaticCalibration(ROI, provenance="SYNTHETIC")
    assert cal.arrangement == "grid" and "arrangement" not in cal.report()["settings"]
    with pytest.raises(ValueError, match="arrangement"):
        AutomaticCalibration(ROI, provenance="SYNTHETIC", arrangement="full")


def test_guide_keeps_product_floors_drums_in_front_of_the_torso_and_cymbals_clear():
    body = BodyReference(0, *BODY, 0.95)
    s = ReachSettings()
    pads = reference_guide_pads(
        body,
        ROI,
        min_width_px=s.min_width_px,
        min_height_px=s.min_height_px,
        gap_px=s.horizontal_gap_px,
        vertical_gap_px=s.vertical_gap_px,
        margin_px=s.margin_px,
    )
    check_kit_pads(pads, ROI, s)
    by = {p["zone_id"]: p for p in pads}
    torso = (1 - body.right, 1 - body.left)
    for zid in ("tom1", "snare"):  # drums overlap the torso's x span
        assert (
            by[zid]["x"] - by[zid]["width"] / 2 < torso[1] and by[zid]["x"] + by[zid]["width"] / 2 > torso[0]
        )
    assert by["crash_ride"]["x"] + by["crash_ride"]["width"] / 2 < torso[0]
    assert by["hihat"]["x"] - by["hihat"]["width"] / 2 > torso[1]


def strokes_at(points, n=5):
    out = []
    for target, (x, end_y) in points.items():
        for i in range(n):
            hand = "LEFT" if i % 2 else "RIGHT"
            out.append(ReachStroke(hand, target, i, i + 0.2, (x, end_y - 0.15), (x, end_y), ((x, end_y),)))
    return out


def test_fit_reports_reasons_for_reversed_or_crowded_targets():
    body = BodyReference(0, *BODY, 0.95)
    good = {"crash_ride": (0.78, 0.50), "tom1": (0.65, 0.71), "snare": (0.35, 0.71), "hihat": (0.22, 0.53)}
    assert fit_reach_reference(strokes_at(good), body, ROI)["passed"]
    swapped = {**good, "tom1": good["snare"], "snare": good["tom1"]}
    assert "TARGET_SIDES_REVERSED" in fit_reach_reference(strokes_at(swapped), body, ROI)["reasons"]
    crowded = {**good, "snare": (0.60, 0.71)}
    assert any(
        r.startswith("PAD_GAP_TOO_SMALL")
        for r in fit_reach_reference(strokes_at(crowded), body, ROI)["reasons"]
    )
    inward = {**good, "crash_ride": (0.62, 0.50)}
    reasons = fit_reach_reference(strokes_at(inward), body, ROI)["reasons"]
    assert "CYMBAL_INTERSECTS_TORSO:crash_ride" in reasons
    few = {k: v for k, v in good.items() if k != "hihat"}
    assert fit_reach_reference(strokes_at(few), body, ROI)["reasons"] == ["MORE_MEASURED_STROKES_REQUIRED"]
    assert np.isfinite(body.navel_y)
