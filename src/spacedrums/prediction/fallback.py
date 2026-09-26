"""Sticky fallback: no automatic retries on the audio thread; restart after correcting the fault."""

from dataclasses import asdict, dataclass

from spacedrums.contracts import Arm


@dataclass(frozen=True)
class FallbackEvent:
    t: float
    from_arm: str
    to_arm: str
    reason: str

    def to_dict(self):
        return {**asdict(self), "kind": "MODEL_FALLBACK", "note": self.reason}


def fallback_target(preferred, available):
    for arm in (Arm(preferred), Arm.A):
        if arm in available:
            return arm
    raise RuntimeError("no baseline available for model fallback")
