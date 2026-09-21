"""TEST-HANDS-1: the coordinate boundary of ``hands`` (native -> ROI-normalized, ADR-0005).

Phase 03 unit test "coordinate conversion at the hands boundary" (phase document, Tests).
"""

from __future__ import annotations

import numpy as np
import pytest

from spacedrums.capture import Roi, px_to_norm_point
from spacedrums.hands import DetectorInput, InputFrame, bbox_of, native_to_full_px, native_to_roi_norm

ROI = Roi(40, 20, 560, 440)  # the Phase 02 candidate ROI on a 640x480 frame


def test_roi_input_is_identity_up_to_float():
    inp = InputFrame.for_roi(ROI)
    native = np.array([[0.0, 0.0], [1.0, 1.0], [0.25, 0.75], [1.3, -0.2]])
    out = native_to_roi_norm(native, inp, ROI)
    assert out == pytest.approx(native, abs=1e-12)


def test_full_frame_input_is_offset_and_scaled():
    inp = InputFrame.for_full(640, 480)
    # native (0.5, 0.5) of the full frame is pixel (320, 240)
    out = native_to_roi_norm(np.array([[0.5, 0.5]]), inp, ROI)
    expected = px_to_norm_point(320.0, 240.0, ROI)
    assert out[0] == pytest.approx(expected)
    # the ROI's own top-left in full-frame native coordinates maps to (0, 0)
    out0 = native_to_roi_norm(np.array([[40 / 640, 20 / 480]]), inp, ROI)
    assert out0[0] == pytest.approx((0.0, 0.0), abs=1e-12)


def test_y_is_down_and_outside_values_are_permitted():
    inp = InputFrame.for_roi(ROI)
    a = native_to_roi_norm(np.array([[0.5, 0.2]]), inp, ROI)[0]
    b = native_to_roi_norm(np.array([[0.5, 0.8]]), inp, ROI)[0]
    assert b[1] > a[1]  # larger native y (lower in the image) -> larger normalized y
    outside = native_to_roi_norm(np.array([[-0.1, 1.2]]), inp, ROI)[0]
    assert outside[0] < 0 and outside[1] > 1  # legal: "outside the ROI" (common.schema point2)


def test_native_to_full_px_shapes_and_values():
    inp = InputFrame(10, 20, 100, 200)
    px = native_to_full_px(np.array([[0.0, 0.0], [1.0, 1.0]]), inp)
    assert px.shape == (2, 2)
    assert px[0] == pytest.approx((10.0, 20.0)) and px[1] == pytest.approx((110.0, 220.0))


def test_bbox_of_points():
    pts = np.array([[0.2, 0.5], [0.4, 0.3], [0.3, 0.9]])
    assert bbox_of(pts) == pytest.approx((0.2, 0.3, 0.2, 0.6))


def test_detector_input_enum_values():
    assert DetectorInput("ROI") is DetectorInput.ROI and str(DetectorInput.FULL) == "FULL"
