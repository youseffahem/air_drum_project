"""Wizard step accumulators (Phase 14, Tasks 14.2-14.5): pure consumers of per-frame summaries.

The runner (``spacedrums.app.calibrate``) turns every delivered frame into a :class:`WizardFrame`:
frame stamps, per-hand ``HandObservation``, the stick axis support measured by the Phase 03 analysis
(:class:`StickSample`), the per-hand ``TrackState`` of an Arm-A-only decision pipeline, and that
arm's committed strikes. A SYNTHETIC actor (``calib.synthetic``) produces the same records for tests.
No step touches a camera, clock or file, so each result is reproducible from its inputs.

Every threshold is a *candidate* from the wizard settings (phase "Decisions That Must Be
Experimentally Validated": coverage/distance thresholds, envelope percentiles and margins,
validation-strike count). Units: ROI-normalized, y down (ADR-0005); spans in ROI pixels; L in
ROI-height units (Phase 03 convention); times in seconds on the frames' clock.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from spacedrums.calib.fit import Box, percentile_box
from spacedrums.capture.roi import Roi
from spacedrums.contracts import CommittedStrike, FrameSample, HandId, HandObservation, TrackState
from spacedrums.hands.grip import GripSettings, grip_reference
from spacedrums.stick.search_region import vec_norm_to_px

HANDS = (HandId.LEFT, HandId.RIGHT)
SPOT_CHECK_LABEL = (
    "delivered-rate spot check from software t_capture stamps; NOT a native-FPS measurement "
    "(Task 02.4) and never written to camera_profile.native_fps_measured"
)


@dataclass(frozen=True)
class StickSample:
    """Axis support of one hand's stick this frame (from ``StickAnalysis.axis``); None = no axis."""

    support_units: float | None  # support length / roi.h (ROI-height units, Phase 03 convention)
    axis_confidence: float = 0.0


@dataclass(frozen=True)
class WizardFrame:
    sample: FrameSample
    hands: Mapping[HandId, HandObservation]
    sticks: Mapping[HandId, StickSample]
    tracks: Mapping[HandId, TrackState]
    commits: tuple[CommittedStrike, ...] = ()
    roi_mean_gray: float | None = None

    @property
    def t(self) -> float:
        return self.sample.t_capture


def _quantiles(values: Sequence[float]) -> tuple[float, float, float]:
    q25, q50, q75 = (float(v) for v in np.percentile(np.asarray(values, float), [25, 50, 75]))
    return q25, q50, q75


def hand_span_px(obs: HandObservation, roi: Roi, grip: GripSettings) -> float | None:
    """Task 03.3 hand span (larger of wrist-middle MCP / pinky-index MCP baselines) in ROI pixels."""
    if not obs.present:
        return None
    ref = grip_reference(obs, grip, roi_aspect=roi.aspect)
    if ref is None:
        return None
    return float(np.hypot(*vec_norm_to_px(ref.span_vec, roi)))


class _Collector:
    """A timed data window: ``feed`` frames until ``t >= t_start + window_s`` and enough frames."""

    def __init__(self, t_start: float, window_s: float, min_frames: int = 1) -> None:
        self.t_start, self.window_s, self.min_frames = float(t_start), float(window_s), int(min_frames)
        self.frames = 0
        self.t_last = float(t_start)

    def feed(self, frame: WizardFrame) -> None:
        self.frames += 1
        self.t_last = frame.t
        self._feed(frame)

    def _feed(self, frame: WizardFrame) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def done(self, t: float) -> bool:
        return t - self.t_start >= self.window_s and self.frames >= self.min_frames

    def progress(self, t: float) -> float:
        return min(1.0, max(0.0, (t - self.t_start) / self.window_s)) if self.window_s > 0 else 1.0


# ----------------------------------------------------------------------------- step 1


