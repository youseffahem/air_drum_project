"""Additive product evidence; legacy StickObservation remains schema 1.0.

MEASURED means a current image endpoint, not ground truth. UNCERTAIN/MISSING
never qualify for calibration or a product strike. Coordinates remain ROI units.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from spacedrums.contracts.enums import HandId


@dataclass(frozen=True)
class EndpointEvidence:
    frame_id: int
    t_capture: float
    hand_id: HandId
    kind: str
    reason: str
    tip: tuple[float, float] | None = None
    origin: tuple[float, float] | None = None
    confidence: float = 0.0
    support_px: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, "hand_id", HandId(self.hand_id))
        if self.frame_id < 0 or not math.isfinite(self.t_capture):
            raise ValueError("invalid endpoint frame or timestamp")
        if not 0 <= self.confidence <= 1 or not math.isfinite(self.support_px) or self.support_px < 0:
            raise ValueError("invalid endpoint confidence or support")
        for p in (self.tip, self.origin):
            if p is not None and (len(p) != 2 or not all(math.isfinite(v) for v in p)):
                raise ValueError("endpoint coordinates must be finite points")
        if self.kind not in ("MEASURED", "UNCERTAIN", "MISSING"):
            raise ValueError("unknown endpoint evidence kind")
        if self.kind == "MEASURED" and (self.tip is None or self.origin is None):
            raise ValueError("measured endpoint needs current tip and axis origin")

    def to_dict(self):
        return {
            "schema_version": "1.0",
            **asdict(self),
            "tip": list(self.tip) if self.tip is not None else None,
            "origin": list(self.origin) if self.origin is not None else None,
        }


@dataclass(frozen=True)
class BodyReference:
    """Measured shoulders/hips bound a torso. Navel is an explicit approximation."""

    t_capture: float
    left: float
    right: float
    shoulder_y: float
    hip_y: float
    confidence: float

    @property
    def center_x(self):
        return (self.left + self.right) / 2

    @property
    def navel_y(self):
        return self.shoulder_y + 0.78 * (self.hip_y - self.shoulder_y)

    def to_dict(self):
        return asdict(self)
