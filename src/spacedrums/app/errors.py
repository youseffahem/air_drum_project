"""Error codes, user-facing messages, structured event log and crash reports (Phase 17, Task 17.9).

Conventions (``docs/testing/user-messages.md`` is the human-readable catalogue of the same table):

* every condition the application reports has a stable **code** ``SD-<COMPONENT>-<NNN>`` and a
  :class:`MessageSpec` (component, severity, title, user message, guidance);
* the structured log (:class:`EventLog`) writes one JSON object per line: wall-clock ISO time,
  ``t_mono``, code, severity, component, message, ``detail`` (machine-readable) and the session's
  provenance (session id, config hash, model id / hashes, calibration hash, git sha); it is bounded
  in memory and append-only on disk;
* a crash report (:func:`write_crash_report`) is a JSON file with the exception, the traceback,
  the same provenance and the last logged events; the application writes it and re-raises.

Messages never claim more than the system knows: a fallback says which arm now sounds, a camera
message says what was measured (delivered FPS from ``t_capture`` differences, never the requested
mode), and no message promises latency or timing.
"""

from __future__ import annotations

import json
import platform
import sys
import traceback
from collections import deque
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from spacedrums.timing import now, wall_clock_iso


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class MessageSpec:
    code: str
    component: str  # camera | capture | tracking | model | audio | safety | app
    severity: Severity
    title: str
    user_message: str
    guidance: str

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "severity": str(self.severity)}


def _m(code, component, severity, title, message, guidance) -> MessageSpec:
    return MessageSpec(code, component, Severity(severity), title, message, guidance)


CATALOGUE: dict[str, MessageSpec] = {
    m.code: m
    for m in (
        _m(
            "SD-CAM-001",
            "camera",
            "CRITICAL",
            "Camera not found",
            "The camera could not be opened.",
            "Check that the webcam is connected and not used by another program, then restart. "
            "The configured device index/backend is in the config's camera_profile block.",
        ),
        _m(
            "SD-CAM-002",
            "camera",
            "ERROR",
            "Camera stopped delivering frames",
            "No camera frame has arrived for a while; drumming is paused (no sound can be triggered).",
            "Check the cable / privacy shutter. If frames do not resume, restart the application.",
        ),
        _m(
            "SD-CAP-001",
            "capture",
            "WARNING",
            "Low frame rate",
            "The camera is delivering fewer frames per second than requested (measured from capture "
            "timestamps).",
            "Add light (the camera lowers its frame rate in dim light), close other camera or video "
            "programs, and keep the laptop on mains power.",
        ),
        _m(
            "SD-CAP-002",
            "capture",
            "WARNING",
            "Frames are being dropped",
            "Processing is falling behind the camera; some frames were skipped and strikes right "
            "after a gap are not committed.",
            "Close other programs; use the experiment overlay mode instead of the full overlay.",
        ),
        _m(
            "SD-CAP-003",
            "capture",
            "WARNING",
            "Camera timestamps irregular",
            "Some camera timestamps went backwards or ahead of delivery and were refused or clamped.",
            "Usually harmless if rare; if it persists, switch the capture backend or timestamp source "
            "(camera_profile.timestamp_source = GRAB_RETURN).",
        ),
        _m(
            "SD-TRK-001",
            "tracking",
            "WARNING",
            "Poor tracking",
            "Hands or sticks are not tracked reliably; strikes may be missed (the system never "
            "guesses a strike while tracking is lost).",
            "Stand inside the marked area, keep both hands and the stick tips in view, improve the "
            "lighting (avoid a bright window behind you) and keep the background calm.",
        ),
        _m(
            "SD-TRK-002",
            "tracking",
            "INFO",
            "Hand re-acquired",
            "Tracking of a hand resumed after a loss; prediction restarts after a short warm-up.",
            "No action needed.",
        ),
        _m(
            "SD-MDL-001",
            "model",
            "WARNING",
            "Model fallback active",
            "The temporal model was disabled; the baseline arm now produces the sounds.",
            "The reason is in the session log. Restart after correcting it (the fallback is sticky "
            "by design).",
        ),
        _m(
            "SD-MDL-002",
            "model",
            "ERROR",
            "Model could not be loaded",
            "The configured model package failed verification or loading; the baseline arm sounds.",
            "Check the model path and hashes in the config's anticipator.model block.",
        ),
        _m(
            "SD-AUD-001",
            "audio",
            "ERROR",
            "Audio device problem",
            "The audio output stopped (device removed or failed); strikes are still detected and "
            "logged but cannot be heard. Reconnection is retried automatically.",
            "Reconnect the headphones/speakers or select another output device in the config's "
            "audio.device block.",
        ),
        _m(
            "SD-AUD-002",
            "audio",
            "WARNING",
            "Audio underruns",
            "The audio device reported buffer underruns; some sounds may be late or crackle.",
            "Close other audio programs; increase audio.buffer_frames if this persists.",
        ),
        _m(
            "SD-AUD-003",
            "audio",
            "INFO",
            "Audio device recovered",
            "Audio output is running again.",
            "No action needed.",
        ),
        _m(
            "SD-INV-001",
            "safety",
            "CRITICAL",
            "Safety invariant violated",
            "An internal safety check failed (see the session log).",
            "Stop the session and report the log: results from this session must not be used.",
        ),
        _m(
            "SD-APP-001",
            "app",
            "CRITICAL",
            "Unexpected error",
            "The application stopped because of an unexpected error; a crash report was written.",
            "Send the crash report file (it contains no images or audio) to the developer.",
        ),
    )
}


