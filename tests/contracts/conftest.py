"""Shared fixtures for the Phase 01 contract-schema tests (TEST-SCHEMA-1).

These tests validate JSON Schemas against example documents. They contain no
pipeline logic and import nothing from src/ (the package has no code in Phase 01).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIRS = [ROOT / "schemas", ROOT / "configs" / "schema"]
EXAMPLES = ROOT / "schemas" / "examples"
CONFIG_EXAMPLE = ROOT / "configs" / "example.candidate.yaml"

RECORD_SCHEMAS = [
    "frame-sample",
    "hand-observation",
    "stick-observation",
    "track-state",
    "kinematic-features",
    "trajectory-prediction",
    "direct-prediction",
    "strike-candidate",
    "committed-strike",
    "audio-event",
    "timing-record",
    "record-stream-header",
]


@pytest.fixture(scope="session")
def schemas() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in SCHEMA_DIRS:
        for path in sorted(d.glob("*.schema.json")):
            out[path.name.removesuffix(".schema.json")] = json.loads(path.read_text(encoding="utf-8"))
    return out


@pytest.fixture(scope="session")
def registry(schemas: dict[str, dict]) -> Registry:
    reg = Registry()
    for schema in schemas.values():
        reg = reg.with_resource(schema["$id"], Resource.from_contents(schema))
    return reg


@pytest.fixture(scope="session")
def validator(schemas: dict[str, dict], registry: Registry):
    def make(stem: str) -> jsonschema.Draft202012Validator:
        schema = schemas[stem]
        jsonschema.Draft202012Validator.check_schema(schema)
        return jsonschema.Draft202012Validator(
            schema, registry=registry, format_checker=jsonschema.FormatChecker()
        )

    return make


@pytest.fixture(scope="session")
def example():
    def load(stem: str) -> dict:
        return json.loads((EXAMPLES / f"{stem}.valid.example.json").read_text(encoding="utf-8"))

    return load


@pytest.fixture(scope="session")
def config_example() -> dict:
    return yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8"))


def is_valid(v: jsonschema.Draft202012Validator, instance) -> bool:
    return not list(v.iter_errors(instance))
