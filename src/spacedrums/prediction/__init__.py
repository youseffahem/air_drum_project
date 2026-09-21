"""Layer L5: ``Anticipator`` implementations (Phase 05: rule-based arm B; Phases 09-13: learned C-*).

Imports only L0 and ``tracking`` types; **never** ``geometry`` (architecture.md section 2.2:
a predictor cannot peek at zones — geometry decides impacts from the trajectory it returns).
"""

from spacedrums.prediction.base import LIVE, AnticipatorBase, DeclineReason
from spacedrums.prediction.rule_based import (
    ACCELERATION_SOURCES,
    COMBINE_MODES,
    MOTION_MODELS,
    RuleBasedAnticipator,
    RuleSettings,
    combine_gates,
    direction_gate,
    extrapolate,
    speed_gate,
    validity_gate,
)

__all__ = [
    "ACCELERATION_SOURCES",
    "COMBINE_MODES",
    "LIVE",
    "MOTION_MODELS",
    "AnticipatorBase",
    "DeclineReason",
    "RuleBasedAnticipator",
    "RuleSettings",
    "combine_gates",
    "direction_gate",
    "extrapolate",
    "speed_gate",
    "validity_gate",
]
