"""Camera backends: the OpenCV device wrapper and a synthetic camera for tests (Task 02.1).

A backend does exactly three things: open a requested mode and report what was negotiated,
block until the next frame and hand it over with the grab-return ``t_mono`` stamp (and the driver
timestamp if the backend exposes one), and expose/set the exposure controls. It knows nothing
about ROIs, queues, hands or zones.

OpenCV specifics learned on HW-01 (docs/camera-profile-hw01-integrated-webcam.md):

* ``MSMF`` exposes ``CAP_PROP_POS_MSEC`` as a per-frame driver timestamp on the QPC base;
  ``DSHOW`` returns -1 (no driver timestamp).
* ``MSMF`` only honours exposure settings applied *after* the stream has started, so
  ``apply_exposure`` is called again after the warm-up frames.
* Where the blocking wait for the next frame happens differs: on ``MSMF`` ``grab()`` blocks and
  ``retrieve()`` is a fast conversion; on ``DSHOW`` ``grab()`` returns at once and ``retrieve()``
  blocks. Stamping after ``grab()`` on DSHOW would therefore be a full frame period *early*.
  ``open()`` probes both durations and fixes ``stamp_after`` (``GRAB`` | ``RETRIEVE``) for the
  session; the decision is part of ``NegotiatedMode`` and of the camera profile.
* Exposure values are backend-specific: on both Windows backends the value is the DirectShow
  log2 scale (``-6`` = 2**-6 s = 15.6 ms); ``AUTO_EXPOSURE`` = 0.75 (auto) / 0.25 (manual) on
  DSHOW and 1 / 0 on MSMF (OpenCV convention). Read-back is unreliable on MSMF.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import numpy as np

from spacedrums import timing

# Backend name -> cv2 API preference constant (resolved lazily so tests need no camera).
_BACKEND_CONSTANTS = {"ANY": "CAP_ANY", "MSMF": "CAP_MSMF", "DSHOW": "CAP_DSHOW",
                      "V4L2": "CAP_V4L2", "AVFOUNDATION": "CAP_AVFOUNDATION", "FFMPEG": "CAP_FFMPEG"}


@dataclass(frozen=True)
class CameraOpenSpec:
    """What we *request* (``camera_profile`` block of the config)."""

    index: int = 0
    backend: str | None = None  # None = library default ("ANY")
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    pixel_format: str | None = None  # FOURCC
    exposure_mode: str = "AUTO"  # AUTO | MANUAL
    exposure_value: float | None = None


@dataclass(frozen=True)
class NegotiatedMode:
    """What the backend *reports* after opening. Advertised by the driver, not measured."""

    backend: str
    index: int
    width: int
    height: int
    fps_prop: float | None  # the driver's claimed frame rate; never a delivered FPS
    fourcc: str | None
    fourcc_raw: int | None
    auto_exposure_prop: float | None
    exposure_prop: float | None
    has_driver_timestamps: bool
    buffersize_prop: float | None
    stamp_after: str = "GRAB"  # GRAB | RETRIEVE: where the blocking wait was found to happen
    grab_probe: dict[str, float] | None = None  # median grab / retrieve durations of the probe

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RawFrame:
    """One frame straight from the backend, stamped at grab return."""

    image: np.ndarray  # (h, w, 3) uint8 BGR
    t_grab_return: float  # t_mono immediately after the blocking grab returned
    t_driver_s: float | None  # backend timestamp in seconds on the driver clock, if any


class CameraBackend(Protocol):
    def open(self, spec: CameraOpenSpec) -> NegotiatedMode: ...
    def read(self) -> RawFrame | None: ...
    def apply_exposure(self, mode: str, value: float | None) -> dict[str, Any]: ...
    def close(self) -> None: ...


# ----------------------------------------------------------------------------- OpenCV backend


def _fourcc_to_str(v: float | int | None) -> str | None:
    if v is None:
        return None
    iv = int(v)
    if iv <= 0:
        return None
    chars = [chr((iv >> (8 * i)) & 0xFF) for i in range(4)]
    if all(32 <= ord(c) < 127 for c in chars):
        return "".join(chars)
    return f"0x{iv & 0xFFFFFFFF:08x}"


def backend_constant(name: str | None) -> int:
    import cv2

    key = (name or "ANY").upper()
    if key not in _BACKEND_CONSTANTS:
        raise ValueError(f"unknown capture backend {name!r}; known: {sorted(_BACKEND_CONSTANTS)}")
    return int(getattr(cv2, _BACKEND_CONSTANTS[key]))


def auto_exposure_values(backend: str) -> tuple[float, float]:
    """``(auto, manual)`` values for ``CAP_PROP_AUTO_EXPOSURE`` on the given backend."""
    return (0.75, 0.25) if backend.upper() == "DSHOW" else (1.0, 0.0)


class OpenCvCamera:
    """``cv2.VideoCapture`` wrapper. Stamps ``t_grab_return`` right after ``grab()`` returns."""

    def __init__(self, *, blocking_probe_frames: int = 30) -> None:
        self._cap = None
        self._backend_name = "ANY"
        self._index = 0
        self._pos_msec_available = False
        self._restore_auto: float | None = None
        self._stamp_after_retrieve = False
        self._grab_probe: dict[str, float] | None = None
        self._blocking_probe_frames = blocking_probe_frames

    def open(self, spec: CameraOpenSpec) -> NegotiatedMode:
        import cv2

        self._backend_name = (spec.backend or "ANY").upper()
        self._index = spec.index
        cap = cv2.VideoCapture(spec.index, backend_constant(spec.backend))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open camera index {spec.index} on backend {self._backend_name}")
        if spec.pixel_format:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*spec.pixel_format))
        if spec.width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, spec.width)
        if spec.height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, spec.height)
        if spec.fps:
            cap.set(cv2.CAP_PROP_FPS, spec.fps)
        self._cap = cap
        # MSMF honours exposure only once streaming; warm up, then apply (again after warm-up
        # in LiveFrameSource).
        ok, _ = cap.read()
        if not ok:
            raise RuntimeError("camera opened but delivered no frame")
        self.apply_exposure(spec.exposure_mode, spec.exposure_value)
        pos = cap.get(cv2.CAP_PROP_POS_MSEC)
        self._pos_msec_available = pos is not None and pos > 0
        self._probe_blocking()
        return self.negotiated()

    def _probe_blocking(self) -> None:
        """Find out whether grab() or retrieve() waits for the frame (see module docstring)."""
        cap = self._cap
        assert cap is not None
        grab_d: list[float] = []
        retr_d: list[float] = []
        for _ in range(self._blocking_probe_frames):
            t0 = timing.now()
            cap.grab()
            t1 = timing.now()
            cap.retrieve()
            t2 = timing.now()
            grab_d.append(t1 - t0)
            retr_d.append(t2 - t1)
        g = float(np.median(grab_d))
        g_hi = float(np.percentile(grab_d, 75))  # bursts (MSMF) make single grabs instant
        r = float(np.median(retr_d))
        # grab "returns at once" only if even its upper quartile is instant and the wait is
        # visibly inside retrieve(); on a bursty backend the upper quartile of grab is a frame
        # period or more, so the stamp stays after grab()
        self._stamp_after_retrieve = g_hi < 0.002 and r > 5 * max(g, 1e-6)
        self._grab_probe = {"grab_median_s": g, "grab_p75_s": g_hi, "retrieve_median_s": r}

    def negotiated(self) -> NegotiatedMode:
        import cv2

        cap = self._cap
        assert cap is not None
        fcc_raw = cap.get(cv2.CAP_PROP_FOURCC)
        fps = cap.get(cv2.CAP_PROP_FPS)
        return NegotiatedMode(
            backend=cap.getBackendName() if hasattr(cap, "getBackendName") else self._backend_name,
            index=self._index,
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps_prop=None if fps is None or fps <= 0 else float(fps),
            fourcc=_fourcc_to_str(fcc_raw),
            fourcc_raw=None if fcc_raw is None else int(fcc_raw),
            auto_exposure_prop=float(cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)),
            exposure_prop=float(cap.get(cv2.CAP_PROP_EXPOSURE)),
            has_driver_timestamps=self._pos_msec_available,
            buffersize_prop=float(cap.get(cv2.CAP_PROP_BUFFERSIZE)),
            stamp_after="RETRIEVE" if self._stamp_after_retrieve else "GRAB",
            grab_probe=self._grab_probe,
        )

    def apply_exposure(self, mode: str, value: float | None) -> dict[str, Any]:
        import cv2

        cap = self._cap
        assert cap is not None
        auto_v, manual_v = auto_exposure_values(self._backend_name)
        if self._restore_auto is None:
            self._restore_auto = auto_v
        mode = mode.upper()
        result: dict[str, Any] = {"mode": mode, "requested_value": value}
        if mode == "AUTO":
            result["set_auto_ok"] = bool(cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, auto_v))
        elif mode == "MANUAL":
            if value is None:
                raise ValueError("MANUAL exposure needs a value")
            result["set_auto_ok"] = bool(cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, manual_v))
            result["set_value_ok"] = bool(cap.set(cv2.CAP_PROP_EXPOSURE, float(value)))
        else:
            raise ValueError(f"unknown exposure mode {mode!r}")
        result["readback_auto"] = float(cap.get(cv2.CAP_PROP_AUTO_EXPOSURE))
        result["readback_value"] = float(cap.get(cv2.CAP_PROP_EXPOSURE))
        return result

    def read(self) -> RawFrame | None:
        import cv2

        cap = self._cap
        if cap is None:
            return None
        ok = cap.grab()
        t_grab = timing.now()
        if not ok:
            return None
        t_drv: float | None = None
        if self._pos_msec_available:
            pos = cap.get(cv2.CAP_PROP_POS_MSEC)
            if pos is not None and pos > 0 and math.isfinite(pos):
                t_drv = float(pos) / 1000.0
        ok, img = cap.retrieve()
        if self._stamp_after_retrieve:
            t_grab = timing.now()  # the wait happened inside retrieve() on this backend
        if not ok or img is None:
            return None
        return RawFrame(image=img, t_grab_return=t_grab, t_driver_s=t_drv)

    def get_prop(self, prop_name: str) -> float | None:
        import cv2

        if self._cap is None:
            return None
        return float(self._cap.get(getattr(cv2, prop_name)))

    def close(self) -> None:
        import cv2

        if self._cap is not None:
            if self._restore_auto is not None:
                # leave the device in auto exposure for other applications
                self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, self._restore_auto)
            self._cap.release()
            self._cap = None


# ----------------------------------------------------------------------------- synthetic backend


class SyntheticCamera:
    """Deterministic fake camera for unit/integration tests (never used for measurements).

    Produces frames at ``fps`` (paced with the real clock unless ``paced=False``, in which case
    they come as fast as the consumer pulls them), optionally repeating every
    ``duplicate_every``-th frame byte-for-byte (to mimic the MSMF low-light padding), with a
    driver timestamp on a foreign clock ``t_drv = drv_offset + drv_slope * (t_grab - lag_s)``
    (the driver "knows" the frame was captured ``lag_s`` before the grab returned) or none at all.
    ``t_grab_return`` is always the real ``timing.now()`` so the source's invariants hold.
    """

    def __init__(
        self,
        *,
        width: int = 64,
        height: int = 48,
        fps: float = 100.0,
        n_frames: int | None = None,
        paced: bool = True,
        duplicate_every: int | None = None,
        driver_timestamps: bool = True,
        drv_offset: float = 0.0,
        drv_slope: float = 1.0,
        jitter_s: float = 0.0,
        lag_s: float = 0.0,
        seed: int = 0,
    ) -> None:
        self.width, self.height, self.fps = width, height, fps
        self.n_frames = n_frames
        self.paced = paced
        self.duplicate_every = duplicate_every
        self.driver_timestamps = driver_timestamps
        self.drv_offset, self.drv_slope = drv_offset, drv_slope
        self.jitter_s = jitter_s
        self.lag_s = lag_s
        self._rng = np.random.default_rng(seed)
        self._i = 0
        self._t0: float | None = None
        self._last_image: np.ndarray | None = None
        self.exposure_calls: list[dict[str, Any]] = []
        self._open = False

    def open(self, spec: CameraOpenSpec) -> NegotiatedMode:
        self._open = True
        self._t0 = timing.now()
        self._i = 0
        self.apply_exposure(spec.exposure_mode, spec.exposure_value)
        return NegotiatedMode(
            backend="SYNTHETIC", index=spec.index, width=self.width, height=self.height,
            fps_prop=self.fps, fourcc="SYNT", fourcc_raw=None, auto_exposure_prop=None,
            exposure_prop=None, has_driver_timestamps=self.driver_timestamps, buffersize_prop=None,
        )

    def apply_exposure(self, mode: str, value: float | None) -> dict[str, Any]:
        rec = {"mode": mode, "requested_value": value}
        self.exposure_calls.append(rec)
        return rec

    def read(self) -> RawFrame | None:
        if not self._open or (self.n_frames is not None and self._i >= self.n_frames):
            return None
        assert self._t0 is not None
        t_nominal = self._t0 + self._i / self.fps
        if self.paced:
            while timing.now() < t_nominal:
                timing.sleep_s(0.0005)
        if self.jitter_s:
            timing.sleep_s(float(self._rng.uniform(0, self.jitter_s)))
        t_grab = timing.now()
        if self.duplicate_every and self._i % self.duplicate_every == self.duplicate_every - 1 \
                and self._last_image is not None:
            image = self._last_image.copy()
        else:
            image = np.empty((self.height, self.width, 3), dtype=np.uint8)
            image[:] = (self._i % 251, (self._i * 7) % 251, (self._i * 13) % 251)
            image[0, 0] = (self._i & 0xFF, (self._i >> 8) & 0xFF, (self._i >> 16) & 0xFF)
        self._last_image = image
        t_drv = (self.drv_offset + self.drv_slope * (t_grab - self.lag_s)) \
            if self.driver_timestamps else None
        self._i += 1
        return RawFrame(image=image, t_grab_return=t_grab, t_driver_s=t_drv)

    def close(self) -> None:
        self._open = False


__all__ = [
    "CameraBackend",
    "CameraOpenSpec",
    "NegotiatedMode",
    "OpenCvCamera",
    "RawFrame",
    "SyntheticCamera",
    "auto_exposure_values",
    "backend_constant",
]
