"""Velocity layer and round-robin choice for grouped samples, decided only from the event's gain.

The gain is the existing kinematic-intensity-proxy curve (a proxy, not force). Layer: ``soft`` below
``SOFT_BELOW`` when the group has one, else ``hard``. Take: a deterministic rotation per
(group, layer), so repeated hits never replay the same file back to back when two or more takes
exist, and the same hit sequence always sounds the same. No randomness, no clock.
"""

from __future__ import annotations

from spacedrums.audio.bank import Sample, SampleBank

SOFT_BELOW = 0.55  # candidate: gain under which the soft layer plays (gain range is 0.2-1.0)


class VariantSelector:
    def __init__(self, bank: SampleBank, soft_below: float = SOFT_BELOW) -> None:
        self.bank = bank
        self.soft_below = float(soft_below)
        self._next: dict[tuple[str, str], int] = {}

    def pick(self, sample_id: str, gain: float) -> Sample:
        layers = self.bank.groups.get(sample_id)
        if not layers:  # an ungrouped sample id: exactly the previous behaviour
            return self.bank[sample_id]
        layer = "soft" if gain < self.soft_below and "soft" in layers else "hard"
        takes = layers[layer]
        i = self._next.get((sample_id, layer), 0)
        self._next[(sample_id, layer)] = (i + 1) % len(takes)
        return takes[i]


__all__ = ["SOFT_BELOW", "VariantSelector"]
