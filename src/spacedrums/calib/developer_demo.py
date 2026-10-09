"""Explicit fixed developer guide. Never represents a measured calibration pass."""

from spacedrums.calib.reach import ReachSettings
from spacedrums.geometry.four_pad import four_pad_layout
from spacedrums.geometry.kit_layout import kit_layout, pad_gaps_px


class DeveloperDemoLayout:
    state = "DEMO_FIXED"
    message = "DEV fixed guide: cross a yellow top edge downward; lift out to repeat"
    body = target = None
    guide_zones = ()

    def __init__(self, cfg):
        self.profile = dict(cfg["product"]["developer_demo"])
        self.roi_size = tuple(cfg["roi"]["px"][2:])
        w, h = self.roi_size
        p = self.profile
        s = ReachSettings(**cfg["product"].get("reach", {}))
        if "pads" in p:
            pads = p["pads"]
            horizontal, vertical = pad_gaps_px(pads, self.roi_size)
            if (any(q["width"] * w < s.min_width_px or q["height"] * h < s.min_height_px for q in pads)
                    or horizontal < s.horizontal_gap_px or vertical < s.vertical_gap_px):
                raise ValueError("developer guide must preserve product pad and gap floors")
            self.zones = kit_layout(pads)
            self.message = "DEV full kit: tap a fingertip down through a pad's top edge; lift to repeat"
            return
        if (p["width"] * w < s.min_width_px or p["height"] * h < s.min_height_px
                or (p["columns"][1] - p["columns"][0] - p["width"]) * w < s.horizontal_gap_px
                or (p["rows"][1] - p["rows"][0] - p["height"]) * h < s.vertical_gap_px):
            raise ValueError("developer guide must preserve product pad and gap floors")
        self.zones = four_pad_layout(p["columns"], p["rows"], p["width"], p["height"])

    def update(self, t, evidence, body=None, commits=()):
        # The shared decision pipeline consumes current measurements. This layout
        # intentionally collects no calibration evidence and never transitions READY.
        if any(e.t_capture != t for e in evidence.values()):
            raise ValueError("developer demo requires current-frame endpoint evidence")

    def report(self):
        return {
            "mode": "DEVELOPER_FIXED_GUIDE",
            "profile": self.profile,
            "roi_size": list(self.roi_size),
            "zones": self.zones,
            "geometry_checks_passed": True,
            "physical_reach_validated": False,
            "calibration_passed": False,
            "participant_evidence": False,
        }
