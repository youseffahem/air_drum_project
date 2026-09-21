"""Per-(hand, zone) commit state machine (Phase 05, Task 05.3) — pure transition logic.

    IDLE ──(candidate passes every gate; n_confirm = 0)──────────────► COMMITTED
    IDLE ──(candidate passes; n_confirm > 0)──► ARMED ──(n_confirm consecutive passing frames)──► COMMITTED
    ARMED ──(a frame without a passing candidate for this zone)──► IDLE   (pending candidate discarded)
    COMMITTED ──(next frame)──► REFRACTORY(until = t_commit + r_zone) ──(timer)──► IDLE
    any ──(track INVALID/STALE, or reset)──► IDLE   (ARMED discarded; refractory timers persist elsewhere)

Duplicate suppression by **episode** (one commit per geometry episode, README section 14): after a
commit the zone remembers that it is waiting for the observed tip to *enter* (an anticipatory commit
precedes the crossing) or that the tip is *inside* after a committed entry; no second commit is
accepted until the tip has been observed leaving the zone, or — for a predicted commit whose crossing
never materialises (a false positive by the V1 no-cancellation rule) — until
``t_impact_target + release_after_s`` has passed. The "inside" flag comes from the policy, which
reads the zone registry (commit may import geometry; architecture.md section 2.2).

The machine decides; the policy evaluates gates and stamps records. Kept separate so every
transition is unit-testable without candidates or zones.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CommitPhase(StrEnum):
    IDLE = "IDLE"
    ARMED = "ARMED"
    COMMITTED = "COMMITTED"
    REFRACTORY = "REFRACTORY"


@dataclass
class ZoneCommitState:
    phase: CommitPhase = CommitPhase.IDLE
    armed_frames: int = 0
    refractory_until: float | None = None
    inside: bool = False  # observed tip currently inside the zone
    commit_pending: bool = False  # committed; crossing not yet observed
    committed_in_episode: bool = False  # committed; tip currently inside after that commit
    pending_target_t: float | None = None
    episode_n: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "armed_frames": self.armed_frames,
            "refractory_until": self.refractory_until,
            "inside": self.inside,
            "commit_pending": self.commit_pending,
            "committed_in_episode": self.committed_in_episode,
            "pending_target_t": self.pending_target_t,
            "episode_n": self.episode_n,
        }


class ZoneCommitMachine:
    """Transitions for one (hand, zone)."""

    def __init__(self, *, n_confirm: int, release_after_s: float) -> None:
        if n_confirm < 0 or release_after_s < 0:
            raise ValueError("n_confirm >= 0 and release_after_s >= 0 required")
        self.n_confirm = int(n_confirm)
        self.release_after_s = float(release_after_s)
        self.s = ZoneCommitState()

    # -- per-frame bookkeeping -------------------------------------------------------------
    def begin_frame(self, t_now: float, inside: bool | None) -> None:
        """Timers, episode entry/exit; ``inside`` None = no observed position this frame."""
        s = self.s
        if s.phase is CommitPhase.COMMITTED:
            s.phase = CommitPhase.REFRACTORY
        if s.phase is CommitPhase.REFRACTORY and (s.refractory_until is None or t_now >= s.refractory_until):
            s.phase = CommitPhase.IDLE
        if inside is not None:
            if inside and not s.inside:  # entry
                if s.commit_pending:
                    s.commit_pending, s.committed_in_episode = False, True
            elif not inside and s.inside:  # exit
                s.committed_in_episode = False
            s.inside = inside
        if (
            s.commit_pending
            and s.pending_target_t is not None
            and t_now > s.pending_target_t + self.release_after_s
        ):
            s.commit_pending, s.pending_target_t = False, None  # predicted crossing never observed

    def episode_blocked(self) -> bool:
        return self.s.commit_pending or (self.s.inside and self.s.committed_in_episode)

    # -- candidate outcome -----------------------------------------------------------------
    def no_passing_candidate(self) -> None:
        if self.s.phase is CommitPhase.ARMED:
            self.s.phase, self.s.armed_frames = CommitPhase.IDLE, 0

    def passing_candidate(self) -> bool:
        """A gate-passing candidate this frame; True when the machine commits now."""
        s = self.s
        if s.phase in (CommitPhase.COMMITTED, CommitPhase.REFRACTORY):
            return False
        if self.n_confirm == 0:
            return True
        if s.phase is CommitPhase.IDLE:
            s.phase, s.armed_frames = CommitPhase.ARMED, 1
        else:
            s.armed_frames += 1
        return s.armed_frames >= self.n_confirm

    def commit(self, t_commit: float, t_impact_target: float, refractory_until: float) -> int:
        """Record the commit; returns the episode number for the strike's ``episode_id``."""
        s = self.s
        s.phase, s.armed_frames = CommitPhase.COMMITTED, 0
        s.refractory_until = float(refractory_until)
        s.episode_n += 1
        if s.inside:
            s.committed_in_episode = True
        else:
            s.commit_pending, s.pending_target_t = True, float(t_impact_target)
        del t_commit  # kept in the signature for symmetry with the policy's stamps
        return s.episode_n

    def invalidate(self) -> None:
        """Track not live: IDLE, ARMED discarded, episode closed (geometry closes it too)."""
        s = self.s
        s.phase, s.armed_frames = CommitPhase.IDLE, 0
        s.inside, s.commit_pending, s.committed_in_episode, s.pending_target_t = False, False, False, None

    def reset(self) -> None:
        """Reset-matrix reset (any reason): like invalidate; timers live in ``RefractoryTimers``."""
        self.invalidate()


__all__ = ["CommitPhase", "ZoneCommitMachine", "ZoneCommitState"]
