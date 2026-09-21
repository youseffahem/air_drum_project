from __future__ import annotations

import pytest

from spacedrums.contracts import TrajectoryAux, TrajectoryPrediction
from spacedrums.geometry import GeometryEngine, TrajectoryPoint, first_impact


def path(*points):
    return tuple(TrajectoryPoint(t, p) for t, p in points)


def test_valid_downward_entry_has_subframe_candidate(registry):
    engine = GeometryEngine(registry, v_min=0.1, session_id="test")
    candidate = engine.intersect(
        path((1.0, (0.5, 0.2)), (1.1, (0.5, 0.4))),
        source="REACTIVE",
        frame_id=2,
        hand_id="RIGHT",
        t_capture=1.1,
        t_candidate=1.11,
    )
    assert candidate is not None
    assert candidate.t_impact_est == pytest.approx(1.05, abs=1e-12)
    assert candidate.t_impact_pred is None and candidate.tti is None
    assert candidate.crossing_velocity == pytest.approx((0.0, 2.0))


def test_upward_exit_side_entry_hover_and_both_inside_do_not_strike(circle_zone, registry):
    assert first_impact(path((0.0, (0.5, 0.4)), (0.1, (0.5, 0.2))), circle_zone, 0.1) is None
    assert first_impact(path((0.0, (0.1, 0.5)), (0.1, (0.4, 0.5))), circle_zone, 0.1) is None
    assert first_impact(path((0.0, (0.45, 0.4)), (0.1, (0.5, 0.5))), circle_zone, 0.1) is None
    engine = GeometryEngine(registry, v_min=0.1)
    assert (
        engine.observe(
            frame_id=1, t_capture=0.0, hand_id="LEFT", position=(0.5, 0.2), status="VALID", t_candidate=0.0
        )
        == ()
    )
    assert (
        len(
            engine.observe(
                frame_id=2,
                t_capture=0.1,
                hand_id="LEFT",
                position=(0.5, 0.4),
                status="VALID",
                t_candidate=0.1,
            )
        )
        == 1
    )
    assert (
        engine.observe(
            frame_id=3, t_capture=0.2, hand_id="LEFT", position=(0.5, 0.5), status="VALID", t_candidate=0.2
        )
        == ()
    )


def test_leave_and_reenter_new_episode_and_invalid_ends_episode(registry):
    engine = GeometryEngine(registry, v_min=0.1, session_id="ep")
    samples = [
        (1, 0.0, (0.5, 0.2), "VALID"),
        (2, 0.1, (0.5, 0.4), "VALID"),
        (3, 0.2, (0.5, 0.2), "VALID"),
        (4, 0.3, (0.5, 0.4), "VALID"),
    ]
    out = [
        engine.observe(frame_id=f, t_capture=t, hand_id="RIGHT", position=p, status=s, t_candidate=t)
        for f, t, p, s in samples
    ]
    assert [len(v) for v in out] == [0, 1, 0, 1]
    assert engine.episode_id("RIGHT", "snare").endswith("e000002")
    engine.observe(frame_id=5, t_capture=0.4, hand_id="RIGHT", position=None, status="INVALID")
    assert (
        engine.observe(frame_id=6, t_capture=0.5, hand_id="RIGHT", position=(0.5, 0.4), status="VALID") == ()
    )


def prediction() -> TrajectoryPrediction:
    return TrajectoryPrediction(
        frame_id=10,
        t_capture=2.0,
        hand_id="RIGHT",
        anticipator_id="rule-test",
        model_hash=None,
        K=2,
        dt_step=0.1,
        t_offsets_s=None,
        positions=((0.5, 0.2), (0.5, 0.4)),
        velocities=None,
        uncertainty=None,
        uncertainty_kind=None,
        aux=TrajectoryAux(),
        t_inference_done=2.01,
    )


def test_predicted_intersection_tti_and_reactive_equivalence(registry):
    engine = GeometryEngine(registry, v_min=0.1, session_id="pred")
    pred = engine.intersect_prediction(prediction(), current_position=(0.5, 0.1), source="RULE")
    reactive = engine.intersect(
        path((2.1, (0.5, 0.2)), (2.2, (0.5, 0.4))),
        source="REACTIVE",
        frame_id=10,
        hand_id="RIGHT",
        t_capture=2.2,
        t_candidate=2.21,
    )
    assert pred is not None and reactive is not None
    assert pred.t_impact_pred == pytest.approx(reactive.t_impact_est, abs=1e-12)
    assert pred.tti == pytest.approx(0.15, abs=1e-12)


def test_prediction_starting_inside_requires_exit_and_reentry(registry):
    engine = GeometryEngine(registry, v_min=0.1)
    no_hit = engine.intersect(
        path((0.0, (0.5, 0.5)), (0.1, (0.5, 0.55))),
        source="RULE",
        frame_id=1,
        hand_id="LEFT",
        t_capture=0.0,
        anticipator_id="a",
    )
    hit = engine.intersect(
        path((0.0, (0.5, 0.5)), (0.1, (0.5, 0.2)), (0.2, (0.5, 0.4))),
        source="MODEL",
        frame_id=1,
        hand_id="LEFT",
        t_capture=0.0,
        anticipator_id="m",
    )
    assert no_hit is None and hit is not None and hit.t_impact_pred == pytest.approx(0.15)


def test_prefix_invariance_observed_causality(registry):
    def run(future):
        engine = GeometryEngine(registry, v_min=0.1)
        result = []
        for frame, (t, p) in enumerate([(0.0, (0.5, 0.2)), (0.1, (0.5, 0.4)), *future]):
            result.extend(
                engine.observe(
                    frame_id=frame, t_capture=t, hand_id="LEFT", position=p, status="VALID", t_candidate=t
                )
            )
            if frame == 1:
                break
        return [c.to_dict() for c in result]

    assert run([(0.2, (0.1, 0.1))]) == run([(0.2, (0.9, 0.9))])
