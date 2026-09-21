"""JSONL record streams with a ``RecordStreamHeader`` first line (contracts.md section 4; Phase 05).

Used by the app's record mode for every record type (``records/<RecordType>.jsonl``) and for
``timing.jsonl``. Line 1 is the header (record type, schema version, the **const** units block,
session/config/git/clock provenance, ``producer``, ``derived``); lines 2.. are records serialised
with ``to_dict()``. Files are written with LF endings and UTF-8; a stream is written even when
empty (header only) so absence is explicit (architecture.md section 12.2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import IO, Any

UNITS = {"time": "s", "clock": "t_mono", "position": "roi_norm", "velocity": "roi_norm_per_s", "angle": "rad"}
STREAM_HEADER_SCHEMA_VERSION = "1.0"


def stream_header(
    *,
    record_type: str,
    record_schema_version: str,
    session_id: str,
    config_hash: str,
    git_sha: str,
    clock_id: str,
    producer: str,
    derived: bool,
) -> dict[str, Any]:
    if producer not in ("LIVE", "REPLAY", "REGENERATED"):
        raise ValueError("producer must be LIVE, REPLAY or REGENERATED")
    return {
        "schema_version": STREAM_HEADER_SCHEMA_VERSION,
        "record_type": record_type,
        "record_schema_version": record_schema_version,
        "units": dict(UNITS),
        "session_id": session_id,
        "config_hash": config_hash,
        "git_sha": git_sha,
        "clock_id": clock_id,
        "producer": producer,
        "derived": bool(derived),
    }


class RecordStreamWriter:
    """Append-only JSONL writer; the header is written at open."""

    def __init__(self, path: str | Path, header: dict[str, Any]) -> None:
        self.path = Path(path)
        self.header = header
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: IO[str] | None = self.path.open("w", encoding="utf-8", newline="\n")
        self._fh.write(json.dumps(header, allow_nan=False) + "\n")
        self.count = 0

    def write(self, record: Any) -> None:
        if self._fh is None:
            raise RuntimeError("stream closed")
        d = record.to_dict() if hasattr(record, "to_dict") else record
        self._fh.write(json.dumps(d, allow_nan=False) + "\n")
        self.count += 1

    def flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> RecordStreamWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_record_stream(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(header, records) of a JSONL stream; raises if the header is missing."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"{path}: empty stream (no header)")
    header = json.loads(lines[0])
    if header.get("schema_version") != STREAM_HEADER_SCHEMA_VERSION or "record_type" not in header:
        raise ValueError(f"{path}: first line is not a RecordStreamHeader")
    return header, [json.loads(line) for line in lines[1:] if line.strip()]


__all__ = [
    "STREAM_HEADER_SCHEMA_VERSION",
    "UNITS",
    "RecordStreamWriter",
    "read_record_stream",
    "stream_header",
]
