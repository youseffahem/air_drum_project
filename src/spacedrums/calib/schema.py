"""calib-v1: the versioned calibration document (Phase 14, Task 14.1; ADR-0037).

A calibration binds a *setup* (camera profile, ROI, geometry version) to the per-user or per-setup
results of the Calibration Wizard: per-hand stick-length prior, the absolute zone layout
(ROI-normalized), the reach envelope it was fitted to and the Arm A validation-strike counts.
The file is YAML; its identity is ``calibration_hash = config_hash(document)`` (canonical JSON,
sorted keys - the hash the config loader uses), so any edit changes the hash.

Validation has two layers: ``schemas/calib-v1.schema.json`` (structure, enums, ranges) and
:func:`semantic_errors` (what JSON Schema cannot express): the absolute zones must be *exactly*
what template -> fit -> nudges -> sample overrides produce (deterministic recomputation, so a hand
edit of one zone is detected), zones must be valid Phase 04 zones without overlap, recorded hashes
must match, the applied L_prior must follow each hand's source, and provenance labels must agree
(a SYNTHETIC calibration can never carry MEASURED validation counts, and vice versa).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from spacedrums.calib.fit import (
    LayoutError,
    ScaleTranslate,
    compose_layout,
    overlap_report,
    zones_hash,
)
from spacedrums.config import config_hash
from spacedrums.contracts import schema as contract_schema

SCHEMA_STEM = "calib-v1"
SCHEMA_VERSION = "calib-v1"
CALIB_ALGORITHM = "p14-calib-v1"
HANDS = ("LEFT", "RIGHT")


class CalibrationError(ValueError):
    """A calibration document is invalid, inconsistent, or does not match the session setup."""


class ProvenanceKind(StrEnum):
    DEVELOPER_LIVE = "DEVELOPER_LIVE"
    DEVELOPER_REPLAY = "DEVELOPER_REPLAY"
    PARTICIPANT_LIVE = "PARTICIPANT_LIVE"
    SYNTHETIC = "SYNTHETIC"


class StepStatus(StrEnum):
    PASSED = "PASSED"
    ACCEPTED_WITH_WARNINGS = "ACCEPTED_WITH_WARNINGS"
    FALLBACK = "FALLBACK"
    SKIPPED = "SKIPPED"


PROVENANCE_LABELS = {
    ProvenanceKind.SYNTHETIC: "SYNTHETIC - scripted wizard actor; machinery self-test, never evidence",
    ProvenanceKind.DEVELOPER_REPLAY: "DEVELOPER REPLAY - recorded developer frames, no cued behaviour; "
    "development diagnostic only",
    ProvenanceKind.DEVELOPER_LIVE: "DEVELOPER LIVE - developer followed the wizard at the camera",
    ProvenanceKind.PARTICIPANT_LIVE: "PARTICIPANT LIVE - Phase 18 participant calibration (kept under data/)",
}


def schema_errors(doc: Any) -> list[str]:
    return contract_schema.errors(SCHEMA_STEM, doc)


def semantic_errors(doc: Mapping[str, Any]) -> list[str]:
    """Cross-field checks of a schema-valid document (empty list == consistent)."""
    problems: list[str] = []
    layout = doc["layout"]
    template = layout["template"]
    if zones_hash(template["zones"]) != template["zones_hash"]:
        problems.append("layout.template.zones_hash does not match the embedded template zones")
    if zones_hash(layout["zones"]) != layout["zones_hash"]:
        problems.append("layout.zones_hash does not match layout.zones")
    fit = layout["fit"]
    if fit["mode"] == "FIXED" and (fit["scale"] != 1.0 or list(fit["translate"]) != [0.0, 0.0]):
        problems.append("FIXED fit mode requires scale 1 and translate [0, 0]")
    try:
        recomputed = compose_layout(
            template["zones"],
            ScaleTranslate.from_dict(fit),
            layout["nudges"],
            float(layout["max_nudge"]),
            layout["sample_overrides"],
        )
    except (LayoutError, ValueError, KeyError) as exc:
        problems.append(f"layout cannot be recomputed from template/fit/nudges/overrides: {exc}")
    else:
        if recomputed != layout["zones"]:
            problems.append(
                "layout.zones differ from template -> fit -> nudges -> sample overrides "
                "(hand-edited zones are not allowed; re-run the wizard)"
            )
        gap = float(doc["settings"].get("ambiguity_gap", 0.0))
        overlap = overlap_report(recomputed, ambiguity_gap=gap)
        if not overlap["passed"]:
            problems.append(f"zones overlap: {overlap['overlapping_pairs']}")
    ids = [z["zone_id"] for z in template["zones"]]
    if [z["zone_id"] for z in layout["zones"]] != ids:
        problems.append("calibrated zone ids/order must equal the template's (feature schema compatibility)")
    if config_hash(doc["settings"]) != doc["settings_hash"]:
        problems.append("settings_hash does not match settings")
    prior = doc["stick_prior"]
    for hand in HANDS:
        info = prior["per_hand"][hand]
        applied = prior["l_prior"][hand]
        expected = info["median"] if info["source"] == "MEASURED" else prior["default_l_prior"]
        if expected is None or applied != expected:
            problems.append(f"stick_prior.l_prior.{hand} must equal the {info['source']} value")
    prov = doc["provenance"]
    kind = ProvenanceKind(prov["kind"])
    if prov["scope"] == "USER" and not prov["user_tag"]:
        problems.append("a USER-scope calibration needs provenance.user_tag (pseudonym)")
    if prov["scope"] == "SETUP" and not prov["setup_tag"]:
        problems.append("a SETUP-scope calibration needs provenance.setup_tag")
    validation = doc["validation"]
    if kind is ProvenanceKind.SYNTHETIC and validation["label"] == "MEASURED":
        problems.append("a SYNTHETIC calibration cannot carry MEASURED validation counts")
    if kind is not ProvenanceKind.SYNTHETIC and validation["label"] == "SYNTHETIC":
        problems.append("SYNTHETIC validation counts in a non-synthetic calibration")
    if kind is ProvenanceKind.DEVELOPER_REPLAY and validation["label"] != "NOT_RUN":
        problems.append("a replayed recording has no cued strikes: validation must be SKIPPED")
    skipped = validation["status"] == StepStatus.SKIPPED
    if skipped != (validation["label"] == "NOT_RUN") or skipped != (validation["passed"] is None):
        problems.append("validation SKIPPED <=> label NOT_RUN <=> passed null")
    if not skipped:
        zone_rows = [row["zone_id"] for row in validation["per_zone"]]
        if zone_rows != ids:
            problems.append("validation.per_zone must list every calibrated zone in layout order")
    if doc["durations_s"]["clock"] == "t_mono" and kind in (
        ProvenanceKind.SYNTHETIC,
        ProvenanceKind.DEVELOPER_REPLAY,
    ):
        problems.append("t_mono durations require a live calibration")
    return problems


def validate_document(doc: Any) -> None:
    """Schema + semantic validation; raises :class:`CalibrationError` listing every problem."""
    errors = schema_errors(doc)
    if errors:
        raise CalibrationError("calib-v1 schema violation(s): " + "; ".join(errors))
    problems = semantic_errors(doc)
    if problems:
        raise CalibrationError("calib-v1 inconsistency: " + "; ".join(problems))


__all__ = [
    "CALIB_ALGORITHM",
    "HANDS",
    "PROVENANCE_LABELS",
    "SCHEMA_STEM",
    "SCHEMA_VERSION",
    "CalibrationError",
    "ProvenanceKind",
    "StepStatus",
    "schema_errors",
    "semantic_errors",
    "validate_document",
]
