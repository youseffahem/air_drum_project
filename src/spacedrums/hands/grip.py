"""Grip reference points (Phase 03, Task 03.3): the anchor for the stick search region and the GEOM tip.

Definition (documented here; every number is a tunable candidate, ``hands.grip`` config block):

* **Grip point** ``g`` = weighted mean of named landmarks, default weights over
  ``index_mcp`` (5), ``thumb_ip`` (3), ``thumb_tip`` (4) and ``middle_mcp`` (9) — the fulcrum region
  where an ordinary matched/German grip pinches the stick (Q32: natural grip with variation; a
  weighted mean over several landmarks tolerates a missing/jittery one better than a single point).
  Weights are normalised to sum to 1; any of the six named landmarks may carry weight.
* **Grip direction prior** ``u`` (unit vector, pointing from the hand towards the stick tip):
  ``KNUCKLE_ROW`` — from the pinky MCP (17) to the index MCP (5), i.e. along the row of knuckles
  (**default candidate**: in a fist the stick lies across the palm, parallel to the MCP row, and its
  tip exits at the thumb/index end — established on the Phase 02 dev captures, Task 03.3 evidence
  note); ``WRIST_TO_GRIP`` — from the wrist (0) through ``g``; ``INDEX_MCP_TO_PIP`` — from index
  MCP (5) to index PIP (6). The last two are the phase document's original candidates; both run
  *along the fingers*, which is perpendicular to the stick in a closed grip (overlay evidence), so
  they are kept selectable for other grips but are not the default.
* **Hand span** ``s`` = the larger of the two baselines wrist (0) → middle MCP (9) and pinky MCP (17)
  → index MCP (5): the hand's apparent size, used by later tasks to scale the search region and
  tolerances so that they follow the user distance. The maximum is taken because either baseline
  alone foreshortens to a few pixels in some poses (a camera-facing fist compresses wrist → MCP).

Frames: all inputs/outputs are ROI-normalized, y-down (ADR-0005). ``u`` is a unit vector *in the
ROI-normalized frame* (the ``unit_vector2`` of the contracts); because the ROI is not square, an
angle in this frame is not the image angle — ``angle_rad`` is computed after correcting by the ROI
aspect (``roi_aspect = w / h``) so that it is the image-plane angle from +x towards +y, which is
what ``TrackState.axis_angle`` means. Degenerate baselines (shorter than ``min_direction_span``)
yield no direction and the reference is marked invalid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

from spacedrums.contracts import HandObservation

# MediaPipe 21-keypoint ordering (phases/README.md section 14)
LANDMARK_INDEX: dict[str, int] = {
    "wrist": 0,
    "thumb_cmc": 1,
    "thumb_mcp": 2,
    "thumb_ip": 3,
    "thumb_tip": 4,
    "index_mcp": 5,
    "index_pip": 6,
    "index_dip": 7,
    "index_tip": 8,
    "middle_mcp": 9,
    "middle_pip": 10,
    "middle_dip": 11,
    "middle_tip": 12,
    "ring_mcp": 13,
    "ring_pip": 14,
    "ring_dip": 15,
    "ring_tip": 16,
    "pinky_mcp": 17,
    "pinky_pip": 18,
    "pinky_dip": 19,
    "pinky_tip": 20,
}
GRIP_WEIGHT_LANDMARKS = ("wrist", "thumb_ip", "thumb_tip", "index_mcp", "index_pip", "middle_mcp")
DEFAULT_POINT_WEIGHTS = {"index_mcp": 0.4, "thumb_ip": 0.2, "thumb_tip": 0.2, "middle_mcp": 0.2}


class GripDirectionMethod(StrEnum):
    KNUCKLE_ROW = "KNUCKLE_ROW"
    WRIST_TO_GRIP = "WRIST_TO_GRIP"
    INDEX_MCP_TO_PIP = "INDEX_MCP_TO_PIP"


@dataclass(frozen=True)
class GripSettings:
    point_weights: dict[str, float] | None = None
    direction: GripDirectionMethod = GripDirectionMethod.KNUCKLE_ROW
    min_direction_span: float = 0.005  # ROI-normalized; shorter baselines carry no direction

    def __post_init__(self) -> None:
        w = dict(DEFAULT_POINT_WEIGHTS if self.point_weights is None else self.point_weights)
        for name, v in w.items():
            if name not in GRIP_WEIGHT_LANDMARKS:
                raise ValueError(f"grip weight for unknown landmark {name!r}; "
                                 f"allowed {GRIP_WEIGHT_LANDMARKS}")
            if v < 0:
                raise ValueError(f"grip weight {name} must be >= 0")
        total = sum(w.values())
        if total <= 0:
            raise ValueError("grip point weights must sum to > 0")
        object.__setattr__(self, "point_weights", {k: v / total for k, v in w.items() if v > 0})
        object.__setattr__(self, "direction", GripDirectionMethod(self.direction))
        if self.min_direction_span <= 0:
            raise ValueError("min_direction_span must be > 0")

    @classmethod
    def from_config(cls, hands_cfg: dict[str, Any]) -> GripSettings:
        g = hands_cfg["grip"]
        return cls(point_weights={k: float(v) for k, v in g["point_weights"].items()},
                   direction=GripDirectionMethod(g["direction"]),
                   min_direction_span=float(g["min_direction_span"]))

    def id_fragment(self) -> str:
        w = "-".join(f"{k}{v:.2f}" for k, v in sorted(self.point_weights.items()))
        return f"grip-{self.direction.lower()}-{w}"


@dataclass(frozen=True)
class GripReference:
    """Grip anchor of one hand for one frame (ROI-normalized)."""

    point: tuple[float, float]
    direction: tuple[float, float] | None  # unit vector in the ROI-normalized frame; None: degenerate
    angle_rad: float | None  # image-plane angle (aspect-corrected), from +x towards +y
    hand_span: float  # max(wrist -> middle MCP, pinky MCP -> index MCP), ROI-normalized
    method: GripDirectionMethod
    baseline_len: float  # length of the direction baseline before normalisation
    span_vec: tuple[float, float] = (0.0, 0.0)  # the chosen span baseline vector (consumers convert to px)

    @property
    def valid(self) -> bool:
        return self.direction is not None


def grip_point(landmarks: np.ndarray, weights: dict[str, float]) -> np.ndarray:
    pts = np.asarray(landmarks, dtype=float)
    g = np.zeros(2)
    for name, w in weights.items():
        g += w * pts[LANDMARK_INDEX[name]]
    return g


def grip_reference(obs: HandObservation, settings: GripSettings,
                   roi_aspect: float = 1.0) -> GripReference | None:
    """Grip point + direction prior for a present hand; ``None`` when the hand is absent."""
    if not obs.present or obs.landmarks is None:
        return None
    lm = np.asarray(obs.landmarks, dtype=float)
    g = grip_point(lm, settings.point_weights)
    if settings.direction is GripDirectionMethod.KNUCKLE_ROW:
        a, b = lm[LANDMARK_INDEX["pinky_mcp"]], lm[LANDMARK_INDEX["index_mcp"]]
    elif settings.direction is GripDirectionMethod.WRIST_TO_GRIP:
        a, b = lm[LANDMARK_INDEX["wrist"]], g
    else:
        a, b = lm[LANDMARK_INDEX["index_mcp"]], lm[LANDMARK_INDEX["index_pip"]]
    d = b - a
    n = float(np.hypot(d[0], d[1]))
    sv1 = lm[LANDMARK_INDEX["middle_mcp"]] - lm[LANDMARK_INDEX["wrist"]]
    sv2 = lm[LANDMARK_INDEX["index_mcp"]] - lm[LANDMARK_INDEX["pinky_mcp"]]
    sv = sv1 if np.hypot(sv1[0], sv1[1]) >= np.hypot(sv2[0], sv2[1]) else sv2
    span = float(np.hypot(sv[0], sv[1]))
    span_vec = (float(sv[0]), float(sv[1]))
    if n < settings.min_direction_span:
        return GripReference(point=(float(g[0]), float(g[1])), direction=None, angle_rad=None,
                             hand_span=span, method=settings.direction, baseline_len=n, span_vec=span_vec)
    u = d / n
    # image-plane angle: undo the ROI anisotropy (x spans w px, y spans h px per normalized unit)
    angle = math.atan2(d[1], d[0] * roi_aspect)
    return GripReference(point=(float(g[0]), float(g[1])), direction=(float(u[0]), float(u[1])),
                         angle_rad=float(angle), hand_span=span, method=settings.direction, baseline_len=n,
                         span_vec=span_vec)


__all__ = [
    "DEFAULT_POINT_WEIGHTS",
    "GRIP_WEIGHT_LANDMARKS",
    "LANDMARK_INDEX",
    "GripDirectionMethod",
    "GripReference",
    "GripSettings",
    "grip_point",
    "grip_reference",
]
