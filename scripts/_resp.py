"""Live-responsiveness diagnostics (2026-10-02): app-loop probe, paced live-path replay, analysis.

Development diagnostics only; every number is software-stamped on the machine that runs it.

* **replay** runs recorded frames through ``spacedrums.app.main.run`` with the recorded timestamps,
  so every decision is deterministic and identical inputs give identical records; stage times are
  real wall-clock durations of this run.
* **paced** pushes pre-decoded recorded frames through the *live* capture thread and bounded queue
  (``LiveFrameSource`` via the ``camera_factory`` seam) at their recorded frame intervals, in real
  time: real compute, real queue drops and real ``t_now``; only the pixels are recorded. Timing is
  not deterministic, so paced conditions are repeated.

The probe patches the loop the same way ``scripts/profile_pipeline.py`` does (``unittest.mock``) and
writes one row per delivered frame. Reset causes come from ``spacedrums.app.loss_diagnosis`` - the
same classifier the app summary uses. Nothing here interpolates, resamples or invents frames.
"""

from __future__ import annotations

import functools
import json
import math
import time
from collections import Counter, defaultdict
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import cv2
import numpy as np

from spacedrums import timing
from spacedrums.app import main as app
from spacedrums.app.audio_out import AudioOutput
from spacedrums.app.loss_diagnosis import LossDiagnosisMonitor, frame_quality
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.capture import LiveFrameSource, ReplayFrameSource
from spacedrums.capture.backend import NegotiatedMode, RawFrame
from spacedrums.commit import PerHandCommitPolicy
from spacedrums.config import load_config
from spacedrums.contracts import HandId
from spacedrums.geometry import GeometryEngine
from spacedrums.hands import HandLandmarker
from spacedrums.hands.identity import IdentityAssigner
from spacedrums.hands.landmarker import MediaPipeHandLandmarkerBackend
from spacedrums.prediction import RuleBasedAnticipator
from spacedrums.stick import StickSettings
from spacedrums.stick.segment import intensity_span
from spacedrums.stick.tip_geom import GeomTipEstimator
from spacedrums.tracking import CausalTracker, TrackerSettings

ROOT = Path(__file__).resolve().parents[1]
HANDS = (HandId.LEFT, HandId.RIGHT)
BUDGET_MS = 1000.0 / 30.0
NO_STRIKE_SEGMENTS = ("move_between_zones", "fake_swings", "stop_before_impact")
ARM_SOURCE = {"A": "REACTIVE", "B": "RULE"}

# stage name -> (owner, attribute); module-level functions are patched where they are looked up
TIMED = (
    (HandLandmarker, "detect", "hands_total"),
    (MediaPipeHandLandmarkerBackend, "detect", "hands_model"),
    (IdentityAssigner, "assign", "identity"),
    ("spacedrums.hands.landmarker", "grip_reference", "hands_grip"),
    (GeomTipEstimator, "estimate", "stick_total"),
    ("spacedrums.stick.estimator", "grip_reference", "stick_grip"),
    ("spacedrums.stick.estimator", "search_region", "stick_region"),
    ("spacedrums.stick.estimator", "segment_stick", "stick_segment"),
    ("spacedrums.stick.estimator", "fit_axis", "stick_axis"),
    ("spacedrums.stick.tip_geom", "geom_tip", "stick_tip"),
    ("spacedrums.stick.tip_geom", "record_from", "stick_tip"),
    (CausalTracker, "update", "tracking"),
    (GeometryEngine, "observe", "geometry"),
    (GeometryEngine, "intersect_prediction", "geometry"),
    (RuleBasedAnticipator, "predict", "rule"),
    (PerHandCommitPolicy, "step", "commit"),
    (AudioOutput, "play", "audio_schedule"),
)
POST_STAGES = ("render", "display")  # after the decision: attributed to the frame just finished


def ms(seconds: float) -> float:
    return 1000.0 * float(seconds)


def pct(values, *, scale: float = 1.0) -> dict[str, Any]:
    v = np.asarray([x for x in values if x is not None], dtype=float) * scale
    if v.size == 0:
        return {"n": 0}
    out: dict[str, Any] = {"n": int(v.size), "mean": float(v.mean())}
    for p in (50, 90, 95, 99):
        out[f"p{p}"] = float(np.percentile(v, p))
    out["max"] = float(v.max())
    return out


def budget(values_ms) -> dict[str, Any]:
    v = np.asarray([x for x in values_ms if x is not None], dtype=float)
    n = max(1, v.size)
    out = {"frame_budget_ms": BUDGET_MS}
    for label, limit in (("over_33_33ms", BUDGET_MS), ("over_40ms", 40.0), ("over_50ms", 50.0)):
        k = int((v > limit).sum())
        out[label] = {"frames": k, "percent": 100.0 * k / n}
    return out


# ----------------------------------------------------------------------------- inputs


def describe_input(path: Path) -> dict[str, Any]:
    """Kind, recorded condition and the files a replay needs (dev capture or recorded session)."""
    path = Path(path)
    meta_file = path / "session.json" if (path / "session.json").exists() else path / "meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    kind = "session" if meta_file.name == "session.json" else "dev-capture"
    exposure = None
    if kind == "dev-capture":
        exposure = (meta.get("exposure") or {}).get("value")
        capture_stats = meta.get("capture_stats")
    else:
        snap = path / "config.snapshot.yaml"
        if snap.exists():
            exposure = load_config(snap).data["camera_profile"]["exposure"]["value"]
        capture_stats = ((meta.get("source") or {}).get("capture_stats")) or None
    calibration = path / "calibration.calib.yaml"
    return {
        "name": path.name,
        "path": str(path),
        "kind": kind,
        "exposure": exposure,
        "capture_stats": capture_stats,
        "segments": meta.get("segments"),
        "calibration": str(calibration) if calibration.exists() else None,
    }


