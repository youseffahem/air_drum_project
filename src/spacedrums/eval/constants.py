"""Phase 09 evaluation policy. Values are frozen only after participant validation."""

HARNESS_VERSION = "p09-harness-v1-development"
W_CANDIDATES_S = (0.025, 0.05, 0.075, 0.1)
# Participant validation is pending. No primary W is frozen yet.
W_CANDIDATE_DEFAULT_S = 0.05
W_PRIMARY_S: float | None = None
DELAY_POLICIES = ("zero", "fixed", "per_frame")
ACTIVE_TIME_DEFINITION = "accepted segment union, less tracking-loss interval union, per hand"
EXCLUDED_LABEL_CLASSES = frozenset(("AMBIGUOUS", "EXCLUDED"))

# Phase 16: a replay/idle-camera profile is not a representative live-stroke constant.
# Keep this unset until the required live evidence and reviewer acceptance exist.
DELTA_PROC_LIVE_S: float | None = None
# Phase 13 Task 13.6 candidate materiality rule; any changed commit set also triggers review.
DELTA_PROC_MATERIAL_CHANGE_S = 0.001
