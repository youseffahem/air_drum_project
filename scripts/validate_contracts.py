"""Phase 01 contract-schema check (Task 01.2 / 01.7, docs/architecture/contracts.md section 5).

This is a SCHEMA CHECK, not project implementation. It:
  1. loads every JSON Schema under schemas/ and configs/schema/ into one registry
     (cross-file $ref resolution via each schema's $id);
  2. checks each schema is itself valid Draft 2020-12;
  3. accepts every schemas/examples/<name>.valid.example.json against <name>.schema.json;
  4. rejects, for every record schema, (a) each required field removed one at a time,
     (b) an unknown extra field, (c) t_capture absent where the contract carries it;
  5. rejects a record-stream header whose units flag is wrong (time = "ms");
  6. accepts configs/example.candidate.yaml against configs/schema/config.schema.json
     and rejects a config with an out-of-scope trigger type.

Exit code 0 = all checks passed. Any failure is printed and exits non-zero.
The same checks run under pytest in tests/contracts/ (TEST-SCHEMA-1).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema
import yaml
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIRS = [ROOT / "schemas", ROOT / "configs" / "schema"]
EXAMPLES = ROOT / "schemas" / "examples"
CONFIG_SCHEMA = ROOT / "configs" / "schema" / "config.schema.json"
CONFIG_EXAMPLE = ROOT / "configs" / "example.candidate.yaml"

# Record schemas defined by Phase 01 (contracts.md section 3-4). Keys = file stem.
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
# Phase 06 dataset documents (session metadata, verification, exclusion record, raw manifest):
# example accepted; required fields removed one at a time -> rejected; unknown field -> rejected.
DATASET_SCHEMAS = [
    "session-metadata",
    "session-verification",
    "exclusion-record",
    "raw-manifest",
]
# Records that must carry t_capture (Task 01.3 rule). Header/audio records are exempt:
# AudioEvent is keyed by strike_id; RecordStreamHeader is not a per-frame record.
CARRIES_T_CAPTURE = [s for s in RECORD_SCHEMAS if s not in ("audio-event", "record-stream-header")]


def load_registry() -> tuple[Registry, dict[str, dict]]:
    """Load all *.schema.json files; return (registry keyed by $id, schemas keyed by stem)."""
    registry = Registry()
    by_stem: dict[str, dict] = {}
    for d in SCHEMA_DIRS:
        for path in sorted(d.glob("*.schema.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
            by_stem[path.name.removesuffix(".schema.json")] = schema
    return registry, by_stem


def validator_for(schema: dict, registry: Registry) -> jsonschema.Draft202012Validator:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(
        schema, registry=registry, format_checker=jsonschema.FormatChecker()
    )


def errors(validator: jsonschema.Draft202012Validator, instance) -> list[str]:
    return [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(instance)]


def main() -> int:
    ok = True

    def report(passed: bool, label: str, detail: list[str] | None = None) -> None:
        nonlocal ok
        ok = ok and passed
        print(("OK   " if passed else "FAIL ") + label)
        for line in detail or []:
            print(f"     - {line}")

    registry, schemas = load_registry()
    report(
        all(s in schemas for s in RECORD_SCHEMAS + DATASET_SCHEMAS + ["common", "config"]),
        f"loaded {len(schemas)} schemas",
    )

    # 2 + 3: each schema is valid; each valid example is accepted.
    for stem in RECORD_SCHEMAS:
        v = validator_for(schemas[stem], registry)
        example = json.loads((EXAMPLES / f"{stem}.valid.example.json").read_text(encoding="utf-8"))
        errs = errors(v, example)
        report(not errs, f"{stem}: schema valid, example accepted", errs)

        # 4a: every required field removed -> rejected.
        for field in schemas[stem]["required"]:
            broken = copy.deepcopy(example)
            del broken[field]
            report(bool(errors(v, broken)), f"{stem}: missing '{field}' rejected")

        # 4b: unknown field -> rejected (additionalProperties: false).
        extra = copy.deepcopy(example)
        extra["not_in_contract"] = 1
        report(bool(errors(v, extra)), f"{stem}: unknown field rejected")

        # 4c: t_capture as a string (wrong type / unit-like mistake) -> rejected.
        if stem in CARRIES_T_CAPTURE:
            wrong = copy.deepcopy(example)
            wrong["t_capture"] = "12345 ms"
            report(bool(errors(v, wrong)), f"{stem}: non-numeric t_capture rejected")

    # 4d (Phase 06): dataset documents.
    for stem in DATASET_SCHEMAS:
        v = validator_for(schemas[stem], registry)
        example = json.loads((EXAMPLES / f"{stem}.valid.example.json").read_text(encoding="utf-8"))
        errs = errors(v, example)
        report(not errs, f"{stem}: schema valid, example accepted", errs)
        for field in schemas[stem]["required"]:
            broken = copy.deepcopy(example)
            del broken[field]
            report(bool(errors(v, broken)), f"{stem}: missing '{field}' rejected")
        extra = copy.deepcopy(example)
        extra["not_in_contract"] = 1
        report(bool(errors(v, extra)), f"{stem}: unknown field rejected")
    # session-metadata classification rules: developer / synthetic material can never carry participant ids.
    v = validator_for(schemas["session-metadata"], registry)
    meta = json.loads((EXAMPLES / "session-metadata.valid.example.json").read_text(encoding="utf-8"))
    promoted = copy.deepcopy(meta)
    promoted["session_kind"] = "PARTICIPANT"  # everything else still says SYNTHETIC
    report(bool(errors(v, promoted)), "session-metadata: SYNTHETIC document relabelled PARTICIPANT rejected")
    pid = copy.deepcopy(meta)
    pid["participant_id"] = "P01"
    report(bool(errors(v, pid)), "session-metadata: SYNTHETIC session with a participant pseudonym rejected")
    dsv = copy.deepcopy(meta)
    dsv["dataset_version"] = "ds-raw-v1.0"
    report(
        bool(errors(v, dsv)), "session-metadata: SYNTHETIC session in a participant dataset version rejected"
    )

    # 5: wrong units flag in the stream header.
    v = validator_for(schemas["record-stream-header"], registry)
    header = json.loads((EXAMPLES / "record-stream-header.valid.example.json").read_text(encoding="utf-8"))
    bad_units = copy.deepcopy(header)
    bad_units["units"]["time"] = "ms"
    report(bool(errors(v, bad_units)), "record-stream-header: units.time = 'ms' rejected")

    # 6: config schema accepts the example config and rejects an out-of-scope trigger type.
    v = validator_for(schemas["config"], registry)
    cfg = yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    errs = errors(v, cfg)
    report(not errs, "config: example.candidate.yaml accepted", errs)
    bad_cfg = copy.deepcopy(cfg)
    bad_cfg["zones"][0]["trigger_type"] = "FOOT"  # OOS-REF:REQ-207 reserved, not implemented
    report(bool(errors(v, bad_cfg)), "config: trigger_type FOOT rejected (reserved)")
    no_zones = copy.deepcopy(cfg)
    del no_zones["zones"]
    report(bool(errors(v, no_zones)), "config: missing zones rejected")

    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