def load_images(path: Path, limit: int | None = None) -> tuple[list[np.ndarray], list[float]]:
    src = ReplayFrameSource(path, limit=limit)
    images = [src.read_image(s) for s in src]
    return images, [s.t_capture for s in src]


class PacedReplayCamera:
    """``CameraBackend`` that serves recorded frames at their recorded intervals, in real time.

    Frames go through the real ``LiveFrameSource`` (capture thread, stamps, dedupe, bounded queue).
    ``warmup`` black frames precede them because ``LiveFrameSource`` discards its warm-up frames.
    The capture thread does no colour conversion here, unlike DSHOW (a stated limitation).
    """

    def __init__(
        self, images: list[np.ndarray], t_capture: list[float], *, warmup: int = 10, fps: float = 30.0
    ):
        if not images:
            raise ValueError("no frames")
        h, w = images[0].shape[:2]
        black = np.zeros_like(images[0])
        self._images = [black] * warmup + list(images)
        t0 = float(t_capture[0])
        lead = [i / fps for i in range(warmup)]
        self._offsets = lead + [warmup / fps + (float(t) - t0) for t in t_capture]
        self.n_frames = len(self._images)  # finite source: LiveFrameSource stops at the end
        self._size = (w, h)
        self._i = 0
        self._t0: float | None = None

    def open(self, spec) -> NegotiatedMode:
        self._t0 = timing.now() + 0.05
        self._i = 0
        w, h = self._size
        return NegotiatedMode(
            backend="PACED-REPLAY",
            index=0,
            width=w,
            height=h,
            fps_prop=None,
            fourcc=None,
            fourcc_raw=None,
            auto_exposure_prop=None,
            exposure_prop=None,
            has_driver_timestamps=False,
            buffersize_prop=None,
        )

    def read(self) -> RawFrame | None:
        if self._t0 is None or self._i >= self.n_frames:
            return None
        due = self._t0 + self._offsets[self._i]
        while True:
            left = due - timing.now()
            if left <= 0:
                break
            timing.sleep_s(min(left, 0.002))
        image = self._images[self._i]
        self._i += 1
        return RawFrame(image=image, t_grab_return=timing.now(), t_driver_s=None)

    def apply_exposure(self, mode: str, value) -> dict[str, Any]:
        return {"mode": mode, "requested_value": value, "note": "recorded frames: exposure fixed at capture"}

    def close(self) -> None:
        self._t0 = None


# ----------------------------------------------------------------------------- report-only candidates

PATCHES = ("none", "identity-elapsed-gate")


@contextmanager
def harness_patch(name: str, *, fps: float = 30.0):
    """Report-only research variants applied inside this process; never deployment settings.

    ``identity-elapsed-gate``: the wrist-continuity gate (``hands.identity.gate_distance``, documented
    per frame) is scaled by the number of nominal frame periods since the hand's remembered wrist,
    so a dropped frame does not halve the continuity score of a hand that moved at the same speed.
    """
    if name == "none":
        yield
        return
    if name != "identity-elapsed-gate":
        raise ValueError(f"unknown harness patch {name!r}")
    from spacedrums.hands import identity as ident

    assign, score = ident.IdentityAssigner.assign, ident.IdentityAssigner._score

    def stamped_assign(self, candidates, frame_id, t_capture):
        self._resp_t = t_capture
        return assign(self, candidates, frame_id, t_capture)

    def scaled_score(self, hand, c, mem):
        if mem is None:
            return score(self, hand, c, mem)
        frames = max(1, int(math.floor((self._resp_t - mem.t_capture) * fps + 0.5)))
        if frames == 1:
            return score(self, hand, c, mem)
        s = self.settings
        p_label = (
            0.5 if c.raw_hand_id is None else (c.raw_score if c.raw_hand_id is hand else 1.0 - c.raw_score)
        )
        d = ident._dist(c.wrist, mem.wrist)
        p_temp = max(0.0, 1.0 - d / (s.gate_distance * frames))
        return s.w_label * p_label + (1.0 - s.w_label) * p_temp, p_label, p_temp, d

    with (
        patch.object(ident.IdentityAssigner, "assign", stamped_assign),
        patch.object(ident.IdentityAssigner, "_score", scaled_score),
    ):
        yield


# ----------------------------------------------------------------------------- probe


