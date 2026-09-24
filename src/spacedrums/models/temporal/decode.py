"""Displacements become a time-stamped trajectory, never a strike."""

import math

import numpy as np

from spacedrums.contracts import TrajectoryAux, TrajectoryPrediction


def decode(
    track, displacements, *, dt_step, anticipator_id, model_hash, probability=None, inference_done=None
):
    delta = np.asarray(displacements, dtype=float)
    if delta.ndim != 2 or delta.shape[1] != 2 or not len(delta) or not np.isfinite(delta).all():
        raise ValueError("finite [K,2] displacements required")
    if not math.isfinite(dt_step) or dt_step <= 0 or track.tip_filtered is None:
        raise ValueError("positive time step and current tip required")
    positions = delta + np.asarray(track.tip_filtered)
    return TrajectoryPrediction(
        frame_id=track.frame_id,
        t_capture=track.t_capture,
        hand_id=track.hand_id,
        anticipator_id=anticipator_id,
        model_hash=model_hash,
        K=len(delta),
        dt_step=dt_step,
        t_offsets_s=None,
        positions=tuple(map(tuple, positions)),
        velocities=None,
        uncertainty=None,
        uncertainty_kind=None,
        aux=TrajectoryAux(strike_prob_within_H=probability),
        t_inference_done=track.t_capture if inference_done is None else inference_done,
    )
