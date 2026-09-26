"""Task 14.4 unit tests: layout fit, scaling, determinism, nudges, sounds, overlap and ROI checks."""

import copy
import math

import numpy as np
import pytest
import yaml
from calib_helpers import ROOT

from spacedrums.calib.fit import (
    Box,
    FitSettings,
    LayoutError,
    ScaleTranslate,
    apply_nudges,
    apply_sample_overrides,
    compose_layout,
    fit_layout,
    inside_roi_report,
    layout_bbox,
    overlap_report,
    percentile_box,
    transform_layout,
    zone_bbox,
    zones_hash,
)
from spacedrums.geometry import ZoneRegistry

MVP4 = yaml.safe_load((ROOT / "configs/zones/mvp4.candidate.yaml").read_text(encoding="utf-8"))["zones"]
V17 = yaml.safe_load((ROOT / "configs/zones/v1-7.candidate.yaml").read_text(encoding="utf-8"))["zones"]


def ellipse_zone(zone_id, cx, cy, rx, ry, angle=0.0):
    shape = {"type": "ELLIPSE", "center": [cx, cy], "rx": rx, "ry": ry, "angle_rad": angle}
    surface = {**shape, "type": "ARC", "theta_start_rad": math.pi, "theta_end_rad": 2 * math.pi}
    normal = [-math.sin(angle), math.cos(angle)]
    return {
        "zone_id": zone_id,
        "name": zone_id,
        "trigger_type": "HAND_TIP",
        "shape": shape,
        "impact_surface": surface,
        "inward_normal": normal,
        "sample_id": "s",
        "gain_curve_id": "default",
    }


def test_rotated_ellipse_bbox_matches_dense_sampling():
    z = ellipse_zone("a", 0.5, 0.4, 0.16, 0.065, 0.12)
    b = zone_bbox(z)
    t = np.linspace(0, 2 * np.pi, 200001)
    c, s = math.cos(0.12), math.sin(0.12)
    x = 0.5 + 0.16 * np.cos(t) * c - 0.065 * np.sin(t) * s
    y = 0.4 + 0.16 * np.cos(t) * s + 0.065 * np.sin(t) * c
    assert b.as_list() == pytest.approx([x.min(), y.min(), x.max(), y.max()], abs=1e-9)


def test_percentile_box():
    pts = [(x / 100, 0.2 + x / 200) for x in range(101)]
    b = percentile_box(pts, 5, 95)
    assert b.as_list() == pytest.approx([0.05, 0.225, 0.95, 0.675])
    with pytest.raises(ValueError):
        percentile_box([], 5, 95)


@pytest.mark.parametrize("zones", [MVP4, V17], ids=["mvp4", "v1-7"])
def test_identity_transform_is_an_exact_copy(zones):
    out = transform_layout(zones, ScaleTranslate())
    assert out == zones and out is not zones and out[0] is not zones[0]
    assert zones_hash(out) == zones_hash(zones)


def test_scale_translate_keeps_normals_angles_and_valid_zones():
    t = ScaleTranslate(0.8, 0.05, -0.02)
    out = transform_layout(MVP4, t)
    ZoneRegistry.from_config(out)  # Phase 04 validation: surface on the boundary, normal into the shape
    for a, b in zip(MVP4, out, strict=True):
        assert b["inward_normal"] == a["inward_normal"]
        assert b["shape"]["angle_rad"] == a["shape"]["angle_rad"]
        assert b["impact_surface"]["theta_start_rad"] == a["impact_surface"]["theta_start_rad"]
        assert b["shape"]["center"] == pytest.approx(
            [0.8 * a["shape"]["center"][0] + 0.05, 0.8 * a["shape"]["center"][1] - 0.02]
        )
        assert b["shape"]["rx"] == pytest.approx(0.8 * a["shape"]["rx"])
        assert b["impact_surface"]["center"] == b["shape"]["center"]
    back = transform_layout(out, ScaleTranslate(1 / 0.8, -0.05 / 0.8, 0.02 / 0.8))
    for a, b in zip(MVP4, back, strict=True):
        assert b["shape"]["center"] == pytest.approx(a["shape"]["center"], abs=1e-12)


def test_polygon_zone_transform():
    poly = {
        "zone_id": "pad",
        "name": "Pad",
        "trigger_type": "HAND_TIP",
        "shape": {"type": "POLYGON", "points": [[0.4, 0.5], [0.6, 0.5], [0.6, 0.7], [0.4, 0.7]]},
        "impact_surface": {"type": "SEGMENT", "p0": [0.4, 0.5], "p1": [0.6, 0.5]},
        "inward_normal": [0.0, 1.0],
        "sample_id": "s",
        "gain_curve_id": "default",
    }
    out = transform_layout([poly], ScaleTranslate(1.2, -0.1, 0.0))
    ZoneRegistry.from_config(out)
    assert out[0]["impact_surface"]["p0"] == pytest.approx([0.38, 0.6])


