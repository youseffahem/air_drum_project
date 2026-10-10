"""SYNTHETIC checks of the developer layout preview: nudging, scaling, saving, rejection and reach."""

from types import SimpleNamespace

import numpy as np
import pytest

from spacedrums.calib.developer_demo import check_kit_pads
from spacedrums.calib.reach import ReachSettings
from spacedrums.capture import Roi
from spacedrums.contracts import HandId
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.kit_layout import kit_layout, load_pads
from spacedrums.ui.layout_preview import KEYS, LayoutPreview, reach_report
from spacedrums.ui.stage import StageRenderer

ROI = Roi(0, 0, 640, 480)
PADS = [
    {"zone_id": "crash", "x": 0.16, "y": 0.34, "width": 0.20, "height": 0.095},
    {"zone_id": "tom1", "x": 0.395, "y": 0.44, "width": 0.15, "height": 0.11},
    {"zone_id": "snare", "x": 0.36, "y": 0.68, "width": 0.21, "height": 0.13},
]


def floors(pads):
    check_kit_pads(pads, (640, 480), ReachSettings())


@pytest.fixture
def preview(tmp_path):
    return LayoutPreview(PADS, floors, save_dir=tmp_path)


def evidence(tip=None):
    return {h: SimpleNamespace(kind="MEASURED" if tip else "MISSING", tip=tip) for h in HandId}


def test_keys_shift_the_kit_in_the_displayed_direction(preview):
    moved = preview.handle_key(ord("l"))  # display right
    assert [p["x"] for p in moved] == pytest.approx([p["x"] + 0.01 for p in PADS])
    moved = preview.handle_key(ord("i"))  # display up
    assert [p["y"] for p in moved] == pytest.approx([p["y"] - 0.01 for p in PADS])
    assert preview.pads == moved and PADS[0]["x"] == 0.16  # the config pads are never mutated


def test_scale_keys_grow_and_shrink_the_whole_kit(preview):
    before = preview.pads[2]["width"]
    assert preview.handle_key(ord("]"))[2]["width"] > before
    assert preview.handle_key(ord("["))[2]["width"] == pytest.approx(before, rel=0.01)


def test_a_nudge_that_leaves_the_roi_or_breaks_a_floor_is_rejected_with_a_reason(preview):
    for _ in range(100):
        moved = preview.handle_key(ord("l"))
        if moved is None:
            break
    assert moved is None and preview.message.startswith("REJECTED")
    assert max(p["x"] + p["width"] / 2 for p in preview.pads) <= 1  # state stayed on the last valid layout
    kit_layout(preview.pads)
    small = LayoutPreview(PADS, floors)
    for _ in range(40):
        if small.handle_key(ord("[")) is None:
            break
    assert small.message.startswith("REJECTED") and "floors" in small.message


def test_unmapped_keys_do_nothing(preview):
    assert preview.handle_key(ord("x")) is None and preview.pads == PADS
    assert set(KEYS) == {ord(c) for c in "ijkl[]"}


def test_save_writes_a_loadable_validated_layout(preview, tmp_path):
    preview.handle_key(ord("j"))
    preview.handle_key(ord("s"))
    path = tmp_path / "kit-layout.yaml"
    assert preview.message == f"Saved {path}"
    loaded = load_pads(path)
    kit_layout(loaded)
    floors(loaded)
    assert loaded[0]["x"] == pytest.approx(0.15)
    assert LayoutPreview(PADS, floors).save() is None  # no directory, no file


def test_observe_collects_measured_tips_and_hits_without_emitting_anything(preview):
    commits = [SimpleNamespace(zone_id="snare"), SimpleNamespace(zone_id="snare")]
    preview.observe(evidence((0.6, 0.4)), SimpleNamespace(commits=commits))
    preview.observe(evidence(), SimpleNamespace(commits=[]))
    preview.observe(evidence((0.6, 0.5)), None)
    assert len(preview.tips[HandId.LEFT]) == 2 and preview.hits["snare"] == 2
    assert preview.display_tips(HandId.LEFT)[0].tolist() == pytest.approx([0.4, 0.4])  # x is mirrored


def test_reach_report_needs_samples_above_and_inside_the_top_edge():
    pad = {"zone_id": "snare", "x": 0.5, "y": 0.5, "width": 0.2, "height": 0.1}
    above, inside, outside = (0.5, 0.45), (0.5, 0.55), (0.9, 0.45)
    assert reach_report([pad], [above, inside])["snare"]["reached"]
    assert not reach_report([pad], [above])["snare"]["reached"]
    assert not reach_report([pad], [above, outside])["snare"]["reached"]
    assert reach_report([pad], np.empty((0, 2)))["snare"] == {"above": 0, "inside": 0, "reached": False}


def test_draw_overlays_coordinates_and_reach_without_touching_the_geometry(preview):
    registry = ZoneRegistry.from_config(kit_layout(PADS))
    renderer = StageRenderer()
    result = SimpleNamespace(sample=SimpleNamespace(t_capture=1.0), commits=[])
    frame = np.full((480, 640, 3), 90, np.uint8)
    img = renderer.render(frame, ROI, registry, evidence(), result)
    plain = img.copy()
    boxes = {z: (p.x, p.y, p.w, p.h) for z, p in renderer.pads.items()}
    for i in range(30):
        preview.observe(evidence((0.5, 0.3 + 0.01 * i)), None)
    preview.draw(img, renderer, ROI, 640)
    assert np.abs(img.astype(int) - plain).sum() > 0  # something was drawn
    assert boxes == {z: (p.x, p.y, p.w, p.h) for z, p in renderer.pads.items()}  # geometry untouched
