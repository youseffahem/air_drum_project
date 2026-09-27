"""Device and pipeline health: ``HealthStatus {camera, tracking, model, audio}`` for the UI (Phase 17).

``HealthMonitor`` is fed once per processed frame (and by the live source while it waits for a
frame). Every threshold is a **candidate** (``HealthSettings``; ADR-0040), chosen to flag conditions
the failure-injection campaign showed to matter, not tuned on participant data:

* camera   FAIL ``SD-CAM-002`` when no frame arrived for ``stall_s``; WARN ``SD-CAP-001`` when the
           delivered rate over the window (from ``t_capture`` differences, never the requested mode)
           is below ``low_fps_ratio`` x nominal; WARN ``SD-CAP-002`` for ``drops_warn`` or more queue
           drops in the window; WARN ``SD-CAP-003`` for refused / clamped timestamps in the window;
* tracking WARN ``SD-TRK-001`` when the better hand was VALID in less than
           ``poor_tracking_valid_fraction`` of the window's frames;
* model    OFF without a model arm; WARN ``SD-MDL-001`` (``SD-MDL-002`` for a load failure) once the
           sticky fallback disabled it;
* audio    OFF when the device is disabled; FAIL ``SD-AUD-001`` while the stream is down; WARN
           ``SD-AUD-002`` when underruns increased within the window.

A component's transition (level or code change) is written once to the ``EventLog``; the overlay
shows the user text of every non-OK component. The monitor reads and never changes the pipeline.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from spacedrums.app.errors import EventLog, user_text


class Level(StrEnum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    OFF = "OFF"


_RANK = {Level.OFF: 0, Level.OK: 0, Level.WARN: 1, Level.FAIL: 2}


@dataclass(frozen=True)
class ComponentHealth:
    level: Level
    code: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"level": str(self.level), "code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class HealthStatus:
    camera: ComponentHealth
    tracking: ComponentHealth
    model: ComponentHealth
    audio: ComponentHealth
    t: float

    def components(self) -> dict[str, ComponentHealth]:
        return {"camera": self.camera, "tracking": self.tracking, "model": self.model, "audio": self.audio}

    def worst(self) -> Level:
        return max((c.level for c in self.components().values()), key=lambda lv: _RANK[lv])

    def messages(self) -> list[str]:
        return [user_text(c.code) for c in self.components().values() if c.code and c.level != Level.OK]

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "worst": str(self.worst()),
            **{k: v.to_dict() for k, v in self.components().items()},
        }


OK = ComponentHealth(Level.OK)


@dataclass(frozen=True)
class HealthSettings:
    """All values are candidates (ADR-0040); nominal_fps is the requested camera rate."""

    nominal_fps: float
    window_s: float = 2.0
    min_frames: int = 15
    low_fps_ratio: float = 0.8
    stall_s: float = 0.5
    drops_warn: int = 3
    poor_tracking_valid_fraction: float = 0.5

    def __post_init__(self) -> None:
        if self.nominal_fps <= 0 or self.window_s <= 0 or self.stall_s <= 0:
            raise ValueError("nominal_fps, window_s and stall_s must be positive")
        if not 0 < self.low_fps_ratio <= 1 or not 0 <= self.poor_tracking_valid_fraction <= 1:
            raise ValueError("ratios must lie in (0, 1]")

    @classmethod
    def from_config(cls, cfg: dict[str, Any], **overrides: Any) -> HealthSettings:
        return cls(nominal_fps=float(cfg["camera_profile"]["requested_fps"]), **overrides)


class HealthMonitor:
    def __init__(self, settings: HealthSettings, *, events: EventLog | None = None) -> None:
        self.s = settings
        self.events = events
        self._frames: deque[tuple[float, int, bool, bool]] = deque()  # t_capture, drops, valid L, valid R
        self._underruns: deque[tuple[float, int]] = deque()
        self._clamped: deque[tuple[float, int]] = deque()
        self._last_frame_wall: float | None = None
        self._status: HealthStatus | None = None
        self.transitions = 0

    # -- inputs ------------------------------------------------------------------------------
    def observe_frame(
        self,
        result,
        pipeline=None,
        *,
        t_now: float,
        audio_state: str | None = None,
        audio_underruns: int | None = None,
        clamped_timestamps: int | None = None,
    ) -> HealthStatus:
        sample = result.sample
        valid = {str(h): str(hf.track.status) == "VALID" for h, hf in result.hands.items()}
        self._frames.append(
            (
                sample.t_capture,
                int(sample.dropped_since_last),
                valid.get("LEFT", False),
                valid.get("RIGHT", False),
            )
        )
        while self._frames and self._frames[0][0] < sample.t_capture - self.s.window_s:
            self._frames.popleft()
        self._last_frame_wall = t_now
        if audio_underruns is not None:
            self._underruns.append((t_now, int(audio_underruns)))
            while self._underruns and self._underruns[0][0] < t_now - self.s.window_s:
                self._underruns.popleft()
        if clamped_timestamps is not None:
            self._clamped.append((t_now, int(clamped_timestamps)))
            while self._clamped and self._clamped[0][0] < t_now - self.s.window_s:
                self._clamped.popleft()
        status = HealthStatus(
            camera=self._camera(),
            tracking=self._tracking(),
            model=self._model(pipeline),
            audio=self._audio(audio_state),
            t=t_now,
        )
        return self._publish(status)

    def observe_no_frame(self, t_now: float) -> HealthStatus | None:
        """Called by the live source while waiting: a camera stall is visible without frames."""
        if self._last_frame_wall is None or self._status is None:
            return None
        waited = t_now - self._last_frame_wall
        if waited <= self.s.stall_s:
            return self._status
        cam = ComponentHealth(Level.FAIL, "SD-CAM-002", {"waited_s": round(waited, 3)})
        status = HealthStatus(cam, self._status.tracking, self._status.model, self._status.audio, t_now)
        return self._publish(status)

    @property
    def status(self) -> HealthStatus | None:
        return self._status

    # -- components --------------------------------------------------------------------------
    def _camera(self) -> ComponentHealth:
        frames = self._frames
        if len(frames) < self.s.min_frames:
            return OK
        span = frames[-1][0] - frames[0][0]
        fps = (len(frames) - 1) / span if span > 0 else None
        drops = sum(f[1] for f in frames)
        clamped = self._clamped[-1][1] - self._clamped[0][1] if len(self._clamped) > 1 else 0
        if fps is not None and fps < self.s.low_fps_ratio * self.s.nominal_fps:
            return ComponentHealth(Level.WARN, "SD-CAP-001", {"delivered_fps": round(fps, 2)})
        if drops >= self.s.drops_warn:
            return ComponentHealth(Level.WARN, "SD-CAP-002", {"drops_in_window": drops})
        if clamped > 0:
            return ComponentHealth(Level.WARN, "SD-CAP-003", {"timestamp_interventions": clamped})
        return ComponentHealth(Level.OK, None, {"delivered_fps": None if fps is None else round(fps, 2)})

    def _tracking(self) -> ComponentHealth:
        frames = self._frames
        if len(frames) < self.s.min_frames:
            return OK
        n = len(frames)
        left = sum(f[2] for f in frames) / n
        right = sum(f[3] for f in frames) / n
        detail = {"valid_fraction_left": round(left, 3), "valid_fraction_right": round(right, 3)}
        if max(left, right) < self.s.poor_tracking_valid_fraction:
            return ComponentHealth(Level.WARN, "SD-TRK-001", detail)
        return ComponentHealth(Level.OK, None, detail)

    def _model(self, pipeline) -> ComponentHealth:
        if pipeline is None or getattr(pipeline, "model_label", None) is None:
            return ComponentHealth(Level.OFF)
        error = pipeline.model_error
        if error is None:
            return OK
        code = "SD-MDL-002" if str(error).startswith("load failure") else "SD-MDL-001"
        return ComponentHealth(
            Level.WARN, code, {"reason": str(error)[:200], "active_arm": str(pipeline.active_arm)}
        )

    def _audio(self, state: str | None) -> ComponentHealth:
        if state is None or state == "DISABLED":
            return ComponentHealth(Level.OFF)
        if state != "RUNNING":
            return ComponentHealth(Level.FAIL, "SD-AUD-001", {"state": state})
        grew = self._underruns[-1][1] - self._underruns[0][1] if len(self._underruns) > 1 else 0
        if grew > 0:
            return ComponentHealth(Level.WARN, "SD-AUD-002", {"underruns_in_window": grew})
        return OK

    # -- publication -------------------------------------------------------------------------
    def _publish(self, status: HealthStatus) -> HealthStatus:
        previous = self._status
        self._status = status
        if self.events is None:
            return status
        for name, comp in status.components().items():
            before = previous.components()[name] if previous is not None else OK
            if (comp.level, comp.code) == (before.level, before.code):
                continue
            self.transitions += 1
            if comp.code is not None:
                self.events.emit(comp.code, detail={"component": name, **comp.detail}, t_mono=status.t)
            elif before.code == "SD-AUD-001" and name == "audio":
                self.events.emit("SD-AUD-003", detail={"component": name}, t_mono=status.t)
        return status


__all__ = ["ComponentHealth", "HealthMonitor", "HealthSettings", "HealthStatus", "Level"]
