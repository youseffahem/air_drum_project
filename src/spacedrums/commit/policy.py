"""``CommitPolicy`` implementation (Phase 05, Task 05.3): per hand, per frame, source-agnostic.

Shared post-processing for every arm (A now, B now, C-* later). ``step(candidates, track_state,
t_now)`` reads only the candidate fields (``strike_probability``, ``tti``/``t_impact_pred``/
``t_impact_est``, zone, hand), the hand's ``TrackState`` and ``t_now``; the arm is recorded for
analysis only (``CommittedStrike.arm``, schema-bound to ``source``).

Gate order per candidate (every threshold from the ``commit`` config block; all candidates):

 1. **safety — status**: ``track_state.status`` must be ``VALID`` (``DEGRADED`` only when
    ``allow_degraded_commits``); otherwise every candidate is discarded, every zone machine goes IDLE
    (ARMED discarded) and *nothing is emitted* (README section 8; Q34-Q35). Refractory timers persist.
 2. **safety — frame-drop guard**: ``dropped_since_last > max_dropped_since_last`` -> no commit this frame
    (Phase 17: the pipeline passes ``frames_missing``, which also counts camera stalls).
 3. **zone validity**: the zone exists in the registry and allows this hand.
 4. **stale prediction**: anticipatory candidate with ``t_impact_pred < t_now - stale_prediction_tolerance_s``
    -> rejected (a prediction about the past cannot be scheduled).
 5. **confidence**: ``strike_probability >= p_commit``; a candidate that carries no probability
    (``null`` — an observed crossing is a certain geometric event) is not gated on it.
 6. **time-to-impact**: ``t_ref - t_now <= tti_commit_s`` with ``t_ref = t_impact_pred`` (anticipatory)
    or ``t_impact_est`` (reactive, always in the past -> always passes).
 7. **refractory**: zone timer (``r_zone``) and hand interval (``r_hand``).
 8. **episode**: no second commit for (hand, zone) inside one geometry episode (state machine).
 9. **hysteresis**: ``n_confirm_frames`` consecutive passing frames (ARMED) before COMMITTED.

A commit stamps ``t_commit = t_now``, ``t_impact_target = t_impact_pred`` (anticipatory) or
``t_commit`` (reactive: "play now"), ``gain`` from the injected monotone mapping (Phase 04 curves) and
``refractory_until``. V1 never cancels a commit ("stop-before-impact after commit" is a false positive
by definition; Phase 05 document).

Shadow logging: one policy instance per hand **per arm**; the active arm's instance emits
``shadow = False`` (audio), every other instance ``shadow = True`` (logged only, never scheduled —
the scheduler refuses shadow commits, Phase 04). Instances share nothing.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from spacedrums.commit.refractory import RefractoryTimers
from spacedrums.commit.state_machine import CommitPhase, ZoneCommitMachine
from spacedrums.contracts import (
    Arm,
    CandidateSource,
    CommittedStrike,
    HandId,
    ResetReason,
    StrikeCandidate,
    TrackState,
    TrackStatus,
)
from spacedrums.geometry import ZoneRegistry

ARM_FOR_SOURCE = {CandidateSource.REACTIVE: Arm.A, CandidateSource.RULE: Arm.B}


def frames_missing(dt_s: float | None, nominal_dt_s: float | None, dropped_since_last: int) -> int:
    """Frames missing before a delivered frame (Phase 17, ADR-0040): queue drops and camera stalls alike.

    ``max(dropped_since_last, round(dt / nominal_dt) - 1)`` (half rounds up). A stall delivers no
    frames and so reports no queue drop, yet leaves the same sparse trajectory behind; the commit
    guard ``max_dropped_since_last`` therefore applies to both. Without a nominal interval only the
    queue drops count.
    """
    missing = int(dropped_since_last)
    if dt_s is not None and nominal_dt_s:
        missing = max(missing, int(math.floor(dt_s / nominal_dt_s + 0.5)) - 1)
    return max(0, missing)


GainFn = Callable[[str, float], float]
EpisodeFn = Callable[[HandId, str], str | None]


class Decision(StrEnum):
    COMMITTED = "COMMITTED"
    ARMED = "ARMED"
    REJECT_STATUS = "REJECT_STATUS"
    REJECT_FRAME_DROP = "REJECT_FRAME_DROP"
    REJECT_ZONE = "REJECT_ZONE"
    REJECT_STALE = "REJECT_STALE"
    REJECT_PROBABILITY = "REJECT_PROBABILITY"
    REJECT_TTI = "REJECT_TTI"
    REJECT_REFRACTORY_ZONE = "REJECT_REFRACTORY_ZONE"
    REJECT_REFRACTORY_HAND = "REJECT_REFRACTORY_HAND"
    REJECT_EPISODE = "REJECT_EPISODE"
    REJECT_SOURCE_ARM = "REJECT_SOURCE_ARM"


@dataclass(frozen=True)
class GateTrace:
    frame_id: int
    t_now: float
    candidate_id: str
    zone_id: str
    decision: Decision

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "t_now": self.t_now,
            "candidate_id": self.candidate_id,
            "zone_id": self.zone_id,
            "decision": self.decision.value,
        }


@dataclass(frozen=True)
class CommitSettings:
    """``commit`` config block (all values candidates; Phases 09/18 re-derive them on data)."""

    commit_policy_id: str = "commit-v1"
    tti_commit_s: float = 0.05
    p_commit: float = 0.5
    n_confirm_frames: int = 0
    refractory_zone_s: float = 0.10
    refractory_hand_s: float = 0.04
    allow_degraded_commits: bool = False
    stale_prediction_tolerance_s: float = 0.02
    max_dropped_since_last: int = 1

    def __post_init__(self) -> None:
        if not self.commit_policy_id:
            raise ValueError("commit_policy_id must be non-empty")
        if (
            min(
                self.tti_commit_s,
                self.refractory_zone_s,
                self.refractory_hand_s,
                self.stale_prediction_tolerance_s,
            )
            < 0
        ):
            raise ValueError("time thresholds must be non-negative")
        if not (0.0 <= self.p_commit <= 1.0):
            raise ValueError("p_commit in [0, 1]")
        if self.n_confirm_frames < 0 or self.max_dropped_since_last < 0:
            raise ValueError("n_confirm_frames and max_dropped_since_last must be >= 0")

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> CommitSettings:
        c = cfg["commit"]
        return cls(
            commit_policy_id=str(c["commit_policy_id"]),
            tti_commit_s=float(c["tti_commit_s"]),
            p_commit=float(c["p_commit"]),
            n_confirm_frames=int(c["n_confirm_frames"]),
            refractory_zone_s=float(c["refractory_zone_s"]),
            refractory_hand_s=float(c["refractory_hand_s"]),
            allow_degraded_commits=bool(c["allow_degraded_commits"]),
            stale_prediction_tolerance_s=float(c["stale_prediction_tolerance_s"]),
            max_dropped_since_last=int(c["max_dropped_since_last"]),
        )

    @property
    def allowed_statuses(self) -> tuple[TrackStatus, ...]:
        return (
            (TrackStatus.VALID, TrackStatus.DEGRADED) if self.allow_degraded_commits else (TrackStatus.VALID,)
        )

    def full_id(self) -> str:
        return (
            f"{self.commit_policy_id}:tti{self.tti_commit_s:.3f}:p{self.p_commit:.2f}:n{self.n_confirm_frames}"
            f":rz{self.refractory_zone_s:.3f}:rh{self.refractory_hand_s:.3f}"
            f":deg{int(self.allow_degraded_commits)}:st{self.stale_prediction_tolerance_s:.3f}"
            f":drop{self.max_dropped_since_last}"
        )


class PerHandCommitPolicy:
    """Implements ``spacedrums.contracts.CommitPolicy`` for one hand and one arm."""

    def __init__(
        self,
        hand_id: HandId | str,
        settings: CommitSettings,
        registry: ZoneRegistry,
        *,
        arm: Arm | str,
        shadow: bool,
        gain_fn: GainFn,
        session_id: str = "session",
        episode_fn: EpisodeFn | None = None,
    ) -> None:
        self.hand_id = HandId(hand_id)
        self.settings = settings
        self.registry = registry
        self.arm = Arm(arm)
        self.shadow = bool(shadow)
        self.gain_fn = gain_fn
        self.session_id = session_id
        self.episode_fn = episode_fn
        self.commit_policy_id = settings.full_id()
        self.timers = RefractoryTimers(
            r_zone_s=settings.refractory_zone_s, r_hand_s=settings.refractory_hand_s
        )
        self.machines: dict[str, ZoneCommitMachine] = {
            zone.zone_id: ZoneCommitMachine(
                n_confirm=settings.n_confirm_frames, release_after_s=settings.stale_prediction_tolerance_s
            )
            for zone in registry
        }
        self._strike_n = 0
        self.commits: int = 0
        self.decisions: dict[str, int] = {}
        self.trace: list[GateTrace] = []  # last frame's per-candidate decisions
        self.frames = 0

    # -- CommitPolicy protocol -------------------------------------------------------------
    def reset(self, reason: ResetReason) -> None:
        for m in self.machines.values():
            if reason is ResetReason.ARM_SWITCH:
                m.discard_armed()  # Phase 17: episode suppression survives an arm switch
            else:
                m.reset()
        self.timers.reset(reason)

    def absorb_suppression(self, other: PerHandCommitPolicy) -> None:
        """Audible continuity across an arm switch (Phase 17, ADR-0040).

        The arm that starts sounding inherits the refractory timers and the open-episode
        suppression of the arm that stops sounding, so one physical strike never sounds twice.
        Only suppression moves between arms; ARMED candidates never do (reset matrix).
        """
        if other.hand_id is not self.hand_id:
            raise ValueError("suppression can only move between policies of the same hand")
        self.timers.absorb(other.timers)
        for zone_id, machine in self.machines.items():
            if zone_id in other.machines:
                machine.absorb(other.machines[zone_id].s)

    def step(
        self,
        candidates: Sequence[StrikeCandidate],
        track_state: TrackState,
        t_now: float,
        *,
        dropped_since_last: int = 0,
    ) -> list[CommittedStrike]:
        if track_state.hand_id is not self.hand_id:
            raise ValueError(
                f"commit policy for {self.hand_id} received a TrackState for {track_state.hand_id}"
            )
        self.frames += 1
        self.trace = []
        t_now = float(t_now)
        status_ok = track_state.status in self.settings.allowed_statuses
        if not status_ok:
            for m in self.machines.values():
                m.invalidate()
            for c in candidates:
                self._note(track_state.frame_id, t_now, c, Decision.REJECT_STATUS)
            return []
        pos = track_state.tip_filtered
        for zone in self.registry:
            inside = zone.shape.contains(pos) if pos is not None else None
            self.machines[zone.zone_id].begin_frame(t_now, inside)
        if dropped_since_last > self.settings.max_dropped_since_last:
            for c in candidates:
                self._note(track_state.frame_id, t_now, c, Decision.REJECT_FRAME_DROP)
            for m in self.machines.values():
                m.no_passing_candidate()
            return []
        out: list[CommittedStrike] = []
        passing_zones: set[str] = set()
        ordered = sorted(candidates, key=lambda c: (self._t_ref(c), c.zone_id, c.candidate_id))
        for c in ordered:
            decision = self._evaluate(c, t_now)
            if decision in (Decision.COMMITTED, Decision.ARMED):
                passing_zones.add(c.zone_id)
            if decision is Decision.COMMITTED:
                out.append(self._commit(c, track_state, t_now))
            self._note(track_state.frame_id, t_now, c, decision)
        for zone_id, m in self.machines.items():
            if zone_id not in passing_zones:
                m.no_passing_candidate()
        return out

    # -- gates -----------------------------------------------------------------------------
    @staticmethod
    def _t_ref(c: StrikeCandidate) -> float:
        return float(c.t_impact_pred if c.t_impact_pred is not None else c.t_impact_est)  # type: ignore[arg-type]

    def _evaluate(self, c: StrikeCandidate, t_now: float) -> Decision:
        s = self.settings
        if c.hand_id is not self.hand_id:
            return Decision.REJECT_ZONE
        if c.source is CandidateSource.MODEL:
            arm_ok = self.arm not in (Arm.A, Arm.B)  # schema invariant: MODEL <-> C-*
        else:
            arm_ok = ARM_FOR_SOURCE[c.source] is self.arm  # REACTIVE <-> A, RULE <-> B
        if not arm_ok:
            return Decision.REJECT_SOURCE_ARM
        zone = self.registry[c.zone_id] if c.zone_id in self.machines else None
        if zone is None or self.hand_id not in zone.allowed_hands:
            return Decision.REJECT_ZONE
        t_ref = self._t_ref(c)
        if not math.isfinite(t_ref):  # Phase 17: an undefined time can never be scheduled
            return Decision.REJECT_STALE
        if c.t_impact_pred is not None and t_ref < t_now - s.stale_prediction_tolerance_s:
            return Decision.REJECT_STALE
        # ``not (p >= p_commit)`` also rejects a NaN probability (a NaN passes ``p < p_commit``)
        if c.strike_probability is not None and not c.strike_probability >= s.p_commit:
            return Decision.REJECT_PROBABILITY
        if t_ref - t_now > s.tti_commit_s:
            return Decision.REJECT_TTI
        if self.timers.zone_blocked(c.zone_id, t_now):
            return Decision.REJECT_REFRACTORY_ZONE
        if self.timers.hand_blocked(t_now):
            return Decision.REJECT_REFRACTORY_HAND
        m = self.machines[c.zone_id]
        if m.episode_blocked() or m.s.phase in (CommitPhase.COMMITTED, CommitPhase.REFRACTORY):
            return Decision.REJECT_EPISODE
        return Decision.COMMITTED if m.passing_candidate() else Decision.ARMED

    def _commit(self, c: StrikeCandidate, track_state: TrackState, t_now: float) -> CommittedStrike:
        anticipatory = c.t_impact_pred is not None
        t_target = float(c.t_impact_pred) if anticipatory else t_now
        until = self.timers.note_commit(c.zone_id, t_now)
        n = self.machines[c.zone_id].commit(t_now, t_target, until)
        episode = self.episode_fn(self.hand_id, c.zone_id) if (self.episode_fn and not anticipatory) else None
        self._strike_n += 1
        self.commits += 1
        return CommittedStrike(
            strike_id=f"{self.session_id}-{self.hand_id}-{self.arm}-s{self._strike_n:06d}",
            candidate_id=c.candidate_id,
            frame_id=track_state.frame_id,
            t_capture=track_state.t_capture,
            hand_id=self.hand_id,
            zone_id=c.zone_id,
            source=c.source,
            derivation=c.derivation,
            arm=self.arm,
            shadow=self.shadow,
            t_commit=t_now,
            t_impact_target=t_target,
            intensity_proxy=float(c.intensity_proxy),
            gain=float(self.gain_fn(c.zone_id, float(c.intensity_proxy))),
            refractory_until=until,
            episode_id=episode or f"{self.session_id}-{self.hand_id}-{c.zone_id}-e{n:06d}",
            commit_policy_id=self.commit_policy_id,
        )

    def _note(self, frame_id: int, t_now: float, c: StrikeCandidate, d: Decision) -> None:
        self.decisions[d.value] = self.decisions.get(d.value, 0) + 1
        self.trace.append(GateTrace(frame_id, t_now, c.candidate_id, c.zone_id, d))

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "hand_id": str(self.hand_id),
            "arm": str(self.arm),
            "shadow": self.shadow,
            "zones": {z: m.s.to_dict() for z, m in self.machines.items()},
            "timers": self.timers.snapshot(),
        }


__all__ = [
    "ARM_FOR_SOURCE",
    "CommitSettings",
    "Decision",
    "GateTrace",
    "PerHandCommitPolicy",
    "frames_missing",
]
