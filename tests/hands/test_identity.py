"""TEST-HANDS-4: LEFT/RIGHT identity assignment on synthetic sequences (Phase 03, Task 03.2).

Synthetic two-hand trajectories (labelled synthetic; never evidence about the estimator) exercise
the assigner's contract: identities follow continuity through a crossing when labels are right;
continuity overrides label noise; labels decide after a gap longer than ``max_gap_s``; a genuinely
ambiguous frame is flagged and its scores capped (never a guess); events are emitted and counted;
the assigner is causal (only its own memory of past frames).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from spacedrums.contracts import HandId
from spacedrums.hands import (
    IdentityAssigner,
    IdentityCandidate,
    IdentityEventKind,
    IdentityMode,
    IdentitySettings,
)

DT = 1 / 30
L, R = HandId.LEFT, HandId.RIGHT


def cand(i: int, x: float, y: float, label: HandId | None, score: float = 0.9) -> IdentityCandidate:
    return IdentityCandidate(index=i, wrist=(x, y), raw_hand_id=label, raw_score=score)


def crossing_paths(n: int = 40) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """LEFT starts at x=0.7, RIGHT at x=0.3 (image sides as on HW-01); they cross at the midpoint."""
    out = []
    for k in range(n):
        u = k / (n - 1)
        xl = 0.7 - 0.4 * u
        xr = 0.3 + 0.4 * u
        out.append(((xl, 0.8), (xr, 0.8 + 0.05 * math.sin(4 * u))))
    return out


def run(assigner: IdentityAssigner, frames):
    """frames: list of (t, [candidates]) -> list of results."""
    return [assigner.assign(c, i, t) for i, (t, c) in enumerate(frames)]


def test_raw_mode_reproduces_task_03_1_rule():
    a = IdentityAssigner(IdentitySettings(mode=IdentityMode.RAW))
    r = a.assign([cand(0, 0.3, 0.8, R, 0.6), cand(1, 0.7, 0.8, R, 0.9)], 0, 0.0)
    assert set(r.assignments) == {R} and r.assignments[R].candidate.index == 1
    assert r.n_unassigned == 1 and not r.ambiguous and r.events == ()


def test_correct_labels_smooth_motion_no_events():
    a = IdentityAssigner(IdentitySettings())
    frames = [(k * DT, [cand(0, *pl, L), cand(1, *pr, R)]) for k, (pl, pr) in enumerate(crossing_paths())]
    results = run(a, frames)
    for r in results:
        assert set(r.assignments) == {L, R} and not r.ambiguous
        assert r.assignments[L].candidate.raw_hand_id is L and r.assignments[R].candidate.raw_hand_id is R
    assert a.counters.label_overrides == 0 and a.counters.identity_jumps == 0
    assert a.counters.ambiguous_frames == 0
    # identity confidence stays high all along, including the crossing frame
    assert min(r.assignments[L].handedness_score for r in results) > 0.8


def test_label_noise_is_overridden_by_continuity_and_logged():
    a = IdentityAssigner(IdentitySettings())
    frames = []
    for k in range(20):
        pl, pr = (0.7 - 0.002 * k, 0.8), (0.3 + 0.002 * k, 0.8)
        if k in (5, 6, 12):  # the estimator flips both labels for three frames
            frames.append((k * DT, [cand(0, *pl, R, 0.8), cand(1, *pr, L, 0.8)]))
        else:
            frames.append((k * DT, [cand(0, *pl, L), cand(1, *pr, R)]))
    results = run(a, frames)
    for r in results:  # identities never flip: LEFT stays the x~0.7 hand
        assert r.assignments[L].candidate.wrist[0] > 0.5 > r.assignments[R].candidate.wrist[0]
    assert a.counters.label_overrides == 6  # 3 frames x 2 hands
    kinds = [e.kind for r in results for e in r.events]
    assert kinds.count(IdentityEventKind.LABEL_OVERRIDE) == 6
    assert IdentityEventKind.IDENTITY_JUMP not in kinds
    assert a.counters.ambiguous_frames == 0
    # confidence dips on the overridden frames but the hand is still assigned
    assert results[5].assignments[L].handedness_score < results[4].assignments[L].handedness_score


def test_same_label_both_hands_resolved_by_continuity():
    a = IdentityAssigner(IdentitySettings())
    a.assign([cand(0, 0.7, 0.8, L), cand(1, 0.3, 0.8, R)], 0, 0.0)
    r = a.assign([cand(0, 0.7, 0.8, R, 0.7), cand(1, 0.3, 0.8, R, 0.7)], 1, DT)  # both say Right
    assert r.assignments[L].candidate.wrist[0] == 0.7 and r.assignments[R].candidate.wrist[0] == 0.3
    assert not r.ambiguous and a.counters.label_overrides == 1


def test_same_label_no_memory_is_ambiguous_not_guessed():
    a = IdentityAssigner(IdentitySettings(ambiguous_score_cap=0.5))
    r = a.assign([cand(0, 0.7, 0.8, R, 0.9), cand(1, 0.3, 0.8, R, 0.9)], 0, 0.0)
    assert r.ambiguous and r.margin == pytest.approx(0.0)
    assert set(r.assignments) == {L, R}  # both emitted (positions are real) ...
    for h in (L, R):  # ... but neither may be trusted as VALID
        assert r.assignments[h].handedness_score <= 0.5
    assert a.counters.ambiguous_frames == 1
    assert any(e.kind is IdentityEventKind.AMBIGUOUS for e in r.events)


def test_coincident_hands_with_weak_labels_are_ambiguous():
    a = IdentityAssigner(IdentitySettings(ambiguity_margin=0.15))
    a.assign([cand(0, 0.52, 0.8, L), cand(1, 0.48, 0.8, R)], 0, 0.0)
    # crossing frame: both detections at the same spot (continuity cannot separate them) and the
    # labels are barely confident -> margin 2 * (0.55 - 0.45) * w_label = 0.1 < 0.15
    r = a.assign([cand(0, 0.50, 0.8, R, 0.55), cand(1, 0.50, 0.8, L, 0.55)], 1, DT)
    assert r.ambiguous and r.margin == pytest.approx(0.1)
    assert all(x.handedness_score <= a.settings.ambiguous_score_cap for x in r.assignments.values())
    # with confident labels (0.6 -> margin 0.2) the labels legitimately decide: not ambiguous
    b = IdentityAssigner(IdentitySettings(ambiguity_margin=0.15))
    b.assign([cand(0, 0.52, 0.8, L), cand(1, 0.48, 0.8, R)], 0, 0.0)
    r2 = b.assign([cand(0, 0.50, 0.8, R, 0.6), cand(1, 0.50, 0.8, L, 0.6)], 1, DT)
    assert not r2.ambiguous and r2.margin == pytest.approx(0.2)


def test_continuity_beats_a_confident_label_flip_when_hands_are_apart():
    a = IdentityAssigner(IdentitySettings())
    a.assign([cand(0, 0.60, 0.8, L), cand(1, 0.40, 0.8, R)], 0, 0.0)
    r = a.assign([cand(0, 0.58, 0.8, R, 0.6), cand(1, 0.42, 0.8, L, 0.6)], 1, DT)
    assert r.assignments[L].candidate.index == 0 and r.assignments[R].candidate.index == 1
    # best (continuity) total 1.267; runner-up is a one-hand subset (0.633), not the label swap (0.6)
    assert not r.ambiguous and r.margin == pytest.approx(1.267 - 0.633, abs=1e-3)


def test_single_detection_keeps_identity_and_other_hand_absent():
    a = IdentityAssigner(IdentitySettings())
    a.assign([cand(0, 0.7, 0.8, L), cand(1, 0.3, 0.8, R)], 0, 0.0)
    r = a.assign([cand(0, 0.31, 0.79, R)], 1, DT)
    assert set(r.assignments) == {R} and not r.ambiguous
    # even with a wrong label the lone detection near RIGHT's memory stays RIGHT
    r2 = a.assign([cand(0, 0.32, 0.79, L, 0.7)], 2, 2 * DT)
    assert set(r2.assignments) == {R} and a.counters.label_overrides == 1


def test_labels_decide_after_a_gap_longer_than_max_gap():
    s = IdentitySettings(max_gap_s=0.25)
    a = IdentityAssigner(s)
    a.assign([cand(0, 0.7, 0.8, L), cand(1, 0.3, 0.8, R)], 0, 0.0)
    # hands vanish for 0.5 s, reappear swapped in space with confident labels: labels win, no events
    r = a.assign([cand(0, 0.3, 0.8, L, 0.95), cand(1, 0.7, 0.8, R, 0.95)], 1, 0.5)
    assert r.assignments[L].candidate.wrist[0] == 0.3 and r.assignments[R].candidate.wrist[0] == 0.7
    assert r.events == () and not r.ambiguous
    assert r.assignments[L].p_temporal is None  # memory expired: no continuity information


def test_identity_jump_is_detected_and_logged():
    a = IdentityAssigner(IdentitySettings(w_label=0.9))  # labels dominate: a jump can happen
    a.assign([cand(0, 0.7, 0.8, L), cand(1, 0.3, 0.8, R)], 0, 0.0)
    # next frame the estimator swaps the labels with high confidence; with w_label 0.9 labels win
    r = a.assign([cand(0, 0.7, 0.8, R, 0.99), cand(1, 0.3, 0.8, L, 0.99)], 1, DT)
    kinds = {e.kind for e in r.events}
    assert IdentityEventKind.IDENTITY_JUMP in kinds and IdentityEventKind.CONTINUITY_OVERRIDE in kinds
    assert a.counters.identity_jumps == 2 and a.counters.continuity_overrides == 2
    assert r.assignments[L].distance_own > a.settings.gate_distance >= r.assignments[L].distance_other


def test_unknown_label_can_only_fill_a_free_hand_with_low_confidence():
    a = IdentityAssigner(IdentitySettings())
    r = a.assign([cand(0, 0.7, 0.8, L, 0.95), cand(1, 0.3, 0.8, None, 0.9)], 0, 0.0)
    assert r.assignments[L].candidate.index == 0
    assert r.assignments[R].candidate.index == 1 and r.assignments[R].handedness_score == pytest.approx(0.5)


def test_extra_detections_are_left_unassigned_and_counted():
    a = IdentityAssigner(IdentitySettings())
    r = a.assign([cand(0, 0.7, 0.8, L), cand(1, 0.3, 0.8, R), cand(2, 0.5, 0.2, R, 0.55)], 0, 0.0)
    assert set(r.assignments) == {L, R} and r.n_unassigned == 1 and a.counters.unassigned == 1


def test_no_detections_yields_empty_result_and_keeps_memory():
    a = IdentityAssigner(IdentitySettings())
    a.assign([cand(0, 0.7, 0.8, L), cand(1, 0.3, 0.8, R)], 0, 0.0)
    r = a.assign([], 1, DT)
    assert r.assignments == {} and not r.ambiguous and r.n_unassigned == 0
    r2 = a.assign([cand(0, 0.3, 0.8, L, 0.6)], 2, 2 * DT)  # memory survived the empty frame
    assert set(r2.assignments) == {R}


def test_causality_output_depends_only_on_past_frames():
    """Feeding extra later frames never changes an earlier frame's result (TEST-CAUSAL-1 spirit)."""
    frames = [(k * DT, [cand(0, *pl, L if k % 7 else R, 0.8), cand(1, *pr, R)])
              for k, (pl, pr) in enumerate(crossing_paths(30))]
    a1 = IdentityAssigner(IdentitySettings())
    res_full = run(a1, frames)
    a2 = IdentityAssigner(IdentitySettings())
    res_prefix = run(a2, frames[:15])
    for r_full, r_pre in zip(res_full[:15], res_prefix, strict=True):
        assert {h: x.candidate.index for h, x in r_full.assignments.items()} == \
               {h: x.candidate.index for h, x in r_pre.assignments.items()}
        assert r_full.ambiguous == r_pre.ambiguous


