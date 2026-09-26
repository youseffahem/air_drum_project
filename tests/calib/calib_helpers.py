"""Shared SYNTHETIC calibration fixtures for tests/calib (unique module name; never evidence)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from spacedrums.app.pipeline import HANDS, DecisionPipeline
from spacedrums.calib import (
    CalibrationWizard,
    Template,
    WizardFrame,
    WizardSettings,
    autopilot,
    save_calibration,
)
from spacedrums.calib.synthetic import SyntheticUser
from spacedrums.config import load_config
from spacedrums.geometry import ZoneRegistry

ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = ROOT / "configs" / "prototype.candidate.yaml"
LIVE_MODEL = ROOT / "configs" / "live.arm-C.candidate.yaml"
APP = {"version": "0.14.0", "git_sha": "0" * 40, "git_dirty": True}
CREATED = "2026-09-26T10:00:00+03:00"


def base_cfg() -> dict:
    return copy.deepcopy(load_config(PROTOTYPE).data)


def make_wizard(
    cfg: dict | None = None,
    *,
    layout: str = "mvp4",
    settings: WizardSettings | None = None,
    kind: str = "SYNTHETIC",
    fit_mode: str = "ENVELOPE",
    nudges: dict | None = None,
    samples: dict | None = None,
    available: list[str] | None = None,
    calibration_id: str = "synthetic-test",
) -> CalibrationWizard:
    return CalibrationWizard(
        cfg or base_cfg(),
        Template.load(layout),
        settings or WizardSettings(),
        calibration_id=calibration_id,
        created_at=CREATED,
        provenance={"kind": kind, "scope": "USER", "user_tag": "synthetic-actor"},
        app=APP,
        fit_mode=fit_mode,
        nudges=nudges,
        sample_overrides=samples,
        available_samples=available,
        clock="synthetic" if kind == "SYNTHETIC" else "replay",
    )


def arm_a_pipeline(cfg: dict, zones: list[dict]) -> DecisionPipeline:
    doc = copy.deepcopy(cfg)
    doc["zones"] = zones
    return DecisionPipeline(
        doc,
        registry=ZoneRegistry.from_config(zones),
        session_id="calib-test",
        active_arm="A",
        shadow_arms=(),
        hardware_id="HW-01",
        config_hash="sha256:" + "0" * 64,
        audio=None,
        gain_fn=lambda _z, _v: 1.0,
    )


def drive(wizard, actor, *, until=None, auto=True, skip_validation=False, max_frames=8000):
    """Closed synthetic loop (same wiring as spacedrums.app.calibrate); stops when done or until(wizard)."""
    zones = wizard.required_zones()
    pipe = arm_a_pipeline(wizard.cfg, zones)
    for _ in range(max_frames):
        if wizard.done or (until is not None and until(wizard)):
            return wizard
        required = wizard.required_zones()
        if required != zones:
            zones = required
            pipe = arm_a_pipeline(wizard.cfg, zones)
        sample, obs, sticks, gray = actor.frame(wizard)
        res = pipe.step(sample, obs, t_now=sample.t_frame_available)
        wizard.update(
            WizardFrame(
                sample,
                {h: obs[h][0] for h in HANDS},
                sticks,
                {h: res.hands[h].track for h in HANDS},
                tuple(c for c in res.commits if not c.shadow),
                gray,
            )
        )
        if until is not None and until(wizard):
            return wizard
        if auto:
            autopilot(wizard, skip_validation=skip_validation)
    raise AssertionError(f"wizard did not finish (stuck at {wizard.step}/{wizard.stage})")


def run_synthetic(**kw) -> CalibrationWizard:
    actor_kw = {
        k: kw.pop(k)
        for k in list(kw)
        if k
        in (
            "seed",
            "noise",
            "support_noise",
            "presence",
            "l_true",
            "reach_box",
            "span_px",
            "camera_profile_id",
        )
    }
    wizard = make_wizard(**kw)
    return drive(wizard, SyntheticUser(wizard.cfg, **actor_kw))


@pytest.fixture(scope="session")
def synthetic_calibration(tmp_path_factory):
    """One complete SYNTHETIC calibration (ENVELOPE fit, MVP-4), saved; (Calibration, path)."""
    wizard = run_synthetic(seed=3)
    path = tmp_path_factory.mktemp("calib") / "synthetic.calib.yaml"
    return save_calibration(wizard.document, path), path
