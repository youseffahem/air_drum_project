"""``HandLandmarker``: the hand-landmark estimator wrapper (Phase 03, Task 03.1).

Wraps the candidate estimator (MediaPipe Tasks Hand Landmarker, ``mediapipe>=1.0``) behind a small
backend Protocol and turns its output into two ``HandObservation`` records per frame, one per
``hand_id`` (LEFT then RIGHT, contracts.md section 3.2 / architecture.md section 3), in
ROI-normalized y-down coordinates (``spacedrums.hands.coords``).

What this task does and does not do:

* **Does:** per-frame detection; coordinate conversion at the boundary; ``detector_id`` that pins
  the estimator version, the model file hash and every parameter; per-frame processing time
  (``timing.now()`` around the backend call, never ``time.*``); per-hand presence; counters for
  everything that is *not* emitted (label collisions, unknown labels, timestamp bumps).
* **Identity (Task 03.2, ``spacedrums.hands.identity``):** the swap-mapped estimator label is one
  input; the assigner combines it with temporal continuity (``hands.identity``, mode ``TEMPORAL``)
  or, in mode ``RAW`` (the Task 03.1 baseline), uses the label alone with the same-label collision
  rule (higher score emitted, other dropped and counted in ``label_collisions``). Ambiguous frames
  cap ``handedness_score`` (never a guess). ``swap_handedness`` was decided ``false`` for HW-01 by
  the owner check of 2026-09-21 (image not mirrored); it remains a config switch for other cameras.

Running modes (``hands.running_mode``): ``VIDEO`` lets the estimator carry its own hand ROI from
the previous frame (causal: previous frames only; needs strictly increasing timestamps, which are
derived from ``t_capture``); ``IMAGE`` runs every frame independently. Both are candidates; the
choice is a Task 03.11 / 03.14 decision.

Model complexity: the Tasks API exposes **no** complexity knob (that was the legacy Solutions API);
the model is selected by ``hands.model_asset_id`` (``assets/models/manifest.json``). The Task 03.1
wording "model complexity/confidence parameters via config" is therefore met by the model asset id
plus the three confidence thresholds.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import cv2
import numpy as np

from spacedrums import timing
from spacedrums.capture.roi import Roi
from spacedrums.contracts import N_HAND_LANDMARKS, FrameView, HandId, HandObservation
from spacedrums.hands.coords import DetectorInput, InputFrame, bbox_of, native_to_roi_norm
from spacedrums.hands.grip import GripReference, GripSettings, grip_reference
from spacedrums.hands.identity import (
    WRIST,
    IdentityAssigner,
    IdentityCandidate,
    IdentityFrameResult,
    IdentityMode,
    IdentitySettings,
)
from spacedrums.hands.model_asset import ModelAsset, resolve_model_asset

DETECTOR_FAMILY = "mediapipe-hand-landmarker"


# ----------------------------------------------------------------------------- settings


@dataclass(frozen=True)
class HandLandmarkerSettings:
    """The ``hands`` config block (config schema 1.2, ADR-0014). Every value is a tunable candidate."""

    model_asset_id: str = "mediapipe-hand-landmarker-float16-v1"
    running_mode: str = "VIDEO"  # VIDEO | IMAGE
    num_hands: int = 2
    min_hand_detection_confidence: float = 0.5
    min_hand_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    input: DetectorInput = DetectorInput.ROI
    swap_handedness: bool = False
    identity: IdentitySettings = IdentitySettings()
    grip: GripSettings = GripSettings()

    def __post_init__(self) -> None:
        if self.running_mode not in ("VIDEO", "IMAGE"):
            raise ValueError(f"running_mode must be VIDEO or IMAGE, got {self.running_mode!r}")
        if self.num_hands < 1:
            raise ValueError("num_hands must be >= 1")
        for name in ("min_hand_detection_confidence", "min_hand_presence_confidence",
                     "min_tracking_confidence"):
            v = getattr(self, name)
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"{name} must lie in [0, 1], got {v!r}")
        object.__setattr__(self, "input", DetectorInput(self.input))

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> HandLandmarkerSettings:
        try:
            h = cfg["hands"]
        except KeyError as exc:
            raise ValueError("config has no 'hands' block (config schema 1.2, ADR-0014)") from exc
        if h["detector"] != DETECTOR_FAMILY:
            raise ValueError(f"unsupported hands.detector {h['detector']!r}")
        return cls(
            model_asset_id=str(h["model_asset_id"]),
            running_mode=str(h["running_mode"]),
            num_hands=int(h["num_hands"]),
            min_hand_detection_confidence=float(h["min_hand_detection_confidence"]),
            min_hand_presence_confidence=float(h["min_hand_presence_confidence"]),
            min_tracking_confidence=float(h["min_tracking_confidence"]),
            input=DetectorInput(h["input"]),
            swap_handedness=bool(h["swap_handedness"]),
            identity=IdentitySettings.from_config(h),
            grip=GripSettings.from_config(h),
        )


# ----------------------------------------------------------------------------- backend


@dataclass(frozen=True)
class RawDetection:
    """One detected hand exactly as the backend reports it (native coordinates)."""

    landmarks_native: np.ndarray  # (21, 2) normalized to the detector input image
    label: str  # the estimator's handedness category name ("Left" / "Right")
    score: float  # the estimator's handedness confidence
    visibility: np.ndarray | None = None  # (21,) if the estimator provides one; None otherwise


@runtime_checkable
class LandmarkBackend(Protocol):
    """Minimal surface the wrapper needs, so tests can inject a deterministic backend."""

    backend_id: str

    def detect(self, image_rgb: np.ndarray, timestamp_ms: int) -> list[RawDetection]: ...

    def close(self) -> None: ...


class MediaPipeHandLandmarkerBackend:
    """MediaPipe Tasks ``HandLandmarker`` on the CPU delegate. Imported lazily (heavy, noisy)."""

    def __init__(self, asset: ModelAsset, settings: HandLandmarkerSettings) -> None:
        import mediapipe as mp  # noqa: PLC0415 - lazy: importing mediapipe costs ~1 s and logs
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        self._vision = vision
        mode = vision.RunningMode.VIDEO if settings.running_mode == "VIDEO" else vision.RunningMode.IMAGE
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(asset.path)),
            running_mode=mode,
            num_hands=settings.num_hands,
            min_hand_detection_confidence=settings.min_hand_detection_confidence,
            min_hand_presence_confidence=settings.min_hand_presence_confidence,
            min_tracking_confidence=settings.min_tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._video = settings.running_mode == "VIDEO"
        self.backend_id = f"{DETECTOR_FAMILY}@{mp.__version__}"
        self.library_version = str(mp.__version__)

    def detect(self, image_rgb: np.ndarray, timestamp_ms: int) -> list[RawDetection]:
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(image_rgb))
        if self._video:
            res = self._landmarker.detect_for_video(img, timestamp_ms)
        else:
            res = self._landmarker.detect(img)
        out: list[RawDetection] = []
        for lms, cats in zip(res.hand_landmarks, res.handedness, strict=True):
            pts = np.array([[lm.x, lm.y] for lm in lms], dtype=float)
            vis_vals = [lm.visibility for lm in lms]
            vis = None
            if all(v is not None for v in vis_vals) and any(float(v) > 0.0 for v in vis_vals):
                vis = np.clip(np.array(vis_vals, dtype=float), 0.0, 1.0)
            top = max(cats, key=lambda c: c.score)
            out.append(RawDetection(landmarks_native=pts, label=str(top.category_name),
                                    score=float(top.score), visibility=vis))
        return out

    def close(self) -> None:
        self._landmarker.close()


# ----------------------------------------------------------------------------- results


@dataclass(frozen=True)
class HandDetection:
    """A detection after the coordinate boundary; kept for debugging/overlay, never stored."""

    landmarks: np.ndarray  # (21, 2) ROI-normalized
    bbox: tuple[float, float, float, float]
    label: str
    score: float
    hand_id: HandId | None  # swap-mapped RAW label (identity assignment may differ); None: unknown label
    visibility: np.ndarray | None = None


@dataclass(frozen=True)
class HandsFrameResult:
    """Everything one ``detect`` call produced for one frame."""

    observations: tuple[HandObservation, HandObservation]  # LEFT, RIGHT — always both
    detections: tuple[HandDetection, ...]  # every detection, emitted or not
    processing_s: float  # wall-clock of the backend call (timing.now deltas), not a timestamp
    n_detected: int
    n_not_emitted: int  # detections not emitted this frame (collisions / unknown labels / extra hands)
    timestamp_bumped: bool  # VIDEO mode: t_capture did not advance in ms; bumped by 1 ms
    identity: IdentityFrameResult | None = None  # Task 03.2 assignment detail (events, ambiguity)
    grips: dict[HandId, GripReference] = field(default_factory=dict)  # Task 03.3, present hands only

    @property
    def left(self) -> HandObservation:
        return self.observations[0]

    @property
    def right(self) -> HandObservation:
        return self.observations[1]

    @property
    def both_present(self) -> bool:
        return self.left.present and self.right.present


@dataclass
class HandsCounters:
    frames: int = 0
    detections: int = 0
    present: dict[str, int] = field(default_factory=lambda: {"LEFT": 0, "RIGHT": 0})
    both_present: int = 0
    label_collisions: int = 0
    unknown_labels: int = 0
    timestamp_bumps: int = 0
    visibility_frames: int = 0  # frames where the estimator returned a visibility array
    ambiguous_frames: int = 0  # Task 03.2: frames where identity was ambiguous (scores capped)

    def to_dict(self) -> dict[str, Any]:
        return {"frames": self.frames, "detections": self.detections, "present": dict(self.present),
                "both_present": self.both_present, "label_collisions": self.label_collisions,
                "unknown_labels": self.unknown_labels, "timestamp_bumps": self.timestamp_bumps,
                "visibility_frames": self.visibility_frames, "ambiguous_frames": self.ambiguous_frames}


# ----------------------------------------------------------------------------- wrapper


def label_to_hand_id(label: str, swap: bool) -> HandId | None:
    """Estimator category name -> ``hand_id``; ``None`` for anything that is not Left/Right."""
    key = label.strip().upper()
    if key not in ("LEFT", "RIGHT"):
        return None
    hid = HandId(key)
    if swap:
        hid = HandId.RIGHT if hid is HandId.LEFT else HandId.LEFT
    return hid


class HandLandmarker:
    """Estimator wrapper producing ``HandObservation`` pairs; one instance per session."""

    def __init__(self, settings: HandLandmarkerSettings, backend: LandmarkBackend | None = None,
                 asset: ModelAsset | None = None) -> None:
        self.settings = settings
        if backend is None:
            asset = asset or resolve_model_asset(settings.model_asset_id, verify=True)
            backend = MediaPipeHandLandmarkerBackend(asset, settings)
        self.backend = backend
        self.asset = asset
        self.counters = HandsCounters()
        self.identity = IdentityAssigner(settings.identity)
        self._t0: float | None = None
        self._last_ms = -1
        s = settings
        model_part = asset.hash_prefix if asset is not None else "nomodel"
        self.detector_id = (
            f"{backend.backend_id}:{model_part}:{s.running_mode.lower()}:nh{s.num_hands}"
            f":d{s.min_hand_detection_confidence:.2f}:p{s.min_hand_presence_confidence:.2f}"
            f":t{s.min_tracking_confidence:.2f}:{s.input.lower()}:swap{int(s.swap_handedness)}"
            f":{s.identity.id_fragment()}:{s.grip.id_fragment()}"
        )

    # -- helpers -----------------------------------------------------------------------------
    def _timestamp_ms(self, t_capture: float) -> tuple[int, bool]:
        """Strictly increasing integer milliseconds for the VIDEO mode, derived from ``t_capture``."""
        if self._t0 is None:
            self._t0 = t_capture
        ms = int(round((t_capture - self._t0) * 1000.0))
        bumped = False
        if ms <= self._last_ms:
            ms = self._last_ms + 1
            bumped = True
        self._last_ms = ms
        return ms, bumped

    def _input_image(self, view: FrameView) -> tuple[np.ndarray, InputFrame]:
        roi = Roi.from_rect(view.sample.roi_px)
        if self.settings.input is DetectorInput.ROI:
            return view.roi, InputFrame.for_roi(roi)
        if view.full is None:
            raise ValueError("hands.input = FULL but the FrameView carries no full frame")
        w, h = view.sample.frame_size_px
        return view.full, InputFrame.for_full(w, h)

    # -- main entry --------------------------------------------------------------------------
    def detect(self, view: FrameView) -> HandsFrameResult:
        sample = view.sample
        image_bgr, inp = self._input_image(view)
        roi = Roi.from_rect(sample.roi_px)
        ms, bumped = self._timestamp_ms(sample.t_capture)

        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        t_start = timing.now()
        raw = self.backend.detect(rgb, ms)
        processing_s = timing.now() - t_start

        detections: list[HandDetection] = []
        for r in raw:
            pts = np.asarray(r.landmarks_native, dtype=float).reshape(-1, 2)
            if pts.shape[0] != N_HAND_LANDMARKS:
                raise ValueError(f"backend returned {pts.shape[0]} landmarks, expected {N_HAND_LANDMARKS}")
            norm = native_to_roi_norm(pts, inp, roi)
            detections.append(HandDetection(
                landmarks=norm, bbox=bbox_of(norm), label=r.label, score=r.score,
                hand_id=label_to_hand_id(r.label, self.settings.swap_handedness), visibility=r.visibility,
            ))

        candidates = [
            IdentityCandidate(index=i, wrist=(float(d.landmarks[WRIST, 0]), float(d.landmarks[WRIST, 1])),
                              raw_hand_id=d.hand_id, raw_score=d.score,
                              area=float(d.bbox[2] * d.bbox[3]))
            for i, d in enumerate(detections)
        ]
        ident = self.identity.assign(candidates, sample.frame_id, sample.t_capture)
        chosen: dict[HandId, tuple[HandDetection, float]] = {
            h: (detections[a.candidate.index], a.handedness_score) for h, a in ident.assignments.items()
        }
        not_emitted = len(detections) - len(chosen)
        self.counters.unknown_labels += sum(1 for d in detections if d.hand_id is None)
        if self.settings.identity.mode is IdentityMode.RAW:
            # same-label collisions (Task 03.1 rule): counted so RAW-vs-TEMPORAL runs stay comparable
            labelled = [d.hand_id for d in detections if d.hand_id is not None]
            self.counters.label_collisions += len(labelled) - len(set(labelled))
        else:
            self.counters.label_collisions += sum(
                1 for a in ident.assignments.values()
                if a.candidate.raw_hand_id is not None and a.candidate.raw_hand_id is not a.hand_id
            )
        if ident.ambiguous:
            self.counters.ambiguous_frames += 1

        obs: list[HandObservation] = []
        for hid in (HandId.LEFT, HandId.RIGHT):  # fixed order: logs are deterministic (architecture.md 3)
            got = chosen.get(hid)
            if got is None:
                obs.append(HandObservation.absent(sample.frame_id, sample.t_capture, hid, self.detector_id))
                continue
            d, identity_score = got
            vis = tuple(float(v) for v in d.visibility) if d.visibility is not None else None
            obs.append(HandObservation(
                frame_id=sample.frame_id, t_capture=sample.t_capture, hand_id=hid, present=True,
                detector_id=self.detector_id,
                landmarks=tuple((float(x), float(y)) for x, y in d.landmarks),
                landmark_visibility=vis, handedness_score=identity_score, bbox=d.bbox,
            ))
            self.counters.present[str(hid)] += 1

        c = self.counters
        c.frames += 1
        c.detections += len(detections)
        c.timestamp_bumps += int(bumped)
        if obs[0].present and obs[1].present:
            c.both_present += 1
        if any(d.visibility is not None for d in detections):
            c.visibility_frames += 1

        grips = {}
        for o in obs:
            g = grip_reference(o, self.settings.grip, roi_aspect=roi.aspect)
            if g is not None:
                grips[o.hand_id] = g
        return HandsFrameResult(observations=(obs[0], obs[1]), detections=tuple(detections),
                                processing_s=processing_s, n_detected=len(detections),
                                n_not_emitted=not_emitted, timestamp_bumped=bumped, identity=ident,
                                grips=grips)

    def close(self) -> None:
        self.backend.close()

    def __enter__(self) -> HandLandmarker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def describe(self) -> dict[str, Any]:
        """Provenance for run logs: ids, model hash, settings, library version."""
        d: dict[str, Any] = {
            "detector_id": self.detector_id,
            "backend_id": self.backend.backend_id,
            "settings": {**self.settings.__dict__, "input": str(self.settings.input),
                         "identity": {**self.settings.identity.__dict__,
                                      "mode": str(self.settings.identity.mode)},
                         "grip": {"point_weights": self.settings.grip.point_weights,
                                  "direction": str(self.settings.grip.direction),
                                  "min_direction_span": self.settings.grip.min_direction_span}},
        }
        if self.asset is not None:
            d["model"] = {"asset_id": self.asset.asset_id, "file": self.asset.path.name,
                          "sha256": self.asset.sha256, "bytes": self.asset.bytes,
                          "licence": self.asset.licence}
        lib = getattr(self.backend, "library_version", None)
        if lib:
            d["library_version"] = lib
        return d


def observations_as_dicts(obs: Sequence[HandObservation]) -> list[dict[str, Any]]:
    return [o.to_dict() for o in obs]


__all__ = [
    "DETECTOR_FAMILY",
    "HandDetection",
    "HandLandmarker",
    "HandLandmarkerSettings",
    "HandsCounters",
    "HandsFrameResult",
    "LandmarkBackend",
    "MediaPipeHandLandmarkerBackend",
    "RawDetection",
    "label_to_hand_id",
    "observations_as_dicts",
]
