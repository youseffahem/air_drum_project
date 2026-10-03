"""Four equal pads; camera coordinates, named in the mirrored player's display.

No default is a calibrated layout. Positions and dimensions are supplied by the
reach fitter. Polygon corners approximate roundovers; top segments define impact.
"""

from __future__ import annotations

import math

DISPLAY_ORDER = ("crash_ride", "hihat", "snare", "tom1")
NAMES = {"crash_ride": "Crash / Ride", "hihat": "Hi-Hat", "snare": "Snare", "tom1": "Tom 1"}
SAMPLES = {
    "crash_ride": "tr505-crash",
    "hihat": "tr505-hihat-closed",
    "snare": "tr505-snare",
    "tom1": "tr505-tom-h",
}


def four_pad_layout(
    columns: tuple[float, float],
    rows: tuple[float, float],
    width: float,
    height: float,
    *,
    mirror: bool = True,
) -> list[dict]:
    """Rows are top strike heights, not centres. Fail on overlap or off-screen pads."""
    xl, xr = sorted(columns)
    yu, yl = sorted(rows)
    if not all(math.isfinite(v) for v in (*columns, *rows, width, height)):
        raise ValueError("layout values must be finite")
    if min(width, height) <= 0 or xr - xl <= width or yl - yu <= height:
        raise ValueError("four pads need positive dimensions and horizontal/vertical gaps")
    if xl - width / 2 < 0 or xr + width / 2 > 1 or yu < 0 or yl + height > 1:
        raise ValueError("pads must be inside the ROI")
    xs = (xr, xl) if mirror else (xl, xr)
    zones = []
    for i, zid in enumerate(DISPLAY_ORDER):
        x, y = xs[i % 2], (yu, yl)[i // 2]
        left, right, bottom = x - width / 2, x + width / 2, y + height
        r = min(width, height) * 0.16
        points = []
        for cx, cy, start in (
            (left + r, y + r, 180),
            (right - r, y + r, 270),
            (right - r, bottom - r, 0),
            (left + r, bottom - r, 90),
        ):
            for j in range(5):
                theta = math.radians(start + j * 90 / 4)
                points.append([cx + r * math.cos(theta), cy + r * math.sin(theta)])
        zones.append(
            {
                "zone_id": zid,
                "name": NAMES[zid],
                "trigger_type": "HAND_TIP",
                "shape": {"type": "POLYGON", "points": points},
                "impact_surface": {"type": "SEGMENT", "p0": [left + r, y], "p1": [right - r, y]},
                "inward_normal": [0.0, 1.0],
                "allowed_hands": ["LEFT", "RIGHT"],
                "sample_id": SAMPLES[zid],
                "gain_curve_id": "default",
            }
        )
    return zones
