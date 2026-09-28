"""Pre-registration precedence for Phase 18: the hash record, the frozen-inputs locks and the ledger.

``docs/experiments/phase-18-prereg.md`` §0 declares a two-stage protocol. This module enforces it.

* **Hash record** (``phase-18-prereg.hashes.json``, tracked). An append-only list of archived
  versions of the pre-registration, and of the locks archived against a version. The document
  digest is SHA-256 over its UTF-8 bytes with CRLF normalised to LF, so a checkout that converts
  line endings cannot change it. A lock digest is SHA-256 over its canonical JSON (sorted keys, no
  whitespace).
* **Locks** (schema ``confirmatory-lock``). They hold the upstream values the pre-registration
  names as symbols. :func:`lock_errors` refuses schema violations, ``PENDING`` placeholders and
  inconsistent arm / budget / method fields. :func:`archive_lock` refuses a lock that does not
  name the latest archived pre-registration version.
* **Ledger** (JSONL, append-only). A confirmatory run on participant data reserves its entry
  before any test data is read. A second reservation for the same lock is refused unless a
  reviewed retry reason is recorded (pre-registration §11).

Nothing in this module reads data or computes a result.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from spacedrums.contracts import schema as contract_schema
from spacedrums.live_eval.hypotheses import delta_te

RECORD_SCHEMA = "spacedrums.phase18.prereg-record/1.0"
DIGEST_NOTE = "sha256 over the UTF-8 bytes with CRLF normalised to LF (documents); canonical JSON (locks)"
LOCK_SCHEMA_STEM = "confirmatory-lock"
PLACEHOLDER = "PENDING"
TEMPORAL_REPLAY_ARMS = ("MODEL:C-GRU", "MODEL:C-TCN", "MODEL:C-MT", "MODEL:C-TT")
REPLAY_ARMS = ("A", "B", "MODEL:C-GBDT", *TEMPORAL_REPLAY_ARMS)


class PreregError(RuntimeError):
    """A precedence rule of the pre-registration refused the operation."""


# ----------------------------------------------------------------------------- digests


def document_digest(path: str | Path) -> str:
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )


def lock_digest(lock: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(lock)).hexdigest()


def file_digest(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


# ----------------------------------------------------------------------------- hash record


def read_record(record_path: str | Path, document: str) -> dict[str, Any]:
    path = Path(record_path)
    if not path.exists():
        return {
            "schema": RECORD_SCHEMA,
            "document": document,
            "digest": DIGEST_NOTE,
            "versions": [],
            "locks": [],
            "approvals": [],
        }
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("schema") != RECORD_SCHEMA or record.get("document") != document:
        raise PreregError(f"{path}: not the hash record of {document}")
    return record


def write_record(record_path: str | Path, record: Mapping[str, Any]) -> None:
    Path(record_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(record_path).open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False, allow_nan=False)
        fh.write("\n")


def latest_version(record: Mapping[str, Any]) -> dict[str, Any] | None:
    return record["versions"][-1] if record["versions"] else None


def approved(record: Mapping[str, Any], version: int) -> bool:
    """Whether an owner / supervisor approval is recorded for ``version`` (pre-registration §0.4)."""
    return any(a.get("version") == version for a in record.get("approvals", []))


def archive_document(
    doc_path: str | Path,
    record_path: str | Path,
    *,
    document: str,
    archived_at: str,
    git_head: str,
    git_dirty: bool,
    note: str,
    after_lock_reason: str | None = None,
) -> dict[str, Any]:
    """Append the document's current digest as a new version (no-op if unchanged).

    A new version after a lock was archived against the previous one starts a **new pre-registered
    run** (§0.3). It is refused unless ``after_lock_reason`` states why, and the reason is recorded.
    """
    record = read_record(record_path, document)
    digest = document_digest(doc_path)
    last = latest_version(record)
    if last is not None and last["sha256"] == digest:
        return {**last, "unchanged": True}
    locked = [
        lock for lock in record["locks"] if last is not None and lock["prereg_version"] == last["version"]
    ]
    if locked and not after_lock_reason:
        raise PreregError(
            "a lock is archived against the latest version; a new version is a new pre-registered run "
            "and needs an explicit reason (after_lock_reason)"
        )
    entry = {
        "version": 1 if last is None else int(last["version"]) + 1,
        "sha256": digest,
        "archived_at": archived_at,
        "git_head": git_head,
        "git_dirty": bool(git_dirty),
        "note": note,
        "new_preregistered_run": bool(locked),
        "after_lock_reason": after_lock_reason,
    }
    record["versions"].append(entry)
    write_record(record_path, record)
    return entry


def verify_document(doc_path: str | Path, record_path: str | Path, *, document: str) -> dict[str, Any]:
    """``ok`` iff the document on disk has the digest of the latest archived version."""
    try:
        record = read_record(record_path, document)
    except (OSError, ValueError, PreregError) as exc:
        return {"ok": False, "reason": f"hash record unreadable: {exc}"}
    last = latest_version(record)
    if last is None:
        return {"ok": False, "reason": "no archived version"}
    digest = document_digest(doc_path)
    if digest != last["sha256"]:
        return {
            "ok": False,
            "reason": "the pre-registration differs from its latest archived version",
            "sha256_on_disk": digest,
            "sha256_archived": last["sha256"],
            "version": last["version"],
        }
    return {"ok": True, "version": last["version"], "sha256": digest, "archived_at": last["archived_at"]}


# ----------------------------------------------------------------------------- locks


def _placeholders(obj: Any, path: str = "") -> Iterator[str]:
    if isinstance(obj, str) and obj.strip().upper().startswith(PLACEHOLDER):
        yield path or "<root>"
    elif isinstance(obj, Mapping):
        for key, value in obj.items():
            yield from _placeholders(value, f"{path}/{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _placeholders(value, f"{path}/{i}")


def _offline_errors(off: Mapping[str, Any], evidence: str) -> list[str]:
    errs: list[str] = []
    arms = off["arms"]
    ids = [a["arm_id"] for a in arms]
    by_id = {a["arm_id"]: a for a in arms}
    if len(ids) != len(set(ids)):
        errs.append("arm ids must be unique")
    for aid in ids:
        if aid not in off["delay"]["primary_s"]:
            errs.append(f"delay.primary_s has no value for arm {aid}")
    if not any(a["replay_arm"] == "A" for a in arms):
        errs.append("arm A is missing")
    b, c = by_id.get(off["b_primary"]), by_id.get(off["c_primary"])
    if b is None or b["replay_arm"] != "B":
        errs.append("b_primary must name a rule-based (replay arm B) arm")
    if c is None or c["replay_arm"] not in TEMPORAL_REPLAY_ARMS:
        errs.append("c_primary must name a temporal trajectory arm")
    for arm in arms:
        model_arm = arm["replay_arm"].startswith("MODEL:")
        if model_arm != (arm.get("model") is not None):
            errs.append(f"arm {arm['arm_id']}: a model block is required exactly for MODEL arms")
        if arm["replay_arm"] == "B" and arm.get("rule") is None:
            errs.append(f"arm {arm['arm_id']}: a rule block is required for B")
        if arm["replay_arm"] == "MODEL:C-GBDT" and (arm.get("model") or {}).get("mode") not in (
            "direct",
            "trajectory",
        ):
            errs.append(f"arm {arm['arm_id']}: C-GBDT needs mode direct or trajectory")
    budgets = off["budgets"]
    expected = delta_te(budgets["delta_audio_s"], off["acoustic"].get("s_phys_s"))
    if not math.isclose(budgets["delta_te_s"], expected, rel_tol=0, abs_tol=1e-12):
        errs.append(f"budgets.delta_te_s must equal max(delta_audio, 2 s_phys) = {expected}")
    ds = off["dataset"]
    if ds["p_test"] != len(ds["test_participants"]) or ds["p_test"] < 1:
        errs.append("dataset.p_test must equal the number of test participants (>= 1)")
    if {s["participant_id"] for s in ds["sessions"]} - set(ds["test_participants"]):
        errs.append("every locked session must belong to a test participant")
    if evidence == "PARTICIPANT" and (ds["kind"] != "PARTICIPANT" or not ds["version"].startswith("ds-v1.")):
        errs.append("a PARTICIPANT lock needs a ds-v1.x participant dataset")
    if evidence == "SYNTHETIC_REHEARSAL" and ds["kind"] != "SELFTEST":
        errs.append("a rehearsal lock must use a SELFTEST dataset")
    return errs


def _live_errors(live: Mapping[str, Any]) -> list[str]:
    errs: list[str] = []
    methods = live["methods"]
    for name in ("M1", "M2"):
        m = methods[name]
        if (m["status"] == "GO") != (m.get("u_s") is not None):
            errs.append(f"methods.{name}: u_s is required exactly when the status is GO")
    expected = (
        "M1" if methods["M1"]["status"] == "GO" else ("M2" if methods["M2"]["status"] == "GO" else None)
    )
    if live.get("primary_method") != expected:
        errs.append(f"primary_method must be {expected!r} (M1 if GO, else M2 if GO, else null)")
    if sorted(live["arms"]) != ["A", "B", "C"]:
        errs.append("live arms must map exactly A, B and C")
    from .arm_settings import live_binding_errors

    errs.extend(live_binding_errors(live))
    return errs


def lock_errors(lock: Mapping[str, Any]) -> list[str]:
    """Schema errors, placeholders and semantic inconsistencies (empty list == archivable)."""
    errs = list(contract_schema.errors(LOCK_SCHEMA_STEM, lock))
    if errs:
        return errs
    errs.extend(f"placeholder value at {p}" for p in _placeholders(lock))
    if lock["lock_kind"] == "offline":
        errs.extend(_offline_errors(lock["offline"], lock["evidence"]))
    else:
        errs.extend(_live_errors(lock["live"]))
    return errs


def archive_lock(
    lock_path: str | Path,
    record_path: str | Path,
    *,
    document: str,
    doc_path: str | Path,
    archived_at: str,
    git_head: str,
    require_approval: bool = False,
) -> dict[str, Any]:
    """Validate a lock against the latest archived pre-registration and append its digest.

    ``require_approval`` (participant locks): the latest version must carry an approval entry.
    """
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    errs = lock_errors(lock)
    if errs:
        raise PreregError("lock is not archivable: " + "; ".join(errs[:12]))
    check = verify_document(doc_path, record_path, document=document)
    if not check["ok"]:
        raise PreregError("pre-registration not verified: " + check["reason"])
    if lock["prereg"]["sha256"] != check["sha256"] or lock["prereg"]["version"] != check["version"]:
        raise PreregError("the lock does not name the latest archived pre-registration version")
    record = read_record(record_path, document)
    if require_approval and not approved(record, check["version"]):
        raise PreregError("the latest pre-registration version carries no owner / supervisor approval")
    if lock["lock_kind"] == "live":
        parent = next(
            (
                e
                for e in record["locks"]
                if e["sha256"] == lock["live"]["offline_lock_sha256"]
                and e["kind"] == "offline"
                and e["evidence"] == lock["evidence"]
                and e["prereg_version"] == check["version"]
            ),
            None,
        )
        if parent is None:
            raise PreregError("live lock requires the archived offline lock for this preregistration")
    digest = lock_digest(lock)
    for entry in record["locks"]:
        if entry["sha256"] == digest:
            return {**entry, "unchanged": True}
    entry = {
        "kind": lock["lock_kind"],
        "evidence": lock["evidence"],
        "path": Path(lock_path).as_posix(),
        "sha256": digest,
        "archived_at": archived_at,
        "git_head": git_head,
        "prereg_version": check["version"],
    }
    record["locks"].append(entry)
    write_record(record_path, record)
    return entry


def verify_lock(
    lock: Mapping[str, Any],
    record_path: str | Path,
    *,
    document: str,
    doc_path: str | Path,
    require_approval: bool = False,
) -> dict[str, Any]:
    """``ok`` iff the lock is valid, archived, and names the latest pre-registration version."""
    errs = lock_errors(lock)
    if errs:
        return {"ok": False, "reason": "invalid lock: " + "; ".join(errs[:12])}
    check = verify_document(doc_path, record_path, document=document)
    if not check["ok"]:
        return {"ok": False, "reason": "pre-registration not verified: " + check["reason"]}
    record = read_record(record_path, document)
    digest = lock_digest(lock)
    entry = next((e for e in record["locks"] if e["sha256"] == digest), None)
    if entry is None:
        return {"ok": False, "reason": "lock not archived in the hash record"}
    if entry["prereg_version"] != check["version"] or lock["prereg"]["sha256"] != check["sha256"]:
        return {"ok": False, "reason": "lock archived against an older pre-registration version"}
    if datetime.fromisoformat(entry["archived_at"]) < datetime.fromisoformat(check["archived_at"]):
        return {"ok": False, "reason": "lock archived before its pre-registration version"}
    if require_approval and not approved(record, check["version"]):
        return {
            "ok": False,
            "reason": "the latest pre-registration version carries no owner / supervisor approval",
        }
    if lock["lock_kind"] == "live":
        parent = next(
            (
                e
                for e in record["locks"]
                if e["sha256"] == lock["live"]["offline_lock_sha256"]
                and e["kind"] == "offline"
                and e["evidence"] == lock["evidence"]
                and e["prereg_version"] == check["version"]
            ),
            None,
        )
        if parent is None:
            return {
                "ok": False,
                "reason": "live lock requires archived offline lock for this preregistration",
            }
    return {"ok": True, "sha256": digest, "archived_at": entry["archived_at"], "prereg": check}


# ----------------------------------------------------------------------------- ledger


class Ledger:
    """Append-only JSONL of confirmatory executions keyed by lock digest."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]

    def _append(self, entry: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")

    def reserve(
        self,
        *,
        lock_sha256: str,
        run_id: str,
        evidence: str,
        at: str,
        git_head: str,
        retry_reason: str | None = None,
    ) -> dict[str, Any]:
        previous = [e for e in self.entries() if e["lock_sha256"] == lock_sha256 and e["event"] == "RESERVED"]
        if previous and evidence == "PARTICIPANT" and not retry_reason:
            raise PreregError(
                f"lock {lock_sha256} was already executed ({previous[-1]['run_id']}); a repeat needs a "
                "reviewed retry reason and is reported as such"
            )
        entry = {
            "event": "RESERVED",
            "lock_sha256": lock_sha256,
            "run_id": run_id,
            "evidence": evidence,
            "at": at,
            "git_head": git_head,
            "attempt": len(previous) + 1,
            "retry_reason": retry_reason,
        }
        self._append(entry)
        return entry

    def finish(self, *, lock_sha256: str, run_id: str, status: str, at: str, detail: str = "") -> None:
        if status not in ("COMPLETED", "FAILED", "ABORTED"):
            raise ValueError("status must be COMPLETED, FAILED or ABORTED")
        self._append(
            {"event": status, "lock_sha256": lock_sha256, "run_id": run_id, "at": at, "detail": detail}
        )


__all__ = [
    "DIGEST_NOTE",
    "Ledger",
    "PreregError",
    "approved",
    "archive_document",
    "archive_lock",
    "canonical_json",
    "document_digest",
    "file_digest",
    "latest_version",
    "lock_digest",
    "lock_errors",
    "read_record",
    "verify_document",
    "verify_lock",
    "write_record",
]
