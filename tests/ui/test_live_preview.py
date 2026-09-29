"""Live mirror: only the camera image is mirrored and overlays are drawn afterwards with readable text;
frames, ROI, records and tracking stay in camera coordinates."""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from live_preview_helpers import (
    CONFIG,
    RENDERERS,
    ROI,
    ROOT,
    asymmetric_frame,
    busy_frame,
    glyph_scores,
    render_with_text,
)

from spacedrums.app import main as app_main
from spacedrums.app.synthetic import scenario
from spacedrums.capture import Roi, crop_roi
from spacedrums.capture.stats import CaptureStats
from spacedrums.config import load_config
from spacedrums.contracts import Arm, FrameView, HandId, ImageRef
from spacedrums.geometry import ZoneRegistry
from spacedrums.timing.logger import read_record_stream
from spacedrums.ui import OverlayConfig, OverlayStyle
from spacedrums.ui.preview import mirror_preview

W = 640
# Labels attached to scene objects sit in the mirrored footprint of their camera-space box.
SCENE_LABELS = {"Hi-Hat", "Snare", "Tom 1", "Crash/Ride", "COMMIT", "HI-HAT", "LEFT 0.95", "RIGHT 0.95",
                "GEOM 0.90", "reach envelope"}
TRACKING_STREAMS = ("HandObservation", "StickObservation", "TrackState", "KinematicFeatures")


@pytest.mark.parametrize("roi_only", [False, True])
def test_mirror_preview_is_an_independent_copy_even_for_shared_roi(roi_only):
    frame = asymmetric_frame()
    before = frame.copy()
    roi = Roi(40, 20, 560, 440)
    source = crop_roi(frame, roi) if roi_only else frame
    source.setflags(write=False)
    preview = mirror_preview(source)
    np.testing.assert_array_equal(preview, source[:, ::-1])
    assert preview.flags.c_contiguous
    assert not np.shares_memory(preview, frame)
    if not roi_only:
        np.testing.assert_array_equal(preview[160, 529], (0, 0, 255))
        np.testing.assert_array_equal(preview[290, 129], (255, 0, 0))
    preview[:] = 42
    np.testing.assert_array_equal(frame, before)
    assert roi.as_tuple() == (40, 20, 560, 440)


def test_live_window_mirrors_the_camera_image():
    """Requirement 1: with nothing overlaid, the live window is exactly the mirrored camera image."""
    sample, observations, result = busy_frame()
    frame = asymmetric_frame()
    before = frame.copy()
    registry = ZoneRegistry.from_config(load_config(CONFIG)["zones"])
    style, overlays_off = OverlayStyle(), OverlayConfig.off()
    args = (frame, ROI, registry, result, observations, Arm.A, style, None, None, overlays_off)
    np.testing.assert_array_equal(app_main.render(*args, mirror=True), before[:, ::-1])
    np.testing.assert_array_equal(app_main.render(*args), before)
    np.testing.assert_array_equal(frame, before)


@pytest.mark.parametrize("name", sorted(RENDERERS))
def test_live_overlay_text_is_drawn_after_the_mirror_and_reads_normally(name):
    """Requirement 2: every overlay text in the live window has upright glyphs."""
    make = RENDERERS[name]
    camera, camera_calls = render_with_text(make, mirror=False)
    display, calls = render_with_text(make, mirror=True)
    assert [(c.text, c.y) for c in calls] == [(c.text, c.y) for c in camera_calls] and calls
    for cam, shown in zip(camera_calls, calls, strict=True):
        camera_score = glyph_scores(camera, cam)[0]
        upright, reversed_ = glyph_scores(display, shown)
        # as legible as in the camera layout (occlusion by scene shapes mirrors with the label) ...
        assert upright >= min(camera_score, 0.9) - 0.05, shown.text
        assert reversed_ <= 0.3, shown.text  # ... and never left-right reversed
        width = cv2.getTextSize(cam.text, cam.font, cam.scale, cam.thickness)[0][0]
        if cam.text in SCENE_LABELS:
            assert shown.x == W - cam.x - width, cam.text  # follows its mirrored object
        elif not cam.text.startswith("intensity"):  # HUD keeps its place (the ROI is symmetric)
            assert shown.x == cam.x, cam.text
    # The rejected behaviour, mirroring the finished raster, fails this check: its text reads backwards.
    flipped = camera[:, ::-1].copy()
    assert np.nanmean([glyph_scores(flipped, shown)[0] for shown in calls]) < 0.6


def as_dicts(observations):
    return {hand: tuple(record.to_dict() for record in pair) for hand, pair in observations.items()}


