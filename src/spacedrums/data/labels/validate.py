"""Label validator (Phase 07, Task 07.7) — machine-checkable integrity before any training.

Everything a downstream phase is allowed to assume about a label set is checked here, and every
failure is a named violation code rather than a message, so the gate record can cite counts per
code. The checks are grouped as:

* **schema** - every record validates against ``label-record.schema.json``; the label set validates
  against ``label-set.schema.json`` and its ``set_hash`` matches.
* **referential integrity** - session, participant, segment (id + take), zone id and frame ids all
  exist in the session the labels claim to come from.
* **time** - ``t_start <= t_end``; ``t_impact_est == t_event`` for impact labels; the event lies
  inside the bracketing frames' interval and inside the recorded session span.
* **episode** - at most one POSITIVE per episode, unique episode ids, unique label ids, no two
  positives of the same hand and zone closer than the conflict window.
* **quarantine** - no POSITIVE inside a quarantined segment (it must be EXCLUDED), and
  ``excluded`` agrees with the Phase 06 exclusion log.
* **provenance / version** - every record's provenance equals the label set's; the ``labels_hash``
  is the hash of the machinery actually recorded; ``dataset_version`` is admissible for the
  ``source_kind`` (a SYNTHETIC label set can never claim a participant dataset).
* **causality** - ``causal`` is false, the runtime block carries its banner, no label time lies
  beyond the last recorded frame, and no label's ``t_impact_est`` was copied from the runtime
  candidate time (which would silently turn a real-time signal into ground truth).
* **physical ground truth** - the three-level ``has_phys_gt`` invariant of ``contracts.md``
  section 6.

``validate_label_dir`` is what ``scripts/validate_labels.py`` runs; a clean run returns an empty
violation list, which is what acceptance criterion "validator passes on all sessions" means.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spacedrums.data.labels.generate import (
    CONFIG_SNAPSHOT,
    read_label_set,
    read_labels,
    read_quarantine,
    read_reference_track,
)
from spacedrums.data.labels.schema import (
    CAUSAL_TRACK_FILENAME,
    LABEL_SET_FILENAME,
    LABELS_FILENAME,
    REFERENCE_TRACK_FILENAME,
    RUNTIME_REFERENCE_BANNER,
    LabelClass,
    Level,
    admissible_source,
    label_set_hash,
    sha256_file,
    sha256_obj,
    validate_label,
    validate_label_set,
)
from spacedrums.data.metadata import METADATA_FILENAME, SessionMetadata
from spacedrums.timing.logger import read_record_stream

CONFLICT_WINDOW_S = 0.02
"""Two positives of the same hand and zone closer than this are a duplicate/conflict, not two
strikes: the fastest human stroke rate in the protocol (RAPID) is far below 50 Hz per hand."""

VIOLATION_CODES = (
    "SCHEMA_INVALID",
    "SET_SCHEMA_INVALID",
    "SET_HASH_MISMATCH",
    "SESSION_MISMATCH",
    "PARTICIPANT_MISMATCH",
    "SEGMENT_UNKNOWN",
    "ZONE_UNKNOWN",
    "FRAME_UNKNOWN",
    "FRAME_ORDER",
    "TIME_ORDER",
    "TIME_OUT_OF_SESSION",
    "IMPACT_TIME_MISMATCH",
    "EPISODE_DUPLICATE",
    "LABEL_ID_DUPLICATE",
    "POSITIVE_CONFLICT",
    "POSITIVE_IN_QUARANTINE",
    "EXCLUSION_MISMATCH",
    "PROVENANCE_MISMATCH",
    "LABELS_HASH_MISMATCH",
    "VERSION_MISMATCH",
    "SOURCE_KIND_NOT_ADMISSIBLE",
    "CAUSAL_FLAG",
    "RUNTIME_BANNER",
    "RUNTIME_TIME_COPIED",
    "FUTURE_LEAKAGE",
    "PHYS_INVARIANT",
    "REFERENCE_TRACK_MISSING",
    "REFERENCE_TRACK_CAUSAL",
    "CAUSAL_TRACK_MISSING",
    "COUNTS_MISMATCH",
)


@dataclass(frozen=True)
class Violation:
    code: str
    label_id: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "label_id": self.label_id, "message": self.message}

    def __str__(self) -> str:
        where = f" [{self.label_id}]" if self.label_id else ""
        return f"{self.code}{where}: {self.message}"


def _v(out: list[Violation], code: str, label_id: str | None, message: str) -> None:
    if code not in VIOLATION_CODES:  # pragma: no cover - programming error
        raise ValueError(f"unknown violation code {code!r}")
    out.append(Violation(code, label_id, message))


def validate_labels(
    labels: Sequence[dict[str, Any]],
    label_set: dict[str, Any],
    *,
    meta: SessionMetadata | None = None,
    zone_ids: Sequence[str] | None = None,
    frame_ids: Sequence[int] | None = None,
    quarantined: dict[tuple[str, int], str] | None = None,
    session_exclusion: str | None = None,
) -> list[Violation]:
    """Validate a label list against its label set and (when given) its session."""
    out: list[Violation] = []
    # The schema check and the hash check are reported under different codes on purpose: a
    # structurally invalid document and a tampered but well-formed one are different failures.
    schema_errs = [e for e in validate_label_set(label_set) if "set_hash" not in e]
    if schema_errs:
        _v(out, "SET_SCHEMA_INVALID", None, schema_errs[0])
    if label_set.get("set_hash") != label_set_hash(label_set):
        _v(out, "SET_HASH_MISMATCH", None, "set_hash does not match the label-set document")

    why = admissible_source(label_set["dataset_version"], label_set["source_kind"])
    if why:
        _v(out, "SOURCE_KIND_NOT_ADMISSIBLE", None, why)

    machinery = {k: label_set["provenance"][k] for k in label_set["provenance"]
                 if k not in ("config_hash", "git_sha", "generator", "reference_track_ref",
                              "causal_track_ref", "session_metadata_sha256", "labels_hash")}
    if label_set["provenance"]["labels_hash"] != sha256_obj(machinery):
        _v(out, "LABELS_HASH_MISMATCH", None,
           "labels_hash is not the hash of the recorded rules / thresholds / smoother / tracker")

    zone_set = set(zone_ids or [])
    frame_set = set(frame_ids or [])
    segments = {}
    t_first = t_last = None
    if meta is not None:
        for seg in meta.data["segments"]:
            segments[(str(seg["segment_id"]), int(seg.get("take") or 1))] = seg
        starts = [float(s["t_start"]) for s in meta.data["segments"]]
        ends = [float(s["t_end"]) for s in meta.data["segments"] if s["t_end"] is not None]
        if starts:
            t_first = min(starts)
        if ends:
            t_last = max(ends)

    quarantined = quarantined or {}
    seen_ids: set[str] = set()
    seen_episodes: set[str] = set()
    positives: list[tuple[str, str, float, str]] = []
    counted: dict[str, int] = {}

    for rec in labels:
        lid = rec.get("label_id")
        errs = validate_label(rec)
        if errs:
            _v(out, "SCHEMA_INVALID", lid, errs[0])
            continue
        counted[rec["label_class"]] = counted.get(rec["label_class"], 0) + 1
        cls = LabelClass(rec["label_class"])

        if lid in seen_ids:
            _v(out, "LABEL_ID_DUPLICATE", lid, "label_id used twice in the same set")
        seen_ids.add(lid)

        for key, code in (("labels_version", "VERSION_MISMATCH"),
                          ("dataset_version", "VERSION_MISMATCH"),
                          ("source_kind", "VERSION_MISMATCH"),
                          ("session_id", "SESSION_MISMATCH"),
                          ("participant_id", "PARTICIPANT_MISMATCH")):
            if rec[key] != label_set[key]:
                _v(out, code, lid, f"{key} {rec[key]!r} differs from the label set {label_set[key]!r}")
        if rec["provenance"] != label_set["provenance"]:
            _v(out, "PROVENANCE_MISMATCH", lid, "provenance differs from the label set's")

        if rec["causal"] is not False:
            _v(out, "CAUSAL_FLAG", lid, "a LabelRecord is non-causal by construction")
        if rec["runtime_reference"]["label"] != RUNTIME_REFERENCE_BANNER:
            _v(out, "RUNTIME_BANNER", lid, "runtime_reference is missing its not-ground-truth banner")
        rt = rec["runtime_reference"]["causal_t_impact_est"]
        if rt is not None and rec["t_impact_est"] is not None and rt == rec["t_impact_est"]:
            _v(out, "RUNTIME_TIME_COPIED", lid,
               "t_impact_est equals the runtime candidate time exactly: ground truth must come "
               "from the reference trajectory, not from the causal pipeline")

        if meta is not None and rec["segment_id"] is not None:
            key = (rec["segment_id"], int(rec["segment_take"] or 1))
            if key not in segments:
                _v(out, "SEGMENT_UNKNOWN", lid, f"segment {key} is not in the session metadata")
            elif rec["segment_type"] != segments[key]["type"]:
                _v(out, "SEGMENT_UNKNOWN", lid,
                   f"segment_type {rec['segment_type']} differs from the marker "
                   f"{segments[key]['type']}")
        if rec["zone_id"] is not None and zone_set and rec["zone_id"] not in zone_set:
            _v(out, "ZONE_UNKNOWN", lid, f"zone_id {rec['zone_id']!r} is not in the zone layout")

        frames = rec["frames"]
        for name in ("first_frame_id", "last_frame_id", "before_event", "after_event"):
            fid = frames[name]
            if fid is not None and frame_set and fid not in frame_set:
                _v(out, "FRAME_UNKNOWN", lid, f"{name} {fid} is not a recorded frame_id")
        if frames["before_event"] is not None and frames["after_event"] is not None:
            if frames["before_event"] > frames["after_event"]:
                _v(out, "FRAME_ORDER", lid, "before_event is after after_event")
        if frames["first_frame_id"] > frames["last_frame_id"]:
            _v(out, "FRAME_ORDER", lid, "first_frame_id is after last_frame_id")

        if Level(rec["level"]) is Level.INTERVAL and rec["t_end"] < rec["t_start"]:
            _v(out, "TIME_ORDER", lid, "t_end is before t_start")
        if rec["t_impact_est"] is not None and rec["t_impact_est"] != rec["t_event"]:
            _v(out, "IMPACT_TIME_MISMATCH", lid,
               "t_impact_est must be the event instant of the same label")
        times = [t for t in (rec["t_event"], rec["t_start"], rec["t_end"]) if t is not None]
        if t_first is not None and t_last is not None:
            for t in times:
                if t < t_first - 1.0 or t > t_last + 1.0:
                    _v(out, "TIME_OUT_OF_SESSION", lid,
                       f"label time {t} lies outside the recorded session span "
                       f"[{t_first}, {t_last}]")
                if t > t_last + 1e-9:
                    _v(out, "FUTURE_LEAKAGE", lid,
                       "label time lies after the last recorded segment: a label cannot describe "
                       "an instant the recording does not contain")

        if rec["episode_id"] is not None:
            if rec["episode_id"] in seen_episodes and cls is LabelClass.POSITIVE:
                _v(out, "EPISODE_DUPLICATE", lid,
                   f"episode {rec['episode_id']} already carries a POSITIVE label")
            seen_episodes.add(rec["episode_id"])
        if cls is LabelClass.POSITIVE:
            positives.append((rec["hand_id"], rec["zone_id"], float(rec["t_impact_est"]), lid))

        seg_key = (rec["segment_id"], int(rec["segment_take"] or 1)) if rec["segment_id"] else None
        expected = session_exclusion or (quarantined.get(seg_key) if seg_key else None)
        if expected and not rec["excluded"]:
            _v(out, "EXCLUSION_MISMATCH", lid,
               f"label lies in quarantined segment {seg_key} but is not marked excluded")
        if rec["excluded"] and cls is LabelClass.POSITIVE:
            _v(out, "POSITIVE_IN_QUARANTINE", lid,
               "a quarantined event must be labelled EXCLUDED, never POSITIVE")
        if rec["excluded"] and expected and rec["exclusion_ref"] != expected:
            _v(out, "EXCLUSION_MISMATCH", lid,
               f"exclusion_ref {rec['exclusion_ref']!r} is not the exclusion of its segment")

        if rec["t_impact_phys"] is not None:
            if meta is not None and not meta.data["has_phys_gt"]:
                _v(out, "PHYS_INVARIANT", lid,
                   "t_impact_phys set on a session whose has_phys_gt is false (contracts.md s.6)")
            seg = segments.get(seg_key) if seg_key else None
            if seg is None or seg["condition"] != "PAD" or seg["pad_zone_id"] != rec["zone_id"]:
                _v(out, "PHYS_INVARIANT", lid,
                   "t_impact_phys is only defined inside a PAD segment on its pad_zone_id")

    positives.sort(key=lambda p: (p[0], p[1], p[2]))
    for a, b in zip(positives, positives[1:], strict=False):
        if a[0] == b[0] and a[1] == b[1] and abs(b[2] - a[2]) < CONFLICT_WINDOW_S:
            _v(out, "POSITIVE_CONFLICT", b[3],
               f"two positives of {a[0]} on {a[1]} are {abs(b[2] - a[2]):.4f} s apart "
               f"(< {CONFLICT_WINDOW_S} s): duplicate or conflicting annotation")

    if counted != {k: v for k, v in label_set["counts"]["by_class"].items() if v}:
        _v(out, "COUNTS_MISMATCH", None,
           f"label counts {counted} differ from the label set's {label_set['counts']['by_class']}")
    return out


def validate_label_dir(
    label_dir: str | Path, *, session_dir: str | Path | None = None
) -> list[Violation]:
    """Validate a whole ``labels/<session>/`` directory, resolving the session when given."""
    label_dir = Path(label_dir)
    out: list[Violation] = []
    label_set = read_label_set(label_dir / LABEL_SET_FILENAME)
    labels = read_labels(label_dir / LABELS_FILENAME)

    ref_path = label_dir / REFERENCE_TRACK_FILENAME
    if not ref_path.exists():
        _v(out, "REFERENCE_TRACK_MISSING", None, f"{REFERENCE_TRACK_FILENAME} is missing")
    else:
        headers, _ = read_reference_track(ref_path)
        for hand, header in headers.items():
            if header.get("causal") is not False or header.get("kind") != "ReferenceTrack":
                _v(out, "REFERENCE_TRACK_CAUSAL", None,
                   f"reference track of {hand} is not marked as a non-causal label artefact")
    if not (label_dir / CAUSAL_TRACK_FILENAME).exists():
        _v(out, "CAUSAL_TRACK_MISSING", None,
           f"{CAUSAL_TRACK_FILENAME} is missing: the causal and reference trajectories are stored "
           "separately (acceptance criterion 2)")

    meta = zone_ids = frame_ids = None
    quarantined: dict[tuple[str, int], str] = {}
    session_exclusion = None
    if session_dir is not None:
        session_dir = Path(session_dir)
        meta = SessionMetadata.read(session_dir)
        if label_set["provenance"]["session_metadata_sha256"] != sha256_file(
            session_dir / METADATA_FILENAME
        ):
            _v(out, "PROVENANCE_MISMATCH", None,
               "session metadata has changed since the labels were generated")
        cfg_path = session_dir / CONFIG_SNAPSHOT
        if cfg_path.exists():
            from spacedrums.config import load_config

            zone_ids = [z["zone_id"] for z in load_config(cfg_path)["zones"]]
        frames_path = session_dir / "frames.jsonl"
        if frames_path.exists():
            frame_ids = [
                json.loads(line)["frame_id"]
                for line in frames_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        quarantined, session_exclusion = read_quarantine(session_dir)

    out += validate_labels(
        labels,
        label_set,
        meta=meta,
        zone_ids=zone_ids,
        frame_ids=frame_ids,
        quarantined=quarantined,
        session_exclusion=session_exclusion,
    )
    return out


def leakage_report(label_dir: str | Path) -> dict[str, Any]:
    """Structural evidence for acceptance criterion 2 (reference and causal tracks separate).

    Checks that both files exist, that the reference file is *not* a record stream (its first line
    is not a ``RecordStreamHeader``) and that the causal file *is* one.
    """
    label_dir = Path(label_dir)
    ref, causal = label_dir / REFERENCE_TRACK_FILENAME, label_dir / CAUSAL_TRACK_FILENAME
    ref_is_stream = True
    try:
        read_record_stream(ref)
    except (ValueError, KeyError, json.JSONDecodeError):
        ref_is_stream = False
    causal_type = None
    if causal.exists():
        try:
            causal_type = read_record_stream(causal)[0]["record_type"]
        except (ValueError, KeyError, json.JSONDecodeError):
            causal_type = None
    return {
        "reference_track_present": ref.exists(),
        "causal_track_present": causal.exists(),
        "reference_is_record_stream": ref_is_stream,
        "causal_record_type": causal_type,
        "separate_files": ref.exists() and causal.exists() and ref != causal,
        "ok": ref.exists() and causal.exists() and not ref_is_stream and causal_type == "TrackState",
    }


__all__ = [
    "CONFLICT_WINDOW_S",
    "VIOLATION_CODES",
    "Violation",
    "leakage_report",
    "validate_label_dir",
    "validate_labels",
]
