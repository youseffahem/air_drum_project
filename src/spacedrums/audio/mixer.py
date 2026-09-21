"""Callback mixer with exact within-buffer start offsets, polyphony and late handling."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, SimpleQueue

import numpy as np

from spacedrums.contracts import AudioEvent


@dataclass
class Voice:
    event: AudioEvent
    samples: np.ndarray
    cursor: int = 0


@dataclass(frozen=True)
class AudioStats:
    underruns: int
    events_late: int
    events_mixed: int
    clipped_samples: int
    output_latency_measured_s: float | None


class CallbackMixer:
    def __init__(
        self, sample_rate_hz: int, channels: int = 2, output_latency_measured_s: float | None = None
    ) -> None:
        if sample_rate_hz < 1 or channels < 1:
            raise ValueError("invalid mixer format")
        self.sample_rate_hz, self.channels = int(sample_rate_hz), int(channels)
        self.output_latency_measured_s = output_latency_measured_s
        self._queue: SimpleQueue[Voice] = SimpleQueue()
        self._voices: list[Voice] = []
        self._underruns = self._events_late = self._events_mixed = self._clipped_samples = 0

    def enqueue(self, event: AudioEvent, samples: np.ndarray) -> None:
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1:
            raise ValueError("mixer input samples must be mono")
        self._queue.put(Voice(event, audio))

    def note_underrun(self) -> None:
        self._underruns += 1

    def mix(self, frames: int, t_buffer_start: float) -> np.ndarray:
        while True:
            try:
                self._voices.append(self._queue.get_nowait())
            except Empty:
                break
        out = np.zeros((frames, self.channels), dtype=np.float32)
        buffer_end = t_buffer_start + frames / self.sample_rate_hz
        keep: list[Voice] = []
        for voice in self._voices:
            requested = voice.event.t_target_play
            if requested >= buffer_end:
                keep.append(voice)
                continue
            offset = int(round((requested - t_buffer_start) * self.sample_rate_hz))
            if offset < 0:
                if voice.cursor == 0:
                    self._events_late += 1
                offset = 0
            available = frames - offset
            n = min(available, len(voice.samples) - voice.cursor)
            if n > 0:
                mono = voice.samples[voice.cursor : voice.cursor + n] * voice.event.gain
                out[offset : offset + n, :] += mono[:, None]
                voice.cursor += n
                self._events_mixed += 1
            if voice.cursor < len(voice.samples):
                keep.append(voice)
        self._voices = keep
        clipped = np.count_nonzero((out > 1.0) | (out < -1.0))
        self._clipped_samples += int(clipped)
        np.clip(out, -1.0, 1.0, out=out)
        return out

    @property
    def stats(self) -> AudioStats:
        return AudioStats(
            self._underruns,
            self._events_late,
            self._events_mixed,
            self._clipped_samples,
            self.output_latency_measured_s,
        )


__all__ = ["AudioStats", "CallbackMixer", "Voice"]