class CameraCheck(_Collector):
    """Profile confirmation, delivered-rate spot check and an exposure hint (Step 1)."""

    def __init__(self, t_start: float, expected: Mapping[str, Any], settings: Mapping[str, Any]) -> None:
        super().__init__(t_start, settings["camera_window_s"], settings["camera_min_frames"])
        self.expected, self.settings = expected, settings
        self.t: list[float] = []
        self.dropped = 0
        self.gray: list[float] = []
        self.mismatches: set[str] = set()

    def _feed(self, frame: WizardFrame) -> None:
        s = frame.sample
        self.t.append(s.t_capture)
        if self.frames > 1:
            self.dropped += int(s.dropped_since_last)
        if s.camera_profile_id != self.expected["camera_profile_id"]:
            self.mismatches.add(
                f"camera_profile_id {s.camera_profile_id!r} != config {self.expected['camera_profile_id']!r}"
            )
        if list(s.frame_size_px) != list(self.expected["resolution_px"]):
            self.mismatches.add(
                f"frame size {list(s.frame_size_px)} != resolution_px {self.expected['resolution_px']}"
            )
        if list(s.roi_px) != list(self.expected["roi_px"]):
            self.mismatches.add(f"frame roi_px {list(s.roi_px)} != config roi.px {self.expected['roi_px']}")
        if frame.roi_mean_gray is not None:
            self.gray.append(float(frame.roi_mean_gray))

    def result(self) -> dict[str, Any]:
        st = self.settings
        intervals = np.diff(np.asarray(self.t, float)) if len(self.t) > 1 else np.asarray([])
        fps = p95 = rel = None
        warnings: list[str] = []
        if len(intervals):
            median = float(np.median(intervals))
            fps = 1.0 / median if median > 0 else None
            p95 = float(np.percentile(intervals, 95))
            if fps is not None:
                rel = (fps - float(self.expected["requested_fps"])) / float(self.expected["requested_fps"])
                if abs(rel) > st["fps_tolerance"]:
                    warnings.append(
                        f"delivered rate {fps:.1f} FPS differs from the requested "
                        f"{self.expected['requested_fps']} FPS by {100 * rel:+.0f}% (check lighting/exposure)"
                    )
        gray = float(np.median(self.gray)) if self.gray else None
        advice = (
            "UNKNOWN"
            if gray is None
            else (
                "TOO_DARK" if gray < st["gray_dark"] else "TOO_BRIGHT" if gray > st["gray_bright"] else "OK"
            )
        )
        if advice == "TOO_DARK":
            warnings.append("ROI is dark: add light or raise exposure (camera profile section 5)")
        elif advice == "TOO_BRIGHT":
            warnings.append("ROI is very bright: lower exposure")
        if self.dropped:
            warnings.append(f"{self.dropped} frame(s) dropped during the check")
        mismatches = sorted(self.mismatches)
        return {
            "frames": self.frames,
            "window_s": self.t_last - self.t_start,
            "delivered_fps_median": fps,
            "interval_p95_s": p95,
            "dropped_total": self.dropped,
            "fps_relative_error": rel,
            "roi_mean_gray": gray,
            "exposure_advice": advice,
            "mismatches": mismatches,
            "warnings": warnings,
            "label": SPOT_CHECK_LABEL,
            "passed": not mismatches and not warnings,
            "acceptable": not mismatches,  # a profile mismatch must be fixed in the config, not accepted
        }


# ----------------------------------------------------------------------------- step 2


