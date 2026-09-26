"""Wizard state machine end to end on the SYNTHETIC actor: every step, resume, fallbacks, repeats."""

import copy

import pytest
from calib_helpers import base_cfg, drive, make_wizard, run_synthetic

from spacedrums.calib import CalibrationError, LayoutError, Stage, Step, save_calibration
from spacedrums.calib.synthetic import SyntheticUser


def test_full_synthetic_run(synthetic_calibration):
    d = synthetic_calibration[0].doc
    assert d["provenance"]["kind"] == "SYNTHETIC" and d["validation"]["label"] == "SYNTHETIC"
    for key in ("playing_area", "stick_prior", "reach_envelope", "validation"):
        assert d[key]["status"] == "PASSED", key
    assert d["camera"]["check"]["status"] == "PASSED"
    assert d["stick_prior"]["l_prior"] == {"LEFT": 0.29, "RIGHT": 0.26}  # the actor's hidden lengths
    assert d["layout"]["fit"]["mode"] == "ENVELOPE" and 0.7 <= d["layout"]["fit"]["scale"] <= 1.3
    assert [r["detected"] for r in d["validation"]["per_zone"]] == [5, 5, 5, 5]
    assert d["validation"]["passed"] is True and d["validation"]["arm"] == "A"
    assert d["durations_s"]["clock"] == "synthetic" and d["durations_s"]["total"] > 0


def test_noisy_run_recovers_l_prior_within_tolerance():
    d = run_synthetic(seed=11, noise=0.002, support_noise=0.004).document
    assert d["stick_prior"]["l_prior"]["LEFT"] == pytest.approx(0.29, abs=0.005)
    assert d["stick_prior"]["l_prior"]["RIGHT"] == pytest.approx(0.26, abs=0.005)


def test_resume_after_a_quit():
    wizard = make_wizard()
    actor = SyntheticUser(wizard.cfg, seed=4)
    drive(wizard, actor, until=lambda w: w.step is Step.ZONE_PLACEMENT and w.stage is Stage.INSTRUCT)
    snap = copy.deepcopy(wizard.snapshot())
    resumed = make_wizard()
    resumed.restore(snap)
    assert resumed.step is Step.ZONE_PLACEMENT and resumed.resumed
    assert resumed.required_l_prior() == {"LEFT": 0.29, "RIGHT": 0.26}
    doc = drive(resumed, SyntheticUser(resumed.cfg, seed=4)).document
    assert doc["durations_s"]["resumed"] is True
    assert doc["durations_s"]["total"] == pytest.approx(
        sum(v for k, v in doc["durations_s"].items() if k not in ("total", "clock", "resumed"))
    )


def test_resume_refuses_another_setup():
    wizard = make_wizard()
    drive(wizard, SyntheticUser(wizard.cfg), until=lambda w: w.step is Step.PLAYING_AREA)
    cfg = base_cfg()
    cfg["roi"]["px"] = [30, 20, 560, 440]
    other = make_wizard(cfg)
    with pytest.raises(CalibrationError, match="binding"):
        other.restore(wizard.snapshot())


def test_tracking_trouble_falls_back_with_warnings(tmp_path):
    d = run_synthetic(seed=2, presence=0.2).document  # a hand is detected in ~20 % of frames
    assert d["playing_area"]["status"] == "ACCEPTED_WITH_WARNINGS" and not d["playing_area"]["passed"]
    assert d["stick_prior"]["status"] == "FALLBACK"
    assert d["validation"]["passed"] is False and d["validation"]["status"] == "ACCEPTED_WITH_WARNINGS"
    assert d["stick_prior"]["l_prior"] == {"LEFT": 0.27, "RIGHT": 0.27}  # layout default, with warnings
    assert all(r["source"] == "DEFAULT" for r in d["stick_prior"]["per_hand"].values())
    save_calibration(d, tmp_path / "x.calib.yaml")  # still a valid, honest document


