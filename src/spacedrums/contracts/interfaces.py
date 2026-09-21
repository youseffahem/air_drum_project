"""Pluggable interfaces as ``Protocol``s (docs/architecture/architecture.md section 11).

The signatures are normative; names, argument order and return types may not change without an
ADR. No interface has a look-ahead argument. Each Protocol is added by the phase that first
implements it, so that no Protocol references a record type that does not exist yet:

* Phase 02: ``FrameSource`` (implemented by ``spacedrums.capture.LiveFrameSource``).
* Phase 03: ``TipEstimator`` (``spacedrums.stick``), ``Tracker`` (``spacedrums.tracking``);
  Phase 04: ``Geometry``, ``AudioScheduler``;
  Phase 05: ``Anticipator``, ``CommitPolicy``; Phase 09: ``DirectAnticipator`` (diagnostic only).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Protocol, runtime_checkable

from spacedrums.contracts.enums import CandidateSource, HandId, ResetReason, TipMethod
from spacedrums.contracts.records import (
    AudioEvent,
    CommittedStrike,
    FrameSample,
    HandObservation,
    StickObservation,
    StrikeCandidate,
    TrackState,
)
from spacedrums.contracts.values import FrameView


@runtime_checkable
class FrameSource(Protocol):
    """Record/replay symmetry (architecture.md section 12): LiveFrameSource | ReplayFrameSource.

    Yields ``FrameSample``s in strictly increasing ``frame_id`` order with non-decreasing
    ``t_capture`` (``TEST-CONFORM-7``). A live source sets ``timestamp_source`` to
    ``DRIVER_MAPPED`` or ``GRAB_RETURN``; a replay source reproduces the recorded ``t_capture``
    exactly and sets ``REPLAY``. The processing loop cannot tell them apart.
    """

    def __iter__(self) -> Iterator[FrameSample]: ...


@runtime_checkable
class TipEstimator(Protocol):
    """architecture.md section 11: pure per-frame function of (frame, hand observation).

    Must return a ``StickObservation`` with ``present=False`` rather than raise when the hand is
    absent; ``method_id`` is the class attribute (``GEOM`` | ``AXIS_REFINED`` | ``MARKER``); the
    output is independent of the call order across hands (``TEST-CONFORM-1``).
    """

    method_id: TipMethod

    def estimate(self, frame_roi: FrameView, hand_obs: HandObservation) -> StickObservation: ...


@runtime_checkable
class Tracker(Protocol):
    """architecture.md section 11: causal per-hand tracker; one ``update`` per frame per hand.

    ``update`` receives only the current observations and its own state (no look-ahead argument);
    ``history`` holds the last <= N states, oldest first, all with ``t_capture`` <= the current one
    (``TEST-CONFORM-2``, ``TEST-CAUSAL-1/2``).
    """

    tracker_id: str

    def update(
        self, hand_obs: HandObservation, stick_obs: StickObservation, t_capture: float
    ) -> TrackState: ...

    def reset(self, reason: ResetReason) -> None: ...

    @property
    def history(self) -> Sequence[TrackState]: ...


@runtime_checkable
class Geometry(Protocol):
    """Causal observed/predicted trajectory intersection (Phase 04)."""

    def intersect(
        self,
        trajectory: Sequence[object],
        *,
        source: CandidateSource,
        frame_id: int,
        hand_id: HandId,
        t_capture: float,
        anticipator_id: str | None = None,
        strike_probability: float | None = None,
        intensity_proxy: float | None = None,
        t_candidate: float | None = None,
    ) -> StrikeCandidate | None: ...


@runtime_checkable
class AudioScheduler(Protocol):
    """Schedules a non-shadow Phase 05 commit without knowing commit policy internals."""

    def schedule(self, committed: CommittedStrike) -> AudioEvent: ...


__all__ = ["AudioScheduler", "FrameSource", "Geometry", "TipEstimator", "Tracker"]
