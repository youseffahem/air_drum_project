"""AR view palette, piece families and callout labels (BGR, matching the reference screen).

Separate from ``ui.theme.DEFAULT_THEME`` on purpose: the AR view uses blue for the left stick and red for
the right stick, as the reference does, while the developer views keep their colour-blind theme.
"""

from __future__ import annotations

# Zone id -> neon accent. Unknown ids fall back to STEEL.
ACCENTS = {
    "crash_ride": (40, 170, 255),
    "crash": (40, 170, 255),
    "ride": (60, 200, 235),
    "hihat": (90, 230, 60),
    "snare": (50, 40, 240),
    "tom1": (255, 120, 30),
    "tom2": (235, 150, 40),
    "floor_tom": (230, 90, 150),
}
STEEL = (200, 200, 205)

# Zone id -> mesh family used by the 3D renderer.
FAMILIES = {
    "crash_ride": "cymbal",
    "crash": "cymbal",
    "ride": "cymbal",
    "hihat": "hihat",
    "snare": "snare",
    "tom1": "tom",
    "tom2": "tom",
    "floor_tom": "tom",
}
CYMBAL_FAMILIES = frozenset({"cymbal", "hihat"})

# Callout text. "Tom 1" stays the zone name; with a single tom the reference calls it "Tom".
LABELS = {"crash_ride": "Crash / Ride", "hihat": "Hi-Hat", "snare": "Snare", "tom1": "Tom"}
FULL_KIT_LABELS = {"tom1": "Tom 1"}

LEFT = (255, 170, 40)  # left stick / hand: blue
RIGHT = (70, 60, 255)  # right stick / hand: red
PANEL = (38, 26, 18)
PANEL_ALPHA = 0.80
BORDER = (95, 72, 56)
TEXT = (250, 248, 245)
MUTED = (200, 190, 182)
OK = (90, 220, 80)
WARN = (40, 190, 255)
BAD = (80, 80, 240)
IDLE = (130, 125, 120)
TRACK = (255, 140, 40)  # slider fill
GRID = (70, 50, 34)


def accent(zone_id: str) -> tuple[int, int, int]:
    return ACCENTS.get(zone_id, STEEL)


def family(zone_id: str) -> str:
    return FAMILIES.get(zone_id, "tom")


def label(zone_id: str, name: str, zone_ids) -> str:
    """Reference callout text; with more than one tom the zone's own name is kept."""
    toms = sum(1 for z in zone_ids if FAMILIES.get(z) == "tom")
    if toms > 1 and zone_id in FULL_KIT_LABELS:
        return FULL_KIT_LABELS[zone_id]
    return LABELS.get(zone_id, name)


__all__ = ["ACCENTS", "FAMILIES", "LABELS", "LEFT", "RIGHT", "accent", "family", "label"]
