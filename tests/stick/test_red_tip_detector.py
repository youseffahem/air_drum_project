"""SYNTHETIC red-tip segmentation: brightness, hue wrap, reflections, blur, occlusion, distractors."""

import math

import cv2
import numpy as np
import pytest

from spacedrums.stick.red_tip import RedTipDetector, RedTipSettings
from spacedrums.stick.red_tip_synthetic import background, draw_blob, draw_tip, hsv_bgr, occlude, speckles

TIP = (301.3, 207.6)


def scene(seed=3, **kw):
    img = background(rng=np.random.default_rng(seed))
    draw_tip(img, TIP, **kw)
    return img


@pytest.mark.parametrize("brightness", [0.35, 0.6, 1.0, 1.3])
@pytest.mark.parametrize("hue", [1, 4, 172, 178])
def test_tip_centre_across_brightness_and_both_sides_of_the_red_hue_wrap(brightness, hue):
    d = RedTipDetector().detect(scene(brightness=brightness, hue=hue))
    assert len(d.blobs) == 1
    assert math.dist(d.blobs[0].center, TIP) < 1.0
    assert not d.blobs[0].clipped and not d.blobs[0].weak


@pytest.mark.parametrize(("size", "offset", "tolerance"), [
    (0.35, (0.0, 0.0), 0.5), (0.6, (0.0, 0.0), 0.5),  # central reflection (the developer photo)
    (0.35, (2.5, -2.0), 1.0), (0.35, (-3.5, 1.5), 1.0),
    # A large reflection cutting the rim removes red outline: up to ~2 px (0.3 % of the ROI width).
    (0.6, (2.5, -2.0), 2.0), (0.6, (-3.5, 1.5), 2.0),
])
def test_glossy_reflection_never_splits_the_tip_and_barely_moves_it(size, offset, tolerance):
    d = RedTipDetector().detect(scene(highlight=size, highlight_offset=offset))
    assert len(d.blobs) == 1
    assert math.dist(d.blobs[0].center, TIP) < tolerance


def test_reflection_pixels_are_not_red_but_the_filled_tip_counts_them():
    plain = RedTipDetector().detect(scene(highlight=0.0)).blobs[0]
    glossy = RedTipDetector().detect(scene(highlight=0.5))
    cx, cy = map(round, TIP)
    assert glossy.mask[cy, cx] == 0  # the bright reflection itself fails the saturation floor
    assert glossy.blobs[0].area == pytest.approx(plain.area, rel=0.15)


def test_partly_occluded_tip_reports_the_visible_part_and_border_clipping_is_flagged():
    img = scene()
    occlude(img, (int(TIP[0]) + 1, 150, 40, 120))  # the right half is hidden
    blobs = RedTipDetector().detect(img).blobs
    assert len(blobs) == 1
    assert blobs[0].center[0] < TIP[0] and math.dist(blobs[0].center, TIP) < 6
    edge = background(rng=np.random.default_rng(1))
    draw_tip(edge, (2.0, 240.0))
    blob = RedTipDetector().detect(edge).blobs[0]
    assert blob.clipped and blob.score < 1


def test_motion_blur_streak_is_found_only_by_the_weak_floors_near_a_track():
    img = background(rng=np.random.default_rng(2))
    draw_tip(img, (300, 260), blur_from=(300, 200))
    det = RedTipDetector()
    d = det.detect(img)
    assert d.blobs == ()  # strong floors: the streak's paint is diluted below s_min
    weak = det.detect_weak(d.hsv, (300, 235), 60)
    assert weak and weak[0].weak
    assert abs(weak[0].center[1] - 230) < 4  # time-averaged position: the middle of the exposure path
    assert det.detect_weak(d.hsv, (100, 100), 40) == []


def test_speckles_large_red_surfaces_skin_and_dull_reds_are_rejected():
    rng = np.random.default_rng(5)
    img = background(rng=rng)
    speckles(img, rng, 300)
    draw_blob(img, (520, 360), 55, hue=178, sat=220, val=200)  # a red surface
    draw_blob(img, (120, 120), 20, hue=12, sat=95, val=170)  # skin tone
    draw_blob(img, (120, 300), 14, hue=8, sat=70, val=150)  # dull red-brown
    d = RedTipDetector().detect(img)
    assert d.blobs == ()
    assert d.reject_counts["TOO_SMALL"] > 0 and d.reject_counts["TOO_LARGE"] == 1
    assert [b.reason for b in d.rejected] == ["TOO_LARGE"]
    draw_tip(img, TIP)
    d = RedTipDetector().detect(img)
    assert len(d.blobs) == 1 and math.dist(d.blobs[0].center, TIP) < 1.0


def test_skin_under_warm_dim_light_is_not_a_tip():
    # Measured in the developer room (data/dev-captures): skin passing H <= 10 / S >= 120 sat at hue 6-10,
    # S ~140, V ~80. The defaults keep it out; painted red stays in.
    img = background(rng=np.random.default_rng(6), bgr=(30, 40, 50))
    for k, (hue, sat) in enumerate(((8, 150), (6, 165), (10, 140), (9, 175))):
        draw_blob(img, (120 + 110 * k, 120), 16, hue=hue, sat=sat, val=90)
    assert RedTipDetector().detect(img).blobs == ()
    draw_tip(img, TIP, brightness=0.45)
    assert len(RedTipDetector().detect(img).blobs) == 1


def test_long_red_line_is_rejected_as_too_elongated():
    img = background(rng=np.random.default_rng(4))
    cv2.line(img, (100, 400), (400, 400), tuple(int(v) for v in hsv_bgr(178, 220, 200)), 3)
    d = RedTipDetector().detect(img)
    assert d.blobs == () and d.reject_counts["TOO_ELONGATED"] == 1


def test_ignore_regions_mask_a_known_red_object_in_camera_coordinates():
    img = scene()
    settings = RedTipSettings(ignore_regions=((0.45, 0.38, 0.5, 0.48),))  # covers TIP (0.47, 0.43)
    assert RedTipDetector(settings).detect(img).blobs == ()
    elsewhere = RedTipSettings(ignore_regions=((0.0, 0.0, 0.2, 0.2),))
    assert len(RedTipDetector(elsewhere).detect(img).blobs) == 1


def test_two_tips_are_two_blobs_and_the_detector_keeps_no_state():
    img = scene()
    draw_tip(img, (450.0, 300.0))
    det = RedTipDetector()
    first, second = det.detect(img), det.detect(img)
    assert first.blobs == second.blobs and len(first.blobs) == 2


def test_settings_validate_ranges_and_the_tracking_threshold():
    for bad in ({"hue_low_max": 170, "hue_high_min": 165}, {"s_min_weak": 200}, {"min_area_px": 0},
                {"ignore_regions": ((0.5, 0.5, 0.4, 0.6),)}, {"max_tracks": 1}, {"gate_max_px": 10.0}):
        with pytest.raises(ValueError):
            RedTipSettings(**bad)
    cfg = {"product": {"stick_tip": {"observed_confidence": 0.5}}, "tracking": {"c_valid": 0.6}}
    with pytest.raises(ValueError, match="c_valid"):
        RedTipSettings.from_config(cfg)
    settings = RedTipSettings.from_config({"product": {"stick_tip": {"ignore_regions": [[0, 0, 0.1, 0.1]]}}})
    assert settings.ignore_regions == ((0.0, 0.0, 0.1, 0.1),)
