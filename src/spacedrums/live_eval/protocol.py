"""Live-session protocol of Experiment 2 (Task 18.4; pre-registration §9).

A live session is a Phase 06 guided recording whose segments are grouped into **arm blocks**:

    familiarisation (arm A, excluded from analysis)
    -> AIR blocks, one per arm in the counterbalanced order
       (single hits per zone, alternating hands, repeated hits at the medium cued tempo,
        fake swings, stop-before-impact)
    -> PAD blocks for the external method M1, one per arm in the same order (optional)

Every segment type is a Phase 06 ``SegmentType``, so the unchanged ``GuidedRecorder``, the metadata
schema, ``verify_session`` and the Phase 07 labelling rules apply. Durations are candidates; the
protocol version stays a draft until the developer pilot (Task 18.3) and the owner freeze it.

:class:`ArmSwitcher` is the only live-specific control. On the first frame of each new block it
makes that block's arm the sounding arm; the other arms keep running in shadow. It records every
switch. It gives the **participant view** status lines without arm names (blinding) and the
**operator** console lines with them. It does not import the application: the pipeline is
duck-typed (``active_arm`` and ``set_active_arm``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from spacedrums.contracts import HandId
from spacedrums.data.protocol import (
    DURATION_CANDIDATES_S,
    TEMPO_BPM_CANDIDATES,
    Protocol,
    SegmentCondition,
    SegmentSpec,
    SegmentType,
    Tempo,
    participant_seed,
    zone_name,
)
from spacedrums.live_eval.counterbalance import LIVE_ARMS, arm_order

LIVE_PROTOCOL_ID = "spacedrums-live-protocol"
LIVE_PROTOCOL_VERSION = "0.1-draft"
"""Draft until the developer pilot and the owner freeze v1.0; recorded per session."""

FAMILIARISATION_BLOCK = "b0"
AIR_BLOCK_TYPES = (
    SegmentType.SINGLE_HITS,
    SegmentType.ALTERNATING_ONE_ZONE,
    SegmentType.TEMPO,
    SegmentType.FAKE_SWING,
    SegmentType.STOP_BEFORE_IMPACT,
)
SINGLE_HIT_DURATION_S = 10.0  # candidate per zone (shorter than the Phase 06 12 s: all zones per arm)
FAMILIARISATION_S = 30.0  # candidate


@dataclass(frozen=True)
class ArmBlock:
    block_id: str
    arm: str  # live label A | B | C
    kind: str  # AIR | PAD | FAMILIARISATION
    segment_ids: tuple[str, ...]
    analysed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "arm": self.arm,
            "kind": self.kind,
            "segment_ids": list(self.segment_ids),
            "analysed": self.analysed,
        }


@dataclass(frozen=True)
class LiveProtocol:
    protocol: Protocol
    blocks: tuple[ArmBlock, ...]
    order: dict[str, Any]
    options: dict[str, Any] = field(default_factory=dict)

    def block_of(self, segment_id: str | None) -> ArmBlock | None:
        if segment_id is None:
            return None
        return next((b for b in self.blocks if segment_id in b.segment_ids), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_id": LIVE_PROTOCOL_ID,
            "version": LIVE_PROTOCOL_VERSION,
            "arm_order": list(self.order["order"]),
            "sequence_index": self.order["sequence_index"],
            "participant_index": self.order["participant_index"],
            "design": self.order["design"],
            "blocks": [b.to_dict() for b in self.blocks],
            "options": dict(self.options),
            "phase06_protocol": self.protocol.to_dict(),
        }


def build_live_protocol(
    zone_ids: Sequence[str],
    *,
    participant_index: int,
    participant_id: str,
    session_index: int = 1,
    arms: Sequence[str] = LIVE_ARMS,
    pad_zone_id: str | None = None,
    duration_scale: float = 1.0,
    primary_zone: str | None = None,
    secondary_zone: str | None = None,
) -> LiveProtocol:
    zones = tuple(str(z) for z in zone_ids)
    if len(zones) < 2:
        raise ValueError("the live protocol needs at least two zones")
    if duration_scale <= 0:
        raise ValueError("duration_scale must be positive")
    if pad_zone_id is not None and pad_zone_id not in zones:
        raise ValueError(f"pad zone {pad_zone_id!r} is not a configured zone")
    z1 = primary_zone or ("snare" if "snare" in zones else zones[0])
    z2 = secondary_zone or next(z for z in zones if z != z1)
    order = arm_order(participant_index, arms)
    medium = TEMPO_BPM_CANDIDATES[Tempo.MEDIUM]
    L, R = HandId.LEFT, HandId.RIGHT

    def dur(seconds: float) -> float:
        return seconds * duration_scale

    segments: list[SegmentSpec] = [
        SegmentSpec(
            f"{FAMILIARISATION_BLOCK}_familiarise",
            SegmentType.SINGLE_HITS,
            "FAMILIARISATION: play a few single hits on any zone",
            dur(FAMILIARISATION_S),
            zone_ids=zones,
            hands=(R, L),
            core=False,
            notes="familiarisation; excluded from analysis",
        )
    ]
    blocks = [ArmBlock(FAMILIARISATION_BLOCK, "A", "FAMILIARISATION", (segments[0].segment_id,), False)]
    for i, arm in enumerate(order["order"], start=1):
        bid = f"b{i}"
        segs = [
            SegmentSpec(
                f"{bid}_single_{z}",
                SegmentType.SINGLE_HITS,
                f"BLOCK {i}: SINGLE hits on {zone_name(z)}, either hand, about one per second",
                dur(SINGLE_HIT_DURATION_S),
                zone_ids=(z,),
                hands=(R, L),
            )
            for z in zones
        ]
        segs += [
            SegmentSpec(
                f"{bid}_alternating_{z1}",
                SegmentType.ALTERNATING_ONE_ZONE,
                f"BLOCK {i}: ALTERNATE right / left on {zone_name(z1)}",
                dur(DURATION_CANDIDATES_S[SegmentType.ALTERNATING_ONE_ZONE]),
                zone_ids=(z1,),
            ),
            SegmentSpec(
                f"{bid}_tempo_{z1}",
                SegmentType.TEMPO,
                f"BLOCK {i}: hit {zone_name(z1)} with the metronome ({medium} bpm)",
                dur(DURATION_CANDIDATES_S[SegmentType.TEMPO]),
                zone_ids=(z1,),
                hands=(R,),
                tempo=Tempo.MEDIUM,
                tempo_bpm=medium,
            ),
            SegmentSpec(
                f"{bid}_fake_{z1}",
                SegmentType.FAKE_SWING,
                f"BLOCK {i}: FAKE swings toward {zone_name(z1)}: pull up before the zone",
                dur(DURATION_CANDIDATES_S[SegmentType.FAKE_SWING]),
                zone_ids=(z1,),
                expects_strikes=False,
            ),
            SegmentSpec(
                f"{bid}_stop_{z1}",
                SegmentType.STOP_BEFORE_IMPACT,
                f"BLOCK {i}: approach {zone_name(z1)} and STOP just above it",
                dur(DURATION_CANDIDATES_S[SegmentType.STOP_BEFORE_IMPACT]),
                zone_ids=(z1,),
                expects_strikes=False,
            ),
        ]
        segments += segs
        blocks.append(ArmBlock(bid, arm, "AIR", tuple(s.segment_id for s in segs)))
    if pad_zone_id is not None:
        for i, arm in enumerate(order["order"], start=1):
            pid = f"p{i}"
            spec = SegmentSpec(
                f"{pid}_pad_{pad_zone_id}",
                SegmentType.PAD_MIC,
                f"PAD {i}: single hits on the practice pad ({zone_name(pad_zone_id)}), about one per second",
                dur(DURATION_CANDIDATES_S[SegmentType.PAD_MIC]),
                zone_ids=(pad_zone_id,),
                hands=(R, L),
                condition=SegmentCondition.PAD,
                pad_zone_id=pad_zone_id,
                core=False,
                optional=True,
            )
            segments.append(spec)
            blocks.append(ArmBlock(pid, arm, "PAD", (spec.segment_id,)))
    seed = participant_seed(participant_id, session_index)
    options = {
        "primary_zone": z1,
        "secondary_zone": z2,
        "duration_scale": duration_scale,
        "pad_zone_id": pad_zone_id,
        "live_protocol_id": LIVE_PROTOCOL_ID,
        "live_protocol_version": LIVE_PROTOCOL_VERSION,
        "arm_order": list(order["order"]),
        "sequence_index": order["sequence_index"],
    }
    protocol = Protocol(
        protocol_id=LIVE_PROTOCOL_ID,
        version=LIVE_PROTOCOL_VERSION,
        segments=tuple(segments),
        zone_order=zones,
        seed=seed,
        seed_source="participant_id+session_index (zone order fixed: config order)",
        options=options,
    )
    return LiveProtocol(protocol=protocol, blocks=tuple(blocks), order=order, options=options)


@dataclass
class ArmSwitcher:
    """Makes each block's arm the sounding arm on the block's first frame; records every switch."""

    live: LiveProtocol
    arm_of_label: Mapping[str, Any]  # live label -> pipeline arm value (for example Arm.C_GRU)
    log: Callable[[str], None] = print
    switches: list[dict[str, Any]] = field(default_factory=list)
    refused: list[dict[str, Any]] = field(default_factory=list)
    current_block: str | None = None

    def update(self, segment_id: str | None, pipeline: Any, *, t_now: float, frame_id: int) -> None:
        block = self.live.block_of(segment_id)
        if block is None or block.block_id == self.current_block:
            return
        self.current_block = block.block_id
        target = self.arm_of_label[block.arm]
        before = str(pipeline.active_arm)
        if pipeline.active_arm != target:
            try:
                pipeline.set_active_arm(target, t_now)
            except ValueError as exc:
                self.refused.append(
                    {"block_id": block.block_id, "arm": block.arm, "t_mono": t_now, "reason": str(exc)}
                )
                self.log(f"[live] block {block.block_id}: switch to {block.arm} REFUSED ({exc})")
                return
        self.switches.append(
            {
                "block_id": block.block_id,
                "arm_label": block.arm,
                "from_arm": before,
                "to_arm": str(pipeline.active_arm),
                "t_mono": float(t_now),
                "frame_id": int(frame_id),
            }
        )
        self.log(f"[live] operator: block {block.block_id} -> arm {block.arm} ({pipeline.active_arm})")

    def participant_lines(self, spec: SegmentSpec | None) -> list[str]:
        """Blinded participant text: the cue and the block counter, never an arm name."""
        if spec is None:
            return ["Session finished - thank you"]
        block = self.live.block_of(spec.segment_id)
        n_blocks = sum(1 for b in self.live.blocks if b.kind in ("AIR", "PAD"))
        index = [b.block_id for b in self.live.blocks if b.kind in ("AIR", "PAD")]
        where = (
            f"block {index.index(block.block_id) + 1} of {n_blocks}"
            if block is not None and block.block_id in index
            else "familiarisation"
        )
        return [spec.cue, where]


__all__ = [
    "AIR_BLOCK_TYPES",
    "LIVE_PROTOCOL_ID",
    "LIVE_PROTOCOL_VERSION",
    "ArmBlock",
    "ArmSwitcher",
    "LiveProtocol",
    "build_live_protocol",
]
