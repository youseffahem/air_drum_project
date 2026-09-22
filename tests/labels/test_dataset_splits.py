"""TEST-LABEL-8 — participant-level splits and leakage (Phase 07, Task 07.8).

These are the leakage tests the phase document requires: participant disjointness, session
integrity, no session in two folds, and the refusal to freeze or write a split that cannot be
justified. All rosters here are **SYNTHETIC pseudonyms** (`SYNTHETIC-P01`, …) used to exercise the
machinery; they are not participants and the machinery refuses to treat them as such.
"""

from __future__ import annotations

import json

import pytest

from spacedrums.data.metadata import SessionKind
from spacedrums.data.splits import (
    FOLDS_FILENAME,
    NORMALISATION_RULE,
    SPLIT_RULE_ID,
    TEST_FILENAME,
    Roster,
    build_split,
    leakage_checks,
    plan_for,
    read_split,
    roster_from_label_sets,
    split_hash,
    validate_split,
    write_split,
)

LV = "labels-v1.0"
SELFTEST = "ds-v0.0-selftest-splits"


def roster(P: int, *, sessions: int = 2, dataset_version: str = SELFTEST,
           kind: SessionKind = SessionKind.SYNTHETIC, strata=None) -> Roster:
    return Roster(
        dataset_version=dataset_version,
        labels_version=LV,
        source_kind=kind,
        sessions_by_participant={
            f"SYNTHETIC-P{i:02d}": [f"SYNTHETIC-P{i:02d}-S{s}" for s in range(1, sessions + 1)]
            for i in range(1, P + 1)
        },
        strata=strata,
        stratify_keys=("experience",) if strata else (),
    )


# ----------------------------------------------------------------------------- the rule


@pytest.mark.parametrize(
    "P, n_test, K",
    [(0, 0, 0), (1, 0, 1), (3, 0, 3), (4, 1, 3), (7, 1, 4), (8, 2, 5), (12, 3, 5), (20, 4, 5),
     (25, 5, 5)],
)
def test_split_plan_is_a_function_of_the_participant_count(P, n_test, K):
    assert plan_for(P)[:2] == (n_test, K)


def test_the_plan_names_the_small_sample_caveat():
    assert "statistically weak" in plan_for(6)[2]
    assert "leave-one-participant-out" in plan_for(2)[2]


def test_a_negative_participant_count_is_refused():
    with pytest.raises(ValueError, match="non-negative"):
        plan_for(-1)


# ----------------------------------------------------------------------------- leakage


def test_folds_and_test_set_are_participant_disjoint():
    test_doc, folds_doc = build_split(roster(10), seed=3)
    test = set(test_doc["test_participants"])
    assert test and not test & set(test_doc["dev_participants"])
    for fold in folds_doc["folds"]:
        assert not set(fold["train_participants"]) & set(fold["val_participants"])
        assert not (set(fold["train_participants"]) | set(fold["val_participants"])) & test


def test_every_session_of_a_participant_travels_with_that_participant():
    r = roster(8, sessions=3)
    test_doc, folds_doc = build_split(r, seed=1)
    for fold in folds_doc["folds"]:
        for p in fold["val_participants"]:
            assert set(r.sessions_by_participant[p]) <= set(fold["val_sessions"])
            assert not set(r.sessions_by_participant[p]) & set(fold["train_sessions"])


def test_no_session_appears_in_two_validation_folds():
    _, folds_doc = build_split(roster(10), seed=5)
    seen: set[str] = set()
    for fold in folds_doc["folds"]:
        assert not seen & set(fold["val_sessions"])
        seen |= set(fold["val_sessions"])


def test_every_session_is_assigned_somewhere():
    r = roster(9)
    test_doc, folds_doc = build_split(r, seed=2)
    assigned = {s for f in folds_doc["folds"] for s in f["val_sessions"]}
    assigned |= {s for p in test_doc["test_participants"] for s in r.sessions_by_participant[p]}
    assert assigned == {s for ss in r.sessions_by_participant.values() for s in ss}


def test_leakage_checks_detect_an_injected_overlap():
    r = roster(8)
    _, folds_doc = build_split(r, seed=1)
    broken = json.loads(json.dumps(folds_doc["folds"]))
    broken[0]["train_participants"].append(broken[0]["val_participants"][0])
    checks = leakage_checks([], broken, r.sessions_by_participant)
    assert checks["participants_disjoint"] is False
    assert checks["all_passed"] is False


def test_leakage_checks_detect_a_test_participant_inside_a_fold():
    r = roster(8)
    test_doc, folds_doc = build_split(r, seed=1)
    broken = json.loads(json.dumps(folds_doc["folds"]))
    broken[0]["train_participants"].append(test_doc["test_participants"][0])
    checks = leakage_checks(test_doc["test_participants"], broken, r.sessions_by_participant)
    assert checks["test_not_in_any_fold"] is False


def test_a_frozen_split_records_every_check_as_passed():
    r = roster(8, dataset_version="ds-v1.0", kind=SessionKind.PARTICIPANT)
    test_doc, _ = build_split(r, seed=0, freeze=True, frozen_at="2026-09-22T12:00:00+03:00")
    assert test_doc["frozen"] is True
    assert test_doc["leakage_checks"]["all_passed"] is True
    assert validate_split(test_doc) == []


# ----------------------------------------------------------------------------- determinism


def test_the_same_roster_and_seed_produce_the_same_split():
    a, _ = build_split(roster(10), seed=11)
    b, _ = build_split(roster(10), seed=11)
    assert a["split_hash"] == b["split_hash"]
    assert a["test_participants"] == b["test_participants"]


