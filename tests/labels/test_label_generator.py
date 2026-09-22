"""TEST-LABEL-4 — the offline label generator end to end (Phase 07, Tasks 07.2 / 07.3).

Runs the real generator on a SYNTHETIC session recorded through the Phase 05/06 record path, and
checks what a downstream phase is allowed to assume: determinism, provenance, the separation of the
causal and reference trajectories, the impact definition, quarantine handling, and the fact that
nothing in a label is copied from the runtime pipeline.
"""

from __future__ import annotations

import json

import pytest
from label_helpers import GIT, SELFTEST_VERSION, labelled_session

from spacedrums.data.labels.generate import (
    generate_labels,
    read_label_set,
    read_labels,
    read_reference_track,
)
from spacedrums.data.labels.rules import Thresholds
from spacedrums.data.labels.schema import (
    CAUSAL_TRACK_FILENAME,
    LABEL_SET_FILENAME,
    LABELS_FILENAME,
    REFERENCE_TRACK_BANNER,
    REFERENCE_TRACK_FILENAME,
    RUNTIME_REFERENCE_BANNER,
    Interpolation,
    LabelClass,
    SmootherId,
)
from spacedrums.data.labels.smooth import ReferenceSmoother
from spacedrums.data.labels.validate import leakage_report, validate_label_dir
from spacedrums.timing.logger import read_record_stream


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p07-generator")
    return labelled_session(tmp, session_id="synthetic-generator")


# ----------------------------------------------------------------------------- artefacts


def test_generator_writes_all_four_artefacts(session):
    _, result, _ = session
    names = {p.name for p in result.written}
    assert names == {LABELS_FILENAME, REFERENCE_TRACK_FILENAME, CAUSAL_TRACK_FILENAME,
                     LABEL_SET_FILENAME}


def test_labels_validate_against_the_schema_and_the_session(session):
    session_dir, result, _ = session
    assert validate_label_dir(result.label_dir, session_dir=session_dir) == []


def test_label_set_counts_match_the_labels(session):
    _, result, _ = session
    doc = read_label_set(result.label_dir / LABEL_SET_FILENAME)
    assert doc["counts"]["total"] == len(result.labels)
    assert doc["counts"]["by_class"] == result.by_class()
    assert "SYNTHETIC" in doc["counts"]["label"]


# ----------------------------------------------------------------------------- determinism


def test_regenerating_reproduces_identical_labels_and_hash(tmp_path):
    a_dir, a, _ = labelled_session(tmp_path / "a", session_id="synthetic-determinism")
    b = generate_labels(a_dir, tmp_path / "b" / "labels", dataset_version=SELFTEST_VERSION,
                        git_sha=GIT, generated_at="2026-09-22T12:00:00+03:00")
    assert (a.label_dir / LABELS_FILENAME).read_bytes() == (b.label_dir / LABELS_FILENAME).read_bytes()
    assert a.label_set["set_hash"] == b.label_set["set_hash"]


def test_a_changed_threshold_changes_the_labels_hash(tmp_path):
    _, a, _ = labelled_session(tmp_path / "a", session_id="synthetic-th-a")
    _, b, _ = labelled_session(tmp_path / "b", session_id="synthetic-th-b",
                               thresholds=Thresholds(stop_speed_max=0.2))
    assert a.labels and b.labels
    assert (a.labels[0]["provenance"]["labels_hash"]
            != b.labels[0]["provenance"]["labels_hash"])


def test_a_changed_smoother_changes_the_labels_hash(tmp_path):
    _, a, _ = labelled_session(tmp_path / "a", session_id="synthetic-sm-a")
    _, b, _ = labelled_session(tmp_path / "b", session_id="synthetic-sm-b",
                               smoother=ReferenceSmoother(SmootherId.SAVGOL_CENTRED))
    assert (a.labels[0]["provenance"]["labels_hash"]
            != b.labels[0]["provenance"]["labels_hash"])


# ----------------------------------------------------------------------------- provenance


def test_every_label_carries_the_full_provenance(session):
    _, result, _ = session
    for rec in result.labels:
        p = rec["provenance"]
        assert p["rules_version"] and p["rules_hash"].startswith("sha256:")
        assert p["smoother_id"] in {str(s) for s in SmootherId}
        assert p["interpolation"] in {str(i) for i in Interpolation}
        assert p["tracker_id"] and p["geometry_version"]
        assert p["reference_track_ref"] == REFERENCE_TRACK_FILENAME
        assert p["causal_track_ref"] == CAUSAL_TRACK_FILENAME
        assert p["git_sha"] == GIT


def test_every_label_is_marked_non_causal(session):
    _, result, _ = session
    assert all(rec["causal"] is False for rec in result.labels)
    assert all(rec["runtime_reference"]["label"] == RUNTIME_REFERENCE_BANNER
               for rec in result.labels)


def test_labeller_id_names_the_generator_not_a_person(session):
    _, result, _ = session
    assert all(rec["labeller_id"].startswith("generator:") for rec in result.labels)
    assert all(rec["review"]["reviewer_id"] is None for rec in result.labels)
    assert all(rec["qc_status"] == "PENDING_REVIEW" for rec in result.labels)


# ----------------------------------------------------------------------------- separation


def test_reference_and_causal_tracks_are_separate_files_with_distinct_kinds(session):
    _, result, _ = session
    report = leakage_report(result.label_dir)
    assert report["ok"]
    assert report["causal_record_type"] == "TrackState"
    assert report["reference_is_record_stream"] is False


