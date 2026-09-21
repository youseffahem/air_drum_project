"""Interface value types that are never stored (docs/architecture/contracts.md section 7).

Phase 02 adds ``FrameView`` (the ``TipEstimator`` input of Phase 03 and the object the capture
module hands to any consumer that wants pixels). ``Trajectory`` is added by Phase 04 (geometry).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spacedrums.contracts.records import FrameSample


@dataclass(frozen=True)
class FrameView:
    """ROI crop of a frame as an in-memory array plus its ``FrameSample``.

    ``roi`` is a *view* into the full frame (pure slicing, no resampling: Phase 02 ROI policy);
    ``full`` is the full frame when the source has it (``None`` for ROI-only replays).
    Shapes are ``(h, w, 3)`` BGR ``uint8`` as delivered by the capture backend.
    """

    sample: FrameSample
    roi: Any
    full: Any | None = None


__all__ = ["FrameView"]
