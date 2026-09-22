"""``LabelRecord`` / ``ReferenceTrack`` vocabulary, versioning and construction (Phase 07, Tasks
07.1 / 07.3 / 07.7).

The JSON Schemas are the contracts (ADR-0012): ``schemas/label-record.schema.json``,
``reference-track.schema.json``, ``label-set.schema.json``, ``label-review.schema.json``. This
module is the Python mirror — the enums, the version identifiers, the provenance block and the
builders that produce documents which validate against those schemas.

Two rules are structural here and are worth naming:

* **Non-causality.** Every ``LabelRecord`` carries ``causal: false`` and every ``ReferenceTrack``
  header carries ``causal: false`` as a schema ``const``. Label construction is the only place in
  the system where future frames may be used (``docs/architecture/causality-tests.md`` section 1).
  What the *causal* pipeline saw at the same moment is kept in the record's ``runtime_reference``
  block, explicitly labelled *REAL-TIME AVAILABLE SIGNALS (not ground truth)*, so a runtime strike
  candidate can never be mistaken for the annotated ground truth.
* **Provenance kind-gating.** ``dataset_version`` is gated on ``source_kind`` exactly as Phase 06
  gates raw manifests (``spacedrums.data.manifest``): SYNTHETIC and DEV_CAPTURE labels may only
  carry ``ds-none-v0.0`` or ``ds-v0.0-selftest*``. Developer or generated material can therefore
  not be promoted to participant dataset status by editing a field (integrity I-4).

Version identifiers (Task 07.10 versioning rule): ``labels_version`` changes whenever the rules,
the thresholds, the smoother or the tracker change; ``labels_hash`` is computed from exactly those
inputs, so a stale ``labels_version`` is detectable rather than merely discouraged.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

from spacedrums.contracts import HandId, TrackStatus
from spacedrums.contracts import schema as contract_schema
from spacedrums.data.metadata import SessionKind

LABEL_RECORD_SCHEMA_VERSION = "1.0"
REFERENCE_TRACK_SCHEMA_VERSION = "1.0"
LABEL_SET_SCHEMA_VERSION = "1.0"
LABEL_REVIEW_SCHEMA_VERSION = "1.0"

RULES_VERSION = "1.0"
"""Version of docs/dataset/labeling-rules-v1.0.md. A rule change bumps this and labels_version."""

LABELS_VERSION = "labels-v1.0"
"""Label machinery version written into every artefact of this phase."""

GEOMETRY_VERSION = "p04-geometry-v1"
"""Identity of the Phase 04 entry test / surface intersection reused unchanged for labels."""

GENERATOR = {"tool": "spacedrums.data.labels.generate", "version": "0.7.0"}
DATASET_VERSION_NONE = "ds-none-v0.0"

LABELS_DIRNAME = "labels"
LABELS_FILENAME = "labels.jsonl"
LABEL_SET_FILENAME = "labels.meta.json"
REVIEW_FILENAME = "review.jsonl"
CAUSAL_TRACK_FILENAME = "tracks_causal.jsonl"
REFERENCE_TRACK_FILENAME = "tracks_reference.jsonl"

REFERENCE_TRACK_BANNER = "NON-CAUSAL OFFLINE LABEL SOURCE - never a model input"
RUNTIME_REFERENCE_BANNER = "REAL-TIME AVAILABLE SIGNALS (not ground truth)"

_PARTICIPANT_DS = re.compile(r"^ds-v[0-9]+\.[0-9]+$")
_PILOT_DS = re.compile(r"^ds-v[0-9]+\.[0-9]+-pilot$")
_SELFTEST_DS = re.compile(r"^ds-v0\.0-selftest(-[a-z0-9]+)*$")


class LabelClass(StrEnum):
    """Label classes of the rules document (Task 07.1)."""

    POSITIVE = "POSITIVE"
    NEG_NO_STRIKE_MOTION = "NEG_NO_STRIKE_MOTION"
    NEG_FAKE_SWING = "NEG_FAKE_SWING"
    NEG_STOP_BEFORE_IMPACT = "NEG_STOP_BEFORE_IMPACT"
    NEG_BETWEEN_ZONES = "NEG_BETWEEN_ZONES"
    NEG_UPWARD_CROSSING = "NEG_UPWARD_CROSSING"
    NEG_TRACKING_LOSS = "NEG_TRACKING_LOSS"
    AMBIGUOUS = "AMBIGUOUS"
    EXCLUDED = "EXCLUDED"


NEGATIVE_CLASSES: frozenset[LabelClass] = frozenset(
    {
        LabelClass.NEG_NO_STRIKE_MOTION,
        LabelClass.NEG_FAKE_SWING,
        LabelClass.NEG_STOP_BEFORE_IMPACT,
        LabelClass.NEG_BETWEEN_ZONES,
        LabelClass.NEG_UPWARD_CROSSING,
        LabelClass.NEG_TRACKING_LOSS,
    }
)

INTERVAL_CLASSES: frozenset[LabelClass] = frozenset(
    {LabelClass.NEG_NO_STRIKE_MOTION, LabelClass.NEG_TRACKING_LOSS, LabelClass.NEG_BETWEEN_ZONES}
)
"""Classes that are always intervals; every other class may be an event."""

METRIC_EXCLUDED_CLASSES: frozenset[LabelClass] = frozenset({LabelClass.AMBIGUOUS, LabelClass.EXCLUDED})
"""Retained in the dataset, counted in the report, never in a metric numerator or denominator."""


class Level(StrEnum):
    EVENT = "EVENT"
    INTERVAL = "INTERVAL"


class QCStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ADJUSTED = "ADJUSTED"


class ReviewDecision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    ADJUST = "ADJUST"
    ADD = "ADD"
    DEFER = "DEFER"


class Interpolation(StrEnum):
    LINEAR = "LINEAR"
    QUADRATIC = "QUADRATIC"


class SmootherId(StrEnum):
    RTS_KALMAN_CV = "rts-kalman-cv-v1"
    RTS_KALMAN_CA = "rts-kalman-ca-v1"
    SAVGOL_CENTRED = "savgol-centred-v1"


DATASET_LABELS = {
    "PARTICIPANT": "PARTICIPANT labelled dataset (consented sessions; counts MEASURED from the listed label sets)",
    "PILOT": "PILOT labelled dataset (pilot volunteers with signed consent; not the campaign dataset)",
    "SELFTEST": "TEST / DEVELOPMENT ONLY - SYNTHETIC and/or DEV CAPTURE labels; never participant evidence",
}


# ----------------------------------------------------------------------------- hashing


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_obj(obj: Any) -> str:
    """``sha256:<hex>`` of the canonical JSON of ``obj`` (order-independent, float-exact)."""
    return "sha256:" + hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- version gating


def dataset_kind(dataset_version: str) -> str:
    """PARTICIPANT / PILOT / SELFTEST for a labelled dataset version (mirrors ``manifest.manifest_kind``)."""
    if _PARTICIPANT_DS.match(dataset_version):
        return "PARTICIPANT"
    if _PILOT_DS.match(dataset_version):
        return "PILOT"
    if _SELFTEST_DS.match(dataset_version):
        return "SELFTEST"
    raise ValueError(
        f"dataset_version {dataset_version!r} must be ds-v<M>.<m> (participant), "
        "ds-v<M>.<m>-pilot (pilot) or ds-v0.0-selftest[-<slug>] (synthetic / dev capture)"
    )


def admissible_source(dataset_version: str, source_kind: SessionKind | str) -> str | None:
    """None if a label set of ``source_kind`` may carry ``dataset_version``; else the refusal reason."""
    kind = dataset_kind(dataset_version)
    sk = SessionKind(source_kind)
    if kind == "PARTICIPANT" and sk is not SessionKind.PARTICIPANT:
        return f"{sk} label set cannot enter a participant dataset {dataset_version}"
    if kind == "PILOT" and sk is not SessionKind.PILOT:
        return f"{sk} label set cannot enter a pilot dataset {dataset_version}"
    if kind == "SELFTEST" and sk not in (SessionKind.SYNTHETIC, SessionKind.DEV_CAPTURE):
        return f"{sk} label set cannot enter a self-test dataset (participant material is never a self-test)"
    return None


def evidence_label(source_kinds: set[SessionKind | str]) -> str:
    """Evidence banner for a set of source kinds; refuses to produce one label for mixed kinds.

    The integrity rule of this project is that SYNTHETIC, DEV CAPTURE and PARTICIPANT evidence are
    reported separately and never combined into one number (integrity I-4). A caller that wants an
    aggregate must therefore group by ``source_kind`` first; this function makes the omission an
    error instead of a silently mislabelled table.
    """
    kinds = {SessionKind(k) for k in source_kinds}
    if not kinds:
        return "none (no label set)"
    if len(kinds) > 1:
        raise ValueError(
            "refusing to label evidence from mixed source kinds "
            f"{sorted(str(k) for k in kinds)}: report SYNTHETIC / DEV CAPTURE / PILOT / PARTICIPANT "
            "counts separately (integrity I-4)"
        )
    kind = next(iter(kinds))
    return {
        SessionKind.SYNTHETIC: "SYNTHETIC (generated observations; never participant evidence)",
        SessionKind.DEV_CAPTURE: "DEV CAPTURE (developer recording; never participant evidence)",
        SessionKind.PILOT: "PILOT (pilot volunteer sessions)",
        SessionKind.PARTICIPANT: "PARTICIPANT (consented campaign sessions)",
    }[kind]


# ----------------------------------------------------------------------------- provenance


@dataclass(frozen=True)
class Provenance:
    """The provenance block of every ``LabelRecord`` (Task 07.3).

    ``labels_hash`` is derived from the fields that define the label machinery, so two label sets
    with the same hash were produced by identical rules, thresholds, smoother, tracker, geometry and
    layout — the machine-checkable half of the Task 07.10 versioning rule.
    """

    rules_version: str
    rules_hash: str
    thresholds_hash: str
    smoother_id: str
    smoother_hash: str
    tracker_id: str
    tracker_hash: str
    geometry_version: str
    zone_layout_id: str
    v_min: float
    interpolation: str
    config_hash: str
    git_sha: str
    reference_track_ref: str
    causal_track_ref: str
    session_metadata_sha256: str
    generator: dict[str, str] | None = None

    def machinery(self) -> dict[str, Any]:
        """The subset that defines the label machinery (what ``labels_hash`` is computed over)."""
        return {
            "rules_version": self.rules_version,
            "rules_hash": self.rules_hash,
            "thresholds_hash": self.thresholds_hash,
            "smoother_id": self.smoother_id,
            "smoother_hash": self.smoother_hash,
            "tracker_id": self.tracker_id,
            "tracker_hash": self.tracker_hash,
            "geometry_version": self.geometry_version,
            "zone_layout_id": self.zone_layout_id,
            "v_min": float(self.v_min),
            "interpolation": self.interpolation,
        }

    @property
    def labels_hash(self) -> str:
        return sha256_obj(self.machinery())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.machinery(),
            "config_hash": self.config_hash,
            "git_sha": self.git_sha,
            "generator": dict(self.generator or GENERATOR),
            "reference_track_ref": self.reference_track_ref,
            "causal_track_ref": self.causal_track_ref,
            "session_metadata_sha256": self.session_metadata_sha256,
            "labels_hash": self.labels_hash,
        }


def empty_review() -> dict[str, Any]:
    """A never-reviewed review block (every field explicit; no field is optional in the schema)."""
    return {
        "reviewed": False,
        "reviewer_id": None,
        "adjusted": False,
        "original": None,
        "reason": None,
        "notes": "",
        "reviewed_at": None,
        "history": [],
        "second_pass": None,
        "disagreement": None,
    }


def runtime_reference(
    *,
    causal_status: TrackStatus | str | None = None,
    causal_t_impact_est: float | None = None,
    candidate_id: str | None = None,
    strike_id: str | None = None,
    arm: str | None = None,
) -> dict[str, Any]:
    """The REAL-TIME AVAILABLE SIGNALS block. Never ground truth; never copied into ``t_impact_est``."""
    return {
        "causal_status": None if causal_status is None else str(TrackStatus(causal_status)),
        "causal_t_impact_est": None if causal_t_impact_est is None else float(causal_t_impact_est),
        "candidate_id": candidate_id,
        "strike_id": strike_id,
        "arm": arm,
        "label": RUNTIME_REFERENCE_BANNER,
    }


def adjustable(record: dict[str, Any]) -> dict[str, Any]:
    """The reviewer-adjustable projection of a label (schema ``$defs/adjustable``)."""
    return {
        "t_impact_est": record["t_impact_est"],
        "t_event": record["t_event"],
        "zone_id": record["zone_id"],
        "label_class": record["label_class"],
    }


def label_id(session_id: str, hand_id: HandId | str, label_class: LabelClass | str, counter: int) -> str:
    """Deterministic label id; stable for identical inputs (Task 07.3 hash check)."""
    return f"{session_id}-{HandId(hand_id)}-{LabelClass(label_class)}-{counter:06d}"


# ----------------------------------------------------------------------------- validation helpers


def validate_label(record: dict[str, Any]) -> list[str]:
    return contract_schema.errors("label-record", record)


def validate_reference_header(header: dict[str, Any]) -> list[str]:
    return contract_schema.errors("reference-track", header)


@cache
def _subschema_validator(stem: str, pointer: str) -> jsonschema.Draft202012Validator:
    """Validator for one ``$defs`` entry of a schema file (the sample lines of a reference track are
    defined inside ``reference-track.schema.json``, not as a file of their own)."""
    schema = contract_schema.load_schemas()[stem]
    return jsonschema.Draft202012Validator(
        {"$ref": f"{schema['$id']}#{pointer}"},
        registry=contract_schema.registry(),
        format_checker=jsonschema.FormatChecker(),
    )


def validate_reference_sample(sample: dict[str, Any]) -> list[str]:
    v = _subschema_validator("reference-track", "/$defs/sample")
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in v.iter_errors(sample)]


def validate_label_set(doc: dict[str, Any]) -> list[str]:
    errs = contract_schema.errors("label-set", doc)
    if not errs and doc.get("set_hash") != label_set_hash(doc):
        errs.append("set_hash does not match the document")
    return errs


def validate_review_entry(entry: dict[str, Any]) -> list[str]:
    return contract_schema.errors("label-review", entry)


def label_set_hash(doc: dict[str, Any]) -> str:
    """Hash of a label-set document without its own hash and its wall-clock stamp."""
    body = {k: v for k, v in doc.items() if k not in ("set_hash", "generated_at")}
    return sha256_obj(body)


__all__ = [
    "CAUSAL_TRACK_FILENAME",
    "DATASET_LABELS",
    "DATASET_VERSION_NONE",
    "GENERATOR",
    "GEOMETRY_VERSION",
    "INTERVAL_CLASSES",
    "LABELS_DIRNAME",
    "LABELS_FILENAME",
    "LABELS_VERSION",
    "LABEL_RECORD_SCHEMA_VERSION",
    "LABEL_REVIEW_SCHEMA_VERSION",
    "LABEL_SET_FILENAME",
    "LABEL_SET_SCHEMA_VERSION",
    "METRIC_EXCLUDED_CLASSES",
    "NEGATIVE_CLASSES",
    "REFERENCE_TRACK_BANNER",
    "REFERENCE_TRACK_FILENAME",
    "REFERENCE_TRACK_SCHEMA_VERSION",
    "REVIEW_FILENAME",
    "RULES_VERSION",
    "RUNTIME_REFERENCE_BANNER",
    "Interpolation",
    "LabelClass",
    "Level",
    "Provenance",
    "QCStatus",
    "ReviewDecision",
    "SmootherId",
    "adjustable",
    "admissible_source",
    "canonical_json",
    "dataset_kind",
    "empty_review",
    "evidence_label",
    "label_id",
    "label_set_hash",
    "runtime_reference",
    "sha256_file",
    "sha256_obj",
    "sha256_text",
    "validate_label",
    "validate_label_set",
    "validate_reference_header",
    "validate_reference_sample",
    "validate_review_entry",
]
