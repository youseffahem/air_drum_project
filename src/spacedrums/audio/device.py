"""Device-stream clock to project monotonic-clock mapping."""

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import Callable
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
    Phase 17: ``stream_factory`` (default ``sounddevice.OutputStream``) and ``clock`` are injectable;
    ``alive()`` reports whether callbacks still arrive (a removed device stops calling back or
    deactivates the stream), and a restart re-opens the stream with a fresh clock mapping.
    """

    def __init__(
        self,
        mixer: CallbackMixer,
        *,
        sample_rate_hz: int,
        buffer_frames: int,
        device: int | str | None = None,
        stream_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] = now,
    ) -> None:
        self.mixer, self.mapper = mixer, DeviceClockMapper()
        self.sample_rate_hz, self.buffer_frames = int(sample_rate_hz), int(buffer_frames)
        self.device = device
        self.stream: Any | None = None
        self.stream_factory = stream_factory
        self.clock = clock
        self.callbacks = 0
        self.last_callback_t: float | None = None
        self.started_t: float | None = None

    def alive(self, t_now: float, stall_s: float) -> bool:
        """True while the stream is active and called back within ``stall_s`` (or since the start)."""
        if self.stream is None or not bool(getattr(self.stream, "active", True)):
            return False
        ref = self.last_callback_t if self.last_callback_t is not None else self.started_t
        return ref is not None and (t_now - ref) <= stall_s

    def _callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        t = self.clock()
        self.callbacks += 1
        self.last_callback_t = t
        self.mapper.update(float(time_info.currentTime), t)
        if bool(getattr(status, "output_underflow", False)):
            self.mixer.note_underrun()
        t_buffer_start = self.mapper.to_mono(float(time_info.outputBufferDacTime))
        outdata[:] = self.mixer.mix(frames, t_buffer_start)

    def start(self) -> None:
        if self.stream is not None:
            raise RuntimeError("audio stream already started")
        factory = self.stream_factory
        if factory is None:
            import sounddevice as sd

            factory = sd.OutputStream
        stream = factory(
            samplerate=self.sample_rate_hz,
            blocksize=self.buffer_frames,
            channels=self.mixer.channels,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        try:
            stream.start()
        except BaseException:
            with contextlib.suppress(Exception):
                stream.close()
            raise
        self.mapper = DeviceClockMapper()  # a re-opened device may restart its stream clock
        self.last_callback_t = None
        self.started_t = self.clock()
        self.stream = stream

    def stop(self) -> None:
        """Stop and close; errors from a device that is already gone are swallowed (Phase 17)."""
        stream, self.stream = self.stream, None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:  # noqa: BLE001 - the device may have vanished; closing must still happen
            pass
        with contextlib.suppress(Exception):
            stream.close()

    def __enter__(self) -> SoundDeviceOutput:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


__all__ = ["ClockFit", "DeviceClockMapper", "SoundDeviceOutput"]
