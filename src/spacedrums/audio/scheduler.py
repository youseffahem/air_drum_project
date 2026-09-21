"""Time-targeted scheduler producing the Phase 01 AudioEvent contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from spacedrums.contracts import AudioEvent, CommittedStrike


class AudioScheduler:
    def __init__(
        self,
        *,
        audio_profile_id: str,
        output_latency_measured_s: float,
        zone_samples: Mapping[str, str],
        clock: Callable[[], float],
    ) -> None:
        if output_latency_measured_s < 0:
            raise ValueError("measured output latency must be non-negative")
        self.audio_profile_id = audio_profile_id
        self.output_latency_measured_s = float(output_latency_measured_s)
        self.zone_samples = dict(zone_samples)
        self.clock = clock

    def schedule(self, committed: CommittedStrike) -> AudioEvent:
        if committed.shadow:
            raise ValueError("shadow commits must never be scheduled to audio")
        now = float(self.clock())
        target = float(committed.t_impact_target)
        late = max(0.0, now - target)
        out_est = target if target >= now else now + self.output_latency_measured_s
        return AudioEvent(
            strike_id=committed.strike_id,
            sample_id=self.zone_samples[committed.zone_id],
            t_audio_scheduled=now,
            t_target_play=target,
            t_audio_out_est=out_est,
            audio_late_s=late,
            gain=committed.gain,
            audio_profile_id=self.audio_profile_id,
        )

    @staticmethod
    def timing_record_fields(event: AudioEvent) -> dict[str, float]:
        """Fields the Phase 05 timing collector copies into its ``TimingRecord``."""
        return {"t_audio_scheduled": event.t_audio_scheduled,
                "t_audio_out_est": event.t_audio_out_est}


__all__ = ["AudioScheduler"]
