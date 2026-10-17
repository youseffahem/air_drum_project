"""Exposure guard: keep the requested exposure honest by measuring delivered frames (ADR-0048).

Why measurement and not read-back: on HW-01 (DSHOW), opening Windows Camera while SpaceDrums streams
switches the shared device to automatic exposure. The sensor then drops to ~15 unique FPS in a dim
room and stays there after Windows Camera closes, while ``CAP_PROP_EXPOSURE`` still reads back the
requested -5 and ``CAP_PROP_AUTO_EXPOSURE`` reads -1 (2026-10-16, docs/perf/camera-brightness.md). A
read-back costs 5-23 ms and proves nothing, so the guard watches the unique-frame rate instead:

* MANUAL: when the rate over ``window_s`` falls below ``min_fps``, the requested exposure is
  re-applied (``REAPPLIED``). An exposure longer than ``1 / min_fps`` cannot meet the floor, so
  the guard is inactive for it (``inactive_reason``).
* AUTO: the camera chooses; in dim light it lengthens the exposure and the rate falls. After
  ``settle_s`` (convergence), a rate below ``min_fps`` switches once to MANUAL ``fallback_value``
  (``AUTO_TO_MANUAL``) — the brightest fixed exposure measured to keep the floor — or, without a
  fallback, is only recorded (``AUTO_SLOW``).

Every action waits ``window_s`` of fresh frames before the next judgement and the guard stops acting
after ``max_actions`` (``GAVE_UP``), so it cannot fight another application forever. The guard is
pure bookkeeping: :class:`ExposureWatch` returns what to do, the capture thread does it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExposureGuard:
    """``camera_profile.exposure.guard``."""

    min_fps: float = 24.0
    window_s: float = 2.0
    settle_s: float = 4.0  # AUTO only: time the camera gets to converge before it is judged
    fallback_value: float | None = None  # AUTO -> MANUAL value when the floor is not met
    max_actions: int = 10

    @classmethod
    def from_config(cls, block: dict[str, Any]) -> ExposureGuard:
        guard = cls(**block)
        if guard.min_fps <= 0 or guard.window_s <= 0 or guard.settle_s < 0 or guard.max_actions < 1:
            raise ValueError(f"invalid exposure guard {block}")
        return guard

    def to_dict(self) -> dict[str, Any]:
        return {"min_fps": self.min_fps, "window_s": self.window_s, "settle_s": self.settle_s,
                "fallback_value": self.fallback_value, "max_actions": self.max_actions}


def exposure_seconds(value: float) -> float:
    """DirectShow log2 convention used by both Windows backends: ``-5`` = 2**-5 s = 31.25 ms."""
    return 2.0 ** value


class ExposureWatch:
    """Decides, from unique-frame times, when the exposure must be re-applied or replaced."""

    def __init__(self, guard: ExposureGuard, mode: str, value: float | None, t_start: float) -> None:
        self.guard = guard
        self.mode = mode.upper()
        self.value = value
        self.actions = 0
        self.events: list[dict[str, Any]] = []
        self.last_fps: float | None = None
        self._times: deque[float] = deque()
        self._since = t_start  # judgements need window_s (AUTO: settle_s) of frames after this
        self._wait = guard.settle_s if self.mode == "AUTO" else guard.window_s
        self._auto_slow_logged = False
        self.inactive_reason = self._inactive_reason()

    def _inactive_reason(self) -> str | None:
        if self.mode == "MANUAL" and self.value is not None \
                and exposure_seconds(self.value) > 1.0 / self.guard.min_fps:
            return (f"exposure {exposure_seconds(self.value) * 1000:.1f} ms is longer than the "
                    f"{1000 / self.guard.min_fps:.1f} ms frame period of min_fps")
        return None

    @property
    def active(self) -> bool:
        return self.inactive_reason is None and self.actions < self.guard.max_actions

    def observe(self, t: float, luminance: float | None = None) -> tuple[str, float | None] | None:
        """Record one unique frame at ``t``; return ``(mode, value)`` to apply, or ``None``."""
        g = self.guard
        self._times.append(t)
        while self._times and self._times[0] < t - g.window_s:
            self._times.popleft()
        if t - self._since < max(self._wait, g.window_s):
            return None
        self.last_fps = (len(self._times) - 1) / g.window_s
        if not self.active or self.last_fps >= g.min_fps:
            return None
        event: dict[str, Any] = {"t": t, "fps": self.last_fps, "luminance": luminance,
                                 "from": {"mode": self.mode, "value": self.value}}
        if self.mode == "AUTO" and g.fallback_value is None:
            if not self._auto_slow_logged:
                self.events.append({**event, "action": "AUTO_SLOW"})
                self._auto_slow_logged = True
            return None
        if self.mode == "AUTO":
            self.mode, self.value = "MANUAL", g.fallback_value
            event["action"] = "AUTO_TO_MANUAL"
            self.inactive_reason = self._inactive_reason()
        else:
            event["action"] = "REAPPLIED"
        self.actions += 1
        if self.actions >= g.max_actions:
            event["note"] = "GAVE_UP: max_actions reached, the guard stops acting"
        event["to"] = {"mode": self.mode, "value": self.value}
        self.events.append(event)
        self._times.clear()
        self._since, self._wait = t, g.window_s
        return self.mode, self.value

    def report(self) -> dict[str, Any]:
        return {"guard": self.guard.to_dict(), "active_mode": self.mode, "active_value": self.value,
                "inactive_reason": self.inactive_reason, "actions": self.actions,
                "last_window_fps": self.last_fps, "events": self.events}


__all__ = ["ExposureGuard", "ExposureWatch", "exposure_seconds"]
