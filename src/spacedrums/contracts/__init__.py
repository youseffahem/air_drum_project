"""Type-only layer L0: records, enums, interface Protocols, schema access (ADR-0012).

Imports nothing else from ``spacedrums`` (architecture.md section 2.2).
"""

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
    TriggerType,
)
from spacedrums.contracts.interfaces import FrameSource
from spacedrums.contracts.records import FrameSample, ImageRef
from spacedrums.contracts.values import FrameView

__all__ = [
    "Arm",
    "CandidateDerivation",
    "CandidateSource",
    "FrameSample",
    "FrameSource",
    "FrameView",
    "HandId",
    "ImageCrop",
    "ImageRef",
    "ImageRefKind",
    "ResetReason",
    "TimestampSource",
    "TipMethod",
    "TrackStatus",
    "TriggerType",
]
