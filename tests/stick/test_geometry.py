"""TEST-STICK-1: search region (03.4), segmentation (03.5) and axis fit (03.6) on synthetic inputs."""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from spacedrums.capture import Roi
from spacedrums.hands import GripDirectionMethod, GripReference
from spacedrums.stick import (
    AxisMethod,
    AxisSettings,
    SearchRegionSettings,
    SegmentSettings,
    clip_polygon,
    fit_axis,
    search_region,
    segment_stick,
)

ROI = Roi(40, 20, 560, 440)


def _grip(point=(0.5, 0.8), direction=(0.0, -1.0), span_vec=(0.0, -0.07)) -> GripReference:
    return GripReference(point=point, direction=direction, angle_rad=math.atan2(direction[1], direction[0]),
                         hand_span=math.hypot(*span_vec), method=GripDirectionMethod.KNUCKLE_ROW,
                         baseline_len=math.hypot(*span_vec), span_vec=span_vec)


# ----------------------------------------------------------------------------- search region


def test_clip_polygon_inside_unchanged_and_outside_clipped():
    sq = np.array([[10, 10], [50, 10], [50, 50], [10, 50]], dtype=float)
    assert clip_polygon(sq, 100, 100).shape == (4, 2)
    out = clip_polygon(sq - 30, 100, 100)  # spans -20..20 -> clipped to 0..20
    assert out.min() >= 0 and out.max() <= 20 and out.shape[0] >= 3
    gone = clip_polygon(sq + 200, 100, 100)
    assert gone.shape[0] == 0


def test_region_geometry_upright_stick():
    g = _grip()
    r = search_region(g, ROI, SearchRegionSettings(length_factor=4.0, width_factor=1.2, back_factor=0.5))
    assert r is not None and not r.empty
    span_px = 0.07 * ROI.h
    assert r.span_px == pytest.approx(span_px)
    assert r.dir_px == pytest.approx((0.0, -1.0))
    assert r.length_px == pytest.approx(4.0 * span_px) and r.width_px == pytest.approx(1.2 * span_px)
    xs, ys = r.corners_px[:, 0], r.corners_px[:, 1]
    ox, oy = r.origin_px
    assert xs.min() == pytest.approx(ox - r.width_px / 2) and xs.max() == pytest.approx(ox + r.width_px / 2)
    assert ys.min() == pytest.approx(oy - r.length_px) and ys.max() == pytest.approx(oy + 0.5 * span_px)
    assert r.mask.shape == (ROI.h, ROI.w)
    assert r.area_px == pytest.approx((r.length_px + 0.5 * span_px) * r.width_px, rel=0.05)
    x0, y0, x1, y1 = r.bbox_px
    assert 0 <= x0 < x1 <= ROI.w and 0 <= y0 < y1 <= ROI.h


def test_region_rotation_and_clipping_at_the_roi_edge():
    g = _grip(point=(0.05, 0.5), direction=(-1.0, 0.0))  # pointing left, out of the ROI
    r = search_region(g, ROI, SearchRegionSettings())
    assert r is not None and not r.empty
    assert r.polygon_px[:, 0].min() >= 0.0  # clipped at x = 0
    assert r.polygon_px.shape[0] <= r.corners_px.shape[0] + 2
    assert r.area_px < r.length_px * r.width_px  # part of it lies outside


def test_region_none_without_direction_or_for_tiny_hands():
    g = GripReference(point=(0.5, 0.5), direction=None, angle_rad=None, hand_span=0.0,
                      method=GripDirectionMethod.KNUCKLE_ROW, baseline_len=0.0)
    assert search_region(g, ROI, SearchRegionSettings()) is None
    tiny = _grip(span_vec=(0.0, -0.001))  # 0.44 px
    assert search_region(tiny, ROI, SearchRegionSettings(min_span_px=8.0)) is None


def test_region_settings_validation():
    with pytest.raises(ValueError):
        SearchRegionSettings(length_factor=0)
    with pytest.raises(ValueError):
        SearchRegionSettings(back_factor=-1)


# ----------------------------------------------------------------------------- segmentation


