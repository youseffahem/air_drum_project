"""TEST-CAPTURE-1: the px <-> ROI-normalized helper (ADR-0005): round trip, corners, y-down, crop."""

from __future__ import annotations

import numpy as np
import pytest

from spacedrums.capture import Roi, crop_roi, norm_to_px, norm_to_px_point, px_to_norm, px_to_norm_point

ROI = Roi(160, 40, 960, 640)


def test_corners():
    assert px_to_norm_point(160, 40, ROI) == (0.0, 0.0)
    assert px_to_norm_point(160 + 960, 40 + 640, ROI) == (1.0, 1.0)
    assert px_to_norm_point(160 + 480, 40 + 320, ROI) == (0.5, 0.5)


def test_y_increases_downward():
    x_top, y_top = px_to_norm_point(500, 100, ROI)
    x_bot, y_bot = px_to_norm_point(500, 500, ROI)
    assert y_bot > y_top and x_top == x_bot


def test_outside_roi_is_legal_and_signed():
    x, y = px_to_norm_point(0, 0, ROI)
    assert x < 0 and y < 0
    x, y = px_to_norm_point(2000, 2000, ROI)
    assert x > 1 and y > 1


@pytest.mark.parametrize("px", [(160, 40), (1119, 679), (777, 333), (0, 0), (5000, 12)])
def test_round_trip_scalar(px):
    n = px_to_norm_point(*px, ROI)
    back = norm_to_px_point(*n, ROI)
    assert back == pytest.approx(px, abs=1e-9)


def test_vectorised_round_trip():
    xs = np.array([160.0, 640.0, 1120.0, -10.0])
    ys = np.array([40.0, 360.0, 680.0, 900.0])
    nx, ny = px_to_norm(xs, ys, ROI)
    assert nx.tolist() == pytest.approx([0.0, 0.5, 1.0, -170 / 960])
    bx, by = norm_to_px(nx, ny, ROI)
    np.testing.assert_allclose(bx, xs)
    np.testing.assert_allclose(by, ys)


def test_aspect_and_bounds():
    assert ROI.aspect == 1.5
    assert ROI.fits(1280, 720) and not ROI.fits(1000, 720)
    assert Roi.full_frame(640, 480).as_tuple() == (0, 0, 640, 480)
    assert Roi.from_rect([1, 2, 3, 4]) == Roi(1, 2, 3, 4)


@pytest.mark.parametrize("bad", [(-1, 0, 10, 10), (0, 0, 0, 10), (0, 0, 10, 0), (0.5, 0, 10, 10)])
def test_invalid_roi(bad):
    with pytest.raises(ValueError):
        Roi(*bad)


def test_crop_is_a_view_without_resampling():
    frame = np.arange(720 * 1280 * 3, dtype=np.uint8).reshape(720, 1280, 3)
    view = crop_roi(frame, ROI)
    assert view.shape == (640, 960, 3)
    assert np.shares_memory(view, frame)
    assert view[0, 0, 0] == frame[40, 160, 0]
    with pytest.raises(ValueError):
        crop_roi(frame[:600], ROI)
