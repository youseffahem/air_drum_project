"""Zone nudge keys act in window space (T1 live mirror regression).

The live wizard window shows the mirrored camera image, the replay window the camera orientation. In
both, i / j / k / l must move the selected zone up / left / down / right on screen, as the key hint
says, while the zones and the recorded nudges stay in camera coordinates.
"""

import copy

import numpy as np
import pytest
from calib_helpers import drive, make_wizard

from spacedrums.app.calibrate import handle_key
from spacedrums.calib import Stage, Step
from spacedrums.calib.synthetic import SyntheticUser
from spacedrums.capture.roi import Roi
from spacedrums.geometry import ZoneRegistry
from spacedrums.ui import Canvas


@pytest.fixture(scope="module")
def placement_review():
    wizard = make_wizard()
    drive(
        wizard,
        SyntheticUser(wizard.cfg),
        until=lambda w: w.step is Step.ZONE_PLACEMENT and w.stage is Stage.REVIEW,
    )
    return wizard


@pytest.fixture
def review(placement_review):
    wizard = copy.deepcopy(placement_review)
    assert wizard.step is Step.ZONE_PLACEMENT and wizard.stage is Stage.REVIEW and not wizard.nudges
    return wizard


def on_screen(wizard, mirror: bool) -> tuple[float, float]:
    """Window position of the selected zone's centre, through the canvas ``draw_wizard`` draws zones on."""
    roi = Roi.from_rect(wizard.cfg["roi"]["px"])
    zone = ZoneRegistry.from_config(wizard.view()["zones"])[wizard.selected_zone_id]
    width, height = wizard.cfg["camera_profile"]["resolution_px"]
    canvas = Canvas.for_display(np.zeros((height, width, 3), np.uint8), mirror).roi(roi)
    cx, cy = zone.shape.center
    return canvas.sign * cx * (roi.w - 1) + canvas.offset, cy * (roi.h - 1)


@pytest.mark.parametrize("mirror", [True, False], ids=["live-mirrored", "replay-camera"])
@pytest.mark.parametrize(
    "key, axis, sign",
    [("j", 0, -1), ("l", 0, 1), ("i", 1, -1), ("k", 1, 1)],
    ids=["left", "right", "up", "down"],
)
def test_nudge_keys_move_the_selected_zone_on_screen(review, mirror, key, axis, sign):
    before = on_screen(review, mirror)
    assert handle_key(review, ord(key), None, mirror=mirror) is None
    after = on_screen(review, mirror)
    assert sign * (after[axis] - before[axis]) > 0
    assert after[1 - axis] == pytest.approx(before[1 - axis])


def test_mirrored_nudges_are_recorded_in_camera_coordinates(review):
    step = review.settings.nudge_step
    zone = review.selected_zone_id
    handle_key(review, ord("j"), None, mirror=True)  # left on the mirrored screen = camera +x
    assert review.nudges[zone] == [pytest.approx(step), 0.0]
    handle_key(review, ord("j"), None, mirror=False)  # left in the camera-orientation window = camera -x
    assert zone not in review.nudges  # back at zero
