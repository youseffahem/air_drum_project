"""Record types mirroring ``schemas/*.schema.json`` (docs/architecture/contracts.md section 3).

Phase 02 implements the first producer, so the first record here is ``FrameSample`` (section 3.1)
plus its ``ImageRef``. Phase 03 adds ``HandObservation`` (3.2, Task 03.1), ``StickObservation``
(3.3, Tasks 03.7-03.9) and ``TrackState`` (3.4, Tasks 03.12-03.13); Phase 04 the geometry/audio
records; Phase 05 ``TimingRecord`` (3.10, Task 05.4). Every other record
(``KinematicFeatures`` ... ``TimingRecord``) is added by the phase that first *produces* it
(contracts.md: "the JSON Schema is the contract, the class is an implementation"), and each class
must:

* serialise with ``to_dict()`` to **exactly** the JSON its schema accepts
  (``tests/contracts/test_record_classes.py`` validates every class against its schema);
* carry ``SCHEMA_VERSION`` equal to the schema's pinned const;
* be immutable (``frozen=True``) and serialisable: no pixel arrays, no object references,
  so records can be logged, replayed and moved across threads/processes (architecture.md
  section 7).

``ImageRef`` is the one deliberate exception to "no pixels": for ``kind = MEMORY`` it *holds* the
in-process array (``array``) because the record's job is to say where the pixels are; the array is
excluded from ``to_dict()``, equality and ``repr``, so the serialised record is exactly
``{"kind": "MEMORY"}`` as the schema requires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spacedrums.contracts.enums import (
    Arm,
    CandidateDerivation,
    CandidateSource,
    HandId,
    ImageCrop,
    ImageRefKind,
    ResetReason,
    TimestampSource,
    TipMethod,
    TrackStatus,
)

_FRAME_SAMPLE_SCHEMA_VERSION = "1.0"
_HAND_OBSERVATION_SCHEMA_VERSION = "1.0"
_STICK_OBSERVATION_SCHEMA_VERSION = "1.0"
_TRACK_STATE_SCHEMA_VERSION = "1.0"
_TRAJECTORY_PREDICTION_SCHEMA_VERSION = "1.1"  # 1.1: aux.consistency_flags (Phase 11, ADR-0028)
_TRAJECTORY_PREDICTION_READABLE = ("1.0", "1.1")  # 1.0 records read as consistency_flags = null
CONSISTENCY_CHECKS = ("zone", "tti", "position", "intensity")
_STRIKE_CANDIDATE_SCHEMA_VERSION = "1.0"
_COMMITTED_STRIKE_SCHEMA_VERSION = "1.0"
_AUDIO_EVENT_SCHEMA_VERSION = "1.0"
_TIMING_RECORD_SCHEMA_VERSION = "1.0"
N_HAND_LANDMARKS = 21  # MediaPipe 21-keypoint ordering (phases/README.md section 14)


@dataclass(frozen=True)
class ImageRef:
    """Where a frame's pixels are (``FrameSample.image_ref``)."""

    kind: ImageRefKind
    path: str | None = None
    index: int | None = None
    crop: ImageCrop | None = None
    array: Any = field(default=None, repr=False, compare=False)  # MEMORY only; never serialised

    def __post_init__(self) -> None:
        kind = ImageRefKind(self.kind)
        object.__setattr__(self, "kind", kind)
        if kind is ImageRefKind.FILE:
            if self.path is None or self.index is None or self.crop is None:
                raise ValueError("ImageRef(kind=FILE) requires path, index and crop")
            if self.index < 0:
                raise ValueError("ImageRef.index must be >= 0")
            object.__setattr__(self, "crop", ImageCrop(self.crop))
            if self.array is not None:
                raise ValueError("ImageRef(kind=FILE) must not carry an in-memory array")
        else:
            if self.path is not None or self.index is not None or self.crop is not None:
                raise ValueError("ImageRef(kind=MEMORY) carries no path/index/crop")

    @classmethod
    def memory(cls, array: Any) -> ImageRef:
        return cls(kind=ImageRefKind.MEMORY, array=array)

    @classmethod
    def file(cls, path: str, index: int, crop: ImageCrop | str) -> ImageRef:
        return cls(kind=ImageRefKind.FILE, path=path, index=index, crop=ImageCrop(crop))

    def to_dict(self) -> dict[str, Any]:
        if self.kind is ImageRefKind.MEMORY:
            return {"kind": "MEMORY"}
        return {"kind": "FILE", "path": self.path, "index": self.index, "crop": str(self.crop)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ImageRef:
        kind = ImageRefKind(d["kind"])
        if kind is ImageRefKind.MEMORY:
            return cls.memory(None)
        return cls.file(d["path"], int(d["index"]), d["crop"])


@dataclass(frozen=True)
class FrameSample:
    """One captured frame with its timestamps and ROI (``frame-sample.schema.json``).

    Invariants checked at construction (the schema cannot express them):
    ``t_capture <= t_frame_available``; ``frame_id >= 0``; ``dropped_since_last >= 0``;
    ``roi_px`` lies inside ``frame_size_px``.
    """

    SCHEMA_VERSION = _FRAME_SAMPLE_SCHEMA_VERSION

    frame_id: int
    t_capture: float
    t_frame_available: float
    timestamp_source: TimestampSource
    frame_size_px: tuple[int, int]
    roi_px: tuple[int, int, int, int]
    image_ref: ImageRef
    camera_profile_id: str
    dropped_since_last: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_source", TimestampSource(self.timestamp_source))
        object.__setattr__(self, "frame_size_px", (int(self.frame_size_px[0]), int(self.frame_size_px[1])))
        object.__setattr__(self, "roi_px", tuple(int(v) for v in self.roi_px))
        if self.frame_id < 0:
            raise ValueError("frame_id must be >= 0")
        if self.dropped_since_last < 0:
            raise ValueError("dropped_since_last must be >= 0")
        if not (self.t_capture <= self.t_frame_available):
            raise ValueError(
                f"t_capture ({self.t_capture!r}) must be <= t_frame_available ({self.t_frame_available!r})"
            )
        w, h = self.frame_size_px
        if w < 1 or h < 1:
            raise ValueError("frame_size_px must be >= 1 in both dimensions")
        if len(self.roi_px) != 4:
            raise ValueError("roi_px must have four components [x, y, w, h]")
        x, y, rw, rh = self.roi_px
        if x < 0 or y < 0 or rw < 1 or rh < 1 or x + rw > w or y + rh > h:
            raise ValueError(f"roi_px {self.roi_px} must lie inside frame_size_px {self.frame_size_px}")
        if not self.camera_profile_id:
            raise ValueError("camera_profile_id must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "frame_id": self.frame_id,
            "t_capture": float(self.t_capture),
            "t_frame_available": float(self.t_frame_available),
            "timestamp_source": str(self.timestamp_source),
            "frame_size_px": list(self.frame_size_px),
            "roi_px": list(self.roi_px),
            "image_ref": self.image_ref.to_dict(),
            "camera_profile_id": self.camera_profile_id,
            "dropped_since_last": self.dropped_since_last,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FrameSample:
        if d.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError(f"unsupported FrameSample schema_version {d.get('schema_version')!r}")
        return cls(
            frame_id=int(d["frame_id"]),
            t_capture=float(d["t_capture"]),
            t_frame_available=float(d["t_frame_available"]),
            timestamp_source=TimestampSource(d["timestamp_source"]),
            frame_size_px=tuple(d["frame_size_px"]),
            roi_px=tuple(d["roi_px"]),
            image_ref=ImageRef.from_dict(d["image_ref"]),
            camera_profile_id=str(d["camera_profile_id"]),
            dropped_since_last=int(d["dropped_since_last"]),
        )


def _point2(p: Any, what: str) -> tuple[float, float]:
    if len(p) != 2:
        raise ValueError(f"{what} must have exactly two components [x, y], got {p!r}")
    return (float(p[0]), float(p[1]))


def _confidence(v: Any, what: str) -> float:
    f = float(v)
    if not (0.0 <= f <= 1.0):
        raise ValueError(f"{what} must lie in [0, 1], got {v!r}")
    return f


@dataclass(frozen=True)
class HandObservation:
    """Per-frame, per-hand landmark observation (``hand-observation.schema.json``; contracts.md 3.2).

    Coordinates are ROI-normalized, y-down (ADR-0005): the ``hands`` module converts the
    estimator's native coordinates at its boundary; no other module sees library coordinates.

    Invariants checked at construction (mirroring the schema's ``if present then ...`` rule and
    the parts JSON Schema cannot express): ``present`` implies 21 landmarks, a 4-component
    ``bbox`` and a ``handedness_score``; ``not present`` implies every nullable field is null;
    ``landmark_visibility`` is null or 21 confidences (null when the estimator provides none —
    the MediaPipe Hand Landmarker does not, Task 03.1 finding).
    """

    SCHEMA_VERSION = _HAND_OBSERVATION_SCHEMA_VERSION

    frame_id: int
    t_capture: float
    hand_id: HandId
    present: bool
    detector_id: str
    landmarks: tuple[tuple[float, float], ...] | None
    landmark_visibility: tuple[float, ...] | None
    handedness_score: float | None
    bbox: tuple[float, float, float, float] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "hand_id", HandId(self.hand_id))
        object.__setattr__(self, "present", bool(self.present))
        if self.frame_id < 0:
            raise ValueError("frame_id must be >= 0")
        if not self.detector_id:
            raise ValueError("detector_id must be non-empty")
        if self.present:
            if self.landmarks is None or self.bbox is None or self.handedness_score is None:
                raise ValueError("present hand requires landmarks, bbox and handedness_score")
            if len(self.landmarks) != N_HAND_LANDMARKS:
                raise ValueError(f"landmarks must have {N_HAND_LANDMARKS} points, got {len(self.landmarks)}")
            object.__setattr__(
                self,
                "landmarks",
                tuple(_point2(p, f"landmarks[{i}]") for i, p in enumerate(self.landmarks)),
            )
            if len(self.bbox) != 4:
                raise ValueError("bbox must be [x, y, w, h]")
            object.__setattr__(self, "bbox", tuple(float(v) for v in self.bbox))
            object.__setattr__(
                self, "handedness_score", _confidence(self.handedness_score, "handedness_score")
            )
        else:
            if (
                self.landmarks is not None
                or self.bbox is not None
                or self.handedness_score is not None
                or self.landmark_visibility is not None
            ):
                raise ValueError(
                    "absent hand carries null landmarks, landmark_visibility, bbox, handedness_score"
                )
        if self.landmark_visibility is not None:
            if len(self.landmark_visibility) != N_HAND_LANDMARKS:
                raise ValueError(f"landmark_visibility must have {N_HAND_LANDMARKS} values")
            object.__setattr__(
                self,
                "landmark_visibility",
                tuple(
                    _confidence(v, f"landmark_visibility[{i}]")
                    for i, v in enumerate(self.landmark_visibility)
                ),
            )

    @classmethod
    def absent(
        cls, frame_id: int, t_capture: float, hand_id: HandId | str, detector_id: str
    ) -> HandObservation:
        """The ``present=False`` record emitted for a hand the detector did not produce."""
        return cls(
            frame_id=frame_id,
            t_capture=t_capture,
            hand_id=HandId(hand_id),
            present=False,
            detector_id=detector_id,
            landmarks=None,
            landmark_visibility=None,
            handedness_score=None,
            bbox=None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "frame_id": self.frame_id,
            "t_capture": float(self.t_capture),
            "hand_id": str(self.hand_id),
            "present": self.present,
            "detector_id": self.detector_id,
            "landmarks": [list(p) for p in self.landmarks] if self.landmarks is not None else None,
            "landmark_visibility": (
                list(self.landmark_visibility) if self.landmark_visibility is not None else None
            ),
            "handedness_score": self.handedness_score,
            "bbox": list(self.bbox) if self.bbox is not None else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HandObservation:
        if d.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError(f"unsupported HandObservation schema_version {d.get('schema_version')!r}")
        lm = d["landmarks"]
        vis = d["landmark_visibility"]
        bbox = d["bbox"]
        return cls(
            frame_id=int(d["frame_id"]),
            t_capture=float(d["t_capture"]),
            hand_id=HandId(d["hand_id"]),
            present=bool(d["present"]),
            detector_id=str(d["detector_id"]),
            landmarks=tuple(tuple(p) for p in lm) if lm is not None else None,
            landmark_visibility=tuple(vis) if vis is not None else None,
            handedness_score=d["handedness_score"],
            bbox=tuple(bbox) if bbox is not None else None,
        )


def _unit2(v: Any, what: str) -> tuple[float, float]:
    ux, uy = _point2(v, what)
    n = (ux * ux + uy * uy) ** 0.5
    if not (0.999 <= n <= 1.001):
        raise ValueError(f"{what} must be a unit vector, got norm {n!r}")
    return (ux, uy)


@dataclass(frozen=True)
class StickObservation:
    """Per-frame, per-hand stick axis + tip estimate (``stick-observation.schema.json``; contracts.md 3.3).

    Invariants: ``present`` implies ``axis_origin``, ``axis_dir`` (unit) and ``tip`` are set;
    ``not present`` implies the geometry fields are null **and both confidences are 0** (schema
    description); ``stick_length_est`` is null or >= 0; ``method_id`` is always set (the benchmark
    label of integrity item I-7 is carried even by an absent record).
    """

    SCHEMA_VERSION = _STICK_OBSERVATION_SCHEMA_VERSION

    frame_id: int
    t_capture: float
    hand_id: HandId
    present: bool
    method_id: TipMethod
    axis_origin: tuple[float, float] | None
    axis_dir: tuple[float, float] | None
    tip: tuple[float, float] | None
    tip_confidence: float
    axis_confidence: float
    stick_length_est: float | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "hand_id", HandId(self.hand_id))
        object.__setattr__(self, "method_id", TipMethod(self.method_id))
        object.__setattr__(self, "present", bool(self.present))
        if self.frame_id < 0:
            raise ValueError("frame_id must be >= 0")
        object.__setattr__(self, "tip_confidence", _confidence(self.tip_confidence, "tip_confidence"))
        object.__setattr__(self, "axis_confidence", _confidence(self.axis_confidence, "axis_confidence"))
        if self.present:
            if self.axis_origin is None or self.axis_dir is None or self.tip is None:
                raise ValueError("present stick requires axis_origin, axis_dir and tip")
            object.__setattr__(self, "axis_origin", _point2(self.axis_origin, "axis_origin"))
            object.__setattr__(self, "axis_dir", _unit2(self.axis_dir, "axis_dir"))
            object.__setattr__(self, "tip", _point2(self.tip, "tip"))
        else:
            if self.axis_origin is not None or self.axis_dir is not None or self.tip is not None:
                raise ValueError("absent stick carries null axis_origin, axis_dir and tip")
            if self.tip_confidence != 0.0 or self.axis_confidence != 0.0:
                raise ValueError("absent stick has tip_confidence = axis_confidence = 0")
        if self.stick_length_est is not None:
            if float(self.stick_length_est) < 0:
                raise ValueError("stick_length_est must be >= 0")
            object.__setattr__(self, "stick_length_est", float(self.stick_length_est))

    @classmethod
    def absent(
        cls, frame_id: int, t_capture: float, hand_id: HandId | str, method_id: TipMethod | str
    ) -> StickObservation:
        return cls(
            frame_id=frame_id,
            t_capture=t_capture,
            hand_id=HandId(hand_id),
            present=False,
            method_id=TipMethod(method_id),
            axis_origin=None,
            axis_dir=None,
            tip=None,
            tip_confidence=0.0,
            axis_confidence=0.0,
            stick_length_est=None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "frame_id": self.frame_id,
            "t_capture": float(self.t_capture),
            "hand_id": str(self.hand_id),
            "present": self.present,
            "method_id": str(self.method_id),
            "axis_origin": list(self.axis_origin) if self.axis_origin is not None else None,
            "axis_dir": list(self.axis_dir) if self.axis_dir is not None else None,
            "tip": list(self.tip) if self.tip is not None else None,
            "tip_confidence": self.tip_confidence,
            "axis_confidence": self.axis_confidence,
            "stick_length_est": self.stick_length_est,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StickObservation:
        if d.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError(f"unsupported StickObservation schema_version {d.get('schema_version')!r}")
        return cls(
            frame_id=int(d["frame_id"]),
            t_capture=float(d["t_capture"]),
            hand_id=HandId(d["hand_id"]),
            present=bool(d["present"]),
            method_id=TipMethod(d["method_id"]),
            axis_origin=tuple(d["axis_origin"]) if d["axis_origin"] is not None else None,
            axis_dir=tuple(d["axis_dir"]) if d["axis_dir"] is not None else None,
            tip=tuple(d["tip"]) if d["tip"] is not None else None,
            tip_confidence=float(d["tip_confidence"]),
            axis_confidence=float(d["axis_confidence"]),
            stick_length_est=d["stick_length_est"],
        )


@dataclass(frozen=True)
class HistoryRef:
    """``TrackState.history_ref``: metadata about the in-memory causal window (never the window)."""

    n: int
    oldest_frame_id: int | None

    def __post_init__(self) -> None:
        if self.n < 0:
            raise ValueError("history_ref.n must be >= 0")
        if self.oldest_frame_id is not None and self.oldest_frame_id < 0:
            raise ValueError("history_ref.oldest_frame_id must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {"n": self.n, "oldest_frame_id": self.oldest_frame_id}


@dataclass(frozen=True)
class TrackState:
    """Per-frame, per-hand causal tracking state (``track-state.schema.json``; contracts.md 3.4).

    Invariants (schema ``allOf`` + descriptions): ``VALID``/``DEGRADED`` carry ``tip_filtered`` and
    ``tip_velocity``; ``INVALID``/``STALE`` carry null position, velocity and acceleration;
    ``frames_since_valid == 0`` only on a fresh ``VALID`` frame; ``reset_reason`` set only on the frame
    of a reset.
    """

    SCHEMA_VERSION = _TRACK_STATE_SCHEMA_VERSION

    frame_id: int
    t_capture: float
    hand_id: HandId
    status: TrackStatus
    tracker_id: str
    tip_method: TipMethod | None
    tip_filtered: tuple[float, float] | None
    tip_velocity: tuple[float, float] | None
    tip_acceleration: tuple[float, float] | None
    axis_angle: float | None
    axis_angular_velocity: float | None
    confidence: float
    frames_since_valid: int
    last_valid_t: float | None
    history_ref: HistoryRef | None
    reset_reason: ResetReason | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "hand_id", HandId(self.hand_id))
        object.__setattr__(self, "status", TrackStatus(self.status))
        if self.tip_method is not None:
            object.__setattr__(self, "tip_method", TipMethod(self.tip_method))
        if self.reset_reason is not None:
            object.__setattr__(self, "reset_reason", ResetReason(self.reset_reason))
        if self.frame_id < 0:
            raise ValueError("frame_id must be >= 0")
        if not self.tracker_id:
            raise ValueError("tracker_id must be non-empty")
        object.__setattr__(self, "confidence", _confidence(self.confidence, "confidence"))
        if self.frames_since_valid < 0:
            raise ValueError("frames_since_valid must be >= 0")
        live = self.status in (TrackStatus.VALID, TrackStatus.DEGRADED)
        if live:
            if self.tip_filtered is None or self.tip_velocity is None:
                raise ValueError(f"{self.status} state requires tip_filtered and tip_velocity")
            object.__setattr__(self, "tip_filtered", _point2(self.tip_filtered, "tip_filtered"))
            object.__setattr__(self, "tip_velocity", _point2(self.tip_velocity, "tip_velocity"))
            if self.tip_acceleration is not None:
                object.__setattr__(
                    self, "tip_acceleration", _point2(self.tip_acceleration, "tip_acceleration")
                )
        else:
            if (
                self.tip_filtered is not None
                or self.tip_velocity is not None
                or self.tip_acceleration is not None
            ):
                raise ValueError(f"{self.status} state carries null position, velocity and acceleration")
        if self.status is TrackStatus.VALID and self.frames_since_valid != 0:
            raise ValueError("a VALID frame has frames_since_valid == 0")
        if self.status is not TrackStatus.VALID and self.frames_since_valid == 0:
            raise ValueError("frames_since_valid == 0 only on a VALID frame")
        if self.history_ref is not None and not isinstance(self.history_ref, HistoryRef):
            object.__setattr__(self, "history_ref", HistoryRef(**self.history_ref))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "frame_id": self.frame_id,
            "t_capture": float(self.t_capture),
            "hand_id": str(self.hand_id),
            "status": str(self.status),
            "tracker_id": self.tracker_id,
            "tip_method": str(self.tip_method) if self.tip_method is not None else None,
            "tip_filtered": list(self.tip_filtered) if self.tip_filtered is not None else None,
            "tip_velocity": list(self.tip_velocity) if self.tip_velocity is not None else None,
            "tip_acceleration": list(self.tip_acceleration) if self.tip_acceleration is not None else None,
            "axis_angle": float(self.axis_angle) if self.axis_angle is not None else None,
            "axis_angular_velocity": (
                float(self.axis_angular_velocity) if self.axis_angular_velocity is not None else None
            ),
            "confidence": self.confidence,
            "frames_since_valid": self.frames_since_valid,
            "last_valid_t": float(self.last_valid_t) if self.last_valid_t is not None else None,
            "history_ref": self.history_ref.to_dict() if self.history_ref is not None else None,
            "reset_reason": str(self.reset_reason) if self.reset_reason is not None else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrackState:
        if d.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError(f"unsupported TrackState schema_version {d.get('schema_version')!r}")
        hr = d["history_ref"]
        return cls(
            frame_id=int(d["frame_id"]),
            t_capture=float(d["t_capture"]),
            hand_id=HandId(d["hand_id"]),
            status=TrackStatus(d["status"]),
            tracker_id=str(d["tracker_id"]),
            tip_method=TipMethod(d["tip_method"]) if d["tip_method"] is not None else None,
            tip_filtered=tuple(d["tip_filtered"]) if d["tip_filtered"] is not None else None,
            tip_velocity=tuple(d["tip_velocity"]) if d["tip_velocity"] is not None else None,
            tip_acceleration=tuple(d["tip_acceleration"]) if d["tip_acceleration"] is not None else None,
            axis_angle=d["axis_angle"],
            axis_angular_velocity=d["axis_angular_velocity"],
            confidence=float(d["confidence"]),
            frames_since_valid=int(d["frames_since_valid"]),
            last_valid_t=d["last_valid_t"],
            history_ref=HistoryRef(int(hr["n"]), hr["oldest_frame_id"]) if hr is not None else None,
            reset_reason=ResetReason(d["reset_reason"]) if d["reset_reason"] is not None else None,
        )


@dataclass(frozen=True)
class TrajectoryAux:
    """Optional auxiliary prediction heads; geometry never substitutes them for ``positions``."""

    strike_prob_within_H: float | None = None
    tti: float | None = None
    zone_logits: tuple[float, ...] | None = None
    zone_ids: tuple[str, ...] | None = None
    impact_pos: tuple[float, float] | None = None
    intensity_proxy: float | None = None
    # Phase 11 (schema 1.1): geometry-vs-head agreement per check, set after geometry; null
    # when no candidate or no head exists. Informational/gating only, never a strike source.
    consistency_flags: tuple[tuple[str, bool | None], ...] | None = None

    def __post_init__(self) -> None:
        if self.consistency_flags is not None:
            flags = dict(self.consistency_flags)
            if set(flags) != set(CONSISTENCY_CHECKS) or any(
                v is not None and not isinstance(v, bool) for v in flags.values()
            ):
                raise ValueError(f"consistency_flags needs exactly {CONSISTENCY_CHECKS}, each bool or null")
            object.__setattr__(self, "consistency_flags", tuple((k, flags[k]) for k in CONSISTENCY_CHECKS))
        if self.strike_prob_within_H is not None:
            object.__setattr__(
                self, "strike_prob_within_H", _confidence(self.strike_prob_within_H, "strike_prob_within_H")
            )
        if self.zone_logits is not None:
            object.__setattr__(self, "zone_logits", tuple(float(v) for v in self.zone_logits))
        if self.zone_ids is not None:
            object.__setattr__(self, "zone_ids", tuple(str(v) for v in self.zone_ids))
        if (self.zone_logits is None) != (self.zone_ids is None):
            raise ValueError("zone_logits and zone_ids must either both be set or both be null")
        if self.zone_logits is not None and len(self.zone_logits) != len(self.zone_ids or ()):
            raise ValueError("zone_logits and zone_ids must have equal length")
        if self.impact_pos is not None:
            object.__setattr__(self, "impact_pos", _point2(self.impact_pos, "impact_pos"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "strike_prob_within_H": self.strike_prob_within_H,
            "tti": self.tti,
            "zone_logits": list(self.zone_logits) if self.zone_logits is not None else None,
            "zone_ids": list(self.zone_ids) if self.zone_ids is not None else None,
            "impact_pos": list(self.impact_pos) if self.impact_pos is not None else None,
            "intensity_proxy": self.intensity_proxy,
            "consistency_flags": dict(self.consistency_flags) if self.consistency_flags is not None else None,
        }


@dataclass(frozen=True)
class TrajectoryPrediction:
    SCHEMA_VERSION = _TRAJECTORY_PREDICTION_SCHEMA_VERSION

    frame_id: int
    t_capture: float
    hand_id: HandId
    anticipator_id: str
    model_hash: str | None
    K: int
    dt_step: float
    t_offsets_s: tuple[float, ...] | None
    positions: tuple[tuple[float, float], ...]
    velocities: tuple[tuple[float, float], ...] | None
    uncertainty: tuple[tuple[float, ...], ...] | None
    uncertainty_kind: str | None
    aux: TrajectoryAux
    t_inference_done: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "hand_id", HandId(self.hand_id))
        if self.frame_id < 0 or self.K < 1 or self.dt_step <= 0 or not self.anticipator_id:
            raise ValueError("invalid trajectory metadata")
        pos = tuple(_point2(p, f"positions[{i}]") for i, p in enumerate(self.positions))
        object.__setattr__(self, "positions", pos)
        if len(pos) != self.K:
            raise ValueError("K must equal len(positions)")
        if self.t_offsets_s is not None:
            offsets = tuple(float(v) for v in self.t_offsets_s)
            if (
                len(offsets) != self.K
                or any(v <= 0 for v in offsets)
                or any(b <= a for a, b in zip(offsets, offsets[1:], strict=False))
            ):
                raise ValueError("t_offsets_s must contain K strictly increasing positive values")
            object.__setattr__(self, "t_offsets_s", offsets)
        if self.velocities is not None:
            velocities = tuple(_point2(v, f"velocities[{i}]") for i, v in enumerate(self.velocities))
            if len(velocities) != self.K:
                raise ValueError("velocities must contain K vectors")
            object.__setattr__(self, "velocities", velocities)
        if self.uncertainty is not None:
            unc = tuple(tuple(float(v) for v in row) for row in self.uncertainty)
            if len(unc) != self.K or any(not row for row in unc) or not self.uncertainty_kind:
                raise ValueError("uncertainty requires K non-empty rows and uncertainty_kind")
            object.__setattr__(self, "uncertainty", unc)
        elif self.uncertainty_kind is not None:
            raise ValueError("uncertainty_kind must be null when uncertainty is null")
        if not isinstance(self.aux, TrajectoryAux):
            object.__setattr__(self, "aux", TrajectoryAux(**self.aux))

    def sample_times(self) -> tuple[float, ...]:
        offsets = self.t_offsets_s or tuple((i + 1) * self.dt_step for i in range(self.K))
        return tuple(self.t_capture + offset for offset in offsets)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "frame_id": self.frame_id,
            "t_capture": float(self.t_capture),
            "hand_id": str(self.hand_id),
            "anticipator_id": self.anticipator_id,
            "model_hash": self.model_hash,
            "K": self.K,
            "dt_step": float(self.dt_step),
            "t_offsets_s": list(self.t_offsets_s) if self.t_offsets_s is not None else None,
            "positions": [list(p) for p in self.positions],
            "velocities": [list(v) for v in self.velocities] if self.velocities is not None else None,
            "uncertainty": [list(v) for v in self.uncertainty] if self.uncertainty is not None else None,
            "uncertainty_kind": self.uncertainty_kind,
            "aux": self.aux.to_dict(),
            "t_inference_done": float(self.t_inference_done),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrajectoryPrediction:
        if d.get("schema_version") not in _TRAJECTORY_PREDICTION_READABLE:
            raise ValueError("unsupported TrajectoryPrediction schema_version")
        return cls(
            frame_id=int(d["frame_id"]),
            t_capture=float(d["t_capture"]),
            hand_id=d["hand_id"],
            anticipator_id=str(d["anticipator_id"]),
            model_hash=d["model_hash"],
            K=int(d["K"]),
            dt_step=float(d["dt_step"]),
            t_offsets_s=tuple(d["t_offsets_s"]) if d["t_offsets_s"] is not None else None,
            positions=tuple(tuple(p) for p in d["positions"]),
            velocities=tuple(tuple(v) for v in d["velocities"]) if d["velocities"] is not None else None,
            uncertainty=tuple(tuple(v) for v in d["uncertainty"]) if d["uncertainty"] is not None else None,
            uncertainty_kind=d["uncertainty_kind"],
            aux=TrajectoryAux(**d["aux"]),
            t_inference_done=float(d["t_inference_done"]),
        )


@dataclass(frozen=True)
class StrikeCandidate:
    SCHEMA_VERSION = _STRIKE_CANDIDATE_SCHEMA_VERSION

    candidate_id: str
    frame_id: int
    t_capture: float
    hand_id: HandId
    zone_id: str
    source: CandidateSource
    derivation: CandidateDerivation
    anticipator_id: str | None
    t_impact_pred: float | None
    t_impact_est: float | None
    tti: float | None
    impact_position: tuple[float, float]
    crossing_velocity: tuple[float, float]
    strike_probability: float | None
    intensity_proxy: float
    t_candidate: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "hand_id", HandId(self.hand_id))
        object.__setattr__(self, "source", CandidateSource(self.source))
        object.__setattr__(self, "derivation", CandidateDerivation(self.derivation))
        object.__setattr__(self, "impact_position", _point2(self.impact_position, "impact_position"))
        object.__setattr__(self, "crossing_velocity", _point2(self.crossing_velocity, "crossing_velocity"))
        if not self.candidate_id or not self.zone_id or self.frame_id < 0:
            raise ValueError("candidate ids must be non-empty and frame_id >= 0")
        reactive = self.source is CandidateSource.REACTIVE
        if reactive and not (
            self.t_impact_est is not None
            and self.t_impact_pred is None
            and self.tti is None
            and self.anticipator_id is None
        ):
            raise ValueError("REACTIVE candidate requires only t_impact_est")
        if not reactive and not (
            self.t_impact_pred is not None
            and self.tti is not None
            and self.t_impact_est is None
            and self.anticipator_id
        ):
            raise ValueError("predicted candidate requires t_impact_pred, tti and anticipator_id")
        if (
            self.source in (CandidateSource.REACTIVE, CandidateSource.RULE)
            and self.derivation is not CandidateDerivation.GEOMETRY
        ):
            raise ValueError("REACTIVE/RULE candidates must use GEOMETRY derivation")
        if self.strike_probability is not None:
            object.__setattr__(
                self, "strike_probability", _confidence(self.strike_probability, "strike_probability")
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "frame_id": self.frame_id,
            "t_capture": float(self.t_capture),
            "hand_id": str(self.hand_id),
            "zone_id": self.zone_id,
            "source": str(self.source),
            "derivation": str(self.derivation),
            "anticipator_id": self.anticipator_id,
            "t_impact_pred": self.t_impact_pred,
            "t_impact_est": self.t_impact_est,
            "tti": self.tti,
            "impact_position": list(self.impact_position),
            "crossing_velocity": list(self.crossing_velocity),
            "strike_probability": self.strike_probability,
            "intensity_proxy": float(self.intensity_proxy),
            "t_candidate": float(self.t_candidate),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrikeCandidate:
        if d.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported StrikeCandidate schema_version")
        return cls(**{k: (tuple(v) if k in ("impact_position", "crossing_velocity") else v)
                      for k, v in d.items() if k != "schema_version"})


@dataclass(frozen=True)
class CommittedStrike:
    SCHEMA_VERSION = _COMMITTED_STRIKE_SCHEMA_VERSION

    strike_id: str
    candidate_id: str
    frame_id: int
    t_capture: float
    hand_id: HandId
    zone_id: str
    source: CandidateSource
    derivation: CandidateDerivation
    arm: Arm
    shadow: bool
    t_commit: float
    t_impact_target: float
    intensity_proxy: float
    gain: float
    refractory_until: float
    episode_id: str
    commit_policy_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "hand_id", HandId(self.hand_id))
        object.__setattr__(self, "source", CandidateSource(self.source))
        object.__setattr__(self, "derivation", CandidateDerivation(self.derivation))
        object.__setattr__(self, "arm", Arm(self.arm))
        if self.frame_id < 0 or self.gain < 0:
            raise ValueError("invalid committed strike")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "strike_id": self.strike_id,
            "candidate_id": self.candidate_id,
            "frame_id": self.frame_id,
            "t_capture": float(self.t_capture),
            "hand_id": str(self.hand_id),
            "zone_id": self.zone_id,
            "source": str(self.source),
            "derivation": str(self.derivation),
            "arm": str(self.arm),
            "shadow": self.shadow,
            "t_commit": float(self.t_commit),
            "t_impact_target": float(self.t_impact_target),
            "intensity_proxy": float(self.intensity_proxy),
            "gain": float(self.gain),
            "refractory_until": float(self.refractory_until),
            "episode_id": self.episode_id,
            "commit_policy_id": self.commit_policy_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CommittedStrike:
        if d.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported CommittedStrike schema_version")
        return cls(**{k: v for k, v in d.items() if k != "schema_version"})


@dataclass(frozen=True)
class AudioEvent:
    SCHEMA_VERSION = _AUDIO_EVENT_SCHEMA_VERSION

    strike_id: str
    sample_id: str
    t_audio_scheduled: float
    t_target_play: float
    t_audio_out_est: float
    audio_late_s: float
    gain: float
    audio_profile_id: str

    def __post_init__(self) -> None:
        if self.audio_late_s < 0 or self.gain < 0:
            raise ValueError("audio_late_s and gain must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "strike_id": self.strike_id,
            "sample_id": self.sample_id,
            "t_audio_scheduled": float(self.t_audio_scheduled),
            "t_target_play": float(self.t_target_play),
            "t_audio_out_est": float(self.t_audio_out_est),
            "audio_late_s": float(self.audio_late_s),
            "gain": float(self.gain),
            "audio_profile_id": self.audio_profile_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AudioEvent:
        if d.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported AudioEvent schema_version")
        return cls(**{k: v for k, v in d.items() if k != "schema_version"})


@dataclass(frozen=True)
class TimingRecord:
    """README section 5.2 stamps for one frame (``kind = FRAME``) or one committed strike
    (``kind = STRIKE``), on ``t_mono`` (``timing-record.schema.json``; contracts.md 3.10). Phase 05.

    Invariants mirroring the schema's ``if/then`` rules: ``STRIKE`` requires ``strike_id``,
    ``hand_id`` and ``t_commit``; ``FRAME`` carries null ``strike_id``/``hand_id``. Latency
    components are never stored here (they are derived by the consumer, README section 5.3).
    ``t_audio_out`` / ``t_acoustic_onset`` are **external measurements only** and stay null
    unless an external instrument produced them (Phase 18); ``t_audio_out_est`` is the software
    estimate and is null when no MEASURED output latency exists for the audio profile.
    """

    SCHEMA_VERSION = _TIMING_RECORD_SCHEMA_VERSION

    kind: str
    frame_id: int
    strike_id: str | None
    hand_id: HandId | None
    arm: Arm | None
    t_capture: float
    t_frame_available: float
    t_tracking_done: float | None
    t_features_done: float | None
    t_inference_done: float | None
    t_candidate: float | None
    t_commit: float | None
    t_audio_scheduled: float | None
    t_audio_out_est: float | None
    t_audio_out: float | None
    t_acoustic_onset: float | None
    t_impact_est: float | None
    t_impact_pred: float | None
    t_impact_phys: float | None
    hardware_id: str
    config_hash: str
    clock_id: str

    def __post_init__(self) -> None:
        if self.kind not in ("FRAME", "STRIKE"):
            raise ValueError("TimingRecord.kind must be FRAME or STRIKE")
        if self.frame_id < 0:
            raise ValueError("frame_id must be >= 0")
        if self.hand_id is not None:
            object.__setattr__(self, "hand_id", HandId(self.hand_id))
        if self.arm is not None:
            object.__setattr__(self, "arm", Arm(self.arm))
        if self.kind == "STRIKE":
            if not self.strike_id or self.hand_id is None or self.t_commit is None:
                raise ValueError("STRIKE timing record requires strike_id, hand_id and t_commit")
        elif self.strike_id is not None or self.hand_id is not None:
            raise ValueError("FRAME timing record carries null strike_id and hand_id")
        if not self.hardware_id or not self.clock_id or not self.config_hash.startswith("sha256:"):
            raise ValueError("hardware_id, clock_id and a sha256: config_hash are required")
        if not (self.t_capture <= self.t_frame_available):
            raise ValueError("t_capture must be <= t_frame_available")

    def to_dict(self) -> dict[str, Any]:
        def f(v: float | None) -> float | None:
            return None if v is None else float(v)

        return {
            "schema_version": self.SCHEMA_VERSION,
            "kind": self.kind,
            "frame_id": self.frame_id,
            "strike_id": self.strike_id,
            "hand_id": str(self.hand_id) if self.hand_id is not None else None,
            "arm": str(self.arm) if self.arm is not None else None,
            "t_capture": float(self.t_capture),
            "t_frame_available": float(self.t_frame_available),
            "t_tracking_done": f(self.t_tracking_done),
            "t_features_done": f(self.t_features_done),
            "t_inference_done": f(self.t_inference_done),
            "t_candidate": f(self.t_candidate),
            "t_commit": f(self.t_commit),
            "t_audio_scheduled": f(self.t_audio_scheduled),
            "t_audio_out_est": f(self.t_audio_out_est),
            "t_audio_out": f(self.t_audio_out),
            "t_acoustic_onset": f(self.t_acoustic_onset),
            "t_impact_est": f(self.t_impact_est),
            "t_impact_pred": f(self.t_impact_pred),
            "t_impact_phys": f(self.t_impact_phys),
            "hardware_id": self.hardware_id,
            "config_hash": self.config_hash,
            "clock_id": self.clock_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TimingRecord:
        if d.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError(f"unsupported TimingRecord schema_version {d.get('schema_version')!r}")
        return cls(**{k: v for k, v in d.items() if k != "schema_version"})


__all__ = [
    "CONSISTENCY_CHECKS",
    "AudioEvent",
    "CommittedStrike",
    "FrameSample",
    "HandObservation",
    "HistoryRef",
    "ImageRef",
    "N_HAND_LANDMARKS",
    "StickObservation",
    "StrikeCandidate",
    "TimingRecord",
    "TrackState",
    "TrajectoryAux",
    "TrajectoryPrediction",
]
