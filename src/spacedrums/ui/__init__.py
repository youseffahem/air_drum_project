"""Layer L7 tooling: stand-here guide (Phase 02), debug overlay (Phase 03 minimal; full dashboard Phase 15),
zone display (Phase 04)."""

from spacedrums.ui.guide import DEFAULT_INSTRUCTION, GuideStyle, draw_guide, guide_status_lines
from spacedrums.ui.overlay import (
    HAND_COLOR,
    STATUS_COLOR,
    TIP_COLOR,
    OverlayStyle,
    draw_debug_overlay,
    draw_hand,
    draw_stick,
    draw_track,
)
from spacedrums.ui.zones import draw_zones

__all__ = [
    "DEFAULT_INSTRUCTION",
    "HAND_COLOR",
    "STATUS_COLOR",
    "TIP_COLOR",
    "GuideStyle",
    "OverlayStyle",
    "draw_debug_overlay",
    "draw_guide",
    "draw_hand",
    "draw_stick",
    "draw_track",
    "draw_zones",
    "guide_status_lines",
]
