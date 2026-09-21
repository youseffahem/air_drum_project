"""Layer L3: per-hand causal filter + README section 8 state machine (Phase 03, Tasks 03.12-03.13).

Produces ``TrackState`` through ``CausalTracker`` (``Tracker`` interface). Imports only L0.
"""

from spacedrums.tracking.filter import (
    FILTER_TYPES,
    AlphaBetaFilter,
    FilterBenchmarkResult,
    FilterOutput,
    KalmanFilter2D,
    ScalarAngleFilter,
    make_filter,
)
from spacedrums.tracking.state_machine import (
    Decision,
    MachineState,
    StateMachineSettings,
    TrackingStateMachine,
)
from spacedrums.tracking.tracker import CausalTracker, TrackerSettings, TrackReset

__all__ = [
    "FILTER_TYPES",
    "AlphaBetaFilter",
    "CausalTracker",
    "Decision",
    "FilterBenchmarkResult",
    "FilterOutput",
    "KalmanFilter2D",
    "MachineState",
    "ScalarAngleFilter",
    "StateMachineSettings",
    "TrackReset",
    "TrackerSettings",
    "TrackingStateMachine",
    "make_filter",
]
