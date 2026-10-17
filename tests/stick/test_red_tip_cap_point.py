"""SYNTHETIC painted caps at the owner photo's size and colours (2026-10-16): the cap point, reflections,
paint runs on the shaft, skin / lips / ear, sizes, orientations, hue and brightness. Not real-camera evidence:
real footage is scored with scripts/analyze_red_tips.py frames --labels."""

import math

import numpy as np
import pytest

from spacedrums.stick.red_tip import RedTipDetector, RedTipSettings
from spacedrums.stick.red_tip_synthetic import REAL_CAP, background, draw_blob, draw_stick, draw_tip, hsv_bgr

WALL = (150, 140, 90)  # the teal wall behind the owner (BGR)
A, B = (200.3, 180.6), (430.7, 210.2)


def wall(seed=1):
    return background(rng=np.random.default_rng(seed), bgr=WALL)


def textured(img, center, axes, *, hue, sat, val, jitter=(2.5, 15.0), seed=0):
    """A skin-like ellipse whose hue / saturation vary per pixel (an ear, lips, a cheek)."""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    inside = ((xx - center[0]) / axes[0]) ** 2 + ((yy - center[1]) / axes[1]) ** 2 <= 1
    n = int(inside.sum())
    hues = (hue + rng.normal(0, jitter[0], n)) % 180
    hsv = np.stack([hues, np.clip(sat + rng.normal(0, jitter[1], n), 0, 255), np.full(n, val)], axis=1)
    img[inside] = [hsv_bgr(*px) for px in hsv]


def only(det, n=1):
    assert len(det.blobs) == n, [(b.center, b.area, b.seed_fraction) for b in det.blobs]
    return det.blobs


def test_two_painted_caps_on_their_sticks_are_two_cap_points():
    img = wall()
    draw_stick(img, A, angle_deg=-85, shaft_px=250, highlight=0.3, highlight_offset=(-3, -4))
    draw_stick(img, B, angle_deg=-95, shaft_px=250, highlight=0.3, highlight_offset=(2, -5), seed=1)
    blobs = sorted(only(RedTipDetector().detect(img), 2), key=lambda b: b.center[0])
    assert math.dist(blobs[0].center, A) < 1.0 and math.dist(blobs[1].center, B) < 1.0
    assert all(b.seed_fraction > 0.8 and not b.weak for b in blobs)


@pytest.mark.parametrize(("size", "offset", "tolerance"), [
    (0.3, (0.0, 0.0), 0.5), (0.5, (0.0, 0.0), 0.5),  # central reflection
    (0.3, (-4.0, -5.0), 1.5), (0.35, (6.0, -6.0), 2.0),  # towards the rim
    (0.45, (9.0, 2.0), 2.0),  # a reflection that cuts the outline: bridged inside the paint's hull
])
def test_a_white_reflection_never_splits_a_cap_and_barely_moves_its_point(size, offset, tolerance):
    img = wall()
    draw_stick(img, A, shaft_px=200, highlight=size, highlight_offset=offset)
    blob = only(RedTipDetector().detect(img))[0]
    assert math.dist(blob.center, A) < tolerance


def test_a_reflection_bridge_never_adds_the_bright_wall_around_a_cap():
    img = background(rng=np.random.default_rng(1), bgr=(235, 238, 240))  # white wall, bright as a reflection
    draw_stick(img, A, shaft_px=200, highlight=0.35)
    plain = RedTipDetector(RedTipSettings(s_highlight_max=0)).detect(img)
    bridged = RedTipDetector().detect(img)
    assert only(bridged)[0].area == pytest.approx(only(plain)[0].area, rel=0.05)
    assert math.dist(bridged.blobs[0].center, A) < 1.0


@pytest.mark.parametrize("run_px", [20, 40, 60])
@pytest.mark.parametrize("angle", [-90, -65, -120, 160])
def test_paint_run_down_the_shaft_reports_the_cap_not_the_red_region(run_px, angle):
    clean = wall()
    draw_stick(clean, A, angle_deg=angle, shaft_px=220, highlight=0.3, highlight_offset=(-3, -4))
    img = wall()
    draw_stick(img, A, angle_deg=angle, shaft_px=220, run_px=run_px, highlight=0.3, highlight_offset=(-3, -4))
    blob = only(RedTipDetector().detect(img))[0]
    assert math.dist(blob.center, A) < 3.5
    if blob.area > 1.3 * only(RedTipDetector().detect(clean))[0].area:  # the run joined the cap's region:
        assert math.dist(blob.region_center, A) > math.dist(blob.center, A) + 2  # its centroid lies lower


def test_a_long_paint_run_joins_the_region_but_never_moves_the_cap_point():
    img = wall()
    draw_stick(img, A, angle_deg=-90, shaft_px=220, run_px=60, highlight=0.3, highlight_offset=(-3, -4))
    blob = only(RedTipDetector().detect(img))[0]
    assert blob.area > 1500  # cap ~740 px^2 + the run
    assert math.dist(blob.center, A) < 3.0
    assert math.dist(blob.region_center, A) > 15  # what the first version reported


