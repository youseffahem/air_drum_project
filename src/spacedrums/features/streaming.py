"""Per-hand bounded feature ring and shared history assembly."""

from collections import defaultdict, deque

import numpy as np

from spacedrums.features.core import FeatureCore


def history_arrays(records, schema):
    if not records:
        return np.zeros((0, schema.dimension)), np.zeros((0, schema.dimension), dtype=bool)
    if any(
        r.feature_schema_id != schema.feature_schema_id or len(r.values) != schema.dimension for r in records
    ):
        raise ValueError("feature schema mismatch")
    x = np.asarray([r.values for r in records], dtype=float)
    mask = np.asarray([r.mask for r in records], dtype=bool)
    if "window_elapsed" in schema.index:
        j = schema.index["window_elapsed"]
        for i, r in enumerate(records):
            if r.track_status in ("VALID", "DEGRADED"):
                x[i, j], mask[i, j] = r.t_capture - records[0].t_capture, True
    return x, mask


class StreamingFeatures:
    def __init__(self, schema, *, history_n=32):
        if type(history_n) is not int or history_n < 1:
            raise ValueError("history_n must be a positive integer")
        self.schema, self.history_n = schema, history_n
        self.core = FeatureCore(schema)
        self.rings = defaultdict(lambda: deque(maxlen=history_n))

    def update(self, track, **observations):
        result = self.core.update(track, **observations)
        self.rings[str(track.hand_id)].append(result)
        return result

    def window(self, hand_id, *, n=None, stats=None):
        n = self.history_n if n is None else n
        if not 1 <= n <= self.history_n:
            raise ValueError("window exceeds ring capacity")
        rows = list(self.rings[str(hand_id)])[-n:]
        if len(rows) != n:
            return None
        x, m = history_arrays(rows, self.schema)
        if stats is not None:
            x, m = stats.apply(x, m, self.schema)
        return x, m

    def reset(self, hand_id=None):
        self.core.reset(hand_id)
        if hand_id is None:
            self.rings.clear()
        else:
            self.rings.pop(str(hand_id), None)
