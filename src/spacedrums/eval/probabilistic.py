"""Phase 12 evaluation helpers for probabilistic trajectory outputs (E4, E2c).

``AnchorRecorder`` wraps a replay model function and remembers the current tip of every prediction
it returns (same frame, therefore causal), so ``geometry.probabilistic.CrossingProbabilityGate`` can
start sampled trajectories where the deterministic geometry starts them. ``calibration`` scores a
crossing probability against an observed binary outcome; it decides nothing.
"""

from __future__ import annotations

import numpy as np

from spacedrums.contracts import TrajectoryPrediction


class AnchorRecorder:
    def __init__(self, model_fn):
        self.model_fn, self.anchors = model_fn, {}

    def __call__(self, track, history, window):
        output = self.model_fn(track, history, window)
        if isinstance(output, TrajectoryPrediction):
            if track.tip_filtered is None or output.frame_id != track.frame_id:
                raise ValueError("a prediction must belong to the current frame with a current tip")
            self.anchors[(str(output.hand_id), output.frame_id, output.t_capture)] = tuple(track.tip_filtered)
        return output

    def anchor(self, prediction):
        return self.anchors[(str(prediction.hand_id), prediction.frame_id, prediction.t_capture)]

    def reset(self, reason=None):
        reset = getattr(self.model_fn, "reset", None)
        if reset is not None:
            reset(reason)


def calibration(probabilities, outcomes, *, bins=10):
    """Reliability table (equal-width bins), expected calibration error, Brier score and ROC-AUC."""
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if p.shape != y.shape or ((p < 0) | (p > 1)).any() or not np.isin(y, (0, 1)).all():
        raise ValueError("probabilities in [0,1] and binary outcomes of equal length required")
    n = len(p)
    out = {"n": n, "positives": int(y.sum()), "bins": []}
    if not n:
        return {**out, "ece": None, "brier": None, "roc_auc": None}
    index = np.minimum((p * bins).astype(int), bins - 1)
    ece = 0.0
    for b in range(bins):
        rows = index == b
        count = int(rows.sum())
        row = {"lower": b / bins, "upper": (b + 1) / bins, "n": count}
        if count:
            row.update(mean_probability=float(p[rows].mean()), observed_rate=float(y[rows].mean()))
            ece += count / n * abs(row["mean_probability"] - row["observed_rate"])
        out["bins"].append(row)
    positives = int(y.sum())
    auc = None
    if 0 < positives < n:
        from scipy.stats import rankdata

        ranks = rankdata(p)
        auc = float((ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * (n - positives)))
    return {**out, "ece": float(ece), "brier": float(np.mean((p - y) ** 2)), "roc_auc": auc}
