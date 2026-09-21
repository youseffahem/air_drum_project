"""Access to the JSON Schemas that *are* the contracts (ADR-0012).

The schema files under ``schemas/`` (records) and ``configs/schema/`` (config) are the source of
truth; the dataclasses in :mod:`spacedrums.contracts.records` are implementations that must
serialise to exactly that JSON. This module locates the schema directory, builds one
``referencing`` registry (cross-file ``$ref`` via each schema's ``$id``) and exposes validators.

Location rule: the repository's ``schemas/`` directory relative to this source tree
(``src/spacedrums/contracts/`` -> repo root), overridable with ``SPACEDRUMS_SCHEMA_ROOT`` for an
installed (non-editable) deployment. There is deliberately no packaged copy of the schemas: two
copies would be two sources of truth.
"""

from __future__ import annotations

import json
import os
from functools import cache, lru_cache
from pathlib import Path

import jsonschema
from referencing import Registry, Resource

_ENV = "SPACEDRUMS_SCHEMA_ROOT"


def repo_root() -> Path:
    """Repository root (directory that contains ``schemas/`` and ``configs/``)."""
    override = os.environ.get(_ENV)
    if override:
        return Path(override).resolve()
    here = Path(__file__).resolve()
    # src/spacedrums/contracts/schema.py -> parents[3] == repository root
    root = here.parents[3]
    if not (root / "schemas").is_dir():  # pragma: no cover - misconfigured checkout
        raise FileNotFoundError(
            f"schemas/ not found under {root}; set {_ENV} to the repository root"
        )
    return root


def schema_dirs() -> list[Path]:
    root = repo_root()
    return [root / "schemas", root / "configs" / "schema"]


@lru_cache(maxsize=1)
def load_schemas() -> dict[str, dict]:
    """All ``*.schema.json`` keyed by file stem (``frame-sample``, ``config``, ...)."""
    out: dict[str, dict] = {}
    for d in schema_dirs():
        for path in sorted(d.glob("*.schema.json")):
            out[path.name.removesuffix(".schema.json")] = json.loads(path.read_text(encoding="utf-8"))
    return out


@lru_cache(maxsize=1)
def registry() -> Registry:
    reg = Registry()
    for schema in load_schemas().values():
        reg = reg.with_resource(schema["$id"], Resource.from_contents(schema))
    return reg


@cache
def validator(stem: str) -> jsonschema.Draft202012Validator:
    """Validator for one schema stem (schema itself checked as Draft 2020-12 first)."""
    schema = load_schemas()[stem]
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(
        schema, registry=registry(), format_checker=jsonschema.FormatChecker()
    )


def errors(stem: str, instance: object) -> list[str]:
    """Human-readable validation errors (empty list == valid)."""
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in validator(stem).iter_errors(instance)]


def validate(stem: str, instance: object) -> None:
    """Raise ``jsonschema.ValidationError`` listing every error if ``instance`` is invalid."""
    errs = errors(stem, instance)
    if errs:
        raise jsonschema.ValidationError(f"{stem}: " + "; ".join(errs))


def is_valid(stem: str, instance: object) -> bool:
    return not errors(stem, instance)


__all__ = ["errors", "is_valid", "load_schemas", "registry", "repo_root", "schema_dirs",
           "validate", "validator"]
