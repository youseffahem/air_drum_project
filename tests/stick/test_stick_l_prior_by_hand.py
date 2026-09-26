"""Phase 14 per-hand L_prior (ADR-0037) in the Phase 03 GEOM estimator; SYNTHETIC frames, never evidence.

With no stick in the frame the GEOM tip is ``grip + L * prior direction``, so the recorded
``stick_length_est`` (ROI-height units) is exactly the prior the estimator used for that hand.
"""

import numpy as np
import pytest

from spacedrums.capture import Roi, crop_roi
from spacedrums.contracts import FrameSample, FrameView, HandId, HandObservation, ImageRef, TimestampSource
from spacedrums.stick import GeomSettings, GeomTipEstimator, StickSettings

ROI = Roi(40, 20, 560, 440)


def view() -> FrameView:
    full = np.full((480, 640, 3), 60, np.uint8)  # no stick: the axis is never found
    s = FrameSample(
        frame_id=0,
        t_capture=1.0,
        t_frame_available=1.001,
        timestamp_source=TimestampSource.REPLAY,
        frame_size_px=(640, 480),
        roi_px=ROI.as_tuple(),
        image_ref=ImageRef.memory(full),
        camera_profile_id="synthetic",
        dropped_since_last=0,
    )
    return FrameView(sample=s, roi=crop_roi(full, ROI), full=full)


def hand(h: HandId) -> HandObservation:
    grip = np.array([280.0, 350.0])
    lm = np.zeros((21, 2))
    lm[0] = grip + [12, 27]
    for f, k in enumerate((5, 9, 13, 17)):
        base = grip + [0, f * 10]
        lm[k], lm[k + 1], lm[k + 2], lm[k + 3] = base, base + [8, 0], base + [15, 0], base + [21, 0]
    lm[1], lm[2], lm[3], lm[4] = grip + [6, 10], grip + [10, 4], grip + [12, -3], grip + [13, -9]
    norm = tuple((float(x / ROI.w), float(y / ROI.h)) for x, y in lm)
    return HandObservation(
        frame_id=0,
        t_capture=1.0,
        hand_id=h,
        present=True,
        detector_id="synthetic",
        landmarks=norm,
        landmark_visibility=None,
        handedness_score=0.9,
        bbox=(0, 0, 1, 1),
    )


def test_per_hand_prior_is_used_per_hand():
    est = GeomTipEstimator(
        StickSettings(geom=GeomSettings(l_prior_by_hand=(("LEFT", 0.31), ("RIGHT", 0.24))))
    )
    left = est.estimate(view(), hand(HandId.LEFT))
    right = est.estimate(view(), hand(HandId.RIGHT))
    assert left.stick_length_est == pytest.approx(0.31) and right.stick_length_est == pytest.approx(0.24)


def test_without_calibration_the_shared_prior_is_unchanged():
    est = GeomTipEstimator(StickSettings())
    for h in (HandId.LEFT, HandId.RIGHT):
        assert est.estimate(view(), hand(h)).stick_length_est == pytest.approx(0.27)


def test_settings_validation_and_config():
    with pytest.raises(ValueError):
        GeomSettings(l_prior_by_hand=(("LEFT", 0.0),))
    with pytest.raises(ValueError):
        GeomSettings(l_prior_by_hand=(("FOOT", 0.3),))
    geom = {
        "l_prior": 0.27,
        "no_axis_confidence_factor": 0.4,
        "refine_online": False,
        "refine_alpha": 0.05,
        "refine_min_axis_confidence": 0.7,
        "refine_support_range": [0.6, 1.4],
        "l_prior_by_hand": {"RIGHT": 0.25, "LEFT": 0.3},
    }
    g = GeomSettings.from_config({"geom": geom})
    assert g.l_prior_by_hand == (("LEFT", 0.3), ("RIGHT", 0.25)) and g.prior(HandId.RIGHT) == 0.25
