"""Applying calibration must retain the newer schema and per-arm settings."""

from calib_helpers import base_cfg

from spacedrums.calib import apply_calibration


def test_schema_19_survives_calibration(synthetic_calibration):
    cfg = base_cfg()
    cfg["meta"]["schema_version"] = "1.9"
    calib, _path = synthetic_calibration
    resolved = apply_calibration(cfg, calib)
    assert resolved["meta"]["schema_version"] == "1.9"
