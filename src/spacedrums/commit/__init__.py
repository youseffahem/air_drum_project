"""Layer L6 (decision): per-hand commit state machine, refractory, duplicate suppression, safety
gates — the ``CommitPolicy`` shared by every arm (Phase 05, Task 05.3).

Imports only L0, ``geometry`` (zone registry, read-only: episode "inside" test) and ``tracking``
types; never ``hands``/``stick``/``prediction``/``features`` (architecture.md section 2.2).
Phase 17 adds ``invariants.CommitAuditor`` (I1/I3/I4 audit of commit streams; never a decision input).
"""

from spacedrums.commit.invariants import AUDIBLE, INVARIANTS, CommitAuditor, InvariantViolation, Violation
from spacedrums.commit.policy import (
    ARM_FOR_SOURCE,
    CommitSettings,
    Decision,
    GateTrace,
    PerHandCommitPolicy,
    frames_missing,
)
from spacedrums.commit.refractory import RefractoryTimers
from spacedrums.commit.state_machine import CommitPhase, ZoneCommitMachine, ZoneCommitState

__all__ = [
    "ARM_FOR_SOURCE",
    "AUDIBLE",
    "INVARIANTS",
    "CommitAuditor",
    "CommitPhase",
    "CommitSettings",
    "Decision",
    "GateTrace",
    "InvariantViolation",
    "PerHandCommitPolicy",
    "RefractoryTimers",
    "Violation",
    "ZoneCommitMachine",
    "ZoneCommitState",
    "frames_missing",
]
