"""TEST-CAPTURE-2: interval statistics on synthetic timestamps, stall detection, drop-oldest queue."""

from __future__ import annotations

import threading

import numpy as np
import pytest

from spacedrums.capture import BoundedFrameQueue, CaptureStats, StallDetector, interval_stats


def test_interval_stats_regular_30fps():
    t = np.arange(0, 10, 1 / 30)
    st = interval_stats(t, 1 / 30)
    assert st.fps == pytest.approx(30.0)
    assert st.std_s == pytest.approx(0.0, abs=1e-9)
    assert st.n_gaps == 0 and st.n_stalls == 0
    assert st.p1_s == pytest.approx(1 / 30) and st.p99_s == pytest.approx(1 / 30)
    assert sum(st.histogram_counts) == st.n_intervals


def test_interval_stats_flags_gaps_and_stalls():
    nominal = 1 / 30
    t = list(np.arange(0, 1, nominal))
    t += [t[-1] + 1.6 * nominal]  # gap (> 1.5x), not a stall (< 2x)
    t += [t[-1] + 2.5 * nominal]  # stall (> 2x) and a gap
    t += [t[-1] + nominal]
    st = interval_stats(t, nominal)
    assert st.n_gaps == 2
    assert st.n_stalls == 1
    assert st.max_s == pytest.approx(2.5 * nominal)
    assert st.fps < 30.0  # delivered rate reflects the missing frames


def test_interval_stats_rejects_bad_input():
    with pytest.raises(ValueError):
        interval_stats([1.0], 1 / 30)
    with pytest.raises(ValueError):
        interval_stats([1.0, 0.5], 1 / 30)
    with pytest.raises(ValueError):
        interval_stats([0.0, 1.0], 0.0)


def test_stall_detector():
    d = StallDetector(1 / 30, 2.0)
    assert d.observe(0.0) is False
    assert d.observe(0.033) is False
    assert d.observe(0.033 + 0.05) is False  # 1.5x: not a stall
    assert d.observe(0.083 + 0.08) is True  # 2.4x
    assert d.stalls == 1
    assert d.is_stalling(0.163 + 0.1) is True
    with pytest.raises(ValueError):
        StallDetector(1 / 30, 1.0)


def test_queue_drop_oldest_and_accounting():
    q: BoundedFrameQueue[int] = BoundedFrameQueue(2)
    assert q.put(1) == 0 and q.put(2) == 0
    assert q.put(3) == 1  # 1 dropped
    assert q.put(4) == 1  # 2 dropped
    assert q.dropped == 2 and len(q) == 2
    item, since = q.get()
    assert item == 3 and since == 2  # freshest survivors, drops reported once
    item, since = q.get()
    assert item == 4 and since == 0
    assert q.get(timeout=0.01) is None
    assert q.delivered == 2
    with pytest.raises(ValueError):
        BoundedFrameQueue(0)


def test_queue_slow_consumer_bounded_latency():
    """Task 02.3 evidence: a slow consumer sees drops increase while queue depth stays bounded."""
    q: BoundedFrameQueue[int] = BoundedFrameQueue(2)
    n = 500
    depths = []

    def producer():
        for i in range(n):
            q.put(i)
            depths.append(len(q))
        q.close()

    th = threading.Thread(target=producer)
    th.start()
    delivered = []
    total_since = 0
    while True:
        got = q.get(timeout=1.0)
        if got is None:
            break
        item, since = got
        delivered.append(item)
        total_since += since
        # slow consumer: burn a little time
        sum(range(20_000))
    th.join()
    assert max(depths) <= 2
    assert delivered == sorted(delivered)  # order preserved
    assert q.dropped + len(delivered) == n
    assert total_since + q.pending_drops == q.dropped  # every drop accounted for exactly once


def test_queue_closed_get_returns_none():
    q: BoundedFrameQueue[int] = BoundedFrameQueue(1)
    q.close()
    assert q.get(timeout=0.01) is None
    with pytest.raises(RuntimeError):
        q.put(1)


def test_capture_stats_to_dict():
    s = CaptureStats(delivered=10, dropped=1, stalled=0, duplicates=2, fps_measured=29.9,
                     interval_p50=0.033, interval_p99=0.04)
    d = s.to_dict()
    assert d["delivered"] == 10 and d["duplicates"] == 2 and d["clamped_timestamps"] == 0