class Probe:
    """Collects one row per delivered frame from inside ``app.main.run``."""

    def __init__(self, cfg: dict[str, Any], *, paced: bool, detail: str = "full") -> None:
        self.cfg = cfg
        self.paced = paced
        self.detail = detail
        self.c_valid = float(cfg["tracking"]["c_valid"])
        self.max_gap_s = TrackerSettings.from_config(cfg).max_frame_gap_s
        self.stick = StickSettings.from_config(cfg)
        self.monitor = LossDiagnosisMonitor(max_gap_s=self.max_gap_s, keep_resets=100000)
        self.rows: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.last_row: dict[str, Any] | None = None
        self.queue_probe: dict[int, tuple[int | None, float]] = {}
        self.decode_s = 0.0
        self._last_start: float | None = None
        self._prev_t: float | None = None
        self._prev_detected: int | None = None
        self._last_bbox: dict[HandId, Any] = {h: None for h in HANDS}
        self._previous_status: dict[HandId, str | None] = {h: None for h in HANDS}

    # -- patches -----------------------------------------------------------------------------
    def _timed(self, owner, attr: str, name: str, stack: ExitStack) -> None:
        if isinstance(owner, str):
            import importlib

            owner = importlib.import_module(owner)
        original = getattr(owner, attr)
        probe = self

        @functools.wraps(original)
        def call(*args, **kwargs):
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                target = probe.last_row if name in POST_STAGES else probe.current
                if target is not None:
                    target["stage_s"][name] = target["stage_s"].get(name, 0.0) + time.perf_counter() - start

        stack.enter_context(patch.object(owner, attr, call))

    def install(self, stack: ExitStack, *, render: str) -> None:
        probe = self
        perception_call = app.Perception.__call__

        def perceive(instance, view):
            start = time.perf_counter()
            if probe._last_start is not None and probe.last_row is not None:
                probe.last_row["loop_ms"] = ms(start - probe._last_start)
            probe._last_start = start
            probe.current = {"t_start": start, "stage_s": {}, "view": view, "decode_s": probe.decode_s}
            observations = perception_call(instance, view)
            probe.current["stage_s"]["perception_total"] = time.perf_counter() - start
            probe.current["hands_result"] = instance.last_hands
            probe.current["analyses"] = dict(instance.last_analyses)
            return observations

        stack.enter_context(patch.object(app.Perception, "__call__", perceive))
        step = DecisionPipeline.step

        def decide(instance, sample, observations, **kwargs):
            if probe.current is None:  # SYNTHETIC source: no perception call this frame
                probe.current = {"t_start": None, "stage_s": {}, "decode_s": 0.0}
            probe.current["observations"] = observations
            start = time.perf_counter()
            try:
                return step(instance, sample, observations, **kwargs)
            finally:
                stage = probe.current["stage_s"]
                stage["decision_total"] = stage.get("decision_total", 0.0) + time.perf_counter() - start

        stack.enter_context(patch.object(DecisionPipeline, "step", decide))
        for owner, attr, name in TIMED:
            self._timed(owner, attr, name, stack)
        view = ReplayFrameSource.view

        def decode(instance, sample):
            start = time.perf_counter()
            out = view(instance, sample)
            probe.decode_s = time.perf_counter() - start
            return out

        stack.enter_context(patch.object(ReplayFrameSource, "view", decode))
        next_frame = LiveFrameSource.next_frame

        def delivered(instance, timeout=1.0):
            start = time.perf_counter()
            sample = next_frame(instance, timeout)
            if sample is not None:
                depth = getattr(instance._queue, "last_depth_at_get", None)
                probe.queue_probe[sample.frame_id] = (depth, time.perf_counter() - start)
            return sample

        stack.enter_context(patch.object(LiveFrameSource, "next_frame", delivered))
        if render != "none":
            self._timed(app, "render", "render", stack)
        if render == "headless":
            for name in ("namedWindow", "imshow", "destroyAllWindows"):
                stack.enter_context(patch.object(cv2, name, lambda *a, **k: None))
            stack.enter_context(patch.object(cv2, "pollKey", lambda: -1))
            stack.enter_context(patch.object(cv2, "waitKey", lambda *a: -1))
        elif render == "window":
            self._timed(cv2, "imshow", "display", stack)
            self._timed(cv2, "pollKey", "display", stack)

    # -- per frame ---------------------------------------------------------------------------
    def on_frame(self, sample, result, pipeline) -> bool:
        end = time.perf_counter()
        cur = self.current or {"t_start": None, "stage_s": {}, "decode_s": 0.0}
        self.current = None
        hands_result = cur.get("hands_result")
        analyses = cur.get("analyses") or {}
        identity = hands_result.identity if hands_result is not None else None
        observations = cur.get("observations") or {}
        dt = None if self._prev_t is None else sample.t_capture - self._prev_t
        self._prev_t = sample.t_capture
        row: dict[str, Any] = {
            "frame_id": sample.frame_id,
            "t_capture": sample.t_capture,
            "dt_ms": None if dt is None else ms(dt),
            "dropped_since_last": sample.dropped_since_last,
            "missing_frames": getattr(pipeline, "missing_frames", None),
            "processing_ms": None if cur["t_start"] is None else ms(end - cur["t_start"]),
            "decode_ms": ms(cur.get("decode_s") or 0.0),
            "stage_s": cur["stage_s"],
            "t_now_minus_capture_ms": ms(result.t_now - sample.t_capture),
        }
        if self.paced and sample.frame_id in self.queue_probe:
            depth, wait = self.queue_probe.pop(sample.frame_id)
            row["queue_depth"] = depth
            row["capture_wait_ms"] = ms(wait)
            if cur["t_start"] is not None:
                row["age_start_ms"] = ms(cur["t_start"] - sample.t_frame_available)
                row["capture_to_start_ms"] = ms(cur["t_start"] - sample.t_capture)
        if hands_result is not None:
            row["n_detected"] = hands_result.n_detected
            row["prev_n_detected"] = self._prev_detected
            self._prev_detected = hands_result.n_detected
            row["identity_events"] = [str(e.kind) for e in identity.events] if identity is not None else []
            row["ambiguous"] = bool(identity is not None and identity.ambiguous)
        gray = None
        view = cur.get("view")
        if view is not None and self.detail == "full":
            gray = cv2.cvtColor(view.roi, cv2.COLOR_BGR2GRAY)
            row["roi_mean"] = float(gray.mean())
        registry = pipeline.registry
        active = str(pipeline.active_arm)
        row["active_arm"] = active
        hands: dict[str, Any] = {}
        for h in HANDS:
            hf = result.hands[h]
            track = hf.track
            hand_obs, stick_obs = observations[h]
            assignment = identity.assignments.get(h) if identity is not None else None
            analysis = analyses.get(h)
            quality = frame_quality(
                hand_obs,
                stick_obs,
                c_valid=self.c_valid,
                assignment=assignment,
                ambiguous=bool(identity is not None and identity.ambiguous and assignment is not None),
                analysis=analysis,
                detail=hands_result is not None,
                last_seen_bbox=self._last_bbox[h],
            )
            if hand_obs.present:
                self._last_bbox[h] = hand_obs.bbox
            diagnosis = self.monitor.observe(
                quality, track, dt_s=dt, dropped_since_last=sample.dropped_since_last
            )
            status = str(track.status)
            previous = self._previous_status[h]
            self._previous_status[h] = status
            tip = track.tip_filtered
            seg = getattr(analysis, "segment", None) if analysis is not None else None
            entry: dict[str, Any] = {
                "present": bool(hand_obs.present),
                "handedness": hand_obs.handedness_score,
                "wrist": list(hand_obs.landmarks[0]) if hand_obs.present else None,
                "bbox": list(hand_obs.bbox) if hand_obs.present else None,
                "label": None,
                "raw_score": None,
                "p_label": None if assignment is None else assignment.p_label,
                "p_temporal": None if assignment is None else assignment.p_temporal,
                "stick": quality.stick_present,
                "axis": quality.axis_found,
                "axis_conf": float(stick_obs.axis_confidence) if quality.stick_present else None,
                "tip_conf": quality.tip_confidence,
                "tip_raw": list(stick_obs.tip) if quality.stick_present else None,
                "region": bool(analysis is not None and getattr(analysis, "region", None) is not None),
                "region_clip": region_clip(getattr(analysis, "region", None)),
                "grip_baseline": grip_baseline(analysis),
                "edge_px": None if seg is None else seg.n_edge_px,
                "components": None
                if seg is None
                else dict(Counter(c.reject_reason or "kept" for c in seg.components)),
                "contrast_gain": None if seg is None else float(getattr(seg, "contrast_gain", 1.0)),
                "limiting": None if quality.limiting is None else str(quality.limiting),
                "status": status,
                "reset_reason": None if track.reset_reason is None else str(track.reset_reason),
                "reset_cause": None if diagnosis is None else str(diagnosis.cause),
                "reacquired": previous in ("INVALID", "STALE") and status == "VALID",
                "tip": None if tip is None else list(tip),
                "inside": [] if tip is None else [z.zone_id for z in registry if z.shape.contains(tip)],
                "candidates": [
                    {"id": c.candidate_id, "zone": c.zone_id, "source": str(c.source)} for c in hf.candidates
                ],
                "decisions": [
                    {
                        "arm": t["arm"],
                        "id": t["candidate_id"],
                        "zone": t["zone_id"],
                        "decision": t["decision"],
                    }
                    for t in hf.decision_traces
                ],
                "commits": [
                    {
                        "arm": str(c.arm),
                        "zone": c.zone_id,
                        "shadow": c.shadow,
                        "t_commit": c.t_commit,
                        "strike_id": c.strike_id,
                    }
                    for c in hf.commits
                ],
                "audio": [
                    {"t_audio_scheduled": e.t_audio_scheduled, "strike_id": e.strike_id} for e in hf.audio
                ],
            }
            if hands_result is not None and assignment is not None:
                det = hands_result.detections[assignment.candidate.index]
                entry["label"], entry["raw_score"] = det.label, float(det.score)
            if gray is not None and analysis is not None and getattr(analysis, "region", None) is not None:
                entry["region_range"] = region_range(gray, analysis.region, self.stick.segment.blur_ksize)
            hands[str(h)] = entry
        row["hands"] = hands
        self.rows.append(row)
        self.last_row = row
        return True


