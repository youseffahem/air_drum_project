"""TEST-LABEL-10 — structural leakage and causality guards (Phase 07).

``docs/architecture/causality-tests.md`` section 1.1 says where non-causal artefacts may live and
what may never touch them. These tests enforce that by inspection of the repository and of the
contracts, not by convention:

* no ``RecordStreamHeader`` may name a label artefact, so a label file cannot be opened as a
  record stream at all;
* no module under a causal package (and, from Phase 08 on, nothing under ``features/`` or
  ``models/``) may import the label machinery or read ``tracks_reference``;
* the label machinery itself imports no runtime decision component.

The ``features``/``models`` scan passes vacuously today because those packages do not exist yet;
it is written now so it fails the moment Phase 08 adds the first file that breaks the rule (phase
document, *Tests → Leakage tests*).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from spacedrums.contracts import schema as contract_schema
from spacedrums.data.labels.schema import (
    CAUSAL_TRACK_FILENAME,
    LABELS_FILENAME,
    REFERENCE_TRACK_FILENAME,
)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "spacedrums"

CAUSAL_PACKAGES = ("capture", "hands", "stick", "tracking", "geometry", "prediction", "commit",
                   "audio", "features", "models", "eval")
FORBIDDEN_IMPORTS = ("spacedrums.data.labels", "spacedrums.data.splits")
FORBIDDEN_READS = ("tracks_reference", "labels.jsonl", "label-record")


def _python_files(package: str) -> list[Path]:
    d = SRC / package
    return sorted(d.rglob("*.py")) if d.is_dir() else []


# ----------------------------------------------------------------------------- contract level


def test_record_stream_header_cannot_name_a_label_artefact():
    enum = contract_schema.load_schemas()["record-stream-header"]["properties"]["record_type"]["enum"]
    for forbidden in ("LabelRecord", "ReferenceTrack", "LabelSet", "LabelReviewEntry"):
        assert forbidden not in enum


def test_the_reference_track_schema_pins_causal_false():
    schema = contract_schema.load_schemas()["reference-track"]
    assert schema["properties"]["causal"]["const"] is False
    assert schema["properties"]["kind"]["const"] == "ReferenceTrack"


def test_the_label_record_schema_pins_causal_false():
    schema = contract_schema.load_schemas()["label-record"]
    assert schema["properties"]["causal"]["const"] is False


def test_the_runtime_reference_block_carries_a_fixed_banner():
    schema = contract_schema.load_schemas()["label-record"]
    banner = schema["properties"]["runtime_reference"]["properties"]["label"]["const"]
    assert "not ground truth" in banner


# ----------------------------------------------------------------------------- source level


@pytest.mark.parametrize("package", CAUSAL_PACKAGES)
def test_no_causal_package_imports_the_label_machinery(package):
    offenders = []
    for path in _python_files(package):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.startswith(FORBIDDEN_IMPORTS) for n in names):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert offenders == [], (
        f"{package} must not import the offline label machinery: {offenders}"
    )


@pytest.mark.parametrize("package", CAUSAL_PACKAGES)
def test_no_causal_package_reads_a_reference_track_or_label_file(package):
    offenders = []
    for path in _python_files(package):
        text = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN_READS:
            if needle in text:
                offenders.append(f"{path.relative_to(ROOT).as_posix()} mentions {needle!r}")
    assert offenders == [], (
        f"{package} must not read label artefacts (causality-tests.md section 1.1): {offenders}"
    )


def test_the_label_machinery_does_not_import_the_decision_pipeline():
    """Labels are built from records, not by running the live decision path: a label must never be
    a by-product of the arm under evaluation."""
    offenders = []
    for path in _python_files("data/labels"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.startswith(("spacedrums.app", "spacedrums.commit", "spacedrums.prediction"))
                   for n in names):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert offenders == []


def test_the_import_linter_contract_names_the_label_packages():
    text = (ROOT / ".importlinter").read_text(encoding="utf-8")
    assert "labels-are-offline" in text
    assert "spacedrums.data.labels" in text
    assert "spacedrums.data.splits" in text


# ----------------------------------------------------------------------------- artefact level


def test_the_two_trajectories_have_different_file_names():
    assert CAUSAL_TRACK_FILENAME != REFERENCE_TRACK_FILENAME
    assert "reference" in REFERENCE_TRACK_FILENAME and "causal" in CAUSAL_TRACK_FILENAME


def test_the_schema_example_of_a_reference_track_is_marked_non_causal():
    doc = json.loads(
        (ROOT / "schemas" / "examples" / "reference-track.valid.example.json").read_text(
            encoding="utf-8"
        )
    )
    assert doc["causal"] is False
    assert "never a model input" in doc["label"]


def test_the_schema_example_of_a_label_record_is_marked_non_causal():
    doc = json.loads(
        (ROOT / "schemas" / "examples" / "label-record.valid.example.json").read_text(
            encoding="utf-8"
        )
    )
    assert doc["causal"] is False
    assert doc["runtime_reference"]["label"].endswith("(not ground truth)")
    assert doc["source_kind"] == "SYNTHETIC"
    assert doc["dataset_version"].startswith("ds-v0.0-selftest")


def test_the_labels_file_name_is_not_a_record_type():
    assert LABELS_FILENAME == "labels.jsonl"
    enum = contract_schema.load_schemas()["record-stream-header"]["properties"]["record_type"]["enum"]
    assert LABELS_FILENAME.removesuffix(".jsonl") not in enum