@pytest.fixture
def synthetic_frames():
    cfg = load_config(CONFIG)
    frames = []
    for sample, observations in list(scenario("single", ZoneRegistry.from_config(cfg["zones"])))[:40]:
        frame = asymmetric_frame()
        sample = replace(sample, image_ref=ImageRef.memory(frame))
        view = FrameView(sample, crop_roi(frame, Roi.from_rect(sample.roi_px)), frame)
        frames.append((sample, view, observations))
    return frames


def run_app(monkeypatch, tmp_path, frames, source, *, window=True):
    seen, rendered, displayed = [], [], []

    class Perception:
        last_analyses = {}

        def __init__(self, config):
            pass

        def __call__(self, view):
            seen.append(view)
            return next(obs for sample, v, obs in frames if v is view)

        def close(self):
            pass

    original_render = app_main.render

    def render(*args, **kwargs):
        image = original_render(*args, **kwargs)
        rendered.append((args, kwargs, image.copy()))
        return image

    monkeypatch.setattr(app_main, "Perception", Perception)
    monkeypatch.setattr(app_main, "render", render)
    monkeypatch.setattr(cv2, "imshow", lambda window, image: displayed.append(image.copy()))
    monkeypatch.setattr(cv2, "namedWindow", lambda *args: None)
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)
    monkeypatch.setattr(cv2, "pollKey", lambda: -1)
    monkeypatch.setattr(cv2, "waitKey", lambda delay: -1)  # window teardown only
    args = app_main.build_parser().parse_args([
        "--config", str(CONFIG), "--source", source, "--no-audio", "--record",
        "--output-dir", str(tmp_path), "--log-dir", str(tmp_path / "logs"),
        "--session-id", "synthetic-preview-test", *([] if window else ["--no-window"]),
    ])
    stream = [(sample, view, None) for sample, view, _ in frames]
    app_main.run(args, source_factory=lambda *_: (iter(stream), lambda: None, {"source": source}, None))
    session = tmp_path / "synthetic-preview-test"
    return SimpleNamespace(seen=seen, rendered=rendered, displayed=displayed, session=session)


@pytest.mark.parametrize("source", ["live", "replay", "devcapture"])
def test_app_window_keeps_frames_records_and_tracking_in_camera_coordinates(
    monkeypatch, tmp_path, synthetic_frames, source
):
    """Requirements 1, 3 and 4 end to end: the live display is mirrored; nothing else is."""
    before = [(view.full.copy(), sample.to_dict()) for sample, view, _ in synthetic_frames]
    records = [as_dicts(obs) for _, _, obs in synthetic_frames]
    run = run_app(monkeypatch, tmp_path / "window", synthetic_frames, source)
    assert run.seen == [view for _, view, _ in synthetic_frames]
    assert len(run.displayed) == len(run.rendered) == len(synthetic_frames)
    for (args, kwargs, image), shown, (_, view, obs) in zip(
        run.rendered, run.displayed, synthetic_frames, strict=True
    ):
        assert kwargs["mirror"] is (source == "live")
        assert args[0] is view.full and args[4] is obs  # the renderer reads the original records
        np.testing.assert_array_equal(shown, image)
    for (sample, view, obs), (pixels, metadata), obs_dicts in zip(
        synthetic_frames, before, records, strict=True
    ):
        np.testing.assert_array_equal(view.full, pixels)  # capture memory untouched
        assert sample.to_dict() == metadata and sample.image_ref.array is view.full
        assert as_dicts(obs) == obs_dicts
        saved = cv2.imread(str(run.session / "frames" / f"frame_{sample.frame_id:06d}.png"))
        np.testing.assert_array_equal(saved, pixels)  # recordings keep the camera orientation
    for index, kind in enumerate(("HandObservation", "StickObservation")):
        rows = read_record_stream(run.session / "records" / f"{kind}.jsonl")[1]
        assert rows == [r[hand][index] for r in records for hand in (HandId.LEFT, HandId.RIGHT)]
    if source == "live":  # the mirrored window has no path back into tracking
        headless = run_app(monkeypatch, tmp_path / "headless", synthetic_frames, source, window=False)
        assert headless.displayed == []
        for kind in TRACKING_STREAMS:
            path = f"records/{kind}.jsonl"
            assert read_record_stream(run.session / path)[1] == read_record_stream(headless.session / path)[1]
        assert (run.session / "frames.jsonl").read_bytes() == (headless.session / "frames.jsonl").read_bytes()


