"""SYNTHETIC/DEV C-arm parity and sticky fallback for ADR-0036 settings."""

import copy
from dataclasses import asdict

import pytest
from live_helpers import model_cfg as _model_cfg
from live_helpers import parity, pipeline

from spacedrums.app.invariants import InvariantMonitor
from spacedrums.app.synthetic import scenario
from spacedrums.contracts import Arm, HandId
from spacedrums.geometry import ZoneRegistry
from spacedrums.prediction import RuleSettings

model_cfg = _model_cfg


def explicit_config(cfg):
    cfg["meta"]["schema_version"] = "1.9"
    cfg["live_arm_settings"] = {
        a: {"commit": copy.deepcopy(cfg["commit"]), "v_min": cfg["geometry"]["v_min"]} for a in "ABC"
    }
    cfg["live_arm_settings"]["B"]["rule"] = asdict(
        RuleSettings.from_config({**cfg, "anticipator": {**cfg["anticipator"], "type": "rule"}})
    )
    cfg["live_arm_settings"]["B"]["rule"]["K"] = 7
    cfg["live_arm_settings"]["B"]["commit"]["tti_commit_s"] = 0.14
    cfg["live_arm_settings"]["C"]["commit"]["p_commit"] = 0.1
    cfg["live_arm_settings"]["C"]["v_min"] = 0.1
    return cfg


def test_model_parity_uses_c_settings_and_independent_b(model_cfg):
    cfg = explicit_config(model_cfg)
    seq = scenario("repeated", ZoneRegistry.from_config(cfg["zones"]), t_down=0.12)
    report, results = parity(cfg, seq, session_id="synthetic-per-arm", measured_delay=False)
    assert report["passed"] and not report["empty_prediction_set"]
    assert any(c.arm == Arm.C_GRU for r in results for c in r.commits)


def test_sticky_fallback_keeps_b_settings_and_auditor(model_cfg):
    cfg = explicit_config(model_cfg)
    cfg["anticipator"]["fallback"]["enabled"] = True
    cfg["anticipator"]["fallback"]["budget_s"] = 100
    cfg["anticipator"]["fallback"]["processing_budget_s"] = 100
    p = pipeline(cfg, "synthetic-per-arm-fallback")
    assert p.rule_settings.K == 7
    p._fallback("injected SYNTHETIC/DEV failure", 100.0)
    assert p.active_arm == Arm.B
    assert p.policies[Arm.B][HandId.LEFT].settings.tti_commit_s == 0.14
    with pytest.raises(ValueError, match="restart"):
        p.set_active_arm(Arm.C_GRU, 100.1)
    monitor = InvariantMonitor.for_pipeline(p)
    for frame, obs in scenario("repeated", ZoneRegistry.from_config(cfg["zones"]), t_down=0.12):
        result = p.step(frame, obs, t_now=frame.t_frame_available)
        monitor.observe(result, p)
        assert result.hands[HandId.LEFT].model_prediction is None
    assert monitor.finish()["violations_total"] == 0
