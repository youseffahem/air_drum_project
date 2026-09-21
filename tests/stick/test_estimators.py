"""TEST-CONFORM-1 (TipEstimator) + TEST-STICK-2: GEOM / AXIS_REFINED / MARKER on a synthetic frame.

Synthetic scene (labelled synthetic, never evidence): a gray ROI crop with a light stick drawn upward
from a synthetic fist whose 21 landmarks are placed so that the knuckle row points along the stick.
"""

from __future__ import annotations

import logging
import math

import cv2
import numpy as np
import pytest

from spacedrums.capture import Roi, crop_roi
from spacedrums.contracts import (
    FrameSample,
    FrameView,
    HandId,
    HandObservation,
    ImageRef,
    StickObservation,
    TimestampSource,
    TipEstimator,
    TipMethod,
)
from spacedrums.contracts import schema as contract_schema
from spacedrums.stick import (
    MARKER_WARNING,
    AxisRefinedSettings,
    AxisRefinedTipEstimator,
    GeomSettings,
    GeomTipEstimator,
    MarkerSettings,
    MarkerTipEstimator,
    StickSettings,
    make_tip_estimator,
)

ROI = Roi(40, 20, 560, 440)
STICK_PX = 120.0
GRIP_PX = np.array([280.0, 350.0])  # ROI px
STICK_DIR = np.array([0.0, -1.0])


def _fist_landmarks(grip_px: np.ndarray, span_px: float = 30.0) -> np.ndarray:
    """Synthetic fist: MCP row (5, 9, 13, 17) along +y below the grip; fingers pointing +x."""
    lm = np.zeros((21, 2))
    top = grip_px.copy()
    lm[0] = top + [12, span_px * 0.9]  # wrist below and slightly right
    for f, k in enumerate((5, 9, 13, 17)):
        base = top + [0, f * span_px / 3]
        lm[k] = base
        lm[k + 1], lm[k + 2], lm[k + 3] = base + [8, 0], base + [15, 0], base + [21, 0]
    lm[1], lm[2], lm[3], lm[4] = top + [6, 10], top + [10, 4], top + [12, -3], top + [13, -9]
    return lm


def _view(frame_id: int = 0, t: float = 1.0, stick: bool = True, marker: bool = False,
          stick_len: float = STICK_PX) -> FrameView:
    full = np.full((480, 640, 3), 60, np.uint8)
    rx, ry = ROI.x, ROI.y
    if stick:
        p0 = GRIP_PX + [rx, ry]
        p1 = p0 + stick_len * STICK_DIR
        cv2.line(full, tuple(int(v) for v in p0), tuple(int(v) for v in p1), (200, 200, 200), 8)
    if marker:
        tip = GRIP_PX + [rx, ry] + (stick_len - 6) * STICK_DIR
        cv2.circle(full, tuple(int(v) for v in tip), 6, (60, 220, 60), -1)  # green blob (BGR)
    s = FrameSample(frame_id=frame_id, t_capture=t, t_frame_available=t + 0.001,
                    timestamp_source=TimestampSource.REPLAY, frame_size_px=(640, 480), roi_px=ROI.as_tuple(),
                    image_ref=ImageRef.memory(full), camera_profile_id="synthetic", dropped_since_last=0)
    return FrameView(sample=s, roi=crop_roi(full, ROI), full=full)


def _obs(frame_id: int = 0, t: float = 1.0, hand: HandId = HandId.RIGHT,
         score: float = 0.9) -> HandObservation:
    lm = _fist_landmarks(GRIP_PX)
    norm = tuple((float(x / ROI.w), float(y / ROI.h)) for x, y in lm)
    return HandObservation(frame_id=frame_id, t_capture=t, hand_id=hand, present=True,
                           detector_id="synthetic", landmarks=norm, landmark_visibility=None,
                           handedness_score=score, bbox=(0, 0, 1, 1))


def _tip_px(rec: StickObservation) -> np.ndarray:
    return np.array([rec.tip[0] * ROI.w, rec.tip[1] * ROI.h])


ALL = [TipMethod.GEOM, TipMethod.AXIS_REFINED, TipMethod.MARKER]


@pytest.fixture
def settings() -> StickSettings:
    return StickSettings(marker=MarkerSettings(hsv_low=(35, 80, 80), hsv_high=(85, 255, 255)))


# ----------------------------------------------------------------------------- TEST-CONFORM-1


