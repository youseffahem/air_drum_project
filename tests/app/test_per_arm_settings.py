"""ADR-0036 offline engineering checks; SYNTHETIC/DEV, live experiment pending."""

import copy
import json
from dataclasses import asdict

import pytest
from app_helpers import ROOT

from spacedrums.app.invariants import InvariantMonitor
from spacedrums.app.synthetic import Swing, build_sequence
from spacedrums.commit import CommitSettings
from spacedrums.config import ConfigError, load_config, validate
from spacedrums.contracts import Arm, HandId
from spacedrums.live_eval.arm_settings import consistency_errors, locked_arm_settings
from spacedrums.live_eval.prereg import lock_errors
from spacedrums.prediction import RuleSettings


def settings(cfg):
    arms = {a: {"commit": copy.deepcopy(cfg["commit"]), "v_min": cfg["geometry"]["v_min"]} for a in "ABC"}
    arms["B"]["rule"] = asdict(RuleSettings.from_config(cfg))
    arms["B"]["rule"]["K"] = 5
    arms["B"]["commit"]["tti_commit_s"] = 0.12
    arms["B"]["commit"]["p_commit"] = 0.0
    arms["A"]["commit"]["refractory_zone_s"] = 0.3
    return arms


def test_schema_requires_complete_versioned_arms(cfg):
    doc = copy.deepcopy(cfg.data)
    doc["live_arm_settings"] = settings(doc)
    with pytest.raises(ConfigError, match="1.9"):
        validate(doc)
    doc["meta"]["schema_version"] = "1.9"
    validate(doc)
    for a in "ABC":
        bad = copy.deepcopy(doc)
        del bad["live_arm_settings"][a]
        with pytest.raises(ConfigError):
            validate(bad)
    bad = copy.deepcopy(doc)
    bad["live_arm_settings"]["B"]["commit"]["aux_heads"] = {}
    with pytest.raises(ConfigError):
        validate(bad)
    load_config(ROOT / "configs/live.arm-C.candidate.yaml")


def test_independent_b_horizon_commit_geometry_and_switch_audit(cfg, registry, make_pipeline):
    arm_settings = settings(cfg)
    p = make_pipeline(
        overrides={
            "meta": {"schema_version": "1.9"},
            "live_arm_settings": arm_settings,
            "anticipator": {"K": 2},
        },
        audio=False,
    )
    assert p.rule_settings.K == 5
    assert p.policies[Arm.A][HandId.LEFT].settings == CommitSettings(**arm_settings["A"]["commit"])
    assert p.policies[Arm.B][HandId.LEFT].settings == CommitSettings(**arm_settings["B"]["commit"])
    assert p.geometry_by_arm[Arm.A] is not p.geometry_by_arm[Arm.B]
    seq = build_sequence(
        registry, [Swing(HandId.LEFT, "snare", 0.2), Swing(HandId.LEFT, "snare", 0.8)], duration_s=1.5
    )
    monitor = InvariantMonitor.for_pipeline(p)
    commits = []
    for i, (frame, obs) in enumerate(seq):
        if i == 17:
            p.set_active_arm(Arm.B, frame.t_capture)
        result = p.step(frame, obs, t_now=frame.t_frame_available)
        monitor.observe(result, p)
        commits.extend(result.commits)
        if i == 17:
            assert not result.commits
        if result.hands[HandId.LEFT].prediction is not None:
            assert len(result.hands[HandId.LEFT].prediction.positions) == 5
    assert commits and monitor.finish()["violations_total"] == 0
    assert p.rule_settings.K == 5


def test_live_offline_exact_binding_rejects_each_changed_setting(cfg):
    off = json.loads((ROOT / "schemas/examples/confirmatory-lock.valid.example.json").read_text())["offline"]
    ids = {"A": "A", "B": off["b_primary"], "C": off["c_primary"]}
    expected = locked_arm_settings(off, cfg, ids)
    live = copy.deepcopy(cfg.data)
    live["live_arm_settings"] = expected
    primary = next(a for a in off["arms"] if a["arm_id"] == off["c_primary"])["model"]
    live["anticipator"]["model"] = {
        "manifest_hash": primary["manifest_sha256"],
        "hash": primary["export_sha256"],
    }
    assert not consistency_errors(off, cfg, live, ids)
    for arm in "ABC":
        for key in (
            "tti_commit_s",
            "p_commit",
            "n_confirm_frames",
            "refractory_hand_s",
            "max_dropped_since_last",
        ):
            bad = copy.deepcopy(live)
            bad["live_arm_settings"][arm]["commit"][key] += 0.1
            assert consistency_errors(off, cfg, bad, ids)
    for key, value in [("K", 9), ("dt_step", 0.02), ("motion_model", "CA"), ("a_max", 15)]:
        bad = copy.deepcopy(live)
        bad["live_arm_settings"]["B"]["rule"][key] = value
        assert consistency_errors(off, cfg, bad, ids)
    with pytest.raises(ValueError):
        locked_arm_settings(off, cfg, {**ids, "B": "A"})


def test_live_lock_template_cannot_be_archived_without_real_bindings():
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from confirmatory_lock import template

    lock = template("live")
    assert lock_errors(lock)
    assert "offline_lock_path" in lock["live"]


def test_live_binding_checks_pinned_files_and_offline_base_config(cfg, tmp_path):
    """Temporary SYNTHETIC schema fixture, never a participant reference or archived lock."""
    import yaml

    from spacedrums.live_eval.arm_settings import live_binding_errors
    from spacedrums.live_eval.prereg import file_digest, lock_digest

    lock = json.loads((ROOT / "schemas/examples/confirmatory-lock.valid.example.json").read_text())
    off = lock["offline"]
    ids = {"A": "A", "B": off["b_primary"], "C": off["c_primary"]}
    live = load_config(ROOT / "configs/live.arm-C.candidate.yaml").data
    live["live_arm_settings"] = locked_arm_settings(off, cfg, ids)
    mdl = next(a for a in off["arms"] if a["arm_id"] == off["c_primary"])["model"]
    live["anticipator"]["model"]["manifest_hash"] = mdl["manifest_sha256"]
    live["anticipator"]["model"]["hash"] = mdl["export_sha256"]
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(cfg.data))
    (tmp_path / "live.yaml").write_text(yaml.safe_dump(live))
    off["sources"]["configs/prototype.candidate.yaml"] = file_digest(tmp_path / "base.yaml")
    (tmp_path / "offline.json").write_text(json.dumps(lock))
    binding = {
        "arms": ids,
        "config_path": "live.yaml",
        "config_sha256": file_digest(tmp_path / "live.yaml"),
        "offline_config_path": "base.yaml",
        "offline_config_sha256": file_digest(tmp_path / "base.yaml"),
        "offline_lock_path": "offline.json",
        "offline_lock_sha256": lock_digest(lock),
    }
    assert not live_binding_errors(binding, root=tmp_path)
    for role in ("config", "offline_config", "offline_lock"):
        assert live_binding_errors({**binding, f"{role}_sha256": "sha256:" + "0" * 64}, root=tmp_path)
    (tmp_path / "base.yaml").write_text("changed")
    assert live_binding_errors(binding, root=tmp_path)
