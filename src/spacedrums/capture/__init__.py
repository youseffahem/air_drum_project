"""Layer L1: timestamped webcam capture, fixed playing ROI, bounded queue (Phase 02).

Produces ``FrameSample`` (contracts.md section 3.1) through :class:`LiveFrameSource`
(``FrameSource`` interface) and, since Phase 05, replays recorded sessions through
:class:`ReplayFrameSource` (record/replay symmetry, architecture.md section 12). Imports only
layer L0 (architecture.md section 2.2).
"""

from spacedrums.capture.backend import (
    CameraBackend,
    CameraOpenSpec,
    NegotiatedMode,
    OpenCvCamera,
    RawFrame,
    SyntheticCamera,
)
from spacedrums.capture.exposure import ExposureGuard, ExposureWatch
from spacedrums.capture.frame_queue import BoundedFrameQueue
from spacedrums.capture.native import NativeCapture, NativeModeRejected, tracking_frame
from spacedrums.capture.replay import ReplayFrameSource
from spacedrums.capture.roi import (
    Roi,
    crop_roi,
    norm_to_px,
    norm_to_px_point,
    px_to_norm,
    px_to_norm_point,
)
from spacedrums.capture.source import CaptureSettings, LiveFrameSource
from spacedrums.capture.stats import CaptureStats, IntervalStats, StallDetector, interval_stats
from spacedrums.capture.timestamps import DriverTimestampMapper, GrabReturnStamper, LinearMap

__all__ = [
    "BoundedFrameQueue",
    "CameraBackend",
    "CameraOpenSpec",
    "CaptureSettings",
    "CaptureStats",
    "DriverTimestampMapper",
    "ExposureGuard",
    "ExposureWatch",
    "GrabReturnStamper",
    "IntervalStats",
    "LinearMap",
    "LiveFrameSource",
    "NativeCapture",
    "NativeModeRejected",
    "NegotiatedMode",
    "OpenCvCamera",
    "RawFrame",
    "ReplayFrameSource",
    "Roi",
    "StallDetector",
    "SyntheticCamera",
    "crop_roi",
    "interval_stats",
    "norm_to_px",
    "norm_to_px_point",
    "px_to_norm",
    "px_to_norm_point",
    "tracking_frame",
]
