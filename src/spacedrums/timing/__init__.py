"""The single monotonic clock ``t_mono`` (ADR-0004; architecture.md section 5.1).

Rules enforced by tests/timing/test_no_direct_time_calls.py:

* Every timestamp in the system comes from :func:`now` — seconds as ``float`` on one
  process-wide monotonic clock. No other module in ``spacedrums`` calls ``time.*`` or
  ``datetime.now`` for timestamps.
* The concrete function behind :func:`now` is identified by :data:`CLOCK_ID`, which is
  written into every ``TimingRecord``, stream header, camera profile and audio profile.

Phase 02 confirms the ADR-0004 candidate ``time.perf_counter`` on HW-01: it is
``QueryPerformanceCounter()`` (resolution 1e-7 s, monotonic, not adjustable — see
``clock_info()``), and the MSMF driver timestamps turned out to share its time base
(docs/camera-profile-hw01-integrated-webcam.md). ADR-0013 records this.

CPU-time and sleep helpers live here too so that ``time`` is imported in exactly one
place; they are *not* timestamps and must never be stored in a record.
"""

from __future__ import annotations

import datetime as _dt
import time as _time

CLOCK_ID = "perf_counter"
"""Identity of the ``t_mono`` source (``clock_id`` field of TimingRecord / RecordStreamHeader)."""


def now() -> float:
    """Current ``t_mono`` in seconds. The only timestamp source in the system."""
    return _time.perf_counter()


def clock_info() -> dict[str, object]:
    """Describe the clock behind :func:`now` (for camera/audio profiles and run logs)."""
    info = _time.get_clock_info("perf_counter")
    return {
        "clock_id": CLOCK_ID,
        "implementation": info.implementation,
        "monotonic": info.monotonic,
        "adjustable": info.adjustable,
        "resolution_s": info.resolution,
    }


def thread_cpu_seconds() -> float:
    """CPU time consumed by the *calling thread* (for capture-thread CPU-usage reports).

    Not a timestamp: never store it in a record; only differences are meaningful.
    """
    return _time.thread_time()


def process_cpu_seconds() -> float:
    """CPU time consumed by the process (not a timestamp)."""
    return _time.process_time()


def sleep_s(seconds: float) -> None:
    """Pace a loop. Kept here so ``time`` is imported in one module only."""
    _time.sleep(seconds)


def wall_clock_iso() -> str:
    """Wall-clock instant as ISO-8601 with timezone offset.

    Used only for provenance fields (``started_at`` / ``finished_at`` in run logs,
    ``SessionMetadata.started_at``), never inside per-frame or per-strike records (ADR-0004).
    """
    return _dt.datetime.now(_dt.UTC).astimezone().isoformat(timespec="seconds")


def wall_clock_local_compact() -> str:
    """Local wall-clock ``YYYYMMDD-HHMM`` for run ids (docs/repo-layout.md section 3.3)."""
    return _dt.datetime.now().strftime("%Y%m%d-%H%M")


__all__ = [
    "CLOCK_ID",
    "clock_info",
    "now",
    "process_cpu_seconds",
    "sleep_s",
    "thread_cpu_seconds",
    "wall_clock_iso",
    "wall_clock_local_compact",
]
