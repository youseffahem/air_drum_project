"""app.play --camera / --exposure (ADR-0047). SYNTHETIC live camera: no webcam, hand model or speaker opens.

The fake webcam behaves like HW-01's DSHOW driver (a 1920x1080 request -> 1280x720, anything else ->
640x480), so the launcher's live path runs end to end in both camera modes and in the fallback.
"""

import json
from dataclasses import replace

import numpy as np
import pytest

from spacedrums.app import play
from spacedrums.capture import SyntheticCamera
from spacedrums.config import config_hash


def forbidden(*a, **kw):
    pytest.fail("this test must not open the hand model, pose model or speaker")


class FakeWebcam(SyntheticCamera):
    def __init__(self, modes):
        super().__init__(paced=False, n_frames=400)
        self.modes = modes
        self.opened = []

    def open(self, spec):
        self.opened.append((spec.width, spec.height))
        self.width, self.height = self.modes.get((spec.width, spec.height), (640, 480))
        return super().open(spec)

    def read(self):
        raw = super().read()
        if raw is None:
            return None
        h, w = raw.image.shape[:2]
        img = np.empty((h, w, 3), np.uint8)
        img[...] = (np.arange(w) % 200)[None, :, None]
        img[..., 2] = raw.image[0, 0, 0]  # per-frame stamp: no false duplicates
        return replace(raw, image=img)


