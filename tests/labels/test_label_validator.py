"""TEST-LABEL-5 — the label validator and its negative cases (Phase 07, Task 07.7).

A validator that never fails is not evidence, so every check has a corruption that triggers it.
The corruptions are applied to a copy of a real generated SYNTHETIC label set; none of them is
written back to disk.
"""

from __future__ import annotations

import copy
import json

import pytest
from label_helpers import labelled_session

from spacedrums.config import load_config
from spacedrums.data.labels.schema import (
    CAUSAL_TRACK_FILENAME,
    LABEL_SET_FILENAME,
    LABELS_FILENAME,
    REFERENCE_TRACK_FILENAME,
    label_set_hash,
)
from spacedrums.data.labels.validate import (
    VIOLATION_CODES,
    Violation,
    leakage_report,
    validate_label_dir,
    validate_labels,
)
from spacedrums.data.metadata import SessionMetadata


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p07-validator")
    session_dir, result, _ = labelled_session(tmp, session_id="synthetic-validator")
    meta = SessionMetadata.read(session_dir)
    zone_ids = [z["zone_id"] for z in load_config(session_dir / "config.snapshot.yaml")["zones"]]
    frame_ids = [
        json.loads(line)["frame_id"]
        for line in (session_dir / "frames.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    label_set = json.loads((result.label_dir / LABEL_SET_FILENAME).read_text(encoding="utf-8"))
    return session_dir, result, meta, zone_ids, frame_ids, label_set


def _run(clean, mutate):
    session_dir, result, meta, zone_ids, frame_ids, label_set = clean
    labels = copy.deepcopy(result.labels)
    ls = copy.deepcopy(label_set)
    labels, ls = mutate(labels, ls)
    return {v.code for v in validate_labels(labels, ls, meta=meta, zone_ids=zone_ids,
                                            frame_ids=frame_ids)}


def _event(labels):
    return next(r for r in labels if r["level"] == "EVENT")


def _positive(labels):
    return next(r for r in labels if r["label_class"] == "POSITIVE")


# ----------------------------------------------------------------------------- clean baseline


def test_a_generated_label_set_is_clean(clean):
    session_dir, result, *_ = clean
    assert validate_label_dir(result.label_dir, session_dir=session_dir) == []


def test_every_violation_code_is_declared():
    assert len(set(VIOLATION_CODES)) == len(VIOLATION_CODES)
    with pytest.raises(ValueError, match="unknown violation code"):
        from spacedrums.data.labels.validate import _v

        _v([], "NOT_A_CODE", None, "x")


def test_violation_renders_readably():
    v = Violation("ZONE_UNKNOWN", "id-1", "bad zone")
    assert str(v) == "ZONE_UNKNOWN [id-1]: bad zone"
    assert v.to_dict()["code"] == "ZONE_UNKNOWN"


# ----------------------------------------------------------------------------- time / frames


def test_invalid_timestamp_outside_the_session_is_caught(clean):
    def mutate(labels, ls):
        rec = _event(labels)
        rec["t_event"] += 10_000.0
        if rec["t_impact_est"] is not None:
            rec["t_impact_est"] = rec["t_event"]
        return labels, ls

    assert {"TIME_OUT_OF_SESSION", "FUTURE_LEAKAGE"} & _run(clean, mutate)


def test_an_inverted_interval_is_caught(clean):
    def mutate(labels, ls):
        rec = next(r for r in labels if r["level"] == "INTERVAL")
        rec["t_start"], rec["t_end"] = rec["t_end"], rec["t_start"] - 1.0
        return labels, ls

    assert "TIME_ORDER" in _run(clean, mutate)


def test_impact_time_must_equal_the_event_instant(clean):
    def mutate(labels, ls):
        rec = _positive(labels)
        rec["t_impact_est"] = rec["t_event"] + 0.001
        return labels, ls

    assert "IMPACT_TIME_MISMATCH" in _run(clean, mutate)


def test_unknown_frame_reference_is_caught(clean):
    def mutate(labels, ls):
        _event(labels)["frames"]["before_event"] = 10_000_000
        return labels, ls

    assert "FRAME_UNKNOWN" in _run(clean, mutate)


def test_reversed_frame_bracket_is_caught(clean):
    def mutate(labels, ls):
        f = _event(labels)["frames"]
        f["before_event"], f["after_event"] = f["after_event"], f["before_event"]
        return labels, ls

    assert "FRAME_ORDER" in _run(clean, mutate)


# ----------------------------------------------------------------------------- identity


def test_impossible_zone_id_is_caught(clean):
    def mutate(labels, ls):
        next(r for r in labels if r["zone_id"])["zone_id"] = "not_a_zone"
        return labels, ls

    assert "ZONE_UNKNOWN" in _run(clean, mutate)


def test_unknown_segment_is_caught(clean):
    def mutate(labels, ls):
        next(r for r in labels if r["segment_id"])["segment_id"] = "s99_not_a_segment"
        return labels, ls

    assert "SEGMENT_UNKNOWN" in _run(clean, mutate)


def test_session_and_participant_must_match_the_label_set(clean):
    def mutate(labels, ls):
        labels[0]["session_id"] = "some-other-session"
        labels[0]["participant_id"] = "SOMEONE"
        return labels, ls

    codes = _run(clean, mutate)
    assert "SESSION_MISMATCH" in codes and "PARTICIPANT_MISMATCH" in codes


def test_duplicate_label_id_is_caught(clean):
    def mutate(labels, ls):
        clone = copy.deepcopy(labels[0])
        labels.append(clone)
        ls["counts"]["by_class"][clone["label_class"]] += 1
        ls["counts"]["total"] += 1
        ls["set_hash"] = label_set_hash(ls)
        return labels, ls

    assert "LABEL_ID_DUPLICATE" in _run(clean, mutate)


# ----------------------------------------------------------------------------- episodes


def test_two_positives_in_one_episode_are_caught(clean):
    def mutate(labels, ls):
        pos = [r for r in labels if r["label_class"] == "POSITIVE"]
        pos[1]["episode_id"] = pos[0]["episode_id"]
        return labels, ls

    assert "EPISODE_DUPLICATE" in _run(clean, mutate)


def test_two_positives_of_the_same_hand_and_zone_too_close_are_a_conflict(clean):
    def mutate(labels, ls):
        pos = _positive(labels)
        clone = copy.deepcopy(pos)
        clone["label_id"] = pos["label_id"] + "-dup"
        clone["episode_id"] = pos["episode_id"] + "-dup"
        clone["t_event"] = pos["t_event"] + 0.001
        clone["t_impact_est"] = clone["t_event"]
        labels.append(clone)
        ls["counts"]["by_class"]["POSITIVE"] += 1
        ls["counts"]["total"] += 1
        ls["set_hash"] = label_set_hash(ls)
        return labels, ls

    assert "POSITIVE_CONFLICT" in _run(clean, mutate)


# ----------------------------------------------------------------------------- provenance


def test_provenance_drift_between_a_label_and_its_set_is_caught(clean):
    def mutate(labels, ls):
        labels[0]["provenance"] = dict(labels[0]["provenance"])
        labels[0]["provenance"]["smoother_id"] = "savgol-centred-v1"
        return labels, ls

    assert "PROVENANCE_MISMATCH" in _run(clean, mutate)


def test_version_drift_is_caught(clean):
    def mutate(labels, ls):
        labels[0]["labels_version"] = "labels-v9.9"
        return labels, ls

    assert "VERSION_MISMATCH" in _run(clean, mutate)


def test_a_labels_hash_that_does_not_match_its_machinery_is_caught(clean):
    def mutate(labels, ls):
        ls["provenance"] = dict(ls["provenance"])
        ls["provenance"]["labels_hash"] = "sha256:" + "1" * 64
        ls["set_hash"] = label_set_hash(ls)
        return labels, ls

    assert "LABELS_HASH_MISMATCH" in _run(clean, mutate)


def test_a_tampered_set_hash_is_caught(clean):
    def mutate(labels, ls):
        ls["notes"] = "tampered"
        return labels, ls

    assert "SET_HASH_MISMATCH" in _run(clean, mutate)


def test_a_synthetic_set_relabelled_participant_is_refused(clean):
    def mutate(labels, ls):
        ls["source_kind"] = "PARTICIPANT"
        ls["set_hash"] = label_set_hash(ls)
        return labels, ls

    assert "SOURCE_KIND_NOT_ADMISSIBLE" in _run(clean, mutate)


def test_count_drift_between_labels_and_the_set_is_caught(clean):
    def mutate(labels, ls):
        ls["counts"]["by_class"] = {"POSITIVE": 999}
        ls["set_hash"] = label_set_hash(ls)
        return labels, ls

    assert "COUNTS_MISMATCH" in _run(clean, mutate)


# ----------------------------------------------------------------------------- causality


def test_the_causal_flag_cannot_be_flipped(clean):
    def mutate(labels, ls):
        labels[0]["causal"] = True
        return labels, ls

    assert {"SCHEMA_INVALID", "CAUSAL_FLAG"} & _run(clean, mutate)


def test_the_runtime_banner_cannot_be_removed(clean):
    def mutate(labels, ls):
        labels[0]["runtime_reference"]["label"] = "ground truth"
        return labels, ls

    assert {"SCHEMA_INVALID", "RUNTIME_BANNER"} & _run(clean, mutate)


def test_copying_the_runtime_candidate_time_into_ground_truth_is_caught(clean):
    def mutate(labels, ls):
        rec = _positive(labels)
        rec["runtime_reference"]["causal_t_impact_est"] = rec["t_impact_est"]
        return labels, ls

    assert "RUNTIME_TIME_COPIED" in _run(clean, mutate)


# ----------------------------------------------------------------------------- physical GT


def test_physical_ground_truth_outside_a_pad_segment_is_refused():
    """Hand-built PILOT-shaped fixture: the schema forbids ``t_impact_phys`` on SYNTHETIC material,
    so the ``has_phys_gt`` invariant itself can only be exercised on a pilot/participant-shaped
    record. This dict is a **test fixture that must be rejected** — it is never written to disk,
    never enters a dataset, and is not participant data."""
    from spacedrums.data.labels.validate import validate_labels as run

    base = json.loads(
        (__import__("pathlib").Path("schemas/examples/label-record.valid.example.json"))
        .read_text(encoding="utf-8")
    )
    rec = copy.deepcopy(base)
    rec["source_kind"] = "PILOT"
    rec["dataset_version"] = "ds-v0.1-pilot"
    rec["t_impact_phys"] = rec["t_impact_est"] + 0.004
    rec["phys"] = {
        "onset_index": 0,
        "onset_t_mono": rec["t_impact_phys"],
        "residual_s": 0.004,
        "mic_latency_bound_s": 0.005,
        "pad_zone_id": rec["zone_id"],
        "sync_residual_rms_s": None,
    }
    label_set = {
        "labels_version": rec["labels_version"],
        "dataset_version": rec["dataset_version"],
        "source_kind": "PILOT",
        "session_id": rec["session_id"],
        "participant_id": rec["participant_id"],
        "provenance": rec["provenance"],
        "counts": {"by_class": {rec["label_class"]: 1}},
        "set_hash": "sha256:" + "0" * 64,
    }
    codes = {v.code for v in run([rec], label_set)}
    # The label set stub is deliberately incomplete, so the set-level checks fire too; what matters
    # is that the per-strike physical-GT invariant is among the violations.
    assert "PHYS_INVARIANT" in codes


# ----------------------------------------------------------------------------- directory level


def test_a_missing_reference_track_is_caught(clean):
    session_dir, result, *_ = clean
    path = result.label_dir / REFERENCE_TRACK_FILENAME
    saved = path.read_bytes()
    try:
        path.unlink()
        codes = {v.code for v in validate_label_dir(result.label_dir, session_dir=session_dir)}
        assert "REFERENCE_TRACK_MISSING" in codes
    finally:
        path.write_bytes(saved)


def test_a_missing_causal_track_is_caught(clean):
    session_dir, result, *_ = clean
    path = result.label_dir / CAUSAL_TRACK_FILENAME
    saved = path.read_bytes()
    try:
        path.unlink()
        codes = {v.code for v in validate_label_dir(result.label_dir, session_dir=session_dir)}
        assert "CAUSAL_TRACK_MISSING" in codes
    finally:
        path.write_bytes(saved)


def test_changed_session_metadata_is_detected_as_provenance_drift(clean):
    session_dir, result, *_ = clean
    meta_path = session_dir / "metadata.json"
    saved = meta_path.read_bytes()
    try:
        doc = json.loads(saved.decode("utf-8"))
        doc["operator_notes"] = "edited after labelling"
        meta_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        codes = {v.code for v in validate_label_dir(result.label_dir, session_dir=session_dir)}
        assert "PROVENANCE_MISMATCH" in codes
    finally:
        meta_path.write_bytes(saved)


def test_leakage_report_flags_a_reference_track_written_as_a_record_stream(clean, tmp_path):
    _, result, *_ = clean
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / CAUSAL_TRACK_FILENAME).write_text(
        (result.label_dir / CAUSAL_TRACK_FILENAME).read_text(encoding="utf-8"), encoding="utf-8"
    )
    (fake / REFERENCE_TRACK_FILENAME).write_text(
        (result.label_dir / CAUSAL_TRACK_FILENAME).read_text(encoding="utf-8"), encoding="utf-8"
    )
    report = leakage_report(fake)
    assert report["reference_is_record_stream"] is True
    assert report["ok"] is False


def test_labels_file_is_not_a_record_stream(clean):
    _, result, *_ = clean
    first = (result.label_dir / LABELS_FILENAME).read_text(encoding="utf-8").splitlines()[0]
    assert "record_type" not in json.loads(first)