def _polygon_area(points) -> float:
    p = np.asarray(points, dtype=float).reshape(-1, 2)
    if p.shape[0] < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def region_clip(region) -> float | None:
    """Fraction of the hand-anchored search rectangle cut away by the ROI border (0 = none, 1 = all);
    None without a region. Stick pixels in the cut part are invisible to the segmentation."""
    if region is None:
        return None
    full = _polygon_area(region.corners_px)
    if full <= 0.0:
        return None
    return max(0.0, min(1.0, 1.0 - _polygon_area(region.polygon_px) / full))


def grip_baseline(analysis) -> float | None:
    """Knuckle-row direction baseline (ROI-norm) of the frame's grip reference; shorter than
    ``hands.grip.min_direction_span`` means no grip direction (``GRIP_DEGENERATE``)."""
    grip = getattr(analysis, "grip", None) if analysis is not None else None
    return None if grip is None else float(grip.baseline_len)


def region_range(gray: np.ndarray, region, blur_ksize: int) -> float | None:
    """p98 - p2 of the (blurred) grayscale search region: the contrast the edge detector sees
    (``stick.segment.intensity_span``, the definition the adaptive thresholds use)."""
    x0, y0, x1, y1 = region.bbox_px
    if x1 <= x0 or y1 <= y0:
        return None
    crop = gray[y0:y1, x0:x1]
    if blur_ksize > 1:
        crop = cv2.GaussianBlur(crop, (blur_ksize, blur_ksize), 0)
    values = crop[region.mask[y0:y1, x0:x1]]
    if values.size == 0:
        return None
    return intensity_span(values)


# ----------------------------------------------------------------------------- analysis

EXCLUSIVE = {
    "hands_pre_post": ("hands_total", ("hands_model", "identity", "hands_grip")),
    "stick_other": (
        "stick_total",
        ("stick_grip", "stick_region", "stick_segment", "stick_axis", "stick_tip"),
    ),
    "perception_other": ("perception_total", ("hands_total", "stick_total")),
    "decision_other": ("decision_total", ("tracking", "geometry", "rule", "commit", "audio_schedule")),
}
STAGE_ORDER = (
    "capture_wait",
    "decode",
    "hands_pre_post",
    "hands_model",
    "identity",
    "hands_grip",
    "hands_total",
    "stick_grip",
    "stick_region",
    "stick_segment",
    "stick_axis",
    "stick_tip",
    "stick_other",
    "stick_total",
    "perception_other",
    "perception_total",
    "tracking",
    "geometry",
    "rule",
    "commit",
    "audio_schedule",
    "decision_other",
    "decision_total",
    "render",
    "display",
)
LOSS_RESETS = ("GAP_EXCEEDED", "LOW_CONFIDENCE", "STALE")


def stage_ms(row: dict[str, Any]) -> dict[str, float]:
    s = {k: ms(v) for k, v in row.get("stage_s", {}).items()}
    for name, (parent, children) in EXCLUSIVE.items():
        if parent in s:
            s[name] = max(0.0, s[parent] - sum(s.get(c, 0.0) for c in children))
    if row.get("capture_wait_ms") is not None:
        s["capture_wait"] = row["capture_wait_ms"]
    if row.get("decode_ms"):
        s["decode"] = row["decode_ms"]
    return s


