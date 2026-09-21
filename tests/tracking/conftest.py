"""Shared SYNTHETIC observation sequences for the tracking tests (labelled synthetic; never evidence).

A sequence is a list of ``(t_capture, HandObservation, StickObservation)`` triples for one hand.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from spacedrums.contracts import HandId, HandObservation, StickObservation, TipMethod

DT = 1 / 30.0


def hand_obs(frame_id: int, t: float, hand: HandId = HandId.RIGHT, present: bool = True) -> HandObservation:
    if not present:
        return HandObservation.absent(frame_id, t, hand, "synthetic")
    lm = tuple((0.4 + 0.005 * i, 0.7 + 0.003 * i) for i in range(21))
    return HandObservation(frame_id=frame_id, t_capture=t, hand_id=hand, present=True,
                           detector_id="synthetic", landmarks=lm, landmark_visibility=None,
                           handedness_score=0.95, bbox=(0.4, 0.7, 0.1, 0.1))


def stick_obs(frame_id: int, t: float, tip, conf: float, hand: HandId = HandId.RIGHT,
              axis_dir=(0.0, -1.0), method: TipMethod = TipMethod.GEOM) -> StickObservation:
    if tip is None:
        return StickObservation.absent(frame_id, t, hand, method)
    return StickObservation(frame_id=frame_id, t_capture=t, hand_id=hand, present=True, method_id=method,
                            axis_origin=(0.4, 0.7), axis_dir=axis_dir, tip=(float(tip[0]), float(tip[1])),
                            tip_confidence=conf, axis_confidence=min(1.0, conf + 0.05), stick_length_est=0.27)


def constant_velocity_truth(n: int, v=(0.3, -0.2), p0=(0.2, 0.8), dt: float = DT):
    return [(p0[0] + v[0] * k * dt, p0[1] + v[1] * k * dt) for k in range(n)]


def parabolic_truth(n: int, a=(0.0, 6.0), v0=(0.4, -1.5), p0=(0.2, 0.7), dt: float = DT):
    out = []
    for k in range(n):
        t = k * dt
        out.append((p0[0] + v0[0] * t + 0.5 * a[0] * t * t, p0[1] + v0[1] * t + 0.5 * a[1] * t * t))
    return out


def make_sequence(truth, conf: float = 0.9, noise: float = 0.0, seed: int = 0, dt: float = DT,
                  t0: float = 100.0, gaps: set[int] | None = None, low_conf: dict[int, float] | None = None,
                  hand: HandId = HandId.RIGHT, jitter_dt: float = 0.0):
    """Observations along ``truth`` with optional gaps (absent frames) and per-frame confidences."""
    rng = np.random.default_rng(seed)
    seq = []
    t = t0
    for k, p in enumerate(truth):
        if k > 0:
            t += dt + (rng.uniform(-jitter_dt, jitter_dt) if jitter_dt else 0.0)
        c = (low_conf or {}).get(k, conf)
        if gaps and k in gaps:
            seq.append((t, hand_obs(k, t, hand, present=False), stick_obs(k, t, None, 0.0, hand)))
            continue
        z = (p[0] + rng.normal(0, noise), p[1] + rng.normal(0, noise)) if noise else p
        ang = -math.pi / 2 + 0.3 * math.sin(k / 10)
        seq.append((t, hand_obs(k, t, hand),
                    stick_obs(k, t, z, c, hand, axis_dir=(math.cos(ang), math.sin(ang)))))
    return seq


@pytest.fixture
def cv_sequence():
    return make_sequence(constant_velocity_truth(60), noise=0.004, seed=1)


@pytest.fixture
def parabolic_sequence():
    return make_sequence(parabolic_truth(60), noise=0.004, seed=2)
