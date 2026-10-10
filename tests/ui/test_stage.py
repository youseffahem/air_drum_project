"""SYNTHETIC checks of the animated full-kit view. No camera or window is opened."""

from types import SimpleNamespace

import numpy as np
import pytest

from spacedrums.capture import Roi
from spacedrums.contracts import HandId
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.kit_layout import kit_layout
from spacedrums.ui.stage import FLASH_S, RIPPLE_S, StageRenderer

ROI = Roi(0, 0, 640, 480)
PADS = [
    {"zone_id": "snare", "x": 0.45, "y": 0.68, "width": 0.20, "height": 0.11},
    {"zone_id": "crash", "x": 0.13, "y": 0.42, "width": 0.17, "height": 0.10},
]


@pytest.fixture
def registry():
    return ZoneRegistry.from_config(kit_layout(PADS))


def frame():
    return np.full((480, 640, 3), 90, np.uint8)


def evidence(tip=None):
    def one(hand):
        if tip is None:
            return SimpleNamespace(kind="MISSING", tip=None)
        return SimpleNamespace(kind="MEASURED", tip=tip)

    return {h: one(h) for h in HandId}


def result(t, zones=()):
    commits = [SimpleNamespace(zone_id=z, hand_id=HandId.RIGHT, gain=1.0) for z in zones]
    return SimpleNamespace(sample=SimpleNamespace(t_capture=t), commits=commits)


def pad_pixels(renderer, image, zone):
    pad = renderer.pads[zone]
    return image[pad.y : pad.y + pad.h, pad.x : pad.x + pad.w].astype(int)


def test_output_is_upscaled_and_layout_is_mirrored(registry):
    renderer = StageRenderer()
    img = renderer.render(frame(), ROI, registry, evidence(), result(1.0))
    assert img.shape == (720, 960, 3)
    # kit_layout takes display x, so the display-left crash must land on the display's left.
    assert renderer.pads["crash"].x < renderer.pads["snare"].x
    assert renderer.pads["snare"].w == pytest.approx(0.20 * 640 * 1.5, abs=3)


def test_hit_flashes_then_returns_to_the_resting_pad(registry):
    renderer = StageRenderer()
    rest = renderer.render(frame(), ROI, registry, evidence(), result(1.0))
    hit = renderer.render(frame(), ROI, registry, evidence(), result(1.01, ["snare"]))
    end = 1.01 + max(FLASH_S, RIPPLE_S * 2) + 0.1
    later = renderer.render(frame(), ROI, registry, evidence(), result(end))
    assert renderer.total == 1 and renderer.last_name == "Snare"
    before, during, after = (pad_pixels(renderer, i, "snare") for i in (rest, hit, later))
    assert np.abs(during - before).mean() > 8  # the accent flash is clearly visible
    assert np.abs(after - before).mean() < 2  # and fully decayed afterwards
    quiet = pad_pixels(renderer, hit, "crash")
    assert np.abs(quiet - pad_pixels(renderer, rest, "crash")).mean() < 2  # other pads unaffected


def test_combo_counts_fast_repeats_and_resets_after_a_pause(registry):
    renderer = StageRenderer()
    for i in range(4):
        renderer.render(frame(), ROI, registry, evidence(), result(1.0 + 0.2 * i, ["snare"]))
    assert renderer.combo == 4
    renderer.render(frame(), ROI, registry, evidence(), result(5.0, ["crash"]))
    assert renderer.combo == 1 and renderer.total == 5


def test_fingertip_trail_follows_gaps_and_loss(registry):
    renderer = StageRenderer()
    for i in range(5):
        renderer.render(frame(), ROI, registry, evidence((0.5, 0.3 + 0.02 * i)), result(1.0 + i / 30))
    assert len(renderer.trails[HandId.LEFT]) == 5
    renderer.render(frame(), ROI, registry, evidence(), result(1.2))
    assert not renderer.trails[HandId.LEFT]


def test_diagnostic_free_hud_works_without_audio_and_registry_swap_rebuilds(registry):
    renderer = StageRenderer()
    renderer.render(frame(), ROI, registry, evidence(), result(1.0), audio=None, latency_ms=None)
    other = ZoneRegistry.from_config(kit_layout(PADS[:1]))
    renderer.render(frame(), ROI, other, evidence(), result(1.1))
    assert list(renderer.pads) == ["snare"]