def finalise_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k != "stage_s"}
    out["stage_ms"] = stage_ms(row)
    if out.get("processing_ms") is not None:
        extra = out["stage_ms"].get("render", 0.0) + out["stage_ms"].get("display", 0.0)
        out["frame_work_ms"] = out["processing_ms"] + extra
    return out


def category(entry: dict[str, Any], active: str) -> str:
    """A no hand, B hand but no stick, C stick but track not VALID, D VALID but no candidate,
    E sounding-arm candidate not committed, F sounding-arm commit (precedence F > E > A-D)."""
    if any(c["arm"] == active and not c["shadow"] for c in entry["commits"]):
        return "F"
    if any(c["source"] == ARM_SOURCE.get(active) for c in entry["candidates"]):
        return "E"
    if not entry["present"]:
        return "A"
    if not entry["stick"]:
        return "B"
    if entry["status"] != "VALID":
        return "C"
    return "D"


def entry_outcomes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Every observed zone entry of the sounding arm (its candidates) and what the commit stage did."""
    outcomes: Counter = Counter()
    status_causes: Counter = Counter()
    for row in rows:
        active = row.get("active_arm", "A")
        source = ARM_SOURCE.get(active)
        for e in row["hands"].values():
            for c in e["candidates"]:
                if c["source"] != source:
                    continue
                decision = next(
                    (d["decision"] for d in e["decisions"] if d["arm"] == active and d["id"] == c["id"]),
                    "NO_TRACE",
                )
                outcomes[decision] += 1
                if decision == "REJECT_STATUS":
                    status_causes[e["limiting"] or f"status {e['status']}"] += 1
    total = sum(outcomes.values())
    rejected = total - outcomes.get("COMMITTED", 0)
    return {
        "entries": total,
        "committed": outcomes.get("COMMITTED", 0),
        "discarded": rejected,
        "discarded_percent": 100.0 * rejected / total if total else None,
        "by_decision": dict(outcomes.most_common()),
        "reject_status_by_limiting_factor": dict(status_causes.most_common()),
    }


def _over(values: list[float], limits=(0.25, 0.5, 1.0)) -> dict[str, int]:
    return {f"over_{t}s": sum(d > t for d in values) for t in limits}


def stretches(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Unresponsive stretches: maximal non-VALID runs between two VALID frames of the same hand,
    split by whether the hand was detected in at least half of the stretch's frames."""
    out: dict[str, Any] = {}
    for h in ("LEFT", "RIGHT"):
        runs: list[tuple[float, bool]] = []
        last_valid_t: float | None = None
        run_frames = run_present = 0
        for row in rows:
            e = row["hands"][h]
            if e["status"] == "VALID":
                if last_valid_t is not None and run_frames:
                    runs.append((row["t_capture"] - last_valid_t, run_present * 2 >= run_frames))
                last_valid_t, run_frames, run_present = row["t_capture"], 0, 0
            elif last_valid_t is not None:
                run_frames += 1
                run_present += int(e["present"])
        visible = [d for d, v in runs if v]
        hidden = [d for d, v in runs if not v]
        out[h] = {
            "hand_visible": {**pct(visible, scale=1000.0), **_over(visible)},
            "hand_absent": {**pct(hidden, scale=1000.0), **_over(hidden)},
        }
    return out


def wrist_speeds(rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float]]:
    """(hand entry, wrist speed in ROI-norm/s) for hands present in two consecutive delivered frames."""
    out = []
    for prev, row in zip(rows, rows[1:], strict=False):
        dt = row["t_capture"] - prev["t_capture"]
        if dt <= 0:
            continue
        for h in ("LEFT", "RIGHT"):
            a, b = prev["hands"][h], row["hands"][h]
            if a["present"] and b["present"]:
                out.append((b, math.hypot(b["wrist"][0] - a["wrist"][0], b["wrist"][1] - a["wrist"][1]) / dt))
    return out


def speed_table(runs: list[list[dict[str, Any]]], bins: tuple[float, float] | None = None) -> dict[str, Any]:
    pairs = [p for rows in runs for p in wrist_speeds(rows)]
    if not pairs:
        return {"n": 0}
    speeds = np.asarray([v for _, v in pairs])
    if bins is None:
        bins = tuple(float(x) for x in np.percentile(speeds, [100 / 3, 200 / 3]))
    table: dict[str, Any] = {
        "bins_roi_per_s": list(bins),
        "source": "wrist landmark speed between consecutive delivered frames",
    }
    for label, lo, hi in (("slow", -1.0, bins[0]), ("normal", bins[0], bins[1]), ("fast", bins[1], math.inf)):
        sel = [(e, v) for e, v in pairs if lo <= v < hi]
        entries = [e for e, _ in sel]
        sticks = [e for e in entries if e["stick"]]
        table[label] = {
            "hand_frames": len(entries),
            "median_speed": float(np.median([v for _, v in sel])) if sel else None,
            "axis_found_percent": 100.0 * sum(e["axis"] for e in sticks) / len(sticks) if sticks else None,
            "tip_valid_level_percent": (
                100.0 * sum(e["limiting"] is None for e in sticks) / len(sticks) if sticks else None
            ),
            "status_valid_percent": (
                100.0 * sum(e["status"] == "VALID" for e in entries) / len(entries) if entries else None
            ),
            "limiting": dict(Counter(e["limiting"] for e in entries if e["limiting"]).most_common()),
        }
    return table


