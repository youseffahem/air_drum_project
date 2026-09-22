"""TEST-LABEL-9 — label statistics, labelled-dataset manifest and dataset card
(Phase 07, Tasks 07.9 / 07.10).

The rule under test throughout is that evidence classes are never merged: statistics group by
``source_kind`` and the helper raises rather than produce one number across kinds; a dataset
manifest admits one kind and refuses the others with a reason; an empty participant manifest is
refused; and the card prints PENDING where there is nothing to report instead of printing zeros.
"""

from __future__ import annotations

import copy

import pytest
from label_helpers import labelled_session

from spacedrums.data.labels.dataset import (
    CARD_LIMITATIONS,
    build_manifest,
    check_manifest_files,
    dataset_card,
    manifest_hash,
    phys_summary,
    read_manifest,
    validate_manifest,
    write_manifest,
)
from spacedrums.data.labels.generate import read_label_set
from spacedrums.data.labels.schema import (
    LABEL_SET_FILENAME,
    LabelClass,
    dataset_kind,
    evidence_label,
)
from spacedrums.data.labels.stats import aggregate, class_balance, group_stats, markdown_table
from spacedrums.data.metadata import SessionKind


@pytest.fixture(scope="module")
def labelled(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p07-stats")
    session_dir, result, _ = labelled_session(tmp, session_id="synthetic-stats")
    return tmp, session_dir, result


# ----------------------------------------------------------------------------- statistics


def test_group_stats_count_every_dimension(labelled):
    _, _, result = labelled
    s = group_stats(result.labels).to_dict()
    assert s["n_labels"] == len(result.labels)
    assert s["n_sessions"] == 1 and s["n_participants"] == 1
    assert sum(s["by_class"].values()) == len(result.labels)
    assert sum(s["by_hand"].values()) == len(result.labels)
    assert "SYNTHETIC" in s["evidence_label"]
    assert "MEASURED from the listed labels" in s["label"]


def test_intensity_distribution_covers_the_positives_only(labelled):
    _, _, result = labelled
    s = group_stats(result.labels).to_dict()
    n_pos = sum(1 for r in result.labels if r["label_class"] == str(LabelClass.POSITIVE))
    assert s["intensity_proxy_gt"]["n"] == n_pos
    if n_pos:
        assert s["intensity_proxy_gt"]["median"] is not None


def test_ambiguous_and_excluded_leave_the_metric_eligible_count(labelled):
    _, _, result = labelled
    labels = copy.deepcopy(result.labels)
    labels[0]["label_class"] = str(LabelClass.AMBIGUOUS)
    labels[0]["t_impact_est"] = None
    labels[0]["intensity_proxy_gt"] = None
    s = group_stats(labels).to_dict()
    assert s["metric_eligible"] == len(labels) - 1
    assert s["ambiguous_fraction"] == pytest.approx(1 / len(labels))


def test_adjustment_rate_is_none_when_nothing_was_reviewed(labelled):
    _, _, result = labelled
    assert group_stats(result.labels).to_dict()["adjustment_rate"] is None


def test_strata_sizes_come_from_the_session_descriptors(labelled):
    _, _, result = labelled
    strata = {result.labels[0]["session_id"]: {"distance_mark": "d100", "lighting": "L2"}}
    s = group_stats(result.labels, strata=strata).to_dict()
    assert s["by_distance_mark"] == {"d100": len(result.labels)}
    assert s["by_lighting"] == {"L2": len(result.labels)}


def test_class_balance_sums_to_one(labelled):
    _, _, result = labelled
    shares = class_balance(group_stats(result.labels).to_dict())
    assert sum(shares.values()) == pytest.approx(1.0)


# ----------------------------------------------------------------------------- never mix kinds


def test_evidence_label_refuses_to_describe_mixed_kinds():
    with pytest.raises(ValueError, match="mixed source kinds"):
        evidence_label({SessionKind.SYNTHETIC, SessionKind.PARTICIPANT})


def test_group_stats_refuse_a_mixed_group(labelled):
    _, _, result = labelled
    labels = copy.deepcopy(result.labels)
    labels[0]["source_kind"] = "DEV_CAPTURE"
    with pytest.raises(ValueError, match="mixed source kinds"):
        group_stats(labels)


def test_aggregate_groups_by_kind_and_produces_no_cross_kind_total(labelled):
    _, _, result = labelled
    labels = copy.deepcopy(result.labels)
    labels[0]["source_kind"] = "DEV_CAPTURE"
    groups = aggregate(labels)
    assert set(groups) == {"SYNTHETIC", "DEV_CAPTURE"}
    assert "total" not in groups
    assert groups["DEV_CAPTURE"]["n_labels"] == 1


def test_markdown_table_renders_one_section_per_kind(labelled):
    _, _, result = labelled
    labels = copy.deepcopy(result.labels)
    labels[0]["source_kind"] = "DEV_CAPTURE"
    text = markdown_table(aggregate(labels))
    assert text.count("### ") == 2
    assert "SYNTHETIC" in text and "DEV CAPTURE" in text


# ----------------------------------------------------------------------------- manifest


def test_manifest_lists_the_label_set_and_hashes_deterministically(labelled):
    tmp, _, result = labelled
    a = build_manifest(tmp / "labels", "ds-v0.0-selftest-tests", git_sha="0" * 40,
                       generated_at="2026-09-22T12:00:00+03:00")
    b = build_manifest(tmp / "labels", "ds-v0.0-selftest-tests", git_sha="0" * 40,
                       generated_at="2026-09-22T13:00:00+03:00")
    assert a["manifest_hash"] == b["manifest_hash"], "generated_at is excluded from the hash"
    assert a["totals"]["n_label_sets"] == 1
    assert a["totals"]["n_labels"] == len(result.labels)
    assert validate_manifest(a) == []
    assert a["kind"] == "SELFTEST"
    assert "TEST / DEVELOPMENT ONLY" in a["label"]


def test_manifest_files_can_be_rehashed(labelled):
    tmp, _, _ = labelled
    doc = build_manifest(tmp / "labels", "ds-v0.0-selftest-tests", git_sha="0" * 40)
    assert check_manifest_files(doc, tmp / "labels") == []


def test_a_tampered_manifest_fails_validation(labelled):
    tmp, _, _ = labelled
    doc = build_manifest(tmp / "labels", "ds-v0.0-selftest-tests", git_sha="0" * 40)
    doc["notes"] = "tampered"
    assert any("manifest_hash" in e for e in validate_manifest(doc))


def test_a_synthetic_label_set_is_refused_from_a_participant_dataset(labelled):
    tmp, _, _ = labelled
    doc = build_manifest(tmp / "labels", "ds-v1.0", git_sha="0" * 40)
    assert doc["totals"]["n_label_sets"] == 0
    assert doc["refused"] and "cannot enter a participant dataset" in doc["refused"][0]["reason"]


def test_an_empty_participant_manifest_is_refused(labelled, tmp_path):
    tmp, _, _ = labelled
    doc = build_manifest(tmp / "labels", "ds-v1.0", git_sha="0" * 40)
    with pytest.raises(ValueError, match="refusing to write an empty PARTICIPANT"):
        write_manifest(doc, tmp_path)


def test_a_label_set_with_different_machinery_is_refused(labelled, tmp_path):
    """The versioning rule, machine-checked: a set produced by different rules / thresholds /
    smoother / tracker cannot join a dataset without a new labels_version."""
    tmp, _, _ = labelled
    other = tmp_path / "labels" / "synthetic-other"
    other.mkdir(parents=True)
    src = next((tmp / "labels").glob("*/"))
    for name in ("labels.jsonl", "tracks_reference.jsonl", "tracks_causal.jsonl",
                 LABEL_SET_FILENAME):
        (other / name).write_text((src / name).read_text(encoding="utf-8"), encoding="utf-8")
    doc = read_label_set(other / LABEL_SET_FILENAME)
    doc["session_id"] = "synthetic-other"
    doc["provenance"] = dict(doc["provenance"])
    doc["provenance"]["labels_hash"] = "sha256:" + "9" * 64
    from spacedrums.data.labels.schema import label_set_hash

    doc["set_hash"] = label_set_hash(doc)
    import json

    (other / LABEL_SET_FILENAME).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    manifest = build_manifest(tmp_path / "labels", "ds-v0.0-selftest-mix", git_sha="0" * 40,
                              label_dirs=[src, other])
    assert manifest["refused"]
    assert "labels_hash differs" in manifest["refused"][0]["reason"]


def test_manifest_round_trips_through_disk(labelled, tmp_path):
    tmp, _, _ = labelled
    doc = build_manifest(tmp / "labels", "ds-v0.0-selftest-tests", git_sha="0" * 40)
    path = write_manifest(doc, tmp_path)
    assert read_manifest(path)["manifest_hash"] == doc["manifest_hash"]


@pytest.mark.parametrize(
    "version, kind",
    [("ds-v1.0", "PARTICIPANT"), ("ds-v0.3-pilot", "PILOT"), ("ds-v0.0-selftest-x", "SELFTEST")],
)
def test_dataset_version_patterns_map_to_kinds(version, kind):
    assert dataset_kind(version) == kind


def test_an_unknown_dataset_version_is_refused():
    with pytest.raises(ValueError, match="dataset_version"):
        dataset_kind("ds-1.0")


def test_manifest_hash_ignores_only_itself_and_the_timestamp(labelled):
    tmp, _, _ = labelled
    doc = build_manifest(tmp / "labels", "ds-v0.0-selftest-tests", git_sha="0" * 40)
    altered = dict(doc)
    altered["notes"] = "x"
    assert manifest_hash(altered) != manifest_hash(doc)


# ----------------------------------------------------------------------------- dataset card


def test_the_card_reports_pending_where_there_is_nothing_to_report(labelled):
    tmp, _, result = labelled
    doc = build_manifest(tmp / "labels", "ds-v0.0-selftest-tests", git_sha="0" * 40)
    sets = [read_label_set(d / LABEL_SET_FILENAME) for d in (tmp / "labels").glob("*/")]
    card = dataset_card(doc, labels=result.labels, phys=phys_summary(sets))
    assert "PENDING" in card
    assert "no participant sessions exist" in card
    assert "no annotation pass has been performed" in card
    assert "geometric only" in card


def test_the_card_states_every_known_limitation(labelled):
    tmp, _, _ = labelled
    doc = build_manifest(tmp / "labels", "ds-v0.0-selftest-tests", git_sha="0" * 40)
    card = dataset_card(doc)
    for item in CARD_LIMITATIONS:
        assert item.split(".")[0][:40] in card


def test_the_card_states_the_versioning_rule_and_the_consent_scope(labelled):
    tmp, _, _ = labelled
    doc = build_manifest(tmp / "labels", "ds-v0.0-selftest-tests", git_sha="0" * 40)
    card = dataset_card(doc)
    assert "new `labels_version`" in card
    assert "Consent scope" in card
    assert "no release is made by Phase 07" in card


def test_the_card_shows_the_split_rationale_when_a_split_exists(labelled):
    tmp, _, _ = labelled
    from spacedrums.data.splits import Roster, build_split

    doc = build_manifest(tmp / "labels", "ds-v0.0-selftest-tests", git_sha="0" * 40)
    split, _ = build_split(
        Roster("ds-v0.0-selftest-tests", "labels-v1.0", SessionKind.SYNTHETIC,
               {f"SYNTHETIC-P{i:02d}": [f"s{i}"] for i in range(1, 9)}),
        seed=0,
    )
    card = dataset_card(doc, split=split)
    assert "P07-SPLIT-1" in card
    assert "TRAIN participants" in card


def test_phys_summary_without_audio_is_pending(labelled):
    tmp, _, _ = labelled
    sets = [read_label_set(d / LABEL_SET_FILENAME) for d in (tmp / "labels").glob("*/")]
    summary = phys_summary(sets)
    assert summary["available"] is False
    assert summary["n_paired"] == 0
    assert "PENDING" in summary["label"]