def test_render_cost_stays_inside_the_frame_budget(registry):
    import time

    renderer = StageRenderer()
    f = frame()
    for i in range(10):
        renderer.render(f, ROI, registry, evidence((0.5, 0.5)), result(1.0 + i / 30))
    start = time.perf_counter()
    n = 60
    for i in range(n):
        hits = ["snare"] if i % 8 == 0 else ()
        renderer.render(f, ROI, registry, evidence((0.45, 0.6)), result(2.0 + i / 30, hits))
    per_frame_ms = (time.perf_counter() - start) * 1000 / n
    assert per_frame_ms < 25, per_frame_ms  # generous CI bound; the live report logs the real render_ms
    print(f"stage render: {per_frame_ms:.1f} ms/frame")


# -- rendered pads must be the hit zones ---------------------------------------------------------

FULL_PADS = [
    {"zone_id": "crash", "x": 0.16, "y": 0.34, "width": 0.20, "height": 0.095},
    {"zone_id": "ride", "x": 0.83, "y": 0.36, "width": 0.20, "height": 0.095},
    {"zone_id": "tom1", "x": 0.395, "y": 0.44, "width": 0.15, "height": 0.11},
    {"zone_id": "tom2", "x": 0.60, "y": 0.42, "width": 0.15, "height": 0.11},
    {"zone_id": "hihat", "x": 0.15, "y": 0.52, "width": 0.19, "height": 0.09},
    {"zone_id": "snare", "x": 0.36, "y": 0.68, "width": 0.21, "height": 0.13},
    {"zone_id": "floor_tom", "x": 0.70, "y": 0.66, "width": 0.24, "height": 0.14},
]


def _polygon_mask(points, shape):
    import cv2

    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.round(np.asarray(points)).astype(np.int32)], 1)
    return mask.astype(bool)


@pytest.mark.parametrize("roi", [Roi(0, 0, 640, 480), Roi(40, 20, 560, 440)])
def test_rendered_pads_are_exactly_the_hit_zones(roi):
    zones = kit_layout(FULL_PADS)
    registry = ZoneRegistry.from_config(zones)
    renderer = StageRenderer()
    renderer.render(frame(), roi, registry, evidence(), result(1.0))
    for zone in registry:
        pad = renderer.pads[zone.zone_id]
        pts = np.array([renderer.to_display(p, roi, 640) for p in zone.shape.points])
        # the sprite box is the polygon's display bounding box
        assert pad.x == pytest.approx(np.floor(pts[:, 0].min()), abs=1)
        assert pad.y == pytest.approx(np.floor(pts[:, 1].min()), abs=1)
        assert pad.x + pad.w == pytest.approx(np.ceil(pts[:, 0].max()), abs=1)
        assert pad.y + pad.h == pytest.approx(np.ceil(pts[:, 1].max()), abs=1)
        # the strike edge drawn is the impact segment, mapped by the same function
        want = [renderer.to_display(q, roi, 640) for q in (zone.impact_surface.p0, zone.impact_surface.p1)]
        assert [pt[1] for pt in pad.edge] == pytest.approx([round(w[1]) for w in want], abs=1)
        assert [pt[0] for pt in pad.edge] == pytest.approx([round(w[0]) for w in want], abs=1)
        assert pad.edge[0][1] == pytest.approx(pad.y, abs=2)  # the edge is the top of the sprite
        # the visible footprint (alpha mask) covers the polygon it represents
        poly = _polygon_mask(pts - [pad.x, pad.y], (pad.h, pad.w))
        iou = (poly & pad.mask[..., 0]).sum() / (poly | pad.mask[..., 0]).sum()
        assert iou >= 0.95, (zone.zone_id, iou)


def test_display_left_pads_render_left_and_cymbals_are_flagged():
    registry = ZoneRegistry.from_config(kit_layout(FULL_PADS))
    renderer = StageRenderer()
    renderer.render(frame(), ROI, registry, evidence(), result(1.0))
    centre = {z: p.x + p.w / 2 for z, p in renderer.pads.items()}
    assert centre["crash"] < centre["tom1"] < centre["tom2"] < centre["ride"]
    assert centre["hihat"] < centre["snare"] < centre["floor_tom"]
    assert {z for z, p in renderer.pads.items() if p.cymbal} == {"crash", "ride", "hihat"}


def test_every_pad_has_a_distinct_accent_and_look():
    registry = ZoneRegistry.from_config(kit_layout(FULL_PADS))
    renderer = StageRenderer()
    renderer.render(frame(), ROI, registry, evidence(), result(1.0))
    assert len({p.accent for p in renderer.pads.values()}) == 7
    sprites = {z: p.sprite[..., :3].reshape(-1, 3).mean(axis=0) for z, p in renderer.pads.items()}
    drums = [sprites[z] for z in ("tom1", "tom2", "floor_tom")]
    assert np.abs(sprites["snare"] - drums[0]).max() > 30  # snare head is not a tom head
    assert np.abs(sprites["crash"] - sprites["snare"]).max() > 30  # cymbal metal is not a drum head
