"""Shared vocabularies of ``schemas/common.schema.json`` (docs/architecture/contracts.md section 2).

String enums so that ``.value`` is exactly the JSON the schemas accept. Extending any enum is a
schema-version bump + ADR (contracts.md section 8); scope-touching values (a foot point, a
FOOT trigger) additionally need the out-of-scope re-inclusion procedure (OOS-REF:REQ-207).
"""

from __future__ import annotations

from enum import StrEnum as _StrEnum  # str(member) == member.value, so JSON encoders see the raw value


class HandId(_StrEnum):
    """Tracked-point identity. V1: the two hands. ``LEFT_FOOT``/``RIGHT_FOOT`` are reserved names,
    not members (OOS-REF:REQ-207)."""

    LEFT = "LEFT"
    RIGHT = "RIGHT"


class TrackStatus(_StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"
    STALE = "STALE"


class TipMethod(_StrEnum):
    GEOM = "GEOM"
    AXIS_REFINED = "AXIS_REFINED"
    MARKER = "MARKER"  # fallback / benchmark condition only (REQ-211, integrity I-7)


class CandidateSource(_StrEnum):
    REACTIVE = "REACTIVE"
    RULE = "RULE"
    MODEL = "MODEL"


class CandidateDerivation(_StrEnum):
    GEOMETRY = "GEOMETRY"
    DIRECT_HEAD = "DIRECT_HEAD"  # diagnostic harness modes only (ADR-0007 amendment)


class Arm(_StrEnum):
    A = "A"
    B = "B"
    C_GBDT = "C-GBDT"
    C_GRU = "C-GRU"
    C_TCN = "C-TCN"
    C_MT = "C-MT"
    C_TT = "C-TT"


class TriggerType(_StrEnum):
    HAND_TIP = "HAND_TIP"  # open enum by contract; FOOT reserved (ADR-0011)


class ResetReason(_StrEnum):
    GAP_EXCEEDED = "GAP_EXCEEDED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    STALE = "STALE"
    MANUAL = "MANUAL"
    ARM_SWITCH = "ARM_SWITCH"
    CONFIG_RELOAD = "CONFIG_RELOAD"
    SESSION_START = "SESSION_START"


class TimestampSource(_StrEnum):
    """How ``FrameSample.t_capture`` was obtained (architecture.md section 5.2)."""

    DRIVER_MAPPED = "DRIVER_MAPPED"
    GRAB_RETURN = "GRAB_RETURN"
    REPLAY = "REPLAY"


class ImageRefKind(_StrEnum):
    MEMORY = "MEMORY"
    FILE = "FILE"


class ImageCrop(_StrEnum):
    FULL = "FULL"
    ROI = "ROI"


__all__ = [
    "Arm",
    "CandidateDerivation",
    "CandidateSource",
    "HandId",
    "ImageCrop",
    "ImageRefKind",
    "ResetReason",
    "TimestampSource",
    "TipMethod",
    "TrackStatus",
    "TriggerType",
]