def launch(monkeypatch, tmp_path, argv, modes):
    cams = []

    def factory():
        cams.append(FakeWebcam(modes))
        return cams[-1]

    monkeypatch.setattr(play, "OpenCvCamera", factory)
    monkeypatch.setattr(play, "BodyLandmarker", forbidden)
    monkeypatch.setattr("spacedrums.hands.HandLandmarker", forbidden)
    monkeypatch.setattr("sounddevice.OutputStream", forbidden)
    shown = []
    monkeypatch.setattr(play.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(play.cv2, "resizeWindow", lambda *a, **k: None)
    monkeypatch.setattr(play.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(play.cv2, "imshow", lambda name, img: shown.append(img.shape))
    monkeypatch.setattr(play.cv2, "pollKey", lambda: -1)
    out = tmp_path / "run"
    argv = [*argv, "--demo", "--red-tips", "--no-audio", "--max-frames", "12", "--output", str(out)]
    code = play.main(argv)
    report = json.loads((out / "report.json").read_text())
    records = [json.loads(line) for line in (out / "observations.jsonl").read_text().splitlines()]
    return code, report, records, shown, cams[0]


HW01 = {(1920, 1080): (1280, 720)}


@pytest.mark.parametrize("kit", ["four", "full"])
def test_native_camera_tracks_640x480_and_shows_the_native_window(monkeypatch, tmp_path, kit):
    code, report, records, shown, cam = launch(monkeypatch, tmp_path, ["--kit", kit], HW01)
    assert code == 0 and report["error"] is None
    mode = report["capture"]["capture_mode"]
    assert mode["mode"] == "NATIVE_CROP" and mode["probe"]["delivered_px"] == [[1280, 720]]
    assert cam.opened == [(1920, 1080)]
    assert {tuple(r["frame"]["frame_size_px"]) for r in records} == {(640, 480)}  # tracking geometry kept
    assert set(shown) == {(720, 960, 3)}  # native 960x720 in both the stage and the diagnostic view
    assert report["config"]["camera_profile"]["native_capture"]["crop_px"] == [159, 0, 960, 720]


def test_standard_camera_is_the_previous_capture(monkeypatch, tmp_path):
    argv = ["--kit", "four", "--camera", "standard"]
    code, report, records, shown, cam = launch(monkeypatch, tmp_path, argv, HW01)
    assert code == 0 and report["capture"]["capture_mode"]["mode"] == "STANDARD"
    assert cam.opened == [(640, 480)] and set(shown) == {(480, 640, 3)}
    assert "native_capture" not in report["config"]["camera_profile"]


def test_undelivered_native_mode_falls_back_and_still_plays(monkeypatch, tmp_path, capsys):
    code, report, records, shown, cam = launch(monkeypatch, tmp_path, ["--kit", "four"], {})
    mode = report["capture"]["capture_mode"]
    assert code == 0 and mode["mode"] == "STANDARD_FALLBACK" and "expected 1280x720" in mode["rejected"]
    assert cam.opened == [(1920, 1080), (640, 480)]
    assert len(records) == 12 and set(shown) == {(480, 640, 3)}
    assert "native mode not delivered" in capsys.readouterr().out


def test_standard_config_is_byte_identical_and_native_adds_only_its_block():
    for kw in ({}, {"demo": True, "kit": "full"}, {"demo": True, "red_tips": True}):
        standard = play.play_config(**kw)
        assert config_hash(standard) == config_hash(play.play_config(camera="standard", **kw))
        native = play.play_config(camera="native", **kw)
        block = native["camera_profile"].pop("native_capture")
        assert block["expect_px"] == [1280, 720]
        guard = native["camera_profile"]["exposure"].pop("guard")
        assert guard["fallback_value"] == -5 and guard["min_fps"] == 24
        assert native == standard  # nothing else changes: ROI, exposure value, zones, thresholds
    with pytest.raises(ValueError, match="camera"):
        play.play_config(camera="hd")


def test_exposure_override_is_validated_and_applied():
    assert play.exposure_override("auto") == {"mode": "AUTO", "value": None}
    assert play.exposure_override("-5") == {"mode": "MANUAL", "value": -5.0}
    cfg = play.play_config(camera="native", exposure=play.exposure_override("AUTO"))
    exposure = cfg["camera_profile"]["exposure"]
    assert (exposure["mode"], exposure["value"]) == ("AUTO", None)
    assert cfg["camera_profile"]["exposure"]["guard"]["fallback_value"] == -5  # the override keeps the guard
    assert "guard" not in play.play_config(camera="standard", exposure=play.exposure_override("auto"))[
        "camera_profile"]["exposure"]
    assert play.play_config()["camera_profile"]["exposure"] == {"mode": "MANUAL", "value": -6}
    assert play.play_config(demo=True)["camera_profile"]["exposure"] == {"mode": "MANUAL", "value": -5}
    with pytest.raises(SystemExit):
        play.main(["--exposure", "bright", "--check"])
    with pytest.raises(SystemExit):
        play.main(["--camera", "hd", "--check"])


def test_preview_presets_reach_the_window_but_never_the_recorded_tracking_frames(monkeypatch, tmp_path):
    import cv2

    from spacedrums.capture import tracking_frame

    argv = ["--kit", "four", "--record-frames"]
    code, report, records, shown, _ = launch(monkeypatch, tmp_path, argv, HW01)
    assert code == 0 and report["config"]["product"]["preview"]["tone"] == "AUTO"
    assert report["preview"]["settings"]["dim"] == 1.0 and "gamma" in report["preview"]
    assert report["tracking_tone"] is None
    saved = cv2.imread(str(tmp_path / "run" / "frames" / "frame_000005.png"))
    native = np.empty((720, 1280, 3), np.uint8)
    native[...] = (np.arange(1280) % 200)[None, :, None]
    expected = tracking_frame(native, (159, 0, 960, 720), (640, 480))
    assert np.array_equal(saved[..., 0], expected[..., 0])  # raw tracking pixels, no preview tone


@pytest.mark.parametrize(("preset", "dim", "tone"), [("raw", 1.0, "OFF"), ("legacy", None, "OFF")])
def test_preview_presets_are_recorded_in_the_config(monkeypatch, tmp_path, preset, dim, tone):
    code, report, _, _, _ = launch(monkeypatch, tmp_path, ["--kit", "full", "--preview", preset], HW01)
    assert code == 0 and report["config"]["product"]["preview"]["dim"] == dim
    assert report["config"]["product"]["preview"]["tone"] == tone


def test_tracking_tone_is_opt_in_and_refused_for_red_tips():
    from types import SimpleNamespace

    from spacedrums.ui.preview_tone import PreviewSettings, PreviewTone

    with pytest.raises(SystemExit):
        play.main(["--red-tips", "--tracking-tone", "auto", "--check"])
    full = np.full((480, 640, 3), 40, np.uint8)
    sample = SimpleNamespace(roi_px=(40, 20, 560, 440))
    view = SimpleNamespace(sample=sample, full=full, roi=full[20:460, 40:600])
    assert play.toned_view(view, PreviewTone(PreviewSettings(tone="OFF"))) is view
    toned = play.toned_view(view, PreviewTone(PreviewSettings(smoothing=1.0)))
    assert toned.full.mean() > 60 and full.mean() == 40  # brightened copy; the raw frame is untouched
    assert toned.roi.shape == (440, 560, 3) and np.shares_memory(toned.roi, toned.full)
