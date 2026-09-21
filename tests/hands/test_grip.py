"""TEST-HANDS-5: grip reference point and direction prior (Phase 03, Task 03.3)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from spacedrums.contracts import HandId, HandObservation
from spacedrums.hands import (
    LANDMARK_INDEX,
    GripDirectionMethod,
    GripSettings,
    grip_point,
    grip_reference,
)


def _hand(wrist=(0.5, 0.8), up=(0.0, -0.1), spread: float = 1.0) -> np.ndarray:
    """Synthetic hand: wrist at ``wrist``; knuckles one ``up`` step above; thumb to the side.

    ``spread`` scales the sideways fan of the MCPs (0 puts every MCP straight above the wrist)."""
    lm = np.zeros((21, 2))
    w = np.array(wrist, dtype=float)
    u = np.array(up, dtype=float)
    side = np.array([-u[1], u[0]])  # perpendicular
    lm[0] = w
    lm[1], lm[2] = w + 0.3 * u + 0.3 * side, w + 0.6 * u + 0.5 * side
    lm[3], lm[4] = w + 0.8 * u + 0.6 * side, w + u + 0.7 * side
    for f, k in enumerate((5, 9, 13, 17)):  # MCPs of index, middle, ring, pinky
        base = w + u + spread * (0.3 - 0.2 * f) * side
        lm[k] = base
        lm[k + 1], lm[k + 2], lm[k + 3] = base + 0.3 * u, base + 0.55 * u, base + 0.8 * u
    return lm


def _obs(lm: np.ndarray) -> HandObservation:
    return HandObservation(frame_id=1, t_capture=0.0, hand_id=HandId.RIGHT, present=True, detector_id="t",
                           landmarks=tuple((float(x), float(y)) for x, y in lm), landmark_visibility=None,
                           handedness_score=0.9, bbox=(0, 0, 1, 1))


def test_landmark_index_table_matches_mediapipe_ordering():
    assert LANDMARK_INDEX["wrist"] == 0 and LANDMARK_INDEX["thumb_tip"] == 4
    assert LANDMARK_INDEX["index_mcp"] == 5 and LANDMARK_INDEX["index_pip"] == 6
    assert LANDMARK_INDEX["middle_mcp"] == 9 and LANDMARK_INDEX["pinky_tip"] == 20
    assert len(LANDMARK_INDEX) == 21 and sorted(LANDMARK_INDEX.values()) == list(range(21))


def test_weights_normalised_and_validated():
    s = GripSettings(point_weights={"index_mcp": 2.0, "middle_mcp": 2.0})
    assert s.point_weights == {"index_mcp": 0.5, "middle_mcp": 0.5}
    with pytest.raises(ValueError):
        GripSettings(point_weights={"pinky_tip": 1.0})  # not an allowed grip landmark
    with pytest.raises(ValueError):
        GripSettings(point_weights={"index_mcp": 0.0})
    with pytest.raises(ValueError):
        GripSettings(point_weights={"index_mcp": -1.0})
    with pytest.raises(ValueError):
        GripSettings(min_direction_span=0)
    assert GripSettings().point_weights == {"index_mcp": 0.4, "thumb_ip": 0.2, "thumb_tip": 0.2,
                                            "middle_mcp": 0.2}


def test_grip_point_is_the_weighted_mean():
    lm = _hand()
    g = grip_point(lm, {"index_mcp": 0.5, "middle_mcp": 0.5})
    assert g == pytest.approx((lm[5] + lm[9]) / 2)
    g1 = grip_point(lm, {"thumb_tip": 1.0})
    assert g1 == pytest.approx(lm[4])


def test_wrist_to_grip_direction_points_from_hand_to_stick_unit_length():
    lm = _hand(up=(0.0, -0.1), spread=0.0)  # knuckles straight above the wrist (y down: up is -y)
    ref = grip_reference(_obs(lm), GripSettings(point_weights={"index_mcp": 0.5, "middle_mcp": 0.5},
                                                 direction="WRIST_TO_GRIP"))
    assert ref is not None and ref.valid
    assert ref.direction == pytest.approx((0.0, -1.0), abs=1e-9)
    assert math.hypot(*ref.direction) == pytest.approx(1.0)
    assert ref.angle_rad == pytest.approx(-math.pi / 2)  # from +x towards +y: straight up is -pi/2
    assert ref.hand_span == pytest.approx(0.1)  # wrist -> middle MCP
    assert ref.method is GripDirectionMethod.WRIST_TO_GRIP


def test_knuckle_row_direction_default():
    lm = _hand(up=(0.0, -0.1))  # MCP row fans sideways: pinky at -0.3*side ... index at +0.3*side
    s = GripSettings()
    assert s.direction is GripDirectionMethod.KNUCKLE_ROW
    ref = grip_reference(_obs(lm), s)
    expected = lm[5] - lm[17]
    expected = expected / np.hypot(*expected)
    assert ref.direction == pytest.approx(tuple(expected))
    assert ref.baseline_len == pytest.approx(float(np.hypot(*(lm[5] - lm[17]))))


def test_index_mcp_to_pip_direction():
    lm = _hand(up=(0.1, 0.0), spread=0.0)  # fingers point to +x
    ref = grip_reference(_obs(lm), GripSettings(direction="INDEX_MCP_TO_PIP"))
    assert ref.direction == pytest.approx((1.0, 0.0), abs=1e-9) and ref.angle_rad == pytest.approx(0.0)
    assert ref.baseline_len == pytest.approx(0.03)


def test_angle_is_aspect_corrected_but_direction_stays_in_roi_frame():
    lm = _hand(up=(0.1, -0.1), spread=0.0)  # 45 degrees in normalized units
    s = GripSettings(point_weights={"middle_mcp": 1.0}, direction="WRIST_TO_GRIP")
    ref_sq = grip_reference(_obs(lm), s, roi_aspect=1.0)
    ref_wide = grip_reference(_obs(lm), s, roi_aspect=560 / 440)
    assert ref_sq.direction == pytest.approx(ref_wide.direction)  # unit vector in the contract frame
    assert ref_sq.angle_rad == pytest.approx(-math.pi / 4)
    # a wider ROI stretches x in pixels: the image-plane angle is flatter than 45 degrees
    assert ref_wide.angle_rad == pytest.approx(math.atan2(-0.1, 0.1 * 560 / 440))
    assert abs(ref_wide.angle_rad) < abs(ref_sq.angle_rad)


def test_degenerate_baseline_yields_no_direction():
    lm = np.tile([[0.5, 0.5]], (21, 1))  # every landmark at one point
    ref = grip_reference(_obs(lm), GripSettings())
    assert ref is not None and not ref.valid and ref.direction is None and ref.angle_rad is None
    assert ref.point == pytest.approx((0.5, 0.5)) and ref.hand_span == 0.0


def test_absent_hand_gives_none():
    absent = HandObservation.absent(1, 0.0, HandId.LEFT, "t")
    assert grip_reference(absent, GripSettings()) is None


def test_translation_invariance_of_direction_and_span():
    a = grip_reference(_obs(_hand(wrist=(0.2, 0.9))), GripSettings(direction="WRIST_TO_GRIP"))
    b = grip_reference(_obs(_hand(wrist=(0.7, 0.3))), GripSettings(direction="WRIST_TO_GRIP"))
    assert a.direction == pytest.approx(b.direction) and a.hand_span == pytest.approx(b.hand_span)
    assert np.array(b.point) - np.array(a.point) == pytest.approx((0.5, -0.6))


def test_from_config_and_id_fragment():
    cfg = {"grip": {"point_weights": {"index_mcp": 1, "thumb_tip": 1}, "direction": "WRIST_TO_GRIP",
                    "min_direction_span": 0.01}}
    s = GripSettings.from_config(cfg)
    assert s.point_weights == {"index_mcp": 0.5, "thumb_tip": 0.5}
    assert s.id_fragment() == "grip-wrist_to_grip-index_mcp0.50-thumb_tip0.50"
