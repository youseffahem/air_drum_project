"""TEST-DATA-1: the structured recording protocol (Task 06.2) — segment vocabulary, deterministic
per-participant randomisation, PAD invariants, and segment-marker integrity (no overlaps, monotone)."""

from __future__ import annotations

import pytest

from spacedrums.contracts import HandId
from spacedrums.data.protocol import (
    CORE_TYPES,
    DURATION_CANDIDATES_S,
    NEGATIVE_TYPES,
    PROTOCOL_VERSION,
    SegmentCondition,
    SegmentSpec,
    SegmentType,
    build_protocol,
    check_segment_markers,
    participant_seed,
)

ZONES = ["hihat", "snare", "tom1", "crash_ride"]


def test_segment_vocabulary_covers_the_phase_document():
    # the fifteen segment kinds of Task 06.2 (1-11 core, 12-13 variation, 14 pad, 15 free play)
    assert len(SegmentType) == 16  # 15 numbered kinds; 3a/3b split alternating into two ids
    assert len(CORE_TYPES) == 12 and SegmentType.PAD_MIC not in CORE_TYPES
    assert SegmentType.FREE_PLAY not in CORE_TYPES
    assert NEGATIVE_TYPES <= CORE_TYPES
    assert set(DURATION_CANDIDATES_S) == set(SegmentType)
    assert PROTOCOL_VERSION.endswith("-draft")  # v1.0 is frozen only after the pilot


def test_build_protocol_covers_every_core_type_and_both_hands():
    p = build_protocol(ZONES, participant_id="P01", session_index=1)
    types = {s.type for s in p.segments}
    assert CORE_TYPES <= types
    singles = [s for s in p.segments if s.type is SegmentType.SINGLE_HITS]
    assert len(singles) == 2 * len(ZONES)
    assert {s.hands for s in singles} == {(HandId.RIGHT,), (HandId.LEFT,)}
    assert [s.zone_ids[0] for s in singles[: len(ZONES)]] == list(p.zone_order)
    assert set(p.zone_order) == set(ZONES)
    assert all(not s.expects_strikes for s in p.segments if s.type in NEGATIVE_TYPES)
    assert len({s.segment_id for s in p.segments}) == len(p.segments)
    assert p.total_duration_s == pytest.approx(sum(s.duration_s for s in p.segments))


def test_zone_order_is_deterministic_per_participant_and_differs_between_them():
    a = build_protocol(ZONES, participant_id="P01", session_index=1)
    b = build_protocol(ZONES, participant_id="P01", session_index=1)
    assert a.zone_order == b.zone_order and a.seed == b.seed == participant_seed("P01", 1)
    orders = {
        build_protocol(ZONES, participant_id=f"P{i:02d}", session_index=1).zone_order for i in range(1, 13)
    }
    assert len(orders) > 1
    assert build_protocol(ZONES, participant_id="P01", session_index=2).seed != a.seed
    assert build_protocol(ZONES, participant_id="P01", seed=7).seed_source == "explicit"


def test_pad_and_optional_segments():
    p = build_protocol(
        ZONES, participant_id="P01", include_pad_mic=True, pad_zone_id="tom1", include_free_play=True
    )
    pad = [s for s in p.segments if s.type is SegmentType.PAD_MIC]
    assert len(pad) == 1 and pad[0].condition is SegmentCondition.PAD and pad[0].pad_zone_id == "tom1"
    assert pad[0].optional and not pad[0].core
    assert any(s.type is SegmentType.FREE_PLAY for s in p.segments)
    with pytest.raises(ValueError):
        build_protocol(ZONES, participant_id="P01", include_pad_mic=True, pad_zone_id="kick")
    with pytest.raises(ValueError):
        SegmentSpec("x", SegmentType.SINGLE_HITS, "c", 1.0, condition="PAD")  # PAD without pad_zone_id
    with pytest.raises(ValueError):
        SegmentSpec("x", SegmentType.PAD_MIC, "c", 1.0)  # PAD_MIC must be PAD
    with pytest.raises(ValueError):
        SegmentSpec("x", SegmentType.SINGLE_HITS, "c", 0.0)


def test_duration_scale_and_variation_toggles():
    full = build_protocol(ZONES, participant_id="P02")
    short = build_protocol(ZONES, participant_id="P02", duration_scale=0.1)
    assert short.total_duration_s == pytest.approx(full.total_duration_s * 0.1)
    assert short.options["duration_scale"] == 0.1
    no_var = build_protocol(
        ZONES, participant_id="P02", include_distance_variation=False, include_lighting_variation=False
    )
    assert {s.type for s in no_var.segments}.isdisjoint(
        {SegmentType.DISTANCE_VARIATION, SegmentType.LIGHTING_VARIATION}
    )


def test_segment_marker_integrity_rules():
    ok = [
        {"segment_id": "a", "t_start": 1.0, "t_end": 2.0, "take": 1},
        {"segment_id": "b", "t_start": 2.0, "t_end": 3.5, "take": 1},
        {"segment_id": "b", "t_start": 3.5, "t_end": 4.0, "take": 2},
    ]
    assert check_segment_markers(ok) == []
    assert check_segment_markers([{"segment_id": "a", "t_start": 2.0, "t_end": 1.0, "take": 1}])
    assert check_segment_markers([{"segment_id": "a", "t_start": 1.0, "t_end": None}])
    overlap = [
        {"segment_id": "a", "t_start": 1.0, "t_end": 2.5, "take": 1},
        {"segment_id": "b", "t_start": 2.0, "t_end": 3.0, "take": 1},
    ]
    assert any("overlaps" in p for p in check_segment_markers(overlap))
    backwards = [
        {"segment_id": "a", "t_start": 2.0, "t_end": 3.0, "take": 1},
        {"segment_id": "b", "t_start": 1.0, "t_end": 1.5, "take": 1},
    ]
    assert check_segment_markers(backwards)
    bad_take = [
        {"segment_id": "a", "t_start": 1.0, "t_end": 2.0, "take": 2},
        {"segment_id": "a", "t_start": 2.0, "t_end": 3.0, "take": 1},
    ]
    assert any("take" in p for p in check_segment_markers(bad_take))
    assert check_segment_markers([{"segment_id": "a", "t_start": float("nan"), "t_end": 1.0}])


def test_protocol_to_dict_is_serialisable_and_complete():
    p = build_protocol(ZONES, participant_id="P03")
    d = p.to_dict()
    assert d["version"] == PROTOCOL_VERSION and d["n_segments"] == len(p.segments)
    assert all(
        set(s) >= {"segment_id", "type", "cue", "duration_s", "zone_ids", "hands", "condition"}
        for s in d["segments"]
    )
    assert p.by_id(d["segments"][0]["segment_id"]).segment_id == d["segments"][0]["segment_id"]
    with pytest.raises(KeyError):
        p.by_id("nope")
