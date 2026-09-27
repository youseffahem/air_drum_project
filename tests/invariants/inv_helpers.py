"""Shared helpers for the Phase 17 invariant, failure-injection and system suites (unique module name).

Every pipeline built here runs on SYNTHETIC observations with a deterministic clock and the audio
device disabled (the scheduler still runs, so I6 is exercised).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spacedrums.app import AudioOutput, DecisionPipeline, OutputLatency
from spacedrums.config import config_hash, deep_merge, load_config, validate
from spacedrums.contracts import Arm, CommittedStrike, HandId
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.zones import surface_midpoint

os.environ.setdefault("SPACEDRUMS_FAULT_INJECTION", "1")  # the test build enables app.faults

ROOT = Path(__file__).resolve().parents[2]
RULE_CONFIG = ROOT / "configs" / "prototype.candidate.yaml"
MODEL_CONFIG = ROOT / "configs" / "live.arm-C.candidate.yaml"


class Ticker:
    """Deterministic ``timing.now`` substitute: strictly increasing, reproducible."""

    def __init__(self, start: float = 500.0, step: float = 0.0005) -> None:
        self.t, self.step = start, step

    def __call__(self) -> float:
        self.t += self.step
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def rule_config():
    return load_config(RULE_CONFIG)


def make_pipeline(cfg, registry, *, active="A", shadow=("B",), clock=None, audio=True, overrides=None, **kw):
    data = cfg.data if hasattr(cfg, "data") else cfg
    chash = getattr(cfg, "config_hash", "sha256:" + "0" * 64)
    if overrides:
        data = deep_merge(data, overrides)
        validate(data)
        chash = config_hash(data)
    clk = clock or Ticker()
    out = (
        AudioOutput(data, latency=OutputLatency.unmeasured(), device_enabled=False, clock=clk)
        if audio
        else None
    )
    return DecisionPipeline(
        data,
        registry=registry,
        session_id="synthetic-p17",
        active_arm=active,
        shadow_arms=shadow,
        hardware_id="HW-01",
        config_hash=chash,
        audio=out,
        clock=clk,
        gain_fn=None if audio else (lambda _z, _v: 0.5),
        **kw,
    )


def strike(
    frame_id: int,
    t: float,
    *,
    hand: HandId = HandId.RIGHT,
    zone: str = "snare",
    arm: Arm = Arm.A,
    source: str = "REACTIVE",
    shadow: bool = False,
    target: float | None = None,
) -> CommittedStrike:
    return CommittedStrike(
        strike_id=f"s-{frame_id}-{arm}-{hand}-{zone}",
        candidate_id=f"c-{frame_id}",
        frame_id=frame_id,
        t_capture=t,
        hand_id=hand,
        zone_id=zone,
        source=source,
        derivation="GEOMETRY",
        arm=arm,
        shadow=shadow,
        t_commit=t,
        t_impact_target=t if target is None else target,
        intensity_proxy=1.0,
        gain=0.5,
        refractory_until=t + 0.1,
        episode_id=f"e-{frame_id}",
        commit_policy_id="commit-v1",
    )


def run_frames(pipe, frames, *, monitor=None, plan=None, switch_at=None, t_now_offset=0.0):
    """Feed (sample, observations) frames; returns the list of FrameResults."""
    results = []
    for i, (sample, obs) in enumerate(frames):
        if plan is not None:
            obs = plan.apply_observations(obs, i)
        if switch_at is not None and i in switch_at:
            pipe.set_active_arm(switch_at[i], sample.t_capture)
        r = pipe.step(sample, obs, t_now=sample.t_frame_available + t_now_offset)
        if monitor is not None:
            monitor.observe(r, pipe)
        results.append(r)
    return results


# ----------------------------------------------------------------------------- fixtures
# Re-exported by the conftest.py of tests/invariants, tests/failure_injection and tests/system.


@pytest.fixture(scope="session")
def cfg():
    return load_config(RULE_CONFIG)


@pytest.fixture(scope="session")
def registry(cfg):
    return ZoneRegistry.from_config(cfg["zones"])


@pytest.fixture
def snare_inside(registry):
    x, y = surface_midpoint(registry["snare"].impact_surface)
    return (x, y + 0.03)


@pytest.fixture
def snare_outside(registry):
    x, y = surface_midpoint(registry["snare"].impact_surface)
    return (x, y - 0.08)


def analytic_model_cfg(tmp_path):
    """The Phase 13 analytic TorchScript fixture (tests/parity/live_helpers.py), SYNTHETIC: a GRU whose
    trajectory head always moves the tip straight down; model config on the prototype zones."""
    import torch

    from spacedrums.features.schema import FeatureSchema
    from spacedrums.models.temporal.config import TemporalConfig, build_model
    from spacedrums.prediction.model_loader import file_hash

    torch.set_num_threads(1)
    cfg = load_config(RULE_CONFIG).data
    schema = FeatureSchema(cfg["zones"])
    c = TemporalConfig("gru", schema.dimension, n=2, k=4, dt_step=1 / 30, hidden=8, auxiliary=True)
    model = build_model(c).eval()
    with torch.no_grad():
        model.head.trajectory.weight.zero_()
        model.head.trajectory.bias.copy_(torch.tensor([0.0, 0.04, 0.0, 0.08, 0.0, 0.12, 0.0, 0.16]))
        model.head.aux.weight.zero_()
        model.head.aux.bias.fill_(10)
    torch.jit.script(model).save(str(tmp_path / "export.pt"))
    stats = {
        "fold": 0,
        "dataset_version": "ds-v0.0-selftest-p17",
        "dataset_hash": "fixture",
        "split_hash": "fixture",
        "feature_schema_id": "fs-v1",
        "feature_schema_hash": schema.fingerprint,
        "center": [0.0] * schema.dimension,
        "scale": [1.0] * schema.dimension,
        "usable": [True] * schema.dimension,
    }
    (tmp_path / "norm_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    keys = (
        "fold",
        "dataset_version",
        "dataset_hash",
        "split_hash",
        "feature_schema_id",
        "feature_schema_hash",
    )
    manifest = {
        **{k: stats[k] for k in keys},
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
        "model_id": "synthetic-analytic-p17",
        "source_kind": "SYNTHETIC",
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    cfg["meta"]["schema_version"] = "1.6"
    cfg["features"] = {
        "schema_id": "fs-v1",
        "groups": list(schema.groups),
        "epsilon": 1e-6,
        "tts_clip_s": 2.0,
    }
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
            "enabled": True,
            "to": "B",
            "budget_s": 1.0,
            "processing_budget_s": 10.0,
            "window_frames": 30,
            "cooldown_s": 0,
            "automatic_recovery": False,
        },
    )
    cfg["arms"] = {"active": "C-GRU", "shadow": ["A", "B"]}
    return cfg


@pytest.fixture
def model_cfg(tmp_path):
    return analytic_model_cfg(tmp_path)


__all__ = [
    "MODEL_CONFIG",
    "ROOT",
    "RULE_CONFIG",
    "Ticker",
    "analytic_model_cfg",
    "cfg",
    "make_pipeline",
    "model_cfg",
    "registry",
    "rule_config",
    "run_frames",
    "snare_inside",
    "snare_outside",
    "strike",
]