def summarise(
    rows: list[dict[str, Any]],
    *,
    meta: dict[str, Any],
    monitor: dict[str, Any] | None = None,
    app_summary: dict[str, Any] | None = None,
    speed_bins=None,
) -> dict[str, Any]:
    if not rows:
        return {"meta": meta, "frames": 0}
    span = rows[-1]["t_capture"] - rows[0]["t_capture"]
    minutes = span / 60.0 if span > 0 else None
    order = {k: i for i, k in enumerate(STAGE_ORDER)}
    stages = sorted({k for r in rows for k in r["stage_ms"]}, key=lambda k: (order.get(k, len(order)), k))
    processing = [r.get("processing_ms") for r in rows]
    work = [r.get("frame_work_ms") for r in rows]
    by_prev: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("prev_n_detected") is not None and "hands_model" in r["stage_ms"]:
            by_prev[str(r["prev_n_detected"])].append(r["stage_ms"]["hands_model"])
    hand_frames = [(h, e, r.get("active_arm", "A")) for r in rows for h, e in r["hands"].items()]
    categories = Counter(category(e, arm) for _, e, arm in hand_frames)
    reacq = sum(e["reacquired"] for _, e, _ in hand_frames)
    resets = [e["reset_reason"] for _, e, _ in hand_frames if e["reset_reason"] in LOSS_RESETS]
    status = {h: dict(Counter(r["hands"][h]["status"] for r in rows)) for h in ("LEFT", "RIGHT")}
    sticks = [e for _, e, _ in hand_frames if e["stick"]]
    commits = [
        (r, h, c)
        for r in rows
        for h, e in r["hands"].items()
        for c in e["commits"]
        if c["arm"] == r.get("active_arm") and not c["shadow"]
    ]
    audio_delay = [
        a["t_audio_scheduled"] - c["t_commit"]
        for r in rows
        for e in r["hands"].values()
        for c, a in zip([c for c in e["commits"] if not c["shadow"]], e["audio"], strict=False)
    ]
    drops = sum(r["dropped_since_last"] for r in rows)
    both = sum(r["hands"]["LEFT"]["present"] and r["hands"]["RIGHT"]["present"] for r in rows)
    out: dict[str, Any] = {
        "meta": meta,
        "frames": len(rows),
        "span_s": span,
        "delivered_fps": (len(rows) - 1) / span if span > 0 else None,
        "dropped": drops,
        "dropped_percent_of_offered": 100.0 * drops / (drops + len(rows)),
        "stages_ms": {k: pct([r["stage_ms"].get(k, 0.0) for r in rows]) for k in stages},
        "processing_ms": {**pct(processing), **budget(processing)},
        "frame_work_ms": {**pct(work), **budget(work)},
        "loop_ms": pct([r.get("loop_ms") for r in rows]),
        "decision_age_ms": pct([r.get("t_now_minus_capture_ms") for r in rows]),
        "hands_model_ms_by_previous_hands_detected": {k: pct(v) for k, v in sorted(by_prev.items())},
        "hand_presence": {
            **{h: sum(r["hands"][h]["present"] for r in rows) / len(rows) for h in ("LEFT", "RIGHT")},
            "both": both / len(rows),
        },
        "status_frames": status,
        "valid_fraction": {h: status[h].get("VALID", 0) / len(rows) for h in status},
        "axis_found_percent": 100.0 * sum(e["axis"] for e in sticks) / len(sticks) if sticks else None,
        "tip_valid_level_percent": (
            100.0 * sum(e["limiting"] is None for e in sticks) / len(sticks) if sticks else None
        ),
        "categories": {
            k: {
                "hand_frames": categories.get(k, 0),
                "percent": 100.0 * categories.get(k, 0) / len(hand_frames),
            }
            for k in "ABCDEF"
        },
        "entries": entry_outcomes(rows),
        "commits": {
            "total": len(commits),
            "by_hand_zone": dict(Counter(f"{h}:{c['zone']}" for _, h, c in commits).most_common()),
        },
        "reacquisitions": reacq,
        "reacquisitions_per_min": reacq / minutes if minutes else None,
        "resets": dict(Counter(resets)),
        "resets_per_min": len(resets) / minutes if minutes else None,
        "non_valid_limiting": dict(
            Counter(
                e["limiting"] for _, e, _ in hand_frames if e["status"] != "VALID" and e["limiting"]
            ).most_common()
        ),
        "stretches_ms": stretches(rows),
        "speed": speed_table([rows], speed_bins),
        "identity_events": dict(Counter(k for r in rows for k in r.get("identity_events", [])).most_common()),
        "ambiguous_frames": sum(bool(r.get("ambiguous")) for r in rows),
        "audio_scheduled_minus_commit_ms": pct(audio_delay, scale=1000.0),
        "roi_mean": pct([r.get("roi_mean") for r in rows]),
        "region_range": pct([e.get("region_range") for e in sticks]),
        "contrast_gain_applied_percent": (
            100.0 * sum((e.get("contrast_gain") or 1.0) > 1.0 for e in sticks) / len(sticks)
            if sticks
            else None
        ),
    }
    depths = [r.get("queue_depth") for r in rows if r.get("queue_depth") is not None]
    if depths:
        out["queue"] = {
            "depth_at_get": {str(k): v for k, v in sorted(Counter(depths).items())},
            "stale_deliveries_percent": 100.0 * sum(d >= 2 for d in depths) / len(depths),
            "frame_available_to_start_ms": pct([r.get("age_start_ms") for r in rows]),
            "capture_to_start_ms": pct([r.get("capture_to_start_ms") for r in rows]),
            "capture_wait_ms": pct([r.get("capture_wait_ms") for r in rows]),
        }
    segments = meta.get("segments")
    if segments:
        table = []
        for seg in segments:
            seg_rows = [r for r in rows if seg["t_start"] <= r["t_capture"] < seg["t_end"]]
            inside = [(r, h, c) for r, h, c in commits if seg["t_start"] <= r["t_capture"] < seg["t_end"]]
            entries = entry_outcomes(seg_rows)
            table.append(
                {
                    "segment": seg["segment_id"],
                    "instruction": seg["instruction"],
                    "frames": len(seg_rows),
                    "commits": len(inside),
                    "by_hand_zone": dict(Counter(f"{h}:{c['zone']}" for _, h, c in inside).most_common()),
                    "entries": entries["entries"],
                    "discarded": entries["discarded"],
                }
            )
        out["segments"] = table
        out["no_strike_segment_commits"] = sum(
            t["commits"] for t in table if t["segment"] in NO_STRIKE_SEGMENTS
        )
    if monitor is not None:
        out["loss_diagnosis"] = monitor
    if app_summary is not None:
        c = app_summary.get("counters", {})
        out["app"] = {
            "frames": app_summary.get("frames"),
            "capture_stats": (app_summary.get("source") or {}).get("capture_stats"),
            "invariants": c.get("invariants"),
            "per_frame_processing_s": c.get("per_frame_processing_s"),
            "events": (c.get("events") or {}).get("counts"),
            "runtime_diagnostics": c.get("diagnostics"),
        }
    return out


