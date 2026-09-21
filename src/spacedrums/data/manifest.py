"""Raw-dataset manifests (Phase 06, Task 06.9; ``schemas/raw-manifest.schema.json``).

Storage layout (git-ignored, manifest-tracked; ADR-0019):

    data/raw/<participant_id>/<session_id>/
        frames/*.png  frames.jsonl  records/*.jsonl  timing.jsonl  config.snapshot.yaml
        session.json (Phase 05 provenance)  metadata.json (SessionMetadata)  verify.json
        checklist.json?  audio_track.wav?
    data/manifests/<dataset_version>.json            (tracked; SHA-256 per file)
    data/manifests/<dataset_version>.exclusions.jsonl (tracked; ExclusionRecords of the listed sessions)

A manifest lists every file of every **accepted** session (verdict ACCEPT; REVIEW sessions only with
``include_review=True``, marked), sorted by participant id, session id and path (reproducibility
policy: manifest order is the dataset order), with byte size and SHA-256. The manifest's own
canonical hash is the ``dataset_hash`` of experiment logs. Sessions are admitted by *kind*: a
participant manifest (``ds-raw-v<M>.<m>``) accepts PARTICIPANT sessions with SIGNED consent only; a
pilot manifest (``…-pilot``) accepts PILOT sessions with SIGNED consent; a self-test manifest
(``ds-raw-v0.0-selftest…``) accepts SYNTHETIC and DEV_CAPTURE sessions only and is labelled
"TEST / DEVELOPMENT ONLY". A session of the wrong kind is refused, never re-labelled (integrity I-4).

Versioning tool: manifest-only (no DVC) — Pending Architecture Decision of the phase document,
resolved in ADR-0019. Withdrawal: a participant's files are deleted and the manifest carries a
withdrawal record (no content); ``apply_withdrawal`` rewrites the manifest accordingly.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from spacedrums import timing
from spacedrums.contracts import schema as contract_schema
from spacedrums.data.metadata import METADATA_FILENAME, ConsentStatus, SessionKind, SessionMetadata
from spacedrums.data.validation import VERIFY_FILENAME

MANIFEST_SCHEMA_VERSION = "1.0"
GENERATOR = {"tool": "spacedrums.data.manifest", "version": "0.6.0"}
_PARTICIPANT_VERSION = re.compile(r"^ds-raw-v[0-9]+\.[0-9]+$")
_PILOT_VERSION = re.compile(r"^ds-raw-v[0-9]+\.[0-9]+-pilot$")
_SELFTEST_VERSION = re.compile(r"^ds-raw-v0\.0-selftest(-[a-z0-9]+)*$")

LABELS = {
    "PARTICIPANT": "PARTICIPANT raw dataset (consented sessions; counts MEASURED from the listed files)",
    "PILOT": "PILOT raw dataset (pilot volunteers with signed consent; not the campaign dataset)",
    "SELFTEST": "TEST / DEVELOPMENT ONLY - SYNTHETIC and/or DEV CAPTURE sessions; never participant evidence",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def manifest_kind(dataset_version: str) -> str:
    if _PARTICIPANT_VERSION.match(dataset_version):
        return "PARTICIPANT"
    if _PILOT_VERSION.match(dataset_version):
        return "PILOT"
    if _SELFTEST_VERSION.match(dataset_version):
        return "SELFTEST"
    raise ValueError(
        f"dataset_version {dataset_version!r} must be ds-raw-v<M>.<m> (participant), "
        "ds-raw-v<M>.<m>-pilot (pilot) or ds-raw-v0.0-selftest[-<slug>] (synthetic / dev capture)"
    )


def admissible(kind: str, meta: SessionMetadata) -> str | None:
    """None if the session may enter a manifest of ``kind``; else the refusal reason."""
    sk = meta.kind
    cs = meta.data["consent_status"]
    if kind == "PARTICIPANT":
        if sk is not SessionKind.PARTICIPANT:
            return f"{sk} session cannot enter a participant manifest"
        if cs != str(ConsentStatus.SIGNED) or not meta.data["consent_record_id"]:
            return f"consent {cs}: only SIGNED consent with a record id enters a participant manifest"
    elif kind == "PILOT":
        if sk is not SessionKind.PILOT:
            return f"{sk} session cannot enter a pilot manifest"
        if cs != str(ConsentStatus.SIGNED):
            return f"consent {cs}: pilot sessions enter a manifest only with SIGNED consent"
    else:
        if sk not in (SessionKind.SYNTHETIC, SessionKind.DEV_CAPTURE):
            return (
                f"{sk} session cannot enter a self-test manifest (participant material is never a self-test)"
            )
    return None


def session_files(session_dir: Path) -> list[dict[str, Any]]:
    """Every regular file under the session, relative POSIX paths, sorted, with bytes + SHA-256."""
    files = [p for p in session_dir.rglob("*") if p.is_file()]
    files.sort(key=lambda p: p.relative_to(session_dir).as_posix())  # string order: platform-independent
    return [
        {
            "path": p.relative_to(session_dir).as_posix(),
            "bytes": p.stat().st_size,
            "sha256": sha256_file(p),
        }
        for p in files
    ]


def build_raw_manifest(
    raw_root: str | Path,
    dataset_version: str,
    *,
    session_dirs: Sequence[str | Path] | None = None,
    include_review: bool = False,
    git_sha: str = "0" * 40,
    git_dirty: bool | None = None,
    notes: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the manifest document for ``dataset_version`` from the sessions under ``raw_root``
    (``<participant>/<session>/`` directories with ``metadata.json`` + ``verify.json``).

    Refused sessions (wrong kind, consent, verdict) are listed under ``refused`` with the reason —
    nothing is silently dropped, nothing is re-labelled.
    """
    root = Path(raw_root)
    kind = manifest_kind(dataset_version)
    dirs = (
        [Path(p) for p in session_dirs]
        if session_dirs is not None
        else sorted(p for p in root.glob("*/*") if p.is_dir() and (p / METADATA_FILENAME).exists())
    )
    sessions: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for sd in dirs:
        if not (sd / METADATA_FILENAME).exists():
            refused.append({"path": str(sd), "session_id": sd.name, "reason": "no metadata.json"})
            continue
        meta = SessionMetadata.read(sd)
        errs = meta.errors()
        if errs:
            refused.append(
                {"path": str(sd), "session_id": meta.session_id, "reason": "metadata invalid: " + errs[0]}
            )
            continue
        why = admissible(kind, meta)
        if why:
            refused.append({"path": str(sd), "session_id": meta.session_id, "reason": why})
            continue
        if not (sd / VERIFY_FILENAME).exists():
            refused.append(
                {"path": str(sd), "session_id": meta.session_id, "reason": "not verified (no verify.json)"}
            )
            continue
        verify = json.loads((sd / VERIFY_FILENAME).read_text(encoding="utf-8"))
        verdict = verify.get("verdict")
        exclusions += verify.get("exclusions", [])
        if verdict == "QUARANTINE" or (verdict == "REVIEW" and not include_review):
            refused.append({"path": str(sd), "session_id": meta.session_id, "reason": f"verdict {verdict}"})
            continue
        files = session_files(sd)
        sessions.append(
            {
                "session_id": meta.session_id,
                "participant_id": meta.data["participant_id"],
                "session_kind": meta.data["session_kind"],
                "session_index": meta.data["session_index"],
                "date": meta.data["date"],
                "verdict": verdict,
                "consent_status": meta.data["consent_status"],
                "protocol_version": meta.data["protocol"]["version"],
                "config_hash": meta.data["config_hash"],
                "git_sha": meta.data["git_sha"],
                "path": sd.relative_to(root).as_posix() if sd.is_relative_to(root) else sd.as_posix(),
                "n_frames": int(verify.get("quality", {}).get("frames", 0)),
                "duration_s": float(verify.get("quality", {}).get("duration_s", 0.0)),
                "segments_accepted": sum(
                    1 for s in verify.get("segments", []) if s.get("verdict") == "ACCEPT"
                ),
                "segments_excluded": sum(
                    1 for s in verify.get("segments", []) if s.get("verdict") == "EXCLUDE"
                ),
                "n_files": len(files),
                "total_bytes": sum(f["bytes"] for f in files),
                "files": files,
            }
        )
    sessions.sort(key=lambda s: (s["participant_id"], s["session_id"]))
    participants = sorted({s["participant_id"] for s in sessions})
    doc: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "kind": kind,
        "label": LABELS[kind],
        "root": root.as_posix(),
        "generated_at": generated_at or timing.wall_clock_iso(),
        "generator": {**GENERATOR, "git_sha": git_sha, "git_dirty": git_dirty},
        "include_review": include_review,
        "totals": {
            "n_sessions": len(sessions),
            "n_participants": len(participants),
            "n_files": sum(s["n_files"] for s in sessions),
            "total_bytes": sum(s["total_bytes"] for s in sessions),
            "total_duration_s": sum(s["duration_s"] for s in sessions),
            "n_frames": sum(s["n_frames"] for s in sessions),
            "segments_accepted": sum(s["segments_accepted"] for s in sessions),
            "segments_excluded": sum(s["segments_excluded"] for s in sessions),
            "label": "MEASURED from the listed files" if sessions else "none (no session listed)",
        },
        "participants": participants,
        "sessions": sessions,
        "refused": refused,
        "exclusions": exclusions,
        "withdrawals": [],
        "notes": notes,
    }
    doc["manifest_hash"] = manifest_hash(doc)
    return doc


