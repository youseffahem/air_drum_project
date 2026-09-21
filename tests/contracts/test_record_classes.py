"""TEST-SCHEMA-1 extension (Phase 02): record *classes* serialise to exactly their schema.

contracts.md section 1: "the JSON Schema is the contract, the class is an implementation".
Every record class added by a phase gets a case here.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from conftest import is_valid

from spacedrums.contracts import (
    N_HAND_LANDMARKS,
    FrameSample,
    HandId,
    HandObservation,
    ImageCrop,
    ImageRef,
    ImageRefKind,
    TimestampSource,
)
from spacedrums.contracts import schema as contract_schema


def _sample(**overrides):
    base = dict(
        frame_id=7, t_capture=10.0, t_frame_available=10.002, timestamp_source="GRAB_RETURN",
        frame_size_px=(640, 480), roi_px=(40, 20, 560, 440),
        image_ref=ImageRef.memory(np.zeros((480, 640, 3), np.uint8)),
        camera_profile_id="hw01-integrated-webcam-v0", dropped_since_last=0,
    )
    base.update(overrides)
    return FrameSample(**base)


def test_frame_sample_memory_ref_validates(validator):
    d = _sample().to_dict()
    assert d["image_ref"] == {"kind": "MEMORY"}  # the array never leaks into the JSON
    assert is_valid(validator("frame-sample"), d)
    assert contract_schema.is_valid("frame-sample", d)
    assert d["schema_version"] == FrameSample.SCHEMA_VERSION


def test_frame_sample_file_ref_round_trip(validator):
    s = _sample(image_ref=ImageRef.file("video.mkv", 120, "FULL"), timestamp_source=TimestampSource.REPLAY)
    d = s.to_dict()
    assert is_valid(validator("frame-sample"), d)
    back = FrameSample.from_dict(d)
    assert back == s
    assert back.image_ref.crop is ImageCrop.FULL and back.image_ref.kind is ImageRefKind.FILE


def test_frame_sample_matches_the_phase01_example(example, validator):
    ex = example("frame-sample")
    s = FrameSample.from_dict(ex)
    assert s.to_dict() == ex


@pytest.mark.parametrize(
    "bad",
    [
        {"t_capture": 10.01},  # t_capture > t_frame_available
        {"frame_id": -1},
        {"dropped_since_last": -1},
        {"roi_px": (600, 20, 100, 100)},  # outside the frame
        {"roi_px": (0, 0, 0, 10)},
        {"frame_size_px": (0, 480)},
        {"camera_profile_id": ""},
        {"timestamp_source": "GUESSED"},
    ],
)
def test_frame_sample_invariants(bad):
    with pytest.raises(ValueError):
        _sample(**bad)


def test_image_ref_rules():
    with pytest.raises(ValueError):
        ImageRef(kind=ImageRefKind.FILE, path="v.mkv")  # missing index/crop
    with pytest.raises(ValueError):
        ImageRef(kind=ImageRefKind.MEMORY, path="v.mkv")
    with pytest.raises(ValueError):
        ImageRef(kind=ImageRefKind.FILE, path="v.mkv", index=0, crop="ROI", array=np.zeros(1))
    ref = ImageRef.memory(np.ones(3))
    assert ref == ImageRef.memory(np.zeros(2))  # array excluded from equality
    assert "array" not in repr(ref)


def test_frame_sample_is_frozen_and_serialisable():
    s = _sample()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.frame_id = 3  # type: ignore[misc]
    d = s.to_dict()
    assert all(not isinstance(v, np.ndarray) for v in d.values())


# ------------------------------------------------------------------- HandObservation (Phase 03, Task 03.1)


def _hand(**overrides):
    base = dict(
        frame_id=120, t_capture=12.345678, hand_id="RIGHT", present=True,
        detector_id="test-hand-landmarker",
        landmarks=tuple((0.4 + 0.01 * i, 0.5 + 0.005 * i) for i in range(N_HAND_LANDMARKS)),
        landmark_visibility=None, handedness_score=0.95,
        bbox=(0.38, 0.48, 0.25, 0.2),
    )
    base.update(overrides)
    return HandObservation(**base)


def test_hand_observation_present_validates(validator):
    d = _hand().to_dict()
    assert is_valid(validator("hand-observation"), d), contract_schema.errors("hand-observation", d)
    assert d["schema_version"] == HandObservation.SCHEMA_VERSION
    assert len(d["landmarks"]) == 21 and d["landmark_visibility"] is None
    assert HandObservation.from_dict(d) == _hand()


def test_hand_observation_absent_validates(validator):
    a = HandObservation.absent(5, 1.0, HandId.LEFT, "det")
    d = a.to_dict()
    assert is_valid(validator("hand-observation"), d)
    assert d["present"] is False and d["landmarks"] is None and d["bbox"] is None
    assert d["handedness_score"] is None and d["landmark_visibility"] is None
    assert HandObservation.from_dict(d) == a


def test_hand_observation_matches_the_phase01_example(example):
    ex = example("hand-observation")
    h = HandObservation.from_dict(ex)
    assert h.to_dict() == ex


def test_hand_observation_with_visibility_validates(validator):
    d = _hand(landmark_visibility=tuple([0.9] * 21)).to_dict()
    assert is_valid(validator("hand-observation"), d)
    assert len(d["landmark_visibility"]) == 21


@pytest.mark.parametrize(
    "bad",
    [
        {"landmarks": None},                                   # present without landmarks
        {"bbox": None},
        {"handedness_score": None},
        {"handedness_score": 1.2},
        {"landmarks": tuple((0.1, 0.2) for _ in range(20))},   # 20 points
        {"landmarks": tuple((0.1, 0.2, 0.3) for _ in range(21))},  # 3-component points
        {"landmark_visibility": tuple([0.5] * 20)},
        {"landmark_visibility": tuple([1.5] * 21)},
        {"bbox": (0.1, 0.2, 0.3)},
        {"hand_id": "LEFT_FOOT"},                              # OOS-REF:REQ-207 reserved, not a member
        {"frame_id": -1},
        {"detector_id": ""},
    ],
)
def test_hand_observation_invariants(bad):
    with pytest.raises(ValueError):
        _hand(**bad)


def test_hand_observation_absent_must_be_all_null():
    with pytest.raises(ValueError):
        _hand(present=False)  # landmarks etc. still set
    with pytest.raises(ValueError):
        HandObservation(frame_id=1, t_capture=0.0, hand_id="LEFT", present=False, detector_id="d",
                        landmarks=None, landmark_visibility=tuple([0.5] * 21), handedness_score=None,
                        bbox=None)


def test_hand_observation_is_frozen_and_serialisable():
    h = _hand()
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.present = False  # type: ignore[misc]
    d = h.to_dict()
    assert all(not isinstance(v, np.ndarray) for v in d.values())
    assert isinstance(h.landmarks, tuple) and isinstance(h.landmarks[0], tuple)
