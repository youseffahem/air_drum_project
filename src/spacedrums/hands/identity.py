"""LEFT/RIGHT identity assignment (Phase 03, Task 03.2).

Combines the estimator's handedness label + score with **temporal continuity** (nearest previous
wrist position, gated) to assign each detection a stable ``hand_id``; detects and logs the cases
where the two sources disagree; and when the assignment is ambiguous it does **not** guess: both
hands are flagged and their ``handedness_score`` is capped so that downstream tracking can only
treat them as ``DEGRADED`` (README section 8; the cap is checked against ``tracking.c_min`` /
``tracking.c_valid`` by the config loader).

Causality: the assigner keeps only the previous assigned wrist position per hand and its
``t_capture``; it never sees a later frame (architecture.md causality rule).

Scoring (all values in [0, 1]; every weight and threshold is a tunable candidate):

* label term ``p_label(h | det) = score`` if the estimator's (swap-mapped) label is ``h``, else
  ``1 - score``;
* temporal term ``p_temp(h | det) = max(0, 1 - d / gate_distance)`` where ``d`` is the wrist
  distance (ROI-normalized) to hand ``h``'s previous wrist; undefined (no information) when
  ``h`` has no previous position younger than ``max_gap_s``;
* combined ``s(h | det) = w_label * p_label + (1 - w_label) * p_temp`` when both exist,
  ``p_label`` alone otherwise.

The assignment is the injective map hands -> detections maximising the summed score, found by
enumeration (at most 2 hands x ``num_hands`` <= 4 detections). **Ambiguity** = the margin between
the best and the second-best total is below ``ambiguity_margin`` (this covers the crossing case:
two detections both within the gate of both previous positions with weak or contradictory labels).

Events (logged at INFO via ``logging`` and returned in the frame result):

* ``LABEL_OVERRIDE`` — continuity won over the estimator label (the assigned ``hand_id`` differs
  from the swap-mapped label): the raw label is what a *raw* swap would look like;
* ``CONTINUITY_OVERRIDE`` — the label won: the assigned detection is not the nearest gated
  detection to that hand's previous wrist;
* ``IDENTITY_JUMP`` — the assigned detection lies outside the gate of the hand's own previous
  wrist but inside the gate of the *other* hand's previous wrist (a possible track swap);
* ``AMBIGUOUS`` — margin below threshold; both hands capped.

Nothing here is a result: swap rates are *measured* by ``scripts/hands_landmark_check.py`` and
reported per capture; the crossing-scenario measurement needs a dev capture with deliberate
crossings and is PENDING (no new recordings in this task).
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from spacedrums.contracts import HandId

log = logging.getLogger(__name__)

WRIST = 0  # MediaPipe landmark index of the wrist
_HANDS = (HandId.LEFT, HandId.RIGHT)


class IdentityMode(StrEnum):
    RAW = "RAW"  # Task 03.1 behaviour: estimator label only (baseline for the swap-rate measurement)
    TEMPORAL = "TEMPORAL"  # Task 03.2: label + continuity


class IdentityEventKind(StrEnum):
    LABEL_OVERRIDE = "LABEL_OVERRIDE"
    CONTINUITY_OVERRIDE = "CONTINUITY_OVERRIDE"
    IDENTITY_JUMP = "IDENTITY_JUMP"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class IdentitySettings:
    """``hands.identity`` config block (schema 1.2, ADR-0014 amendment). All candidates."""

    mode: IdentityMode = IdentityMode.TEMPORAL
    gate_distance: float = 0.15  # ROI-normalized wrist displacement allowed for continuity
    max_gap_s: float = 0.25  # previous position older than this carries no continuity information
    w_label: float = 0.5  # weight of the estimator label term; continuity weight is 1 - w_label
    ambiguity_margin: float = 0.15  # best-vs-second total-score margin below which the frame is ambiguous
    ambiguous_score_cap: float = 0.5  # handedness_score cap when ambiguous; in [c_min, c_valid) (loader)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", IdentityMode(self.mode))
        if self.gate_distance <= 0:
            raise ValueError("gate_distance must be > 0")
        if self.max_gap_s <= 0:
            raise ValueError("max_gap_s must be > 0")
        for name in ("w_label", "ambiguity_margin", "ambiguous_score_cap"):
            v = getattr(self, name)
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"{name} must lie in [0, 1], got {v!r}")

    @classmethod
    def from_config(cls, hands_cfg: dict[str, Any]) -> IdentitySettings:
        i = hands_cfg["identity"]
        return cls(mode=IdentityMode(i["mode"]), gate_distance=float(i["gate_distance"]),
                   max_gap_s=float(i["max_gap_s"]), w_label=float(i["w_label"]),
                   ambiguity_margin=float(i["ambiguity_margin"]),
                   ambiguous_score_cap=float(i["ambiguous_score_cap"]))

    def id_fragment(self) -> str:
        if self.mode is IdentityMode.RAW:
            return "id-raw"
        return (f"id-temporal-g{self.gate_distance:.2f}-gap{self.max_gap_s:.2f}-wl{self.w_label:.2f}"
                f"-m{self.ambiguity_margin:.2f}-cap{self.ambiguous_score_cap:.2f}")


@dataclass(frozen=True)
class IdentityCandidate:
    """What the assigner needs to know about one detection (already ROI-normalized)."""

    index: int
    wrist: tuple[float, float]
    raw_hand_id: HandId | None  # swap-mapped estimator label; None = unknown label
    raw_score: float


@dataclass(frozen=True)
class IdentityEvent:
    frame_id: int
    t_capture: float
    kind: IdentityEventKind
    hand_id: HandId | None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"frame_id": self.frame_id, "t_capture": self.t_capture, "kind": str(self.kind),
                "hand_id": str(self.hand_id) if self.hand_id is not None else None, "detail": self.detail}


@dataclass(frozen=True)
class HandAssignment:
    hand_id: HandId
    candidate: IdentityCandidate
    score: float  # combined identity confidence before capping
    handedness_score: float  # what goes into HandObservation (capped when ambiguous)
    p_label: float
    p_temporal: float | None  # None: no continuity information for this hand
    distance_own: float | None  # wrist distance to this hand's previous wrist
    distance_other: float | None  # wrist distance to the other hand's previous wrist


@dataclass(frozen=True)
class IdentityFrameResult:
    assignments: dict[HandId, HandAssignment]
    ambiguous: bool
    margin: float | None  # best - second best total score; None when < 2 alternatives
    events: tuple[IdentityEvent, ...]
    n_unassigned: int  # detections left without a hand (extra hands / unknown labels)


@dataclass
class IdentityCounters:
    frames: int = 0
    frames_with_detections: int = 0
    assigned: int = 0
    ambiguous_frames: int = 0
    label_overrides: int = 0
    continuity_overrides: int = 0
    identity_jumps: int = 0
    unassigned: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class _Memory:
    wrist: tuple[float, float]
    t_capture: float


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def _nearest(candidates: Sequence[IdentityCandidate],
             wrist: tuple[float, float]) -> tuple[IdentityCandidate, float]:
    best = min(candidates, key=lambda c: _dist(c.wrist, wrist))
    return best, _dist(best.wrist, wrist)


class IdentityAssigner:
    """Per-session, per-frame causal LEFT/RIGHT assignment. One instance per ``HandLandmarker``."""

    def __init__(self, settings: IdentitySettings) -> None:
        self.settings = settings
        self.counters = IdentityCounters()
        self._memory: dict[HandId, _Memory] = {}

    def reset(self) -> None:
        self._memory.clear()

    # -- scoring -----------------------------------------------------------------------------
    def _memory_for(self, hand: HandId, t_capture: float) -> _Memory | None:
        m = self._memory.get(hand)
        if m is None or (t_capture - m.t_capture) > self.settings.max_gap_s:
            return None
        return m

    def _score(self, hand: HandId, c: IdentityCandidate,
               mem: _Memory | None) -> tuple[float, float, float | None, float | None]:
        s = self.settings
        if c.raw_hand_id is None:
            p_label = 0.5  # unknown label carries no information
        else:
            p_label = c.raw_score if c.raw_hand_id is hand else 1.0 - c.raw_score
        if mem is None:
            return p_label, p_label, None, None
        d = _dist(c.wrist, mem.wrist)
        p_temp = max(0.0, 1.0 - d / s.gate_distance)
        return s.w_label * p_label + (1.0 - s.w_label) * p_temp, p_label, p_temp, d

    # -- main entry --------------------------------------------------------------------------
    def assign(self, candidates: Sequence[IdentityCandidate], frame_id: int,
               t_capture: float) -> IdentityFrameResult:
        s = self.settings
        self.counters.frames += 1
        if candidates:
            self.counters.frames_with_detections += 1
        if s.mode is IdentityMode.RAW:
            return self._assign_raw(candidates, frame_id, t_capture)

        mems = {h: self._memory_for(h, t_capture) for h in _HANDS}
        # score table: (hand, candidate index) -> (combined, p_label, p_temp, d)
        table = {(h, c.index): self._score(h, c, mems[h]) for h in _HANDS for c in candidates}

        # enumerate injective assignments (hand -> candidate or None); at least one hand assigned
        options: list[tuple[float, dict[HandId, IdentityCandidate]]] = []
        cand_by_index = {c.index: c for c in candidates}
        choices = [None, *cand_by_index.keys()]
        for pick in itertools.product(choices, repeat=len(_HANDS)):
            used = [p for p in pick if p is not None]
            if len(used) != len(set(used)) or not used:
                continue
            total = sum(table[(h, p)][0] for h, p in zip(_HANDS, pick, strict=True) if p is not None)
            chosen = {h: cand_by_index[p] for h, p in zip(_HANDS, pick, strict=True) if p is not None}
            options.append((total, chosen))
        if not options:
            return IdentityFrameResult(assignments={}, ambiguous=False, margin=None, events=(),
                                       n_unassigned=0)
        # the score sum rewards assigning a second hand whenever its score > 0; a tie between the
        # two-hand assignment and its swap yields margin 0 -> ambiguous (never a guess)
        options.sort(key=lambda o: -o[0])
        best_total, best = options[0]
        margin = (best_total - options[1][0]) if len(options) > 1 else None
        ambiguous = margin is not None and margin < s.ambiguity_margin

        events: list[IdentityEvent] = []
        assignments: dict[HandId, HandAssignment] = {}
        for h, c in best.items():
            combined, p_label, p_temp, d_own = table[(h, c.index)]
            other = HandId.RIGHT if h is HandId.LEFT else HandId.LEFT
            d_other = _dist(c.wrist, mems[other].wrist) if mems[other] is not None else None
            handedness = min(combined, s.ambiguous_score_cap) if ambiguous else combined
            assignments[h] = HandAssignment(hand_id=h, candidate=c, score=combined,
                                            handedness_score=handedness, p_label=p_label,
                                            p_temporal=p_temp, distance_own=d_own, distance_other=d_other)
            if c.raw_hand_id is not None and c.raw_hand_id is not h:
                self.counters.label_overrides += 1
                events.append(IdentityEvent(frame_id, t_capture, IdentityEventKind.LABEL_OVERRIDE, h,
                                            {"raw_label": str(c.raw_hand_id), "raw_score": c.raw_score,
                                             "p_temporal": p_temp, "distance_own": d_own}))
            mem_h = mems[h]
            if mem_h is not None:
                nearest, d_nearest = _nearest(candidates, mem_h.wrist)
                if nearest.index != c.index and d_nearest <= s.gate_distance:
                    self.counters.continuity_overrides += 1
                    events.append(IdentityEvent(frame_id, t_capture, IdentityEventKind.CONTINUITY_OVERRIDE, h,
                                                {"assigned_distance": d_own, "nearest_distance": d_nearest,
                                                 "raw_label": str(c.raw_hand_id), "raw_score": c.raw_score}))
                if d_own is not None and d_own > s.gate_distance and d_other is not None \
                        and d_other <= s.gate_distance:
                    self.counters.identity_jumps += 1
                    events.append(IdentityEvent(frame_id, t_capture, IdentityEventKind.IDENTITY_JUMP, h,
                                                {"distance_own": d_own, "distance_other": d_other,
                                                 "raw_label": str(c.raw_hand_id), "raw_score": c.raw_score}))
        if ambiguous:
            self.counters.ambiguous_frames += 1
            events.append(IdentityEvent(frame_id, t_capture, IdentityEventKind.AMBIGUOUS, None,
                                        {"margin": margin, "n_detections": len(candidates),
                                         "assigned": sorted(str(h) for h in assignments)}))
        for e in events:
            log.info("identity %s frame %d hand %s %s", e.kind, e.frame_id, e.hand_id, e.detail)

        # memory update: assigned hands remember their wrist; unassigned hands keep the old memory
        # until max_gap_s expires (a hand hidden for a moment must still be recognised).
        for h, a in assignments.items():
            self._memory[h] = _Memory(a.candidate.wrist, t_capture)
        self.counters.assigned += len(assignments)
        n_unassigned = len(candidates) - len(assignments)
        self.counters.unassigned += n_unassigned
        return IdentityFrameResult(assignments=assignments, ambiguous=ambiguous, margin=margin,
                                   events=tuple(events), n_unassigned=n_unassigned)

    def _assign_raw(self, candidates: Sequence[IdentityCandidate], frame_id: int,
                    t_capture: float) -> IdentityFrameResult:
        """Task 03.1 rule: label only; same-label collision keeps the higher score."""
        chosen: dict[HandId, IdentityCandidate] = {}
        for c in candidates:
            if c.raw_hand_id is None:
                continue
            cur = chosen.get(c.raw_hand_id)
            if cur is None or c.raw_score > cur.raw_score:
                chosen[c.raw_hand_id] = c
        assignments = {h: HandAssignment(h, c, c.raw_score, c.raw_score, c.raw_score, None, None, None)
                       for h, c in chosen.items()}
        for h, a in assignments.items():
            self._memory[h] = _Memory(a.candidate.wrist, t_capture)
        self.counters.assigned += len(assignments)
        n_unassigned = len(candidates) - len(assignments)
        self.counters.unassigned += n_unassigned
        return IdentityFrameResult(assignments=assignments, ambiguous=False, margin=None, events=(),
                                   n_unassigned=n_unassigned)


__all__ = [
    "WRIST",
    "HandAssignment",
    "IdentityAssigner",
    "IdentityCandidate",
    "IdentityCounters",
    "IdentityEvent",
    "IdentityEventKind",
    "IdentityFrameResult",
    "IdentityMode",
    "IdentitySettings",
]
