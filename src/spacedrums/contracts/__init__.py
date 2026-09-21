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
from spacedrums.contracts.interfaces import (
    Anticipator,
    AudioScheduler,
    CommitPolicy,
    FrameSource,
    Geometry,
    TipEstimator,
    Tracker,
)
from spacedrums.contracts.records import (
    N_HAND_LANDMARKS,
    AudioEvent,
    CommittedStrike,
    FrameSample,
    HandObservation,
    HistoryRef,
    ImageRef,
    StickObservation,
    StrikeCandidate,
    TimingRecord,
    TrackState,
    TrajectoryAux,
    TrajectoryPrediction,
)
from spacedrums.contracts.values import FrameView

__all__ = [
    "Anticipator",
    "AudioEvent",
    "AudioScheduler",
    "Arm",
    "CandidateDerivation",
    "CandidateSource",
    "CommitPolicy",
    "CommittedStrike",
    "FrameSample",
    "FrameSource",
    "FrameView",
    "Geometry",
    "HandId",
    "HandObservation",
    "HistoryRef",
    "ImageCrop",
    "ImageRef",
    "ImageRefKind",
    "N_HAND_LANDMARKS",
    "ResetReason",
    "StickObservation",
    "StrikeCandidate",
    "TimestampSource",
    "TimingRecord",
    "TipEstimator",
    "TipMethod",
    "TrackState",
    "TrackStatus",
    "TrajectoryAux",
    "TrajectoryPrediction",
    "Tracker",
    "TriggerType",
]