class PlayingArea(_Collector):
    """Both hands VALID across the stand-here band; distance advice from the hand span (Step 2)."""

    def __init__(self, t_start: float, settings: Mapping[str, Any], roi: Roi, grip: GripSettings) -> None:
        super().__init__(t_start, settings["playing_window_s"], 1)
        self.settings, self.roi, self.grip = settings, roi, grip
        self.band = tuple(settings["band"])
        self.n_sub = int(settings["n_subregions"])
        self.visits = [0] * self.n_sub
        self.both_valid = 0
        self.spans: dict[HandId, list[float]] = {h: [] for h in HANDS}

    def _feed(self, frame: WizardFrame) -> None:
        valid = {h: frame.tracks[h].status == "VALID" for h in HANDS}
        if all(valid.values()):
            self.both_valid += 1
        for h in HANDS:
            obs = frame.hands[h]
            if not obs.present:
                continue
            span = hand_span_px(obs, self.roi, self.grip)
            if span is not None:
                self.spans[h].append(span)
            wx, wy = obs.landmarks[0]  # wrist, ROI-normalized
            if valid[h] and self.band[0] <= wy <= self.band[1] and 0.0 <= wx <= 1.0:
                self.visits[min(int(wx * self.n_sub), self.n_sub - 1)] += 1

    def result(self) -> dict[str, Any]:
        st = self.settings
        frac = self.both_valid / self.frames if self.frames else None
        lo, hi = st["span_px_range"]
        spans = {
            str(h): {"median": float(np.median(v)) if v else None, "n": len(v)} for h, v in self.spans.items()
        }
        medians = [s["median"] for s in spans.values() if s["median"] is not None]
        if not medians:
            advice = "UNKNOWN"
        else:
            span = float(np.median(medians))
            advice = "MOVE_CLOSER" if span < lo else "MOVE_FARTHER" if span > hi else "OK"
        warnings: list[str] = []
        if frac is None or frac < st["min_both_valid_fraction"]:
            warnings.append(
                f"both hands VALID in {0 if frac is None else 100 * frac:.0f}% of frames "
                f"(need {100 * st['min_both_valid_fraction']:.0f}%): check lighting and stay inside the box"
            )
        uncovered = [k for k, v in enumerate(self.visits) if v < st["min_subregion_frames"]]
        if uncovered:
            names = ["left", "centre", "right"] if self.n_sub == 3 else [str(k) for k in range(self.n_sub)]
            warnings.append(
                "hands not tracked in the " + ", ".join(names[k] for k in uncovered) + " part of the band"
            )
        if advice == "MOVE_CLOSER":
            warnings.append(f"hands look small (span < {lo:g} px): step closer to the camera")
        elif advice == "MOVE_FARTHER":
            warnings.append(f"hands look large (span > {hi:g} px): step back from the camera")
        elif advice == "UNKNOWN":
            warnings.append("no hand span measured")
        width = 1.0 / self.n_sub
        return {
            "frames": self.frames,
            "both_valid_fraction": frac,
            "subregions": [
                {"x0": k * width, "x1": (k + 1) * width, "valid_frames": v} for k, v in enumerate(self.visits)
            ],
            "hand_span_px": spans,
            "distance_advice": advice,
            "passed": not warnings,
            "warnings": warnings,
            "acceptable": True,
        }


# ----------------------------------------------------------------------------- step 3


