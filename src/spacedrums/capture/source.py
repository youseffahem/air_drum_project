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

``t_frame_available = now()`` at enqueue. Two invariants are enforced *and counted*
(``CaptureStats.clamped_timestamps``; must be 0 in a healthy run): ``t_capture <=
t_frame_available`` (clamped) and **strictly increasing** ``t_capture``: a frame whose stamp would
not exceed the previous delivered one is refused, never delivered with an equal stamp (Phase 17:
an equal stamp stopped the decision pipeline; ``timestamp_report()["refused_non_monotone"]``).

Duplicate policy (Task 02.4 finding on HW-01): a frame that is byte-identical to the previous
delivered frame carries no new observation (a real sensor frame always differs by noise) and is
what the Windows camera pipeline pads with when the sensor runs below the nominal rate. Such
frames are *not* delivered and are counted in ``CaptureStats.duplicates``; counting them as
frames would present padded frames as native FPS (integrity I-5). ``frame_id`` is assigned only
at delivery, so neither duplicates nor dropped frames consume an id (contracts.md section 1).

No frame interpolation or upsampling happens anywhere in this module. With
``camera_profile.native_capture`` (ADR-0047) the camera is opened in its native mode, the open is
verified (negotiated and delivered size, unique-frame rate) and, if it fails, the standard
``resolution_px`` mode is reopened (``capture_report()["mode"] == "STANDARD_FALLBACK"``). Each
delivered native frame is then cut to the configured window and area-downscaled to
``resolution_px`` (``capture.native.tracking_frame``) before ``t_frame_available``, so tracking keeps
its geometry and the conversion cost is inside the measured hand-over; the native-resolution window
is kept for display only (:meth:`LiveFrameSource.preview_image`). Duplicates are detected on the
native frame.

With ``camera_profile.exposure.guard`` (ADR-0048) the capture thread measures the unique-frame rate
and re-applies the requested exposure (or replaces a too-slow AUTO with the fallback value) when
another application or the camera changed it; see ``capture.exposure``. The action runs after the
frame is queued; ``capture_report()["exposure"]`` lists every action.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from spacedrums import timing
from spacedrums.capture.backend import CameraBackend, CameraOpenSpec, NegotiatedMode
from spacedrums.capture.exposure import ExposureGuard, ExposureWatch
from spacedrums.capture.frame_queue import BoundedFrameQueue
from spacedrums.capture.native import NativeCapture, NativeModeRejected, crop_view, tracking_frame
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
    native: NativeCapture | None = None  # None = capture resolution_px directly (the standard mode)
    exposure_guard: ExposureGuard | None = None  # None = trust the driver (the previous behaviour)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, dedupe: bool = True) -> CaptureSettings:
        cam = cfg["camera_profile"]
        exp = cam["exposure"]
        bias = cam.get("grab_return_bias_s")
        native = cam.get("native_capture")
        guard = exp.get("guard")
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
                controls=tuple((k, float(v)) for k, v in (cam.get("controls") or {}).items()),
            ),
            roi=Roi.from_rect(cfg["roi"]["px"]) if cfg.get("roi") else None,
            timestamp_source=TimestampSource(cam["timestamp_source"]),
            grab_return_bias_s=float(bias["value_s"]) if bias else 0.0,
            queue_max_frames=int(cam["queue"]["max_frames"]),
            stall_factor=float(cam["queue"]["stall_factor"]),
            nominal_fps=float(cam["requested_fps"]),
            dedupe=dedupe,
            native=NativeCapture.from_config(native) if native else None,
            exposure_guard=ExposureGuard.from_config(guard) if guard else None,
        )