def spec(code: str) -> MessageSpec:
    return CATALOGUE[code]


class ReportedError(RuntimeError):
    """An expected failure with a catalogue code: shown to the user, no crash report (e.g. no camera)."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        if code not in CATALOGUE:
            raise ValueError(f"unknown message code {code!r}")
        super().__init__(user_text(code, detail))
        self.code, self.detail = code, detail


def user_text(code: str, detail: str | None = None) -> str:
    """One console/overlay line: ``[SD-XXX-NNN] Title: message (detail)``."""
    m = CATALOGUE[code]
    return f"[{m.code}] {m.title}: {m.user_message}" + (f" ({detail})" if detail else "")


class EventLog:
    """Structured JSONL event log; bounded in memory, optional file sink, never raises on write."""

    def __init__(
        self, path: str | Path | None = None, *, context: dict[str, Any] | None = None, keep: int = 200
    ):
        self.path = Path(path) if path is not None else None
        self.context = dict(context or {})
        self.recent: deque[dict[str, Any]] = deque(maxlen=keep)
        self.counts: dict[str, int] = {}
        self.write_errors = 0
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, code: str, *, detail: dict[str, Any] | None = None, t_mono: float | None = None) -> dict:
        m = CATALOGUE[code]
        record = {
            "ts_wall": wall_clock_iso(),
            "t_mono": now() if t_mono is None else float(t_mono),
            "code": m.code,
            "severity": str(m.severity),
            "component": m.component,
            "message": m.user_message,
            "detail": detail or {},
            **self.context,
        }
        self.recent.append(record)
        self.counts[code] = self.counts.get(code, 0) + 1
        if self.path is not None:
            try:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, default=str, allow_nan=False) + "\n")
            except (OSError, ValueError):
                self.write_errors += 1
        return record

    def summary(self) -> dict[str, Any]:
        return {"counts": dict(sorted(self.counts.items())), "write_errors": self.write_errors}


def write_crash_report(
    exc: BaseException, directory: str | Path, *, context: dict[str, Any], events: EventLog | None = None
) -> Path:
    """Write ``crash-<wall time>.json`` with the traceback and provenance; returns its path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = wall_clock_iso().replace(":", "").replace("-", "")[:15]
    path = directory / f"crash-{stamp}.json"
    n = 1
    while path.exists():
        n += 1
        path = directory / f"crash-{stamp}-{n}.json"
    report = {
        "code": "SD-APP-001",
        "ts_wall": wall_clock_iso(),
        "t_mono": now(),
        "exception": {"type": type(exc).__name__, "message": str(exc)},
        "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
        "python": sys.version,
        "platform": platform.platform(),
        **context,
        "recent_events": list(events.recent) if events is not None else [],
    }
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


__all__ = [
    "CATALOGUE",
    "EventLog",
    "MessageSpec",
    "ReportedError",
    "Severity",
    "spec",
    "user_text",
    "write_crash_report",
]
