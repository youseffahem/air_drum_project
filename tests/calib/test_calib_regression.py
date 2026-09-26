"""Phase 14 regression: with the recording layout as calibration input, zone geometry equals Phase 04's
layout exactly (no drift) - in the calibration file, in the resolved config and in the model features."""

import json

import pytest
import yaml
from calib_helpers import PROTOTYPE, ROOT, base_cfg, run_synthetic

from spacedrums.calib import CalibrationError, load_calibrated_config, save_calibration
from spacedrums.calib.fit import zones_hash
from spacedrums.calib.synthetic import SyntheticUser
from spacedrums.config import canonical_json, load_config
from spacedrums.features.schema import FeatureSchema

MVP4_PATH = ROOT / "configs/zones/mvp4.candidate.yaml"
PINNED_MANIFEST = ROOT / "experiments/phase-10/20260924-1926-synthetic-horizon/models/cell-000/manifest.json"


def fragment_zones(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))["zones"]


@pytest.fixture(scope="module")
def fixed_calibration(tmp_path_factory):
    wizard = run_synthetic(fit_mode="FIXED", seed=5, noise=0.002)
    path = tmp_path_factory.mktemp("fixed") / "recording-layout.calib.yaml"
    return save_calibration(wizard.document, path), path


def test_recording_layout_is_reproduced_exactly(fixed_calibration):
    calib, _ = fixed_calibration
    phase04 = fragment_zones(MVP4_PATH)
    fit = calib.doc["layout"]["fit"]
    assert fit["mode"] == "FIXED" and fit["scale"] == 1.0 and fit["translate"] == [0.0, 0.0]
    assert calib.doc["layout"]["zones"] == phase04
    assert canonical_json(calib.doc["layout"]["zones"]) == canonical_json(phase04)
    assert calib.doc["layout"]["zones_hash"] == zones_hash(phase04)


def test_resolved_config_equals_the_phase04_prototype_zones(fixed_calibration):
    cfg = load_calibrated_config(PROTOTYPE, calibration=fixed_calibration[1]).config.data
    prototype = load_config(PROTOTYPE).data
    assert cfg["zones"] == prototype["zones"] == fragment_zones(MVP4_PATH)
    assert canonical_json(cfg["zones"]) == canonical_json(prototype["zones"])


def test_feature_schema_fingerprint_does_not_drift(fixed_calibration):
    cfg = load_calibrated_config(PROTOTYPE, calibration=fixed_calibration[1]).config.data
    options = {
        "groups": ["POS", "VEL", "ACC", "AXIS", "HAND", "ZONE", "CONF", "TIME"],
        "epsilon": 1e-6,
        "tts_clip_s": 2.0,
    }
    calibrated = FeatureSchema(cfg["zones"], **options).fingerprint
    assert calibrated == FeatureSchema(fragment_zones(MVP4_PATH), **options).fingerprint
    if PINNED_MANIFEST.is_file():  # the Phase 10 development package is local (experiments/ is ignored)
        assert calibrated == json.loads(PINNED_MANIFEST.read_text(encoding="utf-8"))["feature_schema_hash"]


def test_fixed_v17_template_overlap_blocks_save_until_nudged():
    wizard = run_synthetic_until_placement_review("v1-7")
    assert not wizard.can_accept() and "overlap" in wizard.blocking_reason()
    wizard.nudge("tom1", -0.03, 0.0)
    wizard.nudge("tom2", 0.03, 0.0)
    assert wizard.can_accept()


def run_synthetic_until_placement_review(layout):
    from calib_helpers import drive, make_wizard

    from spacedrums.calib import Stage, Step

    wizard = make_wizard(layout=layout, fit_mode="FIXED")
    return drive(
        wizard,
        SyntheticUser(wizard.cfg, seed=1),
        until=lambda w: w.step is Step.ZONE_PLACEMENT and w.stage is Stage.REVIEW,
    )


def test_two_identical_runs_give_identical_geometry():
    a = run_synthetic(seed=7, noise=0.003).document
    b = run_synthetic(seed=7, noise=0.003).document
    assert a["layout"]["zones_hash"] == b["layout"]["zones_hash"]
    assert a == b


def test_fixed_mode_rejects_a_hand_scaled_copy(fixed_calibration):
    doc = json.loads(json.dumps(fixed_calibration[0].doc))
    doc["layout"]["fit"]["scale"] = 1.0000001
    from spacedrums.calib.schema import validate_document

    with pytest.raises(CalibrationError):
        validate_document(doc)


def test_base_config_is_untouched_by_calibration(fixed_calibration):
    before = base_cfg()
    load_calibrated_config(PROTOTYPE, calibration=fixed_calibration[1])
    assert base_cfg() == before
