from __future__ import annotations

from dataclasses import replace

from test_harness import _config, _track

from spacedrums.commit import CommitSettings
from spacedrums.eval.replay import replay
from spacedrums.features.batch import build_features
from spacedrums.features.schema import FeatureSchema
from spacedrums.models.gbdt.adapter import GBDTAdapter


class FakePredictor:
    manifest = {"trajectory_steps": 4}
    model_hash = "sha256:" + "1" * 64

    def predict(self, x, mask):
        assert x.shape == mask.shape == (2, 56)
        return {
            "strike_probability": 1.0,
            "tti": 0.04,
            "zone_id": "snare",
            "displacements": {1: (0.0, 0.10), 3: (0.0, 0.20)},
        }


def test_model_modes_and_future_perturbation():
    cfg, registry = _config()
    schema = FeatureSchema(cfg["zones"])
    settings = replace(CommitSettings.from_config(cfg), p_commit=0.5, n_confirm_frames=0)
    tracks = [_track(i, 0.505 + i * 0.02) for i in range(8)]
    changed = tracks[:4] + [_track(i, 0.4, x=0.9) for i in range(4, 8)]
    for mode in ("direct", "trajectory"):
        adapter = GBDTAdapter(FakePredictor(), mode=mode, dt_step=0.02)
        a = replay(
            tracks,
            arm="MODEL:C-GBDT",
            registry=registry,
            commit_settings=settings,
            v_min=0.15,
            session_id="model-test",
            model=adapter,
            feature_schema=schema,
            feature_window_n=2,
            feature_records=build_features(tracks, schema),
        )
        b = replay(
            changed,
            arm="MODEL:C-GBDT",
            registry=registry,
            commit_settings=settings,
            v_min=0.15,
            session_id="model-test",
            model=adapter,
            feature_schema=schema,
            feature_window_n=2,
            feature_records=build_features(changed, schema),
        )
        assert [c.to_dict() for c in a.committed if c.frame_id < 4] == [
            c.to_dict() for c in b.committed if c.frame_id < 4
        ]
        assert [c.to_dict() for c in a.candidates if c.frame_id < 4] == [
            c.to_dict() for c in b.candidates if c.frame_id < 4
        ]
        assert a.candidates
        assert all(c.source == "MODEL" for c in a.candidates)