# ----------------------------------------------------------------------------- running


def run_input(
    inp: dict[str, Any],
    *,
    mode: str,
    configs: list[Path],
    out_dir: Path,
    label: str,
    render: str = "none",
    max_frames: int | None = None,
    repeat: int = 0,
    images: tuple[list[np.ndarray], list[float]] | None = None,
    scenario: str | None = None,
    speed_bins=None,
    harness: str = "none",
) -> dict[str, Any]:
    """One app run under the probe; writes ``rows.jsonl``, ``summary.json`` and ``app-summary.json``."""
    from _p16 import ResourceSampler

    from spacedrums.calib import load_calibrated_config

    out_dir.mkdir(parents=True, exist_ok=False)
    session_id = f"resp-{label}-{inp['name']}-r{repeat}"
    argv = [
        "--config",
        *[str(c) for c in configs],
        "--no-audio",
        "--session-id",
        session_id,
        "--log-dir",
        str(out_dir / "logs"),
        "--overlay-mode",
        "experiment",
    ]
    if mode == "replay":
        argv += ["--source", "replay", "--session-dir", inp["path"]]
    elif mode == "paced":
        argv += ["--source", "live"]
    elif mode == "synthetic":
        argv += ["--synthetic", scenario or "rapid"]
    else:
        raise ValueError(f"unknown mode {mode!r}")
    if render == "none":
        argv += ["--no-window"]
    if max_frames:
        argv += ["--max-frames", str(max_frames)]
    if inp.get("calibration"):
        argv += ["--calibration", inp["calibration"]]
    args = app.build_parser().parse_args(argv)
    cfg = load_calibrated_config(*args.config, calibration=args.calibration).config.data
    probe = Probe(cfg, paced=(mode == "paced"), detail=("full" if mode == "replay" else "light"))
    with ExitStack() as stack:
        stack.enter_context(harness_patch(harness))
        probe.install(stack, render=render)
        if mode == "paced":
            if images is None:
                raise ValueError("paced mode needs pre-decoded frames")
            camera = PacedReplayCamera(*images)
            stack.enter_context(patch.object(app, "camera_factory", lambda: camera))
        with ResourceSampler() as sampler:
            app_summary = app.run(args, on_frame=probe.on_frame)
    rows = [finalise_row(r) for r in probe.rows]
    resources = sampler.report()
    resources.pop("samples", None)
    meta = {
        **inp,
        "mode": mode,
        "label": label,
        "repeat": repeat,
        "render": render,
        "harness_patch": harness,
        "configs": [str(c) for c in configs],
        "argv": argv,
        "resources": resources,
    }
    summary = summarise(
        rows, meta=meta, monitor=probe.monitor.summary(), app_summary=app_summary, speed_bins=speed_bins
    )
    with (out_dir / "rows.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, allow_nan=False) + "\n")
    write_json(out_dir / "summary.json", summary)
    write_json(out_dir / "app-summary.json", app_summary)
    return summary


def write_json(path: Path, data: Any) -> None:
    Path(path).write_text(
        json.dumps(data, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8", newline="\n"
    )


def read_rows(run_dir: Path) -> list[dict[str, Any]]:
    with (Path(run_dir) / "rows.jsonl").open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ----------------------------------------------------------------------------- pooling and comparison


def run_dirs(label_dir: Path) -> list[Path]:
    return sorted(p.parent for p in Path(label_dir).glob("*/rows.jsonl"))


def pooled(dirs: list[Path], *, speed_bins=None) -> dict[str, Any]:
    """Counts summed over runs (rates from the sums), distributions pooled over frames."""
    runs = [read_rows(d) for d in dirs]
    summaries = [json.loads((d / "summary.json").read_text(encoding="utf-8")) for d in dirs]
    frames = sum(len(r) for r in runs)
    hand_frames = [e for rows in runs for r in rows for e in r["hands"].values()]
    sticks = [e for e in hand_frames if e["stick"]]
    minutes = sum(max(0.0, s.get("span_s") or 0.0) for s in summaries) / 60.0
    entries = [s["entries"] for s in summaries if "entries" in s]
    n_entries = sum(e["entries"] for e in entries)
    discarded = sum(e["discarded"] for e in entries)
    resets = sum(sum((s.get("resets") or {}).values()) for s in summaries)
    reacq = sum(s.get("reacquisitions") or 0 for s in summaries)
    both = sum(
        r["hands"]["LEFT"]["present"] and r["hands"]["RIGHT"]["present"] for rows in runs for r in rows
    )
    model = [r["stage_ms"]["hands_model"] for rows in runs for r in rows if "hands_model" in r["stage_ms"]]
    processing = [r.get("processing_ms") for rows in runs for r in rows]
    drops = sum(r["dropped_since_last"] for rows in runs for r in rows)
    depths = [r["queue_depth"] for rows in runs for r in rows if r.get("queue_depth") is not None]
    reasons: Counter = Counter()
    causes: Counter = Counter()
    for s in summaries:
        reasons.update(s.get("resets") or {})
        causes.update(((s.get("loss_diagnosis") or {}).get("resets_by_cause") or {}).get("counts") or {})
    entry_status: Counter = Counter()
    for e in entries:
        entry_status.update(e.get("reject_status_by_limiting_factor") or {})
    no_strike = [
        s.get("no_strike_segment_commits")
        for s in summaries
        if s.get("no_strike_segment_commits") is not None
    ]
    return {
        "runs": [str(d) for d in dirs],
        "frames": frames,
        "minutes": minutes,
        "hand_presence_both": both / frames if frames else None,
        "valid_fraction": sum(e["status"] == "VALID" for e in hand_frames) / len(hand_frames)
        if hand_frames
        else None,
        "axis_found_percent": 100.0 * sum(e["axis"] for e in sticks) / len(sticks) if sticks else None,
        "tip_valid_level_percent": 100.0 * sum(e["limiting"] is None for e in sticks) / len(sticks)
        if sticks
        else None,
        "entries": n_entries,
        "discarded": discarded,
        "discarded_percent": 100.0 * discarded / n_entries if n_entries else None,
        "reject_status_by_limiting_factor": dict(entry_status.most_common()),
        "commits": sum((s.get("commits") or {}).get("total", 0) for s in summaries),
        "no_strike_segment_commits": sum(no_strike) if no_strike else None,
        "resets": resets,
        "resets_per_min": resets / minutes if minutes else None,
        "reset_reasons": dict(reasons.most_common()),
        "reset_causes": dict(causes.most_common()),
        "reacquisitions": reacq,
        "reacquisitions_per_min": reacq / minutes if minutes else None,
        "hands_model_ms": pct(model),
        "processing_ms": {**pct(processing), **budget(processing)},
        "dropped": drops,
        "dropped_percent_of_offered": 100.0 * drops / (drops + frames) if frames else None,
        "stale_deliveries_percent": 100.0 * sum(d >= 2 for d in depths) / len(depths) if depths else None,
        "frame_available_to_start_ms": pct([r.get("age_start_ms") for rows in runs for r in rows]),
        "identity_events": dict(
            sum((Counter(s.get("identity_events") or {}) for s in summaries), Counter()).most_common()
        ),
        "speed": speed_table(runs, speed_bins),
    }


def tip_shift(dir_a: Path, dir_b: Path, roi_px: tuple[int, int] = (520, 420)) -> dict[str, Any]:
    """Raw stick-tip displacement (px) between two runs of the same input, where both found an axis."""
    a = {r["frame_id"]: r for r in read_rows(dir_a)}
    b = {r["frame_id"]: r for r in read_rows(dir_b)}
    shifts = []
    for fid in sorted(set(a) & set(b)):
        for h in ("LEFT", "RIGHT"):
            ea, eb = a[fid]["hands"][h], b[fid]["hands"][h]
            if ea["axis"] and eb["axis"] and ea["tip_raw"] and eb["tip_raw"]:
                dx = (ea["tip_raw"][0] - eb["tip_raw"][0]) * roi_px[0]
                dy = (ea["tip_raw"][1] - eb["tip_raw"][1]) * roi_px[1]
                shifts.append(math.hypot(dx, dy))
    return {
        "n_both_axis": len(shifts),
        **pct(shifts),
        "identical_percent": (100.0 * sum(s == 0.0 for s in shifts) / len(shifts) if shifts else None),
    }


def _scan_valid(rows: list[dict[str, Any]], hand: str, indices) -> int | None:
    """First VALID frame of ``hand`` in ``indices`` unless a loss (INVALID/STALE or a reset) comes first."""
    for j in indices:
        e = rows[j]["hands"][hand]
        if e["status"] == "VALID":
            return j
        if e["status"] in ("INVALID", "STALE") or e["reset_reason"]:
            return None
    return None


def gap_recovery(
    rows: list[dict[str, Any]], cfg: dict[str, Any], *, max_gap_frames: int = 3
) -> dict[str, Any]:
    """Part 8, offline only: for every sounding-arm entry discarded for track status, would the last
    VALID position before it and the next VALID position after it (each within ``max_gap_frames``
    delivered frames, no reset in between) form an observed VALID-to-VALID crossing of that zone?
    That is the crossing a dropped intermediate frame would have produced (commit guard 3)."""
    from spacedrums.geometry import ZoneRegistry
    from spacedrums.geometry.intersect import TrajectoryPoint, first_impact

    registry = ZoneRegistry.from_config(cfg["zones"])
    v_min = float(cfg["geometry"]["v_min"])
    outcome: Counter = Counter()
    for i, row in enumerate(rows):
        active = row.get("active_arm", "A")
        for h, e in row["hands"].items():
            for c in e["candidates"]:
                if c["source"] != ARM_SOURCE.get(active):
                    continue
                decision = next(
                    (d["decision"] for d in e["decisions"] if d["arm"] == active and d["id"] == c["id"]), None
                )
                if decision != "REJECT_STATUS":
                    continue

                before = _scan_valid(rows, h, range(i - 1, max(-1, i - 1 - max_gap_frames), -1))
                after = _scan_valid(rows, h, range(i + 1, min(len(rows), i + 1 + max_gap_frames)))
                if before is None:
                    outcome["no VALID frame within 3 before"] += 1
                    continue
                if after is None:
                    outcome["no VALID frame within 3 after"] += 1
                    continue
                a, b = rows[before], rows[after]
                pa, pb = a["hands"][h]["tip"], b["hands"][h]["tip"]
                impact = first_impact(
                    (TrajectoryPoint(a["t_capture"], tuple(pa)), TrajectoryPoint(b["t_capture"], tuple(pb))),
                    registry[c["zone"]],
                    v_min,
                )
                outcome[
                    "VALID-to-VALID crossing (recoverable)" if impact else "VALID frames do not cross"
                ] += 1
    total = sum(outcome.values())
    return {
        "discarded_for_status": total,
        "outcomes": dict(outcome.most_common()),
        "recoverable_percent": 100.0 * outcome["VALID-to-VALID crossing (recoverable)"] / total
        if total
        else None,
    }
