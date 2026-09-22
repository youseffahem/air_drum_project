"""TEST-LABEL-7 — acoustic onset ground truth and the has_phys_gt invariant (Phase 07, Task 07.6).

No microphone recording exists, so the tests below drive the pairing with **injected** onset times
whose offset is known by construction. That validates the machinery and the invariant; it measures
no physical latency and claims no offset for this project's recordings.
"""

from __future__ import annotations

import pytest
from label_helpers import labelled_session

from spacedrums.data.labels.acoustic import (
    DEFAULT_MIC_LATENCY_BOUND_S,
    PairResult,
    apply_pairings,
    pad_segments,
    pair_onsets,
    pair_session,
)
from spacedrums.data.labels.schema import LabelClass
from spacedrums.data.metadata import SessionMetadata


@pytest.fixture(scope="module")
def pad_session(tmp_path_factory):
    """A SYNTHETIC session that contains a PAD segment (the recorder's optional pad block)."""
    tmp = tmp_path_factory.mktemp("p07-acoustic")
    session_dir, result, _ = labelled_session(tmp, session_id="synthetic-acoustic", pad_zone="snare")
    return session_dir, result, SessionMetadata.read(session_dir)


# ----------------------------------------------------------------------------- PENDING branch


def test_a_session_without_a_microphone_track_reports_pending_with_a_reason(pad_session):
    session_dir, result, _ = pad_session
    got = pair_session(session_dir, result.labels)
    assert got.available is False
    assert got.reason
    assert got.n_paired == 0
    assert got.stats()["bias_s"] is None


def test_the_pending_result_serialises_with_its_reason(pad_session):
    session_dir, result, _ = pad_session
    doc = pair_session(session_dir, result.labels).to_dict()
    assert doc["available"] is False and doc["reason"]
    assert doc["bias_s"] is None and doc["n_paired"] == 0


def test_a_session_flagged_without_physical_gt_is_refused_early(tmp_path):
    from data_helpers import make_session

    session_dir, _, _ = make_session(tmp_path / "raw", session_id="synthetic-nophys")
    meta = SessionMetadata.read(session_dir)
    assert meta.data["has_phys_gt"] is False
    got = pair_session(session_dir, [])
    assert got.available is False and "has_phys_gt" in got.reason


# ----------------------------------------------------------------------------- pairing


def test_pad_segments_are_the_only_ones_with_a_pad_zone(pad_session):
    _, _, meta = pad_session
    segs = pad_segments(meta)
    assert segs, "the fixture session records a PAD block"
    assert all(s["condition"] == "PAD" and s["pad_zone_id"] for s in segs)


def test_injected_onsets_pair_with_the_pad_zone_positives_and_recover_the_offset(pad_session):
    _, result, meta = pad_session
    offset = 0.006
    eligible = [
        r for r in result.labels
        if r["label_class"] == str(LabelClass.POSITIVE) and r["segment_type"] == "PAD_MIC"
    ]
    if not eligible:
        pytest.skip("this SYNTHETIC session produced no positive inside the pad block")
    onsets = [r["t_impact_est"] + offset for r in eligible]
    pairs = pair_onsets(result.labels, onsets, meta)
    assert len(pairs) == len(eligible)
    for p in pairs:
        assert p.residual_s == pytest.approx(offset)


def test_an_onset_outside_the_window_is_not_paired(pad_session):
    _, result, meta = pad_session
    eligible = [
        r for r in result.labels
        if r["label_class"] == str(LabelClass.POSITIVE) and r["segment_type"] == "PAD_MIC"
    ]
    if not eligible:
        pytest.skip("this SYNTHETIC session produced no positive inside the pad block")
    onsets = [r["t_impact_est"] + 5.0 for r in eligible]
    assert pair_onsets(result.labels, onsets, meta, window_s=0.15) == []


def test_positives_outside_the_pad_segment_are_never_paired(pad_session):
    """The per-strike level of the has_phys_gt invariant: a strike on another zone, or in an AIR
    segment, has no physical ground truth even though the session has a microphone."""
    _, result, meta = pad_session
    others = [
        r for r in result.labels
        if r["label_class"] == str(LabelClass.POSITIVE) and r["segment_type"] != "PAD_MIC"
    ]
    if not others:
        pytest.skip("this SYNTHETIC session produced no positive outside the pad block")
    onsets = [r["t_impact_est"] + 0.005 for r in others]
    assert pair_onsets(result.labels, onsets, meta) == []


def test_pairing_is_one_to_one(pad_session):
    _, result, meta = pad_session
    eligible = [
        r for r in result.labels
        if r["label_class"] == str(LabelClass.POSITIVE) and r["segment_type"] == "PAD_MIC"
    ]
    if not eligible:
        pytest.skip("this SYNTHETIC session produced no positive inside the pad block")
    onsets = [eligible[0]["t_impact_est"] + d for d in (0.004, 0.006, 0.008)]
    pairs = pair_onsets(result.labels, onsets, meta)
    assert len({p.label_id for p in pairs}) == len(pairs)
    assert len({p.onset_index for p in pairs}) == len(pairs)


# ----------------------------------------------------------------------------- application


def _pair_result(labels, meta, offset=0.006):
    """A PairResult built from injected onsets.

    ``pair_session`` is deliberately not used here: it refuses a session whose ``has_phys_gt`` is
    false, and no SYNTHETIC session carries a microphone track (that is the honest state of the
    project). This exercises the application step with an offset that is known because it was
    injected - machinery evidence, not a measurement.
    """
    eligible = [
        r for r in labels
        if r["label_class"] == str(LabelClass.POSITIVE) and r["segment_type"] == "PAD_MIC"
    ]
    if not eligible:
        pytest.skip("this SYNTHETIC session produced no positive inside the pad block")
    onsets = [r["t_impact_est"] + offset for r in eligible]
    pairs = pair_onsets(labels, onsets, meta)
    return PairResult(
        available=True,
        reason=None,
        n_pad_positives=len(eligible),
        n_onsets=len(onsets),
        n_paired=len(pairs),
        pairings=tuple(pairs),
        mic_latency_bound_s=DEFAULT_MIC_LATENCY_BOUND_S,
        sync_residual_rms_s=None,
        evidence_label="SYNTHETIC - injected onsets, not a microphone recording",
    )


def test_applying_pairings_fills_only_the_paired_labels(pad_session):
    _, result, meta = pad_session
    got = _pair_result(result.labels, meta)
    updated = apply_pairings(result.labels, got, meta)
    paired_ids = {p.label_id for p in got.pairings}
    for rec in updated:
        if rec["label_id"] in paired_ids:
            assert rec["t_impact_phys"] is not None
            assert rec["phys"]["mic_latency_bound_s"] == DEFAULT_MIC_LATENCY_BOUND_S
            assert rec["phys"]["pad_zone_id"] == rec["zone_id"]
        else:
            assert rec["t_impact_phys"] is None and rec["phys"] is None


def test_the_residual_statistics_report_a_fraction_paired(pad_session):
    _, result, meta = pad_session
    got = _pair_result(result.labels, meta)
    stats = got.stats()
    assert stats["bias_s"] == pytest.approx(0.006)
    assert 0.0 <= stats["fraction_paired"] <= 1.0
