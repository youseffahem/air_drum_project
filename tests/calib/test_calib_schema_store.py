"""Task 14.1: calib-v1 schema, semantic validation, hashing and the save/load round trip."""

import copy

import pytest
import yaml

from spacedrums.calib import CalibrationError, calibration_hash, load_calibration, save_calibration
from spacedrums.calib.schema import schema_errors, semantic_errors, validate_document
from spacedrums.calib.store import dump_calibration
from spacedrums.config import config_hash


def test_round_trip_is_lossless_and_lf_only(synthetic_calibration, tmp_path):
    calib, path = synthetic_calibration
    raw = path.read_bytes()
    assert b"\r" not in raw and raw.startswith(b"# calib-v1 calibration")
    again = load_calibration(path)
    assert again.hash == calib.hash == calibration_hash(again.doc) == config_hash(again.doc)
    copy_path = tmp_path / "copy.calib.yaml"
    assert save_calibration(again.doc, copy_path).hash == calib.hash
    assert copy_path.read_bytes() == raw


def test_valid_document_has_no_errors(synthetic_calibration):
    doc = synthetic_calibration[0].doc
    assert schema_errors(doc) == [] and semantic_errors(doc) == []


def test_hand_edited_zone_is_rejected(synthetic_calibration, tmp_path):
    doc = copy.deepcopy(synthetic_calibration[0].doc)
    doc["layout"]["zones"][1]["shape"]["center"][0] += 0.01
    doc["layout"]["zones"][1]["impact_surface"]["center"][0] += 0.01
    path = tmp_path / "edited.calib.yaml"
    path.write_text(dump_calibration(doc), encoding="utf-8")
    with pytest.raises(CalibrationError) as err:
        load_calibration(path)
    assert "zones_hash" in str(err.value) or "differ" in str(err.value)
    doc["layout"]["zones_hash"] = config_hash(doc["layout"]["zones"])  # even a consistent hash cannot hide it
    with pytest.raises(CalibrationError, match="template -> fit"):
        validate_document(doc)


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda d: d.pop("layout"), "schema"),
        (lambda d: d.update(extra=1), "schema"),
        (lambda d: d.update(schema_version="calib-v2"), "schema"),
        (lambda d: d["validation"].update(label="MEASURED"), "SYNTHETIC calibration cannot"),
        (lambda d: d["provenance"].update(user_tag=None), "user_tag"),
        (lambda d: d["settings"].update(strikes_per_zone=9), "settings_hash"),
        (lambda d: d["stick_prior"]["l_prior"].update(LEFT=0.31), "l_prior.LEFT"),
        (lambda d: d["layout"]["fit"].update(mode="FIXED"), "FIXED fit mode"),
        (lambda d: d["durations_s"].update(clock="t_mono"), "t_mono durations"),
        (lambda d: d["layout"]["template"]["zones"][0].update(sample_id="x"), "template.zones_hash"),
    ],
)
def test_inconsistent_documents_are_rejected(synthetic_calibration, mutate, match):
    doc = copy.deepcopy(synthetic_calibration[0].doc)
    mutate(doc)
    with pytest.raises(CalibrationError, match=match):
        validate_document(doc)


def test_replay_calibration_must_skip_validation(synthetic_calibration):
    doc = copy.deepcopy(synthetic_calibration[0].doc)
    doc["provenance"]["kind"] = "DEVELOPER_REPLAY"
    doc["validation"]["label"] = "MEASURED"
    doc["durations_s"]["clock"] = "replay"
    with pytest.raises(CalibrationError, match="replayed recording"):
        validate_document(doc)


def test_yaml_is_sorted_and_readable(synthetic_calibration):
    doc = yaml.safe_load(synthetic_calibration[1].read_text(encoding="utf-8"))
    assert list(doc) == sorted(doc)
    assert doc["schema_version"] == "calib-v1" and doc["validation"]["arm"] == "A"
