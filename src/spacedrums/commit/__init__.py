"""Layer L6 (decision): per-hand commit state machine, refractory, duplicate suppression, safety
gates — the ``CommitPolicy`` shared by every arm (Phase 05, Task 05.3).

Imports only L0, ``geometry`` (zone registry, read-only: episode "inside" test) and ``tracking``
types; never ``hands``/``stick``/``prediction``/``features`` (architecture.md section 2.2).
"""

from spacedrums.commit.policy import ARM_FOR_SOURCE, CommitSettings, Decision, GateTrace, PerHandCommitPolicy
from spacedrums.commit.refractory import RefractoryTimers
from spacedrums.commit.state_machine import CommitPhase, ZoneCommitMachine, ZoneCommitState

__all__ = [
    "ARM_FOR_SOURCE",
    "CommitPhase",
    "CommitSettings",
    "Decision",
    "GateTrace",
    "PerHandCommitPolicy",
    "RefractoryTimers",
    "ZoneCommitMachine",
    "ZoneCommitState",
]
