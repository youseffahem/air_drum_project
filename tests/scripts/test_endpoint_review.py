"""Offline candidate invariants. Synthetic images are not accuracy evidence."""

import copy
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _endpoint_candidate import ProfileEndpointCandidate  # noqa: E402
from review_developer_endpoints import longest_run  # noqa: E402

from spacedrums.contracts import FrameSample, FrameView, HandObservation, ImageRef  # noqa: E402
from spacedrums.hands.grip import GripSettings  # noqa: E402


def scene(frame=0, t=1.0, blank=False, clipped=False, duplicate_grip=False):
    im = np.full((480, 640, 3), 80, np.uint8)
    hands = []
    for hid, x, tipy in [("LEFT", 440, 140), ("RIGHT", 200, 160)]:
        if not blank:
            cv2.line(im, (x, 342), (x, 0 if clipped else tipy), (210, 210, 210), 8)
        if duplicate_grip:
            x = 200
        lm = np.tile([x, 345.0], (21, 1))
        lm[0] = [x + 10, 380]
        lm[3] = [x + 5, 338]
        lm[4] = [x + 5, 335]
        lm[5] = [x, 340]
        lm[9] = [x, 350]
        lm[17] = [x, 370]
        hands.append(
            HandObservation(
                frame,
                t,
                hid,
                True,
                "synthetic-endpoint-review",
                tuple(map(tuple, lm / [640, 480])),
                None,
                0.95,
                (0, 0, 1, 1),
            )
        )
    sample = FrameSample(
        frame, t, t, "REPLAY", (640, 480), (0, 0, 640, 480), ImageRef.memory(im), "synthetic", 0
    )
    return FrameView(sample, im, im), hands


def test_both_physical_caps_from_current_image():
    est = ProfileEndpointCandidate(GripSettings(), temporal=True)
    out, _ = est.process(*scene())
    assert all(e["kind"] == "MEASURED" for e in out)
    expected = {"LEFT": [440, 136], "RIGHT": [200, 156]}
    for e in out:
        assert np.linalg.norm(np.array(e["tip"]) * [640, 480] - expected[e["hand_id"]]) < 8


def test_visual_absence_is_never_a_measured_prior_and_state_expires():
    est = ProfileEndpointCandidate(GripSettings(), temporal=True)
    assert all(e["kind"] == "MEASURED" for e in est.process(*scene())[0])
    out, diag = est.process(*scene(1, 1.04, blank=True))
    assert all(e["kind"] != "MEASURED" and e["tip"] is None for e in out)
    assert any(d["prior_state"] == "PRIOR_ONLY" for d in diag.values())
    out, diag = est.process(*scene(2, 1.2, blank=True))
    assert not est.memory
    assert all(d["prior_tip"] is None for d in diag.values())


def test_image_boundary_cannot_be_called_a_tip():
    est = ProfileEndpointCandidate(GripSettings(), temporal=True)
    out, _ = est.process(*scene(clipped=True))
    assert all(e["kind"] != "MEASURED" for e in out)


def test_same_shaft_cannot_belong_to_both_hands():
    est = ProfileEndpointCandidate(GripSettings(), temporal=True)
    out, _ = est.process(*scene(duplicate_grip=True))
    assert all(e["kind"] != "MEASURED" for e in out)
    assert all(e["reason"] == "SHARED_SHAFT_AMBIGUITY" for e in out)


def test_prefix_outputs_are_causal_and_order_independent():
    one = ProfileEndpointCandidate(GripSettings(), temporal=True)
    two = ProfileEndpointCandidate(GripSettings(), temporal=True)
    out, _ = one.process(*scene())
    first = copy.deepcopy(out)
    v, h = scene()
    other, _ = two.process(v, list(reversed(h)))
    assert {e["hand_id"]: e for e in out} == {e["hand_id"]: e for e in other}
    one.process(*scene(1, 1.04, blank=True))
    assert out == first
    with pytest.raises(ValueError, match="increasing timestamps"):
        one.process(*scene(2, 1.03))


def test_recording_gaps_break_a_continuity_run():
    rows = [{"frame_id": i, "t_capture": t} for i, t in enumerate([0, 0.04, 0.08, 0.3, 0.34])]
    result = longest_run(rows, [True] * 5)
    assert result["count"] == 2
    assert result["longest_frames"] == 3
    assert result["longest_span_s"] == pytest.approx(0.08)


def test_future_hand_observations_cannot_enter_current_measurement():
    est = ProfileEndpointCandidate(GripSettings(), temporal=True)
    v, _ = scene()
    _, future_hands = scene(1, 1.04)
    with pytest.raises(ValueError, match="current frame"):
        est.process(v, future_hands)
