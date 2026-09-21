"""TEST-SCHEMA-1 extension (Phase 02): record *classes* serialise to exactly their schema.

contracts.md section 1: "the JSON Schema is the contract, the class is an implementation".
Every record class added by a phase gets a case here.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from conftest import is_valid

from spacedrums.contracts import FrameSample, ImageCrop, ImageRef, ImageRefKind, TimestampSource
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
