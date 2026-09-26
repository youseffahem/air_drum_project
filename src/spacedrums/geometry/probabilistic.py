"""Probabilistic companion of the deterministic impact test (Phase 12, E4/E2c; ADR-0034).

``intersect.py`` is unchanged and stays the only source of candidates. Here a predicted distribution
over trajectories, read from ``TrajectoryPrediction.uncertainty``, becomes weighted sample polylines
from the current tip, and the unchanged ``first_impact`` is applied to each one exactly as
``GeometryEngine.intersect`` does (earliest impact over the hand's zones, zone id breaking ties).
The result is a crossing probability per zone and a distribution of predicted impact times.
``CrossingProbabilityGate`` may only relabel an existing geometry candidate's
``strike_probability``; the unchanged Phase 05 ``p_commit`` then gates it. It never creates one.

Layouts (``uncertainty_kind``; rows are per output step):

- ``sigma_xy``: ``(std_x, std_y)`` of an independent-axis Gaussian around ``positions``;
- ``members_xy``: ``(dx_1, dy_1, ..., dx_M, dy_M)`` member offsets from ``positions``, equal weights;
- ``mixture_xy``: ``(w_1, dx_1, dy_1, ..., w_M, dx_M, dy_M)`` mode weights and offsets.

Gaussian samples use common random numbers: S antithetic standard-normal draws, fixed by a seed, and
by default one draw per sample shared by every step ("shared": errors along one sampled trajectory
are fully correlated). "independent" draws a fresh normal per step.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np

from spacedrums.contracts import CandidateDerivation, HandId, StrikeCandidate, TrajectoryPrediction
from spacedrums.geometry.intersect import TrajectoryPoint, first_impact
from spacedrums.geometry.zones import Point, ZoneRegistry

LAYOUTS = ("sigma_xy", "members_xy", "mixture_xy")
CORRELATIONS = ("shared", "independent")


def common_draws(samples: int = 32, *, seed: int = 1212, steps: int | None = None) -> np.ndarray:
    """Antithetic standard-normal draws: [S,2] (shared) or [S,K,2] (independent, ``steps`` = K)."""
    if samples < 2 or samples % 2:
        raise ValueError("an even number of at least two samples is required (antithetic pairs)")
    shape = (samples // 2, 2) if steps is None else (samples // 2, steps, 2)
    half = np.random.default_rng(seed).standard_normal(shape)
    return np.concatenate((half, -half))


@dataclass(frozen=True)
class CrossingDistribution:
    """Weighted outcome of the impact test over sampled trajectories."""

    probability: float
    by_zone: tuple[tuple[str, float], ...]
    tti_quantiles_s: tuple[float, float, float] | None  # (q10, q50, q90) of crossing samples
    samples: int

    def zone_probability(self, zone_id: str) -> float:
        return dict(self.by_zone).get(zone_id, 0.0)

    def to_dict(self) -> dict:
        return {
            "probability": self.probability,
            "by_zone": dict(self.by_zone),
            "tti_quantiles_s": None if self.tti_quantiles_s is None else list(self.tti_quantiles_s),
            "samples": self.samples,
        }


def sample_trajectories(
    prediction: TrajectoryPrediction, current_position: Point, *, draws: np.ndarray | None = None
) -> list[tuple[float, tuple[TrajectoryPoint, ...]]]:
    """Weighted polylines from the current tip; a prediction without a layout is one certain sample."""
    times = prediction.sample_times()
    positions = np.asarray(prediction.positions, dtype=float)
    k, kind = prediction.K, prediction.uncertainty_kind
    rows = None if prediction.uncertainty is None else np.asarray(prediction.uncertainty, dtype=float)
    if kind is None:
        weighted = [(1.0, positions)]
    elif kind == "sigma_xy":
        if draws is None or rows.shape != (k, 2) or (rows < 0).any():
            raise ValueError("sigma_xy needs [K,2] nonnegative rows and standard-normal draws")
        z = draws[:, None, :] if draws.ndim == 2 else draws
        if z.shape[1:] not in ((1, 2), (k, 2)):
            raise ValueError("draws must be [S,2] (shared) or [S,K,2] (independent)")
        weighted = [(1.0 / len(z), positions + rows * sample) for sample in z]
    elif kind == "members_xy":
        if rows.shape[0] != k or rows.shape[1] % 2:
            raise ValueError("members_xy rows must hold (dx, dy) per member")
        members = rows.reshape(k, -1, 2).transpose(1, 0, 2)
        weighted = [(1.0 / len(members), positions + offset) for offset in members]
    elif kind == "mixture_xy":
        if rows.shape[0] != k or rows.shape[1] % 3:
            raise ValueError("mixture_xy rows must hold (w, dx, dy) per mode")
        modes = rows.reshape(k, -1, 3)
        weights = modes[0, :, 0]
        if (weights < 0).any() or not math.isclose(float(weights.sum()), 1.0, abs_tol=1e-6):
            raise ValueError("mixture weights must be a probability vector")
        if not np.allclose(modes[:, :, 0], weights[None], atol=1e-9):
            raise ValueError("mixture weights must repeat on every step")
        weighted = [(float(w), positions + modes[:, m, 1:]) for m, w in enumerate(weights)]
    else:
        raise ValueError(f"unknown uncertainty layout {kind!r}; expected one of {LAYOUTS}")
    anchor = TrajectoryPoint(prediction.t_capture, (float(current_position[0]), float(current_position[1])))

    def polyline(path):
        return (
            anchor,
            *(TrajectoryPoint(t, (float(p[0]), float(p[1]))) for t, p in zip(times, path, strict=True)),
        )

    return [(weight, polyline(path)) for weight, path in weighted]


def _weighted_quantiles(values, weights, quantiles):
    order = np.argsort(values, kind="stable")
    values, weights = np.asarray(values)[order], np.asarray(weights)[order]
    cumulative = np.cumsum(weights) / weights.sum()
    return tuple(
        float(values[min(np.searchsorted(cumulative, q - 1e-12), len(values) - 1)]) for q in quantiles
    )


def crossing_distribution(
    registry: ZoneRegistry,
    trajectories: list[tuple[float, tuple[TrajectoryPoint, ...]]],
    *,
    hand_id: HandId | str,
    v_min: float,
) -> CrossingDistribution:
    if not trajectories:
        raise ValueError("at least one sampled trajectory is required")
    hand = HandId(hand_id)
    zones = [zone for zone in registry if hand in zone.allowed_hands]
    total = math.fsum(weight for weight, _ in trajectories)
    if not total > 0:
        raise ValueError("sample weights must sum to a positive value")
    by_zone: dict[str, list[float]] = {}
    times, weights = [], []
    for weight, path in trajectories:
        impacts = [impact for zone in zones if (impact := first_impact(path, zone, v_min)) is not None]
        if not impacts:
            continue
        impact = min(impacts, key=lambda item: (item.t_cross, item.zone.zone_id))
        by_zone.setdefault(impact.zone.zone_id, []).append(weight)
        times.append(impact.t_cross - path[0].t)
        weights.append(weight)
    # Exactly rounded sums: equal-weight samples give exact fractions (e.g. 1/2, 2/3).
    shares = {zone: min(1.0, math.fsum(values) / total) for zone, values in by_zone.items()}
    return CrossingDistribution(
        probability=min(1.0, math.fsum(weights) / total),
        by_zone=tuple(sorted(shares.items())),
        tti_quantiles_s=_weighted_quantiles(times, weights, (0.1, 0.5, 0.9)) if times else None,
        samples=len(trajectories),
    )


def intersect_prob(
    registry: ZoneRegistry,
    prediction: TrajectoryPrediction,
    current_position: Point,
    *,
    v_min: float,
    draws: np.ndarray | None = None,
) -> CrossingDistribution:
    """Probabilistic variant of ``GeometryEngine.intersect_prediction`` (deterministic path unchanged)."""
    return crossing_distribution(
        registry,
        sample_trajectories(prediction, current_position, draws=draws),
        hand_id=prediction.hand_id,
        v_min=v_min,
    )


class CrossingProbabilityGate:
    """Post-geometry relabelling (replay ``candidate_gate``): the candidate zone's crossing probability
    becomes ``strike_probability``. The prediction's current tip comes from ``anchor_of`` (the caller
    records it at prediction time: same frame, causal)."""

    def __init__(
        self,
        registry: ZoneRegistry,
        *,
        v_min: float,
        anchor_of: Callable[[TrajectoryPrediction], Point],
        samples: int = 32,
        seed: int = 1212,
        correlation: str = "shared",
    ) -> None:
        if correlation not in CORRELATIONS:
            raise ValueError(f"correlation must be one of {CORRELATIONS}")
        self.registry, self.v_min, self.anchor_of = registry, float(v_min), anchor_of
        self.samples, self.seed, self.correlation = samples, seed, correlation
        self._draws: dict[int | None, np.ndarray] = {}
        self._cache: dict[tuple[str, int, float], CrossingDistribution] = {}
        self.log: list[dict] = []

    def draws(self, k: int) -> np.ndarray:
        steps = k if self.correlation == "independent" else None
        if steps not in self._draws:
            self._draws[steps] = common_draws(self.samples, seed=self.seed, steps=steps)
        return self._draws[steps]

    def distribution(self, prediction: TrajectoryPrediction) -> CrossingDistribution:
        key = (str(prediction.hand_id), prediction.frame_id, prediction.t_capture)
        if key not in self._cache:
            self._cache[key] = intersect_prob(
                self.registry,
                prediction,
                self.anchor_of(prediction),
                v_min=self.v_min,
                draws=self.draws(prediction.K),
            )
        return self._cache[key]

    def __call__(
        self, prediction: TrajectoryPrediction, candidate: StrikeCandidate | None
    ) -> tuple[TrajectoryPrediction, StrikeCandidate | None]:
        if candidate is None:
            return prediction, None
        if candidate.derivation is not CandidateDerivation.GEOMETRY:
            raise ValueError("crossing probabilities relabel geometry-derived candidates only")
        if prediction.uncertainty is None:
            raise ValueError("the crossing-probability gate needs a predictive distribution")
        distribution = self.distribution(prediction)
        probability = min(1.0, max(0.0, distribution.zone_probability(candidate.zone_id)))
        self.log.append(
            {
                "frame_id": candidate.frame_id,
                "hand_id": str(candidate.hand_id),
                "candidate_id": candidate.candidate_id,
                "zone_id": candidate.zone_id,
                "crossing": distribution.to_dict(),
                "strike_probability": probability,
            }
        )
        return prediction, replace(candidate, strike_probability=probability)


__all__ = [
    "CORRELATIONS",
    "LAYOUTS",
    "CrossingDistribution",
    "CrossingProbabilityGate",
    "common_draws",
    "crossing_distribution",
    "intersect_prob",
    "sample_trajectories",
]
