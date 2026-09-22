"""TEST-SCHEMA-1 extension — the Phase 07 label and dataset schemas.

Same shape as the Phase 01/06 schema tests: the schema is valid Draft 2020-12, its example is
accepted, removing any required field is rejected, an unknown field is rejected, the pinned
``schema_version`` is enforced, and each schema's own semantic conditionals hold.

The conditionals that matter most here are the ones that keep the dataset honest:
a SYNTHETIC or DEV CAPTURE artefact cannot carry a participant dataset version or physical ground
truth; a negative cannot carry an impact time; an adjusted label must keep its original; a frozen
split must pass every leakage check.
"""

from __future__ import annotations

import copy

import pytest

LABEL_SCHEMAS = ["label-record", "reference-track", "label-set", "label-review", "split-file",
                 "dataset-manifest"]


def is_valid(v, instance) -> bool:
    return not list(v.iter_errors(instance))


# ----------------------------------------------------------------------------- generic


@pytest.mark.parametrize("stem", LABEL_SCHEMAS)
def test_schema_is_valid_draft_2020_12_and_accepts_its_example(stem, validator, example):
    assert is_valid(validator(stem), example(stem))


@pytest.mark.parametrize("stem", LABEL_SCHEMAS)
def test_removing_any_required_field_is_rejected(stem, validator, example, schemas):
    v, doc = validator(stem), example(stem)
    for field in schemas[stem]["required"]:
        broken = copy.deepcopy(doc)
        broken.pop(field, None)
        assert not is_valid(v, broken), f"{stem}: missing {field} must be rejected"


@pytest.mark.parametrize("stem", LABEL_SCHEMAS)
def test_an_unknown_field_is_rejected(stem, validator, example):
    broken = copy.deepcopy(example(stem))
    broken["not_a_contract_field"] = 1
    assert not is_valid(validator(stem), broken)


@pytest.mark.parametrize("stem", LABEL_SCHEMAS)
def test_a_wrong_schema_version_is_rejected(stem, validator, example):
    broken = copy.deepcopy(example(stem))
    broken["schema_version"] = "2.0"
    assert not is_valid(validator(stem), broken)


@pytest.mark.parametrize("stem", LABEL_SCHEMAS)
def test_no_millisecond_key_names(stem, schemas):
    text = str(schemas[stem])
    assert "_ms" not in text.replace("_msg", "")


# ----------------------------------------------------------------------------- LabelRecord


