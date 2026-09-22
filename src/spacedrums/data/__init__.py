"""Dataset pipeline: Phase 06 collection (recording protocol, guided recorder hooks, session
metadata, microphone capture + sync check, session verification / unusable-recording policy, raw
manifests) and Phase 07 labelling (``labels`` subpackage: rules, non-causal reference smoother,
label generator, validator, QC/review, acoustic pairing, statistics, labelled-dataset manifest and
card) plus participant-level splits (``splits``).

Nothing in this package records a person by itself: the person-dependent live recording is
reachable only through ``scripts/record_session.py --live``.

Causality note: ``spacedrums.data.labels`` is the only place in the system allowed to use future
frames (``docs/architecture/causality-tests.md`` section 1.1). The layer contract places
``spacedrums.data`` above every causal stage and ``.importlinter`` additionally forbids the causal
packages from importing ``spacedrums.data.labels`` by name, so a label artefact cannot reach a
runtime component.
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
from spacedrums.data.splits import Roster, build_split, plan_for, validate_split, write_split
from spacedrums.data.validation import VerifyThresholds, validate_verification, verify_session

__all__ = [
    "PROTOCOL_ID",
    "PROTOCOL_VERSION",
    "AudioCapture",
    "ConsentStatus",
    "GuidedRecorder",
    "Protocol",
    "QuickCheckThresholds",
    "Roster",
    "SegmentCondition",
    "SegmentSpec",
    "SegmentType",
    "SessionKind",
    "SessionMetadata",
    "SyncResult",
    "VerifyThresholds",
    "build_protocol",
    "build_raw_manifest",
    "build_split",
    "check_segment_markers",
    "detect_onsets",
    "plan_for",
    "read_manifest",
    "sync_check",
    "validate_manifest",
    "validate_metadata",
    "validate_split",
    "validate_verification",
    "verify_session",
    "write_manifest",
    "write_split",
]
