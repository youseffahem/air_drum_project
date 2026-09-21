"""TEST-UI-1: the stand-here guide overlay draws the ROI box, band and text without side effects."""

from __future__ import annotations

import numpy as np
import pytest

from spacedrums.capture import Roi
from spacedrums.capture.stats import CaptureStats
from spacedrums.ui import DEFAULT_INSTRUCTION, GuideStyle, draw_guide, guide_status_lines

ROI = Roi(40, 20, 560, 440)


def _frame(value=90):
    return np.full((480, 640, 3), value, np.uint8)


def test_returns_new_frame_of_same_shape_and_leaves_input_untouched():
    f = _frame()
    out = draw_guide(f, ROI)
    assert out.shape == f.shape and out.dtype == np.uint8
    assert np.array_equal(f, _frame())
    assert not np.array_equal(out, f)


def test_inplace_modifies_input():
    f = _frame()
    out = draw_guide(f, ROI, inplace=True)
    assert out is f and not np.array_equal(f, _frame())


def test_box_edges_are_drawn_in_box_colour():
    style = GuideStyle(box_color=(0, 220, 0), dim_alpha=0.0, band_alpha=0.0)
    out = draw_guide(_frame(), ROI, band=None, instruction="", style=style)
    # a point on the left edge of the ROI, mid height, must be box-coloured
    assert tuple(out[ROI.y + 200, ROI.x + 1]) == (0, 220, 0)
    # far inside the ROI nothing changed (no band, no dimming)
    assert tuple(out[ROI.y + 200, ROI.x + 200]) == (90, 90, 90)


def test_outside_is_dimmed_inside_is_not():
    out = draw_guide(_frame(), ROI, band=None, instruction="", style=GuideStyle(dim_alpha=0.5))
    assert out[5, 5, 0] < 90  # outside dimmed
    assert out[ROI.y + 100, ROI.x + 100, 0] == 90  # inside untouched


def test_band_position_follows_roi_normalized_y_down():
    style = GuideStyle(dim_alpha=0.0, band_color=(0, 0, 255), band_alpha=1.0)
    out = draw_guide(_frame(), ROI, band=(0.5, 0.6), instruction="", style=style)
    y_in_band = ROI.y + int(0.55 * ROI.h)
    y_above = ROI.y + int(0.45 * ROI.h)
    assert tuple(out[y_in_band, ROI.x + 300]) == (0, 0, 255)
    assert tuple(out[y_above, ROI.x + 300]) == (90, 90, 90)


def test_instruction_text_changes_pixels_at_top():
    a = draw_guide(_frame(), ROI, band=None, instruction="", style=GuideStyle(dim_alpha=0.0))
    b = draw_guide(_frame(), ROI, band=None, instruction=DEFAULT_INSTRUCTION, style=GuideStyle(dim_alpha=0.0))
    assert not np.array_equal(a[:50], b[:50])
    assert "hands" in DEFAULT_INSTRUCTION and "box" in DEFAULT_INSTRUCTION


@pytest.mark.parametrize("bad", [(0.6, 0.5), (-0.1, 0.5), (0.5, 1.1)])
def test_bad_band_rejected(bad):
    with pytest.raises(ValueError):
        draw_guide(_frame(), ROI, band=bad)


def test_roi_must_fit():
    with pytest.raises(ValueError):
        draw_guide(_frame(), Roi(600, 0, 100, 100))
    with pytest.raises(ValueError):
        draw_guide(np.zeros((480, 640), np.uint8), ROI)


def test_status_lines_show_drops():
    st = CaptureStats(delivered=100, dropped=3, stalled=1, duplicates=2, fps_measured=29.7,
                      interval_p50=0.033, interval_p99=0.05)
    lines = guide_status_lines(st)
    assert "dropped 3" in lines[0] and "29.7" in lines[0] and "dup 2" in lines[0]
