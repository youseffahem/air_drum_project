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
from spacedrums.contracts.interfaces import FrameSource, TipEstimator, Tracker
from spacedrums.contracts.records import (
    N_HAND_LANDMARKS,
    FrameSample,
    HandObservation,
    HistoryRef,
    ImageRef,
    StickObservation,
    TrackState,
)
from spacedrums.contracts.values import FrameView

__all__ = [
    "Arm",
    "CandidateDerivation",
    "CandidateSource",
    "FrameSample",
    "FrameSource",
    "FrameView",
    "HandId",
    "HandObservation",
    "HistoryRef",
    "ImageCrop",
    "ImageRef",
    "ImageRefKind",
    "N_HAND_LANDMARKS",
    "ResetReason",
    "StickObservation",
    "TimestampSource",
    "TipEstimator",
    "TipMethod",
    "TrackState",
    "TrackStatus",
    "Tracker",
    "TriggerType",
]
