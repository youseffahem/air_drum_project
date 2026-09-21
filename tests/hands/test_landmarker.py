"""TEST-HANDS-2: the ``HandLandmarker`` wrapper with an injected deterministic backend.

No MediaPipe, no model file: these tests pin the wrapper's *contract behaviour* (two schema-valid
``HandObservation``s per frame in LEFT, RIGHT order; ``present=False`` instead of an exception;
label collisions dropped and counted, never re-labelled; ``detector_id`` pins every parameter;
VIDEO-mode timestamps strictly increasing; processing time from ``timing.now``; ROI/FULL input
paths). The real estimator is exercised in ``test_landmarker_model.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

from spacedrums.capture import Roi, crop_roi
from spacedrums.contracts import FrameSample, FrameView, HandId, ImageRef, TimestampSource
from spacedrums.contracts import schema as contract_schema
from spacedrums.hands import (
    DetectorInput,
    HandLandmarker,
    HandLandmarkerSettings,
    HandsFrameResult,
    IdentityMode,
    IdentitySettings,
    LandmarkBackend,
    RawDetection,
    label_to_hand_id,
)

RAW = IdentitySettings(mode=IdentityMode.RAW)  # Task 03.1 label-only rule; TEMPORAL: test_identity.py

ROI = Roi(40, 20, 560, 440)


def _hand_pts(cx: float, cy: float) -> np.ndarray:
    return np.array([[cx + 0.01 * (i % 5), cy - 0.01 * (i // 5)] for i in range(21)])


class FakeBackend:
    backend_id = "fake@1"

    def __init__(self, script: list[list[RawDetection]]) -> None:
        self.script = script
        self.calls: list[tuple[tuple[int, ...], int]] = []
        self.closed = False

    def detect(self, image_rgb: np.ndarray, timestamp_ms: int) -> list[RawDetection]:
        self.calls.append((image_rgb.shape, timestamp_ms))
        k = len(self.calls) - 1
        return self.script[k] if k < len(self.script) else []

    def close(self) -> None:
        self.closed = True


def _view(frame_id: int, t: float, full: np.ndarray | None = None) -> FrameView:
    full = np.zeros((480, 640, 3), np.uint8) if full is None else full
    s = FrameSample(frame_id=frame_id, t_capture=t, t_frame_available=t + 0.001,
                    timestamp_source=TimestampSource.REPLAY, frame_size_px=(640, 480),
                    roi_px=ROI.as_tuple(), image_ref=ImageRef.memory(full),
                    camera_profile_id="test", dropped_since_last=0)
    return FrameView(sample=s, roi=crop_roi(full, ROI), full=full)


def _lm(settings: HandLandmarkerSettings | None = None, script=None) -> tuple[HandLandmarker, FakeBackend]:
    be = FakeBackend(script or [])
    return HandLandmarker(settings or HandLandmarkerSettings(identity=RAW), backend=be), be


def _assert_valid(res: HandsFrameResult) -> None:
    for o in res.observations:
        errs = contract_schema.errors("hand-observation", o.to_dict())
        assert not errs, errs


def test_backend_protocol_is_satisfied_by_the_fake():
    assert isinstance(FakeBackend([]), LandmarkBackend)


def test_two_observations_per_frame_in_fixed_order_and_schema_valid():
    lm, _ = _lm(script=[[RawDetection(_hand_pts(0.3, 0.8), "Right", 0.9),
                         RawDetection(_hand_pts(0.7, 0.8), "Left", 0.8)]])
    res = lm.detect(_view(0, 10.0))
    assert [o.hand_id for o in res.observations] == [HandId.LEFT, HandId.RIGHT]
    assert res.both_present and res.n_detected == 2 and res.n_not_emitted == 0
    assert res.left.handedness_score == 0.8 and res.right.handedness_score == 0.9
    assert res.left.frame_id == 0 and res.left.t_capture == 10.0
    assert res.left.detector_id == lm.detector_id == res.right.detector_id
    _assert_valid(res)


def test_absent_hands_give_present_false_not_an_exception():
    lm, _ = _lm(script=[[]])
    res = lm.detect(_view(3, 1.0))
    assert not res.left.present and not res.right.present and res.n_detected == 0
    assert res.left.landmarks is None and res.right.bbox is None
    _assert_valid(res)
    assert lm.counters.frames == 1 and lm.counters.both_present == 0


def test_label_collision_keeps_higher_score_and_counts_the_other():
    lm, _ = _lm(script=[[RawDetection(_hand_pts(0.3, 0.8), "Right", 0.6),
                         RawDetection(_hand_pts(0.7, 0.8), "Right", 0.9)]])
    res = lm.detect(_view(0, 0.0))
    assert res.right.present and not res.left.present  # never re-labelled by a guess (Task 03.2)
    assert res.right.handedness_score == 0.9
    assert res.n_not_emitted == 1 and lm.counters.label_collisions == 1
    _assert_valid(res)


def test_unknown_label_is_counted_not_emitted():
    lm, _ = _lm(script=[[RawDetection(_hand_pts(0.3, 0.8), "Both", 0.9)]])
    res = lm.detect(_view(0, 0.0))
    assert not res.left.present and not res.right.present
    assert res.n_detected == 1 and res.n_not_emitted == 1 and lm.counters.unknown_labels == 1


def test_swap_handedness_maps_labels():
    assert label_to_hand_id("Left", False) is HandId.LEFT
    assert label_to_hand_id("Left", True) is HandId.RIGHT
    assert label_to_hand_id("right", False) is HandId.RIGHT
    assert label_to_hand_id("Both", False) is None
    lm, _ = _lm(HandLandmarkerSettings(swap_handedness=True, identity=RAW),
                script=[[RawDetection(_hand_pts(0.3, 0.8), "Right", 0.9)]])
    res = lm.detect(_view(0, 0.0))
    assert res.left.present and not res.right.present
    assert ":swap1:" in lm.detector_id


def test_coordinates_are_roi_normalized_for_roi_input():
    pts = _hand_pts(0.3, 0.8)
    lm, be = _lm(script=[[RawDetection(pts, "Right", 0.9)]])
    res = lm.detect(_view(0, 0.0))
    assert be.calls[0][0] == (440, 560, 3)  # the ROI crop was handed to the backend
    lms = np.array(res.right.landmarks)
    assert lms == pytest.approx(pts, abs=1e-12)
    x, y, w, h = res.right.bbox
    assert (x, y) == pytest.approx((pts[:, 0].min(), pts[:, 1].min()))
    assert (w, h) == pytest.approx((np.ptp(pts[:, 0]), np.ptp(pts[:, 1])))


def test_full_frame_input_converts_through_the_roi():
    pts = np.tile([[40 / 640, 20 / 480]], (21, 1))  # the ROI's top-left corner in full-frame native
    lm, be = _lm(HandLandmarkerSettings(input=DetectorInput.FULL, identity=RAW),
                 script=[[RawDetection(pts, "Left", 0.9)]])
    res = lm.detect(_view(0, 0.0))
    assert be.calls[0][0] == (480, 640, 3)
    assert np.array(res.left.landmarks) == pytest.approx(np.zeros((21, 2)), abs=1e-12)


def test_full_input_without_full_frame_raises():
    lm, _ = _lm(HandLandmarkerSettings(input=DetectorInput.FULL, identity=RAW))
    v = _view(0, 0.0)
    v = FrameView(sample=v.sample, roi=v.roi, full=None)
    with pytest.raises(ValueError, match="FULL"):
        lm.detect(v)


def test_video_timestamps_strictly_increasing_and_bumps_counted():
    lm, be = _lm(script=[[], [], [], []])
    lm.detect(_view(0, 100.0))
    lm.detect(_view(1, 100.0333))
    r3 = lm.detect(_view(2, 100.0333))  # same t_capture in ms -> bumped by 1 ms
    lm.detect(_view(3, 100.0666))
    ms = [c[1] for c in be.calls]
    assert ms[0] == 0 and all(b > a for a, b in zip(ms, ms[1:], strict=False)), ms
    assert r3.timestamp_bumped and lm.counters.timestamp_bumps == 1


def test_processing_time_is_measured_and_non_negative():
    lm, _ = _lm(script=[[]])
    res = lm.detect(_view(0, 0.0))
    assert res.processing_s >= 0.0


def test_visibility_passthrough_when_backend_provides_it():
    vis = np.linspace(0.1, 1.0, 21)
    lm, _ = _lm(script=[[RawDetection(_hand_pts(0.3, 0.8), "Right", 0.9, visibility=vis)]])
    res = lm.detect(_view(0, 0.0))
    assert res.right.landmark_visibility == pytest.approx(tuple(vis))
    assert lm.counters.visibility_frames == 1
    _assert_valid(res)


def test_wrong_landmark_count_from_backend_is_an_error():
    lm, _ = _lm(script=[[RawDetection(np.zeros((20, 2)), "Right", 0.9)]])
    with pytest.raises(ValueError, match="21"):
        lm.detect(_view(0, 0.0))


def test_detector_id_pins_parameters():
    s = HandLandmarkerSettings(running_mode="IMAGE", num_hands=1, min_hand_detection_confidence=0.7,
                               min_hand_presence_confidence=0.6, min_tracking_confidence=0.55, identity=RAW)
    lm, _ = _lm(s)
    assert lm.detector_id.startswith("fake@1:nomodel:image:nh1:d0.70:p0.60:t0.55:roi:swap0:id-raw:grip-")
    lm2, _ = _lm(HandLandmarkerSettings())  # TEMPORAL default: every identity + grip parameter is in the id
    assert ":id-temporal-g0.15-gap0.25-wl0.50-m0.15-cap0.50:grip-knuckle_row-" in lm2.detector_id
    d = lm.describe()
    assert d["detector_id"] == lm.detector_id and d["settings"]["input"] == "ROI"
    assert d["settings"]["identity"]["mode"] == "RAW"


def test_settings_validation_and_from_config():
    with pytest.raises(ValueError):
        HandLandmarkerSettings(running_mode="LIVE_STREAM")
    with pytest.raises(ValueError):
        HandLandmarkerSettings(min_tracking_confidence=1.5)
    with pytest.raises(ValueError):
        HandLandmarkerSettings(num_hands=0)
    with pytest.raises(ValueError, match="hands"):
        HandLandmarkerSettings.from_config({})
    with pytest.raises(ValueError, match="detector"):
        HandLandmarkerSettings.from_config({"hands": {"detector": "other"}})
    cfg = {"hands": {"detector": "mediapipe-hand-landmarker", "model_asset_id": "m", "running_mode": "IMAGE",
                     "num_hands": 2, "min_hand_detection_confidence": 0.4,
                     "min_hand_presence_confidence": 0.5,
                     "min_tracking_confidence": 0.6, "input": "FULL", "swap_handedness": True,
                     "identity": {"mode": "TEMPORAL", "gate_distance": 0.2, "max_gap_s": 0.3, "w_label": 0.4,
                                  "ambiguity_margin": 0.1, "ambiguous_score_cap": 0.45},
                     "grip": {"point_weights": {"index_mcp": 1.0}, "direction": "INDEX_MCP_TO_PIP",
                              "min_direction_span": 0.01}}}
    s = HandLandmarkerSettings.from_config(cfg)
    assert s.running_mode == "IMAGE" and s.input is DetectorInput.FULL and s.swap_handedness
    assert s.identity.mode is IdentityMode.TEMPORAL and s.identity.gate_distance == 0.2
    assert s.grip.point_weights == {"index_mcp": 1.0} and str(s.grip.direction) == "INDEX_MCP_TO_PIP"
    with pytest.raises(KeyError):
        cfg["hands"].pop("identity")
        HandLandmarkerSettings.from_config(cfg)  # the identity block is required (schema 1.2)


def test_context_manager_closes_backend():
    lm, be = _lm()
    with lm:
        pass
    assert be.closed


def test_counters_accumulate_over_frames():
    lm, _ = _lm(script=[[RawDetection(_hand_pts(0.3, 0.8), "Right", 0.9)],
                        [RawDetection(_hand_pts(0.3, 0.8), "Right", 0.9),
                         RawDetection(_hand_pts(0.7, 0.8), "Left", 0.9)],
                        []])
    for i in range(3):
        lm.detect(_view(i, float(i)))
    c = lm.counters.to_dict()
    assert c["frames"] == 3 and c["detections"] == 3
    assert c["present"] == {"LEFT": 1, "RIGHT": 2} and c["both_present"] == 1
