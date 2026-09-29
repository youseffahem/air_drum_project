"""Canvas: identity in camera orientation; mirrored shapes follow the image, text stays upright."""

from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from spacedrums.capture import Roi
from spacedrums.data.recorder import GuidedRecorder
from spacedrums.geometry import ZoneRegistry
from spacedrums.ui import Canvas

W, H = 640, 480
FONT = cv2.FONT_HERSHEY_SIMPLEX
POLY = np.array([[100, 200], [180, 190], [190, 300], [110, 310]], np.int32)
EXACT = {
    "filled circle": lambda c: c.circle((150, 200), 21, (0, 255, 0), -1),
    "rectangle": lambda c: c.rectangle((40, 20), (600, 440), (200, 200, 200), 1),
    "line": lambda c: c.line((100, 100), (180, 330), (0, 255, 0), 2),
}
ANTIALIASED = {
    "ring": lambda c: c.circle((150, 200), 21, (0, 255, 0), 2, cv2.LINE_AA),
    "polygon": lambda c: c.polylines([POLY], True, (0, 255, 255), 1),
    "filled polygon": lambda c: c.fill_poly([POLY], (0, 255, 255), cv2.LINE_AA),
    "marker": lambda c: c.marker((150, 200), (0, 0, 255), cv2.MARKER_TILTED_CROSS, 16, 2, cv2.LINE_AA),
    "ellipse": lambda c: c.ellipse((200, 150), (70, 30), 25.0, 0, 360, (80, 210, 245), 2, cv2.LINE_AA),
    "arc": lambda c: c.ellipse((300, 300), (80, 40), -15.0, 30, 200, (40, 70, 255), 3, cv2.LINE_AA),
    "arrow": lambda c: c.arrowed_line((150, 250), (190, 200), (60, 230, 90), 2, cv2.LINE_AA, 0.35),
}


def black():
    return np.zeros((H, W, 3), np.uint8)


def ink(image):
    return (image.max(axis=2) > 40).astype(np.uint8)


def test_camera_canvas_is_pixel_identical_to_direct_cv2_calls():
    direct, canvas = black(), black()
    cv2.circle(direct, (150, 200), 21, (0, 255, 0), 2, cv2.LINE_AA)
    cv2.polylines(direct, [POLY], True, (0, 255, 255), 1)
    cv2.arrowedLine(direct, (150, 250), (190, 200), (60, 230, 90), 2, cv2.LINE_AA, tipLength=0.35)
    cv2.ellipse(direct, (200, 150), (70, 30), 25.0, 30, 200, (80, 210, 245), 2, cv2.LINE_AA)
    cv2.drawMarker(direct, (150, 200), (0, 0, 255), cv2.MARKER_CROSS, 12, 2)
    cv2.putText(direct, "Snare", (100, 400), FONT, 0.48, (235, 235, 235), 1, cv2.LINE_AA)
    c = Canvas(canvas)
    c.circle((150, 200), 21, (0, 255, 0), 2, cv2.LINE_AA)
    c.polylines([POLY], True, (0, 255, 255), 1)
    c.arrowed_line((150, 250), (190, 200), (60, 230, 90), 2, cv2.LINE_AA, tip_length=0.35)
    c.ellipse((200, 150), (70, 30), 25.0, 30, 200, (80, 210, 245), 2, cv2.LINE_AA)
    c.marker((150, 200), (0, 0, 255), cv2.MARKER_CROSS, 12, 2)
    c.put_text("Snare", (100, 400), FONT, 0.48, (235, 235, 235), 1, cv2.LINE_AA)
    np.testing.assert_array_equal(canvas, direct)
    assert c.upright(40, 600).point((46, 80)) == (46, 80) and c.span(40, 600) == slice(40, 600)


@pytest.mark.parametrize("name", sorted(EXACT))
def test_mirrored_canvas_reflects_pixel_exact_shapes(name):
    camera, display = black(), black()
    EXACT[name](Canvas(camera))
    EXACT[name](Canvas.for_display(display, mirror=True))
    np.testing.assert_array_equal(display, camera[:, ::-1])


