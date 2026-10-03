"""Contrast-adaptive edge thresholds for the stick segmentation (ADR-0044, schema 1.10).

In a dark or low-contrast search region the stick's edges stay below the fixed Canny thresholds and
no axis is found. ``stick.segment.contrast_target_range`` divides both thresholds by
``min(contrast_max_gain, target / span)``, where span is the p2-p98 grey range of the region; that
equals stretching the region's contrast. When span >= target (gain 1) the output is byte-identical
to the fixed-threshold pipeline. Synthetic images, plus recorded frames when present.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from spacedrums.capture import ReplayFrameSource
from spacedrums.config import load_config
from spacedrums.contracts import HandObservation
from spacedrums.stick import StickSettings
from spacedrums.stick.estimator import analyse
from spacedrums.stick.search_region import SearchRegion
from spacedrums.stick.segment import SegmentSettings, contrast_gain, intensity_span, segment_stick

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "data" / "dev-sessions" / "dev-p05-swing-L2-exp-5"


def region_for(h: int, w: int, angle: float = -np.pi / 2) -> SearchRegion:
    mask = np.zeros((h, w), bool)
    mask[10 : h - 10, 10 : w - 10] = True
    d = (float(np.cos(angle)), float(np.sin(angle)))
    return SearchRegion(
        origin_px=(w / 2, h - 12),
        dir_px=d,
        span_px=20.0,
        length_px=80.0,
        width_px=24.0,
        corners_px=np.zeros((4, 2)),
        polygon_px=np.array([[10, 10], [w - 10, 10], [w - 10, h - 10]]),
        bbox_px=(10, 10, w - 10, h - 10),
        mask=mask,
    )


def stick_image(background: int, stick: int, h: int = 120, w: int = 80, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.clip(rng.normal(background, 1.5, (h, w)), 0, 255).astype(np.uint8)
    img[15 : h - 15, w // 2 - 3 : w // 2 + 3] = stick  # a vertical stick 6 px wide
    return img


ADAPTIVE = SegmentSettings(contrast_target_range=100.0, contrast_max_gain=3.0)


def test_settings_default_to_fixed_thresholds_and_validate_their_range():
    assert SegmentSettings().contrast_target_range is None and SegmentSettings().contrast_max_gain == 1.0
    for bad in (
        {"contrast_target_range": 0.0},
        {"contrast_target_range": -5.0},
        {"contrast_target_range": 80.0, "contrast_max_gain": 0.9},
    ):
        with pytest.raises(ValueError):
            SegmentSettings(**bad)


def test_a_faint_stick_is_found_only_with_adaptive_thresholds():
    img, region = stick_image(30, 48), region_for(120, 80)
    fixed = segment_stick(img, region, SegmentSettings())
    adaptive = segment_stick(img, region, ADAPTIVE)
    assert fixed.n_kept == 0 and fixed.contrast_gain == 1.0
    assert adaptive.contrast_gain > 1.0 and adaptive.n_kept >= 1
    assert len(adaptive.candidate_px) >= 20


def test_a_high_contrast_region_is_byte_identical_with_and_without_the_option():
    img, region = stick_image(40, 200), region_for(120, 80)
    fixed = segment_stick(img, region, SegmentSettings())
    adaptive = segment_stick(img, region, ADAPTIVE)
    assert adaptive.contrast_gain == 1.0
    np.testing.assert_array_equal(fixed.candidate_px, adaptive.candidate_px)
    np.testing.assert_array_equal(fixed.mask, adaptive.mask)
    assert fixed.components == adaptive.components and fixed.n_edge_px == adaptive.n_edge_px


def test_gain_is_bounded_deterministic_and_uses_the_region_only():
    crop = np.full((40, 40), 10, np.uint8)
    crop[:, 20:] = 250  # bright pixels outside the mask must not count
    mask = np.zeros((40, 40), bool)
    mask[:, :20] = True
    assert intensity_span(crop[mask]) == 1.0  # flat region: span floored at 1 grey level
    assert contrast_gain(crop, mask, ADAPTIVE) == 3.0  # capped at contrast_max_gain
    assert contrast_gain(crop, mask, SegmentSettings()) == 1.0
    assert contrast_gain(crop, np.zeros_like(mask), ADAPTIVE) == 1.0
    values = np.arange(256, dtype=np.uint8).repeat(4)
    assert intensity_span(values) == pytest.approx(245.0, abs=1.0)  # p98 - p2 of a uniform ramp
    assert contrast_gain(crop, mask, ADAPTIVE) == contrast_gain(crop.copy(), mask.copy(), ADAPTIVE)


def test_config_keys_are_optional_and_validated_by_the_schema():
    base = load_config(ROOT / "configs" / "prototype.candidate.yaml")
    plain = StickSettings.from_config(base.data).segment
    assert plain.contrast_target_range is None and plain.contrast_max_gain == 1.0
    cfg = load_config(
        ROOT / "configs" / "prototype.candidate.yaml",
        overrides={"stick": {"segment": {"contrast_target_range": 90.0, "contrast_max_gain": 2.0}}},
    )
    seg = StickSettings.from_config(cfg.data).segment
    assert (seg.contrast_target_range, seg.contrast_max_gain) == (90.0, 2.0)
    from spacedrums.config import ConfigError

    with pytest.raises(ConfigError):
        load_config(
            ROOT / "configs" / "prototype.candidate.yaml",
            overrides={"stick": {"segment": {"contrast_max_gain": 0.5}}},
        )


@pytest.mark.skipif(
    not SESSION.exists(), reason="developer session dev-p05-swing-L2-exp-5 not on this machine"
)
def test_recorded_frames_are_unchanged_wherever_the_region_already_has_enough_contrast():
    cfg = load_config(ROOT / "configs" / "prototype.candidate.yaml").data
    fixed = StickSettings.from_config(cfg)
    adaptive = replace(
        fixed, segment=replace(fixed.segment, contrast_target_range=60.0, contrast_max_gain=3.0)
    )
    src = ReplayFrameSource(SESSION)
    samples = {s.frame_id: s for s in src}
    lines = (SESSION / "records" / "HandObservation.jsonl").read_text(encoding="utf-8").splitlines()[1:]
    observations = [HandObservation.from_dict(json.loads(line)) for line in lines if line.strip()]
    unchanged = changed = 0
    for obs in observations[::3]:
        if not obs.present:
            continue
        view = src.view(samples[obs.frame_id])
        l_px = fixed.geom.prior(obs.hand_id) * view.roi.shape[0]
        a, b = analyse(view, obs, fixed, l_px), analyse(view, obs, adaptive, l_px)
        if b.segment is None:
            continue
        if b.segment.contrast_gain == 1.0:
            unchanged += 1
            np.testing.assert_array_equal(a.segment.candidate_px, b.segment.candidate_px)
            assert a.axis == b.axis
        else:
            changed += 1
    assert unchanged > 20
