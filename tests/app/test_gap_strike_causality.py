"""Strikes around short tracking gaps (live responsiveness 2026-10-02, Part 8) - current safe behaviour.

A strike is committed only from observed VALID positions: dropped frames up to the guard
(``commit.max_dropped_since_last`` = 3) still let a VALID crossing commit, nothing is committed on
bridged or DEGRADED frames, and an entry seen only on a non-VALID frame is not committed later from
memory (the geometry episode stays open). A reset clears the trajectory history. SYNTHETIC
observation sequences (``spacedrums.app.synthetic``) through the full decision pipeline.
"""

from __future__ import annotations

from dataclasses import replace

from app_helpers import all_commits, run_sequence

from spacedrums.app.synthetic import Swing, build_sequence
from spacedrums.contracts import HandId, TrackStatus

R = HandId.RIGHT


def sequence(registry, **kwargs):
    swing = Swing(hand=R, zone_id="snare", t_start=0.30, t_down=0.20, depth=0.05)
    return build_sequence(registry, [swing], duration_s=1.0, **kwargs)


def entry_frame(registry, seq) -> int:
    zone = registry["snare"]
    for k, (_, obs) in enumerate(seq.frames):
        tip = obs[R][1].tip
        if tip is not None and zone.shape.contains(tip):
            return k
    raise AssertionError("the synthetic stroke never enters the zone")


def drop(seq, frames: set[int]):
    """Remove delivered frames (a queue drop) and report them on the next delivered frame."""
    out, pending = [], 0
    for k, (sample, obs) in enumerate(seq.frames):
        if k in frames:
            pending += 1
            continue
        out.append((replace(sample, dropped_since_last=pending), obs))
        pending = 0
    return out


def non_valid_commits(results) -> int:
    return sum(
        1 for r in results for c in r.commits if r.hands[c.hand_id].track.status is not TrackStatus.VALID
    )


def test_reference_stroke_commits_once_at_the_observed_entry(make_pipeline, registry):
    seq = sequence(registry)
    results = run_sequence(make_pipeline(), seq.frames)
    commits = [c for c in all_commits(results) if not c.shadow]
    assert len(commits) == 1 and commits[0].frame_id == entry_frame(registry, seq)


def test_a_dropped_entry_frame_still_commits_from_the_next_valid_frame(make_pipeline, registry):
    seq = sequence(registry)
    k = entry_frame(registry, seq)
    results = run_sequence(make_pipeline(), drop(seq, {k}))
    commits = [c for c in all_commits(results) if not c.shadow]
    assert len(commits) == 1 and commits[0].frame_id == k + 1  # VALID outside -> VALID inside
    assert non_valid_commits(results) == 0


def test_more_dropped_frames_than_the_guard_allows_commit_nothing(make_pipeline, registry):
    seq = sequence(registry)
    k = entry_frame(registry, seq)
    results = run_sequence(make_pipeline(), drop(seq, {k - 3, k - 2, k - 1, k}))
    assert [c for c in all_commits(results) if not c.shadow] == []


def test_an_entry_seen_only_on_a_degraded_frame_is_never_committed_later(make_pipeline, registry):
    """The first frame whose filtered tip is inside the zone is DEGRADED: the entry is observed and
    discarded, and the geometry episode stays open, so the VALID frames that follow inside the zone
    commit nothing. (A low-confidence update can also leave the filtered tip outside; then the next
    VALID frame is the entry and commits - the frame below is chosen so that the entry is DEGRADED.)"""
    swing = [Swing(hand=R, zone_id="snare", t_start=0.30, t_down=0.15, depth=0.08)]
    k = entry_frame(registry, build_sequence(registry, swing, duration_s=1.0))
    for j in (k, k + 1):
        seq = build_sequence(registry, swing, duration_s=1.0, low_conf={R: {j: 0.45}})
        results = run_sequence(make_pipeline(), seq.frames)
        frame = results[j].hands[R]
        if frame.track.status is TrackStatus.DEGRADED and any(
            str(c.source) == "REACTIVE" for c in frame.candidates
        ):
            break
    else:
        raise AssertionError("no DEGRADED entry frame in this stroke")
    traces = [t["decision"] for t in frame.decision_traces if t["arm"] == "A"]
    assert traces == ["REJECT_STATUS"]  # the entry is observed but discarded ...
    assert [c for c in all_commits(results) if not c.shadow] == []  # ... and never sounds later
    assert non_valid_commits(results) == 0


def test_bridged_frames_never_commit_and_a_reset_starts_a_fresh_history(make_pipeline, registry):
    seq = sequence(registry)
    k = entry_frame(registry, seq)
    hidden = build_sequence(
        registry,
        [Swing(hand=R, zone_id="snare", t_start=0.30, t_down=0.20, depth=0.05)],
        duration_s=1.0,
        occluded={R: set(range(k - 2, k + 3))},
    )
    pipeline = make_pipeline()
    results = run_sequence(pipeline, hidden.frames)
    assert non_valid_commits(results) == 0
    statuses = [r.hands[R].track.status for r in results]
    assert TrackStatus.INVALID in statuses  # 5 hidden frames > g_max_frames = 3: reset
    back = statuses.index(TrackStatus.VALID, statuses.index(TrackStatus.INVALID))
    assert results[back].hands[R].track.history_ref.n == 0  # re-acquired from the observation only
