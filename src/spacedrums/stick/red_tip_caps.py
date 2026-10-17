"""Red-painted caps by local redness contrast: the ``redness`` detector (``stick_tip.detector``).

Why not colour thresholds: at playing distance in the owner's room (recordings 2026-10-17, teal light,
exposure -5) a cap is about 11 px across, dark (V 30-55) and shifted toward magenta (hue -15..0). The HSV
detector's seed floors reject most cap pixels (0-11 % of 233 hand-labelled caps found) and any looser colour
band also admits skin, wood and cloth, whose pixels overlap the paint in colour. What does separate a cap is
*local* contrast: a small blob redder than everything around it (docs/perf/red-tip-stick-mode.md section 11).

Per frame, all at half resolution (area-downscaled ROI):

1. **Redness** ``rho = min(R - G, R - B + 12)`` (BGR levels): red over green and not much bluer than red, so
   magenta paint passes while teal light, walls and the shirt go negative.
2. **Blobs**: difference of Gaussians of ``rho`` (sigma / 2 minus sigma for each of ``redness_sigmas``);
   local maxima (5x5) at or above ``redness_threshold``, strongest first.
3. **Region**: each peak grows into the connected pixels above ``surround + region_level x (peak -
   surround)`` inside a 6-sigma window (``surround`` = the DoG's outer Gaussian at the peak). The level is
   raised (0.5, 0.7) until the region closes inside its window; a region that never closes (a red wall, a lit
   face) keeps a 2-sigma disc around the peak (``closed`` feature 0). Peaks inside an earlier region are
   that region.
4. **Cap point**: the centre of the region's largest inscribed circle (holes filled: a highlight inside the
   ball is ball) when its radius reaches 3 half-res px: the ball, since the painted neck and a paint run are
   narrower. Smaller regions keep the peak itself.
5. **One stick end**: two candidates within ``merge_reach_px`` joined by a red path (redness along the segment
   never below ``surround + merge_level x (peak - surround)``) are one structure: a ball split by its
   highlight, or a ball and its painted neck. The widest is kept unless the verifier prefers the other by
   more than ``merge_score_margin``; the other becomes a ``SAME_CAP`` reject.
6. **Verifier** (:class:`CapVerifier`): a logistic score over region features -> ``RedBlob.score`` in
   [0, 1], the evidence the tracker (stick/red_tip_evidence.py) accumulates. The built-in coefficients were
   fitted on the owner's labelled recordings (``scripts/analyze_red_tips.py fit-verifier``, which refits
   them from new labels); caps are dark, saturated, magenta (G < B) and glossy (a highlight), hands brighter
   and green-over-blue.

A region touching the ROI border with its ball centre within one radius of it is ``clipped`` (cut cap: its
point is biased toward the visible part). Coordinates are ROI pixels (full resolution) in camera orientation.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np

from spacedrums.stick.red_tip import RedBlob, RedTipSettings

REDNESS_BLUE_OFFSET = 12.0  # rho = min(R - G, R - B + 12): magenta paint (B slightly above R) still counts
PEAK_KERNEL = np.ones((5, 5), np.uint8)
WINDOW_SIGMAS = 6.0  # region window half-size in sigmas ...
WINDOW_MIN, WINDOW_MAX = 12, 48  # ... clamped (half-res px)
LEVELS = (0.5, 0.7)  # region levels tried after region_level until the region closes
BALL_MIN_RADIUS = 3.0  # half-res px: smaller regions keep the DoG peak as their point
OPEN_DISC_SIGMAS = 2.0  # a never-closing region keeps this disc around its peak

# Every feature a candidate carries (half-resolution units); a verifier uses any subset by name.
FEATURES = (
    "response",  # DoG response at the peak
    "response_rel",  # ... relative to the frame's strongest peak
    "sigma",  # DoG scale of the peak (full-res px)
    "radius",  # inscribed radius (full-res px)
    "area",  # region area (full-res px^2)
    "compactness",  # area / inscribed disc area (1 = round)
    "elongation",  # sqrt(major / minor second moment)
    "redness",  # mean rho inside the region
    "redness_contrast",  # ... minus mean rho in a ring one radius wide around it
    "value",  # mean V (max channel) inside the region
    "saturation",  # mean (V - min) / V inside the region
    "value_contrast",  # mean V of the ring minus inside (caps are darker than their surround)
    "highlight",  # brightest pixel of region + ring minus the region's mean V (gloss)
    "green_minus_blue",  # mean G - B inside (paint is magenta here, skin and wood green over blue)
    "closed",  # 1 when the region closed inside its window
    "hue",  # signed hue of the region's mean colour in degrees: 0 red, < 0 toward magenta, > 0 toward orange
    "orange",  # max(0, hue): skin and wood sit at +10..+30, the paint at or below about +3
    "blueness",  # max(0, -hue): magenta paint in the teal light, and the bluish wall and shirt further out
)

# Fitted with scripts/analyze_red_tips.py fit-verifier on the four labelled owner recordings (2026-10-16
# 225435, 2026-10-17 005436 / 005615 / 005812; all labelled frames: 239 caps, 1012 non-caps). Standardised
# logistic regression, L2 = 1. Signs: stronger and relatively stronger response, more red contrast, darker,
# more saturated and glossier -> more cap-like; orange (skin, wood) and far-blue (wall, shirt) -> less.
# Chosen on held-out halves and the unpainted data/dev-captures (docs/perf/red-tip-stick-mode.md section 11).
DEFAULT_VERIFIER = {
    "features": ["response", "response_rel", "redness_contrast", "value", "saturation", "highlight", "orange",
                 "blueness"],
    "mean": [14.691, 0.650722, 22.1019, 79.8599, 0.424444, 57.6165, 2.34272, 47.0517],
    "scale": [4.75128, 0.190233, 7.87067, 39.3419, 0.13959, 41.9369, 9.24614, 50.8077],
    "weights": [2.13515, 0.992018, 0.666219, -2.01237, 1.02678, 0.557993, -2.96144, -0.968935],
    "bias": -4.96775,
}


@dataclass(frozen=True)
class CapVerifier:
    """Logistic cap score over standardised features: ``sigmoid(bias + sum(w * (x - mean) / scale))``."""

    features: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    weights: tuple[float, ...]
    bias: float

    def __post_init__(self) -> None:
        unknown = [f for f in self.features if f not in FEATURES]
        if unknown:
            raise ValueError(f"unknown verifier features {unknown}; known: {list(FEATURES)}")
        n = len(self.features)
        if not n or not len(self.mean) == len(self.scale) == len(self.weights) == n:
            raise ValueError("verifier features, mean, scale and weights need the same non-zero length")
        if min(self.scale) <= 0:
            raise ValueError("verifier scales must be > 0")

    @classmethod
    def from_dict(cls, d: dict | None) -> CapVerifier:
        d = d or DEFAULT_VERIFIER
        def floats(key):
            return tuple(float(v) for v in d[key])

        return cls(tuple(d["features"]), floats("mean"), floats("scale"), floats("weights"), float(d["bias"]))

    def as_dict(self) -> dict:
        return {"features": list(self.features), "mean": [round(v, 6) for v in self.mean],
                "scale": [round(v, 6) for v in self.scale], "weights": [round(v, 6) for v in self.weights],
                "bias": round(self.bias, 6)}

    @property
    def index(self) -> list[int]:
        return [FEATURES.index(f) for f in self.features]

    def score(self, rows: np.ndarray) -> np.ndarray:
        """Quality in [0, 1] for rows of all :data:`FEATURES`."""
        if not len(rows):
            return np.zeros(0)
        z = (np.asarray(rows, float)[:, self.index] - np.asarray(self.mean)) / np.asarray(self.scale)
        return 1.0 / (1.0 + np.exp(-(z @ np.asarray(self.weights) + self.bias)))

    @classmethod
    def fit(cls, rows: np.ndarray, labels: np.ndarray, features=DEFAULT_VERIFIER["features"], *,
            l2: float = 1.0, iterations: int = 50) -> CapVerifier:
        """Newton / IRLS logistic regression on standardised features (no extra dependency)."""
        x = np.asarray(rows, float)[:, [FEATURES.index(f) for f in features]]
        y = np.asarray(labels, float)
        if len(set(y.tolist())) < 2:
            raise ValueError("fitting a verifier needs both cap and non-cap examples")
        mean, scale = x.mean(0), x.std(0) + 1e-6
        z = np.hstack([(x - mean) / scale, np.ones((len(x), 1))])
        w = np.zeros(z.shape[1])
        ridge = l2 * np.diag(np.r_[np.ones(len(w) - 1), 0.0])
        for _ in range(iterations):
            p = 1.0 / (1.0 + np.exp(-z @ w))
            grad = z.T @ (p - y) + ridge @ w
            hess = (z * (p * (1 - p))[:, None]).T @ z + ridge
            step = np.linalg.solve(hess, grad)
            w -= step
            if float(np.abs(step).max()) < 1e-8:
                break
        return cls(tuple(features), tuple(mean.tolist()), tuple(scale.tolist()), tuple(w[:-1].tolist()),
                   float(w[-1]))


@dataclass(frozen=True)
class CapCandidate:
    """One redness candidate before verification (half-res internals kept for merging and the HUD)."""

    point: tuple[float, float]  # ROI px (full resolution): ball centre or peak
    peak: tuple[float, float]  # ROI px: the DoG peak
    features: tuple[float, ...]  # FEATURES order
    clipped: bool
    base: float  # surround redness at the peak (half-res map)
    top: float  # peak redness (blurred map)
    half: tuple[float, float]  # point in half-res px
    bbox: tuple[int, int, int, int]  # ROI px x, y, w, h
    outline: tuple[tuple[int, int], ...]
    axis: tuple[float, float]


@dataclass(frozen=True)
class CapDetection:
    blobs: tuple[RedBlob, ...]  # verified candidates, best quality first (score = quality)
    rejected: tuple[RedBlob, ...]  # merged parts of a stick end (reason SAME_CAP) and ignored regions
    reject_counts: Counter
    mask: np.ndarray  # half-res uint8: the candidate regions (HUD inset)


def signed_hue(r: float, g: float, b: float) -> float:
    """Hue of one colour in degrees, signed around red: paint reads -100..+3 in the owner's recordings and
    about -6..+2 in daylight, skin and wood +10..+30 (brightness-independent, unlike G - B)."""
    hi, lo = max(r, g, b), min(r, g, b)
    if hi - lo < 1e-6:
        return 0.0
    if hi == r:
        hue = 60.0 * (g - b) / (hi - lo)
    elif hi == g:
        hue = 60.0 * (2.0 + (b - r) / (hi - lo))
    else:
        hue = 60.0 * (4.0 + (r - g) / (hi - lo))
    return (hue + 180.0) % 360.0 - 180.0


def redness(bgr: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(bgr.astype(np.float32))
    return np.minimum(r - g, r - b + REDNESS_BLUE_OFFSET)


def _peaks(rho: np.ndarray, sigmas, threshold: float, limit: int) -> list[tuple]:
    """(x, y, response, sigma, surround) of the ``limit`` strongest DoG maxima, strongest first."""
    surround = [cv2.GaussianBlur(rho, (0, 0), s) for s in sigmas]
    resp = [cv2.GaussianBlur(rho, (0, 0), s / 2) - sur for s, sur in zip(sigmas, surround, strict=True)]
    best = resp[0].copy()
    for r in resp[1:]:
        np.maximum(best, r, out=best)
    ys, xs = np.nonzero((best == cv2.dilate(best, PEAK_KERNEL)) & (best >= threshold))
    values = best[ys, xs]
    order = np.argsort(-values, kind="stable")[:limit]
    ys, xs, values = ys[order], xs[order], values[order]
    scale = np.argmax(np.stack([r[ys, xs] for r in resp]), 0) if len(order) else []  # first maximum
    return [(int(x), int(y), float(v), float(sigmas[k]), float(surround[k][y, x]))
            for x, y, v, k in zip(xs, ys, values, scale, strict=True)]


def _touches_window(comp: np.ndarray, box, shape) -> bool:
    x0, y0, x1, y1 = box
    hs, ws = shape
    return bool((comp[0].any() and y0 > 0) or (comp[-1].any() and y1 < hs) or
                (comp[:, 0].any() and x0 > 0) or (comp[:, -1].any() and x1 < ws))


class CapDetector:
    """Stateless per-frame redness candidates + verifier; ``settings`` is the only configuration."""

    def __init__(self, settings: RedTipSettings | None = None) -> None:
        self.settings = settings or RedTipSettings()
        self.verifier = CapVerifier.from_dict(self.settings.verifier)

    def candidates(self, roi: np.ndarray) -> tuple[list[CapCandidate], np.ndarray, np.ndarray]:
        """Unverified candidates (at most ``redness_candidates``), the blurred half-res redness map and the
        half-res region mask."""
        s = self.settings
        h, w = roi.shape[:2]
        small = cv2.resize(roi, (max(1, w // 2), max(1, h // 2)), interpolation=cv2.INTER_AREA)
        small = small.astype(np.float32)
        hs, ws = small.shape[:2]
        bs, gs, rs = cv2.split(small)
        rho = np.minimum(rs - gs, rs - bs + REDNESS_BLUE_OFFSET)
        peaks = _peaks(rho, s.redness_sigmas, s.redness_threshold, 2 * s.redness_candidates)
        rho_b = cv2.GaussianBlur(rho, (0, 0), 0.7)
        mask = np.zeros((hs, ws), np.uint8)
        if not peaks:
            return [], rho_b, mask
        v = np.maximum(np.maximum(rs, gs), bs)
        sat = (v - np.minimum(np.minimum(rs, gs), bs)) / np.maximum(v, 1.0)
        top_response = peaks[0][2]
        out: list[CapCandidate] = []
        for x, y, resp, sig, base in peaks:
            if len(out) >= s.redness_candidates:
                break
            if mask[y, x]:
                continue
            half = int(np.clip(WINDOW_SIGMAS * sig, WINDOW_MIN, WINDOW_MAX))
            box = (max(0, x - half), max(0, y - half), min(ws, x + half + 1), min(hs, y + half + 1))
            x0, y0, x1, y1 = box
            loc = rho_b[y0:y1, x0:x1]
            cy, cx, rr0 = y - y0, x - x0, max(2, int(round(sig / 2)))
            near = loc[max(0, cy - rr0):cy + rr0 + 1, max(0, cx - rr0):cx + rr0 + 1]
            peak = float(near.max())
            ly, lx = np.unravel_index(int(np.argmax(near)), near.shape)
            seed = (max(0, cy - rr0) + int(ly), max(0, cx - rr0) + int(lx))
            comp, closed = None, False
            for level in (s.region_level, *[lv for lv in LEVELS if lv > s.region_level]):
                _n, lab = cv2.connectedComponents((loc >= base + level * (peak - base)).astype(np.uint8),
                                                  connectivity=8)
                if lab[seed] == 0:
                    break
                comp = lab == lab[seed]
                if not _touches_window(comp, box, (hs, ws)):
                    closed = True
                    break
            if comp is None:
                continue
            if not closed:  # never closes inside its window: a background-sized structure, keep a disc
                yy, xx = np.ogrid[y0 - y:y1 - y, x0 - x:x1 - x]
                comp = comp & (yy * yy + xx * xx <= (OPEN_DISC_SIGMAS * sig) ** 2)
                if not comp.any():
                    continue
            out.append(self._candidate(comp, box, (x, y), resp, sig, base, peak, closed, top_response,
                                       (small, v, sat, rho), (hs, ws)))
            mask[y0:y1, x0:x1][comp] = 255
        return out, rho_b, mask

    @staticmethod
    def _candidate(comp, box, peak_xy, resp, sig, base, peak, closed, top_response, maps,
                   shape) -> CapCandidate:
        small, v, sat_map, rho = maps  # half-res BGR, max channel, saturation, redness
        hs, ws = shape
        x0, y0, x1, y1 = box
        cu8 = comp.view(np.uint8)
        contours, _ = cv2.findContours(cu8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros(comp.shape, np.uint8)  # a highlight inside the ball is ball (features keep comp)
        cv2.drawContours(filled, contours, -1, 1, thickness=-1)
        padded = cv2.copyMakeBorder(filled | cu8, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        dt = cv2.distanceTransform(padded, cv2.DIST_L2, 3)[1:-1, 1:-1]
        r_in = float(dt.max())
        if r_in >= BALL_MIN_RADIUS:
            my, mx = np.nonzero(dt >= r_in - 0.5)
            cx, cy = float(mx.mean()) + x0, float(my.mean()) + y0
        else:
            cx, cy = float(peak_xy[0]), float(peak_xy[1])
        m = cv2.moments(cu8, binaryImage=True)
        area = float(m["m00"])
        border = min(cx, cy, ws - 1 - cx, hs - 1 - cy)
        touches = ((y0 == 0 and comp[0].any()) or (y1 == hs and comp[-1].any()) or
                   (x0 == 0 and comp[:, 0].any()) or (x1 == ws and comp[:, -1].any()))
        clipped = bool(touches and border <= r_in + 1.0)
        a = max(area, 1.0)
        mu20, mu02, mu11 = m["mu20"] / a, m["mu02"] / a, m["mu11"] / a
        mid, dev = (mu20 + mu02) / 2, math.hypot((mu20 - mu02) / 2, mu11)
        elongation = math.sqrt((mid + dev) / max(mid - dev, 1 / 12))
        theta = 0.5 * math.atan2(2 * mu11, mu20 - mu02)
        axis = (math.cos(theta), math.sin(theta))
        if axis[1] > 0:  # point up the image, like RedBlob.axis
            axis = (-axis[0], -axis[1])
        rr = max(1, int(round(r_in)))
        disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rr + 1, 2 * rr + 1))
        ring = cv2.subtract(cv2.dilate(cu8, disc), cu8)
        has_ring = cv2.countNonZero(ring) > 0
        sl = (slice(y0, y1), slice(x0, x1))
        vv, vr = v[sl], rho[sl]
        v_in = cv2.mean(vv, cu8)[0]
        sat = cv2.mean(sat_map[sl], cu8)[0]
        rho_in = cv2.mean(vr, cu8)[0]
        rho_ring = cv2.mean(vr, ring)[0] if has_ring else 0.0
        v_ring = cv2.mean(vv, ring)[0] if has_ring else v_in
        highlight = cv2.minMaxLoc(vv, mask=cv2.bitwise_or(cu8, ring))[1] - v_in
        b_in, g_in, red_in = cv2.mean(small[sl], cu8)[:3]
        hue = signed_hue(red_in, g_in, b_in)
        features = (resp, resp / max(top_response, 1e-3), 2 * sig, 2 * r_in, 4 * area,
                    area / (math.pi * r_in * r_in + 1e-6), elongation, rho_in, rho_in - rho_ring, v_in, sat,
                    v_ring - v_in, highlight, g_in - b_in, float(closed), hue, max(0.0, hue), max(0.0, -hue))
        outline = tuple((int(2 * (p[0][0] + x0) + 1), int(2 * (p[0][1] + y0) + 1))
                        for p in max(contours, key=len)) if contours else ()
        bx, by, bw, bh = cv2.boundingRect(cu8)
        bbox = (2 * (x0 + bx), 2 * (y0 + by), 2 * bw, 2 * bh)
        return CapCandidate((2 * cx + 0.5, 2 * cy + 0.5), (2 * peak_xy[0] + 0.5, 2 * peak_xy[1] + 0.5),
                            features, clipped, base, peak, (cx, cy), bbox, outline, axis)

    def same_structure(self, a: CapCandidate, b: CapCandidate, rho_b: np.ndarray) -> bool:
        """``a`` and ``b`` are one stick end: close and joined by a continuous red path (module docstring)."""
        s = self.settings
        if math.dist(a.point, b.point) > s.merge_reach_px:
            return False
        base = min(a.base, b.base)
        floor = base + s.merge_level * (min(a.top, b.top) - base)
        (xa, ya), (xb, yb) = a.half, b.half
        n = int(max(abs(xb - xa), abs(yb - ya))) + 2
        xs = np.clip(np.round(np.linspace(xa, xb, n)).astype(int), 0, rho_b.shape[1] - 1)
        ys = np.clip(np.round(np.linspace(ya, yb, n)).astype(int), 0, rho_b.shape[0] - 1)
        return bool(rho_b[ys, xs].min() >= floor)

    def detect(self, roi: np.ndarray) -> CapDetection:
        s = self.settings
        cands, rho_b, mask = self.candidates(roi)
        quality = self.verifier.score(np.array([c.features for c in cands])) if cands else np.zeros(0)
        radius = FEATURES.index("radius")
        keep = list(range(len(cands)))
        merged = []
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                if i in keep and j in keep and self.same_structure(cands[i], cands[j], rho_b):
                    wide = cands[i].features[radius] >= cands[j].features[radius]
                    if abs(quality[i] - quality[j]) > s.merge_score_margin:
                        wide = quality[i] > quality[j]
                    drop = j if wide else i
                    keep.remove(drop)
                    merged.append(drop)
        counts: Counter = Counter()
        counts["SAME_CAP"] += len(merged)
        h, w = roi.shape[:2]
        blobs, rejected = [], [self._blob(cands[k], float(quality[k]), "SAME_CAP") for k in merged]
        for k in keep:
            c = cands[k]
            x, y = c.point[0] / w, c.point[1] / h
            if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in s.ignore_regions):
                counts["IGNORED_REGION"] += 1
                rejected.append(self._blob(c, float(quality[k]), "IGNORED_REGION"))
                continue
            blobs.append(self._blob(c, float(quality[k]), None))
        blobs.sort(key=lambda b: -b.score)
        return CapDetection(tuple(blobs), tuple(rejected), counts, mask)

    @staticmethod
    def _blob(c: CapCandidate, quality: float, reason: str | None) -> RedBlob:
        f = dict(zip(FEATURES, c.features, strict=True))
        return RedBlob(c.point, f["area"], c.bbox, f["elongation"], c.axis, c.clipped, quality, reason=reason,
                       region_center=c.peak, outline=c.outline)


__all__ = ["DEFAULT_VERIFIER", "FEATURES", "CapCandidate", "CapDetection", "CapDetector", "CapVerifier",
           "redness", "signed_hue"]
