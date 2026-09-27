"""Phase 18 live design: counterbalancing, protocol, arm switching, LiveSessionMetadata (TEST-P18-LIVE)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from spacedrums.contracts import Arm
from spacedrums.contracts import schema as contract_schema
from spacedrums.data.protocol import SegmentType
from spacedrums.live_eval.counterbalance import arm_order, arm_sequences, balance_report, williams_sequences
from spacedrums.live_eval.metadata import LiveSessionMetadata, consistency_errors
from spacedrums.live_eval.protocol import AIR_BLOCK_TYPES, ArmSwitcher, build_live_protocol

ROOT = Path(__file__).resolve().parents[2]
ZONES = ("hihat", "snare", "tom1", "crash_ride")
EXAMPLE = ROOT / "schemas/examples/live-session-metadata.valid.example.json"


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6])
def test_williams_designs_balance_position_and_first_order_carryover(n):
    seqs = williams_sequences(n)
    assert len(seqs) == (n if n % 2 == 0 else 2 * n)
    report = balance_report([[str(x) for x in s] for s in seqs])
    assert report["position_balanced"] and report["carryover_balanced"]


def test_three_live_arms_use_all_six_orders_deterministically():
    seqs = arm_sequences()
    assert sorted(seqs) == sorted(
        {("A", "B", "C"), ("A", "C", "B"), ("B", "A", "C"), ("B", "C", "A"), ("C", "A", "B"), ("C", "B", "A")}
    )
    assert arm_order(1)["order"] == list(seqs[0]) and arm_order(7)["order"] == list(seqs[0])
    assert arm_order(4)["sequence_index"] == 3
    with pytest.raises(ValueError):
        arm_order(0)


def test_live_protocol_blocks_follow_the_order_with_phase06_segments_only():
    live = build_live_protocol(ZONES, participant_index=2, participant_id="PILOT01", pad_zone_id="snare")
    order = live.order["order"]
    air = [b for b in live.blocks if b.kind == "AIR"]
    pad = [b for b in live.blocks if b.kind == "PAD"]
    assert [b.arm for b in air] == order and [b.arm for b in pad] == order
    assert live.blocks[0].kind == "FAMILIARISATION" and live.blocks[0].analysed is False
    ids = [s.segment_id for s in live.protocol.segments]
    assert len(ids) == len(set(ids))
    for block in air:
        types = {live.protocol.by_id(s).type for s in block.segment_ids}
        assert types == set(AIR_BLOCK_TYPES)
    assert all(live.protocol.by_id(s).type is SegmentType.PAD_MIC for b in pad for s in b.segment_ids)
    assert live.protocol.options["primary_zone"] == "snare"
    with pytest.raises(ValueError):
        build_live_protocol(ZONES, participant_index=1, participant_id="P01", pad_zone_id="cowbell")


class _Pipeline:
    def __init__(self, refuse=()):
        self.active_arm, self.refuse, self.calls = Arm.A, set(refuse), []

    def set_active_arm(self, arm, t_now):
        if arm in self.refuse:
            raise ValueError("model disabled")
        self.calls.append((arm, t_now))
        self.active_arm = arm


def test_arm_switcher_switches_once_per_block_and_blinds_the_participant():
    live = build_live_protocol(ZONES, participant_index=3, participant_id="PILOT01")
    labels = {"A": Arm.A, "B": Arm.B, "C": Arm.C_GRU}
    switcher = ArmSwitcher(live, labels, log=lambda _m: None)
    pipe = _Pipeline()
    t = 0.0
    for spec in live.protocol.segments:
        for _ in range(3):
            switcher.update(spec.segment_id, pipe, t_now=t, frame_id=int(t * 30))
            t += 0.1
    assert [s["arm_label"] for s in switcher.switches] == ["A", *live.order["order"]]
    assert len(pipe.calls) == sum(
        1 for a, b in zip(["A", *live.order["order"]], live.order["order"], strict=False) if a != b
    )
    for spec in live.protocol.segments:
        text = " ".join(switcher.participant_lines(spec)).upper()
        assert "C-GRU" not in text and "ARM" not in text
    refusing = ArmSwitcher(live, labels, log=lambda _m: None)
    pipe = _Pipeline(refuse={Arm.C_GRU})
    for spec in live.protocol.segments:
        refusing.update(spec.segment_id, pipe, t_now=1.0, frame_id=1)
    assert refusing.refused and refusing.refused[0]["arm"] == "C"


def test_example_live_session_metadata_validates_and_the_conditionals_bite():
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert contract_schema.errors("live-session-metadata", example) == []
    bad = copy.deepcopy(example)
    bad["consent_record_id"] = "CF-LIVE-X"  # a SYNTHETIC session cannot carry a consent record
    assert contract_schema.errors("live-session-metadata", bad)
    bad = copy.deepcopy(example)
    bad["session_kind"], bad["consent_status"] = "PARTICIPANT", "PENDING"
    assert contract_schema.errors("live-session-metadata", bad)
    bad = copy.deepcopy(example)
    bad["arm_blocks"][1]["arm"] = "D"
    assert contract_schema.errors("live-session-metadata", bad)


def test_live_metadata_is_consistent_with_its_phase06_document(tmp_path):
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    base = {
        k: example[k]
        for k in ("session_id", "session_kind", "participant_id", "consent_status", "consent_record_id")
    }
    base["calibration_hash"] = example["calibration"]["calibration_hash"]
    base["segments"] = [{"segment_id": s} for b in example["arm_blocks"] for s in b["segment_ids"]]
    (tmp_path / "metadata.json").write_text(json.dumps(base), encoding="utf-8")
    live = LiveSessionMetadata(copy.deepcopy(example))
    live.data["base_metadata"]["sha256"] = None
    assert consistency_errors(live.data, tmp_path) == []
    path = live.write(tmp_path)
    assert LiveSessionMetadata.read(tmp_path).data["base_metadata"]["sha256"].startswith("sha256:")
    assert path.name == "live-session.json"
    (tmp_path / "metadata.json").write_text(json.dumps({**base, "participant_id": "DEV2"}), encoding="utf-8")
    assert any("participant_id" in e for e in consistency_errors(live.data, tmp_path))
    swapped = copy.deepcopy(live.data)
    swapped["live_protocol"]["arm_order"] = ["C", "B", "A"]
    assert any("do not follow" in e for e in consistency_errors(swapped, tmp_path))
