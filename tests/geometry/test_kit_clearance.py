"""SYNTHETIC checks of the pairwise pad-clearance rule, kit transforms and saved layouts."""

import pytest

from spacedrums.geometry.kit_layout import (
    kit_clearance_failures,
    kit_layout,
    load_pads,
    pad_clearance_px,
    save_pads,
    transform_pads,
)

SIZE = (640, 480)


def pad(zone_id, x, y, w=0.15, h=0.10):
    return {"zone_id": zone_id, "x": x, "y": y, "width": w, "height": h}


def test_clearance_is_signed_in_pixels():
    a, b = pad("snare", 0.2, 0.2), pad("tom1", 0.5, 0.2)
    dx, dy = pad_clearance_px(a, b, SIZE)
    assert dx == pytest.approx((0.3 - 0.15) * 640) and dy == pytest.approx(-0.10 * 480)


def test_a_pair_passes_when_either_axis_clears_its_floor():
    apart_x = [pad("snare", 0.2, 0.2), pad("tom1", 0.5, 0.2)]
    apart_y = [pad("snare", 0.2, 0.2), pad("tom1", 0.2, 0.5)]
    assert kit_clearance_failures(apart_x, SIZE, 32, 32) == []
    assert kit_clearance_failures(apart_y, SIZE, 32, 32) == []


def test_diagonal_neighbours_that_clear_neither_floor_are_rejected():
    # 10 px apart in x and 10 px apart in y: the old per-axis rule never compared these two.
    a = pad("snare", 0.2, 0.2)
    b = pad("tom1", 0.2 + 0.15 + 10 / 640, 0.2 + 0.10 + 10 / 480)
    failures = kit_clearance_failures([a, b], SIZE, 32, 32)
    assert [(f[0], f[1]) for f in failures] == [("snare", "tom1")]
    assert failures[0][2] == pytest.approx(10) and failures[0][3] == pytest.approx(10)


def test_transform_shifts_and_scales_about_the_centroid():
    pads = [pad("snare", 0.3, 0.5), pad("tom1", 0.7, 0.5)]
    moved = transform_pads(pads, dx=0.02, dy=-0.01)
    assert [p["x"] for p in moved] == [0.32, 0.72] and [p["y"] for p in moved] == [0.49, 0.49]
    grown = transform_pads(pads, scale=1.1)
    assert grown[0]["width"] == pytest.approx(0.165) and grown[0]["height"] == pytest.approx(0.11)
    # the centroid of the pad centres stays put and the centres spread by the same factor
    assert (grown[0]["x"] + grown[1]["x"]) / 2 == pytest.approx(0.5)
    assert grown[1]["x"] - grown[0]["x"] == pytest.approx(0.44)
    assert [p["zone_id"] for p in grown] == ["snare", "tom1"] and pads[0]["x"] == 0.3  # input untouched


def test_transform_rejects_nonsense_and_leaves_validation_to_the_caller():
    with pytest.raises(ValueError):
        transform_pads([pad("snare", 0.5, 0.5)], scale=0)
    pushed = transform_pads([pad("snare", 0.9, 0.5)], dx=0.1)
    with pytest.raises(ValueError, match="inside"):
        kit_layout(pushed)


def test_saved_layout_round_trips_and_rejects_malformed_files(tmp_path):
    pads = [pad("snare", 0.3333333, 0.5), pad("tom1", 0.7, 0.5)]
    path = tmp_path / "kit-layout.yaml"
    save_pads(path, pads, note="test")
    loaded = load_pads(path)
    assert [p["zone_id"] for p in loaded] == ["snare", "tom1"] and loaded[0]["x"] == pytest.approx(0.3333)
    kit_layout(loaded)
    bad = tmp_path / "bad.yaml"
    bad.write_text("pads:\n  - {zone_id: snare, x: 0.5}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly"):
        load_pads(bad)
    bad.write_text("nothing: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pads"):
        load_pads(bad)