@pytest.fixture
def preview_input(monkeypatch):
    cfg = load_config(CONFIG)
    sample, observations = next(iter(scenario("single", ZoneRegistry.from_config(cfg["zones"]))))
    frame = asymmetric_frame()
    sample = replace(sample, image_ref=ImageRef.memory(frame))
    roi = Roi.from_rect(sample.roi_px)
    displayed = []
    monkeypatch.setattr(cv2, "imshow", lambda window, image: displayed.append(image.copy()))
    monkeypatch.setattr(cv2, "namedWindow", lambda *args: None)
    monkeypatch.setattr(cv2, "destroyWindow", lambda *args: None)
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)
    # Loops poll keys without waiting (T2); q only reaches them through pollKey.
    monkeypatch.setattr(cv2, "pollKey", lambda: ord("q"))
    monkeypatch.setattr(cv2, "waitKey", lambda delay: -1)
    return SimpleNamespace(
        sample=sample, observations=observations, frame=frame,
        view=FrameView(sample, crop_roi(frame, roi), frame), roi=roi, displayed=displayed,
    )


def spy(monkeypatch, module, name):
    calls = []
    original = getattr(module, name)

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append((kwargs.get("mirror", False), result.copy()))
        return result

    monkeypatch.setattr(module, name, wrapper)
    return calls


@pytest.mark.parametrize("script", ["exposure_blur_check", "show_guide"])
def test_developer_windows_mirror_display_and_keep_saved_images_original(
    monkeypatch, tmp_path, preview_input, script
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = import_module(script)
    data = preview_input
    before = data.frame.copy()
    mode = SimpleNamespace(backend="SYNTHETIC", width=640, height=480, fourcc="BGR", fps_prop=30)
    mode.to_dict = lambda: {"width": 640, "height": 480}
    stopped = []
    source = SimpleNamespace(
        roi=data.roi, start=lambda: mode, next_frame=lambda **kw: data.sample,
        stop=lambda: stopped.append(True), stats=lambda: CaptureStats(1, 0, 0, 0, 30, None, None),
    )
    monkeypatch.setattr(module, "LiveFrameSource", lambda *args: source)
    monkeypatch.setattr(module, "OpenCvCamera", lambda: None)
    calls = spy(monkeypatch, module, "draw_guide")
    if script == "exposure_blur_check":
        monkeypatch.setattr(module, "DEV_CAPTURES", tmp_path)
        assert module.main(["record", "--name", "synthetic-preview", "--lighting", "SYNTHETIC"]) == 0
        saved = cv2.imread(str(tmp_path / "synthetic-preview" / "frame_00000.png"))
        np.testing.assert_array_equal(saved, before)
        assert [mirror for mirror, _ in calls] == [True]
    else:
        screenshot = tmp_path / "guide.png"
        assert module.main(["--screenshot", str(screenshot)]) == 0
        assert [mirror for mirror, _ in calls] == [True, False]
        # The exported screenshot keeps the camera orientation.
        np.testing.assert_array_equal(cv2.imread(str(screenshot)), calls[1][1])
    assert stopped and len(data.displayed) == 1
    np.testing.assert_array_equal(data.displayed[0], calls[0][1])
    np.testing.assert_array_equal(data.frame, before)


@pytest.mark.parametrize("source", ["live", "replay"])
def test_calibration_window_mirrors_only_live_display(monkeypatch, tmp_path, preview_input, source):
    from spacedrums.app import calibrate
    from spacedrums.calib.steps import StickSample

    data = preview_input
    before = data.frame.copy()
    seen = []

    class Perception:
        def __init__(self, cfg):
            pass

        def __call__(self, view):
            assert view is data.view
            np.testing.assert_array_equal(view.full, before)
            seen.append(view)
            return data.observations

        def stick_samples(self):
            return {hand: StickSample(None, 0.0) for hand in HandId}

        def close(self):
            pass

    monkeypatch.setattr(calibrate, "WizardPerception", Perception)
    monkeypatch.setattr(calibrate, "iter_source", lambda *_: (
        iter([(data.sample, data.view, None)]), lambda: None, {"source": source}, None,
    ))
    calls = spy(monkeypatch, calibrate, "draw_wizard")
    args = calibrate.build_parser().parse_args([
        "--source", source, "--user-tag", "synthetic-preview", "--no-audio",
        "--output", str(tmp_path / "synthetic-preview.calib.yaml"), "--max-frames", "1",
    ])
    calibrate.run(args)
    assert seen and len(calls) == len(data.displayed) == 1
    assert calls[0][0] is (source == "live")
    np.testing.assert_array_equal(data.displayed[0], calls[0][1])
    np.testing.assert_array_equal(data.frame, before)
