"""Schema-validated configuration loading, resolution and hashing (ADR-0010; Phase 02 code).

Model (docs/architecture/architecture.md section 14, docs/reproducibility-policy.md section 3):

* A run's configuration is **one resolved document** validated against
  ``configs/schema/config.schema.json`` *before any computation*.
* How that document is assembled is this loader's business: :func:`load_config` deep-merges any
  number of YAML files in order (later files override earlier ones, key by key), then applies
  optional in-memory overrides, validates, runs the cross-field checks the schema descriptions
  list, and hashes the result into ``config_hash``.
* Fragments such as ``configs/camera/<device>.candidate.yaml`` carry only the blocks they own
  plus ``meta``; they are merged onto a base document (e.g. ``configs/example.candidate.yaml``)
  and are individually checkable with :func:`validate_blocks`.
* ``config_hash = "sha256:" + SHA256(canonical_json(resolved))`` where canonical JSON is UTF-8,
  keys sorted recursively, no insignificant whitespace, floats via ``repr`` (Python's default),
  NaN/Inf forbidden. Note that ``30`` and ``30.0`` hash differently on purpose: they are
  different documents.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from spacedrums.contracts import schema as contract_schema

CONFIG_SCHEMA_STEM = "config"


class ConfigError(ValueError):
    """A configuration failed validation or a cross-field check."""


@dataclass(frozen=True)
class ResolvedConfig:
    """The validated resolved document plus its provenance."""

    data: dict[str, Any]
    config_hash: str
    sources: tuple[str, ...] = field(default_factory=tuple)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


# ----------------------------------------------------------------------------- YAML + merge


def load_yaml(path: str | Path) -> dict[str, Any]:
    """``yaml.safe_load`` (docs/environment.md: always safe_load) of one mapping document."""
    with Path(path).open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise ConfigError(f"{path}: top level must be a mapping, got {type(doc).__name__}")
    return doc


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict: ``override`` merged onto ``base`` recursively.

    Mappings merge key by key; any other value (lists included) replaces the base value
    wholesale, so a fragment that lists ``zones`` replaces the whole zone list.
    """
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


# ----------------------------------------------------------------------------- canonical JSON


