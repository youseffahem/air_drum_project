"""TEST-LABEL-1 — labelling rules v1.0 on synthetic evidence (Phase 07, Task 07.1).

Every rule of ``docs/dataset/labeling-rules-v1.0.md`` has a test here. The rules are tested through
:func:`spacedrums.data.labels.rules.classify` on constructed :class:`EventEvidence`, which is what
makes them testable without a session on disk; the end-to-end path is
``test_label_generator.py``.
"""

from __future__ import annotations

import math

import pytest
from label_helpers import evidence

from spacedrums.data.labels.rules import (
    RULES,
    Thresholds,
    classify,
    closest_point_on_surface,
    distance_to_surface,
    intensity_proxy_gt,
    inward_speed,
    label_confidence,
    rules_hash,
    signed_distance_to_surface,
)
from spacedrums.data.labels.schema import LabelClass

TH = Thresholds(v_min=0.15)


# ----------------------------------------------------------------------------- R1 / R2 positives


def test_r1_valid_entry_is_positive():
    cls, rule = classify(evidence(inward_speed=1.5), TH)
    assert (cls, rule) == (LabelClass.POSITIVE, "P07-R1")


def test_r1_uses_the_phase04_entry_test_not_the_lowest_point():
    """A crossing well above ``v_min`` is a POSITIVE regardless of where the stroke bottoms out:
    the rule keys on the surface crossing, not on a minimum or a velocity reversal."""
    for speed in (0.2, 0.5, 5.0):
        cls, _ = classify(evidence(inward_speed=speed), TH)
        assert cls is LabelClass.POSITIVE


def test_r2_intensity_proxy_is_the_inward_normal_component(circle_zone):
    v = (0.3, 1.2)
    assert intensity_proxy_gt(circle_zone, v) == pytest.approx(inward_speed(circle_zone, v))
    # inward_normal of the fixture is (0, 1): the proxy is the downward component only.
    assert intensity_proxy_gt(circle_zone, v) == pytest.approx(1.2)


def test_r2_proxy_ignores_the_tangential_component(circle_zone):
    assert intensity_proxy_gt(circle_zone, (9.0, 0.0)) == pytest.approx(0.0)


# ----------------------------------------------------------------------------- R3 / R4 negatives


def test_r3_fake_swing_fast_approach_without_entry():
    cls, rule = classify(
        evidence(direction="APPROACH", min_distance=0.03, max_inward_speed=1.0,
                 speed_at_min_distance=0.9),
        TH,
    )
    assert (cls, rule) == (LabelClass.NEG_FAKE_SWING, "P07-R3")


def test_r3_needs_both_closeness_and_speed():
    far = classify(evidence(direction="APPROACH", min_distance=0.2, max_inward_speed=1.0,
                            speed_at_min_distance=0.9), TH)
    slow = classify(evidence(direction="APPROACH", min_distance=0.03, max_inward_speed=0.05,
                             speed_at_min_distance=0.9), TH)
    assert far is None
    assert slow is None


def test_r4_stop_before_impact_decelerates_to_near_zero():
    cls, rule = classify(
        evidence(direction="APPROACH", min_distance=0.02, max_inward_speed=1.0,
                 speed_at_min_distance=0.01),
        TH,
    )
    assert (cls, rule) == (LabelClass.NEG_STOP_BEFORE_IMPACT, "P07-R4")


def test_r4_is_checked_before_r3_because_it_is_more_specific():
    """A stop-short is also close and was also fast on the way in; the deceleration decides."""
    stop = evidence(direction="APPROACH", min_distance=0.02, max_inward_speed=1.0,
                    speed_at_min_distance=0.01)
    assert classify(stop, TH)[0] is LabelClass.NEG_STOP_BEFORE_IMPACT


# ----------------------------------------------------------------------------- R5 upward / exit


def test_r5_entry_slower_than_v_min_is_an_explicit_negative():
    cls, rule = classify(evidence(inward_speed=0.05), TH)
    assert (cls, rule) == (LabelClass.NEG_UPWARD_CROSSING, "P07-R5")


def test_r5_exit_direction_crossing_is_a_negative():
    cls, rule = classify(evidence(direction="EXIT", inward_speed=-1.0), TH)
    assert (cls, rule) == (LabelClass.NEG_UPWARD_CROSSING, "P07-R5")


def test_r5_recovery_of_a_labelled_entry_is_not_a_second_event():
    assert classify(evidence(direction="EXIT", inward_speed=-1.0, recovery_of_entry=True), TH) is None


def test_r5_zero_inward_speed_is_never_a_positive():
    cls, _ = classify(evidence(inward_speed=0.0), TH)
    assert cls is LabelClass.NEG_UPWARD_CROSSING


