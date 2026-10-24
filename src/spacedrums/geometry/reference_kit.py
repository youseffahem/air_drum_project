"""Reference four-piece arrangement (the AR view's kit): cymbals outer and high, Tom inner-left and
Snare inner-right on the lower row, as on the SpaceDrums reference screen.

The ids, names and TR-505 samples are the four-pad ones (``four_pad``), so audio and records are
unchanged; only positions differ from the 2x2 grid. Pads are given in the player's mirrored display,
ROI-normalised (x = centre, y = top strike edge), exactly like ``kit_layout``.
"""

from __future__ import annotations

from spacedrums.geometry.four_pad import NAMES, SAMPLES
from spacedrums.geometry.kit_layout import kit_layout

REFERENCE_IDS = ("crash_ride", "tom1", "snare", "hihat")  # display order, left to right
# Fixed developer pads over the 640x480 ROI. Every pad keeps the product floors (72 x 42 px) and every
# pair clears 32 px horizontally or vertically: tom/snare 48 px apart in x; crash over tom and hi-hat over
# snare overlap in x but clear 40+ px vertically (the hi-hat sits higher than in the reference for this).
REFERENCE_PADS = [
    {"zone_id": "crash_ride", "x": 0.13, "y": 0.46, "width": 0.26, "height": 0.0875},
    {"zone_id": "tom1", "x": 0.30, "y": 0.66, "width": 0.27, "height": 0.0875},
    {"zone_id": "snare", "x": 0.645, "y": 0.67, "width": 0.27, "height": 0.0875},
    {"zone_id": "hihat", "x": 0.87, "y": 0.50, "width": 0.26, "height": 0.0875},
]


def reference_kit_layout(pads: list[dict] | None = None, *, mirror: bool = True) -> list[dict]:
    """Zones for reference pads (default ``REFERENCE_PADS``); any subset of the four ids is accepted."""
    return kit_layout(REFERENCE_PADS if pads is None else pads, mirror=mirror, names=NAMES, samples=SAMPLES)


__all__ = ["REFERENCE_IDS", "REFERENCE_PADS", "reference_kit_layout"]
