"""Record types mirroring ``schemas/*.schema.json`` (docs/architecture/contracts.md section 3).

Phase 02 implements the first producer, so the first record here is ``FrameSample`` (section 3.1)
plus its ``ImageRef``. Every other record (``HandObservation`` ... ``TimingRecord``) is added by
the phase that first *produces* it (contracts.md: "the JSON Schema is the contract, the class is
an implementation"), and each class must:

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

from spacedrums.contracts.enums import ImageCrop, ImageRefKind, TimestampSource

_FRAME_SAMPLE_SCHEMA_VERSION = "1.0"


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
        object.__setattr__(
            self, "frame_size_px", (int(self.frame_size_px[0]), int(self.frame_size_px[1]))
        )
        object.__setattr__(self, "roi_px", tuple(int(v) for v in self.roi_px))
        if self.frame_id < 0:
            raise ValueError("frame_id must be >= 0")
        if self.dropped_since_last < 0:
            raise ValueError("dropped_since_last must be >= 0")
        if not (self.t_capture <= self.t_frame_available):
            raise ValueError(
                f"t_capture ({self.t_capture!r}) must be <= t_frame_available "
                f"({self.t_frame_available!r})"
            )
        w, h = self.frame_size_px
        if w < 1 or h < 1:
            raise ValueError("frame_size_px must be >= 1 in both dimensions")
        if len(self.roi_px) != 4:
            raise ValueError("roi_px must have four components [x, y, w, h]")
        x, y, rw, rh = self.roi_px
        if x < 0 or y < 0 or rw < 1 or rh < 1 or x + rw > w or y + rh > h:
            raise ValueError(
                f"roi_px {self.roi_px} must lie inside frame_size_px {self.frame_size_px}"
            )
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


__all__ = ["FrameSample", "ImageRef"]
