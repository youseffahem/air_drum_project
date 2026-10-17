"""SYNTHETIC checks that the native-resolution preview (ADR-0047) changes display pixels only.

The preview is the tracking field of view at 1.5x; every overlay must land where it lands on the
1.5x upscale of the tracking frame, and the tracker's ROI-pixel coordinates must be scaled once.
No camera or window opens.
"""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from spacedrums.app.play import display_roi
from spacedrums.capture import Roi
from spacedrums.contracts import HandId
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.kit_layout import kit_layout
from spacedrums.stick.red_tip_estimator import RedTipEndpointEstimator
from spacedrums.stick.red_tip_synthetic import path_frames
from spacedrums.ui.developer_demo import DemoOverlay
from spacedrums.ui.stage import StageRenderer

ROI = Roi(0, 0, 640, 480)
REGISTRY = ZoneRegistry.from_config(kit_layout([
    {"zone_id": "snare", "x": 0.45, "y": 0.68, "width": 0.20, "height": 0.11},
    {"zone_id": "crash", "x": 0.13, "y": 0.42, "width": 0.17, "height": 0.10},
]))


def scene(w, h):
    """A smooth gradient with a sharp checker patch (the patch is where native detail shows)."""
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.stack([60 + 100 * xx / w, 60 + 100 * yy / h, np.full((h, w), 110.0)], axis=-1)
    patch = ((xx // max(1, w // 160) + yy // max(1, w // 160)) % 2).astype(bool)
    box = (yy > h * 0.2) & (yy < h * 0.35) & (xx > w * 0.2) & (xx < w * 0.4)
    img[box & patch] = 230
    img[box & ~patch] = 20
    return img.astype(np.uint8)


def detail(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.mean(cv2.Laplacian(g, cv2.CV_32F) ** 2))


def stage_result(t):
    return SimpleNamespace(sample=SimpleNamespace(t_capture=t), commits=[])


def evidence(tip=None):
    return {h: SimpleNamespace(kind="MEASURED" if tip else "MISSING", tip=tip, origin=tip) for h in HandId}


def test_display_roi_scales_every_edge():
    assert display_roi(Roi(40, 20, 560, 440), 1.5).as_tuple() == (60, 30, 840, 660)
    assert display_roi(ROI, 1.0) is ROI


def test_stage_uses_the_native_window_instead_of_the_upscale():
    native = scene(960, 720)
    tracking = cv2.resize(native, (640, 480), interpolation=cv2.INTER_AREA)
    old, new = StageRenderer(), StageRenderer()
    a = old.render(tracking, ROI, REGISTRY, evidence(), stage_result(1.0))
    b = new.render(tracking, ROI, REGISTRY, evidence(), stage_result(1.0), preview=native)
    assert a.shape == b.shape == (720, 960, 3)
    assert {k: (p.x, p.y, p.w, p.h) for k, p in old.pads.items()} == \
        {k: (p.x, p.y, p.w, p.h) for k, p in new.pads.items()}  # the kit does not move
    region = (slice(150, 250), slice(600, 760))  # the checker patch, mirrored
    assert detail(b[region]) > 1.5 * detail(a[region])  # more real detail where the scene has it
    smooth = (slice(450, 520), slice(60, 200))
    assert np.abs(a[smooth].astype(int) - b[smooth].astype(int)).mean() < 3  # same picture elsewhere


def test_stage_without_a_preview_is_unchanged_by_the_option():
    tracking = scene(640, 480)
    a = StageRenderer().render(tracking, ROI, REGISTRY, evidence(), stage_result(1.0))
    b = StageRenderer().render(tracking, ROI, REGISTRY, evidence(), stage_result(1.0), preview=None)
    assert np.array_equal(a, b)


def test_stage_resizes_a_preview_of_another_size():
    tracking = scene(640, 480)
    img = StageRenderer().render(tracking, ROI, REGISTRY, evidence(), stage_result(1.0),
                                 preview=scene(1280, 960))
    assert img.shape == (720, 960, 3)


def demo_render(full, roi, tips=None, tip_ev=None, scale=1.0, tip=(0.25, 0.5)):
    result = SimpleNamespace(sample=SimpleNamespace(t_capture=1.0), commits=[],
                             hands={h: SimpleNamespace(candidates=()) for h in HandId})
    ev = tip_ev or evidence(tip)
    return DemoOverlay().render(full, roi, REGISTRY, ev, result, dropped=0, perception_ms=1.0,
                                audio_state="DISABLED", stroke_diagnostics={}, tip_diagnostics=tips,
                                px_scale=scale)


def green(img):
    return np.all(img == (60, 255, 100), axis=-1)


def test_demo_overlay_draws_normalised_points_at_the_same_place_on_the_preview():
    small = demo_render(np.full((480, 640, 3), 90, np.uint8), ROI)
    big = demo_render(np.full((720, 960, 3), 90, np.uint8), display_roi(ROI, 1.5), scale=1.5)
    ys, xs = np.nonzero(green(small))
    yb, xb = np.nonzero(green(big))
    assert xs.size and xb.size
    assert xb.mean() == pytest.approx(1.5 * xs.mean(), abs=1.5)  # mirrored tip at camera x 0.25
    assert yb.mean() == pytest.approx(1.5 * ys.mean(), abs=1.5)


def test_red_tip_pixel_coordinates_are_scaled_once():
    est = RedTipEndpointEstimator()
    for view, _ in path_frames({"a": [(450.0, 200.0)] * 4, "b": [(180.0, 260.0)] * 4}, exposure_fraction=0.0):
        est.observe(view)
    tips, ev = est.frame, dict(est.evidence)
    tip = tips.slots[HandId.LEFT].tip
    big = demo_render(np.full((720, 960, 3), 90, np.uint8), display_roi(ROI, 1.5), tips, ev, 1.5)
    plain = demo_render(np.full((720, 960, 3), 90, np.uint8), display_roi(ROI, 1.5), None, ev, 1.5)
    x, y = 959 - round(1.5 * tip[0]), round(1.5 * tip[1])  # mirrored display pixel of the tracked tip
    assert not np.array_equal(plain[y - 3:y + 4, x - 3:x + 4], big[y - 3:y + 4, x - 3:x + 4])
    xu, yu = 959 - round(tip[0]), round(tip[1])  # the unscaled position stays untouched by tip markers
    assert np.array_equal(plain[yu - 2:yu + 3, xu - 2:xu + 3], big[yu - 2:yu + 3, xu - 2:xu + 3])