def test_insufficient_sweep_keeps_the_template():
    wizard = make_wizard()
    actor = SyntheticUser(wizard.cfg, seed=1)
    drive(wizard, actor, until=lambda w: w.step is Step.ZONE_PLACEMENT and w.stage is Stage.COUNTDOWN)
    actor.presence = 0.0  # nobody sweeps
    drive(wizard, actor, until=lambda w: w.step is Step.ZONE_PLACEMENT and w.stage is Stage.REVIEW)
    assert wizard.pending["fallback"] and wizard.pending["layout"]["fit"]["mode"] == "FIXED"
    wizard.accept()
    assert wizard.outcomes[Step.ZONE_PLACEMENT]["status"] == "FALLBACK"


def test_failed_validation_can_repeat_placement_then_skip():
    wizard = make_wizard()
    actor = SyntheticUser(wizard.cfg, seed=1)
    drive(wizard, actor, until=lambda w: w.step is Step.VALIDATION and w.stage is Stage.COUNTDOWN)
    actor.presence = 0.0  # no strikes -> every zone LOW_DETECTION
    drive(wizard, actor, until=lambda w: w.step is Step.VALIDATION and w.stage is Stage.REVIEW)
    assert wizard.pending["passed"] is False
    wizard.back_to_placement()
    assert wizard.step is Step.ZONE_PLACEMENT and wizard.placement_attempts == 2
    actor.presence = 1.0
    drive(wizard, actor, until=lambda w: w.step is Step.VALIDATION and w.stage is Stage.INSTRUCT)
    wizard.skip_validation()
    doc = drive(wizard, actor).document
    assert doc["validation"]["status"] == "SKIPPED" and doc["validation"]["passed"] is None
    assert doc["validation"]["label"] == "NOT_RUN" and doc["layout"]["attempts"] == 2


def test_placement_attempts_are_bounded():
    wizard = make_wizard()
    wizard.placement_attempts = wizard.settings.max_placement_attempts
    drive(wizard, SyntheticUser(wizard.cfg), until=lambda w: w.step is Step.VALIDATION)
    with pytest.raises(CalibrationError, match="maximum"):
        wizard.back_to_placement()


def test_camera_profile_mismatch_blocks_the_wizard():
    wizard = make_wizard()
    with pytest.raises(CalibrationError, match="camera_profile_id"):
        drive(wizard, SyntheticUser(wizard.cfg, camera_profile_id="another-camera"))
    assert wizard.step is Step.CAMERA_CHECK and not wizard.can_accept()


def test_nudges_and_sounds_in_review():
    wizard = make_wizard(
        available=["tr505-snare", "tr505-clap", "tr505-hihat-closed", "tr505-tom-h", "tr505-crash"]
    )
    drive(
        wizard,
        SyntheticUser(wizard.cfg),
        until=lambda w: w.step is Step.ZONE_PLACEMENT and w.stage is Stage.REVIEW,
    )
    before = copy.deepcopy(wizard.pending["layout"]["zones"])
    for _ in range(20):
        wizard.nudge("snare", 0.005, 0.0)  # clamps at max_nudge
    assert wizard.nudges["snare"] == [pytest.approx(0.05), 0.0]
    moved = wizard.pending["layout"]["zones"][1]["shape"]["center"][0]
    assert moved == pytest.approx(before[1]["shape"]["center"][0] + 0.05)
    wizard.set_sample("snare", "tr505-clap")
    with pytest.raises(LayoutError):
        wizard.set_sample("snare", "not-in-bank")
    assert wizard.sample_overrides == {"snare": "tr505-clap"}
    doc = drive(wizard, SyntheticUser(wizard.cfg, seed=9)).document
    assert doc["layout"]["nudges"] == {"snare": [pytest.approx(0.05), 0.0]}
    assert doc["layout"]["zones"][1]["sample_id"] == "tr505-clap"


def test_view_model_is_plain_data():
    wizard = make_wizard()
    view = wizard.view()
    assert view["step_number"] == 1 and view["n_steps"] == 6 and view["stage"] == "INSTRUCT"
    assert "SPACE" in view["keys"] and view["zones"] is None
    drive(
        wizard,
        SyntheticUser(wizard.cfg),
        until=lambda w: (
            w.step is Step.VALIDATION and w.stage is Stage.COLLECT and w.current_cue() is not None
        ),
    )
    view = wizard.view()
    assert view["highlight_zone"] == "hihat" and view["zones"] and view["lines"][0].startswith("HIT: hihat")
