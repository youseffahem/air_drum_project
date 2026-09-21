"""Pluggable interfaces as ``Protocol``s (docs/architecture/architecture.md section 11).

The signatures are normative; names, argument order and return types may not change without an
ADR. No interface has a look-ahead argument. Each Protocol is added by the phase that first
implements it, so that no Protocol references a record type that does not exist yet:

* Phase 02: ``FrameSource`` (implemented by ``spacedrums.capture.LiveFrameSource``).
* Phase 03: ``TipEstimator``, ``Tracker``; Phase 04: ``Geometry``, ``AudioScheduler``;
  Phase 05: ``Anticipator``, ``CommitPolicy``; Phase 09: ``DirectAnticipator`` (diagnostic only).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from spacedrums.contracts.records import FrameSample


@runtime_checkable
class FrameSource(Protocol):
    """Record/replay symmetry (architecture.md section 12): LiveFrameSource | ReplayFrameSource.

    Yields ``FrameSample``s in strictly increasing ``frame_id`` order with non-decreasing
    ``t_capture`` (``TEST-CONFORM-7``). A live source sets ``timestamp_source`` to
    ``DRIVER_MAPPED`` or ``GRAB_RETURN``; a replay source reproduces the recorded ``t_capture``
    exactly and sets ``REPLAY``. The processing loop cannot tell them apart.
    """

    def __iter__(self) -> Iterator[FrameSample]: ...


__all__ = ["FrameSource"]
