"""Stick pixel-candidate extraction (Phase 03, Task 03.5) — classical pipeline, markerless.

Inside the search region (Task 03.4): grayscale -> Gaussian blur -> Canny edges -> AND region mask
-> morphological closing -> connected components -> keep components that are **elongated**
(PCA eigenvalue ratio >= ``min_elongation``) and **oriented** within ``angle_tol_rad`` of the grip
direction prior (Q9/Q30: ordinary stick colours; edges rather than colour). The union of the kept
components' pixels is the candidate set handed to the axis fit (Task 03.6). Every threshold is a
tunable candidate (``stick.segment``); the failure catalogue (background edges, sleeve, skin) is
built from the overlays in the benchmark report, not assumed here.

A learned segmentation model is *not* implemented: it is the optional second candidate of the phase
document, opened only if the classical pipeline fails the benchmark (Open Question).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from spacedrums.stick.search_region import SearchRegion


@dataclass(frozen=True)
class SegmentSettings:
    blur_ksize: int = 3  # odd; 1 disables
    canny_low: float = 40.0
    canny_high: float = 120.0
    close_ksize: int = 3  # odd; 1 disables the morphological closing
    min_component_px: int = 25
    min_elongation: float = 2.0  # sqrt(lambda1 / lambda2) of the component pixel PCA (dev sweep: 2.0 > 3.0)
    angle_tol_rad: float = 0.7  # |component axis angle - prior angle| (mod pi)
    max_components: int = 4  # keep the N most elongated qualifying components

    def __post_init__(self) -> None:
        for name in ("blur_ksize", "close_ksize"):
            v = getattr(self, name)
            if v < 1 or v % 2 == 0:
                raise ValueError(f"{name} must be an odd integer >= 1")
        if not (0 < self.canny_low < self.canny_high):
            raise ValueError("require 0 < canny_low < canny_high")
        if self.min_component_px < 1 or self.min_elongation < 1 or self.max_components < 1:
            raise ValueError("min_component_px, min_elongation and max_components must be >= 1")
        if not (0 < self.angle_tol_rad <= math.pi / 2):
            raise ValueError("angle_tol_rad must lie in (0, pi/2]")

    @classmethod
    def from_config(cls, stick_cfg: dict[str, Any]) -> SegmentSettings:
        g = stick_cfg["segment"]
        return cls(blur_ksize=int(g["blur_ksize"]), canny_low=float(g["canny_low"]),
                   canny_high=float(g["canny_high"]),
                   close_ksize=int(g["close_ksize"]), min_component_px=int(g["min_component_px"]),
                   min_elongation=float(g["min_elongation"]), angle_tol_rad=float(g["angle_tol_rad"]),
                   max_components=int(g["max_components"]))


@dataclass(frozen=True)
class ComponentInfo:
    n_px: int
    elongation: float
    angle_rad: float  # principal axis angle in the image plane, [-pi/2, pi/2)
    centroid_px: tuple[float, float]
    kept: bool
    reject_reason: str | None = None


@dataclass(frozen=True)
class SegmentResult:
    candidate_px: np.ndarray  # (N, 2) float, (x, y) in ROI px; N may be 0
    components: tuple[ComponentInfo, ...] = ()
    n_edge_px: int = 0
    mask: np.ndarray | None = field(default=None, repr=False)  # kept-candidate mask (roi_h, roi_w) bool

    @property
    def n_kept(self) -> int:
        return sum(1 for c in self.components if c.kept)


def _angle_diff_mod_pi(a: float, b: float) -> float:
    d = (a - b + math.pi / 2) % math.pi - math.pi / 2
    return abs(d)


def component_pca(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float]:
    """(elongation, principal angle) of a pixel set."""
    pts = np.stack([xs, ys], axis=1).astype(float)
    c = pts - pts.mean(axis=0)
    cov = c.T @ c / max(1, len(pts) - 1)
    evals, evecs = np.linalg.eigh(cov)  # ascending
    lam2, lam1 = max(evals[0], 1e-6), max(evals[1], 1e-6)
    v = evecs[:, 1]
    angle = math.atan2(v[1], v[0])
    if angle >= math.pi / 2:
        angle -= math.pi
    if angle < -math.pi / 2:
        angle += math.pi
    return float(math.sqrt(lam1 / lam2)), float(angle)


def segment_stick(gray_roi: np.ndarray, region: SearchRegion, settings: SegmentSettings) -> SegmentResult:
    """Candidate stick pixels inside ``region`` of the grayscale ROI crop (uint8, (h, w))."""
    h, w = gray_roi.shape[:2]
    if region.empty:
        return SegmentResult(candidate_px=np.zeros((0, 2)), mask=np.zeros((h, w), dtype=bool))
    x0, y0, x1, y1 = region.bbox_px
    if x1 <= x0 or y1 <= y0:
        return SegmentResult(candidate_px=np.zeros((0, 2)), mask=np.zeros((h, w), dtype=bool))
    crop = gray_roi[y0:y1, x0:x1]
    if settings.blur_ksize > 1:
        crop = cv2.GaussianBlur(crop, (settings.blur_ksize, settings.blur_ksize), 0)
    edges = cv2.Canny(crop, settings.canny_low, settings.canny_high)
    edges[~region.mask[y0:y1, x0:x1]] = 0
    n_edge = int(np.count_nonzero(edges))
    if settings.close_ksize > 1:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (settings.close_ksize, settings.close_ksize))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats((edges > 0).astype(np.uint8),
                                                                  connectivity=8)
    prior_angle = math.atan2(region.dir_px[1], region.dir_px[0])
    infos: list[ComponentInfo] = []
    kept: list[tuple[float, int]] = []
    for lab in range(1, n_labels):
        n_px = int(stats[lab, cv2.CC_STAT_AREA])
        # OpenCV already computed each component's bounds. Preserve the exact row-major
        # pixel order and original crop coordinates without scanning the whole crop per label.
        bx, by, bw, bh = (int(v) for v in stats[lab, :4])
        ys, xs = np.nonzero(labels[by:by + bh, bx:bx + bw] == lab)
        xs, ys = xs + bx, ys + by
        cx, cy = float(xs.mean() + x0), float(ys.mean() + y0)
        if n_px < settings.min_component_px:
            infos.append(ComponentInfo(n_px, 0.0, 0.0, (cx, cy), False, "too_small"))
            continue
        elong, ang = component_pca(xs, ys)
        if elong < settings.min_elongation:
            infos.append(ComponentInfo(n_px, elong, ang, (cx, cy), False, "not_elongated"))
            continue
        if _angle_diff_mod_pi(ang, prior_angle) > settings.angle_tol_rad:
            infos.append(ComponentInfo(n_px, elong, ang, (cx, cy), False, "orientation"))
            continue
        infos.append(ComponentInfo(n_px, elong, ang, (cx, cy), True))
        kept.append((elong, lab))
    kept.sort(reverse=True)
    keep_labels = {lab for _, lab in kept[: settings.max_components]}
    if len(kept) > settings.max_components:  # demote the surplus in the info list
        surplus = {lab for _, lab in kept[settings.max_components:]}
        infos = [ComponentInfo(c.n_px, c.elongation, c.angle_rad, c.centroid_px, False, "surplus")
                 if c.kept and lab in surplus else c
                 for c, lab in zip(infos, [lab for lab in range(1, n_labels)], strict=True)]
    mask = np.zeros((h, w), dtype=bool)
    if keep_labels:
        sel = np.isin(labels, list(keep_labels))
        mask[y0:y1, x0:x1] = sel
        ys, xs = np.nonzero(sel)
        pts = np.stack([xs + x0, ys + y0], axis=1).astype(float)
    else:
        pts = np.zeros((0, 2))
    return SegmentResult(candidate_px=pts, components=tuple(infos), n_edge_px=n_edge, mask=mask)


__all__ = ["ComponentInfo", "SegmentResult", "SegmentSettings", "component_pca", "segment_stick"]