def test_a_label_record_must_declare_itself_non_causal(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["causal"] = True
    assert not is_valid(validator("label-record"), broken)


def test_a_negative_cannot_carry_an_impact_time_or_intensity(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["label_class"] = "NEG_FAKE_SWING"
    assert not is_valid(validator("label-record"), broken), "t_impact_est set on a negative"


def test_a_positive_needs_a_zone_an_episode_and_an_intensity_proxy(validator, example):
    v = validator("label-record")
    for field in ("zone_id", "episode_id", "intensity_proxy_gt", "impact_position"):
        broken = copy.deepcopy(example("label-record"))
        broken[field] = None
        assert not is_valid(v, broken), f"POSITIVE without {field} must be rejected"


def test_an_interval_label_cannot_carry_an_event_instant(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["label_class"] = "NEG_TRACKING_LOSS"
    broken["level"] = "INTERVAL"
    assert not is_valid(validator("label-record"), broken)


def test_an_event_label_cannot_carry_interval_bounds(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["t_start"] = broken["t_event"]
    broken["t_end"] = broken["t_event"] + 1.0
    assert not is_valid(validator("label-record"), broken)


def test_a_synthetic_label_cannot_claim_a_participant_dataset_version(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["dataset_version"] = "ds-v1.0"
    assert not is_valid(validator("label-record"), broken)


def test_a_synthetic_label_cannot_carry_physical_ground_truth(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["t_impact_phys"] = broken["t_impact_est"]
    assert not is_valid(validator("label-record"), broken)


def test_physical_ground_truth_requires_the_phys_block(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["source_kind"] = "PILOT"
    broken["dataset_version"] = "ds-v0.1-pilot"
    broken["t_impact_phys"] = broken["t_impact_est"]
    broken["phys"] = None
    assert not is_valid(validator("label-record"), broken)


def test_an_excluded_label_needs_its_exclusion_id(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["excluded"] = True
    assert not is_valid(validator("label-record"), broken)


def test_an_exclusion_id_without_the_excluded_flag_is_rejected(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["exclusion_ref"] = "excl-x"
    assert not is_valid(validator("label-record"), broken)


def test_an_adjusted_label_must_keep_its_original_and_name_its_reviewer(validator, example):
    v = validator("label-record")
    broken = copy.deepcopy(example("label-record"))
    broken["review"]["adjusted"] = True
    broken["qc_status"] = "ADJUSTED"
    assert not is_valid(v, broken), "adjusted without original / reviewer must be rejected"
    broken["review"]["original"] = {
        "t_impact_est": broken["t_impact_est"],
        "t_event": broken["t_event"],
        "zone_id": broken["zone_id"],
        "label_class": broken["label_class"],
    }
    broken["review"]["reviewer_id"] = "A1"
    assert is_valid(v, broken)


def test_an_adjusted_label_cannot_stay_pending(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["review"]["adjusted"] = True
    broken["review"]["reviewer_id"] = "A1"
    broken["review"]["original"] = {
        "t_impact_est": broken["t_impact_est"], "t_event": broken["t_event"],
        "zone_id": broken["zone_id"], "label_class": broken["label_class"],
    }
    broken["qc_status"] = "PENDING_REVIEW"
    assert not is_valid(validator("label-record"), broken)


def test_an_unknown_label_class_or_rule_id_is_rejected(validator, example):
    v = validator("label-record")
    for field, value in (("label_class", "NOT_A_CLASS"), ("label_rule_id", "R1"),
                         ("qc_status", "MAYBE"), ("hand_id", "LEFT_FOOT")):
        broken = copy.deepcopy(example("label-record"))
        broken[field] = value
        assert not is_valid(v, broken), f"{field} = {value!r} must be rejected"


def test_a_three_component_impact_position_is_rejected(validator, example):
    broken = copy.deepcopy(example("label-record"))
    broken["impact_position"] = [0.1, 0.2, 0.3]
    assert not is_valid(validator("label-record"), broken)


def test_an_unknown_interpolation_or_smoother_is_rejected(validator, example):
    v = validator("label-record")
    broken = copy.deepcopy(example("label-record"))
    broken["provenance"]["interpolation"] = "CUBIC"
    assert not is_valid(v, broken)
    broken = copy.deepcopy(example("label-record"))
    broken["provenance"]["git_sha"] = "not-a-sha"
    assert not is_valid(v, broken)


# ----------------------------------------------------------------------------- ReferenceTrack


def test_a_reference_track_must_be_non_causal_and_keep_its_kind(validator, example):
    v = validator("reference-track")
    for field, value in (("causal", True), ("kind", "TrackState"),
                         ("method_id", "causal-kalman"), ("label", "fine")):
        broken = copy.deepcopy(example("reference-track"))
        broken[field] = value
        assert not is_valid(v, broken), f"reference track with {field} = {value!r} must be rejected"


def test_a_reference_track_in_the_wrong_units_is_rejected(validator, example):
    v = validator("reference-track")
    for key, value in (("time", "ms"), ("clock", "wall"), ("position", "px"),
                       ("velocity", "px_per_s")):
        broken = copy.deepcopy(example("reference-track"))
        broken["units"][key] = value
        assert not is_valid(v, broken)


def test_a_reference_sample_needs_its_hand_and_a_two_component_position(schemas, registry):
    import jsonschema

    sub = jsonschema.Draft202012Validator(
        {"$ref": schemas["reference-track"]["$id"] + "#/$defs/sample"}, registry=registry
    )
    good = {"hand_id": "RIGHT", "frame_id": 3, "t": 100.1, "p": [0.5, 0.5], "v": [0.0, 1.0],
            "quality": 0.8, "interpolated": False}
    assert is_valid(sub, good)
    for broken in ({**good, "p": [0.5, 0.5, 0.5]}, {**good, "quality": 1.5},
                   {k: v for k, v in good.items() if k != "hand_id"}):
        assert not is_valid(sub, broken)


# ----------------------------------------------------------------------------- LabelSet


def test_a_synthetic_label_set_cannot_claim_physical_ground_truth(validator, example):
    broken = copy.deepcopy(example("label-set"))
    broken["phys"]["available"] = True
    assert not is_valid(validator("label-set"), broken)


def test_an_unavailable_phys_block_needs_a_reason_and_no_numbers(validator, example):
    v = validator("label-set")
    broken = copy.deepcopy(example("label-set"))
    broken["phys"]["reason"] = None
    assert not is_valid(v, broken)
    broken = copy.deepcopy(example("label-set"))
    broken["phys"]["residual_bias_s"] = 0.004
    assert not is_valid(v, broken), "an unavailable pairing cannot report a bias"


def test_a_synthetic_label_set_cannot_claim_a_participant_dataset_version(validator, example):
    broken = copy.deepcopy(example("label-set"))
    broken["dataset_version"] = "ds-v1.0"
    assert not is_valid(validator("label-set"), broken)


# ----------------------------------------------------------------------------- LabelReviewEntry


def test_an_adjust_entry_needs_before_after_and_a_reason(validator, example):
    v = validator("label-review")
    for field in ("before", "after", "reason"):
        broken = copy.deepcopy(example("label-review"))
        broken[field] = None
        assert not is_valid(v, broken), f"ADJUST without {field} must be rejected"


def test_a_review_pass_outside_one_and_two_is_rejected(validator, example):
    v = validator("label-review")
    for value in (0, 3):
        broken = copy.deepcopy(example("label-review"))
        broken["pass"] = value
        assert not is_valid(v, broken)


def test_an_unknown_review_decision_is_rejected(validator, example):
    broken = copy.deepcopy(example("label-review"))
    broken["decision"] = "MAYBE"
    assert not is_valid(validator("label-review"), broken)


# ----------------------------------------------------------------------------- SplitFile


def test_a_frozen_split_must_pass_every_leakage_check(validator, example):
    broken = copy.deepcopy(example("split-file"))
    broken["frozen"] = True
    broken["frozen_at"] = "2026-09-22T12:00:00+03:00"
    broken["source_kind"] = "PARTICIPANT"
    broken["dataset_version"] = "ds-v1.0"
    broken["leakage_checks"]["all_passed"] = False
    assert not is_valid(validator("split-file"), broken)


def test_a_synthetic_split_can_never_be_frozen(validator, example):
    broken = copy.deepcopy(example("split-file"))
    broken["frozen"] = True
    broken["frozen_at"] = "2026-09-22T12:00:00+03:00"
    assert not is_valid(validator("split-file"), broken)


def test_a_synthetic_split_cannot_claim_a_participant_dataset_version(validator, example):
    broken = copy.deepcopy(example("split-file"))
    broken["dataset_version"] = "ds-v1.0"
    assert not is_valid(validator("split-file"), broken)


def test_an_unknown_split_kind_is_rejected(validator, example):
    broken = copy.deepcopy(example("split-file"))
    broken["split_kind"] = "RANDOM"
    assert not is_valid(validator("split-file"), broken)


# ----------------------------------------------------------------------------- DatasetManifest


def test_a_selftest_manifest_cannot_use_a_participant_version(validator, example):
    broken = copy.deepcopy(example("dataset-manifest"))
    broken["dataset_version"] = "ds-v1.0"
    assert not is_valid(validator("dataset-manifest"), broken)


def test_a_participant_manifest_cannot_use_a_selftest_version(validator, example):
    broken = copy.deepcopy(example("dataset-manifest"))
    broken["kind"] = "PARTICIPANT"
    assert not is_valid(validator("dataset-manifest"), broken)


def test_a_selftest_manifest_cannot_declare_a_frozen_split(validator, example):
    broken = copy.deepcopy(example("dataset-manifest"))
    broken["splits"]["frozen"] = True
    assert not is_valid(validator("dataset-manifest"), broken)


def test_the_manifest_records_which_files_are_causal(example):
    doc = example("dataset-manifest")
    for entry in doc["label_sets"]:
        kinds = {f["path"]: f["causal"] for f in entry["files"]}
        assert kinds.get("tracks_causal.jsonl") is True
        assert kinds.get("tracks_reference.jsonl") is False
        assert kinds.get("labels.jsonl") is False
