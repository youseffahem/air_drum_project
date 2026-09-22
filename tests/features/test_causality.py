"""TEST-CAUSAL-1/2 and property checks, SYNTHETIC records; exact comparisons."""

from dataclasses import replace

import numpy as np
import pytest

from spacedrums.features.batch import build_features
from spacedrums.features.groups import GROUPS
from spacedrums.features.schema import FeatureSchema
from spacedrums.features.streaming import StreamingFeatures


@pytest.mark.parametrize("variant", ["REMOVED", "GARBAGE", "SHIFTED"])
@pytest.mark.parametrize("jerk", [False, True])
def test_causal_1_future_perturbation(schema, track_factory, variant, jerk):
    if jerk:
        schema = FeatureSchema(schema.zones_config, groups=GROUPS)
    tracks = [
        track_factory(i, hand=hand, tip_acceleration=None, status="INVALID" if i in (10, 11) else "VALID")
        for i in range(30)
        for hand in ("LEFT", "RIGHT")
    ]
    baseline = build_features(tracks, schema)
    for cut in (0, 9, 10, 11, 12, 20, 28):
        prefix = [t for t in tracks if t.frame_id <= cut]
        suffix = [t for t in tracks if t.frame_id > cut]
        if variant == "REMOVED":
            suffix = []
        else:
            offset = 42.0 if variant == "GARBAGE" else -0.7
            suffix = [
                replace(t, tip_filtered=(offset, offset), tip_velocity=(-9.0, 12.0)) if t.tip_filtered else t
                for t in suffix
            ]
        assert build_features(prefix + suffix, schema)[: len(prefix)] == baseline[: len(prefix)]


@pytest.mark.parametrize("jerk", [False, True])
def test_causal_2_history_bound_and_negative_control(schema, track_factory, jerk):
    if jerk:
        schema = FeatureSchema(schema.zones_config, groups=GROUPS)
    tracks = [track_factory(i, tip_velocity=(i * i * 0.001, 0.2), tip_acceleration=None) for i in range(30)]
    baseline = build_features(tracks, schema)
    n = schema.descriptor()["core_history_n"]
    for i in (8, 15, 24, 29):
        assert build_features(tracks[i - n + 1 : i + 1], schema)[-1] == baseline[i]
        assert build_features(tracks[i - n + 2 : i + 1], schema)[-1] != baseline[i]


def test_property_random_gaps_hands_finite_masks_parity(schema, track_factory):
    rng = np.random.default_rng(8001)
    tracks = []
    clock = 100.0
    for i in range(100):
        clock += float(rng.uniform(0.005, 0.08))
        for hand in ("LEFT", "RIGHT"):
            status = rng.choice(["VALID", "DEGRADED", "INVALID", "STALE"])
            tracks.append(track_factory(i, hand=hand, status=status, t_capture=clock))
    batch = build_features(tracks, schema)
    stream = StreamingFeatures(schema, history_n=8)
    online = [stream.update(t) for t in tracks]
    assert batch == online
    for r in online:
        assert np.isfinite(r.values).all()
        assert all(v == 0 for v, m in zip(r.values, r.mask, strict=True) if not m)
    assert all(len(ring) == 8 for ring in stream.rings.values())
    assert stream.window("RIGHT")[0].shape == (8, schema.dimension)
    stream.reset()
    assert stream.window("RIGHT") is None
