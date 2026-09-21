"""Structured recording protocol (Phase 06, Task 06.2): segment vocabulary, cue definitions, timing
candidates and the per-participant randomisation of the zone order.

The protocol is **machinery and documentation only** in this phase: no session has been run with a
person, so every duration, count and tempo below is a *candidate* (phase document: "final
durations/counts tunable and recorded in the protocol version"). ``PROTOCOL_VERSION`` stays a draft
until the pilot of Task 06.10 has been performed and the owner freezes v1.0; a session's metadata
records the exact version it was recorded with.

Vocabulary consumed by Phase 07 (labelling rules key on ``SegmentType``):

* ``SegmentType`` — the fifteen segment kinds of the phase document (1–15), plus the pad+mic and
  free-play optional ones, as stable upper-case identifiers.
* ``SegmentSpec`` — one cued block: which zones and hands are cued, the text shown on screen, the
  candidate duration, the metronome tempo (if any), the ``AIR | PAD`` condition
  (docs/architecture/contracts.md section 6, ``has_phys_gt`` invariant) and whether the block is
  *core* (counts towards the session-level exclusion rule of Task 06.8).
* ``build_protocol`` — the ordered segment list for a session; the zone order of the single-hit
  block is a deterministic permutation seeded from the participant pseudonym + session index, so it
  is reproducible from the metadata alone and differs between participants (Q47–48 order confounds).
* ``check_segment_markers`` — integrity of recorded segment markers (monotone, non-overlapping,
  finite): the unit test of the phase document.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from spacedrums.contracts import HandId

PROTOCOL_ID = "spacedrums-recording-protocol"
PROTOCOL_VERSION = "0.1-draft"
"""Draft: v1.0 is frozen only after the Task 06.10 pilot (PENDING). Recorded per session."""


class SegmentType(StrEnum):
    """Segment kinds of phases/phase-06-data-collection.md, Task 06.2 (numbers in the docstrings)."""

    WARMUP = "WARMUP"  # 1 free movement without striking (no-strike motion)
    SINGLE_HITS = "SINGLE_HITS"  # 2 single hits per zone, one hand, cued zone order randomised
    ALTERNATING_ONE_ZONE = "ALTERNATING_ONE_ZONE"  # 3a alternating L/R on one zone
    ALTERNATING_TWO_ZONES = "ALTERNATING_TWO_ZONES"  # 3b alternating L/R on two zones
    TEMPO = "TEMPO"  # 4 repeated hits on one zone at a cued tempo (slow / medium / fast)
    RAPID = "RAPID"  # 5 rapid consecutive hits, as fast as comfortable, per hand
    NEAR_SIMULTANEOUS = "NEAR_SIMULTANEOUS"  # 6 near-simultaneous two-hand hits on two zones
    MOVE_BETWEEN_ZONES = "MOVE_BETWEEN_ZONES"  # 7 movement between zones without striking
    FAKE_SWING = "FAKE_SWING"  # 8 swing toward a zone and pull up before entering
    STOP_BEFORE_IMPACT = "STOP_BEFORE_IMPACT"  # 9 approach a zone and stop just above the surface
    OCCLUSION = "OCCLUSION"  # 10 deliberate occlusion (cross hands / stick in front of the other hand)
    TRACKING_INTERRUPTION = "TRACKING_INTERRUPTION"  # 11 hand out of the ROI and back; camera covered
    DISTANCE_VARIATION = "DISTANCE_VARIATION"  # 12 short hit block at a second marked distance
    LIGHTING_VARIATION = "LIGHTING_VARIATION"  # 13 short hit block under a second lighting condition
    PAD_MIC = "PAD_MIC"  # 14 optional practice pad + microphone (ADR-0002); condition PAD
    FREE_PLAY = "FREE_PLAY"  # 15 optional free play (Open Question; not in the draft protocol)


class SegmentCondition(StrEnum):
    AIR = "AIR"
    PAD = "PAD"


class Tempo(StrEnum):
    SLOW = "SLOW"
    MEDIUM = "MEDIUM"
    FAST = "FAST"


# Candidate tempi (beats per minute) for the TEMPO segments; set via the metronome cue and recorded in
# the metadata. Values are candidates, never measurements (phase document: "tempo values are
# candidates, set via metronome, recorded").
TEMPO_BPM_CANDIDATES: dict[Tempo, int] = {Tempo.SLOW: 60, Tempo.MEDIUM: 100, Tempo.FAST: 140}

# Candidate durations in seconds per segment type (phase document: tunable; pilot decides).
DURATION_CANDIDATES_S: dict[SegmentType, float] = {
    SegmentType.WARMUP: 20.0,
    SegmentType.SINGLE_HITS: 12.0,
    SegmentType.ALTERNATING_ONE_ZONE: 15.0,
    SegmentType.ALTERNATING_TWO_ZONES: 15.0,
    SegmentType.TEMPO: 15.0,
    SegmentType.RAPID: 10.0,
    SegmentType.NEAR_SIMULTANEOUS: 15.0,
    SegmentType.MOVE_BETWEEN_ZONES: 15.0,
    SegmentType.FAKE_SWING: 15.0,
    SegmentType.STOP_BEFORE_IMPACT: 15.0,
    SegmentType.OCCLUSION: 15.0,
    SegmentType.TRACKING_INTERRUPTION: 15.0,
    SegmentType.DISTANCE_VARIATION: 20.0,
    SegmentType.LIGHTING_VARIATION: 20.0,
    SegmentType.PAD_MIC: 30.0,
    SegmentType.FREE_PLAY: 60.0,
}

CORE_TYPES: frozenset[SegmentType] = frozenset(
    {
        SegmentType.WARMUP,
        SegmentType.SINGLE_HITS,
        SegmentType.ALTERNATING_ONE_ZONE,
        SegmentType.ALTERNATING_TWO_ZONES,
        SegmentType.TEMPO,
        SegmentType.RAPID,
        SegmentType.NEAR_SIMULTANEOUS,
        SegmentType.MOVE_BETWEEN_ZONES,
        SegmentType.FAKE_SWING,
        SegmentType.STOP_BEFORE_IMPACT,
        SegmentType.OCCLUSION,
        SegmentType.TRACKING_INTERRUPTION,
    }
)
"""Core segments 1–11 of the phase document (segments 12–15 are variation / optional blocks)."""

NEGATIVE_TYPES: frozenset[SegmentType] = frozenset(
    {
        SegmentType.WARMUP,
        SegmentType.MOVE_BETWEEN_ZONES,
        SegmentType.FAKE_SWING,
        SegmentType.STOP_BEFORE_IMPACT,
    }
)
"""Segments whose cue asks for NO strike (Q48 negatives). The cue is an instruction, not a label:
Phase 07 labels come from observation of the recording, never from the segment type."""

ZONE_DISPLAY_NAMES = {
    "snare": "SNARE",
    "hihat": "HI-HAT",
    "tom1": "TOM 1",
    "tom2": "TOM 2",
    "floor_tom": "FLOOR TOM",
    "crash_ride": "CRASH/RIDE",
    "ride": "RIDE",
    "crash": "CRASH",
}


def zone_name(zone_id: str) -> str:
    return ZONE_DISPLAY_NAMES.get(zone_id, zone_id.upper())


def hand_name(hand: HandId) -> str:
    return "LEFT" if hand is HandId.LEFT else "RIGHT"


@dataclass(frozen=True)
class SegmentSpec:
    """One cued block of the protocol."""

    segment_id: str
    type: SegmentType
    cue: str  # instruction shown on screen / read by the operator
    duration_s: float  # candidate duration (the recorder ends the block on time or on a key)
    zone_ids: tuple[str, ...] = ()  # cued zones (highlighted); empty = none
    hands: tuple[HandId, ...] = (HandId.LEFT, HandId.RIGHT)  # hands the block concerns (validity check)
    tempo: Tempo | None = None
    tempo_bpm: int | None = None
    condition: SegmentCondition = SegmentCondition.AIR
    pad_zone_id: str | None = None
    core: bool = True
    optional: bool = False  # optional blocks are skipped unless enabled for the session
    expects_strikes: bool = True  # False for the Q48 negative-only cues
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", SegmentType(self.type))
        object.__setattr__(self, "condition", SegmentCondition(self.condition))
        object.__setattr__(self, "zone_ids", tuple(str(z) for z in self.zone_ids))
        object.__setattr__(self, "hands", tuple(HandId(h) for h in self.hands))
        if self.tempo is not None:
            object.__setattr__(self, "tempo", Tempo(self.tempo))
        if not self.segment_id or any(c.isspace() for c in self.segment_id):
            raise ValueError("segment_id must be a non-empty token without whitespace")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        if not self.hands:
            raise ValueError("a segment concerns at least one hand")
        if (self.condition is SegmentCondition.PAD) != (self.pad_zone_id is not None):
            raise ValueError("pad_zone_id is set iff condition is PAD (contracts.md section 6)")
        if self.type is SegmentType.PAD_MIC and self.condition is not SegmentCondition.PAD:
            raise ValueError("PAD_MIC segments carry condition PAD")

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "type": str(self.type),
            "cue": self.cue,
            "duration_s": float(self.duration_s),
            "zone_ids": list(self.zone_ids),
            "hands": [str(h) for h in self.hands],
            "tempo": None if self.tempo is None else str(self.tempo),
            "tempo_bpm": self.tempo_bpm,
            "condition": str(self.condition),
            "pad_zone_id": self.pad_zone_id,
            "core": self.core,
            "optional": self.optional,
            "expects_strikes": self.expects_strikes,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Protocol:
    """The ordered segment list of one session plus the randomisation provenance."""

    protocol_id: str
    version: str
    segments: tuple[SegmentSpec, ...]
    zone_order: tuple[str, ...]
    seed: int
    seed_source: str
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ids = [s.segment_id for s in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("segment ids must be unique within a protocol")

    @property
    def total_duration_s(self) -> float:
        """Sum of candidate durations (an *arithmetic* candidate, never a measured session length)."""
        return float(sum(s.duration_s for s in self.segments))

    @property
    def core_segment_ids(self) -> tuple[str, ...]:
        return tuple(s.segment_id for s in self.segments if s.core)

    def by_id(self, segment_id: str) -> SegmentSpec:
        for s in self.segments:
            if s.segment_id == segment_id:
                return s
        raise KeyError(segment_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_id": self.protocol_id,
            "version": self.version,
            "seed": self.seed,
            "seed_source": self.seed_source,
            "zone_order": list(self.zone_order),
            "options": dict(self.options),
            "n_segments": len(self.segments),
            "total_duration_candidate_s": self.total_duration_s,
            "segments": [s.to_dict() for s in self.segments],
        }


# ----------------------------------------------------------------------------- randomisation


def participant_seed(participant_id: str, session_index: int) -> int:
    """Deterministic seed from the pseudonym and session index (reproducible from the metadata)."""
    h = hashlib.sha256(f"{participant_id}|{int(session_index)}|{PROTOCOL_ID}".encode()).digest()
    return int.from_bytes(h[:4], "big")


def _permute(items: Sequence[str], seed: int) -> tuple[str, ...]:
    """Fisher–Yates with a small deterministic LCG (no numpy: identical across platforms/versions)."""
    out = list(items)
    state = seed & 0xFFFFFFFF
    for i in range(len(out) - 1, 0, -1):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        j = state % (i + 1)
        out[i], out[j] = out[j], out[i]
    return tuple(out)


# ----------------------------------------------------------------------------- protocol builder


def build_protocol(
    zone_ids: Iterable[str],
    *,
    participant_id: str,
    session_index: int = 1,
    seed: int | None = None,
    include_distance_variation: bool = True,
    include_lighting_variation: bool = True,
    include_pad_mic: bool = False,
    pad_zone_id: str | None = None,
    include_free_play: bool = False,
    duration_scale: float = 1.0,
    primary_zone: str | None = None,
    secondary_zone: str | None = None,
) -> Protocol:
    """Ordered segments of the draft protocol for one session.

    ``duration_scale`` shortens every candidate duration uniformly (used by the SYNTHETIC self-test
    and for a quick dry run; the scale is recorded in the protocol options).
    """
    zones = tuple(str(z) for z in zone_ids)
    if len(zones) < 2:
        raise ValueError("the protocol needs at least two zones")
    if seed is None:
        seed, seed_source = participant_seed(participant_id, session_index), "participant_id+session_index"
    else:
        seed_source = "explicit"
    order = _permute(zones, seed)
    z1 = primary_zone or ("snare" if "snare" in zones else zones[0])
    z2 = secondary_zone or (
        "hihat" if "hihat" in zones and "hihat" != z1 else next(z for z in zones if z != z1)
    )
    if z1 not in zones or z2 not in zones or z1 == z2:
        raise ValueError("primary_zone / secondary_zone must be two distinct configured zones")
    L, R = HandId.LEFT, HandId.RIGHT

    def dur(t: SegmentType) -> float:
        return DURATION_CANDIDATES_S[t] * duration_scale

    segs: list[SegmentSpec] = [
        SegmentSpec(
            "s01_warmup",
            SegmentType.WARMUP,
            "WARM-UP: move the sticks freely, do NOT strike any zone",
            dur(SegmentType.WARMUP),
            expects_strikes=False,
        )
    ]
    k = 2
    for hand in (R, L):
        for z in order:
            segs.append(
                SegmentSpec(
                    f"s{k:02d}_single_{z}_{hand_name(hand)[0]}",
                    SegmentType.SINGLE_HITS,
                    f"SINGLE hits on {zone_name(z)}, {hand_name(hand)} hand, about one per second",
                    dur(SegmentType.SINGLE_HITS),
                    zone_ids=(z,),
                    hands=(hand,),
                )
            )
            k += 1
    segs += [
        SegmentSpec(
            f"s{k:02d}_alt_one_zone",
            SegmentType.ALTERNATING_ONE_ZONE,
            f"ALTERNATING left / right hits on {zone_name(z1)}",
            dur(SegmentType.ALTERNATING_ONE_ZONE),
            zone_ids=(z1,),
        ),
        SegmentSpec(
            f"s{k + 1:02d}_alt_two_zones",
            SegmentType.ALTERNATING_TWO_ZONES,
            f"ALTERNATING: RIGHT on {zone_name(z1)}, LEFT on {zone_name(z2)}",
            dur(SegmentType.ALTERNATING_TWO_ZONES),
            zone_ids=(z1, z2),
        ),
    ]
    k += 2
    for tempo in (Tempo.SLOW, Tempo.MEDIUM, Tempo.FAST):
        bpm = TEMPO_BPM_CANDIDATES[tempo]
        segs.append(
            SegmentSpec(
                f"s{k:02d}_tempo_{str(tempo).lower()}",
                SegmentType.TEMPO,
                f"REPEATED hits on {zone_name(z1)}, RIGHT hand, follow the metronome ({tempo}, {bpm} bpm)",
                dur(SegmentType.TEMPO),
                zone_ids=(z1,),
                hands=(R,),
                tempo=tempo,
                tempo_bpm=bpm,
            )
        )
        k += 1
    for hand in (R, L):
        segs.append(
            SegmentSpec(
                f"s{k:02d}_rapid_{hand_name(hand)[0]}",
                SegmentType.RAPID,
                f"RAPID hits on {zone_name(z1)}, {hand_name(hand)} hand, as fast as comfortable",
                dur(SegmentType.RAPID),
                zone_ids=(z1,),
                hands=(hand,),
            )
        )
        k += 1
    segs += [
        SegmentSpec(
            f"s{k:02d}_near_simultaneous",
            SegmentType.NEAR_SIMULTANEOUS,
            f"BOTH hands together: RIGHT on {zone_name(z1)} + LEFT on {zone_name(z2)} at the same time",
            dur(SegmentType.NEAR_SIMULTANEOUS),
            zone_ids=(z1, z2),
        ),
        SegmentSpec(
            f"s{k + 1:02d}_move_between",
            SegmentType.MOVE_BETWEEN_ZONES,
            "MOVE the sticks between the highlighted zones WITHOUT striking (follow the path)",
            dur(SegmentType.MOVE_BETWEEN_ZONES),
            zone_ids=tuple(order),
            expects_strikes=False,
        ),
        SegmentSpec(
            f"s{k + 2:02d}_fake_swing",
            SegmentType.FAKE_SWING,
            f"FAKE swings towards {zone_name(z1)}: swing and PULL UP before entering the zone",
            dur(SegmentType.FAKE_SWING),
            zone_ids=(z1,),
            expects_strikes=False,
        ),
        SegmentSpec(
            f"s{k + 3:02d}_stop_before_impact",
            SegmentType.STOP_BEFORE_IMPACT,
            f"Approach {zone_name(z1)} and STOP just above the surface (no strike)",
            dur(SegmentType.STOP_BEFORE_IMPACT),
            zone_ids=(z1,),
            expects_strikes=False,
        ),
        SegmentSpec(
            f"s{k + 4:02d}_occlusion",
            SegmentType.OCCLUSION,
            f"Play {zone_name(z1)} while CROSSING hands / holding one stick in front of the other hand",
            dur(SegmentType.OCCLUSION),
            zone_ids=(z1,),
        ),
        SegmentSpec(
            f"s{k + 5:02d}_tracking_interruption",
            SegmentType.TRACKING_INTERRUPTION,
            "Play, then briefly move one hand OUT of the box and back; operator covers the camera briefly",
            dur(SegmentType.TRACKING_INTERRUPTION),
            zone_ids=(z1,),
        ),
    ]
    k += 6
    if include_distance_variation:
        segs.append(
            SegmentSpec(
                f"s{k:02d}_distance_variation",
                SegmentType.DISTANCE_VARIATION,
                f"Step to the SECOND floor mark, then single hits on {zone_name(z1)} and {zone_name(z2)}",
                dur(SegmentType.DISTANCE_VARIATION),
                zone_ids=(z1, z2),
                core=False,
            )
        )
        k += 1
    if include_lighting_variation:
        segs.append(
            SegmentSpec(
                f"s{k:02d}_lighting_variation",
                SegmentType.LIGHTING_VARIATION,
                f"Operator changes the lighting (checklist id), then single hits on {zone_name(z1)}",
                dur(SegmentType.LIGHTING_VARIATION),
                zone_ids=(z1,),
                core=False,
            )
        )
        k += 1
    if include_pad_mic:
        pz = pad_zone_id or z1
        if pz not in zones:
            raise ValueError(f"pad_zone_id {pz!r} is not a configured zone")
        segs.append(
            SegmentSpec(
                f"s{k:02d}_pad_mic",
                SegmentType.PAD_MIC,
                f"PRACTICE PAD at {zone_name(pz)}: operator claps for sync, then single hits on the pad, "
                "operator claps again",
                dur(SegmentType.PAD_MIC),
                zone_ids=(pz,),
                condition=SegmentCondition.PAD,
                pad_zone_id=pz,
                core=False,
                optional=True,
            )
        )
        k += 1
    if include_free_play:
        segs.append(
            SegmentSpec(
                f"s{k:02d}_free_play",
                SegmentType.FREE_PLAY,
                "FREE play on any zones",
                dur(SegmentType.FREE_PLAY),
                zone_ids=tuple(order),
                core=False,
                optional=True,
                notes="Open Question (Q47): not part of the draft protocol; enabled explicitly",
            )
        )
    return Protocol(
        protocol_id=PROTOCOL_ID,
        version=PROTOCOL_VERSION,
        segments=tuple(segs),
        zone_order=order,
        seed=seed,
        seed_source=seed_source,
        options={
            "include_distance_variation": include_distance_variation,
            "include_lighting_variation": include_lighting_variation,
            "include_pad_mic": include_pad_mic,
            "pad_zone_id": pad_zone_id if include_pad_mic else None,
            "include_free_play": include_free_play,
            "duration_scale": duration_scale,
            "primary_zone": z1,
            "secondary_zone": z2,
        },
    )


# ----------------------------------------------------------------------------- marker integrity


def check_segment_markers(markers: Sequence[dict[str, Any]]) -> list[str]:
    """Integrity of recorded segment markers: each has ``segment_id``, ``t_start`` < ``t_end`` (finite),
    consecutive markers do not overlap and start times are strictly increasing; ``take`` numbers of a
    repeated ``segment_id`` increase. Returns a list of problems (empty == OK)."""
    problems: list[str] = []
    prev_end: float | None = None
    prev_start: float | None = None
    takes: dict[str, int] = {}
    for i, m in enumerate(markers):
        sid = m.get("segment_id")
        if not sid:
            problems.append(f"marker {i}: missing segment_id")
            continue
        t0, t1 = m.get("t_start"), m.get("t_end")
        if t0 is None or t1 is None:
            problems.append(f"{sid}: open marker (t_start={t0!r}, t_end={t1!r})")
            continue
        t0, t1 = float(t0), float(t1)
        if not (t0 == t0 and t1 == t1 and abs(t0) != float("inf") and abs(t1) != float("inf")):
            problems.append(f"{sid}: non-finite marker")
            continue
        if not t0 < t1:
            problems.append(f"{sid}: t_start {t0} >= t_end {t1}")
        if prev_start is not None and not t0 > prev_start:
            problems.append(f"{sid}: t_start {t0} not after previous start {prev_start}")
        if prev_end is not None and t0 < prev_end:
            problems.append(f"{sid}: overlaps previous marker (starts {t0} before {prev_end})")
        take = int(m.get("take", 1))
        if take < 1:
            problems.append(f"{sid}: take must be >= 1")
        if sid in takes and take <= takes[sid]:
            problems.append(f"{sid}: take {take} not greater than earlier take {takes[sid]}")
        takes[sid] = max(take, takes.get(sid, 0))
        prev_start, prev_end = t0, t1
    return problems


__all__ = [
    "CORE_TYPES",
    "DURATION_CANDIDATES_S",
    "NEGATIVE_TYPES",
    "PROTOCOL_ID",
    "PROTOCOL_VERSION",
    "TEMPO_BPM_CANDIDATES",
    "Protocol",
    "SegmentCondition",
    "SegmentSpec",
    "SegmentType",
    "Tempo",
    "build_protocol",
    "check_segment_markers",
    "hand_name",
    "participant_seed",
    "zone_name",
]
