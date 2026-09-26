"""Task 14.1 / 14.7: the pipeline config loads the calibration, records its hash and stays consistent."""

import copy

import pytest
import yaml
from calib_helpers import PROTOTYPE, arm_a_pipeline, base_cfg

from spacedrums.calib import CALIBRATED, UNCALIBRATED, apply_calibration, load_calibrated_config
from spacedrums.config import ConfigError, config_hash, load_config, validate
from spacedrums.geometry import ZoneRegistry


def test_calibrated_config(synthetic_calibration):
    calib, path = synthetic_calibration
    cc = load_calibrated_config(PROTOTYPE, calibration=path)
    cfg = cc.config.data
    assert cc.status == CALIBRATED and cc.calibration.hash == calib.hash
    assert cfg["zones"] == calib.doc["layout"]["zones"]
    assert cfg["stick"]["geom"]["l_prior_by_hand"] == calib.doc["stick_prior"]["l_prior"]
    assert cfg["meta"]["schema_version"] == "1.7" and cfg["calibration_path"] == str(path)
    assert cfg["calibration"]["calibration_hash"] == calib.hash
    assert cfg["calibration"]["template_zones"] == calib.doc["layout"]["template"]["zones"]
    assert cfg["roi"] == base_cfg()["roi"]  # the ROI is bound, never overridden
    assert cc.session_fields() == {
        "calibration_status": "CALIBRATED",
        "calibration_hash": calib.hash,
        "calibration_id": calib.calibration_id,
    }
    assert any("SYNTHETIC" in w for w in cc.warnings)
    assert cc.config.config_hash == config_hash(cfg) and str(path) in cc.config.sources


def test_uncalibrated_config():
    cc = load_calibrated_config(PROTOTYPE)
    assert cc.status == UNCALIBRATED and cc.calibration is None
    assert cc.session_fields() == {
        "calibration_status": "UNCALIBRATED",
        "calibration_hash": None,
        "calibration_id": None,
    }
    assert cc.config.config_hash == load_config(PROTOTYPE).config_hash  # no drift for uncalibrated runs


def test_plain_loader_refuses_an_unresolved_calibration_path(tmp_path, synthetic_calibration):
    cfg = base_cfg()
    cfg["meta"]["schema_version"] = "1.7"
    cfg["calibration_path"] = str(synthetic_calibration[1])
    path = tmp_path / "with-path.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(ConfigError, match="load_calibrated_config"):
        load_config(path)
    assert load_calibrated_config(path).status == CALIBRATED


def test_snapshot_is_self_contained_and_edits_are_detected(synthetic_calibration, tmp_path):
    cfg = load_calibrated_config(PROTOTYPE, calibration=synthetic_calibration[1]).config.data
    snap = tmp_path / "config.snapshot.yaml"
    snap.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert load_config(snap).config_hash == config_hash(cfg)
    assert load_calibrated_config(snap).status == CALIBRATED
    edited = copy.deepcopy(cfg)
    edited["zones"][0]["sample_id"] = "tr505-clap"
    with pytest.raises(ConfigError, match="zones differ"):
        validate(edited)
    edited = copy.deepcopy(cfg)
    edited["stick"]["geom"]["l_prior_by_hand"]["LEFT"] = 0.5
    with pytest.raises(ConfigError, match="l_prior_by_hand"):
        validate(edited)


def test_l_prior_by_hand_needs_a_calibration_and_1_7():
    cfg = base_cfg()
    cfg["stick"]["geom"]["l_prior_by_hand"] = {"LEFT": 0.3, "RIGHT": 0.3}
    with pytest.raises(ConfigError, match="1.7"):
        validate(cfg)
    cfg["meta"]["schema_version"] = "1.7"
    with pytest.raises(ConfigError, match="calibration resolver"):
        validate(cfg)


def test_pipeline_asserts_the_calibrated_registry(synthetic_calibration):
    calib = synthetic_calibration[0]
    cfg = apply_calibration(base_cfg(), calib)
    arm_a_pipeline(cfg, cfg["zones"])  # consistent: fine
    from spacedrums.app.pipeline import DecisionPipeline

    with pytest.raises(AssertionError, match="calibration's zones"):
        DecisionPipeline(
            cfg,
            registry=ZoneRegistry.from_config(calib.template_zones),
            session_id="x",
            active_arm="A",
            hardware_id="HW-01",
            config_hash="sha256:" + "0" * 64,
            audio=None,
            gain_fn=lambda _z, _v: 1.0,
        )
    counters = arm_a_pipeline(cfg, cfg["zones"]).counters()
    assert counters["calibration"]["calibration_hash"] == calib.hash
