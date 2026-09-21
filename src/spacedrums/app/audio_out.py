"""Audio output wiring for the prototype (Phase 05, Task 05.5): scheduler + bank + mixer + device.

The scheduler needs the audio profile's **MEASURED** output latency (Phase 04, Task 04.8) to fill
``AudioEvent.t_audio_out_est``. On HW-01 that measurement is PENDING (Phase 04 gate, criterion 6),
and ``docs/audio-profile-hw01-realtek.md`` forbids a fabricated default. This wrapper therefore
carries an explicit provenance: ``output_latency`` is either ``measured`` (value + run id supplied by
the operator from an accepted run) or ``unmeasured`` (value 0.0 used *only* so the scheduler can
place the sample as early as possible; ``t_audio_out_est`` is then **not** copied into any
``TimingRecord`` — see ``spacedrums.timing.records``). Sound still plays either way; only the
software estimate of the DAC instant is withheld.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from spacedrums.audio import AudioScheduler, CallbackMixer, GainCurve, SampleBank, SoundDeviceOutput
from spacedrums.contracts import AudioEvent, CommittedStrike
from spacedrums.timing import now


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
    ) -> None:
        audio = cfg["audio"]
        self.latency = latency
        self.device_enabled = bool(device_enabled)
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
            )
        self.events: int = 0

    def gain(self, zone_id: str, intensity_proxy: float) -> float:
        return float(self.curves[self.zone_curve[zone_id]](intensity_proxy))

    def start(self) -> None:
        if self.device is not None:
            self.device.start()

    def stop(self) -> None:
        if self.device is not None:
            self.device.stop()

    def play(self, committed: CommittedStrike) -> AudioEvent:
        """Schedule (never a shadow commit — the scheduler refuses) and enqueue if a device runs."""
        event = self.scheduler.schedule(committed)
        if self.mixer is not None and self.bank is not None:
            self.mixer.enqueue(event, self.bank[event.sample_id].data)
        self.events += 1
        return event

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "events_scheduled": self.events,
            "device_enabled": self.device_enabled,
            "output_latency": self.latency.to_dict(),
        }
        if self.mixer is not None:
            st = self.mixer.stats
            out["mixer"] = {
                "underruns": st.underruns,
                "events_late": st.events_late,
                "events_mixed": st.events_mixed,
                "clipped_samples": st.clipped_samples,
            }
        return out


__all__ = ["AudioOutput", "OutputLatency"]