@pytest.mark.parametrize("radius", [4.0, 7.0, 13.0, 18.0])
@pytest.mark.parametrize("angle", [0.0, -45.0, -90.0, 30.0, 120.0])
def test_cap_sizes_and_orientations(radius, angle):
    img = wall()
    draw_tip(img, A, length=2.6 * radius, radius=radius, angle_deg=angle, highlight=0.3)
    blob = only(RedTipDetector().detect(img))[0]
    assert math.dist(blob.center, A) < 1.0


@pytest.mark.parametrize("hue", [174, 177, 0, 2, 4])
@pytest.mark.parametrize(("brightness", "sat"), [(0.5, 215), (0.75, 175), (1.0, 190), (1.25, 160)])
def test_hue_saturation_and_brightness_variation_of_the_paint(hue, brightness, sat):
    img = wall()
    draw_tip(img, A, hue=hue, sat=sat, brightness=brightness, highlight=0.3, **REAL_CAP)
    blob = only(RedTipDetector().detect(img))[0]
    assert math.dist(blob.center, A) < 1.0


@pytest.mark.parametrize(("hue", "sat"), [(12, 200), (20, 230), (160, 200), (150, 220)])
def test_orange_and_magenta_paint_are_not_tips(hue, sat):
    img = wall()
    draw_tip(img, A, hue=hue, sat=sat, **REAL_CAP)
    assert RedTipDetector().detect(img).blobs == ()


def test_skin_lips_and_ear_are_rejected_while_a_cap_beside_them_is_kept():
    img = wall()
    # Measured on the owner photo: ear H ~4 / S ~134, lips H ~5-6 / S ~130-136 (dark), cheek H 10-13.
    textured(img, (320, 120), (60, 70), hue=11, sat=136, val=150, seed=1)  # face
    textured(img, (250, 130), (10, 22), hue=4, sat=134, val=137, jitter=(3.0, 20.0), seed=2)  # ear
    textured(img, (320, 165), (24, 9), hue=5, sat=136, val=70, jitter=(3.0, 20.0), seed=3)  # lips
    det = RedTipDetector().detect(img)
    assert det.blobs == ()
    draw_stick(img, (330.2, 250.4), shaft_px=200, highlight=0.3)
    blob = only(RedTipDetector().detect(img))[0]
    assert math.dist(blob.center, (330.2, 250.4)) < 1.0


def test_a_face_touching_the_cap_is_never_absorbed_into_it():
    alone = wall()
    draw_stick(alone, A, shaft_px=200, highlight=0.3)
    touching = wall()
    textured(touching, (A[0] + 45, A[1]), (35, 50), hue=8, sat=150, val=140, seed=4)  # skin right against it
    draw_stick(touching, A, shaft_px=200, highlight=0.3)
    ref, blob = only(RedTipDetector().detect(alone))[0], only(RedTipDetector().detect(touching))[0]
    # Growth is bounded (grow_px): the face adds at most a thin rim, moving the point ~2 px toward it.
    assert math.dist(blob.center, A) < 2.5
    assert blob.area == pytest.approx(ref.area, rel=0.2)


def test_no_red_tip_in_view_gives_no_blob():
    img = wall()
    draw_blob(img, (320, 240), 60, hue=15, sat=150, val=170, axes=(12, 200))  # a bare wooden stick
    det = RedTipDetector().detect(img)
    assert det.blobs == () and det.rejected == ()


def test_moderate_blur_stays_a_strong_cap_near_mid_exposure_and_fast_blur_needs_a_track():
    img = wall()
    draw_tip(img, (300.0, 260.0), blur_from=(300.0, 248.0), **REAL_CAP)
    blob = only(RedTipDetector().detect(img))[0]
    assert abs(blob.center[0] - 300) < 1.0 and 250 < blob.center[1] < 258
    streak = wall()
    draw_tip(streak, (300.0, 330.0), blur_from=(300.0, 270.0), **REAL_CAP)  # 60 px in one exposure
    det = RedTipDetector()
    found = det.detect(streak)
    assert found.blobs == ()  # a streak never starts a track ...
    weak = det.detect_weak(found.hsv, (300.0, 300.0), 90)  # ... but a track's gate recovers it
    assert weak and weak[0].weak and abs(weak[0].center[1] - 300) < 4  # mid-exposure


def test_new_settings_are_validated():
    for bad in ({"hue_margin_weak": 90}, {"min_seed_fraction": 1.5}, {"min_seed_px": 0}, {"grow_px": -1},
                {"head_contrast": 0}, {"head_length_factor": 0}, {"v_highlight": 300}):
        with pytest.raises(ValueError):
            RedTipSettings(**bad)


def test_a_long_blur_streak_is_a_core_for_tracked_tips_only_never_a_new_tip():
    img = wall()
    draw_tip(img, (300.0, 300.0), blur_from=(300.0, 256.0), **REAL_CAP)  # 44 px in one exposure
    det = RedTipDetector().detect(img)
    assert det.blobs == ()  # growth outweighs the diluted seeds: not a birth candidate ...
    assert len(det.cores) == 1 and det.cores[0].core_only and not det.cores[0].weak  # ... but strong paint
    assert abs(det.cores[0].center[0] - 300) < 1.0 and abs(det.cores[0].center[1] - 278) < 4  # mid-exposure
