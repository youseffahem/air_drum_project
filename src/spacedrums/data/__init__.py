"""Data-collection pipeline (Phase 06): recording protocol, guided recorder hooks, session metadata,
microphone capture + sync check, session verification / unusable-recording policy, raw manifests.

Phase 07 adds labelling, QC and participant-level splits here; none of that exists yet (phase
document: "What Must NOT Be Done Yet"). Nothing in this package records a person by itself: the
person-dependent live recording is reachable only through ``scripts/record_session.py --live``.
"""

from spacedrums.data.audio_capture import AudioCapture, SyncResult, detect_onsets, sync_check
from spacedrums.data.manifest import build_raw_manifest, read_manifest, validate_manifest, write_manifest
from spacedrums.data.metadata import ConsentStatus, SessionKind, SessionMetadata, validate_metadata
from spacedrums.data.protocol import (
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    Protocol,
    SegmentCondition,
    SegmentSpec,
    SegmentType,
    build_protocol,
    check_segment_markers,
)
from spacedrums.data.recorder import GuidedRecorder, QuickCheckThresholds
from spacedrums.data.validation import VerifyThresholds, validate_verification, verify_session

__all__ = [
    "PROTOCOL_ID",
    "PROTOCOL_VERSION",
    "AudioCapture",
    "ConsentStatus",
    "GuidedRecorder",
    "Protocol",
    "QuickCheckThresholds",
    "SegmentCondition",
    "SegmentSpec",
    "SegmentType",
    "SessionKind",
    "SessionMetadata",
    "SyncResult",
    "VerifyThresholds",
    "build_protocol",
    "build_raw_manifest",
    "check_segment_markers",
    "detect_onsets",
    "read_manifest",
    "sync_check",
    "validate_manifest",
    "validate_metadata",
    "validate_verification",
    "verify_session",
    "write_manifest",
]