class StickPrior(_Collector):
    """Per-hand L_prior = median axis support over a still hold (Step 3; Phase 03 Open Question)."""

    def __init__(self, t_start: float, settings: Mapping[str, Any], default_l_prior: float) -> None:
        super().__init__(t_start, settings["stick_window_s"], 1)
        self.settings, self.default = settings, float(default_l_prior)
        self.values: dict[HandId, list[float]] = {h: [] for h in HANDS}
        reasons = ("not_valid", "no_axis", "low_axis_confidence", "moving")
        self.rejected = {h: dict.fromkeys(reasons, 0) for h in HANDS}

    def _feed(self, frame: WizardFrame) -> None:
        st = self.settings
        for h in HANDS:
            track, stick = frame.tracks[h], frame.sticks.get(h)
            if track.status != "VALID":
                self.rejected[h]["not_valid"] += 1
            elif stick is None or stick.support_units is None or stick.support_units <= 0:
                self.rejected[h]["no_axis"] += 1  # no axis, or an axis with no extent past the grip
            elif stick.axis_confidence < st["stick_min_axis_confidence"]:
                self.rejected[h]["low_axis_confidence"] += 1
            elif math.hypot(*track.tip_velocity) > st["stick_max_tip_speed"]:
                self.rejected[h]["moving"] += 1
            else:
                self.values[h].append(float(stick.support_units))

    def hand_result(self, h: HandId) -> dict[str, Any]:
        st = self.settings
        v = self.values[h]
        warnings: list[str] = []
        median = q25 = q75 = rel = None
        if v:
            q25, median, q75 = _quantiles(v)
            rel = (q75 - q25) / median if median > 0 else None
        lo, hi = st["l_prior_range"]
        if len(v) < st["stick_min_frames"]:
            warnings.append(
                f"only {len(v)} still frames with a confident axis (need {st['stick_min_frames']})"
            )
        if median is not None and not lo <= median <= hi:
            warnings.append(f"median support {median:.3f} outside the sanity range [{lo}, {hi}]")
        if rel is not None and rel > st["stick_max_rel_iqr"]:
            warnings.append(f"support unstable (IQR/median {rel:.2f} > {st['stick_max_rel_iqr']})")
        measured = not warnings
        if not measured:
            warnings.append(f"using the layout default L_prior {self.default:g}")
        return {
            "source": "MEASURED" if measured else "DEFAULT",
            "median": median,
            "q25": q25,
            "q75": q75,
            "rel_iqr": rel,
            "n_accepted": len(v),
            "n_rejected": dict(self.rejected[h]),
            "warnings": warnings,
        }

    def result(self) -> dict[str, Any]:
        per_hand = {str(h): self.hand_result(h) for h in HANDS}
        l_prior = {
            k: (r["median"] if r["source"] == "MEASURED" else self.default) for k, r in per_hand.items()
        }
        warnings = [f"{k}: {w}" for k, r in per_hand.items() for w in r["warnings"]]
        return {
            "units": "ROI_HEIGHT",
            "l_prior": l_prior,
            "default_l_prior": self.default,
            "per_hand": per_hand,
            "passed": all(r["source"] == "MEASURED" for r in per_hand.values()),
            "warnings": warnings,
            "acceptable": True,
        }


# ----------------------------------------------------------------------------- step 4


class ReachSweep(_Collector):
    """Reach envelope = percentile box of VALID tip positions during the guided sweep (Step 4)."""

    def __init__(self, t_start: float, settings: Mapping[str, Any]) -> None:
        super().__init__(t_start, settings["sweep_window_s"], 1)
        self.settings = settings
        self.points: list[tuple[float, float]] = []
        self.per_hand = {h: 0 for h in HANDS}

    def _feed(self, frame: WizardFrame) -> None:
        for h in HANDS:
            track = frame.tracks[h]
            if track.status == "VALID" and track.tip_filtered is not None:
                self.points.append((float(track.tip_filtered[0]), float(track.tip_filtered[1])))
                self.per_hand[h] += 1

    def envelope(self) -> dict[str, Any]:
        st = self.settings
        lo, hi = st["envelope_percentiles"]
        warnings: list[str] = []
        box: Box | None = None
        if len(self.points) < st["envelope_min_points"]:
            warnings.append(
                f"only {len(self.points)} tracked tip positions (need {st['envelope_min_points']}); "
                "the template layout is kept"
            )
        else:
            box = percentile_box(self.points, lo, hi)
            if box.width <= 0 or box.height <= 0:
                warnings.append("degenerate reach envelope; the template layout is kept")
                box = None
        return {
            "method": "PERCENTILE_BOX",
            "percentiles": [float(lo), float(hi)],
            "box": None if box is None else box.as_list(),
            "n_points": len(self.points),
            "points_per_hand": {str(h): n for h, n in self.per_hand.items()},
            "warnings": warnings,
        }


# ----------------------------------------------------------------------------- step 5


@dataclass(frozen=True)
class Cue:
    zone_id: str
    index: int  # strike index within the zone (0-based)
    t0: float
    t1: float