def manifest_hash(doc: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the manifest without its own hash field."""
    body = {k: v for k, v in doc.items() if k != "manifest_hash"}
    return (
        "sha256:"
        + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )


def validate_manifest(doc: dict[str, Any]) -> list[str]:
    errs = contract_schema.errors("raw-manifest", doc)
    if not errs and doc.get("manifest_hash") != manifest_hash(doc):
        errs.append("manifest_hash does not match the document")
    return errs


def write_manifest(
    doc: dict[str, Any], manifests_dir: str | Path, *, allow_empty: bool = False
) -> tuple[Path, Path]:
    """Write ``<version>.json`` and ``<version>.exclusions.jsonl``; returns both paths.

    A PARTICIPANT or PILOT manifest with no session is refused unless ``allow_empty`` (a
    ``ds-raw-v1.0.json`` must never exist before participant sessions do, integrity I-4)."""
    errs = validate_manifest(doc)
    if errs:
        raise ValueError("manifest invalid: " + "; ".join(errs[:3]))
    if doc["kind"] in ("PARTICIPANT", "PILOT") and not doc["sessions"] and not allow_empty:
        raise ValueError(
            f"refusing to write an empty {doc['kind']} manifest {doc['dataset_version']}: no accepted session "
            "of that kind exists (participant data is PENDING until recorded)"
        )
    mdir = Path(manifests_dir)
    mdir.mkdir(parents=True, exist_ok=True)
    mpath = mdir / f"{doc['dataset_version']}.json"
    mpath.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    epath = mdir / f"{doc['dataset_version']}.exclusions.jsonl"
    with epath.open("w", encoding="utf-8", newline="\n") as fh:
        for e in doc["exclusions"]:
            fh.write(json.dumps(e, allow_nan=False) + "\n")
    return mpath, epath


def read_manifest(path: str | Path) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    errs = validate_manifest(doc)
    if errs:
        raise ValueError(f"{path}: " + "; ".join(errs[:3]))
    return doc


def check_manifest_files(doc: dict[str, Any], raw_root: str | Path) -> list[str]:
    """Re-hash every listed file; returns the mismatches (empty == the files match the manifest)."""
    root = Path(raw_root)
    problems = []
    for s in doc["sessions"]:
        sd = root / s["path"]
        for f in s["files"]:
            p = sd / f["path"]
            if not p.exists():
                problems.append(f"{s['session_id']}/{f['path']}: missing")
            elif p.stat().st_size != f["bytes"] or sha256_file(p) != f["sha256"]:
                problems.append(f"{s['session_id']}/{f['path']}: hash/size mismatch")
    return problems


def apply_withdrawal(
    doc: dict[str, Any], participant_id: str, *, date: str, note: str = ""
) -> dict[str, Any]:
    """Remove a participant's sessions from the manifest and add a withdrawal record (no content)."""
    kept = [s for s in doc["sessions"] if s["participant_id"] != participant_id]
    removed = [s["session_id"] for s in doc["sessions"] if s["participant_id"] == participant_id]
    out = dict(doc)
    out["sessions"] = kept
    out["participants"] = sorted({s["participant_id"] for s in kept})
    out["exclusions"] = [e for e in doc["exclusions"] if e.get("participant_id") != participant_id]
    out["withdrawals"] = list(doc["withdrawals"]) + [
        {"participant_id": participant_id, "date": date, "n_sessions_removed": len(removed), "note": note}
    ]
    out["totals"] = {
        "n_sessions": len(kept),
        "n_participants": len(out["participants"]),
        "n_files": sum(s["n_files"] for s in kept),
        "total_bytes": sum(s["total_bytes"] for s in kept),
        "total_duration_s": sum(s["duration_s"] for s in kept),
        "n_frames": sum(s["n_frames"] for s in kept),
        "segments_accepted": sum(s["segments_accepted"] for s in kept),
        "segments_excluded": sum(s["segments_excluded"] for s in kept),
        "label": "MEASURED from the listed files" if kept else "none (no session listed)",
    }
    out["manifest_hash"] = manifest_hash(out)
    return out


__all__ = [
    "LABELS",
    "MANIFEST_SCHEMA_VERSION",
    "admissible",
    "apply_withdrawal",
    "build_raw_manifest",
    "check_manifest_files",
    "manifest_hash",
    "manifest_kind",
    "read_manifest",
    "session_files",
    "sha256_file",
    "validate_manifest",
    "write_manifest",
]
