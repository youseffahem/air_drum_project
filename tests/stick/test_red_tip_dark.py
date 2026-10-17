"""SYNTHETIC dim-light caps (opt-in dark-paint pass), modelled on the owner's 2026-10-16 recording at playing
distance (exposure -5): caps ~11 px across, H ~150 (signed -30), S ~100, V ~38 on a teal wall. Not
real-camera evidence: that recording is scored with scripts/analyze_red_tips.py frames --labels."""

import math

import numpy as np
import pytest

from spacedrums.contracts import HandId
from spacedrums.stick.red_tip import RedTipDetector, RedTipSettings
from spacedrums.stick.red_tip_estimator import RedTipEndpointEstimator
from spacedrums.stick.red_tip_synthetic import background, draw_blob, draw_stick, draw_tip, path_frames

WALL = (160, 129, 66)  # the teal wall of the recording (BGR)
DARK_CAP = {"hue": 150, "sat": 105, "val": 40, "radius": 5.5, "length": 13.0, "highlight": 0.3}
DARK = RedTipSettings(detector="colour", dark_paint=True)
A = (300.4, 150.6)


def wall(seed=1):
    return background(rng=np.random.default_rng(seed), bgr=WALL)


def dark_blobs(img, settings=DARK):
    return [b for b in RedTipDetector(settings).detect(img).blobs if b.dark]


def test_a_dim_cap_is_invisible_to_the_red_seeds_and_found_by_the_dark_pass():
    img = wall()
    draw_stick(img, A, angle_deg=-90, shaft_px=150, **DARK_CAP)
    assert RedTipDetector().detect(img).blobs == ()  # the default (red) path: what the live sessions showed
    blobs = dark_blobs(img)
    assert len(blobs) == 1 and math.dist(blobs[0].center, A) < 1.5
    assert blobs[0].surround >= DARK.dark_birth_surround  # held up against the wall


@pytest.mark.parametrize("angle", [-90, -70, -115])
def test_a_dim_cap_merged_with_a_dark_shaft_is_cut_free_at_its_wider_end(angle):
    img = wall()
    draw_stick(img, A, angle_deg=angle, shaft_px=150, wood_hsv=(150, 80, 33), **DARK_CAP)  # shaft as dark
    blobs = dark_blobs(img)
    assert len(blobs) == 1 and math.dist(blobs[0].center, A) < 3.0


def test_purple_cloth_dark_skin_and_wood_are_not_dark_paint():
    img = wall()
    draw_blob(img, (120, 380), 30, hue=140, sat=70, val=110)  # light purple blanket
    draw_blob(img, (300, 380), 9, hue=8, sat=110, val=45)  # skin in shadow
    draw_blob(img, (480, 380), 7, hue=15, sat=120, val=40, axes=(4, 25))  # dark wood
    assert dark_blobs(img) == []


def test_a_dim_cap_in_front_of_a_dark_shirt_has_no_context_to_start_a_track():
    img = background(rng=np.random.default_rng(2), bgr=(28, 24, 26))  # black shirt
    draw_tip(img, A, **DARK_CAP)
    blobs = dark_blobs(img)
    assert len(blobs) == 1 and blobs[0].surround < DARK.dark_birth_surround


def test_a_dark_track_is_used_only_after_its_longer_birth_and_reports_dark_evidence():
    est = RedTipEndpointEstimator(DARK)
    path = [(420.0, 150.0 + 2 * k) for k in range(8)]
    states = []
    for view, truth in path_frames({"a": path}, exposure_fraction=0.0, tip_kw=DARK_CAP, decorate=_paint_wall):
        est.observe(view)
        st = est.frame.slots[HandId.LEFT]
        states.append(st.state)
        if st.measured:
            assert math.dist(st.tip, truth["a"]) < 1.5
            assert est.evidence[HandId.LEFT].reason == "RED_TIP_DARK"
            assert est.evidence[HandId.LEFT].confidence == DARK.dark_confidence
    assert states[:3] == ["NO_TRACK"] * 3 and states[3:] == ["DARK"] * 5  # 4 frames to confirm, then measured


def _paint_wall(img, k):
    img[:] = wall(k)


def test_dark_paint_is_off_by_default_and_validated():
    assert RedTipSettings().dark_paint is False
    for bad in ({"dark_hue_min": 10, "dark_hue_max": 5}, {"dark_v_min": 120}, {"dark_min_area_px": 300},
                {"dark_birth_frames": 0}, {"dark_birth_surround": 1.5}, {"dark_max_elongation": 0.5}):
        with pytest.raises(ValueError):
            RedTipSettings(**bad)
