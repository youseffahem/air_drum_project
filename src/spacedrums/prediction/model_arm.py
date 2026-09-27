"""Causal live wrapper around the injected Phase 10 adapter; shared weights, per-hand windows."""

import math
from collections import defaultdict, deque
from dataclasses import replace

from spacedrums.contracts import CandidateSource
from spacedrums.timing import now


class ModelArm:
    source = CandidateSource.MODEL

    def __init__(self, adapter, feature_stream, stats, *, clock=now):
        self.adapter, self.stream, self.stats, self.clock = adapter, feature_stream, stats, clock
        self.manifest = adapter.manifest
        self.model_id = self.manifest["model_id"]
        self.histories = defaultdict(lambda: deque(maxlen=adapter.n))
        self.features = {}
        self.stamps = {}
        self.predictions = 0

    def declared_history(self):
        return self.adapter.declared_history()

    def reset(self, reason=None):
        self.adapter.reset(reason)
        self.stream.reset()
        self.histories.clear()
        self.features.clear()
        self.stamps.clear()

    def predict(self, track_history, features=None):
        """Anticipator interface for a delivered TrackState history."""
        if not track_history:
            return None
        return self.step(track_history[-1], delivered_t=track_history[-1].t_capture)

    def step(self, track, *, delivered_t, hand=None, stick=None, frame=None):
        if track.t_capture > delivered_t:
            raise AssertionError("model cannot see a future frame")
        h = track.hand_id
        if track.reset_reason is not None:
            self.histories[h].clear()
            self.stream.reset(h)
            self.adapter._reset_hand(h)
        if track.status not in ("VALID", "DEGRADED"):
            self.histories[h].clear()
            self.stream.rings[str(h)].clear()
            self.adapter._reset_hand(h)
        self.histories[h].append(track)
        assert all(t.t_capture <= delivered_t for t in self.histories[h]), "future history"
        record = self.stream.update(track, hand=hand, stick=stick, frame=frame)
        self.features[h] = record
        window = self.stream.window(h, stats=self.stats)
        done = self.clock()
        try:
            pred = self.adapter.predict(tuple(self.histories[h]), window)
        finally:
            end = self.clock()
            self.stamps[h] = {
                "t_features_done": done,
                "t_inference_done": end,
                "inference_s": max(0.0, end - done),
            }
        if pred is not None:
            check_finite(pred)
            self.predictions += 1
            pred = replace(pred, t_inference_done=end)
        return pred


def check_finite(pred):
    """Phase 17: a corrupt model must fail loudly (fallback), not go silent or pass a NaN gate."""
    values = [v for p in pred.positions for v in p]
    aux = pred.aux
    for name in ("strike_prob_within_H", "intensity_proxy", "tti"):
        value = getattr(aux, name, None) if aux is not None else None
        if value is not None:
            values.append(value)
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError("model produced a non-finite prediction")
