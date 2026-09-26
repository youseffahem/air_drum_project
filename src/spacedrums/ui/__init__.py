"""Layer L7 tooling: stand-here guide (Phase 02), debug overlay (Phase 03 minimal; full dashboard Phase 15),
zone display (Phase 04), calibration wizard views (Phase 14)."""

from spacedrums.ui.dashboard import (
    DashboardModel,
    DashboardRecord,
    DashboardWorker,
    RecordBus,
    render_dashboard,
    timing_row,
)
from spacedrums.ui.guide import DEFAULT_INSTRUCTION, GuideStyle, draw_guide, guide_status_lines
from spacedrums.ui.overlay import (
    HAND_COLOR,
    STATUS_COLOR,
    TIP_COLOR,
    OverlayConfig,
    OverlayRecords,
    OverlayStyle,
    RuntimeStats,
    draw_debug_overlay,
    draw_hand,
    draw_scientific_overlay,
    draw_stick,
    draw_track,
)
from spacedrums.ui.wizard_views import WizardStyle, WizardView, draw_wizard
from spacedrums.ui.zones import draw_zones

__all__ = [
    "DEFAULT_INSTRUCTION",
    "HAND_COLOR",
    "STATUS_COLOR",
    "TIP_COLOR",
    "GuideStyle",
    "OverlayStyle",
    "OverlayConfig",
    "OverlayRecords",
    "RuntimeStats",
    "DashboardModel",
    "DashboardRecord",
    "DashboardWorker",
    "RecordBus",
    "WizardStyle",
    "WizardView",
    "draw_debug_overlay",
    "draw_guide",
    "draw_hand",
    "draw_stick",
    "draw_track",
    "draw_scientific_overlay",
    "render_dashboard",
    "draw_wizard",
    "draw_zones",
    "guide_status_lines",
    "timing_row",
]