def _reject_non_finite(obj: Any, path: str = "$") -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ConfigError(f"{path}: NaN/Inf are forbidden in a configuration")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _reject_non_finite(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _reject_non_finite(v, f"{path}[{i}]")


def canonical_json(obj: Any) -> bytes:
    """UTF-8, sorted keys, no insignificant whitespace, floats via repr, NaN/Inf forbidden."""
    _reject_non_finite(obj)
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def config_hash(obj: Any) -> str:
    """``sha256:<64 hex>`` over :func:`canonical_json` (reproducibility-policy.md section 3)."""
    return "sha256:" + hashlib.sha256(canonical_json(obj)).hexdigest()


# ----------------------------------------------------------------------------- validation


def schema_errors(cfg: dict[str, Any]) -> list[str]:
    return contract_schema.errors(CONFIG_SCHEMA_STEM, cfg)


def validate_blocks(cfg_fragment: dict[str, Any], blocks: list[str] | None = None) -> None:
    """Validate the named top-level blocks of a *fragment* against their sub-schemas.

    Lets a camera fragment (``meta`` + ``camera_profile`` + ``roi``) be checked on its own
    without the unrelated blocks of a full document. Unknown block names are an error.
    """
    full = contract_schema.load_schemas()[CONFIG_SCHEMA_STEM]
    names = blocks if blocks is not None else [k for k in cfg_fragment if k in full["properties"]]
    for name in names:
        if name not in full["properties"]:
            raise ConfigError(f"unknown config block {name!r}")
        if name not in cfg_fragment:
            raise ConfigError(f"fragment has no block {name!r}")
        sub = {"$schema": full["$schema"], "$id": full["$id"] + f"#block-{name}",
               **full["properties"][name]}
        v = jsonschema.Draft202012Validator(
            sub, registry=contract_schema.registry(), format_checker=jsonschema.FormatChecker()
        )
        errs = [f"{name}/{'/'.join(str(p) for p in e.absolute_path)}: {e.message}"
                for e in v.iter_errors(cfg_fragment[name])]
        if errs:
            raise ConfigError("fragment invalid: " + "; ".join(errs))


def cross_field_checks(cfg: dict[str, Any]) -> list[str]:
    """Checks the schema descriptions promise but JSON Schema cannot express.

    Phase 02 implements the ones its blocks need; later phases append theirs here
    (Phase 04: impact surface on the zone boundary; Phase 13: model hash present, ...).
    """
    problems: list[str] = []
    tr = cfg.get("tracking", {})
    if "c_min" in tr and "c_valid" in tr and tr["c_min"] > tr["c_valid"]:
        problems.append(f"tracking.c_min ({tr['c_min']}) must be <= tracking.c_valid ({tr['c_valid']})")
    cam = cfg.get("camera_profile", {})
    roi = cfg.get("roi", {}).get("px")
    res = cam.get("resolution_px")
    if roi and res:
        x, y, w, h = roi
        if x + w > res[0] or y + h > res[1]:
            problems.append(f"roi.px {roi} must lie inside camera_profile.resolution_px {res}")
    exp = cam.get("exposure", {})
    if exp.get("mode") == "MANUAL" and exp.get("value") is None:
        problems.append("camera_profile.exposure.value must be set when mode is MANUAL")
    if exp.get("mode") == "AUTO" and exp.get("value") is not None:
        problems.append("camera_profile.exposure.value must be null when mode is AUTO")
    if cam.get("timestamp_source") == "GRAB_RETURN" and cam.get("native_fps_measured") is None \
            and cam.get("grab_return_bias_s") is not None:
        # a bias is only meaningful once the mode it was measured in is itself measured
        problems.append("camera_profile.grab_return_bias_s set while native_fps_measured is null")
    return problems


def validate(cfg: dict[str, Any]) -> None:
    """Schema validation + cross-field checks; raises :class:`ConfigError` with every problem."""
    errs = schema_errors(cfg)
    if errs:
        raise ConfigError("config schema violation(s): " + "; ".join(errs))
    problems = cross_field_checks(cfg)
    if problems:
        raise ConfigError("config cross-field violation(s): " + "; ".join(problems))


# ----------------------------------------------------------------------------- public API


def resolve(*paths: str | Path, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge the given YAML files in order, then ``overrides``; no validation."""
    doc: dict[str, Any] = {}
    for p in paths:
        doc = deep_merge(doc, load_yaml(p))
    if overrides:
        doc = deep_merge(doc, overrides)
    return doc


def load_config(*paths: str | Path, overrides: dict[str, Any] | None = None) -> ResolvedConfig:
    """Resolve, validate (schema + cross-field), hash. The only entry point runs should use."""
    if not paths and not overrides:
        raise ConfigError("load_config needs at least one file or overrides")
    doc = resolve(*paths, overrides=overrides)
    validate(doc)
    return ResolvedConfig(
        data=doc, config_hash=config_hash(doc), sources=tuple(str(Path(p)) for p in paths)
    )


def write_resolved(cfg: ResolvedConfig | dict[str, Any], path: str | Path) -> Path:
    """Write ``config.resolved.yaml`` (the exact document that was hashed)."""
    data = cfg.data if isinstance(cfg, ResolvedConfig) else cfg
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write("# Resolved configuration snapshot (docs/reproducibility-policy.md section 3).\n")
        if isinstance(cfg, ResolvedConfig):
            fh.write(f"# config_hash: {cfg.config_hash}\n")
            fh.write(f"# sources: {list(cfg.sources)}\n")
        yaml.safe_dump(data, fh, sort_keys=True, allow_unicode=True, default_flow_style=False)
    return out


__all__ = [
    "ConfigError",
    "ResolvedConfig",
    "canonical_json",
    "config_hash",
    "cross_field_checks",
    "deep_merge",
    "load_config",
    "load_yaml",
    "resolve",
    "schema_errors",
    "validate",
    "validate_blocks",
    "write_resolved",
]
