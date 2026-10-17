"""SYNTHETIC checks of the red-tip diagnostics in the developer demo view. No camera or window opens."""

import math
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from spacedrums.capture import Roi
from spacedrums.contracts import HandId
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.kit_layout import kit_layout
from spacedrums.stick.red_tip_estimator import RedTipEndpointEstimator
from spacedrums.stick.red_tip_synthetic import path_frames
from spacedrums.ui.developer_demo import INSET, DemoOverlay

ROI = Roi(0, 0, 640, 480)
REGISTRY = ZoneRegistry.from_config(kit_layout([{"zone_id": "snare", "x": 0.45, "y": 0.68, "width": 0.2,
                                                 "height": 0.11}]))


def frames_with_a_gap():
    a = [(450.0, 200.0 + 3 * k) for k in range(8)]
    a[6] = None  # frame 6: the left tip coasts (predicted, drawn as a ring)
    est = RedTipEndpointEstimator()
    out = []
    for view, _ in path_frames({"a": a, "b": [(180.0, 260.0)] * 8}, exposure_fraction=0.0):
        est.observe(view)
        out.append((view, est.frame, dict(est.evidence)))
    return out


def render(overlay, view, evidence, tips=None, stroke=None):
    result = SimpleNamespace(sample=view.sample, commits=[],
                             hands={h: SimpleNamespace(candidates=()) for h in HandId})
    return overlay.render(view.full, ROI, REGISTRY, evidence, result, dropped=0, perception_ms=2.0,
                          audio_state="DISABLED", stroke_diagnostics=stroke or {}, tip_diagnostics=tips)


def test_tip_diagnostics_add_the_mask_inset_tracks_and_hud_lines():
    frames = frames_with_a_gap()
    view, tips, evidence = frames[3]
    plain = render(DemoOverlay(), view, evidence)
    shown = render(DemoOverlay(), view, evidence, tips, {HandId.LEFT: {"reason": "NOT_DOWNWARD"}})
    w, h = INSET
    inset = (slice(480 - h - 8, 480 - 8), slice(640 - w - 8, 640 - 8))
    assert not np.array_equal(plain[inset], shown[inset])
    red = np.all(shown[inset] == (60, 60, 255), axis=-1)
    assert red.sum() > 0  # the two tips appear in the (mirrored) mask inset
    tip = tips.slots[HandId.LEFT].tip  # camera x 450 -> mirrored display x 189
    x, y = 639 - round(tip[0]), round(tip[1])
    assert not np.array_equal(plain[y - 3:y + 4, x - 3:x + 4], shown[y - 3:y + 4, x - 3:x + 4])
    lines = DemoOverlay()._tip_lines(tips, {HandId.LEFT: {"reason": "NOT_DOWNWARD"}})
    assert lines[0].startswith("RED ") and "L OBS#" in lines[0] and "R OBS#" in lines[0]
    assert lines[1] == "STROKE L NOT_DOWNWARD | R -"


def test_a_predicted_tip_is_drawn_as_a_ring_and_counted_as_lost():
    frames = frames_with_a_gap()
    overlay = DemoOverlay()
    for view, tips, evidence in frames[:7]:
        img = render(overlay, view, evidence, tips)
    st = frames[6][1].slots[HandId.LEFT]
    assert st.state == "PREDICTED" and st.tip is None
    x, y = 639 - round(st.predicted[0]), round(st.predicted[1])
    centre, ring = img[y, x].astype(int), img[y, x + 9].astype(int)
    assert np.abs(ring - centre).sum() > 60  # a hollow ring, not a filled dot
    lines = overlay._tip_lines(frames[6][1], {})
    assert "L PRED#" in lines[0]


def test_redness_candidates_show_the_cap_outline_and_an_untrusted_tip_is_a_ring():
    view, tips, evidence = frames_with_a_gap()[3]
    cap = max(tips.candidates, key=lambda b: b.center[0])  # the left slot's cap (camera x 450)
    assert cap.outline and 0.0 <= cap.score <= 1.0  # the default redness detector
    observed = tips.slots[HandId.LEFT]
    low = replace(observed, state="LOW_EVIDENCE", confidence=0.0)
    untrusted = replace(tips, tracker=replace(tips.tracker, slots={**tips.slots, HandId.LEFT: low}))
    plain = render(DemoOverlay(), view, evidence)
    shown = render(DemoOverlay(), view, evidence, tips)
    ring = render(DemoOverlay(), view, evidence, untrusted)
    ox, oy = max(cap.outline, key=lambda p: math.dist(p, cap.center))  # an outline point away from the dots
    x, y = 639 - ox, oy
    assert not np.array_equal(plain[y - 1:y + 2, x - 1:x + 2], shown[y - 1:y + 2, x - 1:x + 2])
    cx, cy = 639 - round(observed.tip[0]), round(observed.tip[1])
    assert not np.array_equal(shown[cy, cx], ring[cy, cx])  # filled dot when measured, hollow when not
    assert "L LOW#" in DemoOverlay()._tip_lines(untrusted, {})[0]


def test_without_tip_diagnostics_the_demo_view_is_unchanged():
    view, tips, evidence = frames_with_a_gap()[3]
    a = render(DemoOverlay(), view, evidence)
    b = DemoOverlay().render(view.full, ROI, REGISTRY, evidence,
                             SimpleNamespace(sample=view.sample, commits=[], hands={}), dropped=0,
                             perception_ms=2.0, audio_state="DISABLED", stroke_diagnostics={})
    assert np.array_equal(a, b)