@dataclass(frozen=True)
class _Pending:
    image: np.ndarray
    t_capture: float
    t_frame_available: float
    source: TimestampSource
    preview: np.ndarray | None = None  # native-resolution tracking window (display only)


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
        self._depth_at_get: Counter[int] = Counter()  # consumer thread only (queue_report)
        # counters (guarded by _lock)
        self._duplicates = 0
        self._stalled = 0
        self._clamped = 0
        self._refused = 0
        self._read_failures = 0
        self._raw_frames = 0
        self._driver_mapped = 0
        self._grab_return = 0
        self._thread_cpu_s = 0.0
        self._thread_wall_s = 0.0
        self._cpu0 = 0.0
        self._wall0 = 0.0
        self._error: BaseException | None = None
        self._native: NativeCapture | None = None  # set only once a native open is verified
        self._capture_report: dict[str, Any] = {}
        self._convert_s: deque[float] = deque(maxlen=900)  # guarded by _lock
        self._preview: tuple[int, np.ndarray | None] | None = None  # consumer thread only
        self._watch: ExposureWatch | None = None  # capture thread; read via capture_report()

    # -- lifecycle -------------------------------------------------------------------------
    def start(self) -> NegotiatedMode:
        if self._thread is not None:
            raise RuntimeError("already started")
        if self.settings.native is not None:
            self.negotiated = self._open_native(self.settings.native)
        else:
            self.negotiated = self.camera.open(self.settings.spec)
            self._capture_report = {"mode": "STANDARD"}
        if self._native is not None:
            self._frame_size = (int(self.settings.spec.width), int(self.settings.spec.height))
        else:
            self._frame_size = (self.negotiated.width, self.negotiated.height)
        self._capture_report["tracking_px"] = list(self._frame_size)
        self._capture_report["controls"] = getattr(self.camera, "controls_report", None)
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

    def _open_native(self, native: NativeCapture) -> NegotiatedMode:
        """Open the native mode and verify it; reopen the standard mode if it is not delivered."""
        spec = self.settings.spec
        if not (spec.width and spec.height):
            raise ValueError("native_capture needs camera_profile.resolution_px (the tracking size)")
        native.check((spec.width, spec.height))
        report: dict[str, Any] = {"native_capture": native.to_dict()}
        try:
            try:
                request = replace(spec, width=native.request_px[0], height=native.request_px[1])
                mode = self.camera.open(request)
            except RuntimeError as exc:
                raise NativeModeRejected(f"native open failed: {exc}") from exc
            report["native_negotiated"] = mode.to_dict()
            report["probe"] = self._probe_native(native, mode)
        except NativeModeRejected as exc:
            self.camera.close()
            if native.fallback == "FAIL":
                raise
            report.update(mode="STANDARD_FALLBACK", rejected=str(exc), probe=exc.probe)
            self._capture_report = report
            return self.camera.open(spec)
        report["mode"] = "NATIVE_CROP"
        self._capture_report = report
        self._native = native
        return mode

    def _probe_native(self, native: NativeCapture, mode: NegotiatedMode) -> dict[str, Any]:
        """Read ``probe_frames`` frames: every one must have the expected size, at a unique rate
        of at least ``min_fps`` when the exposure is MANUAL (under AUTO the rate follows the light
        in every mode, so it cannot tell modes apart). Driver properties alone prove nothing."""
        ew, eh = native.expect_px
        if (mode.width, mode.height) != (ew, eh):
            raise NativeModeRejected(f"driver reports {mode.width}x{mode.height}, expected {ew}x{eh}")
        shapes: set[tuple[int, int]] = set()
        unique_t: list[float] = []
        prev: np.ndarray | None = None
        read = 0
        for _ in range(native.probe_frames):
            raw = self.camera.read()
            if raw is None:
                continue
            read += 1
            shapes.add((raw.image.shape[1], raw.image.shape[0]))
            if prev is None or not _same_image(raw.image, prev):
                unique_t.append(raw.t_grab_return)
            prev = raw.image
        fps = (len(unique_t) - 1) / (unique_t[-1] - unique_t[0]) \
            if len(unique_t) > 1 and unique_t[-1] > unique_t[0] else None
        manual = self.settings.spec.exposure_mode.upper() == "MANUAL"
        probe = {"frames_read": read, "unique_frames": len(unique_t), "unique_fps": fps,
                 "delivered_px": sorted([list(s) for s in shapes]),
                 "rate_checked": bool(native.min_fps) and manual}
        if read < 2 or shapes != {(ew, eh)}:
            raise NativeModeRejected(f"delivered frames {probe['delivered_px']} (read {read}), "
                                     f"expected {ew}x{eh}", probe)
        if probe["rate_checked"] and (fps is None or fps < native.min_fps):
            raise NativeModeRejected(f"unique-frame rate {fps} below min_fps {native.min_fps}", probe)
        return probe

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
                if s.exposure_guard is not None:
                    watch = ExposureWatch(s.exposure_guard, s.spec.exposure_mode, s.spec.exposure_value,
                                          raw.t_grab_return)
                    with self._lock:
                        self._watch = watch
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
            image, preview = raw.image, None
            if self._native is not None:
                t0 = timing.now()
                preview = crop_view(raw.image, self._native.crop_px)
                image = tracking_frame(raw.image, self._native.crop_px, self._frame_size)
                with self._lock:
                    self._convert_s.append(timing.now() - t0)
            t_avail = timing.now()
            clamped = 0
            if t_cap > t_avail:
                t_cap = t_avail
                clamped = 1
            if last_t_capture is not None and t_cap <= last_t_capture:
                with self._lock:  # Phase 17: refused (never delivered with an equal / earlier stamp)
                    self._clamped += 1
                    self._refused += 1
                continue
            last_t_capture = t_cap
            with self._lock:
                self._clamped += clamped
                if src is TimestampSource.DRIVER_MAPPED:
                    self._driver_mapped += 1
                else:
                    self._grab_return += 1
            self._queue.put(_Pending(image, t_cap, t_avail, src, preview))
            watch = self._watch
            if watch is not None:  # after the hand-over: an exposure call costs tens of ms
                action = watch.observe(raw.t_grab_return, float(raw.image[::16, ::16].mean()))
                if action is not None:
                    self.exposure_report = self.camera.apply_exposure(*action)

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
        if self._queue.last_depth_at_get is not None:
            self._depth_at_get[self._queue.last_depth_at_get] += 1
        assert self._frame_size is not None and self._roi is not None
        frame_id = self._next_frame_id
        self._next_frame_id += 1
        self._recent_t_capture.append(pending.t_capture)
        self._preview = (frame_id, pending.preview)
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

    def preview_image(self, sample: FrameSample) -> np.ndarray | None:
        """Native-resolution image of ``sample``'s field of view, for display only.

        ``None`` in the standard mode, after a fallback, or when ``sample`` is not the latest
        delivered frame. It shares memory with the capture buffer: copy before drawing on it, and
        never pass it to perception, calibration or a recorder (those use ``view(sample)``).
        """
        got = self._preview
        return got[1] if got is not None and got[0] == sample.frame_id else None

    def capture_report(self) -> dict[str, Any]:
        """Which capture mode is running and why, the native-open probe, the device controls and
        the per-frame crop/downscale cost (call from the consumer thread or after stop)."""
        with self._lock:
            conv = sorted(self._convert_s)
        rep = dict(self._capture_report)
        with self._lock:
            watch = self._watch
        rep["exposure"] = {"requested": {"mode": self.settings.spec.exposure_mode,
                                         "value": self.settings.spec.exposure_value},
                           "last_apply": self.exposure_report,
                           "guard": watch.report() if watch is not None else None}
        rep["conversion_ms"] = {
            "frames": len(conv),
            "p50": 1000 * conv[len(conv) // 2],
            "p95": 1000 * conv[min(len(conv) - 1, int(0.95 * len(conv)))],
            "max": 1000 * conv[-1],
        } if conv else None
        return rep

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

    def queue_report(self) -> dict[str, Any]:
        """Queue depth the consumer saw at each delivery (call from the consumer thread or after stop).

        Depth 1: the delivered frame was the newest one available. Depth >= 2: a newer frame was
        already waiting, so an older frame was processed (a *late* delivery; it is not a drop).
        """
        depths = dict(sorted(self._depth_at_get.items()))
        return {
            "max_frames": self._queue.max_frames,
            "delivered": sum(depths.values()),
            "depth_at_get": {str(k): v for k, v in depths.items()},
            "late_deliveries": sum(v for k, v in depths.items() if k >= 2),
        }

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
                "refused_non_monotone": self._refused,
                "capture_thread_cpu_s": self._thread_cpu_s,
                "capture_thread_wall_s": self._thread_wall_s,
                "capture_thread_cpu_fraction": (self._thread_cpu_s / self._thread_wall_s)
                if self._thread_wall_s > 0 else None,
            }
        rep["driver_mapper"] = self._mapper.residual_stats()
        rep["driver_timestamps_seen"] = self._mapper.n_pairs > 0
        return rep


__all__ = ["CaptureSettings", "LiveFrameSource"]
