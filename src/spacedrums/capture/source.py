"""``LiveFrameSource``: capture thread -> t_capture -> t_frame_available -> bounded queue -> FrameSample.

Implements ``spacedrums.contracts.interfaces.FrameSource`` (architecture.md section 11) with the
T1 threading baseline (ADR-0009): one capture thread pulls frames from a :class:`CameraBackend`,
stamps them, and pushes into a :class:`BoundedFrameQueue` (drop-oldest, drops counted); the
consumer thread turns queued frames into ``FrameSample``s in ``frame_id`` order.

Timestamp policy (architecture.md section 5.2, Task 02.2), per frame and labelled per frame:

* requested ``DRIVER_MAPPED`` and the backend supplies a monotone driver timestamp: once the
  mapper's warm-up window is fitted, ``t_capture = map(t_drv)`` and
  ``timestamp_source = DRIVER_MAPPED``; the warm-up frames themselves and any frame without a
  driver stamp are labelled ``GRAB_RETURN`` (honest per-frame labelling, never a guess);
* otherwise ``t_capture = t_grab_return - grab_return_bias_s`` and ``GRAB_RETURN``.

``t_frame_available = now()`` at enqueue. Two invariants are enforced by clamping *and counted*
(``CaptureStats.clamped_timestamps``; must be 0 in a healthy run): ``t_capture <=
t_frame_available`` and monotone ``t_capture``.

Duplicate policy (Task 02.4 finding on HW-01): a frame that is byte-identical to the previous
delivered frame carries no new observation (a real sensor frame always differs by noise) and is
what the Windows camera pipeline pads with when the sensor runs below the nominal rate. Such
frames are *not* delivered and are counted in ``CaptureStats.duplicates``; counting them as
frames would present padded frames as native FPS (integrity I-5). ``frame_id`` is assigned only
at delivery, so neither duplicates nor dropped frames consume an id (contracts.md section 1).

No frame interpolation, upsampling or resampling happens anywhere in this module.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np

from spacedrums import timing
from spacedrums.capture.backend import CameraBackend, CameraOpenSpec, NegotiatedMode
from spacedrums.capture.frame_queue import BoundedFrameQueue
from spacedrums.capture.roi import Roi, crop_roi
from spacedrums.capture.stats import CaptureStats, StallDetector, interval_stats
from spacedrums.capture.timestamps import DriverTimestampMapper, GrabReturnStamper
from spacedrums.contracts import FrameSample, FrameView, ImageRef, TimestampSource


@dataclass(frozen=True)
class CaptureSettings:
    """Everything the source needs, derived from the ``camera_profile`` + ``roi`` config blocks."""

    camera_profile_id: str
    spec: CameraOpenSpec
    roi: Roi | None  # None = full frame
    timestamp_source: TimestampSource = TimestampSource.GRAB_RETURN
    grab_return_bias_s: float = 0.0
    queue_max_frames: int = 2
    stall_factor: float = 2.0
    nominal_fps: float | None = None  # requested rate; only used for the stall threshold
    dedupe: bool = True
    warmup_frames: int = 10
    mapper_warmup_n: int = 60

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, dedupe: bool = True) -> CaptureSettings:
        cam = cfg["camera_profile"]
        exp = cam["exposure"]
        bias = cam.get("grab_return_bias_s")
        return cls(
            camera_profile_id=cam["profile_id"],
            spec=CameraOpenSpec(
                index=cam["device"]["index"] if cam["device"]["index"] is not None else 0,
                backend=cam["device"]["backend"],
                width=cam["resolution_px"][0],
                height=cam["resolution_px"][1],
                fps=cam["requested_fps"],
                pixel_format=cam.get("pixel_format"),
                exposure_mode=exp["mode"],
                exposure_value=exp["value"],
            ),
            roi=Roi.from_rect(cfg["roi"]["px"]) if cfg.get("roi") else None,
            timestamp_source=TimestampSource(cam["timestamp_source"]),
            grab_return_bias_s=float(bias["value_s"]) if bias else 0.0,
            queue_max_frames=int(cam["queue"]["max_frames"]),
            stall_factor=float(cam["queue"]["stall_factor"]),
            nominal_fps=float(cam["requested_fps"]),
            dedupe=dedupe,
        )


@dataclass(frozen=True)
class _Pending:
    image: np.ndarray
    t_capture: float
    t_frame_available: float
    source: TimestampSource


def _same_image(a: np.ndarray, b: np.ndarray) -> bool:
    """Byte-identity check; cheap strided pre-check before the full comparison."""
    if a.shape != b.shape or a.dtype != b.dtype:
        return False
    if not np.array_equal(a[::8, ::8], b[::8, ::8]):
        return False
    return bool(np.array_equal(a, b))


class LiveFrameSource:
    """Live ``FrameSource``. Use as a context manager or call :meth:`start` / :meth:`stop`."""

    def __init__(self, camera: CameraBackend, settings: CaptureSettings) -> None:
        self.camera = camera
        self.settings = settings
        self.negotiated: NegotiatedMode | None = None
        self.exposure_report: dict[str, Any] | None = None
        self._queue: BoundedFrameQueue[_Pending] = BoundedFrameQueue(settings.queue_max_frames)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._next_frame_id = 0
        self._frame_size: tuple[int, int] | None = None
        self._roi: Roi | None = settings.roi
        self._mapper = DriverTimestampMapper(warmup_n=settings.mapper_warmup_n)
        self._grab = GrabReturnStamper(settings.grab_return_bias_s)
        nominal = 1.0 / settings.nominal_fps if settings.nominal_fps else None
        self._stall = StallDetector(nominal, settings.stall_factor) if nominal else None
        self._recent_t_capture: deque[float] = deque(maxlen=900)
        # counters (guarded by _lock)
        self._duplicates = 0
        self._stalled = 0
        self._clamped = 0
        self._read_failures = 0
        self._raw_frames = 0
        self._driver_mapped = 0
        self._grab_return = 0
        self._thread_cpu_s = 0.0
        self._thread_wall_s = 0.0
        self._cpu0 = 0.0
        self._wall0 = 0.0
        self._error: BaseException | None = None

    # -- lifecycle -------------------------------------------------------------------------
    def start(self) -> NegotiatedMode:
        if self._thread is not None:
            raise RuntimeError("already started")
        self.negotiated = self.camera.open(self.settings.spec)
        self._frame_size = (self.negotiated.width, self.negotiated.height)
        if self._roi is None:
            self._roi = Roi.full_frame(*self._frame_size)
        elif not self._roi.fits(*self._frame_size):
            self.camera.close()
            raise ValueError(
                f"ROI {self._roi.as_tuple()} does not fit the negotiated frame {self._frame_size}"
            )
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="spacedrums-capture", daemon=True)
        self._thread.start()
        return self.negotiated

    def stop(self) -> None:
        self._stop.set()
        self._queue.close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self.camera.close()

    def __enter__(self) -> LiveFrameSource:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- capture thread ----------------------------------------------------------------------
    def _run(self) -> None:
        self._cpu0 = timing.thread_cpu_seconds()
        self._wall0 = timing.now()
        try:
            self._capture_loop()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the consumer via stats/raise
            self._error = exc
        finally:
            self._update_cpu_usage()
            self._queue.close()

    def _update_cpu_usage(self) -> None:
        """Called from the capture thread only (thread CPU time is per calling thread)."""
        with self._lock:
            self._thread_cpu_s = timing.thread_cpu_seconds() - self._cpu0
            self._thread_wall_s = timing.now() - self._wall0

    def _capture_loop(self) -> None:
        s = self.settings
        prev_image: np.ndarray | None = None
        last_t_capture: float | None = None
        warmup_left = s.warmup_frames
        exposure_reapplied = False
        while not self._stop.is_set():
            raw = self.camera.read()
            if raw is None:
                if self._stop.is_set() or getattr(self.camera, "n_frames", None) is not None:
                    break  # finite (synthetic) source exhausted, or stopping
                with self._lock:
                    self._read_failures += 1
                timing.sleep_s(0.005)
                continue
            with self._lock:
                self._raw_frames += 1
                raw_n = self._raw_frames
            if raw_n % 30 == 0:
                self._update_cpu_usage()
            if warmup_left > 0:
                warmup_left -= 1
                prev_image = raw.image
                continue
            if not exposure_reapplied:
                # MSMF honours exposure only once streaming (backend.py); harmless elsewhere.
                self.exposure_report = self.camera.apply_exposure(
                    s.spec.exposure_mode, s.spec.exposure_value
                )
                exposure_reapplied = True
            if self._stall is not None and self._stall.observe(raw.t_grab_return):
                with self._lock:
                    self._stalled += 1
            if s.dedupe and prev_image is not None and _same_image(raw.image, prev_image):
                with self._lock:
                    self._duplicates += 1
                continue
            prev_image = raw.image

            # --- t_capture policy (per-frame label) ---
            src = TimestampSource.GRAB_RETURN
            t_cap: float | None = None
            if s.timestamp_source is TimestampSource.DRIVER_MAPPED and raw.t_driver_s is not None \
                    and self._mapper.monotone:
                self._mapper.add(raw.t_driver_s, raw.t_grab_return)
                if self._mapper.ready:
                    t_cap = self._mapper.to_mono(raw.t_driver_s)
                    src = TimestampSource.DRIVER_MAPPED
            if t_cap is None:
                t_cap = self._grab.to_mono(raw.t_grab_return)
            t_avail = timing.now()
            clamped = 0
            if t_cap > t_avail:
                t_cap = t_avail
                clamped = 1
            if last_t_capture is not None and t_cap < last_t_capture:
                t_cap = last_t_capture
                clamped = 1
            last_t_capture = t_cap
            with self._lock:
                self._clamped += clamped
                if src is TimestampSource.DRIVER_MAPPED:
                    self._driver_mapped += 1
                else:
                    self._grab_return += 1
            self._queue.put(_Pending(raw.image, t_cap, t_avail, src))

    # -- consumer side ---------------------------------------------------------------------
    def next_frame(self, timeout: float | None = 1.0) -> FrameSample | None:
        """Next delivered frame, or ``None`` on timeout / when the source is exhausted."""
        if self._error is not None:
            raise RuntimeError("capture thread failed") from self._error
        got = self._queue.get(timeout)
        if got is None:
            if self._error is not None:
                raise RuntimeError("capture thread failed") from self._error
            return None
        pending, since = got
        assert self._frame_size is not None and self._roi is not None
        frame_id = self._next_frame_id
        self._next_frame_id += 1
        self._recent_t_capture.append(pending.t_capture)
        return FrameSample(
            frame_id=frame_id,
            t_capture=pending.t_capture,
            t_frame_available=pending.t_frame_available,
            timestamp_source=pending.source,
            frame_size_px=self._frame_size,
            roi_px=self._roi.as_tuple(),
            image_ref=ImageRef.memory(pending.image),
            camera_profile_id=self.settings.camera_profile_id,
            dropped_since_last=since,
        )

    def __iter__(self) -> Iterator[FrameSample]:
        while True:
            if self._queue.closed and len(self._queue) == 0:
                return
            sample = self.next_frame(timeout=0.5)
            if sample is not None:
                yield sample
            elif self._queue.closed:
                return

    def view(self, sample: FrameSample) -> FrameView:
        """``FrameView`` with the ROI crop as a pure slice of the in-memory frame."""
        full = sample.image_ref.array
        if full is None:
            raise ValueError("sample carries no in-memory image")
        return FrameView(sample=sample, roi=crop_roi(full, Roi.from_rect(sample.roi_px)), full=full)

    @property
    def roi(self) -> Roi | None:
        return self._roi

    # -- reporting -------------------------------------------------------------------------
    def stats(self) -> CaptureStats:
        with self._lock:
            dup, stalled, clamped = self._duplicates, self._stalled, self._clamped
        fps = p50 = p99 = None
        if len(self._recent_t_capture) >= 2:
            nominal = 1.0 / self.settings.nominal_fps if self.settings.nominal_fps else None
            st = interval_stats(list(self._recent_t_capture), nominal,
                                stall_factor=self.settings.stall_factor)
            fps, p50, p99 = st.fps, st.p50_s, st.p99_s
        return CaptureStats(
            delivered=self._queue.delivered, dropped=self._queue.dropped, stalled=stalled,
            duplicates=dup, fps_measured=fps, interval_p50=p50, interval_p99=p99,
            clamped_timestamps=clamped,
        )

    def timestamp_report(self) -> dict[str, Any]:
        """Which policy actually applied, mapper residuals, thread CPU usage."""
        with self._lock:
            rep = {
                "requested_policy": str(self.settings.timestamp_source),
                "frames_driver_mapped": self._driver_mapped,
                "frames_grab_return": self._grab_return,
                "grab_return_bias_s": self.settings.grab_return_bias_s,
                "raw_frames_read": self._raw_frames,
                "read_failures": self._read_failures,
                "capture_thread_cpu_s": self._thread_cpu_s,
                "capture_thread_wall_s": self._thread_wall_s,
                "capture_thread_cpu_fraction": (self._thread_cpu_s / self._thread_wall_s)
                if self._thread_wall_s > 0 else None,
            }
        rep["driver_mapper"] = self._mapper.residual_stats()
        rep["driver_timestamps_seen"] = self._mapper.n_pairs > 0
        return rep


__all__ = ["CaptureSettings", "LiveFrameSource"]