def test_settings_validation():
    with pytest.raises(ValueError):
        IdentitySettings(gate_distance=0)
    with pytest.raises(ValueError):
        IdentitySettings(max_gap_s=-1)
    with pytest.raises(ValueError):
        IdentitySettings(w_label=1.5)
    with pytest.raises(ValueError):
        IdentitySettings(mode="GUESS")
    assert IdentitySettings(mode="RAW").id_fragment() == "id-raw"


def test_reset_clears_memory():
    a = IdentityAssigner(IdentitySettings())
    a.assign([cand(0, 0.7, 0.8, L), cand(1, 0.3, 0.8, R)], 0, 0.0)
    a.reset()
    r = a.assign([cand(0, 0.3, 0.8, L, 0.95)], 1, DT)  # no memory -> label decides
    assert set(r.assignments) == {L} and r.assignments[L].p_temporal is None


def test_event_serialises():
    a = IdentityAssigner(IdentitySettings())
    r = a.assign([cand(0, 0.7, 0.8, R, 0.9), cand(1, 0.3, 0.8, R, 0.9)], 3, 0.1)
    d = next(e for e in r.events if e.kind is IdentityEventKind.AMBIGUOUS).to_dict()
    assert d["kind"] == "AMBIGUOUS" and d["frame_id"] == 3 and d["hand_id"] is None
    assert isinstance(d["detail"]["margin"], float) and not isinstance(d["detail"]["margin"], np.floating)
