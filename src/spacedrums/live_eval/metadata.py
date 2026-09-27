"""``LiveSessionMetadata`` (Phase 18 Interfaces / Contracts): the Python mirror of
``schemas/live-session-metadata.schema.json``.

The phase document says ``LiveSessionMetadata`` *extends* ``SessionMetadata``. The Phase 06
document is closed (``additionalProperties: false``), so the extension is by composition:

* The session directory keeps its unchanged ``metadata.json``. It is still valid Phase 06
  ``SessionMetadata``, so ``verify_session`` and the Phase 07 labelling pipeline apply as for any
  recording.
* ``live-session.json`` references that file by SHA-256 and repeats its identity fields (session
  id, kind, participant, consent, calibration). :func:`consistency_errors` checks them against it.
* It adds ``arm_blocks[]`` (assigned arm, segment ids, time span, switches, commits per arm,
  fallbacks), ``external_methods[]`` (M1 / M2 / M3 status, recordings with hashes, sync result,
  uncertainty) and ``sync_markers[]``. It also records the calibration hash, blinding, the
  pre-registration / lock provenance and whether the participant is also a dataset participant.

The schema's conditional rules keep SYNTHETIC and DEV_CAPTURE sessions from carrying consent
records, and require signed consent for PILOT and PARTICIPANT sessions (integrity item I-4).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spacedrums.contracts import schema as contract_schema
from spacedrums.live_eval.prereg import file_digest
from spacedrums.live_eval.protocol import LiveProtocol

SCHEMA_STEM = "live-session-metadata"
LIVE_METADATA_FILENAME = "live-session.json"
LIVE_SCHEMA_VERSION = "1.0"


@dataclass
class LiveSessionMetadata:
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        *,
        session_metadata: Mapping[str, Any],
        live: LiveProtocol,
        prereg: Mapping[str, Any],
        lock: Mapping[str, Any] | None,
        blinding: Mapping[str, Any],
        external_methods: Sequence[Mapping[str, Any]],
        overlap_with_dataset: str,
        questionnaire: Mapping[str, Any],
        evidence_label: str,
        notes: str = "",
    ) -> LiveSessionMetadata:
        sm = session_metadata
        d: dict[str, Any] = {
            "schema_version": LIVE_SCHEMA_VERSION,
            "session_id": sm["session_id"],
            "session_kind": sm["session_kind"],
            "participant_id": sm["participant_id"],
            "consent_status": sm["consent_status"],
            "consent_record_id": sm["consent_record_id"],
            "base_metadata": {"path": "metadata.json", "sha256": None},
            "evidence_label": evidence_label,
            "prereg": dict(prereg),
            "lock": None if lock is None else dict(lock),
            "live_protocol": {
                k: v for k, v in live.to_dict().items() if k not in ("phase06_protocol", "blocks", "options")
            }
            | {"duration_scale": live.options["duration_scale"], "pad_zone_id": live.options["pad_zone_id"]},
            "arm_blocks": [
                {
                    **b.to_dict(),
                    "t_start": None,
                    "t_end": None,
                    "status": "NOT_RUN",
                    "switches": [],
                    "commits_by_arm": {},
                    "fallback_events": [],
                }
                for b in live.blocks
            ],
            "external_methods": [dict(m) for m in external_methods],
            "sync_markers": [],
            "calibration": {
                "calibration_status": sm.get("calibration_status"),
                "calibration_id": sm.get("calibration_id"),
                "calibration_hash": sm.get("calibration_hash"),
            },
            "blinding": dict(blinding),
            "questionnaire": dict(questionnaire),
            "overlap_with_dataset": overlap_with_dataset,
            "notes": notes,
        }
        return cls(d)

    # -- filling ---------------------------------------------------------------------------
    def close_blocks(
        self,
        segments: Sequence[Mapping[str, Any]],
        switches: Sequence[Mapping[str, Any]],
        committed: Sequence[Mapping[str, Any]],
        fallback_events: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        """Block spans from the recorded segment markers (latest take); commits and switches per block."""
        latest: dict[str, Mapping[str, Any]] = {}
        for seg in segments:
            if seg["status"] == "RECORDED" and seg["t_end"] is not None:
                latest[seg["segment_id"]] = seg
        for block in self.data["arm_blocks"]:
            spans = [latest[s] for s in block["segment_ids"] if s in latest]
            if not spans:
                block["status"] = "NOT_RUN"
                continue
            block["t_start"] = min(float(s["t_start"]) for s in spans)
            block["t_end"] = max(float(s["t_end"]) for s in spans)
            block["status"] = "COMPLETED" if len(spans) == len(block["segment_ids"]) else "PARTIAL"
            a, b = block["t_start"], block["t_end"]
            block["switches"] = [dict(s) for s in switches if s["block_id"] == block["block_id"]]
            counts: dict[str, dict[str, int]] = {}
            for c in committed:
                if a <= float(c["t_commit"]) < b:
                    slot = counts.setdefault(str(c["arm"]), {"sounding": 0, "shadow": 0})
                    slot["shadow" if c.get("shadow") else "sounding"] += 1
            block["commits_by_arm"] = counts
            block["fallback_events"] = [dict(f) for f in fallback_events if a <= float(f["t"]) < b]

    def add_sync_marker(self, kind: str, t_mono: float, source: str, note: str = "") -> dict[str, Any]:
        marker = {
            "marker_id": f"live-sync-{len(self.data['sync_markers']) + 1:03d}",
            "kind": kind,
            "t_mono": float(t_mono),
            "source": source,
            "note": note,
        }
        self.data["sync_markers"].append(marker)
        return marker

    def set_method(self, method: str, **fields: Any) -> dict[str, Any]:
        for m in self.data["external_methods"]:
            if m["method"] == method:
                m.update(fields)
                return m
        raise KeyError(method)

    # -- validation / io ---------------------------------------------------------------------
    def errors(self, session_dir: str | Path | None = None) -> list[str]:
        errs = list(contract_schema.errors(SCHEMA_STEM, self.data))
        if not errs and session_dir is not None:
            errs.extend(consistency_errors(self.data, session_dir))
        return errs

    def write(self, session_dir: str | Path, *, validate: bool = True) -> Path:
        session_dir = Path(session_dir)
        base = session_dir / "metadata.json"
        if base.exists():
            self.data["base_metadata"]["sha256"] = file_digest(base)
        if validate:
            errs = self.errors(session_dir)
            if errs:
                raise ValueError("LiveSessionMetadata invalid: " + "; ".join(errs[:10]))
        path = session_dir / LIVE_METADATA_FILENAME
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False, allow_nan=False)
            fh.write("\n")
        return path

    @classmethod
    def read(cls, session_dir: str | Path) -> LiveSessionMetadata:
        d = json.loads((Path(session_dir) / LIVE_METADATA_FILENAME).read_text(encoding="utf-8"))
        if d.get("schema_version") != LIVE_SCHEMA_VERSION:
            raise ValueError(f"unsupported LiveSessionMetadata schema_version {d.get('schema_version')!r}")
        return cls(copy.deepcopy(d))


def consistency_errors(live: Mapping[str, Any], session_dir: str | Path) -> list[str]:
    """Identity and segment agreement with the session's Phase 06 ``metadata.json``."""
    base_path = Path(session_dir) / "metadata.json"
    if not base_path.exists():
        return ["metadata.json (Phase 06 SessionMetadata) is missing"]
    base = json.loads(base_path.read_text(encoding="utf-8"))
    errs = []
    for key in ("session_id", "session_kind", "participant_id", "consent_status", "consent_record_id"):
        if live[key] != base[key]:
            errs.append(f"{key} differs from metadata.json ({live[key]!r} != {base[key]!r})")
    if live["calibration"]["calibration_hash"] != base.get("calibration_hash"):
        errs.append("calibration_hash differs from metadata.json")
    digest = live["base_metadata"]["sha256"]
    if digest is not None and digest != file_digest(base_path):
        errs.append("metadata.json changed after live-session.json referenced it")
    known = {s["segment_id"] for s in base["segments"]}
    for block in live["arm_blocks"]:
        if block["status"] != "NOT_RUN" and not set(block["segment_ids"]) & known:
            errs.append(f"block {block['block_id']} has a span but none of its segments is recorded")
    order = live["live_protocol"]["arm_order"]
    air = [b["arm"] for b in live["arm_blocks"] if b["kind"] == "AIR"]
    if air != order:
        errs.append(f"AIR block arms {air} do not follow the recorded order {order}")
    return errs


__all__ = ["LIVE_METADATA_FILENAME", "LiveSessionMetadata", "consistency_errors"]
