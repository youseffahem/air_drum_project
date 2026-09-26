"""Task 14.6: re-calibration triggers (camera profile, ROI, geometry version, template, user request)."""

import copy

import pytest
import yaml
from calib_helpers import ROOT, base_cfg

from spacedrums.calib import CalibrationError, Trigger, load_calibrated_config, recalibration_triggers, store


def codes(calib, cfg, **kw):
    return [t["code"] for t in recalibration_triggers(calib, cfg, **kw)]


def test_same_setup_has_no_trigger(synthetic_calibration):
    assert codes(synthetic_calibration[0], base_cfg()) == []


def test_camera_profile_change(synthetic_calibration):
    cfg = base_cfg()
    cfg["camera_profile"]["exposure"]["value"] = -5  # any camera-profile edit changes its hash
    assert codes(synthetic_calibration[0], cfg) == [Trigger.CAMERA_PROFILE_CHANGED]
    cfg = base_cfg()
    cfg["camera_profile"]["profile_id"] = "other-camera"
    assert Trigger.CAMERA_PROFILE_CHANGED in codes(synthetic_calibration[0], cfg)


def test_roi_change(synthetic_calibration):
    cfg = base_cfg()
    cfg["roi"]["px"] = [30, 20, 560, 440]
    assert codes(synthetic_calibration[0], cfg) == [Trigger.ROI_CHANGED]


def test_geometry_version_change(synthetic_calibration, monkeypatch):
    monkeypatch.setattr(store, "GEOMETRY_VERSION", "p04-geometry-v2")
    assert codes(synthetic_calibration[0], base_cfg()) == [Trigger.GEOMETRY_VERSION_CHANGED]


def test_template_change(synthetic_calibration, tmp_path):
    source = synthetic_calibration[0].doc["layout"]["template"]["source"]
    fragment = yaml.safe_load((ROOT / source).read_text(encoding="utf-8"))
    fragment["zones"][0]["sample_id"] = "changed"
    (tmp_path / source).parent.mkdir(parents=True)
    (tmp_path / source).write_text(yaml.safe_dump(fragment), encoding="utf-8")
    assert codes(synthetic_calibration[0], base_cfg(), root=tmp_path) == [Trigger.TEMPLATE_CHANGED]
    assert codes(synthetic_calibration[0], base_cfg(), root=tmp_path / "absent") == []  # embedded copy kept


def test_user_request(synthetic_calibration):
    assert codes(synthetic_calibration[0], base_cfg(), user_request=True) == [Trigger.USER_REQUEST]


def test_loader_refuses_a_stale_calibration(synthetic_calibration, tmp_path):
    cfg = base_cfg()
    cfg["roi"]["px"] = [30, 20, 560, 440]
    path = tmp_path / "moved-roi.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(CalibrationError, match="ROI_CHANGED") as err:
        load_calibrated_config(path, calibration=synthetic_calibration[1])
    assert "spacedrums.app.calibrate" in str(err.value) and "UNCALIBRATED" in str(err.value)


def test_triggers_do_not_mutate_inputs(synthetic_calibration):
    cfg = base_cfg()
    before = copy.deepcopy(cfg), copy.deepcopy(synthetic_calibration[0].doc)
    recalibration_triggers(synthetic_calibration[0], cfg, user_request=True)
    assert (cfg, synthetic_calibration[0].doc) == before
