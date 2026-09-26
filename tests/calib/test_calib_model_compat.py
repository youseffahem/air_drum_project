"""Task 14.7: ZONE features follow the loaded calibration; the model is verified against its training
layout. Uses a tiny analytic TorchScript package (SYNTHETIC engineering fixture, never evidence)."""

import copy
import json

import numpy as np
import pytest
import torch
from calib_helpers import base_cfg, run_synthetic

from spacedrums.app.arms import LayoutAdaptedStats, build_model_arm, check_zone_features
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.calib import Calibration, apply_calibration, calibration_hash
from spacedrums.contracts import HandId, TrackState
from spacedrums.features.schema import FeatureSchema
from spacedrums.geometry import ZoneRegistry
from spacedrums.models.temporal.config import TemporalConfig, build_model
from spacedrums.prediction.model_loader import file_hash

GROUPS = ["POS", "VEL", "ACC", "AXIS", "HAND", "ZONE", "CONF", "TIME"]


def model_config(tmp_path, training_zones):
    """A 1.6 live config whose package was 'trained' on ``training_zones`` (analytic weights)."""
    torch.set_num_threads(1)
    cfg = base_cfg()
    schema = FeatureSchema(training_zones, groups=GROUPS)
    c = TemporalConfig("gru", schema.dimension, n=2, k=4, dt_step=1 / 30, hidden=8, auxiliary=True)
    model = build_model(c).eval()
    torch.jit.script(model).save(str(tmp_path / "export.pt"))
    stats = {
        "fold": 0,
        "dataset_version": "ds-v0.0-selftest-p14",
        "dataset_hash": "fixture",
        "split_hash": "fixture",
        "feature_schema_id": "fs-v1",
        "feature_schema_hash": schema.fingerprint,
        "center": [0.0] * schema.dimension,
        "scale": [1.0] * schema.dimension,
        "usable": [True] * schema.dimension,
    }
    (tmp_path / "norm_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    manifest = {
        **{
            k: stats[k]
            for k in (
                "fold",
                "dataset_version",
                "dataset_hash",
                "split_hash",
                "feature_schema_id",
                "feature_schema_hash",
            )
        },
        "family": "gru",
        "config": c.to_dict(),
        "config_hash": c.config_hash,
        "N": c.n,
        "K": c.k,
        "F": c.features,
        "dt_step": c.dt_step,
        "export_hash": file_hash(tmp_path / "export.pt"),
        "checkpoint_hash": "sha256:" + "0" * 64,
        "norm_stats_id": file_hash(tmp_path / "norm_stats.json"),
        "model_id": "synthetic-analytic-p14",
        "source_kind": "SYNTHETIC",
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    cfg["meta"]["schema_version"] = "1.6"
    cfg["features"] = {"schema_id": "fs-v1", "groups": GROUPS, "epsilon": 1e-6, "tts_clip_s": 2.0}
    cfg["anticipator"].update(
        type="model",
        K=c.k,
        dt_step_s=c.dt_step,
        model={
            "path": str(tmp_path),
            "hash": manifest["export_hash"],
            "runtime": "torchscript",
            "manifest_hash": file_hash(tmp_path / "manifest.json"),
            "N": 2,
            "family": "gru",
            "norm_stats_path": str(tmp_path / "norm_stats.json"),
            "intra_op_threads": 1,
            "feature_schema_id": "fs-v1",
            "cadence_window_frames": 15,
            "cadence_tolerance": 0.25,
        },
        fallback={
            "enabled": False,
            "to": "B",
            "budget_s": 0.01,
            "processing_budget_s": 0.1,
            "window_frames": 5,
            "cooldown_s": 0,
            "automatic_recovery": False,
        },
    )
    return cfg


@pytest.fixture(scope="module")
def scaled_calibration():
    doc = run_synthetic(seed=3).document
    assert doc["layout"]["fit"]["scale"] != 1.0
    return Calibration(doc, calibration_hash(doc))


def valid_track(tip):
    return TrackState(
        frame_id=1,
        t_capture=1.0,
        hand_id=HandId.RIGHT,
        status="VALID",
        tracker_id="t",
        tip_method="GEOM",
        tip_filtered=tip,
        tip_velocity=(0.0, 0.5),
        tip_acceleration=None,
        axis_angle=None,
        axis_angular_velocity=None,
        confidence=0.9,
        frames_since_valid=0,
        last_valid_t=1.0,
        history_ref=None,
        reset_reason=None,
    )


def test_zone_features_follow_the_calibrated_zones(tmp_path, scaled_calibration):
    calib = scaled_calibration
    cfg = apply_calibration(model_config(tmp_path, calib.template_zones), calib)
    arm = build_model_arm(cfg, clock=lambda: 0.0)
    assert arm.stream.schema.zones_config == cfg["zones"] == calib.zones
    assert isinstance(arm.stats, LayoutAdaptedStats)
    info = check_zone_features(arm, cfg)
    assert info["layout_adapted"] and info["training_layout"] == "mvp4" and "untested" in info["caution"]
    record = arm.stream.update(valid_track((0.4, 0.5)))
    idx = arm.stream.schema.index["distance_snare"]
    expected = FeatureSchema(calib.zones, groups=GROUPS)
    template = FeatureSchema(calib.template_zones, groups=GROUPS)
    from spacedrums.features.core import FeatureCore

    calibrated_value = FeatureCore(expected).update(valid_track((0.4, 0.5))).values[idx]
    template_value = FeatureCore(template).update(valid_track((0.4, 0.5))).values[idx]
    assert record.values[idx] == pytest.approx(calibrated_value) and calibrated_value != pytest.approx(
        template_value
    )
    x, m = arm.stream.window(HandId.RIGHT, n=1, stats=arm.stats)
    assert np.isfinite(x).all()
    with pytest.raises(AssertionError, match="calibration"):
        arm.stats.apply(np.zeros((1, template.dimension)), np.ones((1, template.dimension), bool), template)


def test_pipeline_runs_the_model_on_a_calibrated_layout(tmp_path, scaled_calibration):
    cfg = apply_calibration(model_config(tmp_path, scaled_calibration.template_zones), scaled_calibration)
    pipe = DecisionPipeline(
        cfg,
        registry=ZoneRegistry.from_config(cfg["zones"]),
        session_id="x",
        active_arm="C-GRU",
        shadow_arms=("A",),
        hardware_id="HW-01",
        config_hash="sha256:" + "0" * 64,
        audio=None,
        gain_fn=lambda _z, _v: 1.0,
    )
    assert pipe.model_error is None and pipe.feature_layout["layout_adapted"]
    assert (
        pipe.counters()["model"]["feature_layout"]["feature_zones_hash"]
        == scaled_calibration.doc["layout"]["zones_hash"]
    )


def test_zone_feature_assertion_catches_a_foreign_layout(tmp_path, scaled_calibration):
    cfg = apply_calibration(model_config(tmp_path, scaled_calibration.template_zones), scaled_calibration)
    arm = build_model_arm(cfg, clock=lambda: 0.0)
    other = copy.deepcopy(cfg)
    other["zones"] = scaled_calibration.template_zones
    with pytest.raises(AssertionError, match="zones other than"):
        check_zone_features(arm, other)


def test_template_must_be_the_training_layout(tmp_path, scaled_calibration):
    import yaml
    from calib_helpers import ROOT

    v17 = yaml.safe_load((ROOT / "configs/zones/v1-7.candidate.yaml").read_text(encoding="utf-8"))["zones"]
    cfg = apply_calibration(model_config(tmp_path, v17), scaled_calibration)  # model 'trained' on V1-7
    with pytest.raises(ValueError, match="calibration template 'mvp4'"):
        build_model_arm(cfg, clock=lambda: 0.0)


def test_fixed_calibration_needs_no_adaptation(tmp_path):
    doc = run_synthetic(fit_mode="FIXED", seed=1).document
    calib = Calibration(doc, calibration_hash(doc))
    cfg = apply_calibration(model_config(tmp_path, calib.template_zones), calib)
    arm = build_model_arm(cfg, clock=lambda: 0.0)
    assert not isinstance(arm.stats, LayoutAdaptedStats)
    assert not check_zone_features(arm, cfg)["layout_adapted"]