@pytest.mark.parametrize("name", sorted(ANTIALIASED))
def test_mirrored_canvas_reflects_antialiased_shapes_within_one_pixel(name):
    camera, display = black(), black()
    ANTIALIASED[name](Canvas(camera))
    ANTIALIASED[name](Canvas.for_display(display, mirror=True))
    expected, drawn = ink(camera[:, ::-1]), ink(display)
    near = np.ones((3, 3), np.uint8)
    assert drawn.sum() > 50
    assert not (drawn & (1 - cv2.dilate(expected, near))).any()
    assert not (expected & (1 - cv2.dilate(drawn, near))).any()


def test_mirrored_text_is_upright_in_the_reflected_footprint():
    display, camera = black(), black()
    text, org = "Hi-Hat 12", (100, 200)
    Canvas.for_display(display, mirror=True).put_text(text, org, FONT, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    Canvas(camera).put_text(text, org, FONT, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    width = cv2.getTextSize(text, FONT, 0.6, 2)[0][0]
    upright = black()
    cv2.putText(upright, text, (W - org[0] - width, org[1]), FONT, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    np.testing.assert_array_equal(display, upright)  # normal glyphs, drawn after the mirror
    assert not np.array_equal(display, camera[:, ::-1])  # a reflected raster would read backwards
    cols = np.flatnonzero(ink(display).any(axis=0))
    camera_cols = np.flatnonzero(ink(camera).any(axis=0))
    assert abs(int(cols[0]) - (W - 1 - int(camera_cols[-1]))) <= 2  # same footprint, mirrored side


def test_upright_hud_keeps_its_place_in_the_mirrored_container():
    roi = Roi(100, 20, 460, 440)  # deliberately asymmetric: the ROI moves under the mirror
    display = Canvas.for_display(black(), mirror=True)
    assert display.span(roi.x, roi.x1) == slice(W - roi.x1, W - roi.x)
    hud = display.upright(roi.x, roi.x1)
    assert hud.point((roi.x + 6, 60)) == (W - roi.x1 + 6, 60)  # left edge of the displayed ROI
    assert display.upright(0, W).point((8, 470)) == (8, 470)  # full-frame HUD: screen coordinates
    region, full = display.roi(roi), Canvas.for_display(black(), mirror=True)
    region.circle((30, 40), 9, (0, 255, 0), -1)
    full.circle((roi.x + 30, roi.y + 40), 9, (0, 255, 0), -1)
    np.testing.assert_array_equal(display.image, full.image)
    assert region.mirrored and region.width == roi.w


def test_protocol_cues_follow_the_mirrored_zone_and_keep_the_countdown_upright():
    ellipse = {"center": [0.2, 0.5], "rx": 0.12, "ry": 0.08, "angle_rad": 0.3}
    registry = ZoneRegistry.from_config([{
        "zone_id": "hihat", "name": "Hi-Hat", "trigger_type": "HAND_TIP",
        "shape": {"type": "ELLIPSE", **ellipse},
        "impact_surface": {"type": "ARC", **ellipse, "theta_start_rad": np.pi, "theta_end_rad": 2 * np.pi},
        "inward_normal": [0.0, 1.0], "sample_id": "s", "gain_curve_id": "default",
    }])
    spec = SimpleNamespace(zone_ids=("hihat",), duration_s=2.0, tempo_bpm=None)
    recorder = SimpleNamespace(spec=spec, done=False, t_deadline=11.0, last_t=10.5)
    camera, display = black()[:400, :520].copy(), black()[:400, :520].copy()
    GuidedRecorder.draw_cues(recorder, Canvas(camera), registry)
    GuidedRecorder.draw_cues(recorder, Canvas.for_display(display, mirror=True), registry)
    bar = slice(camera.shape[0] - 14, camera.shape[0] - 5)
    np.testing.assert_array_equal(display[bar], camera[bar])  # countdown drains left to right
    cue = slice(0, camera.shape[0] - 20)
    cue_cols = np.flatnonzero(ink(display[cue]).any(axis=0))
    assert cue_cols.min() > display.shape[1] // 2  # a camera-left cue is shown on the right