def _synthetic_stick_image(angle_deg: float = 90.0, width: int = 8, length: int = 120, start=(280.0, 350.0),
                           noise: float = 0.0, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Gray ROI crop with a light stick drawn from ``start`` along ``angle_deg`` (image plane, y down)."""
    img = np.full((ROI.h, ROI.w), 60, np.uint8)
    d = np.array([math.cos(math.radians(angle_deg)), -math.sin(math.radians(angle_deg))])
    end = np.array(start) + length * d
    cv2.line(img, tuple(int(v) for v in start), tuple(int(v) for v in end), 200, width)
    if noise > 0:
        rng = np.random.default_rng(seed)
        img = np.clip(img.astype(float) + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    return img, d


def test_segmentation_keeps_the_stick_edges_and_rejects_blobs():
    img, d = _synthetic_stick_image()
    cv2.circle(img, (200, 250), 20, 200, -1)  # a round blob inside the region: not elongated
    g = _grip(point=(280 / ROI.w, 350 / ROI.h), direction=(0.0, -1.0), span_vec=(0.0, -30 / ROI.h))
    r = search_region(g, ROI, SearchRegionSettings(length_factor=5.0, width_factor=6.0))
    seg = segment_stick(img, r, SegmentSettings())
    assert seg.n_kept >= 1 and len(seg.candidate_px) > 100
    kept = [c for c in seg.components if c.kept]
    assert all(c.elongation >= 2.0 for c in kept)
    assert all(abs(abs(c.angle_rad) - math.pi / 2) < 0.2 for c in kept)  # vertical
    rejected = [c for c in seg.components if not c.kept]
    assert any(c.reject_reason == "not_elongated" for c in rejected)
    # the candidate pixels hug the stick: their x spread is the stick width plus edge thickness
    assert np.ptp(seg.candidate_px[:, 0]) < 20


def test_segmentation_rejects_wrong_orientation():
    img, _ = _synthetic_stick_image(angle_deg=0.0, start=(150.0, 300.0))  # horizontal stick
    g = _grip(point=(150 / ROI.w, 300 / ROI.h), direction=(0.0, -1.0), span_vec=(0.0, -30 / ROI.h))
    r = search_region(g, ROI, SearchRegionSettings(length_factor=5.0, width_factor=8.0))
    seg = segment_stick(img, r, SegmentSettings(angle_tol_rad=0.5))
    assert seg.n_kept == 0 and any(c.reject_reason == "orientation" for c in seg.components)


def test_segmentation_empty_region_and_settings_validation():
    img, _ = _synthetic_stick_image()
    g = _grip(point=(-2.0, 0.5))  # far outside
    r = search_region(g, ROI, SearchRegionSettings())
    seg = segment_stick(img, r, SegmentSettings())
    assert len(seg.candidate_px) == 0 and seg.n_kept == 0
    with pytest.raises(ValueError):
        SegmentSettings(blur_ksize=2)
    with pytest.raises(ValueError):
        SegmentSettings(canny_low=100, canny_high=50)


# ----------------------------------------------------------------------------- axis fit


def _line_points(origin, u, length=120.0, n=300, sigma=0.8, outliers=0, seed=0):
    rng = np.random.default_rng(seed)
    t = rng.uniform(0, length, n)
    normal = np.array([-u[1], u[0]])
    pts = np.array(origin) + t[:, None] * u + rng.normal(0, sigma, n)[:, None] * normal
    if outliers:
        pts = np.vstack([pts, rng.uniform([0, 0], [ROI.w, ROI.h], (outliers, 2))])
    return pts


@pytest.mark.parametrize("method", ["PCA", "RANSAC", "HOUGH"])
def test_axis_fit_recovers_synthetic_line(method):
    u = np.array([math.cos(math.radians(75)), -math.sin(math.radians(75))])
    grip = np.array([280.0, 350.0])
    pts = _line_points(grip + 3 * u, u, outliers=0 if method == "PCA" else 60)
    mask = np.zeros((ROI.h, ROI.w), bool)
    ij = np.round(pts).astype(int)
    ij = ij[(ij[:, 0] >= 0) & (ij[:, 0] < ROI.w) & (ij[:, 1] >= 0) & (ij[:, 1] < ROI.h)]
    mask[ij[:, 1], ij[:, 0]] = True
    ax = fit_axis(pts, tuple(grip), tuple(u), span_px=30.0, settings=AxisSettings(method=AxisMethod(method)),
                  mask=mask)
    assert ax is not None
    ang = math.degrees(math.acos(min(1.0, abs(float(np.dot(ax.dir_px, u))))))
    assert ang < 2.0  # within 2 degrees
    assert float(np.dot(ax.dir_px, u)) > 0  # oriented away from the hand
    assert ax.grip_distance_px < 3.0 and ax.residual_rms_px < 3.0
    assert 100 < ax.support_len_px < 135
    assert ax.n_inliers >= 250 and 0 < ax.confidence <= 1
    far = np.asarray(ax.support_far_px)
    assert np.hypot(*(far - (grip + 3 * u + 120 * u))) < 10


def test_axis_fit_rejects_line_far_from_grip():
    u = np.array([0.0, -1.0])
    pts = _line_points((400.0, 350.0), u)  # 120 px to the right of the grip
    ax = fit_axis(pts, (280.0, 350.0), tuple(u), span_px=30.0, settings=AxisSettings(method="PCA"))
    assert ax is None


def test_axis_fit_needs_enough_points_and_is_deterministic():
    u = np.array([0.0, -1.0])
    pts = _line_points((280.0, 350.0), u, n=10)
    assert fit_axis(pts, (280.0, 350.0), tuple(u), 30.0, AxisSettings(min_inliers=20)) is None
    pts = _line_points((280.0, 350.0), u, outliers=80)
    a = fit_axis(pts, (280.0, 350.0), tuple(u), 30.0, AxisSettings(method="RANSAC", seed=3))
    b = fit_axis(pts, (280.0, 350.0), tuple(u), 30.0, AxisSettings(method="RANSAC", seed=3))
    assert a == b  # re-seeded per call: bit-identical (TEST-CAUSAL-1 precondition)


def test_axis_orientation_follows_prior_sign():
    u = np.array([0.0, -1.0])
    pts = _line_points((280.0, 350.0), u)
    up = fit_axis(pts, (280.0, 350.0), (0.0, -1.0), 30.0, AxisSettings(method="PCA"))
    down = fit_axis(pts, (280.0, 350.0), (0.0, 1.0), 30.0, AxisSettings(method="PCA"))
    assert up.dir_px[1] < 0 < down.dir_px[1]


def test_axis_settings_validation():
    with pytest.raises(ValueError):
        AxisSettings(method="LSQ")
    with pytest.raises(ValueError):
        AxisSettings(min_inliers=1)