def test_the_reference_track_header_declares_itself_non_causal(session):
    _, result, _ = session
    headers, samples = read_reference_track(result.label_dir / REFERENCE_TRACK_FILENAME)
    assert headers
    for hand, header in headers.items():
        assert header["causal"] is False
        assert header["kind"] == "ReferenceTrack"
        assert header["label"] == REFERENCE_TRACK_BANNER
        assert header["n_samples"] == len(samples[hand])


def test_the_causal_track_is_an_unchanged_copy_of_the_session_stream(session):
    session_dir, result, _ = session
    a = (session_dir / "records" / "TrackState.jsonl").read_text(encoding="utf-8")
    b = (result.label_dir / CAUSAL_TRACK_FILENAME).read_text(encoding="utf-8")
    assert a == b


def test_reference_positions_differ_from_the_causal_ones(session):
    """If the two trajectories were identical the labels would be defined by the causal tracker's
    noise, which is exactly what Task 07.2 forbids."""
    _, result, _ = session
    _, samples = read_reference_track(result.label_dir / REFERENCE_TRACK_FILENAME)
    causal = {
        (r["hand_id"], r["frame_id"]): r["tip_filtered"]
        for r in read_record_stream(result.label_dir / CAUSAL_TRACK_FILENAME)[1]
        if r["tip_filtered"]
    }
    compared = [
        (s.p, causal[(hand, s.frame_id)])
        for hand, hand_samples in samples.items()
        for s in hand_samples
        if (hand, s.frame_id) in causal
    ]
    assert compared, "the session should have overlapping causal and reference samples"
    assert any(list(ref) != list(cau) for ref, cau in compared)


# ----------------------------------------------------------------------------- impact definition


def test_positive_labels_match_the_synthetic_analytic_crossings(session):
    """The generator's impact definition is the Phase 04 entry test on the reference trajectory.
    On a SYNTHETIC session the analytic crossing time is known, so the labels can be checked
    against it — the only ground truth available without recordings."""
    _, result, extra = session
    truth = sorted(t["t_cross"] for t in extra["truth"])
    positives = sorted(r["t_impact_est"] for r in result.labels
                       if r["label_class"] == str(LabelClass.POSITIVE))
    assert len(positives) == len(truth), f"{len(positives)} positives vs {len(truth)} synthetic truths"
    for got, want in zip(positives, truth, strict=True):
        assert got == pytest.approx(want, abs=1 / 30), "label within one frame of the analytic crossing"


def test_positives_carry_position_velocity_and_the_gt_intensity_proxy(session):
    _, result, _ = session
    for rec in result.labels:
        if rec["label_class"] != str(LabelClass.POSITIVE):
            continue
        assert rec["t_impact_est"] == rec["t_event"]
        assert rec["impact_position"] and rec["crossing_velocity"]
        assert rec["intensity_proxy_gt"] is not None
        assert rec["episode_id"]
        assert rec["intensity_secondary"]["peak_speed_pre"] is not None


def test_negatives_never_carry_an_impact_time_or_intensity(session):
    _, result, _ = session
    for rec in result.labels:
        if rec["label_class"].startswith("NEG_"):
            assert rec["t_impact_est"] is None
            assert rec["intensity_proxy_gt"] is None
            assert rec["t_impact_phys"] is None


def test_frame_references_bracket_the_event(session):
    _, result, _ = session
    frames = {
        json.loads(line)["frame_id"]: json.loads(line)["t_capture"]
        for line in (session[0] / "frames.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    for rec in result.labels:
        if rec["level"] != "EVENT":
            continue
        before, after = rec["frames"]["before_event"], rec["frames"]["after_event"]
        assert before in frames and after in frames
        assert frames[before] - 1e-9 <= rec["t_event"] <= frames[after] + 1e-9


def test_one_positive_per_episode(session):
    _, result, _ = session
    episodes = [r["episode_id"] for r in result.labels
                if r["label_class"] == str(LabelClass.POSITIVE)]
    assert len(episodes) == len(set(episodes))


# ----------------------------------------------------------------------------- kind gating


def test_a_synthetic_session_cannot_be_labelled_into_a_participant_dataset(tmp_path):
    from data_helpers import make_session

    session_dir, _, _ = make_session(tmp_path / "raw", session_id="synthetic-gate")
    with pytest.raises(ValueError, match="cannot enter a participant dataset"):
        generate_labels(session_dir, tmp_path / "labels", dataset_version="ds-v1.0", git_sha=GIT)


def test_an_unknown_dataset_version_is_refused(tmp_path):
    from data_helpers import make_session

    session_dir, _, _ = make_session(tmp_path / "raw", session_id="synthetic-badver")
    with pytest.raises(ValueError, match="dataset_version"):
        generate_labels(session_dir, tmp_path / "labels", dataset_version="nonsense", git_sha=GIT)


# ----------------------------------------------------------------------------- runtime reference


def test_runtime_reference_is_carried_but_never_becomes_ground_truth(session):
    _, result, _ = session
    for rec in result.labels:
        rt = rec["runtime_reference"]
        assert rt["label"] == RUNTIME_REFERENCE_BANNER
        if rt["causal_t_impact_est"] is not None and rec["t_impact_est"] is not None:
            assert rt["causal_t_impact_est"] != rec["t_impact_est"]


def test_labels_are_read_back_identically(session):
    _, result, _ = session
    assert read_labels(result.label_dir / LABELS_FILENAME) == result.labels
