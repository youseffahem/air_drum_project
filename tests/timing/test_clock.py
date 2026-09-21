"""TEST-TIMING-1: the single clock accessor (ADR-0004) and the no-direct-time-calls rule."""

from __future__ import annotations

import re
from pathlib import Path

from spacedrums import timing

SRC = Path(__file__).resolve().parents[2] / "src" / "spacedrums"

# Anything that yields an instant or sleeps; `time.thread_time`/`process_time` included so that
# every use of the `time` module goes through spacedrums.timing.
_FORBIDDEN = re.compile(
    r"\btime\.(perf_counter(_ns)?|monotonic(_ns)?|time(_ns)?|thread_time(_ns)?|process_time(_ns)?|sleep)\s*\("
    r"|\bfrom\s+time\s+import\b"
    r"|\bimport\s+time\b"
    r"|\bdatetime\.(datetime\.)?now\s*\("
    r"|\bdatetime\.(datetime\.)?utcnow\s*\("
)


def test_now_is_monotone_float_seconds():
    a = timing.now()
    b = timing.now()
    assert isinstance(a, float)
    assert b >= a


def test_clock_info_names_the_source():
    info = timing.clock_info()
    assert info["clock_id"] == timing.CLOCK_ID == "perf_counter"
    assert info["monotonic"] is True
    assert info["resolution_s"] > 0


def test_thread_cpu_seconds_is_cpu_time_not_a_timestamp():
    c0 = timing.thread_cpu_seconds()
    x = 0
    for i in range(200_000):
        x += i
    assert timing.thread_cpu_seconds() >= c0


def test_wall_clock_iso_has_timezone_offset():
    s = timing.wall_clock_iso()
    assert re.search(r"[+-]\d\d:\d\d$", s), s
    assert re.fullmatch(r"\d{8}-\d{4}", timing.wall_clock_local_compact())


def test_no_module_outside_timing_calls_time_directly():
    """Code-review rule of ADR-0004, made mechanical (architecture.md section 5.1)."""
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.parent.name == "timing":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.split("#", 1)[0]
            if _FORBIDDEN.search(stripped):
                offenders.append(f"{path.relative_to(SRC)}:{lineno}: {line.strip()}")
    assert not offenders, "direct time calls outside spacedrums.timing:\n" + "\n".join(offenders)
