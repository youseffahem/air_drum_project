"""``SessionMetadata`` (Phase 06, Task 06.4) — the Python mirror of ``schemas/session-metadata.schema.json``.

The JSON Schema is the contract (ADR-0012); this module builds, validates, reads and writes the
document and adds the invariants the schema cannot express (segment-marker integrity, the
``has_phys_gt`` three-level rule of contracts.md section 6, consistency between ``pad_mic`` and the
PAD segments, tip-method condition). Nothing here fills a participant field with a guess: the
``new()`` factory takes the session kind and produces the *explicit* NOT_COLLECTED / null / PENDING
representations for everything that was not supplied, and the schema's conditional rules refuse a
SYNTHETIC or DEV_CAPTURE session that carries participant-style identifiers, consent or dataset
versions.

Session kinds: ``SYNTHETIC`` (generated observations, never a recording), ``DEV_CAPTURE``
(developer-only material; never a dataset), ``PILOT`` (pilot volunteer; enters a dataset only with
signed consent), ``PARTICIPANT`` (consented participant). ``session_id`` / ``participant_id`` follow
docs/repo-layout.md section 3.5 (``P07-S2``) with the ``PILOT<NN>``, ``DEV`` and ``SYNTHETIC``
extensions of the schema.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from spacedrums.contracts import Arm, TipMethod
from spacedrums.contracts import schema as contract_schema
from spacedrums.data.protocol import (
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    SegmentCondition,
    SegmentSpec,
    SegmentType,
    check_segment_markers,
)

SCHEMA_STEM = "session-metadata"
SESSION_METADATA_SCHEMA_VERSION = "1.0"
METADATA_FILENAME = "metadata.json"
DATASET_VERSION_NONE = "ds-none-v0.0"
GENERATOR = {"tool": "spacedrums.data.recorder", "version": "0.6.0"}


class SessionKind(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    DEV_CAPTURE = "DEV_CAPTURE"
    PILOT = "PILOT"
    PARTICIPANT = "PARTICIPANT"


class ConsentStatus(StrEnum):
    SIGNED = "SIGNED"
    PENDING = "PENDING"
    NOT_REQUIRED = "NOT_REQUIRED"
    WITHDRAWN = "WITHDRAWN"


class SegmentStatus(StrEnum):
    RECORDED = "RECORDED"
    RETAKEN = "RETAKEN"
    ABORTED = "ABORTED"
    SKIPPED = "SKIPPED"


NOT_COLLECTED = "NOT_COLLECTED"


def participant_meta_not_collected(kind: SessionKind) -> dict[str, Any]:
    return {
        "handedness": NOT_COLLECTED,
        "experience": NOT_COLLECTED,
        "height_range": NOT_COLLECTED,
        "source": "NOT_APPLICABLE"
        if kind in (SessionKind.SYNTHETIC, SessionKind.DEV_CAPTURE)
        else NOT_COLLECTED,
    }


def default_lighting(
    kind: SessionKind, lighting_id: str | None = None, description: str = ""
) -> dict[str, Any]:
    if kind is SessionKind.SYNTHETIC:
        lid, desc = "SYNTHETIC", "no camera: generated observations"
    else:
        lid, desc = (lighting_id or "L0"), description
    return {
        "id": lid,
        "description": desc,
        "mean_luminance_auto": None,
        "auto_exposure_unique_fps": None,
        "exposure_used": None,
        "flicker_note": "",
        "second_condition_id": None,
    }


def default_background(kind: SessionKind, tag: str | None = None, description: str = "") -> dict[str, Any]:
    if kind is SessionKind.SYNTHETIC:
        return {"tag": "SYNTHETIC", "people_present": None, "description": "no camera"}
    return {"tag": tag or "UNSPECIFIED", "people_present": None, "description": description}


def default_sticks(kind: SessionKind) -> dict[str, Any]:
    if kind is SessionKind.SYNTHETIC:
        return {"colour": "", "length_class": "NONE", "marker": "NONE", "ownership": "NONE"}
    return {"colour": "", "length_class": "UNSPECIFIED", "marker": "NONE", "ownership": "OWN"}


def session_id_for(
    kind: SessionKind, participant_id: str, session_index: int, slug: str | None = None
) -> str:
    """Automatic session naming (Task 06.1): ``P07-S2`` / ``PILOT01-S1`` / ``dev-<slug>`` /
    ``synthetic-<slug>``."""
    kind = SessionKind(kind)
    if kind is SessionKind.PARTICIPANT or kind is SessionKind.PILOT:
        return f"{participant_id}-S{int(session_index)}"
    if not slug:
        raise ValueError(f"{kind} sessions need a slug for the session id")
    return f"{'dev' if kind is SessionKind.DEV_CAPTURE else 'synthetic'}-{slug}"


def participant_id_for(kind: SessionKind, participant_id: str | None) -> str:
    kind = SessionKind(kind)
    if kind is SessionKind.SYNTHETIC:
        return "SYNTHETIC"
    if kind is SessionKind.DEV_CAPTURE:
        return "DEV"
    if not participant_id:
        raise ValueError(f"{kind} sessions need a participant pseudonym (P<NN> / PILOT<NN>)")
    return participant_id


@dataclass
class SessionMetadata:
    """Mutable builder around the schema document (``data`` is exactly what is written to disk)."""

    data: dict[str, Any] = field(default_factory=dict)

    # -- construction ----------------------------------------------------------------------
    @classmethod
    def new(
        cls,
        *,
        kind: SessionKind | str,
        session_id: str,
        participant_id: str,
        session_index: int,
        date: str,
        started_at: str,
        t_mono_at_start: float,
        hardware_id: str,
        camera_profile_id: str,
        audio_profile_id: str,
        roi_px: tuple[int, int, int, int] | list[int],
        config_hash: str,
        git_sha: str,
        clock_id: str,
        zone_layout_id: str,
        arm_active: Arm | str,
        arms_shadow: tuple[Arm | str, ...] | list[Arm | str],
        tip_method_active: TipMethod | str,
        protocol: dict[str, Any] | None,
        source: dict[str, Any],
        video: dict[str, Any],
        location_tag: str = "",
        distance_mark: dict[str, Any] | None = None,
        lighting: dict[str, Any] | None = None,
        background: dict[str, Any] | None = None,
        stick_description: dict[str, Any] | None = None,
        participant_meta: dict[str, Any] | None = None,
        consent_status: ConsentStatus | str | None = None,
        consent_record_id: str | None = None,
        pad_zone_id: str | None = None,
        operator_notes: str = "",
        dataset_version: str = DATASET_VERSION_NONE,
        generator: dict[str, str] | None = None,
    ) -> SessionMetadata:
        kind = SessionKind(kind)
        if consent_status is None:
            consent_status = (
                ConsentStatus.NOT_REQUIRED
                if kind in (SessionKind.SYNTHETIC, SessionKind.DEV_CAPTURE)
                else ConsentStatus.PENDING
            )
        tip = TipMethod(tip_method_active)
        if protocol is None:
            protocol = {
                "protocol_id": PROTOCOL_ID,
                "version": PROTOCOL_VERSION,
                "seed": 0,
                "seed_source": "none",
                "zone_order": [],
                "options": {},
            }
        d: dict[str, Any] = {
            "schema_version": SESSION_METADATA_SCHEMA_VERSION,
            "dataset_version": dataset_version,
            "session_kind": str(kind),
            "session_id": session_id,
            "participant_id": participant_id,
            "participant_meta": participant_meta or participant_meta_not_collected(kind),
            "session_index": int(session_index),
            "date": date,
            "started_at": started_at,
            "t_mono_at_start": float(t_mono_at_start),
            "finished_at": None,
            "location_tag": location_tag
            or ("none (synthetic)" if kind is SessionKind.SYNTHETIC else "unspecified"),
            "hardware_id": hardware_id,
            "camera_profile_id": camera_profile_id,
            "audio_profile_id": audio_profile_id,
            "measured_fps": None,
            "roi_px": [int(v) for v in roi_px],
            "distance_mark": distance_mark
            or {
                "label": "none (synthetic)" if kind is SessionKind.SYNTHETIC else "unspecified",
                "nominal_distance_m": None,
                "second_mark_label": None,
                "second_mark_nominal_distance_m": None,
            },
            "lighting": lighting or default_lighting(kind),
            "background": background or default_background(kind),
            "stick_description": stick_description or default_sticks(kind),
            "tip_method_active": str(tip),
            "tip_method_condition": "MARKER" if tip is TipMethod.MARKER else "MARKERLESS",
            "arm_active": str(Arm(arm_active)),
            "arms_shadow": [str(Arm(a)) for a in arms_shadow],
            "fallback_events": [],
            "config_hash": config_hash,
            "git_sha": git_sha,
            "clock_id": clock_id,
            "zone_layout_id": zone_layout_id,
            "protocol": protocol,
            "segments": [],
            "pad_mic": {
                "present": pad_zone_id is not None,
                "zone_id": pad_zone_id,
                "sync_markers": [],
                "audio_track": None,
            },
            "has_phys_gt": False,
            "audio_track_ref": None,
            "audio_alignment_residual_s": None,
            "capture_stats": None,
            "video": video,
            "consent_status": str(ConsentStatus(consent_status)),
            "consent_record_id": consent_record_id,
            "source": source,
            "generator": dict(generator or GENERATOR),
            "operator_notes": operator_notes,
            "quality_flags": [],
        }
        return cls(d)

    # -- segments ----------------------------------------------------------------------------
    def open_segment(self, spec: SegmentSpec, t_start: float, take: int) -> dict[str, Any]:
        """Append an open marker (``t_end`` null, status RECORDED until closed or superseded)."""
        seg = {
            "segment_id": spec.segment_id,
            "type": str(spec.type),
            "take": int(take),
            "t_start": float(t_start),
            "t_end": None,
            "condition": str(spec.condition),
            "pad_zone_id": spec.pad_zone_id,
            "status": str(SegmentStatus.ABORTED),  # until closed
            "cue": spec.cue,
            "zone_ids": list(spec.zone_ids),
            "hands": [str(h) for h in spec.hands],
            "tempo_bpm": spec.tempo_bpm,
            "notes": "",
            "quick_check": None,
        }
        self.data["segments"].append(seg)
        return seg

    def close_segment(self, seg: dict[str, Any], t_end: float, quick_check: dict[str, Any] | None) -> None:
        seg["t_end"] = float(t_end)
        seg["status"] = str(SegmentStatus.RECORDED)
        seg["quick_check"] = quick_check

    def mark_retaken(self, segment_id: str) -> None:
        """Flag every earlier take of ``segment_id`` as RETAKEN (kept, never deleted; Task 06.8)."""
        for seg in self.data["segments"]:
            if seg["segment_id"] == segment_id and seg["status"] == str(SegmentStatus.RECORDED):
                seg["status"] = str(SegmentStatus.RETAKEN)

    def add_skipped(self, spec: SegmentSpec, t: float, note: str) -> None:
        seg = self.open_segment(spec, t, take=1 + self.takes_of(spec.segment_id))
        seg["t_end"] = float(t)
        seg["status"] = str(SegmentStatus.SKIPPED)
        seg["notes"] = note

    def takes_of(self, segment_id: str) -> int:
        return sum(1 for s in self.data["segments"] if s["segment_id"] == segment_id)

    def add_sync_marker(
        self, kind: str, t_mono: float, segment_id: str | None, note: str = ""
    ) -> dict[str, Any]:
        markers = self.data["pad_mic"]["sync_markers"]
        m = {
            "marker_id": f"sync-{len(markers) + 1:03d}",
            "kind": kind,
            "t_mono": float(t_mono),
            "segment_id": segment_id,
            "note": note,
        }
        markers.append(m)
        return m

    def add_fallback_event(self, t: float, kind: str, note: str = "") -> None:
        self.data["fallback_events"].append({"t": float(t), "kind": kind, "note": note})

    def add_quality_flag(self, flag: str) -> None:
        if flag not in self.data["quality_flags"]:
            self.data["quality_flags"].append(flag)

    def set_audio_track(self, info: dict[str, Any], residual_s: float | None) -> None:
        """Record the microphone track; ``has_phys_gt`` follows the contracts.md section 6 rule."""
        self.data["pad_mic"]["audio_track"] = info
        self.data["audio_track_ref"] = info["path"]
        self.data["audio_alignment_residual_s"] = residual_s
        self.refresh_has_phys_gt()

    def refresh_has_phys_gt(self) -> None:
        has_pad_segment = any(s["condition"] == str(SegmentCondition.PAD) for s in self.data["segments"])
        self.data["has_phys_gt"] = bool(
            self.data["pad_mic"]["present"]
            and self.data["audio_track_ref"] is not None
            and self.data["audio_alignment_residual_s"] is not None
            and has_pad_segment
        )

    def finish(self, finished_at: str, capture_stats: dict[str, Any] | None = None) -> None:
        self.data["finished_at"] = finished_at
        if capture_stats is not None:
            self.data["capture_stats"] = capture_stats
        self.refresh_has_phys_gt()

    # -- validation ------------------------------------------------------------------------
    def errors(self) -> list[str]:
        return validate_metadata(self.data)

    def validate(self) -> None:
        errs = self.errors()
        if errs:
            raise ValueError("SessionMetadata invalid: " + "; ".join(errs))

    # -- I/O ---------------------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionMetadata:
        if d.get("schema_version") != SESSION_METADATA_SCHEMA_VERSION:
            raise ValueError(f"unsupported SessionMetadata schema_version {d.get('schema_version')!r}")
        return cls(copy.deepcopy(d))

    def write(self, session_dir: str | Path, *, validate: bool = True) -> Path:
        if validate:
            self.validate()
        path = Path(session_dir) / METADATA_FILENAME
        path.write_text(json.dumps(self.data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return path

    @classmethod
    def read(cls, session_dir: str | Path) -> SessionMetadata:
        path = Path(session_dir) / METADATA_FILENAME
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @property
    def kind(self) -> SessionKind:
        return SessionKind(self.data["session_kind"])

    @property
    def session_id(self) -> str:
        return self.data["session_id"]

    @property
    def label(self) -> str:
        return classification_label(self.kind)


def classification_label(kind: SessionKind | str) -> str:
    """The evidence label every report must print next to a session (integrity I-4)."""
    return {
        SessionKind.SYNTHETIC: (
            "SYNTHETIC - generated observations; not a recording; not participant evidence"
        ),
        SessionKind.DEV_CAPTURE: "DEV CAPTURE - developer material; not participant data; not a dataset",
        SessionKind.PILOT: "PILOT - pilot volunteer; counted as a participant only with signed consent",
        SessionKind.PARTICIPANT: "PARTICIPANT - consented participant session",
    }[SessionKind(kind)]


# ----------------------------------------------------------------------------- validation


def validate_metadata(d: dict[str, Any]) -> list[str]:
    """Schema errors plus the invariants JSON Schema cannot express. Empty list == valid."""
    errs = contract_schema.errors(SCHEMA_STEM, d)
    if errs:
        return errs
    problems: list[str] = []
    segments = d["segments"]
    closed = [s for s in segments if s["t_end"] is not None]
    problems += [f"segments: {p}" for p in check_segment_markers(closed)]
    for s in segments:
        if s["status"] == str(SegmentStatus.ABORTED) and s["t_end"] is not None:
            problems.append(f"segments/{s['segment_id']}: ABORTED segment carries a t_end")
        if s["status"] in (str(SegmentStatus.RECORDED), str(SegmentStatus.RETAKEN)) and s["t_end"] is None:
            problems.append(f"segments/{s['segment_id']}: closed status without t_end")
        try:
            SegmentType(s["type"])
        except ValueError:
            problems.append(f"segments/{s['segment_id']}: unknown type {s['type']!r}")
        if s["t_start"] < d["t_mono_at_start"] - 1e-9:
            problems.append(f"segments/{s['segment_id']}: starts before t_mono_at_start")
    # re-take rule: every earlier take of a repeated id must be RETAKEN, the last one not
    by_id: dict[str, list[dict[str, Any]]] = {}
    for s in segments:
        by_id.setdefault(s["segment_id"], []).append(s)
    for sid, takes in by_id.items():
        for s in takes[:-1]:
            if s["status"] == str(SegmentStatus.RECORDED):
                problems.append(f"segments/{sid}: take {s['take']} superseded but not flagged RETAKEN")
        if takes[-1]["status"] == str(SegmentStatus.RETAKEN):
            problems.append(f"segments/{sid}: last take flagged RETAKEN without a later take")
    # has_phys_gt three-level rule (contracts.md section 6)
    pad = d["pad_mic"]
    has_pad_segment = any(s["condition"] == "PAD" for s in segments)
    expected = bool(
        pad["present"]
        and d["audio_track_ref"] is not None
        and d["audio_alignment_residual_s"] is not None
        and has_pad_segment
    )
    if d["has_phys_gt"] != expected:
        problems.append(
            f"has_phys_gt is {d['has_phys_gt']} but the availability rule gives {expected} "
            "(pad present, audio_track_ref, alignment residual, >= 1 PAD segment)"
        )
    if has_pad_segment and not pad["present"]:
        problems.append("a PAD segment exists but pad_mic.present is false")
    for s in segments:
        if s["condition"] == "PAD" and pad["present"] and s["pad_zone_id"] != pad["zone_id"]:
            problems.append(f"segments/{s['segment_id']}: pad_zone_id differs from pad_mic.zone_id")
    if (pad["audio_track"] is None) != (d["audio_track_ref"] is None):
        problems.append("audio_track_ref and pad_mic.audio_track must be set together")
    if pad["audio_track"] is not None and pad["audio_track"]["path"] != d["audio_track_ref"]:
        problems.append("audio_track_ref must equal pad_mic.audio_track.path")
    if d["finished_at"] is not None and d["started_at"] > d["finished_at"]:
        problems.append("finished_at precedes started_at")
    return problems


__all__ = [
    "DATASET_VERSION_NONE",
    "GENERATOR",
    "METADATA_FILENAME",
    "NOT_COLLECTED",
    "SESSION_METADATA_SCHEMA_VERSION",
    "ConsentStatus",
    "SegmentStatus",
    "SessionKind",
    "SessionMetadata",
    "classification_label",
    "default_background",
    "default_lighting",
    "default_sticks",
    "participant_id_for",
    "participant_meta_not_collected",
    "session_id_for",
    "validate_metadata",
]