@dataclass
class ValidationSchedule:
    """Deterministic cue timetable: after ``lead_in_s``, ``strikes_per_zone`` contiguous windows of
    ``cue_period_s`` per zone, zones in layout order."""

    zone_ids: tuple[str, ...]
    t_start: float
    strikes_per_zone: int
    cue_period_s: float
    lead_in_s: float
    cues: list[Cue] = field(init=False)

    def __post_init__(self) -> None:
        t = self.t_start + self.lead_in_s
        self.cues = []
        for zone in self.zone_ids:
            for k in range(self.strikes_per_zone):
                self.cues.append(Cue(zone, k, t, t + self.cue_period_s))
                t += self.cue_period_s

    @property
    def t_end(self) -> float:
        return self.cues[-1].t1 if self.cues else self.t_start + self.lead_in_s

    def at(self, t: float) -> Cue | None:
        for cue in self.cues:
            if cue.t0 <= t < cue.t1:
                return cue
        return None


class ValidationStrikes(_Collector):
    """Cued strikes per zone under Arm A only; per-zone detections and flags (Step 5)."""

    def __init__(
        self,
        t_start: float,
        settings: Mapping[str, Any],
        zone_ids: Sequence[str],
        near_pairs: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self.schedule = ValidationSchedule(
            tuple(zone_ids),
            float(t_start),
            int(settings["strikes_per_zone"]),
            float(settings["cue_period_s"]),
            float(settings["validation_lead_in_s"]),
        )
        super().__init__(t_start, self.schedule.t_end - float(t_start), 1)
        self.settings = settings
        self.near = {z for pair in near_pairs for z in pair["zones"]}
        self.window_commits: dict[int, list[str]] = {i: [] for i in range(len(self.schedule.cues))}
        self.outside = 0

    def _feed(self, frame: WizardFrame) -> None:
        for commit in frame.commits:
            if commit.shadow or commit.arm != "A":
                continue  # the wizard pipeline runs A only; anything else is ignored by construction
            t = commit.t_impact_target
            for i, cue in enumerate(self.schedule.cues):
                if cue.t0 <= t < cue.t1:
                    self.window_commits[i].append(commit.zone_id)
                    break
            else:
                self.outside += 1

    def result(self) -> dict[str, Any]:
        st = self.settings
        n = self.schedule.strikes_per_zone
        per_zone = []
        flags: list[str] = []
        for zone in self.schedule.zone_ids:
            windows = [i for i, c in enumerate(self.schedule.cues) if c.zone_id == zone]
            hits = [self.window_commits[i] for i in windows]
            detected = sum(1 for h in hits if zone in h)
            wrong = sum(sum(1 for z in h if z != zone) for h in hits)
            extra = sum(max(0, h.count(zone) - 1) for h in hits)
            rate = detected / n if n else None
            zf = []
            if rate is not None and rate < st["min_detection_rate"]:
                zf.append("LOW_DETECTION")
            if n and wrong / n > st["max_cross_talk_rate"]:
                zf.append("CROSS_TALK")
            if extra:
                zf.append("DUPLICATES")
            if zone in self.near:
                zf.append("NEAR_NEIGHBOUR")
            flags += [f"{zone}: {f}" for f in zf]
            per_zone.append(
                {
                    "zone_id": zone,
                    "cued": n,
                    "detected": detected,
                    "detection_rate": rate,
                    "wrong_zone_commits": wrong,
                    "extra_commits": extra,
                    "flags": zf,
                }
            )
        if self.outside:
            flags.append(f"{self.outside} commit(s) outside every cue window")
        failing = [r for r in per_zone if {"LOW_DETECTION", "CROSS_TALK"} & set(r["flags"])]
        return {
            "arm": "A",
            "strikes_per_zone": n,
            "cue_period_s": self.schedule.cue_period_s,
            "per_zone": per_zone,
            "flags": flags,
            "passed": not failing,
            "warnings": flags,
            "acceptable": True,
        }


__all__ = [
    "HANDS",
    "SPOT_CHECK_LABEL",
    "CameraCheck",
    "Cue",
    "PlayingArea",
    "ReachSweep",
    "StickPrior",
    "StickSample",
    "ValidationSchedule",
    "ValidationStrikes",
    "WizardFrame",
    "hand_span_px",
]
