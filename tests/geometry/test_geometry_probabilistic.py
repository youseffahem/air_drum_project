"""Phase 12 probabilistic geometry: known crossing probabilities, layouts, and a drop/relabel-only gate.

The deterministic impact test is reused unchanged; a certain prediction reproduces the deterministic
candidate exactly, and the gate can only relabel ``strike_probability`` of an existing candidate.
"""

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import norm

from spacedrums.config import load_config
from spacedrums.contracts import StrikeCandidate, TrajectoryAux, TrajectoryPrediction
from spacedrums.geometry import GeometryEngine, ZoneRegistry
from spacedrums.geometry.probabilistic import (
    CrossingProbabilityGate,
    common_draws,
    intersect_prob,
    sample_trajectories,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ZoneRegistry.from_config(load_config(ROOT / "configs/prototype.candidate.yaml")["zones"])
ANCHOR = (0.40, 0.50)  # above the snare's upper arc (top at y = 0.58), outside every zone


def prediction(positions, *, uncertainty=None, kind=None, offsets=None, dt=0.02):
    return TrajectoryPrediction(
        frame_id=7,
        t_capture=10.0,
        hand_id="LEFT",
        anticipator_id="synthetic-probabilistic-test",
        model_hash=None,
        K=len(positions),
        dt_step=dt,
        t_offsets_s=offsets,
        positions=tuple(map(tuple, positions)),
        velocities=None,
        uncertainty=uncertainty,
        uncertainty_kind=kind,
        aux=TrajectoryAux(),
        t_inference_done=10.0,
    )


def vertical(end_y, k=4):
    return [(0.40, ANCHOR[1] + (end_y - ANCHOR[1]) * (j + 1) / k) for j in range(k)]


def test_certain_prediction_reproduces_the_deterministic_candidate():
    pred = prediction(vertical(0.62))
    candidate = GeometryEngine(REGISTRY, v_min=0.15).intersect_prediction(pred, current_position=ANCHOR)
    dist = intersect_prob(REGISTRY, pred, ANCHOR, v_min=0.15)
    assert dist.probability == 1.0 and dist.zone_probability("snare") == 1.0 and dist.samples == 1
    assert dist.tti_quantiles_s == pytest.approx((candidate.tti,) * 3, abs=1e-12)
    miss = intersect_prob(REGISTRY, prediction(vertical(0.56)), ANCHOR, v_min=0.15)
    assert miss.probability == 0.0 and miss.by_zone == () and miss.tti_quantiles_s is None


@pytest.mark.parametrize("distance", [0.0, 0.01, 0.02])
def test_shared_gaussian_matches_the_analytic_crossing_probability(distance):
    # Mean ends `distance` above the surface; sigma grows linearly, so with a shared draw every
    # sampled path is straight and crosses iff its last point is below the surface: P = 1 - Phi(d/s).
    s, k = 0.01, 4
    rows = tuple((0.0, s * (j + 1) / k) for j in range(k))
    pred = prediction(vertical(0.58 - distance), uncertainty=rows, kind="sigma_xy")
    dist = intersect_prob(REGISTRY, pred, ANCHOR, v_min=0.15, draws=common_draws(20000, seed=5))
    expected = 1 - norm.cdf(distance / s)
    assert dist.probability == pytest.approx(expected, abs=0.01)
    assert dist.zone_probability("snare") == pytest.approx(dist.probability)
    if distance == 0.0:  # antithetic pairs: exactly half of the draws have z_y > 0
        assert dist.probability == 0.5
        assert intersect_prob(REGISTRY, pred, ANCHOR, v_min=0.15, draws=common_draws(32)).probability == 0.5


def test_independent_draws_and_draw_shapes():
    rows = tuple((0.0, 0.01) for _ in range(4))
    pred = prediction(vertical(0.575), uncertainty=rows, kind="sigma_xy")
    shared = intersect_prob(REGISTRY, pred, ANCHOR, v_min=0.15, draws=common_draws(64))
    independent = intersect_prob(REGISTRY, pred, ANCHOR, v_min=0.15, draws=common_draws(64, steps=4))
    assert 0 < shared.probability < 1 and 0 < independent.probability < 1
    assert common_draws(8).shape == (8, 2) and common_draws(8, steps=3).shape == (8, 3, 2)
    np.testing.assert_array_equal(common_draws(8)[:4], -common_draws(8)[4:])
    with pytest.raises(ValueError, match="even"):
        common_draws(7)
    with pytest.raises(ValueError, match="draws"):
        sample_trajectories(pred, ANCHOR)


def test_member_and_mixture_layouts_have_exact_probabilities():
    down, up = np.asarray(vertical(0.62)), np.asarray(vertical(0.45))
    mean = (2 * down + up) / 3
    members = [down - mean, down - mean, up - mean]
    rows = tuple(tuple(np.concatenate([m[j] for m in members])) for j in range(4))
    dist = intersect_prob(REGISTRY, prediction(mean, uncertainty=rows, kind="members_xy"), ANCHOR, v_min=0.15)
    assert dist.probability == pytest.approx(2 / 3) and dist.samples == 3
    # Mixture: the point trajectory is the most probable mode (upwards, w = 0.7); the other crosses.
    offsets = down - up
    mixture = tuple((0.3, *offsets[j], 0.7, 0.0, 0.0) for j in range(4))
    dist = intersect_prob(
        REGISTRY, prediction(up, uncertainty=mixture, kind="mixture_xy"), ANCHOR, v_min=0.15
    )
    assert dist.probability == pytest.approx(0.3) and dict(dist.by_zone) == {"snare": pytest.approx(0.3)}
    bad = tuple((0.3, *offsets[j], 0.6, 0.0, 0.0) for j in range(4))
    with pytest.raises(ValueError, match="probability vector"):
        intersect_prob(REGISTRY, prediction(up, uncertainty=bad, kind="mixture_xy"), ANCHOR, v_min=0.15)


def test_two_rate_offsets_are_intersected_as_given():
    offsets = (0.02, 0.04, 0.08)
    pred = prediction([(0.40, 0.52), (0.40, 0.54), (0.40, 0.62)], offsets=offsets)
    candidate = GeometryEngine(REGISTRY, v_min=0.15).intersect_prediction(pred, current_position=ANCHOR)
    dist = intersect_prob(REGISTRY, pred, ANCHOR, v_min=0.15)
    # Crossing y = 0.58 lies on the coarse last segment (0.54 -> 0.62 over 0.04 s): t = 0.04 + 0.02.
    assert candidate.tti == pytest.approx(0.06) and dist.tti_quantiles_s[1] == pytest.approx(0.06)


def _candidate(pred, **changes):
    candidate = GeometryEngine(REGISTRY, v_min=0.15, session_id="gate").intersect_prediction(
        pred, current_position=ANCHOR, source="MODEL", t_candidate=10.0
    )
    return replace(candidate, **changes) if changes else candidate


def test_gate_only_relabels_existing_geometry_candidates():
    rows = tuple((0.0, 0.01 * (j + 1) / 4) for j in range(4))
    pred = prediction(vertical(0.57), uncertainty=rows, kind="sigma_xy")
    gate = CrossingProbabilityGate(REGISTRY, v_min=0.15, anchor_of=lambda _p: ANCHOR, samples=4000)
    assert gate(pred, None) == (pred, None)  # nothing to gate, nothing created
    crossing = prediction(vertical(0.62), uncertainty=rows, kind="sigma_xy")
    candidate = _candidate(crossing)
    out_pred, out = gate(crossing, candidate)
    assert out_pred is crossing and out.candidate_id == candidate.candidate_id
    assert replace(out, strike_probability=None) == replace(candidate, strike_probability=None)
    assert out.strike_probability == pytest.approx(1 - norm.cdf(-0.04 / 0.01), abs=1e-3)
    assert gate.log[-1]["strike_probability"] == out.strike_probability
    with pytest.raises(ValueError, match="geometry-derived"):
        gate(crossing, replace(candidate, derivation="DIRECT_HEAD"))
    with pytest.raises(ValueError, match="predictive distribution"):
        gate(prediction(vertical(0.62)), candidate)


def test_gate_zone_probability_uses_the_candidate_zone():
    # A wide x spread sends some samples beside the snare; only the candidate zone's share counts.
    rows = tuple((0.2 * (j + 1) / 4, 0.0) for j in range(4))
    pred = prediction(vertical(0.62), uncertainty=rows, kind="sigma_xy")
    gate = CrossingProbabilityGate(REGISTRY, v_min=0.15, anchor_of=lambda _p: ANCHOR, samples=2000)
    _, out = gate(pred, _candidate(pred))
    dist = gate.distribution(pred)
    assert out.strike_probability == pytest.approx(dist.zone_probability("snare"))
    assert out.strike_probability < 1.0 and math.isclose(sum(dict(dist.by_zone).values()), dist.probability)
    assert isinstance(out, StrikeCandidate)
