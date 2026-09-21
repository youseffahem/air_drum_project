"""Microphone capture for the optional practice-pad condition (Phase 06, Task 06.6; ADR-0002).

The microphone stream is timestamped on ``t_mono``: every PortAudio input block arrives with the
device clock instants ``inputBufferAdcTime`` (first sample of the block) and ``currentTime``; the
callback pairs ``currentTime`` with ``timing.now()`` in a causal rolling least-squares fit
(``spacedrums.audio.DeviceClockMapper``, the same mapping the output side uses, ADR-0004) and maps the
first sample's ADC time onto ``t_mono``. The residual of that fit is recorded with the track; the
**sync check** against operator-marked claps (``sync_check``) is the independent measurement of the
audio/video alignment the phase document asks for (Pending Benchmark: it needs a pilot).

Everything device-related is isolated in :class:`AudioCapture` (lazy ``sounddevice`` import) and
funnels through :meth:`AudioCapture.on_block`, which the tests drive with SYNTHETIC blocks and device
times. ``detect_onsets`` / ``sync_check`` are pure functions on arrays. No audio is recorded by any
test; no feasibility number exists until the pilot (Task 06.10).
"""

from __future__ import annotations

import hashlib
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from spacedrums import timing
from spacedrums.audio.device import DeviceClockMapper

AUDIO_TRACK_FILENAME = "audio_track.wav"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def write_wav(path: Path, samples: np.ndarray, sample_rate_hz: int) -> Path:
    """PCM-16 WAV (stdlib ``wave``); ``samples`` is float in [-1, 1], shape (n,) or (n, channels)."""
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    pcm = np.clip(np.round(x * 32767.0), -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(x.shape[1])
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate_hz))
        wf.writeframes(pcm.tobytes())
    return path


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """(float32 samples in [-1, 1] shape (n, channels), sample rate)."""
    with wave.open(str(path), "rb") as wf:
        n, ch, sw, sr = wf.getnframes(), wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
        raw = wf.readframes(n)
    if sw != 2:
        raise ValueError(f"{path}: expected 16-bit PCM, got sample width {sw}")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return x.reshape(-1, ch), sr


@dataclass
class AudioCapture:
    """Accumulates input blocks with ``t_mono`` mapping and writes ``audio_track.wav`` + its sidecar.

    ``start()`` opens a ``sounddevice.InputStream`` (PERSON/DEVICE-DEPENDENT: never called by tests);
    ``on_block`` is the device-independent core.
    """

    sample_rate_hz: int = 48000
    channels: int = 1
    device: str | int | None = None
    blocksize: int = 1024

    def __post_init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self._mapper = DeviceClockMapper()
        self._adc_first: float | None = None
        self._stream: Any = None
        self.n_samples = 0
        self.device_name = str(self.device) if self.device is not None else "default input"

    # -- device-independent core -------------------------------------------------------------
    def on_block(self, block: np.ndarray, adc_time: float, current_time: float, t_mono_now: float) -> None:
        """One input block: ``adc_time`` = device time of the block's first sample, ``current_time`` =
        device time when the callback ran, ``t_mono_now`` = ``timing.now()`` at that instant."""
        self._mapper.update(current_time, t_mono_now)
        if self._adc_first is None:
            self._adc_first = float(adc_time)
        x = np.asarray(block, dtype=np.float32)
        if x.ndim == 1:
            x = x[:, None]
        self._blocks.append(x.copy())
        self.n_samples += x.shape[0]

    @property
    def t_mono_first_sample(self) -> float | None:
        if self._adc_first is None:
            return None
        return self._mapper.to_mono(self._adc_first)

    def clock_fit(self) -> dict[str, Any] | None:
        if self._adc_first is None:
            return None
        fit = self._mapper.fit
        return {
            "offset_s": fit.offset_s,
            "slope": fit.slope,
            "residual_rms_s": fit.residual_rms_s,
            "n": fit.n,
        }

    def samples(self) -> np.ndarray:
        if not self._blocks:
            return np.zeros((0, self.channels), np.float32)
        return np.concatenate(self._blocks, axis=0)

    def write(self, session_dir: Path, filename: str = AUDIO_TRACK_FILENAME) -> dict[str, Any]:
        """Write the WAV and return the ``pad_mic.audio_track`` sidecar of the metadata schema."""
        path = Path(session_dir) / filename
        write_wav(path, self.samples(), self.sample_rate_hz)
        return {
            "path": filename,
            "sample_rate_hz": int(self.sample_rate_hz),
            "channels": int(self.channels),
            "dtype": "pcm16",
            "n_samples": int(self.n_samples),
            "t_mono_first_sample": self.t_mono_first_sample,
            "clock_fit": self.clock_fit(),
            "device": self.device_name,
            "sha256": sha256_file(path),
        }

    # -- device lifecycle (not exercised by tests) ------------------------------------------
    def start(self) -> None:  # pragma: no cover - needs a microphone
        import sounddevice as sd

        def callback(indata, frames, time_info, status):  # noqa: ANN001
            self.on_block(indata, time_info.inputBufferAdcTime, time_info.currentTime, timing.now())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate_hz,
            channels=self.channels,
            dtype="float32",
            device=self.device,
            blocksize=self.blocksize,
            callback=callback,
        )
        try:
            self.device_name = str(sd.query_devices(self._stream.device)["name"])
        except Exception:  # noqa: BLE001
            pass
        self._stream.start()

    def stop(self) -> None:  # pragma: no cover - needs a microphone
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


