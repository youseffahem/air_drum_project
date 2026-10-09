"""Audio output wiring for the prototype (Phase 05, Task 05.5): scheduler + bank + mixer + device.

The scheduler needs the audio profile's **MEASURED** output latency (Phase 04, Task 04.8) to fill
``AudioEvent.t_audio_out_est``. On HW-01 that measurement is PENDING (Phase 04 gate, criterion 6),
and ``docs/audio-profile-hw01-realtek.md`` forbids a fabricated default. This wrapper therefore
carries an explicit provenance: ``output_latency`` is either ``measured`` (value + run id supplied by
the operator from an accepted run) or ``unmeasured`` (value 0.0 used *only* so the scheduler can
place the sample as early as possible; ``t_audio_out_est`` is then **not** copied into any
``TimingRecord`` — see ``spacedrums.timing.records``). Sound still plays either way; only the
software estimate of the DAC instant is withheld.

Phase 17 (Task 17.5, ADR-0040): the device is supervised. ``check_health(t_now)`` (called once per
processed frame) marks the output ``DOWN`` when the stream stops calling back for ``stall_s`` or
fails to start, and retries every ``retry_s`` (candidates). While ``DOWN`` a commit is still
scheduled and logged (``AudioEvent``) but not enqueued (``dropped_while_down``); a restart clears the
mixer so a recovered device never plays a backlog of stale sounds. Nothing here raises into the
decision loop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from spacedrums.audio import AudioScheduler, CallbackMixer, GainCurve, SampleBank, SoundDeviceOutput
from spacedrums.contracts import AudioEvent, CommittedStrike
from spacedrums.timing import now

log = logging.getLogger(__name__)
STALL_S = 0.5  # candidate: no callback for this long -> DOWN (a 128-sample buffer calls back every ~2.7 ms)
RETRY_S = 1.0  # candidate: restart attempts while DOWN


@dataclass(frozen=True)
class OutputLatency:
    value_s: float
    measured: bool
    run_id: str | None = None

    @property
    def status(self) -> str:
        return "MEASURED" if self.measured else "PENDING"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_s": self.value_s,
            "status": self.status,
            "run_id": self.run_id,
            "note": (
                "accepted post-DAC output-latency run"
                if self.measured
                else "no accepted audio output-latency measurement for this profile (Phase 04 criterion 6 "
                "PENDING); 0.0 is a scheduling placeholder, never an estimate"
            ),
        }

    @classmethod
    def unmeasured(cls) -> OutputLatency:
        return cls(0.0, False, None)


class AudioOutput:
    """Schedules non-shadow commits and (optionally) plays them on the device."""

    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        latency: OutputLatency,
        device_enabled: bool,
        clock: Callable[[], float] = now,
        stream_factory: Callable[..., Any] | None = None,
        stall_s: float = STALL_S,
        retry_s: float = RETRY_S,
        output_scale: float = 1.0,
    ) -> None:
        audio = cfg["audio"]
        self.latency = latency
        self.device_enabled = bool(device_enabled)
        self.clock = clock
        self.stall_s, self.retry_s = float(stall_s), float(retry_s)
        # output_scale attenuates played samples only (unattended soak runs); never a gain curve
        self.output_scale = float(output_scale)
        self.device_state = "DISABLED" if not device_enabled else "STOPPED"
        self.recoveries = self.start_failures = self.outages = 0
        self.dropped_while_down = 0
        self.last_error: str | None = None
        self._next_retry: float | None = None
        self.sample_rate_hz = int(audio["sample_rate_hz"])
        self.buffer_frames = int(audio["buffer_frames"])
        zone_samples = {z["zone_id"]: z["sample_id"] for z in cfg["zones"]}
        self.scheduler = AudioScheduler(
            audio_profile_id=str(audio["audio_profile_id"]),
            output_latency_measured_s=latency.value_s,
            zone_samples=zone_samples,
            clock=clock,
        )
        self.curves = {c["gain_curve_id"]: GainCurve.from_config(c) for c in audio["gain"]["curves"]}
        self.zone_curve = {z["zone_id"]: z["gain_curve_id"] for z in cfg["zones"]}
        self.bank: SampleBank | None = None
        self.mixer: CallbackMixer | None = None
        self.device: SoundDeviceOutput | None = None
        if self.device_enabled:
            self.bank = SampleBank.load(
                audio["sample_bank"]["path"],
                audio["sample_bank"]["manifest"],
                sample_rate_hz=self.sample_rate_hz,
            )
            self.mixer = CallbackMixer(
                self.sample_rate_hz,
                channels=2,
                output_latency_measured_s=latency.value_s if latency.measured else None,
            )
            self.device = SoundDeviceOutput(
                self.mixer,
                sample_rate_hz=self.sample_rate_hz,
                buffer_frames=self.buffer_frames,
                device=audio["device"]["name"],
                stream_factory=stream_factory,
                clock=clock,
                host_api=audio["device"].get("host_api"),
                latency=audio.get("stream_latency", "low"),
                exclusive=bool(audio.get("wasapi_exclusive", False)),
            )
        self.events: int = 0

    def gain(self, zone_id: str, intensity_proxy: float) -> float:
        return float(self.curves[self.zone_curve[zone_id]](intensity_proxy))

    def start(self) -> None:
        """Open the device; a failure leaves the output DOWN (retried by ``check_health``), no raise."""
        if self.device is None:
            return
        try:
            self.device.start()
            self.device_state = "RUNNING"
        except Exception as exc:  # noqa: BLE001 - no audio device must not stop the session
            self.start_failures += 1
            self._down(f"start failed: {type(exc).__name__}: {exc}", self.clock())

    def stop(self) -> None:
        if self.device is not None:
            self.device.stop()
            if self.device_state != "DISABLED":
                self.device_state = "STOPPED"

    def _down(self, reason: str, t_now: float) -> None:
        if self.device_state != "DOWN":
            self.outages += 1
            log.warning("audio output down: %s", reason)
        self.device_state = "DOWN"
        self.last_error = reason
        self._next_retry = t_now + self.retry_s

    def check_health(self, t_now: float) -> str:
        """Supervise the stream once per frame: detect loss, retry, recover. Returns the state."""
        if self.device is None:
            return self.device_state
        if self.device_state == "RUNNING" and not self.device.alive(t_now, self.stall_s):
            self._down(f"no audio callback for more than {self.stall_s:.2f} s", t_now)
        if self.device_state == "DOWN" and self._next_retry is not None and t_now >= self._next_retry:
            self.device.stop()
            assert self.mixer is not None
            self.mixer.clear()  # a recovered device never plays the backlog
            try:
                self.device.start()
            except Exception as exc:  # noqa: BLE001 - keep retrying; the session goes on silently
                self.start_failures += 1
                self.last_error = f"restart failed: {type(exc).__name__}: {exc}"
                self._next_retry = t_now + self.retry_s
            else:
                self.device_state = "RUNNING"
                self.recoveries += 1
                log.warning("audio output recovered")
        return self.device_state

    def play(self, committed: CommittedStrike) -> AudioEvent:
        """Schedule (never a shadow commit — the scheduler refuses) and enqueue if a device runs."""
        event = self.scheduler.schedule(committed)
        if self.mixer is not None and self.bank is not None:
            if self.device_state == "RUNNING":
                data = self.bank[event.sample_id].data
                self.mixer.enqueue(event, data if self.output_scale == 1.0 else data * self.output_scale)
            else:
                self.dropped_while_down += 1
        self.events += 1
        return event

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "events_scheduled": self.events,
            "device_enabled": self.device_enabled,
            "output_latency": self.latency.to_dict(),
            "device": {
                "state": self.device_state,
                "outages": self.outages,
                "recoveries": self.recoveries,
                "start_failures": self.start_failures,
                "dropped_while_down": self.dropped_while_down,
                "last_error": self.last_error,
                "callbacks": getattr(self.device, "callbacks", None),
                "host_api": getattr(self.device, "opened_host_api", None),
                "stream_latency_s": getattr(self.device, "opened_latency_s", None),
                "output_scale": self.output_scale,
            },
        }
        if self.mixer is not None:
            st = self.mixer.stats
            out["mixer"] = {
                "underruns": st.underruns,
                "events_late": st.events_late,
                "events_mixed": st.events_mixed,
                "clipped_samples": st.clipped_samples,
                "voices_cleared": st.voices_cleared,
            }
        return out


__all__ = ["AudioOutput", "OutputLatency"]
