"""Calibration file I/O, re-calibration triggers and application to the pipeline config
(Phase 14, Tasks 14.1 / 14.6 / 14.7; ADR-0037).

* :func:`save_calibration` / :func:`load_calibration` - YAML (LF, sorted keys), validated on both
  ends; ``calibration_hash = config_hash(document)``; a save is re-loaded and must hash identically.
* :func:`recalibration_triggers` - camera profile change (hashed block), ROI change, geometry-version
  change, template-layout change, user request. Any trigger refuses the calibration at load.
* :func:`apply_calibration` - the resolved config gets the calibrated ``zones``, per-hand
  ``stick.geom.l_prior_by_hand`` and the derived ``calibration`` block (schema 1.7). The ROI is not
  changed: it is part of the binding, so a different ROI is a trigger, never a silent override.
* :func:`load_calibrated_config` - the entry point for every session-producing run; returns the
  resolved config plus the CALIBRATED / UNCALIBRATED status and warnings for session metadata.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from spacedrums.calib.fit import zones_hash
from spacedrums.calib.schema import (
    CALIB_ALGORITHM,
    HANDS,
    CalibrationError,
    ProvenanceKind,
    StepStatus,
    validate_document,
)
from spacedrums.calib.wizard import setup_binding
from spacedrums.config import ConfigError, ResolvedConfig, config_hash, resolve, validate
from spacedrums.contracts import schema as contract_schema
from spacedrums.geometry import GEOMETRY_VERSION

CALIBRATED = "CALIBRATED"
UNCALIBRATED = "UNCALIBRATED"
HEADER = (
    "# calib-v1 calibration (Phase 14, ADR-0037). Written by the Calibration Wizard - do not edit:\n"
    "# the loader recomputes the layout from template + fit + nudges and rejects hand edits.\n"
    "# Identity: calibration_hash = config_hash(document) (canonical JSON, sorted keys).\n"
)


class Trigger(StrEnum):
    CAMERA_PROFILE_CHANGED = "CAMERA_PROFILE_CHANGED"
    ROI_CHANGED = "ROI_CHANGED"
    GEOMETRY_VERSION_CHANGED = "GEOMETRY_VERSION_CHANGED"
    TEMPLATE_CHANGED = "TEMPLATE_CHANGED"
    USER_REQUEST = "USER_REQUEST"


@dataclass(frozen=True)
class Calibration:
    doc: dict[str, Any]
    hash: str
    path: Path | None = None

    @property
    def calibration_id(self) -> str:
        return self.doc["calibration_id"]

    @property
    def zones(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.doc["layout"]["zones"])

    @property
    def template_zones(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.doc["layout"]["template"]["zones"])

    @property
    def l_prior_by_hand(self) -> dict[str, float]:
        return {h: float(self.doc["stick_prior"]["l_prior"][h]) for h in HANDS}

    @property
    def provenance_kind(self) -> ProvenanceKind:
        return ProvenanceKind(self.doc["provenance"]["kind"])

    @property
    def validation_passed(self) -> bool | None:
        return self.doc["validation"]["passed"]


def calibration_hash(doc: Mapping[str, Any]) -> str:
    return config_hash(dict(doc))


def dump_calibration(doc: Mapping[str, Any]) -> str:
    body = yaml.safe_dump(dict(doc), sort_keys=True, allow_unicode=True, default_flow_style=False, width=110)
    return HEADER + body


def load_calibration(path: str | Path) -> Calibration:
    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CalibrationError(f"cannot read calibration {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise CalibrationError(f"{path}: a calibration is a mapping document")
    validate_document(doc)
    return Calibration(doc, calibration_hash(doc), path)


def save_calibration(doc: Mapping[str, Any], path: str | Path) -> Calibration:
    """Validate, write (UTF-8, LF), re-load and require the identical hash (lossless round trip)."""
    validate_document(doc)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dump_calibration(doc).encode("utf-8"))
    loaded = load_calibration(path)
    if loaded.hash != calibration_hash(doc):
        raise CalibrationError("calibration changed on its YAML round trip")
    return loaded


def recalibration_triggers(
    calib: Calibration,
    cfg: Mapping[str, Any],
    *,
    user_request: bool = False,
    root: Path | None = None,
) -> list[dict[str, str]]:
    """Why ``calib`` must not be used with ``cfg`` (empty list = still valid)."""
    b = setup_binding(cfg)
    d = calib.doc
    out: list[dict[str, str]] = []
    cam = d["camera"]
    if cam["profile_id"] != b["camera_profile_id"] or cam["profile_hash"] != b["camera_profile_hash"]:
        out.append(
            {
                "code": str(Trigger.CAMERA_PROFILE_CHANGED),
                "detail": f"calibrated with {cam['profile_id']} ({cam['profile_hash'][:19]}...), "
                f"config has {b['camera_profile_id']} ({b['camera_profile_hash'][:19]}...)",
            }
        )
    if list(d["roi"]["px"]) != b["roi_px"]:
        detail = f"calibrated ROI {d['roi']['px']}, config {b['roi_px']}"
        out.append({"code": str(Trigger.ROI_CHANGED), "detail": detail})
    if d["app"]["geometry_version"] != GEOMETRY_VERSION:
        out.append(
            {
                "code": str(Trigger.GEOMETRY_VERSION_CHANGED),
                "detail": f"calibrated with {d['app']['geometry_version']}, running {GEOMETRY_VERSION}",
            }
        )
    template = d["layout"]["template"]
    source = (root or contract_schema.repo_root()) / template["source"]
    if source.is_file():
        current = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if zones_hash(current.get("zones") or []) != template["zones_hash"]:
            out.append(
                {
                    "code": str(Trigger.TEMPLATE_CHANGED),
                    "detail": f"{template['source']} changed since calibration (embedded template kept)",
                }
            )
    if user_request:
        out.append({"code": str(Trigger.USER_REQUEST), "detail": "re-calibration requested"})
    return out


def calibration_warnings(calib: Calibration) -> list[str]:
    """Non-blocking facts a session must record (never silently ignored)."""
    d = calib.doc
    out = []
    kind = calib.provenance_kind
    if kind is ProvenanceKind.SYNTHETIC:
        out.append("SYNTHETIC calibration (scripted actor): development self-test only, never evidence")
    elif kind is ProvenanceKind.DEVELOPER_REPLAY:
        out.append("DEVELOPER_REPLAY calibration: replayed frames, no cued behaviour; development only")
    for key in ("playing_area", "stick_prior", "reach_envelope", "validation"):
        status = d[key]["status"]
        if status != StepStatus.PASSED:
            out.append(f"{key}: {status}")
    if d["camera"]["check"]["status"] != StepStatus.PASSED:
        out.append(f"camera_check: {d['camera']['check']['status']}")
    if d["layout"]["fit"]["mode"] == "FIXED":
        out.append("layout: FIXED template (no envelope fit)")
    if d["validation"]["passed"] is False:
        out.append("validation flagged: " + "; ".join(d["validation"]["flags"]))
    if d["app"]["calib_algorithm"] != CALIB_ALGORITHM:
        out.append(f"made by wizard {d['app']['calib_algorithm']} (running {CALIB_ALGORITHM})")
    if d["app"]["git_dirty"]:
        out.append("made on a dirty working tree")
    return out


def apply_calibration(cfg: Mapping[str, Any], calib: Calibration) -> dict[str, Any]:
    """Derived config: calibrated zones + per-hand L_prior + the ``calibration`` block (schema 1.7)."""
    doc = copy.deepcopy(dict(cfg))
    doc["meta"] = {**doc["meta"], "schema_version": "1.7"}
    zones = calib.zones
    doc["zones"] = zones
    if "stick" in doc:
        doc["stick"]["geom"]["l_prior_by_hand"] = calib.l_prior_by_hand
    layout = calib.doc["layout"]
    doc["calibration"] = {
        "calibration_id": calib.calibration_id,
        "calibration_hash": calib.hash,
        "provenance_kind": str(calib.provenance_kind),
        "template_layout_id": layout["template"]["layout_id"],
        "template_zones": calib.template_zones,
        "template_zones_hash": layout["template"]["zones_hash"],
        "zones_hash": zones_hash(zones),
        "fit": {
            "mode": layout["fit"]["mode"],
            "scale": layout["fit"]["scale"],
            "translate": list(layout["fit"]["translate"]),
        },
        "l_prior_by_hand": calib.l_prior_by_hand,
        "validation_passed": calib.validation_passed,
        "geometry_version": calib.doc["app"]["geometry_version"],
    }
    return doc


@dataclass(frozen=True)
class CalibratedConfig:
    config: ResolvedConfig
    calibration: Calibration | None
    status: str
    warnings: tuple[str, ...] = ()

    def session_fields(self) -> dict[str, Any]:
        """SessionMetadata / session.json fields (schema: calibration_status, _hash, _id)."""
        block = self.config.data.get("calibration")
        return {
            "calibration_status": self.status,
            "calibration_hash": None if block is None else block["calibration_hash"],
            "calibration_id": None if block is None else block["calibration_id"],
        }


def _locate(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute() or p.exists():
        return p
    candidate = contract_schema.repo_root() / p
    return candidate if candidate.exists() else p


def load_calibrated_config(
    *paths: str | Path,
    overrides: dict[str, Any] | None = None,
    calibration: str | Path | None = None,
) -> CalibratedConfig:
    """Resolve config files (+ optional calibration) into one validated, hashed document.

    * no ``calibration_path`` -> the plain document, status UNCALIBRATED;
    * ``calibration_path`` (or ``calibration=``) -> the calib-v1 file is loaded and verified, any
      re-calibration trigger raises :class:`CalibrationError`, otherwise the calibration is applied;
    * a document that already carries the derived block (a session's config snapshot) is used as is:
      the config loader proves its zones / L_prior / block agree.
    """
    if not paths and not overrides:
        raise ConfigError("load_calibrated_config needs at least one file or overrides")
    doc = resolve(*paths, overrides=overrides)
    sources = tuple(str(Path(p)) for p in paths)
    if calibration is not None:
        doc["calibration_path"] = str(calibration)
    if doc.get("calibration") is not None:
        validate(doc)
        warnings = []
        file = _locate(doc["calibration_path"])
        if file.is_file():
            try:
                current = load_calibration(file)
            except CalibrationError as exc:
                warnings.append(f"calibration file {file} no longer loads: {exc}")
            else:
                if current.hash != doc["calibration"]["calibration_hash"]:
                    warnings.append(f"calibration file {file} changed since this snapshot (snapshot used)")
        resolved = ResolvedConfig(doc, config_hash(doc), sources)
        return CalibratedConfig(resolved, None, CALIBRATED, tuple(warnings))
    path = doc.get("calibration_path")
    if path is None:
        validate(doc)
        return CalibratedConfig(ResolvedConfig(doc, config_hash(doc), sources), None, UNCALIBRATED)
    base = {k: v for k, v in doc.items() if k != "calibration_path"}
    validate(base)
    calib = load_calibration(_locate(path))
    triggers = recalibration_triggers(calib, doc)
    if triggers:
        raise CalibrationError(
            f"re-calibration required for {path}: "
            + "; ".join(f"{t['code']}: {t['detail']}" for t in triggers)
            + " - run `python -m spacedrums.app.calibrate` again, or remove calibration_path to run "
            "UNCALIBRATED with the default layout"
        )
    out = apply_calibration(doc, calib)
    validate(out)
    return CalibratedConfig(
        ResolvedConfig(out, config_hash(out), (*sources, str(path))),
        calib,
        CALIBRATED,
        tuple(calibration_warnings(calib)),
    )


__all__ = [
    "CALIBRATED",
    "UNCALIBRATED",
    "CalibratedConfig",
    "Calibration",
    "Trigger",
    "apply_calibration",
    "calibration_hash",
    "calibration_warnings",
    "dump_calibration",
    "load_calibrated_config",
    "load_calibration",
    "recalibration_triggers",
    "save_calibration",
]