# ----------------------------------------------------------------------------- onset + sync


def detect_onsets(
    samples: np.ndarray,
    sample_rate_hz: int,
    *,
    threshold_ratio: float = 0.3,
    min_gap_s: float = 0.25,
    frame_s: float = 0.005,
) -> list[float]:
    """Times (s from the first sample) of transient onsets: the first analysis frame whose RMS exceeds
    ``threshold_ratio`` x the peak frame RMS after at least ``min_gap_s`` below it. Deterministic; the
    ratio and gap are candidates (a clap is far above room noise; a pad tap in the pilot decides)."""
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    hop = max(1, int(round(frame_s * sample_rate_hz)))
    n = len(x) // hop
    if n == 0:
        return []
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1))
    peak = float(rms.max())
    if peak <= 0:
        return []
    thr = threshold_ratio * peak
    onsets: list[float] = []
    armed = True
    below = 0.0
    for i, v in enumerate(rms):
        if v >= thr:
            if armed:
                onsets.append(i * hop / sample_rate_hz)
                armed = False
            below = 0.0
        else:
            below += frame_s
            if below >= min_gap_s:
                armed = True
    return onsets


@dataclass(frozen=True)
class SyncResult:
    n_markers: int
    n_onsets: int
    n_matched: int
    residuals_s: tuple[float, ...]  # onset - marker, per matched marker (in marker order)
    unmatched_markers: tuple[int, ...]
    window_s: float

    @property
    def residual_rms_s(self) -> float | None:
        if not self.residuals_s:
            return None
        return float(np.sqrt(np.mean(np.square(self.residuals_s))))

    @property
    def residual_max_abs_s(self) -> float | None:
        return max(abs(r) for r in self.residuals_s) if self.residuals_s else None

    @property
    def residual_mean_s(self) -> float | None:
        return float(np.mean(self.residuals_s)) if self.residuals_s else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_markers": self.n_markers,
            "n_onsets": self.n_onsets,
            "n_matched": self.n_matched,
            "residuals_s": list(self.residuals_s),
            "residual_mean_s": self.residual_mean_s,
            "residual_rms_s": self.residual_rms_s,
            "residual_max_abs_s": self.residual_max_abs_s,
            "unmatched_markers": list(self.unmatched_markers),
            "window_s": self.window_s,
        }


def sync_check(
    marker_t_mono: Sequence[float],
    onset_t_mono: Sequence[float],
    *,
    window_s: float = 0.5,
) -> SyncResult:
    """Match operator-marked instants to acoustic onsets (greedy, one-to-one, nearest first, within
    ``window_s``) and report the residual ``onset - marker`` per marker. A marker is the key press
    (reaction-time offset expected, roughly constant); the *spread* of the residuals is the alignment
    quality; the mean is the operator offset. Both are reported; neither is interpreted here."""
    markers = [float(t) for t in marker_t_mono]
    onsets = [float(t) for t in onset_t_mono]
    pairs = sorted(
        (abs(o - m), i, j)
        for i, m in enumerate(markers)
        for j, o in enumerate(onsets)
        if abs(o - m) <= window_s
    )
    used_m: set[int] = set()
    used_o: set[int] = set()
    match: dict[int, int] = {}
    for _, i, j in pairs:
        if i in used_m or j in used_o:
            continue
        used_m.add(i)
        used_o.add(j)
        match[i] = j
    residuals = tuple(onsets[match[i]] - markers[i] for i in sorted(match))
    return SyncResult(
        n_markers=len(markers),
        n_onsets=len(onsets),
        n_matched=len(match),
        residuals_s=residuals,
        unmatched_markers=tuple(i for i in range(len(markers)) if i not in match),
        window_s=window_s,
    )


def onsets_on_t_mono(
    samples: np.ndarray, sample_rate_hz: int, t_mono_first_sample: float, **kwargs: Any
) -> list[float]:
    return [t_mono_first_sample + t for t in detect_onsets(samples, sample_rate_hz, **kwargs)]


def synthetic_clicks(
    sample_rate_hz: int,
    duration_s: float,
    click_times_s: Sequence[float],
    *,
    seed: int = 0,
    noise: float = 0.002,
) -> np.ndarray:
    """SYNTHETIC test signal: low noise floor plus short decaying bursts at ``click_times_s``. For the
    machinery tests only — never evidence of microphone behaviour."""
    rng = np.random.default_rng(seed)
    n = int(round(duration_s * sample_rate_hz))
    x = rng.normal(0.0, noise, n).astype(np.float32)
    burst_n = int(0.02 * sample_rate_hz)
    env = np.exp(-np.arange(burst_n) / (0.004 * sample_rate_hz)).astype(np.float32)
    for t in click_times_s:
        i = int(round(t * sample_rate_hz))
        if 0 <= i < n:
            seg = min(burst_n, n - i)
            x[i : i + seg] += 0.8 * env[:seg] * np.sign(rng.normal(size=seg)).astype(np.float32)
    return np.clip(x, -1.0, 1.0)


__all__ = [
    "AUDIO_TRACK_FILENAME",
    "AudioCapture",
    "SyncResult",
    "detect_onsets",
    "onsets_on_t_mono",
    "read_wav",
    "sha256_file",
    "sync_check",
    "synthetic_clicks",
    "write_wav",
]
