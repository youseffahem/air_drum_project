"""Refractory timers (Phase 05, Task 05.3): the only commit state that persists across resets.

Per (hand, zone): ``refractory_until = t_commit + r_zone``. Per hand: ``last_commit_t`` for the
minimum inter-commit interval ``r_hand`` (lets rapid alternating hits land on *different* zones
while blocking a double trigger on the same hand within ``r_hand``). Both are cleared only on
``SESSION_START`` (architecture.md section 6.2 reset matrix): timers can suppress a commit, never
create one, so keeping them across ``INVALID``/``STALE``/``MANUAL``/``ARM_SWITCH`` is the safe
direction — a re-acquired hand cannot immediately re-trigger the zone it just hit.
"""

from __future__ import annotations

from spacedrums.contracts import ResetReason


class RefractoryTimers:
    def __init__(self, *, r_zone_s: float, r_hand_s: float) -> None:
        if r_zone_s < 0 or r_hand_s < 0:
            raise ValueError("refractory periods must be non-negative")
        self.r_zone_s = float(r_zone_s)
        self.r_hand_s = float(r_hand_s)
        self._until: dict[str, float] = {}
        self.last_commit_t: float | None = None

    def zone_until(self, zone_id: str) -> float | None:
        return self._until.get(zone_id)

    def zone_blocked(self, zone_id: str, t_now: float) -> bool:
        until = self._until.get(zone_id)
        return until is not None and t_now < until

    def hand_blocked(self, t_now: float) -> bool:
        return (
            self.last_commit_t is not None
            and self.r_hand_s > 0.0
            and (t_now - self.last_commit_t) < self.r_hand_s
        )

    def note_commit(self, zone_id: str, t_commit: float) -> float:
        """Start the zone timer and the hand interval; returns ``refractory_until``."""
        until = float(t_commit) + self.r_zone_s
        self._until[zone_id] = until
        self.last_commit_t = float(t_commit)
        return until

    def reset(self, reason: ResetReason) -> None:
        if reason is ResetReason.SESSION_START:
            self._until.clear()
            self.last_commit_t = None
        # every other reason: timers persist (safe direction)

    def snapshot(self) -> dict[str, float | None]:
        return {
            "last_commit_t": self.last_commit_t,
            **{f"until:{z}": u for z, u in sorted(self._until.items())},
        }


__all__ = ["RefractoryTimers"]
