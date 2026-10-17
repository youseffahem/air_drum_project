"""Red-tip STICK perception for ``app.play --red-tips`` (a coloured MARKER condition, integrity I-7).

Same interface as ``app.main.Perception`` (``__call__(view) -> Observations``, ``estimator``,
``last_hands``, ``landmarker``, ``close``), so the play loop, the decision pipeline and the overlays
are unchanged. Tips come from the painted caps on every frame (``stick_tip.detector``: the redness
detector by default, HSV colour as an option). The MediaPipe hand model is created and run only
with ``product.stick_tip.hand_assist``: it costs about 27 ms per frame (fingertip sessions) and found a
hand in about 17 % of held-stick hand-frames (2026-10-16 stick session). Without it both hands are
reported absent with detector id ``red-tip-only``; the tracker reads only the tip observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spacedrums.contracts import FrameView, HandId, HandObservation
from spacedrums.stick.red_tip import RedTipSettings
from spacedrums.stick.red_tip_estimator import RedTipEndpointEstimator

HANDS = (HandId.LEFT, HandId.RIGHT)
DETECTOR_ID = "red-tip-only"


@dataclass(frozen=True)
class NoHands:
    """``HandsFrameResult`` stand-in when the hand model is not run."""

    left: HandObservation
    right: HandObservation
    processing_s: float = 0.0


class RedTipPerception:
    def __init__(self, cfg: dict[str, Any]) -> None:
        from spacedrums.stick import StickSettings

        self.settings = RedTipSettings.from_config(cfg)
        self.stick_settings = StickSettings.from_config(cfg)
        self.landmarker = None
        if self.settings.hand_assist:
            from spacedrums.hands import HandLandmarker, HandLandmarkerSettings

            self.landmarker = HandLandmarker(HandLandmarkerSettings.from_config(cfg))
        self.estimator = RedTipEndpointEstimator(self.settings, self.stick_settings.grip)
        self.last_hands: Any = None
        self.last_analyses: dict[HandId, Any] = {}

    def __call__(self, view: FrameView):
        s = view.sample
        if self.landmarker is not None:
            res = self.landmarker.detect(view)
        else:
            res = NoHands(*(HandObservation.absent(s.frame_id, s.t_capture, h, DETECTOR_ID) for h in HANDS))
        self.last_hands = res
        hands = {HandId.LEFT: res.left, HandId.RIGHT: res.right}
        sticks = self.estimator.observe(view, hands if self.landmarker is not None else None)
        return {h: (hands[h], sticks[h]) for h in HANDS}

    def close(self) -> None:
        if self.landmarker is not None:
            self.landmarker.close()


__all__ = ["DETECTOR_ID", "NoHands", "RedTipPerception"]
