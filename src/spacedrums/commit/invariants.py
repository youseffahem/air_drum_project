"""Commit-stream safety auditor (Phase 17, Task 17.2): invariants I1, I3 and I4.

    I1  no CommittedStrike while the hand's TrackState.status is outside the allowed set
        (VALID; DEGRADED only when ``commit.allow_degraded_commits``)
    I3  refractory respected: per (stream, hand, zone) ``r_zone`` and per (stream, hand) ``r_hand``
    I4  at most one commit per observed geometry entry episode, per (stream, hand, zone)

A *stream* is one arm's policy instance (``str(arm)``, shadow commits included) and, in addition,
the **audible** stream (every non-shadow commit, whichever arm produced it). The audible stream is
what the user hears; it is the one that can break across an arm switch or a model fallback even
when every arm's own policy is correct.

Entry episodes are observed here from the delivered ``TrackState`` s, with the same containment
test the commit state machine uses (``zone.shape.contains(tip_filtered)`` on VALID/DEGRADED
states): an episode starts at an outside-to-inside transition and ends when the tip leaves the
zone or tracking is lost. Reactive commits belong to the episode the tip is in at the commit
frame. An anticipatory commit (RULE / MODEL) belongs to the first entry of that hand into that
zone observed while ``t_now <= t_impact_target + stale_prediction_tolerance_s`` (the release rule
of ``ZoneCommitMachine``: entry first, then release); a commit whose entry never comes is counted
as ``unattributed`` (a false positive under the V1 no-cancellation rule, not a violation).

This is an **auditor, not a decision stage**: nothing it computes feeds back into a decision. It
therefore may wait for later frames to attribute an anticipatory commit to its entry; causal
components may not (README section 13). Raise-or-log handling belongs to the caller
(``spacedrums.app.invariants.InvariantMonitor`` for the live loop, the Phase 17 replay scripts
for the Phase 09 harness output).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from spacedrums.commit.policy import CommitSettings
from spacedrums.contracts import CandidateSource, CommittedStrike, HandId, TrackState, TrackStatus
from spacedrums.geometry import ZoneRegistry

AUDIBLE = "AUDIBLE"
EPS = 1e-9

INVARIANTS: dict[str, str] = {
    "I1": "no CommittedStrike while TrackState.status is outside {VALID} (or {VALID, DEGRADED} when enabled)",
    "I2": "no record consumed or emitted with t_capture later than the current processed frame",
    "I3": "refractory respected per hand x zone (r_zone) and per hand (r_hand), per arm and audible stream",
    "I4": "at most one commit per observed geometry entry episode, per arm and audible stream",
    "I5": "no commit in an arm-switch / fallback frame, none from a failed model arm, shadow flag = arm",
    "I6": "no audio event without a non-shadow CommittedStrike; each audible commit scheduled exactly once",
}


@dataclass(frozen=True)
class Violation:
    invariant: str
    frame_id: int
    t_capture: float
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invariant": self.invariant,
            "frame_id": self.frame_id,
            "t_capture": self.t_capture,
            "message": self.message,
            "detail": self.detail,
        }


class InvariantViolation(AssertionError):
    """Raised by a monitor in ``raise`` mode (test builds)."""

    def __init__(self, violation: Violation) -> None:
        super().__init__(f"{violation.invariant} at frame {violation.frame_id}: {violation.message}")
        self.violation = violation


@dataclass(frozen=True)
class _Pending:
    stream: str
    hand: HandId
    zone_id: str
    strike_id: str
    deadline: float


class CommitAuditor:
    """Per-session auditor of (tracks, commits) per frame. Frames must be fed in delivery order."""

    def __init__(self, settings: CommitSettings, registry: ZoneRegistry, *, settings_by_arm=None) -> None:
        self.settings = settings
        self.settings_by_arm = dict(settings_by_arm or {})
        self.registry = registry
        self.allowed = settings.allowed_statuses
        self.release_after_s = settings.stale_prediction_tolerance_s
        self._inside: dict[tuple[HandId, str], bool] = {}
        self._episode: Counter[tuple[HandId, str]] = Counter()
        self._pending: list[_Pending] = []
        self._last_zone: dict[tuple[str, HandId, str], float] = {}
        self._last_hand: dict[tuple[str, HandId], float] = {}
        self._zone_until = {}
        self._hand_until = {}
        self._episode_commits: Counter[tuple[str, HandId, str, int]] = Counter()
        self.checks: Counter[str] = Counter()
        self.unattributed: Counter[str] = Counter()
        self.frames = 0

    # -- per frame -----------------------------------------------------------------------------
    def audit_frame(
        self,
        *,
        frame_id: int,
        t_capture: float,
        t_now: float,
        tracks: Mapping[HandId, TrackState],
        commits: Sequence[CommittedStrike],
    ) -> list[Violation]:
        self.frames += 1
        out: list[Violation] = []
        entries = self._observe_entries(tracks)
        still: list[_Pending] = []
        for p in self._pending:  # machine order: an entry this frame wins over the release
            if (p.hand, p.zone_id) in entries:
                out += self._attribute(p.stream, p.hand, p.zone_id, p.strike_id, frame_id, t_capture)
            elif t_now > p.deadline + EPS:
                self.unattributed[p.stream] += 1
            else:
                still.append(p)
        self._pending = still
        for c in sorted(commits, key=lambda s: (str(s.hand_id), s.t_commit, s.strike_id)):
            out += self._commit(c, tracks.get(c.hand_id), frame_id, t_capture)
        return out

    def finish(self) -> None:
        """End of session: anticipatory commits still waiting for an entry are unattributed."""
        for p in self._pending:
            self.unattributed[p.stream] += 1
        self._pending = []

    def summary(self) -> dict[str, Any]:
        return {
            "frames": self.frames,
            "checks": dict(sorted(self.checks.items())),
            "episodes_observed": sum(self._episode.values()),
            "anticipatory_unattributed": dict(sorted(self.unattributed.items())),
        }

    # -- internals ------------------------------------------------------------------------------
    def _observe_entries(self, tracks: Mapping[HandId, TrackState]) -> set[tuple[HandId, str]]:
        entries: set[tuple[HandId, str]] = set()
        for h, track in tracks.items():
            live = (
                track.status in (TrackStatus.VALID, TrackStatus.DEGRADED) and track.tip_filtered is not None
            )
            for zone in self.registry:
                key = (HandId(h), zone.zone_id)
                inside = bool(live and zone.shape.contains(track.tip_filtered))
                if inside and not self._inside.get(key, False):
                    self._episode[key] += 1
                    entries.add(key)
                self._inside[key] = inside
        return entries

    def _commit(
        self, c: CommittedStrike, track: TrackState | None, frame_id: int, t_capture: float
    ) -> list[Violation]:
        out: list[Violation] = []
        detail = {
            "strike_id": c.strike_id,
            "arm": str(c.arm),
            "hand_id": str(c.hand_id),
            "zone_id": c.zone_id,
        }
        settings = self.settings_by_arm.get(c.arm, self.settings)
        self.checks["I1"] += 1
        if track is None or track.frame_id != c.frame_id:
            out.append(Violation("I1", frame_id, t_capture, "commit without the hand's TrackState", detail))
        elif track.status not in settings.allowed_statuses:
            out.append(
                Violation(
                    "I1",
                    frame_id,
                    t_capture,
                    f"commit while status {track.status}",
                    {**detail, "status": str(track.status)},
                )
            )
        streams = (str(c.arm),) + (() if c.shadow else (AUDIBLE,))
        for stream in streams:
            out += self._refractory(stream, c, frame_id, t_capture)
        key = (c.hand_id, c.zone_id)
        if c.source is CandidateSource.REACTIVE or self._inside.get(key, False):
            if not self._inside.get(key, False):
                self.checks["I4"] += 1
                out.append(
                    Violation("I4", frame_id, t_capture, "reactive commit without an observed entry", detail)
                )
            else:
                for stream in streams:
                    out += self._attribute(stream, c.hand_id, c.zone_id, c.strike_id, frame_id, t_capture)
        else:
            deadline = float(c.t_impact_target) + settings.stale_prediction_tolerance_s
            self._pending += [_Pending(s, c.hand_id, c.zone_id, c.strike_id, deadline) for s in streams]
        return out

    def _refractory(
        self, stream: str, c: CommittedStrike, frame_id: int, t_capture: float
    ) -> list[Violation]:
        out: list[Violation] = []
        settings = self.settings_by_arm.get(c.arm, self.settings)
        kz, kh = (stream, c.hand_id, c.zone_id), (stream, c.hand_id)
        self.checks["I3"] += 1
        previous = self._last_zone.get(kz)
        if previous is not None and c.t_commit < self._zone_until[kz] - EPS:
            out.append(
                Violation(
                    "I3",
                    frame_id,
                    t_capture,
                    f"{stream} {c.hand_id}/{c.zone_id} commits {c.t_commit - previous:.4f}s apart < r_zone",
                    {"stream": stream, "strike_id": c.strike_id, "interval_s": c.t_commit - previous},
                )
            )
        previous_hand = self._last_hand.get(kh)
        if previous_hand is not None and c.t_commit < self._hand_until[kh] - EPS:
            out.append(
                Violation(
                    "I3",
                    frame_id,
                    t_capture,
                    f"{stream} {c.hand_id} commits {c.t_commit - previous_hand:.4f}s apart < r_hand",
                    {"stream": stream, "strike_id": c.strike_id, "interval_s": c.t_commit - previous_hand},
                )
            )
        self._zone_until[kz] = max(self._zone_until.get(kz, 0), c.t_commit + settings.refractory_zone_s)
        self._hand_until[kh] = max(self._hand_until.get(kh, 0), c.t_commit + settings.refractory_hand_s)
        self._last_zone[kz] = float(c.t_commit)
        self._last_hand[kh] = float(c.t_commit)
        return out

    def _attribute(
        self, stream: str, hand: HandId, zone_id: str, strike_id: str, frame_id: int, t_capture: float
    ) -> list[Violation]:
        episode = self._episode[(hand, zone_id)]
        key = (stream, hand, zone_id, episode)
        self._episode_commits[key] += 1
        self.checks["I4"] += 1
        if self._episode_commits[key] > 1:
            return [
                Violation(
                    "I4",
                    frame_id,
                    t_capture,
                    f"{stream}: {self._episode_commits[key]} commits in one {hand}/{zone_id} entry episode",
                    {"stream": stream, "strike_id": strike_id, "episode": episode},
                )
            ]
        return []


__all__ = ["AUDIBLE", "INVARIANTS", "CommitAuditor", "InvariantViolation", "Violation"]
