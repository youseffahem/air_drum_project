from dataclasses import replace

import numpy as np
import pytest
import torch

from spacedrums.commit import CommitSettings
from spacedrums.config import load_config
from spacedrums.contracts import Anticipator, TrackState
from spacedrums.contracts.schema import validate
from spacedrums.eval.replay import replay
from spacedrums.features.batch import build_features
from spacedrums.features.schema import FeatureSchema
from spacedrums.geometry import ZoneRegistry
from spacedrums.models.temporal import TemporalConfig, build_model
from spacedrums.models.temporal.adapter import TemporalAnticipator


def track(i, y, hand="LEFT", status="VALID"):
    live = status in ("VALID", "DEGRADED")
    return TrackState(
        i,
        10 + i * 0.02,
        hand,
        status,
        "synthetic",
        None,
        (0.4, y) if live else None,
        (0.0, 1.0) if live else None,
        (0.0, 0.0) if live else None,
        None,
        None,
        1.0,
        0 if status == "VALID" else 1,
        10 + i * 0.02,
        None,
        None,
    )


def adapter(family="gru", stateful=False, crossing=True, auxiliary=False):
    c = TemporalConfig(family, 56, n=2, k=4, dt_step=0.02, hidden=8, auxiliary=auxiliary)
    model = build_model(c).eval()
    # Controlled analytic trajectory; verifies the route, not learned accuracy.
    with torch.no_grad():
        model.head.trajectory.weight.zero_()
        model.head.trajectory.bias.copy_(
            torch.tensor([0.0, 0.05, 0.0, 0.1, 0.0, 0.15, 0.0, 0.2]) * (1 if crossing else -1)
        )
        if auxiliary:
            model.head.aux.weight.zero_()
            model.head.aux.bias.fill_(10)
    manifest = {
        "family": family,
        "N": 2,
        "K": 4,
        "F": 56,
        "dt_step": 0.02,
        "config": c.to_dict(),
        "checkpoint_hash": "sha256:" + "1" * 64,
    }
    return TemporalAnticipator(model, manifest, stateful=stateful)


@pytest.mark.parametrize("family", ["gru", "tcn"])
def test_decode_schema_and_per_hand_gaps(family):
    a = adapter(family, stateful=family == "gru")
    assert isinstance(a, Anticipator)
    assert a.predict([]) is None
    features = (np.ones((2, 56)), np.ones((2, 56), bool))
    left = [track(i, 0.5) for i in range(2)]
    right = [track(i, 0.5, hand="RIGHT") for i in range(2)]
    first = a.predict(left, features)
    validate("trajectory-prediction", first.to_dict())
    assert first.positions[-1][1] == pytest.approx(0.7)
    assert first.sample_times()[-1] == pytest.approx(10.1)
    a.predict(right, features)
    assert a.predict([track(2, 0.5, status="INVALID")], features) is None
    if family == "gru":
        assert "LEFT" not in a.states and "RIGHT" in a.states
    assert a.predict(right, features) is None  # repeated timestamp is refused


@pytest.mark.parametrize("family", ["gru", "tcn"])
@pytest.mark.parametrize("crossing", [False, True])
def test_model_harness_geometry_only_and_future_invariance(family, crossing):
    cfg = load_config("configs/prototype.candidate.yaml")
    schema, registry = FeatureSchema(cfg["zones"]), ZoneRegistry.from_config(cfg["zones"])
    tracks = [track(i, 0.505 + i * 0.02) for i in range(8)]
    changed = tracks[:4] + [track(i, 0.4) for i in range(4, 8)]

    def run(sequence):
        return replay(
            sequence,
            arm="MODEL:C-" + family.upper(),
            registry=registry,
            commit_settings=replace(CommitSettings.from_config(cfg), p_commit=0.5, n_confirm_frames=0),
            v_min=0.15,
            session_id="synthetic-temporal",
            model=adapter(family, crossing=crossing, auxiliary=True),
            feature_schema=schema,
            feature_window_n=2,
            feature_records=build_features(sequence, schema),
        )

    result, future = run(tracks), run(changed)
    assert bool(result.candidates) == crossing  # high auxiliary probability alone cannot create strikes
    assert [c.to_dict() for c in result.committed if c.frame_id < 4] == [
        c.to_dict() for c in future.committed if c.frame_id < 4
    ]
    if crossing:
        assert result.committed
    for c in result.candidates:
        validate("strike-candidate", c.to_dict())
        assert c.source == "MODEL" and c.derivation == "GEOMETRY"
        assert c.crossing_velocity[1] == pytest.approx(2.5)
    for c in result.committed:
        validate("committed-strike", c.to_dict())


def test_temporal_arm_rejects_direct_strikes():
    cfg = load_config("configs/prototype.candidate.yaml")
    from spacedrums.contracts import StrikeCandidate

    candidate = StrikeCandidate(
        "synthetic",
        0,
        10.0,
        "LEFT",
        "snare",
        "MODEL",
        "DIRECT_HEAD",
        "fake",
        10.02,
        None,
        0.02,
        (0.4, 0.58),
        (0.0, 1.0),
        1.0,
        1.0,
        10.0,
    )
    with pytest.raises(ValueError, match="trajectory"):
        replay(
            [track(0, 0.5)],
            arm="MODEL:C-GRU",
            registry=ZoneRegistry.from_config(cfg["zones"]),
            commit_settings=CommitSettings.from_config(cfg),
            v_min=0.15,
            session_id="synthetic",
            model=lambda *_: candidate,
        )


def test_injected_feature_assembler_matches_offline_windows_through_gaps(fold):
    from collections import defaultdict, deque

    from spacedrums.features.normalize import NormStats
    from spacedrums.features.streaming import StreamingFeatures, history_arrays
    from spacedrums.models.temporal.data import load_fold

    path, sessions, _ = fold
    c = TemporalConfig("gru", 56, n=4, k=3)
    _, _, stats_data = load_fold(path, c)
    stats = NormStats(stats_data)
    session, model = sessions[0], build_model(c).eval()
    m = {
        "family": "gru",
        "N": 4,
        "K": 3,
        "F": 56,
        "dt_step": c.dt_step,
        "config": c.to_dict(),
        "checkpoint_hash": "sha256:" + "2" * 64,
        "feature_schema_hash": session.schema.fingerprint,
        "fold": 0,
    }
    online = TemporalAnticipator(
        model, m, feature_stream=StreamingFeatures(session.schema, history_n=4), stats=stats
    )
    offline = TemporalAnticipator(model, m)
    histories, rings = defaultdict(lambda: deque(maxlen=4)), defaultdict(lambda: deque(maxlen=4))
    count = 0
    for t, f in zip(session.tracks, session.table.records, strict=True):
        histories[t.hand_id].append(t)
        rings[t.hand_id].append(f)
        history = list(histories[t.hand_id])
        arrays = (
            stats.apply(*history_arrays(list(rings[t.hand_id]), session.schema), session.schema)
            if len(history) == 4
            else None
        )
        a, b = online.predict(history), offline.predict(history, arrays)
        assert (a is None) == (b is None)
        if a is not None:
            np.testing.assert_allclose(a.positions, b.positions, rtol=1e-5, atol=1e-6)
            count += 1
    assert count > 0
