"""TEST-LABEL-6 — QC/review round-trip and agreement statistics (Phase 07, Task 07.5).

The interactive tool needs a person; everything below it does not, and that is what is tested here:
the sampling plan, the deterministic review queue, applying a decision, the correction history, the
second-pass disagreement rule, and Cohen's kappa.

Every decision used here is **scripted by the test**. Nothing in this file is an annotator's
judgement and no inter-annotator agreement is claimed.
"""

from __future__ import annotations

import json

import pytest
from label_helpers import labelled_session

from spacedrums.data.labels.review import (
    QC_PROTOCOL_ID,
    SamplingPlan,
    agreement,
    apply_entry,
    cohen_kappa,
    make_entry,
    qc_summary,
    read_review_log,
    review_queue,
    stratum_of,
    write_review_log,
)
from spacedrums.data.labels.schema import LabelClass, QCStatus, ReviewDecision, validate_label

STAMP = "2026-09-22T12:00:00+03:00"
STAMP2 = "2026-09-22T13:00:00+03:00"


@pytest.fixture(scope="module")
def labels(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p07-review")
    _, result, _ = labelled_session(tmp, session_id="synthetic-review")
    return result.labels, result.label_dir


# ----------------------------------------------------------------------------- sampling plan


def test_sampling_plan_rates_per_class():
    plan = SamplingPlan(1.0, 1.0, 0.25)
    assert plan.rate_for(LabelClass.POSITIVE) == 1.0
    assert plan.rate_for(LabelClass.AMBIGUOUS) == 1.0
    assert plan.rate_for(LabelClass.NEG_FAKE_SWING) == 0.25
    assert plan.rate_for(LabelClass.EXCLUDED) == 0.0


def test_sampling_plan_rejects_rates_outside_zero_one():
    with pytest.raises(ValueError, match="positives_rate"):
        SamplingPlan(1.5, 1.0, 1.0)


def test_queue_reviews_every_positive_and_samples_negatives(labels):
    recs, _ = labels
    queue = review_queue(recs, SamplingPlan(1.0, 1.0, 0.0))
    queued = {r["label_id"] for r in queue}
    for rec in recs:
        if rec["label_class"] in (str(LabelClass.POSITIVE), str(LabelClass.AMBIGUOUS)):
            assert rec["label_id"] in queued
        if rec["label_class"].startswith("NEG_"):
            assert rec["label_id"] not in queued


def test_queue_is_deterministic(labels):
    recs, _ = labels
    a = [r["label_id"] for r in review_queue(recs, SamplingPlan(1.0, 1.0, 0.5))]
    b = [r["label_id"] for r in review_queue(recs, SamplingPlan(1.0, 1.0, 0.5))]
    assert a == b == sorted(a)


def test_excluded_labels_are_never_queued():
    rec = {"label_id": "x", "label_class": str(LabelClass.EXCLUDED)}
    assert review_queue([rec], SamplingPlan(1.0, 1.0, 1.0)) == []


# ----------------------------------------------------------------------------- stratification


def test_stratum_carries_zone_hand_segment_speed_and_lighting(labels):
    recs, _ = labels
    s = stratum_of(recs[0], lighting="L2")
    assert set(s) == {"zone_id", "hand_id", "segment_type", "speed_band", "lighting"}
    assert s["lighting"] == "L2"
    assert s["speed_band"] in ("SLOW", "MEDIUM", "FAST", "UNKNOWN")


# ----------------------------------------------------------------------------- decisions


def _entry(rec, decision, *, after=None, reason=None, pass_no=1, reviewer="A1", at=STAMP):
    return make_entry(rec, decision=decision, reviewer_id=reviewer, reviewed_at=at,
                      pass_no=pass_no, after=after, reason=reason)


def test_accept_marks_the_label_reviewed_without_changing_it(labels):
    recs, _ = labels
    rec = next(r for r in recs if r["label_class"] == str(LabelClass.POSITIVE))
    out = apply_entry(rec, _entry(rec, ReviewDecision.ACCEPT))
    assert out["qc_status"] == str(QCStatus.ACCEPTED)
    assert out["review"]["reviewed"] is True and out["review"]["reviewer_id"] == "A1"
    assert out["t_impact_est"] == rec["t_impact_est"]
    assert out["review"]["adjusted"] is False
    assert validate_label(out) == []


def test_reject_records_the_decision_and_keeps_the_label(labels):
    recs, _ = labels
    out = apply_entry(recs[0], _entry(recs[0], ReviewDecision.REJECT, reason="tracker artefact"))
    assert out["qc_status"] == str(QCStatus.REJECTED)
    assert out["review"]["reason"] == "tracker artefact"
    assert validate_label(out) == []


def test_defer_makes_the_event_ambiguous(labels):
    recs, _ = labels
    rec = next(r for r in recs if r["label_class"] == str(LabelClass.POSITIVE))
    out = apply_entry(rec, _entry(rec, ReviewDecision.DEFER, reason="cannot tell"))
    assert out["label_class"] == str(LabelClass.AMBIGUOUS)
    assert out["label_rule_id"] == "P07-R6c"
    assert validate_label(out) == []


def test_adjust_keeps_the_original_and_records_the_history(labels):
    recs, _ = labels
    rec = next(r for r in recs if r["label_class"] == str(LabelClass.POSITIVE))
    shifted = rec["t_impact_est"] + 0.008
    after = {"t_impact_est": shifted, "t_event": shifted, "zone_id": rec["zone_id"],
             "label_class": rec["label_class"]}
    out = apply_entry(rec, _entry(rec, ReviewDecision.ADJUST, after=after, reason="one frame late"))
    assert out["qc_status"] == str(QCStatus.ADJUSTED)
    assert out["review"]["adjusted"] is True
    assert out["review"]["original"]["t_impact_est"] == rec["t_impact_est"]
    fields = {h["field"] for h in out["review"]["history"]}
    assert fields == {"t_impact_est", "t_event"}
    assert out["t_impact_est"] == shifted
    assert validate_label(out) == []


def test_a_second_adjustment_appends_to_the_history_and_keeps_the_first_original(labels):
    recs, _ = labels
    rec = next(r for r in recs if r["label_class"] == str(LabelClass.POSITIVE))
    first = rec["t_impact_est"] + 0.008
    once = apply_entry(rec, _entry(rec, ReviewDecision.ADJUST,
                                   after={"t_impact_est": first, "t_event": first,
                                          "zone_id": rec["zone_id"],
                                          "label_class": rec["label_class"]},
                                   reason="first"))
    second = first + 0.004
    twice = apply_entry(once, _entry(once, ReviewDecision.ADJUST,
                                     after={"t_impact_est": second, "t_event": second,
                                            "zone_id": once["zone_id"],
                                            "label_class": once["label_class"]},
                                     reason="second"))
    assert twice["review"]["original"]["t_impact_est"] == rec["t_impact_est"]
    assert len(twice["review"]["history"]) == 4
    assert twice["t_impact_est"] == second


def test_changing_the_class_to_a_negative_clears_the_impact_fields(labels):
    recs, _ = labels
    rec = next(r for r in recs if r["label_class"] == str(LabelClass.POSITIVE))
    after = {"t_impact_est": rec["t_impact_est"], "t_event": rec["t_event"],
             "zone_id": rec["zone_id"], "label_class": str(LabelClass.NEG_FAKE_SWING)}
    out = apply_entry(rec, _entry(rec, ReviewDecision.ADJUST, after=after, reason="pulled up"))
    assert out["label_class"] == str(LabelClass.NEG_FAKE_SWING)
    assert out["t_impact_est"] is None and out["intensity_proxy_gt"] is None
    assert validate_label(out) == []


def test_an_adjust_entry_requires_a_reason(labels):
    recs, _ = labels
    rec = recs[0]
    with pytest.raises(ValueError, match="review entry invalid"):
        make_entry(rec, decision=ReviewDecision.ADJUST, reviewer_id="A1", reviewed_at=STAMP,
                   after={"t_impact_est": None, "t_event": rec["t_event"],
                          "zone_id": rec["zone_id"], "label_class": rec["label_class"]},
                   reason=None)


# ----------------------------------------------------------------------------- second pass


def test_second_pass_never_overwrites_the_first(labels):
    recs, _ = labels
    rec = next(r for r in recs if r["label_class"] == str(LabelClass.POSITIVE))
    first = apply_entry(rec, _entry(rec, ReviewDecision.ACCEPT))
    second = apply_entry(first, _entry(first, ReviewDecision.ACCEPT, pass_no=2, reviewer="A2",
                                       at=STAMP2))
    assert second["review"]["reviewer_id"] == "A1"
    assert second["review"]["second_pass"]["reviewer_id"] == "A2"
    assert second["qc_status"] == str(QCStatus.ACCEPTED)
    assert validate_label(second) == []


def test_a_presence_disagreement_makes_the_event_ambiguous(labels):
    recs, _ = labels
    rec = next(r for r in recs if r["label_class"] == str(LabelClass.POSITIVE))
    first = apply_entry(rec, _entry(rec, ReviewDecision.ACCEPT))
    second = apply_entry(first, _entry(first, ReviewDecision.REJECT, pass_no=2, reviewer="A2",
                                       at=STAMP2, reason="not a strike"))
    assert second["review"]["disagreement"]["kind"] == "PRESENCE"
    assert second["review"]["disagreement"]["resolution"] == "AMBIGUOUS"
    assert second["label_class"] == str(LabelClass.AMBIGUOUS)
    assert validate_label(second) == []


def test_a_timing_disagreement_is_recorded_and_keeps_the_first_pass_value(labels):
    recs, _ = labels
    rec = next(r for r in recs if r["label_class"] == str(LabelClass.POSITIVE))
    first = apply_entry(rec, _entry(rec, ReviewDecision.ACCEPT))
    shifted = first["t_impact_est"] + 0.01
    entry = make_entry(first, decision=ReviewDecision.ADJUST, reviewer_id="A2", reviewed_at=STAMP2,
                       pass_no=2, after={"t_impact_est": shifted, "t_event": shifted,
                                         "zone_id": first["zone_id"],
                                         "label_class": first["label_class"]},
                       reason="half a frame later")
    second = apply_entry(first, entry)
    d = second["review"]["disagreement"]
    assert d["kind"] == "TIMING" and d["resolution"] == "FIRST_PASS"
    assert second["t_impact_est"] == first["t_impact_est"]
    assert d["delta_t_s"] == pytest.approx(0.01)


# ----------------------------------------------------------------------------- log


def test_review_log_round_trips_and_is_append_only(labels, tmp_path):
    recs, _ = labels
    path = tmp_path / "review.jsonl"
    write_review_log([_entry(recs[0], ReviewDecision.ACCEPT)], path)
    write_review_log([_entry(recs[1], ReviewDecision.ACCEPT)], path)
    log = read_review_log(path)
    assert len(log) == 2
    assert [e["label_id"] for e in log] == [recs[0]["label_id"], recs[1]["label_id"]]


def test_reading_a_missing_log_is_empty_not_an_error(tmp_path):
    assert read_review_log(tmp_path / "nothing.jsonl") == []


def test_an_invalid_entry_is_refused_by_the_writer(labels, tmp_path):
    recs, _ = labels
    bad = _entry(recs[0], ReviewDecision.ACCEPT)
    bad["pass"] = 7
    with pytest.raises(ValueError, match="review entry invalid"):
        write_review_log([bad], tmp_path / "review.jsonl")


# ----------------------------------------------------------------------------- agreement


def test_cohen_kappa_of_perfect_disagreement_is_minus_one():
    kappa, p_o, p_e = cohen_kappa([(True, False), (False, True)])
    assert kappa == pytest.approx(-1.0)
    assert p_o == 0.0 and p_e == pytest.approx(0.5)


def test_cohen_kappa_is_undefined_when_one_category_is_used_throughout():
    kappa, p_o, _ = cohen_kappa([(True, True), (True, True)])
    assert kappa is None, "a perfect score on a single category would be meaningless"
    assert p_o == 1.0


def test_cohen_kappa_of_an_empty_sample_is_none():
    assert cohen_kappa([])[0] is None


def test_agreement_pairs_the_two_passes_and_reports_timing(labels):
    recs, _ = labels
    rec = next(r for r in recs if r["label_class"] == str(LabelClass.POSITIVE))
    after1 = {"t_impact_est": rec["t_impact_est"], "t_event": rec["t_event"],
              "zone_id": rec["zone_id"], "label_class": rec["label_class"]}
    shifted = rec["t_impact_est"] + 0.012
    after2 = {**after1, "t_impact_est": shifted, "t_event": shifted}
    entries = [
        _entry(rec, ReviewDecision.ACCEPT, after=after1),
        make_entry(rec, decision=ReviewDecision.ADJUST, reviewer_id="A2", reviewed_at=STAMP2,
                   pass_no=2, after=after2, reason="later"),
    ]
    ag = agreement(entries, kind="INTER_ANNOTATOR", evidence_label="SYNTHETIC scripted")
    assert ag.n_pairs == 1 and ag.n_both_present == 1
    assert ag.median_abs_dt_s == pytest.approx(0.012)
    assert ag.to_dict()["evidence_label"] == "SYNTHETIC scripted"


def test_agreement_without_a_second_pass_reports_nothing_rather_than_a_number(labels):
    recs, _ = labels
    ag = agreement([_entry(recs[0], ReviewDecision.ACCEPT)], evidence_label="PENDING")
    assert ag.n_pairs == 0 and ag.kappa is None and ag.median_abs_dt_s is None


# ----------------------------------------------------------------------------- summary


def test_qc_summary_counts_the_review_state(labels):
    recs, _ = labels
    reviewed = [apply_entry(recs[0], _entry(recs[0], ReviewDecision.ACCEPT))] + list(recs[1:])
    summary = qc_summary(reviewed, SamplingPlan(1.0, 1.0, 0.2))
    assert summary["protocol_id"] == QC_PROTOCOL_ID
    assert summary["reviewed"] == 1
    assert summary["accepted"] == 1
    assert summary["pending"] == len(recs) - 1
    assert summary["sampling"]["negatives_rate"] == 0.2
    assert json.dumps(summary)  # serialisable into the label set
