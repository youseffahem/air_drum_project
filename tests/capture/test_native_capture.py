"""Native capture with an unchanged tracking frame (ADR-0047), device controls. SYNTHETIC: no webcam opens.

The fake camera delivers a size that depends on the request, like HW-01's DSHOW driver (a 1920x1080
request -> 1280x720, anything else -> 640x480), so the verified open and the fallback are exercised
without hardware. The live counterpart is ``scripts/camera_modes.py``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from spacedrums.capture import (
    CaptureSettings,
    LiveFrameSource,
    NativeCapture,
    NativeModeRejected,
    Roi,
    SyntheticCamera,
    tracking_frame,
)
from spacedrums.capture.backend import CameraOpenSpec, OpenCvCamera
from spacedrums.config import load_yaml
from spacedrums.contracts import TimestampSource

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = ROOT / "configs" / "camera" / "hw01-native-720p.candidate.yaml"
NATIVE = NativeCapture(request_px=(1920, 1080), expect_px=(1280, 720), crop_px=(159, 0, 960, 720),
                       min_fps=25.0, probe_frames=8)


def structured(w, h, stamp):
    """Column index in B, row index in G, a per-frame stamp in R (so real frames always differ)."""
    img = np.empty((h, w, 3), np.uint8)
    img[..., 0] = (np.arange(w) % 251)[None, :]
    img[..., 1] = (np.arange(h) % 251)[:, None]
    img[..., 2] = stamp
    return img


class ModeCamera(SyntheticCamera):
    """Delivers ``modes[requested size]`` (w, h, fps); other requests get 640x480 at 30."""

    def __init__(self, modes=None, **kw):
        kw.setdefault("paced", False)
        super().__init__(**kw)
        self.modes = {(1920, 1080): (1280, 720, 30.0)} if modes is None else modes
        self.opened: list[CameraOpenSpec] = []
        self.closed = 0

    def open(self, spec):
        self.opened.append(spec)
        self.width, self.height, self.fps = self.modes.get((spec.width, spec.height), (640, 480, 30.0))
        return super().open(spec)

    def read(self):
        raw = super().read()
        if raw is None:
            return None
        return replace(raw, image=structured(self.width, self.height, int(raw.image[0, 0, 0])))

    def close(self):
        self.closed += 1
        super().close()


def settings(native=NATIVE, exposure="MANUAL", **kw):
    base = dict(camera_profile_id="synthetic-native", roi=Roi(40, 20, 560, 440),
                spec=CameraOpenSpec(width=640, height=480, fps=30.0, exposure_mode=exposure,
                                    exposure_value=-6.0 if exposure == "MANUAL" else None),
                timestamp_source=TimestampSource.GRAB_RETURN, nominal_fps=30.0, queue_max_frames=64,
                warmup_frames=2, native=native)
    base.update(kw)
    return CaptureSettings(**base)


def run(camera, s):
    src = LiveFrameSource(camera, s)
    with src:
        frames = []
        for sample in src:
            frames.append((sample, src.view(sample).full.copy(), src.preview_image(sample)))
    return src, frames


# ----------------------------------------------------------------------------- pure mapping


def test_tracking_frame_reproduces_the_640x480_window_geometry():
    native = np.zeros((720, 1280, 3), np.uint8)
    native[:, 159 + 300:159 + 303] = 255  # a 3 px native stripe = tracking columns 200 and 201
    native[450:453, :] = 255  # a 3 px native row band = tracking rows 300 and 301
    out = tracking_frame(native, (159, 0, 960, 720), (640, 480))
    assert out.shape == (480, 640, 3) and out.flags["C_CONTIGUOUS"]
    cols = np.flatnonzero(out[10, :, 0] > 100)
    rows = np.flatnonzero(out[:, 10, 0] > 100)
    assert cols.tolist() == [200, 201] and rows.tolist() == [300, 301]
    assert out[10, 199, 0] < 100 and out[10, 202, 0] < 100


def test_area_downscale_averages_noise_and_keeps_brightness():
    rng = np.random.default_rng(0)
    native = np.clip(rng.normal(100, 8, (720, 1280, 3)), 0, 255).astype(np.uint8)
    out = tracking_frame(native, (159, 0, 960, 720), (640, 480))
    assert abs(float(out.mean()) - float(native[:, 159:1119].mean())) < 0.5
    assert out.std() < 0.8 * native.std()  # 1.5x area averaging, never sharpening or upscaling noise


def test_a_crop_of_the_tracking_size_is_an_independent_copy():
    native = structured(1280, 720, 7)
    out = tracking_frame(native, (100, 50, 640, 480), (640, 480))
    assert np.array_equal(out, native[50:530, 100:740])
    out[:] = 0
    assert native[50, 100, 0] == 100 % 251  # the capture buffer is untouched


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (dict(crop_px=(0, 0, 600, 450)), "upscaling is refused"),
        (dict(crop_px=(0, 0, 1280, 720)), "aspect ratio"),
        (dict(crop_px=(400, 0, 960, 720)), "does not fit"),
        (dict(fallback="IGNORE"), "fallback"),
        (dict(probe_frames=1), "probe_frames"),
    ],
)
def test_windows_that_cannot_reproduce_the_tracking_frame_are_refused(change, message):
    with pytest.raises(ValueError, match=message):
        replace(NATIVE, **change).check((640, 480))
    with pytest.raises(ValueError, match="upscaling"):
        tracking_frame(np.zeros((480, 640, 3), np.uint8), (0, 0, 320, 240), (640, 480))


def test_the_shipped_fragment_is_the_measured_centre_window():
    block = load_yaml(FRAGMENT)["camera_profile"]["native_capture"]
    native = NativeCapture.from_config(block)
    native.check((640, 480))
    x, y, w, h = native.crop_px
    assert (w, h) == (960, 720) and y == 0
    assert abs(x - (1280 - 960) / 2) <= 1.5  # registration put the 640x480 window 158.8-159.0 px in
    assert native.request_px == (1920, 1080) and native.expect_px == (1280, 720)
    assert native.fallback == "STANDARD"


def test_settings_from_config_read_native_capture_and_controls():
    cfg = {"camera_profile": {
        "profile_id": "p", "device": {"index": 0, "name": None, "backend": "DSHOW"},
        "resolution_px": [640, 480], "requested_fps": 30, "pixel_format": None,
        "exposure": {"mode": "MANUAL", "value": -5}, "timestamp_source": "GRAB_RETURN",
        "grab_return_bias_s": None, "native_fps_measured": None,
        "queue": {"max_frames": 1, "drop_policy": "DROP_OLDEST", "stall_factor": 2.0},
        "native_capture": load_yaml(FRAGMENT)["camera_profile"]["native_capture"],
        "controls": {"GAIN": 4}}}
    s = CaptureSettings.from_config(cfg)
    assert s.native is not None and s.native.crop_px == (159, 0, 960, 720)
    assert s.spec.controls == (("GAIN", 4.0),)
    del cfg["camera_profile"]["native_capture"], cfg["camera_profile"]["controls"]
    plain = CaptureSettings.from_config(cfg)
    assert plain.native is None and plain.spec.controls == ()


# ----------------------------------------------------------------------------- live source


def test_verified_native_mode_tracks_640x480_and_previews_the_native_window():
    cam = ModeCamera(n_frames=60)
    src, frames = run(cam, settings())
    report = src.capture_report()
    assert report["mode"] == "NATIVE_CROP"
    assert report["probe"]["delivered_px"] == [[1280, 720]] and report["probe"]["rate_checked"]
    assert (cam.opened[0].width, cam.opened[0].height) == (1920, 1080) and len(cam.opened) == 1
    assert report["tracking_px"] == [640, 480] and report["conversion_ms"]["frames"] == len(frames) > 0
    for sample, full, preview in frames:
        assert sample.frame_size_px == (640, 480) and sample.roi_px == (40, 20, 560, 440)
        assert full.shape == (480, 640, 3) and preview.shape == (720, 960, 3)
        assert preview[0, 0, 0] == 159 % 251 and preview[0, 959, 0] == (159 + 959) % 251  # the window
        stamp = preview[0, 0, 2]
        assert np.array_equal(full, tracking_frame(structured(1280, 720, stamp), NATIVE.crop_px, (640, 480)))
    assert all(b.t_capture > a.t_capture for (a, _, _), (b, _, _) in zip(frames, frames[1:], strict=False))
    assert all(s.t_capture <= s.t_frame_available for s, _, _ in frames)


def test_preview_is_only_returned_for_the_latest_delivered_frame():
    cam = ModeCamera(n_frames=40)
    src = LiveFrameSource(cam, settings())
    with src:
        first = src.next_frame(timeout=2.0)
        assert src.preview_image(first) is not None
        second = src.next_frame(timeout=2.0)
        assert src.preview_image(first) is None and src.preview_image(second) is not None


def test_wrong_delivered_size_falls_back_to_the_standard_mode_and_says_why():
    cam = ModeCamera(modes={}, n_frames=60)  # the driver never delivers 1280x720
    src, frames = run(cam, settings())
    report = src.capture_report()
    assert report["mode"] == "STANDARD_FALLBACK" and "expected 1280x720" in report["rejected"]
    assert [(s.width, s.height) for s in cam.opened] == [(1920, 1080), (640, 480)] and cam.closed >= 1
    assert frames and all(f.shape == (480, 640, 3) and p is None for _, f, p in frames)
    assert report["conversion_ms"] is None


def test_a_slow_native_mode_falls_back_under_manual_exposure_only():
    slow = {(1920, 1080): (1280, 720, 10.0)}  # like DSHOW 1280x720 YUY2 over USB 2.0
    cam = ModeCamera(modes=slow, n_frames=30, paced=True)
    src, frames = run(cam, settings())
    report = src.capture_report()
    assert report["mode"] == "STANDARD_FALLBACK" and "below min_fps" in report["rejected"]
    assert report["probe"]["unique_fps"] == pytest.approx(10.0, rel=0.25)
    # Under AUTO exposure the rate follows the light in every mode, so it cannot reject a mode.
    cam = ModeCamera(modes=slow, n_frames=12, paced=True)
    src, _ = run(cam, settings(exposure="AUTO"))
    assert src.capture_report()["mode"] == "NATIVE_CROP"
    assert src.capture_report()["probe"]["rate_checked"] is False


def test_fallback_fail_refuses_to_start():
    cam = ModeCamera(modes={}, n_frames=30)
    src = LiveFrameSource(cam, settings(native=replace(NATIVE, fallback="FAIL")))
    with pytest.raises(NativeModeRejected, match="expected 1280x720"):
        src.start()


def test_duplicates_are_refused_on_the_native_frame():
    cam = ModeCamera(n_frames=80, duplicate_every=4)
    src, frames = run(cam, settings())
    assert src.stats().duplicates > 0
    stamps = [p[0, 0, 2] for _, _, p in frames]
    assert all(a != b for a, b in zip(stamps, stamps[1:], strict=False))


def test_standard_settings_keep_the_previous_behaviour():
    cam = ModeCamera(n_frames=40)
    src, frames = run(cam, settings(native=None))
    assert src.capture_report()["mode"] == "STANDARD"
    assert [(s.width, s.height) for s in cam.opened] == [(640, 480)]
    assert frames and all(p is None and f.shape == (480, 640, 3) for _, f, p in frames)


def test_native_capture_needs_the_tracking_size():
    s = settings(spec=CameraOpenSpec(exposure_mode="MANUAL", exposure_value=-6.0))
    with pytest.raises(ValueError, match="resolution_px"):
        LiveFrameSource(ModeCamera(n_frames=5), s).start()


# ----------------------------------------------------------------------------- device controls


class FakeCap:
    """cv2.VideoCapture stand-in: GAIN accepts 1-8 (HW-01 DSHOW), FOCUS is unsupported (-1)."""

    def __init__(self):
        self.props = {cv2.CAP_PROP_GAIN: 1.0, cv2.CAP_PROP_BRIGHTNESS: 0.0, cv2.CAP_PROP_FOCUS: -1.0,
                      cv2.CAP_PROP_AUTO_EXPOSURE: 0.25}
        self.released = False

    def get(self, prop):
        return self.props.get(prop, -1.0)

    def set(self, prop, value):
        if prop == cv2.CAP_PROP_GAIN and not 1 <= value <= 8:
            return False
        if prop == cv2.CAP_PROP_FOCUS:
            return False
        self.props[prop] = float(value)
        return True

    def release(self):
        self.released = True


def test_controls_are_verified_by_readback_and_restored_on_close():
    cam = OpenCvCamera()
    cap = cam._cap = FakeCap()
    report = cam.apply_controls((("GAIN", 4), ("BRIGHTNESS", 32), ("FOCUS", 10)))
    by = {r["control"]: r for r in report}
    assert by["GAIN"]["verified"] and by["GAIN"]["original"] == 1.0 and by["GAIN"]["readback"] == 4.0
    assert by["BRIGHTNESS"]["verified"]
    assert not by["FOCUS"]["verified"] and not by["FOCUS"]["set_ok"] and by["FOCUS"]["readback"] == -1.0
    clamped = cam.apply_controls((("GAIN", 32),))[0]
    assert clamped["set_ok"] is False and clamped["verified"] is False and clamped["readback"] == 4.0
    cam.close()
    assert cap.released and cap.props[cv2.CAP_PROP_GAIN] == 1.0 and cap.props[cv2.CAP_PROP_BRIGHTNESS] == 0.0


def test_unknown_controls_are_refused():
    cam = OpenCvCamera()
    cam._cap = FakeCap()
    with pytest.raises(ValueError, match="unknown camera control"):
        cam.apply_controls((("EXPOSURE", -5),))  # exposure has its own, backend-aware path
