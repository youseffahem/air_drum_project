from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from spacedrums.geometry import Arc, Ellipse, Polygon, Segment, Zone, ZoneRegistry

ROOT = Path(__file__).resolve().parents[2]


def test_candidate_layouts_load_and_defaults_are_hand_agnostic():
    mvp = ZoneRegistry.load(ROOT / "configs/zones/mvp4.candidate.yaml")
    v1 = ZoneRegistry.load(ROOT / "configs/zones/v1-7.candidate.yaml")
    assert len(mvp) == 4 and len(v1) == 7
    assert {z.zone_id for z in mvp} == {"hihat", "snare", "tom1", "crash_ride"}
    assert all(tuple(map(str, z.allowed_hands)) == ("LEFT", "RIGHT") for z in (*mvp, *v1))
    assert all(str(z.trigger_type) == "HAND_TIP" for z in (*mvp, *v1))
    manifest = json.loads((ROOT / "assets/samples/recorded-manifest.json").read_text(encoding="utf-8"))
    sample_ids = {item["sample_id"] for item in manifest["samples"]}
    assert all(zone.sample_id in sample_ids for zone in (*mvp, *v1))


def test_ellipse_rotation_containment_and_boundary():
    ellipse = Ellipse((0.5, 0.5), 0.2, 0.1, math.pi / 2)
    assert ellipse.contains((0.5, 0.65))
    assert not ellipse.contains((0.65, 0.5))
    assert ellipse.on_boundary((0.5, 0.7))


def test_polygon_containment_boundary_and_outside():
    polygon = Polygon(((0.1, 0.2), (0.8, 0.2), (0.7, 0.8), (0.2, 0.7)))
    assert polygon.contains((0.4, 0.4))
    assert polygon.on_boundary((0.45, 0.2))
    assert not polygon.contains((0.95, 0.5))


def test_surface_on_boundary_and_inward_normal_validation(circle_zone):
    circle_zone.validate_surface()
    with pytest.raises(ValueError, match="surface"):
        Zone(
            "bad",
            "Bad",
            "HAND_TIP",
            Ellipse((0.5, 0.5), 0.2, 0.2),
            Segment((0.3, 0.5), (0.7, 0.5)),
            (0.0, 1.0),
            ("LEFT", "RIGHT"),
            "s",
            "g",
        )
    with pytest.raises(ValueError, match="does not point"):
        Zone(
            "bad",
            "Bad",
            "HAND_TIP",
            Ellipse((0.5, 0.5), 0.2, 0.2),
            Arc((0.5, 0.5), 0.2, 0.2, 0, math.pi, 2 * math.pi),
            (0.0, -1.0),
            ("LEFT", "RIGHT"),
            "s",
            "g",
        )


def test_polygon_surface_is_boundary_subset():
    zone = Zone(
        "p",
        "Polygon",
        "HAND_TIP",
        Polygon(((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8))),
        Segment((0.2, 0.2), (0.8, 0.2)),
        (0.0, 1.0),
        ("LEFT", "RIGHT"),
        "s",
        "g",
    )
    assert zone.shape.contains((0.5, 0.3))
