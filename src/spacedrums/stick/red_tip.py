"""Red-painted stick tips: HSV colour segmentation (a coloured MARKER condition, integrity I-7).

One BGR->HSV conversion per frame. Red wraps around hue 0, so every colour band is two ``inRange`` bands
(H in [0, hue_low_max] or [hue_high_min, 179]). Segmentation is a hysteresis on colour:

* **Seeds** (the paint core): the *core* hue band with the strong floors ``s_min`` / ``v_min``, opened with
  an ``open_px`` square so scattered seed pixels (skin, sensor noise) vanish. Hue is the separator that
  matters: glossy red paint sits at H ~ 179-1, while skin, lips, a paint run on the wooden shaft and the
  wood itself sit at H >= 5 (owner photo, 2026-10-16).
* **Growth** (edges, mild blur, shading): the band widened by ``hue_margin_weak`` with the weak floors,
  kept **only within ``grow_px`` of a seed**, so a face or hand behind a tip is never absorbed into it.
* **Highlights**: bright unsaturated pixels within ``grow_px`` of a seed connect the fragments a
  reflection cuts apart. They join a tip's shape only inside the convex hull of its paint, so a reflection
  restores a notched outline but the bright wall around a tip never adds a ring.

Each connected region (after a small elliptical closing; fragments closer than ``merge_px`` merge) is a
filled shape: an interior reflection counts as tip. A region must contain ``min_seed_px`` seeds and a
``min_seed_fraction`` share of seeds (lips, skin edges and paint runs alone fail: ``OFF_COLOUR``), and pass
the area and elongation limits.

**Cap point.** ``RedBlob.center`` is the centre of the painted cap, not of the whole red region: when the
region is longer than a head window (``head_length_factor`` x its width) and one end's red pixels are
clearly more saturated (relative difference of the mean saturation >= ``head_contrast``: 0.125 between the
photo's cap and paint run, < 0.05 between the two ends of a clean cap), the centre is the filled centroid
of that end's window. A cap with paint run down the shaft therefore reports the cap; a plain cap reports
its filled centroid. Blur re-detections keep the streak centroid (mid-exposure): choosing an end of a
streak would pick an arbitrary time in it.
``region_center`` is the whole region's centroid (diagnostics only).

:meth:`RedTipDetector.detect_weak` re-segments only a small window around a tracked tip with the weak
floors and no seed requirement, reusing the frame's HSV image (no second full-image pass). Motion blur
spreads a fast tip over a streak whose saturation drops below the strong floor exactly at strike speed.

Coordinates are ROI pixels in camera orientation (x right, y down); thresholds are OpenCV HSV units
(H 0-179, S and V 0-255). Every default is a candidate for the developer setup, not a calibration.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, replace

import cv2
import numpy as np

MAX_CANDIDATES = 8  # strong blobs kept for association per frame, best score first
MAX_REJECTED = 8  # rejected blobs kept for diagnostics (speckles are only counted)
MAX_PARTS = 32  # connected regions considered for merging, largest first
CAP_WINDOW_MAX_SHARE = 0.8  # a region shorter than head window / this share is one cap: plain centroid
DARK_OPEN = np.ones((2, 2), np.uint8)  # dark-paint pass: drops single-pixel noise of a dim frame ...
DARK_KERNEL = np.ones((3, 3), np.uint8)  # ... and closes the cap's highlight


@dataclass(frozen=True)
class RedTipSettings:
    """``product.stick_tip`` config block (``configs/red-tip.candidate.yaml``); all values are candidates."""

    # Segmentation (OpenCV HSV units; ROI pixels). See configs/red-tip.candidate.yaml for the evidence.
    hue_low_max: int = 4  # core band 1: H in [0, hue_low_max]
    hue_high_min: int = 170  # core band 2: H in [hue_high_min, 179]; 180 disables the band
    s_min: int = 145  # seed (strong) floors: a region needs seeds, a new track needs a seeded region
    v_min: int = 60
    s_min_weak: int = 70  # growth / weak floors: near seeds, and inside the gate of a tracked tip (blur)
    v_min_weak: int = 40
    hue_margin_weak: int = 3  # growth / weak band = core band widened by this many hue units each side
    open_px: int = 3  # seeds are opened with this square first: scattered skin / noise seeds vanish; < 2 off
    grow_px: int = 4  # growth and reflections stay within this distance of a seed; 0 = seeds only
    v_highlight: int = 190  # a reflection pixel: V >= v_highlight ...
    s_highlight_max: int = 80  # ... and S <= s_highlight_max; 0 disables reflection bridging
    close_px: int = 5  # elliptical closing kernel joining pixels split by the reflection; < 2 disables
    merge_px: float = 3.0  # fragments closer than this (bounding-box gap) merge; small, so two tips stay two
    min_area_px: float = 30.0  # filled-region area floor (sensor noise; a cap at 2 m is still ~150)
    max_area_px: float = 4000.0  # area ceiling (large red surfaces); a cap near the camera is ~1500
    max_elongation: float = 12.0  # std-dev ratio of the shape; blur streaks are elongated, red edges more so
    min_seed_px: int = 6  # seeds a region needs (sensor speckles in dark areas have one or two)
    min_seed_fraction: float = 0.45  # seed share of the filled region (lips / skin / paint runs fall below)
    head_length_factor: float = 1.2  # cap window length along the region axis, in region widths
    head_contrast: float = 0.08  # relative saturation difference between the two ends marking the cap end
    reference_area_px: float = 300.0  # blob score saturates at this area (ranking only)
    # Dark paint (opt-in; calibrate with scripts/tune_red_tips.py --calibrate-dark). In dim light at playing
    # distance the paint reads dark and shifted toward magenta (owner recording 2026-10-16 225435, exposure
    # -5: caps H -61..-9 signed, S 52-144, V 27-58), where the strong band finds 0.3 % of the cap pixels.
    # Pixels pass a wide band; whole blobs must then match the paint on average (hue, R-B, S, V).
    dark_paint: bool = False
    dark_hue_min: int = -60  # signed hue band of dark-paint pixels (0 = red; negative = toward magenta)
    dark_hue_max: int = 5
    dark_s_min: int = 60
    dark_v_min: int = 20
    dark_v_max: int = 110
    dark_rg_min: int = 6  # R - G of a pixel (BGR levels): the paint stays redder than green in the dark
    dark_hue_mean_max: float = -20.0  # blob means: hue (signed) ...
    dark_rb_mean_max: float = 4.0  # ... R - B (right stick -7 on average, left stick up to +4) ...
    dark_s_mean_min: float = 85.0  # ... saturation ...
    dark_v_mean_min: float = 32.0  # ... value
    dark_min_area_px: float = 15.0  # a cap at playing distance is ~90 px^2 (640 x 480); its core with a
    dark_max_area_px: float = 250.0  # highlight cut out can be as small as ~20
    dark_max_elongation: float = 3.5  # caps 1.1-3.4, other dark blobs median 2.6 (owner recording)
    dark_birth_surround: float = 0.65  # a dark blob starts a track only with a bright surround (caps 12-15
    # of 16 directions, hands / cloth at the frame bottom median 6); a bound track continues without it
    dark_birth_frames: int = 4  # consecutive frames a track born from a dark blob needs before it is used
    dark_confidence: float = 0.8  # evidence class of a dark-paint measurement (VALID downstream)
    ignore_regions: tuple[tuple[float, float, float, float], ...] = ()  # ROI-norm camera x0, y0, x1, y1
    # Detector: "redness" (local redness contrast + verifier + evidence tracker, stick/red_tip_caps.py and
    # stick/red_tip_evidence.py) or "colour" (the HSV segmentation above + RedTipTracker). Owner recordings
    # 2026-10-17 at playing distance: colour finds 0-11 % of 233 labelled caps, redness 73-94 % on held-out
    # frames (docs/perf/red-tip-stick-mode.md section 11).
    detector: str = "redness"
    redness_sigmas: tuple[float, ...] = (2.5, 4.5, 8.0)  # DoG scales, half-resolution px (cap radius ~1.4x2x)
    redness_threshold: float = 3.0  # DoG response floor of a candidate (BGR levels)
    redness_candidates: int = 12  # candidates kept per frame, strongest response first
    region_level: float = 0.25  # region = redness above surround + this x (peak - surround), raised to close
    merge_reach_px: float = 60.0  # two candidates joined by a red path within this distance are one stick end
    merge_level: float = 0.15  # ... the path's redness never drops below surround + this x (peak - surround)
    merge_score_margin: float = 0.4  # one stick end keeps its widest part unless the verifier differs more
    verifier: dict | None = None  # CapVerifier fields (features, mean, scale, weights, bias); None = built-in
    birth_quality: float = 0.35  # verifier quality a candidate needs to start a track
    instant_quality: float = 0.8  # ... to retake a slot on its first frame near where that slot last measured
    evidence_alpha: float = 0.3  # weight of the newest quality in a track's evidence (EMA)
    bind_evidence: float = 0.35  # evidence a track needs to take a free slot
    release_evidence: float = 0.12  # a bound track whose evidence falls below this frees its slot
    measure_evidence: float = 0.35  # a bound track is measured only with this much evidence ...
    measure_quality: float = 0.25  # ... and this quality in the current frame, else LOW_EVIDENCE
    challenge_margin: float = 0.15  # an unbound track with this much more evidence than the weaker bound one
    challenge_frames: int = 3  # ... for this many consecutive frames takes its slot
    clip_release_frames: int = 8  # a bound track cut by the border this many frames in a row frees its slot
    takeover_s: float = 0.07  # a slot coasting this long may be taken by a live track (fast reacquisition)
    identity_memory_s: float = 1.5  # one new tip takes the slot that measured near it within this time ...
    identity_memory_px: float = 120.0  # ... and distance; otherwise its side of the image decides
    still_s: float = 2.0  # a track that has not moved move_px for this long ...
    still_decay_s: float = 3.0  # ... loses slot rank linearly over this time (measurement is unaffected) ...
    still_floor: float = 0.3  # ... down to this factor (a static red object yields to a played stick)
    # Tracking (ROI pixels, seconds).
    max_tracks: int = 6  # internal tracks: both sticks plus red distractors
    birth_frames: int = 2  # consecutive strong observations confirming a new track
    gate_px: float = 28.0  # association gate around the predicted position ...
    gate_speed_gain: float = 1.0  # ... plus this times the predicted travel (covers a sudden stop) ...
    gate_growth_px_s: float = 600.0  # ... plus this per second missed beyond one frame ...
    gate_max_px: float = 140.0  # ... capped here
    max_predict_s: float = 0.1  # velocity extrapolation horizon for gating (never output)
    max_coast_s: float = 0.25  # a missed track keeps its identity this long, then it is deleted
    velocity_alpha: float = 0.6  # weight of the newest velocity sample (gating only)
    ambiguity_margin: float = 0.35  # swapped-assignment cost margin below which identities are ambiguous
    reset_after_ambiguity: bool = True  # restart both hands' stroke state when an ambiguous episode ends
    max_weak_frames: int = 4  # consecutive weak re-detections that still count as measured
    static_window_s: float = 4.0  # a bound track that never moved move_px for this long ...
    move_px: float = 20.0  # ... yields its slot to a track that moved this far within the last second
    observed_confidence: float = 0.9  # evidence classes, not probabilities: strong blob ...
    weak_confidence: float = 0.75  # ... and weak (blur) re-detection
    hand_assist: bool = False  # also run the MediaPipe hand model for birth labels / vetoes
    hand_reach_spans: float = 14.0  # hand assist: a new tip must lie within this many hand spans of a grip

    def __post_init__(self) -> None:
        regions = tuple(tuple(float(v) for v in r) for r in self.ignore_regions)
        object.__setattr__(self, "ignore_regions", regions)
        object.__setattr__(self, "redness_sigmas", tuple(float(v) for v in self.redness_sigmas))
        if self.detector not in ("redness", "colour"):
            raise ValueError("detector must be 'redness' or 'colour'")
        if not self.redness_sigmas or min(self.redness_sigmas) <= 0 or self.redness_candidates < 2:
            raise ValueError("redness_sigmas must be positive and redness_candidates >= 2")
        if not 0 < self.region_level < 0.7 or not 0 <= self.merge_level < 1 or self.merge_reach_px < 0:
            raise ValueError("region_level in (0, 0.7), merge_level in [0, 1), merge_reach_px >= 0 required")
        for name in ("birth_quality", "instant_quality", "evidence_alpha", "bind_evidence",
                     "release_evidence", "measure_evidence", "measure_quality", "challenge_margin",
                     "merge_score_margin", "still_floor"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must lie in [0, 1]")
        if self.evidence_alpha == 0 or self.release_evidence > self.bind_evidence:
            raise ValueError("evidence_alpha > 0 and release_evidence <= bind_evidence required")
        if self.challenge_frames < 1 or self.clip_release_frames < 1:
            raise ValueError("challenge_frames >= 1 and clip_release_frames >= 1 required")
        if min(self.takeover_s, self.identity_memory_s, self.identity_memory_px, self.still_s) < 0 or \
                self.still_decay_s <= 0:
            raise ValueError("takeover_s, identity_memory_*, still_s >= 0 and still_decay_s > 0 required")
        if not 0 <= self.hue_low_max <= 179 or not self.hue_low_max < self.hue_high_min <= 180:
            raise ValueError("require 0 <= hue_low_max < hue_high_min <= 180 (OpenCV hue units)")
        if self.hue_margin_weak < 0 or self.hue_low_max + self.hue_margin_weak >= \
                self.hue_high_min - self.hue_margin_weak:
            raise ValueError("hue_margin_weak must be >= 0 and keep the widened bands apart")
        for name in ("s_min", "v_min", "s_min_weak", "v_min_weak", "v_highlight", "s_highlight_max"):
            if not 0 <= getattr(self, name) <= 255:
                raise ValueError(f"{name} must lie in [0, 255]")
        if self.s_min_weak > self.s_min or self.v_min_weak > self.v_min:
            raise ValueError("weak floors must not exceed the strong floors")
        if min(self.close_px, self.open_px, self.grow_px) < 0 or self.merge_px < 0:
            raise ValueError("close_px, open_px, grow_px and merge_px must be >= 0")
        if not 0 < self.min_area_px < self.max_area_px:
            raise ValueError("require 0 < min_area_px < max_area_px")
        if self.max_elongation < 1 or self.reference_area_px <= 0:
            raise ValueError("max_elongation >= 1 and reference_area_px > 0 required")
        if self.min_seed_px < 1 or not 0 <= self.min_seed_fraction <= 1:
            raise ValueError("min_seed_px >= 1 and min_seed_fraction in [0, 1] required")
        if self.head_length_factor <= 0 or not 0 < self.head_contrast <= 1:
            raise ValueError("head_length_factor > 0 and head_contrast in (0, 1] required")
        for r in regions:
            if len(r) != 4 or not (0 <= r[0] < r[2] <= 1 and 0 <= r[1] < r[3] <= 1):
                raise ValueError("ignore_regions are [x0, y0, x1, y1] with x0 < x1 and y0 < y1 in [0, 1]")
        if self.max_tracks < 2 or self.birth_frames < 1 or self.max_weak_frames < 0:
            raise ValueError("max_tracks >= 2, birth_frames >= 1 and max_weak_frames >= 0 required")
        if self.gate_px <= 0 or self.gate_max_px < self.gate_px:
            raise ValueError("require 0 < gate_px <= gate_max_px")
        if min(self.gate_speed_gain, self.gate_growth_px_s, self.max_predict_s, self.max_coast_s) < 0:
            raise ValueError("gate gains, max_predict_s and max_coast_s must be >= 0")
        if not 0 < self.velocity_alpha <= 1 or self.ambiguity_margin < 0:
            raise ValueError("velocity_alpha in (0, 1] and ambiguity_margin >= 0 required")
        if self.static_window_s <= 0 or self.move_px <= 0:
            raise ValueError("static_window_s > 0 and move_px > 0 required")
        if not (0 < self.observed_confidence <= 1 and 0 < self.weak_confidence <= 1):
            raise ValueError("confidence classes must lie in (0, 1]")
        if self.hand_reach_spans <= 0:
            raise ValueError("hand_reach_spans must be > 0")
        if not -89 <= self.dark_hue_min < self.dark_hue_max <= 89:
            raise ValueError("require -89 <= dark_hue_min < dark_hue_max <= 89 (signed hue)")
        if not 0 <= self.dark_v_min < self.dark_v_max <= 255 or not 0 <= self.dark_s_min <= 255:
            raise ValueError("dark_s_min in [0, 255] and 0 <= dark_v_min < dark_v_max <= 255 required")
        if not 0 <= self.dark_rg_min <= 255 or not 0 < self.dark_min_area_px < self.dark_max_area_px:
            raise ValueError("dark_rg_min in [0, 255] and 0 < dark_min_area_px < dark_max_area_px required")
        if self.dark_max_elongation < 1 or not 0 <= self.dark_birth_surround <= 1:
            raise ValueError("dark_max_elongation >= 1 and dark_birth_surround in [0, 1] required")
        if self.dark_birth_frames < 1 or not 0 < self.dark_confidence <= 1:
            raise ValueError("dark_birth_frames >= 1 and dark_confidence in (0, 1] required")

    @classmethod
    def from_config(cls, cfg: dict) -> RedTipSettings:
        settings = cls(**dict((cfg.get("product") or {}).get("stick_tip") or {}))
        tracking = cfg.get("tracking")
        if tracking is not None and settings.observed_confidence < float(tracking["c_valid"]):
            raise ValueError("stick_tip.observed_confidence must reach tracking.c_valid or no tip strikes")
        return settings

    def as_dict(self) -> dict:
        d = asdict(self)
        d["ignore_regions"] = [list(r) for r in self.ignore_regions]
        d["redness_sigmas"] = list(self.redness_sigmas)
        return d


@dataclass(frozen=True)
class RedBlob:
    """One red region in ROI pixels. ``area`` is the filled area: a reflection hole counts."""

    center: tuple[float, float]  # the cap point (see the module docstring)
    area: float
    bbox: tuple[int, int, int, int]  # x, y, w, h
    elongation: float  # sqrt(major / minor second moment); 1 = round
    axis: tuple[float, float]  # unit principal axis, sign chosen to point up the image
    clipped: bool  # touches the ROI border: the centre is biased toward the visible part
    score: float  # ranking only: area relative to reference_area_px x seed share, halved when clipped
    weak: bool = False  # found with the weak floors inside a track gate
    reason: str | None = None  # reject reason; None = accepted
    region_center: tuple[float, float] | None = None  # centroid of the whole filled region (diagnostics)
    seed_fraction: float | None = None  # seed share of the filled region (None for weak re-detections)
    core_only: bool = False  # the region failed its seed share (blur): the blob is its saturated core alone
    dark: bool = False  # found by the dark-paint pass (dim light), not by the red seeds
    surround: float | None = None  # dark blobs: share of directions clearly brighter around it (context)
    colour: tuple[float, float, float, float] | None = None  # dark blobs: mean signed hue, S, V, R - B
    outline: tuple[tuple[int, int], ...] | None = None  # redness caps: the cap region's contour (HUD only)


@dataclass(frozen=True)
class RedDetection:
    hsv: np.ndarray  # the frame's HSV image (reused by weak re-detection)
    mask: np.ndarray  # seed (strong) mask before closing (diagnostics inset)
    blobs: tuple[RedBlob, ...]  # accepted strong blobs, best score first (<= MAX_CANDIDATES)
    rejected: tuple[RedBlob, ...]  # largest rejected blobs with reasons (diagnostics)
    reject_counts: Counter
    region: np.ndarray | None = None  # seeds + growth near seeds (diagnostics / tuning)
    cores: tuple[RedBlob, ...] = ()  # saturated cores of regions that failed their seed share (blur):
    # a bound track may recover on one (RedTipTracker.step); they never start a track


class RedTipDetector:
    """Stateless per-frame segmentation; ``settings`` is the only configuration."""

    def __init__(self, settings: RedTipSettings | None = None) -> None:
        self.settings = settings or RedTipSettings()
        k = self.settings.close_px
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)) if k >= 2 else None
        o = self.settings.open_px
        self.open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (o, o)) if o >= 2 else None
        g = self.settings.grow_px
        self.grow_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)) if g else None

    def mask(self, hsv: np.ndarray, s_min: int, v_min: int, margin: int = 0) -> np.ndarray:
        """Red pixels: the core hue band widened by ``margin`` hue units each side (H in
        [0, hue_low_max + margin] or [hue_high_min - margin, 179]) with S/V floors."""
        s = self.settings
        low, high = min(179, s.hue_low_max + margin), s.hue_high_min - margin
        out = cv2.inRange(hsv, (0, s_min, v_min), (low, 255, 255))
        if high <= 179:
            cv2.bitwise_or(out, cv2.inRange(hsv, (high, s_min, v_min), (179, 255, 255)), dst=out)
        return out

    def _ignore(self, mask: np.ndarray, offset: tuple[int, int], shape: tuple[int, int]) -> None:
        h, w = shape
        ox, oy = offset
        for x0, y0, x1, y1 in self.settings.ignore_regions:
            a, b = math.floor(x0 * w) - ox, math.floor(y0 * h) - oy
            c, d = math.ceil(x1 * w) - ox, math.ceil(y1 * h) - oy
            if c > 0 and d > 0 and a < mask.shape[1] and b < mask.shape[0]:
                mask[max(0, b):d, max(0, a):c] = 0

    def segment(self, hsv: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        """Seeds, region (seeds + growth near seeds) and reflection bridges of a full HSV ROI.

        Growth and reflections are computed only inside the seeds' padded bounding box."""
        s = self.settings
        h, w = hsv.shape[:2]
        seeds = self.mask(hsv, s.s_min, s.v_min)
        if self.open_kernel is not None:  # isolated seed pixels (skin, noise) never anchor growth
            seeds = cv2.morphologyEx(seeds, cv2.MORPH_OPEN, self.open_kernel)
        self._ignore(seeds, (0, 0), (h, w))
        region, bridge = seeds.copy(), None
        bx, by, bw, bh = cv2.boundingRect(seeds)
        if self.grow_kernel is None or bw == 0:
            return seeds, region, bridge
        pad = s.grow_px
        x0, y0, x1, y1 = max(0, bx - pad), max(0, by - pad), min(w, bx + bw + pad), min(h, by + bh + pad)
        win = hsv[y0:y1, x0:x1]
        near = cv2.dilate(seeds[y0:y1, x0:x1], self.grow_kernel)
        grow = cv2.bitwise_and(self.mask(win, s.s_min_weak, s.v_min_weak, s.hue_margin_weak), near)
        cv2.bitwise_or(region[y0:y1, x0:x1], grow, dst=region[y0:y1, x0:x1])
        self._ignore(region, (0, 0), (h, w))
        if s.s_highlight_max > 0:
            bridge = np.zeros_like(seeds)
            shine = cv2.inRange(win, (0, 0, s.v_highlight), (179, s.s_highlight_max, 255))
            bridge[y0:y1, x0:x1] = cv2.bitwise_and(shine, near)
            self._ignore(bridge, (0, 0), (h, w))
        return seeds, region, bridge

    def detect(self, roi_bgr: np.ndarray) -> RedDetection:
        hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
        seeds, region, bridge = self.segment(hsv)
        accepted, rejected, counts, cores = self._blobs(region, (0, 0), seeds.shape[:2], seeds=seeds,
                                                        bridge=bridge, sat=hsv[..., 1])
        if self.settings.dark_paint:
            dark = self._dark(roi_bgr, hsv, region, counts)
            accepted = sorted(accepted + dark, key=lambda b: (-b.score, b.center))
        if len(accepted) > MAX_CANDIDATES:
            counts["CANDIDATE_LIMIT"] += len(accepted) - MAX_CANDIDATES
        kept, shown = tuple(accepted[:MAX_CANDIDATES]), tuple(rejected[:MAX_REJECTED])
        return RedDetection(hsv, seeds, kept, shown, counts, region, tuple(cores))

    def dark_mask(self, roi_bgr: np.ndarray, hsv: np.ndarray) -> np.ndarray:
        """Pixels in the dark-paint band (before the per-blob averages); also used by the tuner."""
        s = self.settings
        lo, hi = s.dark_hue_min, s.dark_hue_max
        out = np.zeros(hsv.shape[:2], np.uint8)
        if hi >= 0:
            out = cv2.inRange(hsv, (max(0, lo), s.dark_s_min, s.dark_v_min), (hi, 255, s.dark_v_max))
        if lo < 0:
            top = 179 if hi >= 0 else 180 + hi
            low = cv2.inRange(hsv, (180 + lo, s.dark_s_min, s.dark_v_min), (top, 255, s.dark_v_max))
            cv2.bitwise_or(out, low, dst=out)
        _, g, r = cv2.split(roi_bgr)
        cv2.bitwise_and(out, cv2.compare(cv2.subtract(r, g), s.dark_rg_min, cv2.CMP_GE), dst=out)
        return out

    def _dark(self, roi_bgr, hsv, region, counts) -> list[RedBlob]:
        """Dark-paint blobs: a wide pixel band, small morphology, then per-blob colour averages and shape.
        Each blob also gets ``surround``: the share of 16 directions around it that are clearly brighter
        than the blob (a cap held up shows its shaft in one or two; hands, cloth and shadows in few)."""
        s = self.settings
        h, w = hsv.shape[:2]
        mask = self.dark_mask(roi_bgr, hsv)
        mask[cv2.dilate(region, DARK_KERNEL) > 0] = 0  # what the red seeds already found is not repeated
        self._ignore(mask, (0, 0), (h, w))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, DARK_OPEN)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, DARK_KERNEL)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        value = hsv[..., 2]
        hue_rot = cv2.LUT(np.ascontiguousarray(hsv[..., 0]), HUE_ROTATE)  # signed hue + 90: no wrap in means
        out = []
        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            polygon = cv2.contourArea(c)  # under-counts a blob by about its outline: a cheap speck filter
            thick = polygon > DARK_THIN_PX * max(bw, bh)
            if bw * bh < s.dark_min_area_px or polygon < DARK_SPECK_PX \
                    or (thick and polygon > DARK_REGION_FACTOR * s.dark_max_area_px):
                continue
            # Cheap colour check over the masked bounding box (the head is judged exactly below): most dark
            # regions of a dim frame (hair, shirt folds, shadows) are nowhere near the paint's averages.
            # A compact region is its own head, so the exact limits apply; a long one may hold a cap whose
            # colour the shaft dilutes, so it gets slack until its head is cut out.
            box = mask[y:y + bh, x:x + bw]
            compact = polygon <= s.dark_max_area_px and max(bw, bh) <= DARK_COMPACT_ASPECT * min(bw, bh)
            slack_h, slack_s = (0.0, 0.0) if compact else (DARK_PRE_HUE, DARK_PRE_S)
            region_hue = cv2.mean(hue_rot[y:y + bh, x:x + bw], box)[0] - 90
            _, region_sat, region_val, _ = cv2.mean(hsv[y:y + bh, x:x + bw], box)
            if region_hue > s.dark_hue_mean_max + slack_h or region_sat < s.dark_s_mean_min - slack_s \
                    or (compact and region_val < s.dark_v_mean_min):
                counts["DARK_REJECTED"] += 1
                continue
            inside = np.zeros((bh, bw), np.uint8)
            cv2.drawContours(inside, [c], -1, 1, -1, offset=(-x, -y))
            px = (inside > 0) & (box > 0)
            shape = _shape(px)
            if shape is None:
                continue
            if shape[0] > s.dark_max_area_px or shape[1] > s.dark_max_elongation:
                # The cap merged with the dark upper shaft: keep the wider end of the region (the head).
                px = _wide_end(px, shape)
                shape = _shape(px) if px is not None else None
                if shape is None or shape[0] > s.dark_max_area_px or shape[1] > s.dark_max_elongation:
                    counts["DARK_REJECTED"] += 1
                    continue
            area, elongation, axis, centre = shape
            if area < s.dark_min_area_px:
                continue
            sel = px.astype(np.uint8)
            hue = cv2.mean(hue_rot[y:y + bh, x:x + bw], sel)[0] - 90
            _, sat, val, _ = cv2.mean(hsv[y:y + bh, x:x + bw], sel)
            blue, _, red, _ = cv2.mean(roi_bgr[y:y + bh, x:x + bw], sel)
            if not (hue <= s.dark_hue_mean_max and red - blue <= s.dark_rb_mean_max
                    and sat >= s.dark_s_mean_min and val >= s.dark_v_mean_min):
                counts["DARK_REJECTED"] += 1
                continue
            centre = (x + centre[0], y + centre[1])
            clipped = x <= 0 or y <= 0 or x + bw >= w or y + bh >= h
            surround = _surround(value, centre, math.sqrt(area / math.pi), val)
            score = 0.5 * min(1.0, area / s.reference_area_px) * (0.5 if clipped else 1.0)  # below red blobs
            out.append(RedBlob(centre, float(area), (x, y, bw, bh), elongation, axis, bool(clipped),
                               float(score), region_center=centre, dark=True, surround=surround,
                               colour=(hue, sat, val, red - blue)))
        counts["DARK"] += len(out)
        return out

    def detect_weak(self, hsv: np.ndarray, center: tuple[float, float], radius: float) -> list[RedBlob]:
        """Weak-floor blobs whose centre lies within ``radius`` of ``center``, nearest first."""
        s = self.settings
        h, w = hsv.shape[:2]
        x0, y0 = max(0, int(center[0] - radius)), max(0, int(center[1] - radius))
        x1, y1 = min(w, int(center[0] + radius) + 2), min(h, int(center[1] + radius) + 2)
        if x1 - x0 < 3 or y1 - y0 < 3:
            return []
        mask = self.mask(hsv[y0:y1, x0:x1], s.s_min_weak, s.v_min_weak, s.hue_margin_weak)
        self._ignore(mask, (x0, y0), (h, w))
        blobs, _, _, _ = self._blobs(mask, (x0, y0), (h, w))
        near = [(math.dist(b.center, center), b) for b in blobs]
        return [b for d, b in sorted(near, key=lambda x: x[0]) if d <= radius]

    def _blobs(self, region, offset, shape, *, seeds=None, bridge=None, sat=None):
        """Blobs of ``region`` (offset into an ROI of ``shape``). ``seeds`` given = strong detection."""
        s = self.settings
        weak = seeds is None
        counts: Counter = Counter()
        closed = cv2.morphologyEx(region, cv2.MORPH_CLOSE, self.kernel) if self.kernel is not None else region
        conn = closed if bridge is None else cv2.bitwise_or(closed, bridge)
        contours, _ = cv2.findContours(conn, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        parts = []
        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            if bw * bh < s.min_area_px / 4:
                counts["TOO_SMALL"] += 1
                continue
            parts.append(([c], [x, y, x + bw, y + bh]))
        if len(parts) > MAX_PARTS:
            parts.sort(key=lambda p: -(p[1][2] - p[1][0]) * (p[1][3] - p[1][1]))
            counts["TOO_SMALL"] += len(parts) - MAX_PARTS
            parts = parts[:MAX_PARTS]
        accepted, rejected, cores = [], [], []
        for group, box in _merge(parts, s.merge_px):
            x0, y0, x1, y1 = box
            if (x1 - x0) * (y1 - y0) < s.min_area_px:  # the filled area cannot exceed the bounding box
                counts["TOO_SMALL"] += 1
                continue
            if seeds is not None and cv2.countNonZero(seeds[y0:y1, x0:x1]) < s.min_seed_px:
                counts["OFF_COLOUR"] += 1  # not even the bounding box holds enough paint core
                continue
            blob = self._shape_blob(group, box, conn, closed, seeds, bridge, offset, shape, region, sat)
            if blob is None or blob.area < s.min_area_px:
                counts["TOO_SMALL"] += 1
                continue
            reason = blob.reason
            if reason is not None:  # rejected on colour before its shape was built
                pass
            elif not weak and blob.seed_fraction < s.min_seed_fraction:
                reason = "OFF_COLOUR"
            elif blob.area > s.max_area_px:
                reason = "TOO_LARGE"
            elif blob.elongation > s.max_elongation:
                reason = "TOO_ELONGATED"
            if reason is None and blob.core_only:
                cores.append(blob)
                counts["CORE_ONLY"] += 1
            elif reason is None:
                accepted.append(blob)
            else:
                counts[reason] += 1
                rejected.append(replace(blob, reason=reason))
        accepted.sort(key=lambda b: (-b.score, b.center))
        rejected.sort(key=lambda b: -b.area)
        return accepted, rejected, counts, cores

    def _shape_blob(self, group, box, conn, closed, seeds, bridge, offset, shape, region=None,
                    sat=None) -> RedBlob | None:
        s = self.settings
        x0, y0, x1, y1 = box
        inside = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.drawContours(inside, group, -1, 1, -1, offset=(-x0, -y0))
        member = (inside > 0) & (conn[y0:y1, x0:x1] > 0)
        paint = (member & (closed[y0:y1, x0:x1] > 0)).astype(np.uint8)
        ox, oy = offset
        coloured_px = None if region is None else region[y0:y1, x0:x1] > 0
        core_only = False
        if seeds is not None:  # the filled shape contains the paint: a failing share of the paint is final
            n_paint = int(np.count_nonzero(paint))
            seed_px = member & (seeds[y0:y1, x0:x1] > 0)
            seeded = int(np.count_nonzero(seed_px))
            short = seeded < s.min_seed_px or seeded < s.min_seed_fraction * n_paint
            if n_paint >= s.min_area_px and short and seeded >= s.min_area_px:
                # Motion blur dilutes saturation, so growth can outweigh a real tip's seeds: the saturated
                # core alone is the blob then (skin and lips keep no core this large after the opening).
                core = seed_px.astype(np.uint8)
                paint = core if self.kernel is None else cv2.morphologyEx(core, cv2.MORPH_CLOSE, self.kernel)
                member, coloured_px, bridge, core_only = paint > 0, paint > 0, None, True
            elif n_paint >= s.min_area_px and short:
                ys, xs = np.nonzero(paint)
                c = (float(xs.mean()) + x0 + ox, float(ys.mean()) + y0 + oy)
                box_px = (x0 + ox, y0 + oy, x1 - x0, y1 - y0)
                return RedBlob(c, float(n_paint), box_px, 1.0, (0.0, -1.0), False, 0.0, reason="OFF_COLOUR",
                               region_center=c, seed_fraction=seeded / n_paint)
        contours, _ = cv2.findContours(paint, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        filled = np.zeros_like(paint)
        cv2.drawContours(filled, contours, -1, 1, -1)
        if bridge is not None:
            shine = member & (bridge[y0:y1, x0:x1] > 0) & (filled == 0)
            if shine.any():  # a reflection restores the outline only inside the paint's convex hull
                hull = np.zeros_like(paint)
                cv2.fillConvexPoly(hull, cv2.convexHull(np.vstack(contours)), 1)
                filled[shine & (hull > 0)] = 1
        m = cv2.moments(filled, binaryImage=True)
        if m["m00"] <= 0:
            return None
        area = float(m["m00"])
        cx, cy = m["m10"] / area, m["m01"] / area
        mu20, mu02, mu11 = m["mu20"] / area, m["mu02"] / area, m["mu11"] / area
        half, common = (mu20 + mu02) / 2, math.hypot((mu20 - mu02) / 2, mu11)
        major, minor = half + common, max(half - common, 1 / 12)  # 1/12: variance of a one-pixel width
        angle = 0.5 * math.atan2(2 * mu11, mu20 - mu02)
        axis = (math.cos(angle), math.sin(angle))
        if axis[1] > 0 or (axis[1] == 0 and axis[0] < 0):
            axis = (-axis[0], -axis[1])
        seed_fraction = None
        cap = (cx, cy)
        if seeds is not None:
            seed_in = (seeds[y0:y1, x0:x1] > 0) & (filled > 0)
            seed_fraction = float(np.count_nonzero(seed_in)) / area
            if sat is not None and not core_only:
                coloured = coloured_px & (filled > 0)  # reflections excluded
                cap = _cap_point(filled, coloured, sat[y0:y1, x0:x1], (cx, cy), axis, minor, s)
        h, w = shape
        clipped = x0 + ox <= 0 or y0 + oy <= 0 or x1 + ox >= w or y1 + oy >= h
        score = min(1.0, area / s.reference_area_px) * (1.0 if seed_fraction is None else seed_fraction)
        return RedBlob(
            center=(x0 + ox + cap[0], y0 + oy + cap[1]), area=area,
            bbox=(x0 + ox, y0 + oy, x1 - x0, y1 - y0),
            elongation=float(min(1e3, math.sqrt(max(major, minor) / minor))), axis=axis,
            clipped=bool(clipped), score=float(score * (0.5 if clipped else 1.0)), weak=seeds is None,
            region_center=(x0 + ox + cx, y0 + oy + cy), seed_fraction=seed_fraction, core_only=core_only,
        )


SURROUND_DIRECTIONS = np.stack([np.cos(np.linspace(0, 2 * np.pi, 16, endpoint=False)),
                                np.sin(np.linspace(0, 2 * np.pi, 16, endpoint=False))], axis=1)
SURROUND_STEPS = np.arange(5.0)  # radial samples from radius + 3 px outward


DARK_REGION_FACTOR = 6  # a dark region up to this many cap areas may still hold a cap at its end
DARK_THIN_PX = 12.0  # ... unless it is stick-like (mean width under this): a whole dark shaft with its cap
DARK_SPECK_PX = 6.0  # contour (polygon) area below which a dark region is noise, not a cap
DARK_PRE_HUE, DARK_PRE_S = 12.0, 20.0  # slack of the whole-region colour pre-check over the head limits
DARK_COMPACT_ASPECT = 2.5  # a region within this bounding-box aspect is checked as its own head
HUE_ROTATE = ((np.arange(256) + 90) % 180).astype(np.uint8)  # OpenCV hue -> signed hue + 90


def _shape(px: np.ndarray):
    """(area, elongation, unit axis pointing up, centroid) of a boolean mask, or None when empty."""
    m = cv2.moments(px.astype(np.uint8), binaryImage=True)
    area = m["m00"]
    if area <= 0:
        return None
    mu20, mu02, mu11 = m["mu20"] / area, m["mu02"] / area, m["mu11"] / area
    half, common = (mu20 + mu02) / 2, math.hypot((mu20 - mu02) / 2, mu11)
    major, minor = half + common, max(half - common, 1 / 12)
    angle = 0.5 * math.atan2(2 * mu11, mu20 - mu02)
    axis = (math.cos(angle), math.sin(angle))
    if axis[1] > 0 or (axis[1] == 0 and axis[0] < 0):
        axis = (-axis[0], -axis[1])
    return float(area), float(min(1e3, math.sqrt(max(major, minor) / minor))), axis, \
        (m["m10"] / area, m["m01"] / area)


def _wide_end(px: np.ndarray, shape) -> np.ndarray | None:
    """The head of a region that is a cap plus part of its shaft: the end window (1.3 x the region's 90th
    percentile width) whose mean width is larger; on a near tie the end higher in the image."""
    _, _, axis, centre = shape
    ys, xs = np.nonzero(px)
    proj = (xs - centre[0]) * axis[0] + (ys - centre[1]) * axis[1]  # grows toward the top of the image
    bins = np.floor(proj - proj.min()).astype(int)
    widths = np.bincount(bins)
    filled = np.sort(widths[widths > 0])
    window = 1.3 * float(filled[int(0.9 * (len(filled) - 1))])  # ~90th percentile width
    top, bottom = bins >= bins.max() - window, bins <= window
    w_top = float(np.mean(widths[np.unique(bins[top])]))
    w_bottom = float(np.mean(widths[np.unique(bins[bottom])]))
    keep = top if w_top >= 0.9 * w_bottom else bottom
    out = np.zeros_like(px)
    out[ys[keep], xs[keep]] = True
    return out if out.any() else None


def _surround(value: np.ndarray, centre, radius: float, blob_v: float, margin: float = 25.0) -> float:
    """Share of 16 directions whose ring just outside a blob (median of 5 radial samples) is brighter than
    the blob by ``margin`` V levels; samples outside the image count as not brighter."""
    h, w = value.shape
    r = radius + 3 + SURROUND_STEPS  # (5,)
    xs = np.rint(centre[0] + SURROUND_DIRECTIONS[:, :1] * r).astype(int)  # (16, 5)
    ys = np.rint(centre[1] + SURROUND_DIRECTIONS[:, 1:] * r).astype(int)
    inside = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    samples = np.where(inside, value[np.clip(ys, 0, h - 1), np.clip(xs, 0, w - 1)], 0).astype(float)
    return float(np.mean(np.median(samples, axis=1) > blob_v + margin))


def _cap_point(filled, coloured, sat, centroid, axis, minor, s: RedTipSettings) -> tuple[float, float]:
    """Centre of the painted cap inside a filled region (crop pixels); see the module docstring."""
    ys, xs = np.nonzero(filled)
    proj = (xs - centroid[0]) * axis[0] + (ys - centroid[1]) * axis[1]
    lo, hi = float(proj.min()), float(proj.max())
    window = s.head_length_factor * math.sqrt(12 * minor)  # 12 * variance = squared width of a band
    if window >= CAP_WINDOW_MAX_SHARE * (hi - lo + 1):
        return centroid
    red = coloured[ys, xs]
    sats = sat[ys, xs].astype(float)
    ends = (proj >= hi - window, proj <= lo + window)
    means = [float(sats[e & red].mean()) if (e & red).any() else 0.0 for e in ends]
    if abs(means[0] - means[1]) < s.head_contrast * max(means):
        return centroid
    end = ends[0] if means[0] > means[1] else ends[1]
    return float(xs[end].mean()), float(ys[end].mean())


def _merge(parts, merge_px):
    """Union of regions whose bounding boxes are within ``merge_px``: (contours, merged box) per group."""
    n = len(parts)
    if n == 0:
        return []
    boxes = np.array([box for _, box in parts], float)
    lo, hi = boxes[:, :2], boxes[:, 2:]
    gap = np.maximum(0.0, np.maximum(lo[:, None], lo[None]) - np.minimum(hi[:, None], hi[None]))  # (n, n, 2)
    near = np.hypot(gap[..., 0], gap[..., 1]) <= merge_px
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in zip(*np.nonzero(np.triu(near, 1)), strict=True):
        parent[find(int(i))] = find(int(j))
    groups: dict[int, tuple[list, list[int]]] = {}
    for i, (members, box) in enumerate(parts):
        root = find(i)
        if root not in groups:
            groups[root] = (list(members), list(box))
            continue
        g_members, g_box = groups[root]
        g_members.extend(members)
        g_box[0], g_box[1] = min(g_box[0], box[0]), min(g_box[1], box[1])
        g_box[2], g_box[3] = max(g_box[2], box[2]), max(g_box[3], box[3])
    return list(groups.values())


__all__ = ["MAX_CANDIDATES", "RedBlob", "RedDetection", "RedTipDetector", "RedTipSettings"]
