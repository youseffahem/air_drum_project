"""Display-only preview brightness (ADR-0048). SYNTHETIC: no camera or window opens."""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from spacedrums.capture import Roi
from spacedrums.contracts import HandId
from spacedrums.ui.kit import render_kit
from spacedrums.ui.preview_tone import PreviewSettings, PreviewTone, gamma_lut, mean_luminance
from spacedrums.ui.stage import StageRenderer


def scene(level):
    rng = np.random.default_rng(1)
    return np.clip(rng.normal(level, 12, (480, 640, 3)), 0, 255).astype(np.uint8)


def test_auto_tone_brightens_a_dark_frame_toward_the_target_without_touching_it():
    dark = scene(40)
    before = dark.copy()
    tone = PreviewTone(PreviewSettings(target_luminance=115, smoothing=1.0))
    out = tone(dark)
    assert np.array_equal(dark, before) and out is not dark  # input untouched
    assert mean_luminance(out) > 80 and tone.gamma == pytest.approx(0.5)  # min_gamma caps the boost
    mid = scene(70)
    out = PreviewTone(PreviewSettings(target_luminance=115, smoothing=1.0))(mid)
    assert 95 < mean_luminance(out) < 125


def test_auto_tone_never_darkens_and_keeps_black_and_white():
    bright = scene(160)
    tone = PreviewTone(PreviewSettings(smoothing=1.0))
    assert tone(bright) is bright and tone.gamma == 1.0
    lut = gamma_lut(0.5)
    assert lut[0] == 0 and lut[255] == 255 and np.all(np.diff(lut.astype(int)) >= 0)


def test_auto_tone_is_smoothed_so_the_preview_does_not_flicker():
    tone = PreviewTone(PreviewSettings(smoothing=0.15))
    tone(scene(40))
    assert 0.85 < tone.gamma < 1.0  # one frame moves only part of the way
    for _ in range(60):
        tone(scene(40))
    assert tone.gamma == pytest.approx(0.5, abs=0.02)
    assert tone.report()["gamma"]["min"] == pytest.approx(tone.gamma, abs=0.01)


def test_off_and_gamma_modes_and_presets():
    img = scene(60)
    assert PreviewTone(PreviewSettings(tone="OFF"))(img) is img
    fixed = PreviewTone(PreviewSettings(tone="GAMMA", gamma=0.7))(img)
    assert np.array_equal(fixed, cv2.LUT(img, gamma_lut(0.7)))
    base = PreviewSettings()
    assert base.preset("natural") == base
    assert base.preset("raw") == PreviewSettings(dim=1.0, vignette=False, tone="OFF")
    legacy = base.preset("legacy")
    assert legacy.dim is None and legacy.vignette and legacy.tone == "OFF"
    with pytest.raises(ValueError):
        base.preset("vivid")
    for bad in ({"tone": "HDR"}, {"dim": 0}, {"dim": 1.5}, {"target_luminance": 300}, {"min_gamma": 0}):
        with pytest.raises(ValueError):
            PreviewSettings(**bad)


ROI = Roi(0, 0, 640, 480)


def stage_bg(renderer, img):
    result = SimpleNamespace(sample=SimpleNamespace(t_capture=1.0), commits=[])
    ev = {h: SimpleNamespace(kind="MISSING", tip=None) for h in HandId}
    return renderer.render(img, ROI, [], ev, result)


def test_stage_without_dim_or_vignette_shows_the_camera_brightness():
    img = np.full((480, 640, 3), 100, np.uint8)
    natural = stage_bg(StageRenderer(dim=1.0, vignette=False), img)
    legacy = stage_bg(StageRenderer(), img)
    centre, corner = (slice(300, 420), slice(400, 560)), (slice(330, 390), slice(4, 30))  # mid-left edge
    assert natural[centre].mean() == pytest.approx(100, abs=1)
    assert natural[corner].mean() == pytest.approx(100, abs=1)
    assert legacy[centre].mean() == pytest.approx(62, abs=3)  # the previous look is still available
    assert legacy[corner].mean() < 50
    vignette_only = stage_bg(StageRenderer(dim=1.0, vignette=True), img)
    assert vignette_only[centre].mean() > 95 and vignette_only[corner].mean() < 80


def test_kit_view_darkening_is_configurable():
    img = np.full((480, 640, 3), 100, np.uint8)
    legacy = render_kit(img, ROI)
    natural = render_kit(img, ROI, dim=1.0, lift=0)
    area = (slice(100, 200), slice(100, 200))  # away from the bars and guides
    assert legacy[area].mean() == pytest.approx(64, abs=1)  # 0.60 * 100 + 4
    assert natural[area].mean() == pytest.approx(100, abs=1)