# ----------------------------------------------------------------------------- R6 ambiguous


def test_r6a_speed_inside_the_band_is_ambiguous():
    cls, rule = classify(evidence(inward_speed=TH.v_min), TH)
    assert (cls, rule) == (LabelClass.AMBIGUOUS, "P07-R6a")
    assert classify(evidence(inward_speed=TH.v_min * 1.1), TH)[0] is LabelClass.AMBIGUOUS


def test_r6b_degraded_reference_tracking_is_ambiguous():
    for bad in ({"valid_fraction": 0.1}, {"mean_quality": 0.1}, {"interpolated": True}):
        cls, rule = classify(evidence(**bad), TH)
        assert (cls, rule) == (LabelClass.AMBIGUOUS, "P07-R6b")


def test_r6b_also_applies_to_a_non_crossing_approach():
    cls, rule = classify(evidence(direction="APPROACH", min_distance=0.02, interpolated=True), TH)
    assert (cls, rule) == (LabelClass.AMBIGUOUS, "P07-R6b")


# ----------------------------------------------------------------------------- R7 confidence


def test_r7_confidence_combines_quality_and_validity():
    assert label_confidence(0.8, 0.5) == pytest.approx(0.4)
    assert label_confidence(2.0, 2.0) == 1.0
    assert label_confidence(-1.0, 0.5) == 0.0


# ----------------------------------------------------------------------------- R11 quarantine


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"direction": "EXIT", "inward_speed": -1.0},
        {"direction": "APPROACH", "min_distance": 0.02, "speed_at_min_distance": 0.01},
        {"inward_speed": 0.0},
    ],
)
def test_r11_quarantine_wins_over_every_other_rule(kwargs):
    cls, rule = classify(evidence(in_quarantine=True, **kwargs), TH)
    assert (cls, rule) == (LabelClass.EXCLUDED, "P07-R11")


# ----------------------------------------------------------------------------- thresholds


def test_thresholds_hash_changes_with_any_threshold():
    a = Thresholds(v_min=0.15)
    b = Thresholds(v_min=0.15, ambiguous_band=0.16)
    assert a.thresholds_hash != b.thresholds_hash
    assert a.thresholds_hash == Thresholds(v_min=0.15).thresholds_hash


def test_thresholds_round_trip_and_reject_unknown_keys():
    t = Thresholds(v_min=0.2, stop_speed_max=0.05)
    assert Thresholds.from_dict(t.to_dict()) == t
    with pytest.raises(ValueError, match="unknown threshold keys"):
        Thresholds.from_dict({**t.to_dict(), "not_a_threshold": 1.0})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"v_min": -1.0},
        {"ambiguous_band": 1.0},
        {"stop_band_max": 0.0},
        {"stop_speed_max": 0.0},
        {"min_valid_fraction": 1.5},
    ],
)
def test_thresholds_reject_impossible_values(kwargs):
    with pytest.raises(ValueError):
        Thresholds(**kwargs)


def test_rules_hash_is_stable_and_covers_every_rule_id():
    assert rules_hash() == rules_hash()
    assert set(RULES) == {f"P07-R{n}" for n in range(1, 12)}
    for rule in RULES.values():
        assert rule["title"] and rule["text"]


# ----------------------------------------------------------------------------- surface geometry


def test_distance_to_an_arc_surface_is_zero_on_the_surface(circle_zone):
    arc = circle_zone.impact_surface
    mid = arc.point_at((arc.theta_start_rad + arc.theta_end_rad) / 2)
    assert distance_to_surface(circle_zone, mid) == pytest.approx(0.0, abs=1e-9)


def test_signed_distance_is_negative_inside_and_positive_outside(circle_zone):
    assert signed_distance_to_surface(circle_zone, (0.5, 0.5)) < 0  # centre of the ellipse
    assert signed_distance_to_surface(circle_zone, (0.5, 0.95)) > 0  # below the bottom arc


def test_closest_point_on_a_segment_surface_is_clamped_to_the_segment(segment_zone):
    seg = segment_zone.impact_surface
    far = (seg.p1[0] + 1.0, seg.p1[1])
    assert closest_point_on_surface(seg, far) == pytest.approx(seg.p1)


def test_distance_grows_monotonically_away_from_the_surface(circle_zone):
    arc = circle_zone.impact_surface
    mid = arc.point_at((arc.theta_start_rad + arc.theta_end_rad) / 2)
    ds = [distance_to_surface(circle_zone, (mid[0], mid[1] + k * 0.01)) for k in range(1, 6)]
    assert ds == sorted(ds)
    assert all(math.isfinite(d) for d in ds)
