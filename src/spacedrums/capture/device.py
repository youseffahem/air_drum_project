"""Device enumeration and mode probing through the capture backend (Task 02.1).

OpenCV cannot list a camera's advertised modes; the honest equivalent is to *request* a set of
candidate modes and record what the backend negotiates, plus a short unique-frame count so a
mode that is negotiated but not delivered (e.g. 720p YUY2 over USB 2.0, 60 FPS requests) is
visible. Everything returned here is labelled *inspected / advertised by the driver*: the
delivered rate is measured by ``scripts/measure_fps.py`` (Task 02.4), never here.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import numpy as np

from spacedrums import timing
from spacedrums.capture.backend import CameraOpenSpec, OpenCvCamera

DEFAULT_BACKENDS = ("MSMF", "DSHOW")
DEFAULT_MODES: tuple[tuple[int, int, float], ...] = (
    (640, 480, 30), (640, 480, 60), (848, 480, 30), (960, 540, 30),
    (1280, 720, 30), (1280, 720, 60), (1920, 1080, 30), (1920, 1080, 60),
)


def list_pnp_cameras() -> list[dict[str, Any]]:
    """Camera devices known to the OS (Windows PnP); names only, informational."""
    if not sys.platform.startswith("win"):
        return []
    cmd = (
        "Get-PnpDevice -Class Camera,Image -Status OK | "
        "ForEach-Object { $_.FriendlyName + '|' + $_.InstanceId }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        if "|" in line:
            name, inst = line.strip().split("|", 1)
            rows.append({"name": name, "instance_id": inst})
    return rows


def available_backends() -> list[str]:
    import cv2.videoio_registry as reg

    return [reg.getBackendName(b) for b in reg.getCameraBackends()]


def enumerate_devices(max_index: int = 4, backends: tuple[str, ...] = DEFAULT_BACKENDS) -> list[dict]:
    """Try to open indices 0..max_index on each backend; record the default negotiated mode."""
    rows = []
    for backend in backends:
        for idx in range(max_index + 1):
            cam = OpenCvCamera()
            t0 = timing.now()
            row: dict[str, Any] = {"backend": backend, "index": idx}
            try:
                mode = cam.open(CameraOpenSpec(index=idx, backend=backend))
                row.update({"opened": True, "default_mode": mode.to_dict()})
            except Exception as exc:  # noqa: BLE001 - enumeration records failures
                row.update({"opened": False, "error": str(exc)})
            finally:
                cam.close()
            row["open_time_s"] = timing.now() - t0
            rows.append(row)
    return rows


def probe_mode(
    index: int,
    backend: str,
    width: int,
    height: int,
    fps: float,
    *,
    pixel_format: str | None = None,
    exposure_mode: str = "AUTO",
    exposure_value: float | None = None,
    n_frames: int = 45,
) -> dict[str, Any]:
    """Request one mode; report the negotiated mode and a short unique-frame rate."""
    cam = OpenCvCamera()
    req = {"width": width, "height": height, "fps": fps, "pixel_format": pixel_format,
           "exposure_mode": exposure_mode, "exposure_value": exposure_value}
    row: dict[str, Any] = {"backend": backend, "index": index, "requested": req}
    try:
        cam.open(CameraOpenSpec(index=index, backend=backend, width=width, height=height,
                                       fps=fps, pixel_format=pixel_format,
                                       exposure_mode=exposure_mode, exposure_value=exposure_value))
        for _ in range(8):
            cam.read()
        cam.apply_exposure(exposure_mode, exposure_value)  # MSMF applies only once streaming
        for _ in range(5):
            cam.read()
        prev = None
        unique = 0
        lum = []
        t0 = timing.now()
        for _ in range(n_frames):
            raw = cam.read()
            if raw is None:
                break
            if prev is None or not np.array_equal(prev, raw.image):
                unique += 1
            prev = raw.image
            lum.append(float(raw.image.mean()))
        dur = timing.now() - t0
        row.update({
            "negotiated": cam.negotiated().to_dict(),
            "short_probe": {
                "frames_read": len(lum), "unique_frames": unique, "duration_s": dur,
                "unique_fps_short": (unique / dur) if dur > 0 else None,
                "mean_luminance": float(np.mean(lum)) if lum else None,
                "note": "short probe (<2 s); not a measurement of delivered FPS (Task 02.4 is)",
            },
        })
    except Exception as exc:  # noqa: BLE001
        row["error"] = str(exc)
    finally:
        cam.close()
    return row


__all__ = ["DEFAULT_BACKENDS", "DEFAULT_MODES", "available_backends", "enumerate_devices",
           "list_pnp_cameras", "probe_mode"]
