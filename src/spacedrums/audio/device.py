"""Device-stream clock to project monotonic-clock mapping."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from spacedrums.audio.mixer import CallbackMixer
from spacedrums.timing import now


@dataclass(frozen=True)
class ClockFit:
    offset_s: float
    slope: float
    residual_rms_s: float
    n: int


class DeviceClockMapper:
    """Causal rolling least-squares mapping: t_mono = offset + slope * t_device."""

    def __init__(self, max_samples: int = 256) -> None:
        if max_samples < 2:
            raise ValueError("max_samples must be >= 2")
        self._pairs: deque[tuple[float, float]] = deque(maxlen=max_samples)

    def update(self, t_device: float, t_mono: float) -> ClockFit:
        self._pairs.append((float(t_device), float(t_mono)))
        return self.fit

    @property
    def fit(self) -> ClockFit:
        if not self._pairs:
            raise RuntimeError("clock mapper has no samples")
        x = np.asarray([p[0] for p in self._pairs], dtype=np.float64)
        y = np.asarray([p[1] for p in self._pairs], dtype=np.float64)
        if len(x) == 1 or float(np.ptp(x)) == 0.0:
            slope, offset = 1.0, float(y[-1] - x[-1])
        else:
            xc = x - x.mean()
            slope = float(np.dot(xc, y - y.mean()) / np.dot(xc, xc))
            offset = float(y.mean() - slope * x.mean())
        residual = y - (offset + slope * x)
        return ClockFit(offset, slope, float(np.sqrt(np.mean(residual**2))), len(x))

    def to_mono(self, t_device: float) -> float:
        fit = self.fit
        return fit.offset_s + fit.slope * float(t_device)


class SoundDeviceOutput:
    """Thin lifecycle wrapper around a PortAudio output callback.

    Import is delayed so geometry/tests do not need an audio device. Device callback timestamps
    are mapped into the project's monotonic clock before the mixer computes sample offsets.
    """

    def __init__(
        self,
        mixer: CallbackMixer,
        *,
        sample_rate_hz: int,
        buffer_frames: int,
        device: int | str | None = None,
    ) -> None:
        self.mixer, self.mapper = mixer, DeviceClockMapper()
        self.sample_rate_hz, self.buffer_frames = int(sample_rate_hz), int(buffer_frames)
        self.device = device
        self.stream: Any | None = None

    def _callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        self.mapper.update(float(time_info.currentTime), now())
        if bool(getattr(status, "output_underflow", False)):
            self.mixer.note_underrun()
        t_buffer_start = self.mapper.to_mono(float(time_info.outputBufferDacTime))
        outdata[:] = self.mixer.mix(frames, t_buffer_start)

    def start(self) -> None:
        if self.stream is not None:
            raise RuntimeError("audio stream already started")
        import sounddevice as sd

        self.stream = sd.OutputStream(
            samplerate=self.sample_rate_hz,
            blocksize=self.buffer_frames,
            channels=self.mixer.channels,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self.stream.start()

    def stop(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def __enter__(self) -> SoundDeviceOutput:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


__all__ = ["ClockFit", "DeviceClockMapper", "SoundDeviceOutput"]
