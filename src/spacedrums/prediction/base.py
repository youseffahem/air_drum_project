"""Shared ``Anticipator`` scaffolding (architecture.md section 11; Phase 05, Task 05.2).

Every anticipator — the rule-based extrapolator (Baseline B) now, learned arms later — receives the
tracker's **causal history** (oldest first, every ``t_capture`` <= the current frame's) and returns a
``TrajectoryPrediction`` or ``None``. This base class implements the gates that are common to all of
them and that ``TEST-CONFORM-3`` checks:

* an empty history, a history whose latest state is not live (``INVALID``/``STALE``), or a history
  shorter than the declared warm-up ``N_min`` -> ``None`` (never an exception);
* a history whose ``t_capture`` values are not strictly increasing -> ``None`` (timestamp
  irregularity is a decline, not a guess);
* only the last ``N`` states are ever read (``declared_history()``), so ``TEST-CAUSAL-2`` has a
  declared window and nothing can hide long memory;
* every decline is counted by reason (``DeclineReason``) for the failure-case evidence.

Subclasses implement ``_predict_window(window)`` on the (already validated) window.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Any

from spacedrums.contracts import ResetReason, TrackState, TrackStatus, TrajectoryPrediction
from spacedrums.timing import now

LIVE = (TrackStatus.VALID, TrackStatus.DEGRADED)


class DeclineReason(StrEnum):
    """Why ``predict`` returned ``None`` (diagnostics only; never a record field)."""

    EMPTY_HISTORY = "EMPTY_HISTORY"
    STATUS_NOT_LIVE = "STATUS_NOT_LIVE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    NON_MONOTONIC_TIME = "NON_MONOTONIC_TIME"
    NO_KINEMATICS = "NO_KINEMATICS"
    NO_ACCELERATION = "NO_ACCELERATION"
    LOW_SPEED = "LOW_SPEED"
    HIGH_ACCELERATION = "HIGH_ACCELERATION"


class AnticipatorBase(ABC):
    """Common gating for ``spacedrums.contracts.Anticipator`` implementations."""

    anticipator_id: str
    model_hash: str | None

    def __init__(
        self, *, anticipator_id: str, n_window: int, n_min: int, clock: Callable[[], float] = now
    ) -> None:
        if not anticipator_id:
            raise ValueError("anticipator_id must be non-empty")
        if n_window < 1 or n_min < 1 or n_min > n_window:
            raise ValueError("require 1 <= n_min <= n_window")
        self.anticipator_id = anticipator_id
        self.model_hash = None
        self.n_window = int(n_window)
        self.n_min = int(n_min)
        self.clock = clock
        self.declines: dict[str, int] = {}
        self.last_decline: DeclineReason | None = None
        self.predictions = 0

    # -- Anticipator protocol --------------------------------------------------------------
    def reset(self, reason: ResetReason) -> None:  # noqa: ARG002 - rule-based: no hidden state
        """Rule-based anticipators hold no hidden state; learned subclasses override."""
        return None

    def declared_history(self) -> dict[str, Any]:
        """``N`` (states read) and ``N_min`` (warm-up) for ``TEST-CAUSAL-2``."""
        return {"N": self.n_window, "N_min": self.n_min}

    def predict(
        self, track_history: Sequence[TrackState], features: object | None = None
    ) -> TrajectoryPrediction | None:
        del features  # rule-based arm: features are Phase 08; the interface slot is kept
        if not track_history:
            return self._decline(DeclineReason.EMPTY_HISTORY)
        latest = track_history[-1]
        if latest.status not in LIVE:
            return self._decline(DeclineReason.STATUS_NOT_LIVE)
        window = tuple(track_history[-self.n_window :])
        if any(s.status not in LIVE or s.tip_filtered is None or s.tip_velocity is None for s in window):
            return self._decline(DeclineReason.NO_KINEMATICS)
        if len(window) < self.n_min:
            return self._decline(DeclineReason.INSUFFICIENT_HISTORY)
        if any(b.t_capture <= a.t_capture for a, b in zip(window, window[1:], strict=False)):
            return self._decline(DeclineReason.NON_MONOTONIC_TIME)
        out = self._predict_window(window)
        if out is not None:
            self.predictions += 1
            self.last_decline = None
        return out

    # -- subclass hooks --------------------------------------------------------------------
    @abstractmethod
    def _predict_window(self, window: tuple[TrackState, ...]) -> TrajectoryPrediction | None: ...

    def _decline(self, reason: DeclineReason) -> None:
        self.declines[reason.value] = self.declines.get(reason.value, 0) + 1
        self.last_decline = reason
        return None


__all__ = ["LIVE", "AnticipatorBase", "DeclineReason"]