@pytest.mark.parametrize("method", ALL)
def test_conform_1_schema_valid_and_ids_match(method, settings):
    est = make_tip_estimator(method, settings)
    assert isinstance(est, TipEstimator) and est.method_id is method
    rec = est.estimate(_view(7, 3.5, marker=True), _obs(7, 3.5))
    d = rec.to_dict()
    assert not contract_schema.errors("stick-observation", d), contract_schema.errors("stick-observation", d)
    assert rec.method_id is method and rec.frame_id == 7 and rec.t_capture == 3.5
    assert rec.hand_id is HandId.RIGHT
    assert rec.present


@pytest.mark.parametrize("method", ALL)
def test_conform_1_absent_hand_gives_present_false(method, settings):
    est = make_tip_estimator(method, settings)
    absent = HandObservation.absent(1, 0.5, HandId.LEFT, "synthetic")
    rec = est.estimate(_view(1, 0.5), absent)
    assert not rec.present and rec.method_id is method and rec.hand_id is HandId.LEFT
    assert rec.tip_confidence == 0.0 and rec.axis_confidence == 0.0 and rec.tip is None
    assert not contract_schema.errors("stick-observation", rec.to_dict())


@pytest.mark.parametrize("method", ALL)
def test_conform_1_output_independent_of_hand_call_order(method, settings):
    v = _view(2, 1.0, marker=True)
    a1 = make_tip_estimator(method, settings)
    r_left_first = (a1.estimate(v, _obs(2, 1.0, HandId.LEFT)), a1.estimate(v, _obs(2, 1.0, HandId.RIGHT)))
    a2 = make_tip_estimator(method, settings)
    r_right_first = (a2.estimate(v, _obs(2, 1.0, HandId.RIGHT)), a2.estimate(v, _obs(2, 1.0, HandId.LEFT)))
    assert r_left_first[0].to_dict() == r_right_first[1].to_dict()
    assert r_left_first[1].to_dict() == r_right_first[0].to_dict()


@pytest.mark.parametrize("method", ALL)
def test_causal_1_regression_guard_per_frame_function(method, settings):
    """A TipEstimator is a per-frame function: later frames cannot change an earlier output."""
    est = make_tip_estimator(method, settings)
    first = est.estimate(_view(0, 1.0, marker=True), _obs(0, 1.0)).to_dict()
    for k in range(1, 5):  # feed later, different frames
        est.estimate(_view(k, 1.0 + k / 30, stick=(k % 2 == 0), marker=True), _obs(k, 1.0 + k / 30))
    again = make_tip_estimator(method, settings).estimate(_view(0, 1.0, marker=True), _obs(0, 1.0)).to_dict()
    assert first == again


# ----------------------------------------------------------------------------- GEOM


def test_geom_tip_lies_l_prior_along_the_axis(settings):
    est = GeomTipEstimator(settings)
    rec = est.estimate(_view(), _obs())
    assert rec.present and est.last_analysis.axis is not None
    expected = GRIP_PX + settings.geom.l_prior * ROI.h * STICK_DIR
    assert np.hypot(*(_tip_px(rec) - expected)) < 6.0  # the axis is on the drawn stick
    assert rec.stick_length_est == pytest.approx(settings.geom.l_prior)
    assert rec.axis_dir[1] < 0 and abs(rec.axis_dir[0]) < 0.1
    assert rec.tip_confidence <= 0.9 and rec.tip_confidence > 0.4  # bounded by handedness_score


def test_geom_without_stick_falls_back_to_the_prior_direction(settings):
    est = GeomTipEstimator(settings)
    rec = est.estimate(_view(stick=False), _obs())
    assert rec.present and est.last_analysis.axis is None and est.counters["no_axis"] == 1
    assert rec.axis_confidence == 0.0
    assert rec.tip_confidence == pytest.approx(0.9 * settings.geom.no_axis_confidence_factor)
    # tip along the knuckle-row prior (upwards) at L
    assert _tip_px(rec)[1] < GRIP_PX[1] - 0.8 * settings.geom.l_prior * ROI.h


def test_geom_confidence_is_capped_by_handedness_score(settings):
    est = GeomTipEstimator(settings)
    rec = est.estimate(_view(), _obs(score=0.3))
    assert rec.tip_confidence <= 0.3