def test_fit_centres_and_scales_into_the_envelope():
    tb = layout_bbox(MVP4)
    fs = FitSettings(margin=0.0, roi_inset=0.0)
    same = fit_layout(MVP4, tb, fs)
    assert same.transform.scale == pytest.approx(1.0) and same.transform.tx == pytest.approx(0.0, abs=1e-12)
    small = Box(0.3, 0.3, 0.6, 0.6)
    fit = fit_layout(MVP4, small, FitSettings())
    assert fit.clamped and fit.transform.scale == pytest.approx(0.7)
    assert any("clamped" in w for w in fit.warnings)
    shifted = fit_layout(MVP4, Box(0.3, 0.45, 1.3, 1.05), FitSettings())
    fb = shifted.fitted_bbox
    assert fb.x0 >= 0.01 - 1e-12 and fb.x1 <= 0.99 + 1e-12 and fb.y1 <= 0.99 + 1e-12
    assert shifted.clamped
    inner = fit_layout(MVP4, Box(0.1, 0.25, 0.85, 0.75), FitSettings())
    assert inner.fitted_bbox.x0 >= 0.12 - 1e-9 and inner.fitted_bbox.x1 <= 0.83 + 1e-9  # margin 0.02


def test_fit_is_deterministic():
    env = Box(0.113, 0.2427, 0.887, 0.7957)
    a = fit_layout(MVP4, env, FitSettings())
    b = fit_layout(MVP4, env, FitSettings())
    za = compose_layout(MVP4, a.transform, {}, 0.05, {})
    zb = compose_layout(MVP4, b.transform, {}, 0.05, {})
    assert zones_hash(za) == zones_hash(zb)


def test_nudges_are_bounded_and_known():
    out = apply_nudges(MVP4, {"snare": [0.05, -0.05]}, 0.05)
    assert out[1]["shape"]["center"] == pytest.approx([0.45, 0.63])
    assert out[1]["impact_surface"]["center"] == out[1]["shape"]["center"]
    assert out[0] == MVP4[0]
    with pytest.raises(LayoutError, match="exceeds"):
        apply_nudges(MVP4, {"snare": [0.051, 0.0]}, 0.05)
    with pytest.raises(LayoutError, match="unknown"):
        apply_nudges(MVP4, {"kick": [0.0, 0.0]}, 0.05)


def test_sample_overrides_change_only_the_sound():
    out = apply_sample_overrides(MVP4, {"snare": "tr505-clap"}, available=["tr505-clap", "tr505-snare"])
    assert out[1]["sample_id"] == "tr505-clap"
    assert {k: v for k, v in out[1].items() if k != "sample_id"} == {
        k: v for k, v in MVP4[1].items() if k != "sample_id"
    }
    with pytest.raises(LayoutError, match="sample bank"):
        apply_sample_overrides(MVP4, {"snare": "missing"}, available=["tr505-snare"])


def test_overlap_report():
    assert overlap_report(MVP4, ambiguity_gap=0.01)["passed"]
    report = overlap_report(V17)  # Phase 04 V1-7 candidate: tom1 and tom2 overlap (finding, ADR-0037)
    assert not report["passed"] and ["tom1", "tom2"] in report["overlapping_pairs"]
    a, b = ellipse_zone("a", 0.3, 0.5, 0.1, 0.05), ellipse_zone("b", 0.3, 0.5, 0.1, 0.05)
    assert not overlap_report([a, b])["passed"]
    small = ellipse_zone("small", 0.3, 0.5, 0.02, 0.01)
    assert not overlap_report([a, small])["passed"]  # containment without edge crossing
    far = ellipse_zone("far", 0.7, 0.5, 0.1, 0.05)
    assert overlap_report([a, far])["passed"]
    near = ellipse_zone("near", 0.505, 0.5, 0.1, 0.05)
    rep = overlap_report([a, near], ambiguity_gap=0.01)
    assert rep["passed"] and rep["near_pairs"][0]["zones"] == ["a", "near"]
    assert 0 < rep["near_pairs"][0]["gap"] < 0.01


def test_v17_overlap_is_resolved_by_bounded_nudges():
    zones = compose_layout(V17, ScaleTranslate(), {"tom1": [-0.03, 0.0], "tom2": [0.03, 0.0]}, 0.05, {})
    assert overlap_report(zones)["passed"]


def test_inside_roi_report():
    z = ellipse_zone("edge", 0.05, 0.5, 0.1, 0.05)
    rep = inside_roi_report([z])
    assert not rep["passed"] and rep["outside"][0]["zone_id"] == "edge"
    assert inside_roi_report(MVP4)["passed"]


def test_compose_validates_zones():
    broken = copy.deepcopy(MVP4)
    broken[0]["impact_surface"]["rx"] = 0.2  # surface no longer on the boundary
    with pytest.raises(ValueError):
        compose_layout(broken, ScaleTranslate(), {}, 0.05, {})