def test_a_different_seed_can_produce_a_different_split():
    hashes = {build_split(roster(12), seed=s)[0]["split_hash"] for s in range(6)}
    assert len(hashes) > 1


def test_both_files_of_one_split_share_the_hash():
    test_doc, folds_doc = build_split(roster(10), seed=4)
    assert test_doc["split_hash"] == folds_doc["split_hash"]
    assert test_doc["split_kind"] == "TEST_HOLDOUT" and folds_doc["split_kind"] == "CV_FOLDS"


def test_the_hash_covers_the_roster_and_the_outcome():
    a, _ = build_split(roster(10), seed=0)
    b, _ = build_split(roster(11), seed=0)
    assert a["split_hash"] != b["split_hash"]
    tampered = dict(a)
    tampered["test_participants"] = list(a["dev_participants"][:1])
    assert split_hash(tampered) != a["split_hash"]


def test_a_tampered_split_file_fails_validation():
    test_doc, _ = build_split(roster(10), seed=0)
    test_doc["test_participants"] = ["SYNTHETIC-P01"]
    assert any("split_hash" in e for e in validate_split(test_doc))


# ----------------------------------------------------------------------------- stratification


def test_stratified_picking_spreads_the_test_set_over_the_strata():
    strata = {f"SYNTHETIC-P{i:02d}": ("NOVICE" if i % 2 else "EXPERIENCED") for i in range(1, 13)}
    test_doc, _ = build_split(roster(12, strata=strata), seed=0)
    picked = {strata[p] for p in test_doc["test_participants"]}
    assert picked == {"NOVICE", "EXPERIENCED"}
    assert "experience" in test_doc["stratify_keys"]


def test_without_strata_the_rationale_says_so():
    test_doc, _ = build_split(roster(8), seed=0)
    assert "No stratification was possible" in test_doc["rationale"]
    assert SPLIT_RULE_ID in test_doc["rationale"]


# ----------------------------------------------------------------------------- refusals


def test_a_synthetic_roster_cannot_claim_a_participant_dataset_version():
    with pytest.raises(ValueError, match="cannot produce a PARTICIPANT split"):
        build_split(roster(8, dataset_version="ds-v1.0"), seed=0)


def test_participant_material_never_enters_a_self_test_split():
    with pytest.raises(ValueError, match="never enters a self-test split"):
        build_split(roster(8, kind=SessionKind.PARTICIPANT), seed=0)


def test_a_self_test_split_cannot_be_frozen():
    with pytest.raises(ValueError, match="self-test material is never frozen"):
        build_split(roster(8), seed=0, freeze=True)


def test_an_empty_roster_cannot_be_frozen():
    r = Roster("ds-v1.0", LV, SessionKind.PARTICIPANT, {})
    with pytest.raises(ValueError, match="no participant exists"):
        build_split(r, seed=0, freeze=True)


def test_holding_out_more_participants_than_exist_is_refused():
    with pytest.raises(ValueError, match="cannot hold out"):
        build_split(roster(3), seed=0, n_test=5)


def test_writing_an_empty_participant_split_is_refused(tmp_path):
    r = Roster("ds-v1.0", LV, SessionKind.PARTICIPANT, {})
    test_doc, folds_doc = build_split(r, seed=0)
    with pytest.raises(ValueError, match="refusing to write an empty participant split"):
        write_split(test_doc, folds_doc, tmp_path)


# ----------------------------------------------------------------------------- files


def test_writing_and_reading_a_self_test_split_round_trips(tmp_path):
    test_doc, folds_doc = build_split(roster(10), seed=0)
    a, b = write_split(test_doc, folds_doc, tmp_path)
    assert a.name == TEST_FILENAME and b.name == FOLDS_FILENAME
    assert a.parent.name == SELFTEST
    assert read_split(a)["split_hash"] == test_doc["split_hash"]
    assert read_split(b)["folds"] == folds_doc["folds"]


def test_every_split_file_carries_the_phase08_normalisation_rule():
    test_doc, folds_doc = build_split(roster(8), seed=0)
    for doc in (test_doc, folds_doc):
        assert doc["normalisation_rule"] == NORMALISATION_RULE
        assert "TRAIN participants" in doc["normalisation_rule"]


def test_a_self_test_split_is_labelled_development_only():
    test_doc, _ = build_split(roster(8), seed=0)
    assert "TEST / DEVELOPMENT ONLY" in test_doc["label"]


# ----------------------------------------------------------------------------- roster building


def test_a_roster_from_label_sets_groups_sessions_by_participant():
    sets = [
        {"participant_id": "SYNTHETIC-P01", "session_id": "s1", "source_kind": "SYNTHETIC"},
        {"participant_id": "SYNTHETIC-P01", "session_id": "s2", "source_kind": "SYNTHETIC"},
        {"participant_id": "SYNTHETIC-P02", "session_id": "s3", "source_kind": "SYNTHETIC"},
    ]
    r = roster_from_label_sets(sets, dataset_version=SELFTEST, labels_version=LV)
    assert r.P == 2
    assert r.sessions_by_participant["SYNTHETIC-P01"] == ["s1", "s2"]


def test_a_roster_refuses_to_mix_source_kinds():
    sets = [
        {"participant_id": "A", "session_id": "s1", "source_kind": "SYNTHETIC"},
        {"participant_id": "B", "session_id": "s2", "source_kind": "DEV_CAPTURE"},
    ]
    with pytest.raises(ValueError, match="mixed source kinds"):
        roster_from_label_sets(sets, dataset_version=SELFTEST, labels_version=LV)