def test_geom_online_refinement_is_causal_and_moves_l_towards_support():
    st = StickSettings(geom=GeomSettings(l_prior=0.20, refine_online=True, refine_alpha=0.5,
                                         refine_min_axis_confidence=0.3, refine_support_range=(0.5, 2.0)))
    est = GeomTipEstimator(st)
    l0 = est._l_px(HandId.RIGHT, ROI)
    est.estimate(_view(0, 1.0), _obs(0, 1.0))
    l1 = est._l_px(HandId.RIGHT, ROI)
    assert l1 != l0 and abs(l1 - STICK_PX) < abs(l0 - STICK_PX)  # moved towards the drawn 120 px
    assert est._l_px(HandId.LEFT, ROI) == l0  # per-hand state
    est.reset()
    assert est._l_px(HandId.RIGHT, ROI) == l0


# ----------------------------------------------------------------------------- AXIS_REFINED


def test_axis_refined_uses_support_endpoint_when_consistent(settings):
    est = AxisRefinedTipEstimator(settings)
    rec = est.estimate(_view(), _obs())
    assert rec.present and est.last_used_refined is True and est.counters["fallback"] == 0
    expected_far = GRIP_PX + STICK_PX * STICK_DIR
    assert np.hypot(*(_tip_px(rec) - expected_far)) < 8.0
    assert rec.stick_length_est == pytest.approx(STICK_PX / ROI.h, abs=0.03)


def test_axis_refined_falls_back_when_support_is_truncated():
    # stick drawn much shorter than L: support < min_support_factor * L -> GEOM fallback, reduced confidence
    st = StickSettings(geom=GeomSettings(l_prior=0.40),
                       axis_refined=AxisRefinedSettings(min_support_factor=0.6))
    est = AxisRefinedTipEstimator(st)
    rec = est.estimate(_view(stick_len=60), _obs())
    assert rec.present and est.last_used_refined is False and est.counters["fallback"] == 1
    geom = GeomTipEstimator(st).estimate(_view(stick_len=60), _obs())
    assert rec.tip == pytest.approx(geom.tip)
    expected = geom.tip_confidence * st.axis_refined.fallback_confidence_factor
    assert rec.tip_confidence == pytest.approx(expected)


def test_axis_refined_without_axis_falls_back_to_prior(settings):
    est = AxisRefinedTipEstimator(settings)
    rec = est.estimate(_view(stick=False), _obs())
    assert rec.present and est.counters["fallback"] == 1 and est.counters["no_axis"] == 1


# ----------------------------------------------------------------------------- MARKER


def test_marker_warns_and_finds_the_blob(settings, caplog):
    with caplog.at_level(logging.WARNING, logger="spacedrums.stick.tip_marker"):
        est = MarkerTipEstimator(settings)
    assert any(MARKER_WARNING in r.message for r in caplog.records)
    rec = est.estimate(_view(marker=True), _obs())
    assert rec.present and rec.method_id is TipMethod.MARKER
    blob = GRIP_PX + (STICK_PX - 6) * STICK_DIR
    assert np.hypot(*(_tip_px(rec) - blob)) < 4.0
    assert 0 < rec.tip_confidence <= 0.9


def test_marker_absent_without_blob_and_axis_inconsistency(settings):
    est = MarkerTipEstimator(settings)
    rec = est.estimate(_view(marker=False), _obs())
    assert not rec.present and est.counters["no_blob"] == 1
    # blob far from the axis inside the region -> rejected by the axis-consistency check
    v = _view()
    rx, ry = ROI.x, ROI.y
    cv2.circle(v.full, (int(GRIP_PX[0] + rx + 14), int(GRIP_PX[1] + ry - 60)), 5, (60, 220, 60), -1)
    st = StickSettings(marker=MarkerSettings(axis_consistency_px=3.0))
    est2 = MarkerTipEstimator(st)
    rec2 = est2.estimate(v, _obs())
    assert not rec2.present and est2.counters["axis_inconsistent"] == 1


def test_settings_validation_and_factory():
    with pytest.raises(ValueError):
        GeomSettings(l_prior=0)
    with pytest.raises(ValueError):
        AxisRefinedSettings(fallback_confidence_factor=2)
    with pytest.raises(ValueError):
        MarkerSettings(search="EVERYWHERE")
    assert make_tip_estimator("AXIS_REFINED", StickSettings()).method_id is TipMethod.AXIS_REFINED
    with pytest.raises(ValueError):
        make_tip_estimator("LASER", StickSettings())
    assert math.isclose(StickSettings().geom.l_prior, 0.27)
