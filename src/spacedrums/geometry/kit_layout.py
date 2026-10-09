"""Seven-piece kit without a kick: hi-hat, snare, three toms, crash and ride.

Pads are given in the player's mirrored display; camera coordinates are mirrored here
exactly as in ``four_pad``. No default is a calibrated layout.
"""

from __future__ import annotations

import math

from spacedrums.geometry.four_pad import pad_zone

KIT_NAMES = {
    "crash": "Crash",
    "ride": "Ride",
    "hihat": "Hi-Hat",
    "snare": "Snare",
    "tom1": "Tom 1",
    "tom2": "Tom 2",
    "floor_tom": "Floor Tom",
}
KIT_SAMPLES = {
    "crash": "tr505-crash",
    "ride": "tr505-ride",
    "hihat": "tr505-hihat-closed",
    "snare": "tr505-snare",
    "tom1": "tr505-tom-h",
    "tom2": "tr505-tom-m",
    "floor_tom": "tr505-tom-l",
}
CYMBALS = frozenset({"crash", "ride", "hihat", "crash_ride"})


def kit_layout(pads: list[dict], *, mirror: bool = True) -> list[dict]:
    """``pads``: dicts of zone_id, x (display centre), y (top strike edge), width, height."""
    if not pads:
        raise ValueError("a kit needs at least one pad")
    boxes, zones = [], []
    for pad in pads:
        zid = pad["zone_id"]
        if zid not in KIT_NAMES:
            raise ValueError(f"unknown kit pad {zid!r}")
        x, y, w, h = (float(pad[k]) for k in ("x", "y", "width", "height"))
        if not all(math.isfinite(v) for v in (x, y, w, h)) or min(w, h) <= 0:
            raise ValueError("pad values must be finite and positive")
        if x - w / 2 < 0 or x + w / 2 > 1 or y < 0 or y + h > 1:
            raise ValueError(f"pad {zid} must be inside the ROI")
        if any(zid == other[0] for other in boxes):
            raise ValueError(f"duplicate pad {zid}")
        for oid, ox0, oy0, ox1, oy1 in boxes:
            if x - w / 2 < ox1 and ox0 < x + w / 2 and y < oy1 and oy0 < y + h:
                raise ValueError(f"pads {zid} and {oid} overlap")
        boxes.append((zid, x - w / 2, y, x + w / 2, y + h))
        zones.append(pad_zone(zid, KIT_NAMES[zid], KIT_SAMPLES[zid], 1 - x if mirror else x, y, w, h))
    return zones


def pad_gaps_px(pads: list[dict], roi_size: tuple[int, int]) -> tuple[float, float]:
    """Smallest horizontal / vertical clearance (px) between any two pads that share the other axis."""
    w, h = roi_size
    horizontal = vertical = math.inf
    for i, a in enumerate(pads):
        for b in pads[i + 1 :]:
            dx = abs(a["x"] - b["x"]) - (a["width"] + b["width"]) / 2
            dy = max(a["y"], b["y"]) - min(a["y"] + a["height"], b["y"] + b["height"])
            if dy < 0:  # rows overlap vertically: horizontal clearance matters
                horizontal = min(horizontal, dx * w)
            if dx < 0:  # columns overlap: vertical clearance matters
                vertical = min(vertical, dy * h)
    return horizontal, vertical
