"""Measured stroke evidence -> constrained 2x2 fit, also used by offline simulation.

No inferred GEOM tip or axis length is admissible. A global reach bounding box
cannot fill a hole in the measured play area: every target needs local strokes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

import numpy as np

from spacedrums.contracts.perception import BodyReference, EndpointEvidence
from spacedrums.geometry.four_pad import DISPLAY_ORDER, four_pad_layout


@dataclass(frozen=True)
class ReachSettings:
    min_width_px: float = 72.0
    min_height_px: float = 42.0
    horizontal_gap_px: float = 32.0
    vertical_gap_px: float = 32.0
    margin_px: float = 10.0
    min_strokes: int = 4
    min_confidence: float = 0.65
    min_travel: float = 0.04
    max_gap_s: float = 0.11


@dataclass(frozen=True)
class ReachStroke:
    hand: str
    target: str
    t_start: float
    t_end: float
    start: tuple[float, float]
    end: tuple[float, float]
    points: tuple[tuple[float, float], ...]


class StrokeCollector:
    """Records a downstroke only once its measured rebound is observed (calibration only)."""

    def __init__(self, settings: ReachSettings):
        self.settings = settings
        self.runs = {}
        self.strokes: list[ReachStroke] = []
        self.counts: Counter = Counter()

    def clear_motion(self):
        self.runs.clear()

    def add(self, e: EndpointEvidence, target: str):
        self.counts[e.kind] += 1
        if e.kind != "MEASURED" or e.confidence < self.settings.min_confidence:
            run = self.runs.get(e.hand_id)
            # Keep a bounded measured approach through brief missing observations.
            # No point is inserted for the gap; an idle run cannot seed a stroke.
            approaching = run and len(run) >= 2 and run[-1].tip[1] > run[-2].tip[1]
            if not approaching or e.t_capture - run[-1].t_capture > self.settings.max_gap_s:
                self.runs.pop(e.hand_id, None)
            return
        if e.tip is None or not all(0.01 < v < 0.99 for v in e.tip):
            self.runs.pop(e.hand_id, None)
            return
        run = self.runs.get(e.hand_id, [])
        if run and (
            e.t_capture <= run[-1].t_capture or e.t_capture - run[-1].t_capture > self.settings.max_gap_s
        ):
            run = []
        if run and e.tip[1] < run[-1].tip[1] - 0.006:
            dy = run[-1].tip[1] - run[0].tip[1]
            dx = abs(run[-1].tip[0] - run[0].tip[0])
            if len(run) >= 3 and dy >= self.settings.min_travel and dy >= 0.5 * dx:
                self.strokes.append(
                    ReachStroke(
                        str(e.hand_id),
                        target,
                        run[0].t_capture,
                        run[-1].t_capture,
                        run[0].tip,
                        run[-1].tip,
                        tuple(p.tip for p in run),
                    )
                )
            run = []
        run.append(e)
        self.runs[e.hand_id] = run[-45:]


def fit_reach(
    strokes: list[ReachStroke],
    body: BodyReference,
    roi_size: tuple[int, int],
    settings: ReachSettings | None = None,
    *,
    mirror: bool = True,
) -> dict:
    """Fit equal pads to per-target endpoints; fail with reasons and preserve evidence.

    Column centres and row strike heights are medians of demonstrated strokes.
    Pad width covers 10–90% of the demonstrated horizontal endpoint distribution
    with a noise margin. Each stroke must have observed samples above and below
    the fitted surface. Torso exclusion and pixel floors are hard constraints.
    """
    settings = settings or ReachSettings()
    w, h = roi_size
    reasons = []
    groups = {z: [s for s in strokes if s.target == z] for z in DISPLAY_ORDER}
    result = {
        "passed": False,
        "reasons": reasons,
        "zones": [],
        "settings": asdict(settings),
        "counts": {z: len(g) for z, g in groups.items()},
        "support": {},
    }
    if any(len(g) < settings.min_strokes for g in groups.values()):
        reasons.append("MORE_MEASURED_STROKES_REQUIRED")
        return result
    if set(s.hand for s in strokes) != {"LEFT", "RIGHT"}:
        reasons.append("BOTH_HANDS_REQUIRED")
    if body.confidence < settings.min_confidence:
        reasons.append("BODY_REFERENCE_UNCERTAIN")
    centers = {z: np.median([s.end for s in g], axis=0) for z, g in groups.items()}
    display_cols = [float(np.median([centers[DISPLAY_ORDER[i]][0] for i in ids])) for ids in ((0, 2), (1, 3))]
    xl, xr = sorted(display_cols)
    if (display_cols[0] < display_cols[1]) == mirror:
        reasons.append("TARGET_SIDES_REVERSED")
    # Put the strike edge above the median bottom by a margin that was traversed.
    margin = settings.margin_px / h
    rows = [
        float(np.median([centers[DISPLAY_ORDER[i]][1] for i in ids])) - margin for ids in ((0, 1), (2, 3))
    ]
    spread = max(float(np.ptp(np.percentile([s.end[0] for s in g], [10, 90]))) for g in groups.values())
    width = max(settings.min_width_px / w, spread + 2 * settings.margin_px / w)
    height = settings.min_height_px / h
    if xr - xl - width < settings.horizontal_gap_px / w:
        reasons.append("HORIZONTAL_GAP_TOO_SMALL")
    if rows[1] - rows[0] - height < settings.vertical_gap_px / h:
        reasons.append("VERTICAL_REACH_TOO_SMALL")
    if (
        xl + width / 2 + settings.margin_px / w > body.left
        or xr - width / 2 - settings.margin_px / w < body.right
    ):
        reasons.append("PADS_INTERSECT_TORSO")
    if abs((xl + xr) / 2 - body.center_x) > 0.04:
        reasons.append("LAYOUT_NOT_CENTERED")
    if abs(rows[1] - body.navel_y) > max(0.10, 0.25 * (body.hip_y - body.shoulder_y)):
        reasons.append("LOWER_ROW_OUTSIDE_NAVEL_BAND")
    result.update(
        columns=[xl, xr],
        rows=rows,
        width=width,
        height=height,
        dimensions_px=[width * w, height * h],
        body=body.to_dict(),
    )
    for i, zid in enumerate(DISPLAY_ORDER):
        x = display_cols[i % 2]
        y = rows[i // 2]
        usable_half = width / 2 - 0.16 * min(width, height) - settings.margin_px / w
        supported = [
            s
            for s in groups[zid]
            if s.start[1] <= y - margin and s.end[1] >= y + margin * 0.5 and abs(s.end[0] - x) <= usable_half
        ]
        result["support"][zid] = len(supported)
        if len(supported) < settings.min_strokes:
            reasons.append(f"INSUFFICIENT_APPROACH_MARGIN:{zid}")
    if reasons:
        return result
    try:
        zones = four_pad_layout((xl, xr), tuple(rows), width, height, mirror=mirror)
    except ValueError as exc:
        reasons.append(str(exc))
        return result
    result.update(passed=True, zones=zones)
    return result
