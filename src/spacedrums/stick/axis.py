"""Stick axis estimation (Phase 03, Task 03.6): line fit to candidate pixels, anchored at the grip.

Three fit candidates, selected by ``stick.axis.method`` (Pending Benchmark; ADR at the phase gate):

* ``PCA``    — principal axis of all candidate pixels; accepted only if the line passes within
  ``grip_tolerance_factor * span_px`` of the grip point.
* ``RANSAC`` — hypotheses are lines **through the grip point** and a random candidate pixel (the grip
  constraint is built into the hypothesis), scored by inlier count within ``inlier_dist_px``; the
  winner is refined by PCA on its inliers and re-checked against the grip tolerance. Deterministic:
  the generator is re-seeded with ``seed`` on every call, so the same input gives the same output
  (``TEST-CAUSAL-1`` bit-identity).
* ``HOUGH``  — probabilistic Hough segments on the candidate mask; the longest segment whose line
  passes within the grip tolerance wins; inliers/residuals computed as above.

Output: ``axis_origin`` (grip point projected onto the line), ``axis_dir`` oriented **away from the
hand** (positive dot product with the grip direction prior), ``confidence`` (producer-defined:
``inlier_ratio * grip_proximity``, where ``grip_proximity = 1 - d_grip / tolerance``), the residual
RMS of the inliers, and the **support** = signed extent of the inliers along the axis from the
origin, following the *connected* inlier run only (a gap longer than ``support_gap_factor * span``
ends it, so stray in-band pixels cannot extend the stick); its far end is the ``AXIS_REFINED`` tip
candidate. All in ROI pixel coordinates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import cv2
import numpy as np


class AxisMethod(StrEnum):
    PCA = "PCA"
    RANSAC = "RANSAC"
    HOUGH = "HOUGH"


@dataclass(frozen=True)
class AxisSettings:
    method: AxisMethod = AxisMethod.RANSAC
    grip_tolerance_factor: float = 0.6  # x span_px: max distance of the fitted line from the grip point
    inlier_dist_px: float = 2.0  # floor; the band is max(this, inlier_dist_factor * span_px)
    inlier_dist_factor: float = 0.3  # x span_px: covers both stick edges (stick width ~ 0.25-0.3 span)
    min_inliers: int = 20
    ransac_iters: int = 64
    seed: int = 0
    support_gap_factor: float = 0.5  # x span_px: a gap longer than this ends the connected support
    hough_threshold: int = 15
    hough_min_len_px: float = 15.0
    hough_max_gap_px: float = 6.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", AxisMethod(self.method))
        if self.grip_tolerance_factor <= 0 or self.inlier_dist_px <= 0 or self.inlier_dist_factor < 0:
            raise ValueError("grip_tolerance_factor, inlier_dist_px > 0 and inlier_dist_factor >= 0 required")
        if self.min_inliers < 2 or self.ransac_iters < 1:
            raise ValueError("min_inliers >= 2 and ransac_iters >= 1 required")

    @classmethod
    def from_config(cls, stick_cfg: dict[str, Any]) -> AxisSettings:
        a = stick_cfg["axis"]
        return cls(method=AxisMethod(a["method"]), grip_tolerance_factor=float(a["grip_tolerance_factor"]),
                   inlier_dist_px=float(a["inlier_dist_px"]),
                   inlier_dist_factor=float(a["inlier_dist_factor"]), min_inliers=int(a["min_inliers"]),
                   ransac_iters=int(a["ransac_iters"]), seed=int(a["seed"]),
                   support_gap_factor=float(a["support_gap_factor"]),
                   hough_threshold=int(a["hough_threshold"]), hough_min_len_px=float(a["hough_min_len_px"]),
                   hough_max_gap_px=float(a["hough_max_gap_px"]))


@dataclass(frozen=True)
class AxisEstimate:
    origin_px: tuple[float, float]  # grip point projected onto the fitted line
    dir_px: tuple[float, float]  # unit, oriented away from the hand
    confidence: float  # inlier_ratio * grip_proximity in [0, 1]
    inlier_ratio: float
    n_points: int
    n_inliers: int
    residual_rms_px: float  # perpendicular RMS of the inliers
    grip_distance_px: float  # distance of the grip point from the line
    support_len_px: float  # far extent of the inliers along dir from the origin (>= 0)
    support_near_px: float  # near extent (<= 0: behind the origin)
    support_far_px: tuple[float, float]  # far inlier endpoint on the axis
    method: AxisMethod

    @property
    def angle_rad(self) -> float:
        return math.atan2(self.dir_px[1], self.dir_px[0])


def _pca_line(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = pts.mean(axis=0)
    d = pts - c
    cov = d.T @ d / max(1, len(pts) - 1)
    _, evecs = np.linalg.eigh(cov)
    v = evecs[:, 1]
    return c, v / np.hypot(v[0], v[1])


def _perp_dist(pts: np.ndarray, point: np.ndarray, u: np.ndarray) -> np.ndarray:
    d = pts - point
    return np.abs(d[:, 0] * u[1] - d[:, 1] * u[0])


def _band(s: AxisSettings, span_px: float) -> float:
    return max(s.inlier_dist_px, s.inlier_dist_factor * span_px)


def _contiguous_extent(proj: np.ndarray, max_gap: float) -> tuple[float, float]:
    """(far, near) extent of the inlier run connected to the origin: stop at the first gap > max_gap.

    Stray in-band pixels far along the line (a background edge, an outlier) must not extend the
    support; the AXIS_REFINED tip is the end of the *connected* stick, not the farthest inlier.
    """
    fwd = np.sort(proj[proj >= 0])
    far = 0.0
    for p in fwd:
        if p - far > max_gap:
            break
        far = float(p)
    bwd = np.sort(-proj[proj < 0])
    near = 0.0
    for p in bwd:
        if p - near > max_gap:
            break
        near = float(p)
    return far, -near


def _finish(pts: np.ndarray, point: np.ndarray, u: np.ndarray, grip: np.ndarray, prior: np.ndarray,
            span_px: float, s: AxisSettings, method: AxisMethod) -> AxisEstimate | None:
    band = _band(s, span_px)
    if float(np.dot(u, prior)) < 0:
        u = -u
    dist = _perp_dist(pts, point, u)
    inl = dist <= band
    n_in = int(inl.sum())
    if n_in < s.min_inliers:
        return None
    # refine on inliers (PCA), keep orientation
    c, v = _pca_line(pts[inl])
    if float(np.dot(v, u)) < 0:
        v = -v
    dist = _perp_dist(pts, c, v)
    inl = dist <= band
    n_in = int(inl.sum())
    if n_in < s.min_inliers:
        return None
    tol = s.grip_tolerance_factor * span_px
    g_rel = grip - c
    g_dist = abs(float(g_rel[0] * v[1] - g_rel[1] * v[0]))
    if g_dist > tol:
        return None
    origin = c + float(np.dot(g_rel, v)) * v  # grip projected onto the line
    proj = (pts[inl] - origin) @ v
    far, near = _contiguous_extent(proj, s.support_gap_factor * span_px)
    ratio = n_in / len(pts)
    conf = max(0.0, min(1.0, ratio * (1.0 - g_dist / tol)))
    rms = float(np.sqrt(np.mean(dist[inl] ** 2)))
    far_pt = origin + max(far, 0.0) * v
    return AxisEstimate(origin_px=(float(origin[0]), float(origin[1])), dir_px=(float(v[0]), float(v[1])),
                        confidence=conf, inlier_ratio=float(ratio), n_points=int(len(pts)), n_inliers=n_in,
                        residual_rms_px=rms, grip_distance_px=g_dist, support_len_px=max(far, 0.0),
                        support_near_px=min(near, 0.0), support_far_px=(float(far_pt[0]), float(far_pt[1])),
                        method=method)


def fit_axis(points_px: np.ndarray, grip_px: tuple[float, float], prior_dir_px: tuple[float, float],
             span_px: float, settings: AxisSettings, mask: np.ndarray | None = None) -> AxisEstimate | None:
    """Fit the stick axis to candidate pixels; ``None`` when no acceptable line exists."""
    pts = np.asarray(points_px, dtype=float).reshape(-1, 2)
    if len(pts) < settings.min_inliers:
        return None
    grip = np.asarray(grip_px, dtype=float)
    prior = np.asarray(prior_dir_px, dtype=float)
    prior = prior / max(1e-12, float(np.hypot(prior[0], prior[1])))
    s = settings
    if s.method is AxisMethod.PCA:
        c, v = _pca_line(pts)
        return _finish(pts, c, v, grip, prior, span_px, s, s.method)
    if s.method is AxisMethod.RANSAC:
        rng = np.random.default_rng(s.seed)  # re-seeded per call: deterministic output
        best: tuple[int, np.ndarray] | None = None
        idx = rng.integers(0, len(pts), size=s.ransac_iters)
        for i in idx:
            d = pts[i] - grip
            n = float(np.hypot(d[0], d[1]))
            if n < 1e-6:
                continue
            u = d / n
            n_in = int((_perp_dist(pts, grip, u) <= _band(s, span_px)).sum())
            if best is None or n_in > best[0]:
                best = (n_in, u)
        if best is None or best[0] < s.min_inliers:
            return None
        return _finish(pts, grip, best[1], grip, prior, span_px, s, s.method)
    # HOUGH
    if mask is None:
        return None
    m = mask.astype(np.uint8) * 255
    lines = cv2.HoughLinesP(m, 1, np.pi / 180, s.hough_threshold, minLineLength=s.hough_min_len_px,
                            maxLineGap=s.hough_max_gap_px)
    if lines is None:
        return None
    tol = s.grip_tolerance_factor * span_px
    best_seg: tuple[float, np.ndarray, np.ndarray] | None = None
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        p = np.array([x1, y1], dtype=float)
        q = np.array([x2, y2], dtype=float)
        u = q - p
        ln = float(np.hypot(u[0], u[1]))
        if ln < 1e-6:
            continue
        u /= ln
        g_rel = grip - p
        if abs(float(g_rel[0] * u[1] - g_rel[1] * u[0])) > tol:
            continue
        if best_seg is None or ln > best_seg[0]:
            best_seg = (ln, p, u)
    if best_seg is None:
        return None
    return _finish(pts, best_seg[1], best_seg[2], grip, prior, span_px, s, s.method)


__all__ = ["AxisEstimate", "AxisMethod", "AxisSettings", "fit_axis"]
