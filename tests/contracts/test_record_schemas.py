"""TEST-SCHEMA-1 — record contracts (Phase 01, Task 01.2; docs/architecture/contracts.md section 5).

For every record schema: the schema is valid Draft 2020-12; the valid example is
accepted; removing any required field is rejected; an unknown field is rejected;
a non-numeric t_capture is rejected. Then the conditional rules that encode
contract semantics (source/status/kind dependent nullability) are checked.
"""

from __future__ import annotations

import copy

import pytest
from conftest import RECORD_SCHEMAS, is_valid

CARRIES_T_CAPTURE = [s for s in RECORD_SCHEMAS if s not in ("audio-event", "record-stream-header")]


@pytest.mark.parametrize("stem", RECORD_SCHEMAS)
def test_schema_is_valid_and_example_accepted(validator, example, stem):
    v = validator(stem)  # check_schema runs inside the fixture
    errs = list(v.iter_errors(example(stem)))
    assert not errs, [e.message for e in errs]


@pytest.mark.parametrize("stem", RECORD_SCHEMAS)
def test_every_required_field_is_enforced(validator, schemas, example, stem):
    v = validator(stem)
    for field in schemas[stem]["required"]:
        broken = copy.deepcopy(example(stem))
        del broken[field]
        assert not is_valid(v, broken), f"{stem}: missing '{field}' was accepted"


@pytest.mark.parametrize("stem", RECORD_SCHEMAS)
def test_unknown_field_rejected(validator, example, stem):
    v = validator(stem)
    extra = copy.deepcopy(example(stem))
    extra["not_in_contract"] = 1
    assert not is_valid(v, extra)


@pytest.mark.parametrize("stem", CARRIES_T_CAPTURE)
def test_t_capture_must_be_numeric_seconds(validator, example, stem):
    v = validator(stem)
    wrong = copy.deepcopy(example(stem))
    wrong["t_capture"] = "12345 ms"
    assert not is_valid(v, wrong)
    absent = copy.deepcopy(example(stem))
    del absent["t_capture"]
    assert not is_valid(v, absent)


@pytest.mark.parametrize("stem", RECORD_SCHEMAS)
def test_schema_version_is_pinned(validator, example, stem):
    v = validator(stem)
    wrong = copy.deepcopy(example(stem))
    wrong["schema_version"] = "0.9"
    assert not is_valid(v, wrong)


# --- semantic conditionals ---------------------------------------------------


def test_hand_id_enum_is_closed_in_v1(validator, example):
    v = validator("track-state")
    doc = copy.deepcopy(example("track-state"))
    doc["hand_id"] = "LEFT_FOOT"  # OOS-REF:REQ-207 reserved; needs a schema bump
    assert not is_valid(v, doc)


def test_point2_has_exactly_two_components(validator, example):
    v = validator("stick-observation")
    doc = copy.deepcopy(example("stick-observation"))
    doc["tip"] = [0.5, 0.5, 0.1]  # depth is not a V1 coordinate (REQ-206)
    assert not is_valid(v, doc)


def test_hand_present_requires_landmarks(validator, example):
    v = validator("hand-observation")
    doc = copy.deepcopy(example("hand-observation"))
    doc["landmarks"] = None
    assert not is_valid(v, doc)
    absent = copy.deepcopy(example("hand-observation"))
    absent.update(present=False, landmarks=None, landmark_visibility=None, bbox=None, handedness_score=None)
    assert is_valid(v, absent)


def test_landmark_count_is_21(validator, example):
    v = validator("hand-observation")
    doc = copy.deepcopy(example("hand-observation"))
    doc["landmarks"] = doc["landmarks"][:20]
    assert not is_valid(v, doc)


def test_track_state_invalid_has_no_position(validator, example):
    v = validator("track-state")
    doc = copy.deepcopy(example("track-state"))
    doc.update(status="INVALID")  # tip_filtered still set -> contradiction
    assert not is_valid(v, doc)
    doc.update(
        tip_filtered=None,
        tip_velocity=None,
        tip_acceleration=None,
        reset_reason="GAP_EXCEEDED",
        history_ref=None,
    )
    assert is_valid(v, doc)


def test_track_state_valid_requires_position(validator, example):
    v = validator("track-state")
    doc = copy.deepcopy(example("track-state"))
    doc["tip_filtered"] = None
    assert not is_valid(v, doc)


def test_reactive_candidate_has_est_not_pred(validator, example):
    v = validator("strike-candidate")
    doc = copy.deepcopy(example("strike-candidate"))
    doc.update(source="REACTIVE")  # still carries t_impact_pred/tti -> reject
    assert not is_valid(v, doc)
    doc.update(t_impact_pred=None, tti=None, t_impact_est=12.40, anticipator_id=None)
    assert is_valid(v, doc)


def test_anticipatory_candidate_requires_pred_and_tti(validator, example):
    v = validator("strike-candidate")
    for source in ("RULE", "MODEL"):
        doc = copy.deepcopy(example("strike-candidate"))
        doc.update(source=source, t_impact_pred=None)
        assert not is_valid(v, doc), source


