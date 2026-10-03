"""Bounded capture queue with drop-oldest and drop accounting (Task 02.3; ADR-0009 T1).

Policy (the only one the config schema allows, ``queue.drop_policy: DROP_OLDEST``): when the
queue is full, the *oldest* queued item is discarded so the consumer always gets the freshest
frame and latency never accumulates. Every discard is counted; the count is handed to the
consumer with the next delivered item as ``dropped_since_last``, so that
``sum(dropped_since_last over delivered) + pending == total dropped`` at every instant.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Generic, TypeVar

T = TypeVar("T")


class BoundedFrameQueue(Generic[T]):
    """Thread-safe single-producer / single-consumer queue of at most ``max_frames`` items."""

    def __init__(self, max_frames: int) -> None:
        if max_frames < 1:
            raise ValueError("max_frames must be >= 1")
        self.max_frames = int(max_frames)
        self._items: deque[T] = deque()
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._closed = False
        self.delivered = 0
        self.dropped = 0
        self._pending_drops = 0
        # Observability only (live responsiveness, 2026-10-02): queue length at the last delivery,
        # the delivered item included. 1 = it was the newest frame; >= 2 = a newer one was waiting.
        self.last_depth_at_get: int | None = None

    # -- producer side ---------------------------------------------------------------------
    def put(self, item: T) -> int:
        """Enqueue; if full, drop the oldest queued item. Returns how many were dropped (0/1)."""
        with self._lock:
            if self._closed:
                raise RuntimeError("queue is closed")
            dropped = 0
            if len(self._items) >= self.max_frames:
                self._items.popleft()
                dropped = 1
                self.dropped += 1
                self._pending_drops += 1
            self._items.append(item)
            self._not_empty.notify()
            return dropped

    # -- consumer side ---------------------------------------------------------------------
    def get(self, timeout: float | None = None) -> tuple[T, int] | None:
        """Dequeue the oldest item with the drops accumulated since the previous delivery.

        Returns ``None`` on timeout or when the queue is closed and empty.
        """
        with self._not_empty:
            if not self._items and not self._closed:
                self._not_empty.wait(timeout)
            if not self._items:
                return None
            self.last_depth_at_get = len(self._items)
            item = self._items.popleft()
            since = self._pending_drops
            self._pending_drops = 0
            self.delivered += 1
            return item, since

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._not_empty.notify_all()

    # -- introspection ---------------------------------------------------------------------
    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def pending_drops(self) -> int:
        with self._lock:
            return self._pending_drops

    @property
    def closed(self) -> bool:
        return self._closed


__all__ = ["BoundedFrameQueue"]
