"""Phase 14 contracts (ADR-0037): calib-v1 schema, config 1.7 fields, SessionMetadata calibration fields."""

import copy
import json
from pathlib import Path

import pytest

from spacedrums.calib.schema import semantic_errors
from spacedrums.contracts import schema as contract_schema
from spacedrums.geometry import GEOMETRY_VERSION

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = json.loads((ROOT / "schemas/examples/calib-v1.valid.example.json").read_text(encoding="utf-8"))


def test_calib_example_is_valid_and_consistent():
    assert contract_schema.errors("calib-v1", EXAMPLE) == []
    assert semantic_errors(EXAMPLE) == []
    assert EXAMPLE["provenance"]["kind"] == "SYNTHETIC" and EXAMPLE["validation"]["label"] == "SYNTHETIC"
    assert EXAMPLE["app"]["geometry_version"] == GEOMETRY_VERSION


@pytest.mark.parametrize("field", sorted(contract_schema.load_schemas()["calib-v1"]["required"]))
def test_calib_required_fields(field):
    doc = copy.deepcopy(EXAMPLE)
    del doc[field]
    assert contract_schema.errors("calib-v1", doc)


def test_calib_rules_in_the_schema():
    for path, value in (
        (("layout", "checks", "overlap", "passed"), False),
        (("validation", "arm"), "B"),
        (("stick_prior", "units"), "PX"),
        (("schema_version",), "calib-v2"),
        (("provenance", "user_tag"), "Real Name"),
    ):
        doc = copy.deepcopy(EXAMPLE)
        target = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        assert contract_schema.errors("calib-v1", doc), path


def test_config_schema_1_7_fields():
    cfg_schema = contract_schema.load_schemas()["config"]
    assert "1.7" in cfg_schema["properties"]["meta"]["properties"]["schema_version"]["enum"]
    assert {"calibration_path", "calibration"} <= set(cfg_schema["properties"])
    geom = cfg_schema["properties"]["stick"]["properties"]["geom"]
    assert "l_prior_by_hand" in geom["properties"] and "l_prior_by_hand" not in geom["required"]


def test_session_metadata_calibration_fields():
    meta = json.loads(
        (ROOT / "schemas/examples/session-metadata.valid.example.json").read_text(encoding="utf-8")
    )
    assert contract_schema.errors("session-metadata", meta) == []  # optional: older documents stay valid
    meta.update(calibration_status="CALIBRATED", calibration_hash="sha256:" + "a" * 64, calibration_id="x-1")
    assert contract_schema.errors("session-metadata", meta) == []
    meta.update(calibration_status="UNCALIBRATED", calibration_hash=None, calibration_id=None)
    assert contract_schema.errors("session-metadata", meta) == []
    meta["calibration_hash"] = "md5:abc"
    assert contract_schema.errors("session-metadata", meta)
    meta.update(calibration_hash=None, calibration_status="MAYBE")
    assert contract_schema.errors("session-metadata", meta)


def test_committed_example_calibration_is_synthetic_and_valid():
    from spacedrums.calib import load_calibration

    calib = load_calibration(ROOT / "configs/calibration/synthetic-selftest.calib.yaml")
    assert calib.provenance_kind == "SYNTHETIC" and calib.doc["validation"]["label"] == "SYNTHETIC"
    assert calib.doc["provenance"]["kind"] != "PARTICIPANT_LIVE"  # participants never live in configs/


def test_geometry_version_is_shared_with_the_phase07_labels():
    from spacedrums.data.labels.schema import GEOMETRY_VERSION as LABELS_GEOMETRY_VERSION

    assert GEOMETRY_VERSION == LABELS_GEOMETRY_VERSION