def test_trajectory_prediction_positions_required_aux_nullable(validator, example):
    v = validator("trajectory-prediction")
    doc = copy.deepcopy(example("trajectory-prediction"))
    doc["positions"] = []
    assert not is_valid(v, doc)  # primary output cannot be empty
    doc = copy.deepcopy(example("trajectory-prediction"))
    doc["aux"]["tti"] = 0.05
    doc["aux"]["zone_logits"] = [0.1, 0.9]
    doc["aux"]["zone_ids"] = ["snare", "hihat"]
    assert is_valid(v, doc)


def test_model_hash_format(validator, example):
    v = validator("trajectory-prediction")
    doc = copy.deepcopy(example("trajectory-prediction"))
    doc["model_hash"] = "abc123"
    assert not is_valid(v, doc)
    doc["model_hash"] = "sha256:" + "a" * 64
    assert is_valid(v, doc)


def test_timing_record_kind_frame_has_no_strike(validator, example):
    v = validator("timing-record")
    doc = copy.deepcopy(example("timing-record"))
    doc.update(kind="FRAME")  # strike_id still set -> reject
    assert not is_valid(v, doc)
    doc.update(strike_id=None, hand_id=None)
    assert is_valid(v, doc)


def test_timing_record_external_measurements_default_null(example):
    doc = example("timing-record")
    # The example must not pretend an external measurement exists (integrity I-1/I-6).
    assert doc["t_audio_out"] is None
    assert doc["t_acoustic_onset"] is None
    assert doc["t_impact_phys"] is None


def test_stream_header_units_are_pinned(validator, example):
    v = validator("record-stream-header")
    for key, bad in (("time", "ms"), ("clock", "wall"), ("position", "px"), ("angle", "deg")):
        doc = copy.deepcopy(example("record-stream-header"))
        doc["units"][key] = bad
        assert not is_valid(v, doc), key


def test_committed_strike_arm_and_shadow(validator, example):
    v = validator("committed-strike")
    doc = copy.deepcopy(example("committed-strike"))
    doc["arm"] = "NA"  # NA is an experiment-log value, not a live arm
    assert not is_valid(v, doc)
    doc.update(source="MODEL", arm="C-GRU", shadow=True)
    assert is_valid(v, doc)


def test_committed_strike_source_arm_invariant(validator, example):
    """Gate-review addition (2026-09-21): source and arm must agree (ADR-0008)."""
    v = validator("committed-strike")
    for source, arm, ok in (
        ("REACTIVE", "A", True),
        ("REACTIVE", "B", False),
        ("RULE", "B", True),
        ("RULE", "C-GBDT", False),
        ("MODEL", "C-TCN", True),
        ("MODEL", "A", False),
    ):
        doc = copy.deepcopy(example("committed-strike"))
        doc.update(source=source, arm=arm)
        assert is_valid(v, doc) is ok, (source, arm)


def test_derivation_direct_head_is_model_only(validator, example):
    """Gate-review addition (2026-09-21): DIRECT_HEAD is a diagnostic path for MODEL sources only."""
    v = validator("strike-candidate")
    doc = copy.deepcopy(example("strike-candidate"))  # source RULE
    doc["derivation"] = "DIRECT_HEAD"
    assert not is_valid(v, doc)
    doc.update(source="MODEL")
    assert is_valid(v, doc)
    doc = copy.deepcopy(example("strike-candidate"))
    doc.update(source="REACTIVE", t_impact_pred=None, tti=None, t_impact_est=12.4, anticipator_id=None)
    doc["derivation"] = "DIRECT_HEAD"
    assert not is_valid(v, doc)
    vc = validator("committed-strike")
    doc = copy.deepcopy(example("committed-strike"))  # source RULE / arm B
    doc["derivation"] = "DIRECT_HEAD"
    assert not is_valid(vc, doc)


def test_direct_prediction_is_diagnostic_and_model_only(validator, example):
    """Gate-review addition (2026-09-21): DirectPrediction requires a model hash and a sanctioned mode."""
    v = validator("direct-prediction")
    doc = copy.deepcopy(example("direct-prediction"))
    doc["model_hash"] = None  # rule-based anticipators have no direct mode
    assert not is_valid(v, doc)
    doc = copy.deepcopy(example("direct-prediction"))
    doc["diagnostic_mode"] = "LIVE"
    assert not is_valid(v, doc)


def test_trajectory_sparse_offsets(validator, example):
    """Gate-review addition (2026-09-21): sparse horizons are explicit, never interpolated."""
    v = validator("trajectory-prediction")
    doc = copy.deepcopy(example("trajectory-prediction"))
    doc["positions"] = [[0.63, 0.88], [0.64, 0.98]]
    doc["velocities"] = None
    doc["K"] = 2
    doc["t_offsets_s"] = [0.1, 0.2]
    assert is_valid(v, doc)
    doc["t_offsets_s"] = [0.0, 0.2]  # offsets must be strictly positive
    assert not is_valid(v, doc)


def test_audio_event_late_is_non_negative(validator, example):
    v = validator("audio-event")
    doc = copy.deepcopy(example("audio-event"))
    doc["audio_late_s"] = -0.001
    assert not is_valid(v, doc)
