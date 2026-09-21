"""Layer L2 (perception): hand landmarks -> ``HandObservation`` x2 per frame (Phase 03).

Task 03.1: estimator wrapper, coordinate boundary, ``detector_id``, per-frame timing.
Task 03.2: temporal LEFT/RIGHT identity assignment (``identity``).
Task 03.3: grip reference points (``grip``).

Imports only L0 and ``spacedrums.capture.roi`` (px<->normalized helper), architecture.md section 2.2.
"""

from spacedrums.hands.coords import (
    DetectorInput,
    InputFrame,
    bbox_of,
    native_to_full_px,
    native_to_roi_norm,
)
from spacedrums.hands.grip import (
    DEFAULT_POINT_WEIGHTS,
    GRIP_WEIGHT_LANDMARKS,
    LANDMARK_INDEX,
    GripDirectionMethod,
    GripReference,
    GripSettings,
    grip_point,
    grip_reference,
)
from spacedrums.hands.identity import (
    WRIST,
    HandAssignment,
    IdentityAssigner,
    IdentityCandidate,
    IdentityCounters,
    IdentityEvent,
    IdentityEventKind,
    IdentityFrameResult,
    IdentityMode,
    IdentitySettings,
)
from spacedrums.hands.landmarker import (
    DETECTOR_FAMILY,
    HandDetection,
    HandLandmarker,
    HandLandmarkerSettings,
    HandsCounters,
    HandsFrameResult,
    LandmarkBackend,
    MediaPipeHandLandmarkerBackend,
    RawDetection,
    label_to_hand_id,
    observations_as_dicts,
)
from spacedrums.hands.model_asset import (
    ModelAsset,
    ModelAssetError,
    assets_root,
    manifest_path,
    resolve_model_asset,
)

__all__ = [
    "DEFAULT_POINT_WEIGHTS",
    "DETECTOR_FAMILY",
    "GRIP_WEIGHT_LANDMARKS",
    "LANDMARK_INDEX",
    "GripDirectionMethod",
    "GripReference",
    "GripSettings",
    "grip_point",
    "grip_reference",
    "WRIST",
    "HandAssignment",
    "IdentityAssigner",
    "IdentityCandidate",
    "IdentityCounters",
    "IdentityEvent",
    "IdentityEventKind",
    "IdentityFrameResult",
    "IdentityMode",
    "IdentitySettings",
    "DetectorInput",
    "HandDetection",
    "HandLandmarker",
    "HandLandmarkerSettings",
    "HandsCounters",
    "HandsFrameResult",
    "InputFrame",
    "LandmarkBackend",
    "MediaPipeHandLandmarkerBackend",
    "ModelAsset",
    "ModelAssetError",
    "RawDetection",
    "assets_root",
    "bbox_of",
    "label_to_hand_id",
    "manifest_path",
    "native_to_full_px",
    "native_to_roi_norm",
    "observations_as_dicts",
    "resolve_model_asset",
]
