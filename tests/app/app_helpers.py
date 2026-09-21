"""Fixtures for the Phase 05 application tests: the candidate config, the MVP-4 registry, a pipeline
factory with a deterministic clock. Every sequence fed here is SYNTHETIC (``spacedrums.app.synthetic``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spacedrums.app import AudioOutput, DecisionPipeline, OutputLatency
from spacedrums.config import load_config
from spacedrums.geometry import ZoneRegistry

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "prototype.candidate.yaml"


class Ticker:
    """Deterministic ``timing.now`` substitute: strictly increasing, reproducible."""

    def __init__(self, start: float = 500.0, step: float = 0.001) -> None:
        self.t, self.step = start, step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


@pytest.fixture(scope="session")
def cfg():
    return load_config(CONFIG)


@pytest.fixture(scope="session")
def registry(cfg) -> ZoneRegistry:
    return ZoneRegistry.from_config(cfg["zones"])


@pytest.fixture
def make_pipeline(cfg, registry):
    def _make(
        *,
        active="A",
        shadow=("B",),
        overrides: dict | None = None,
        clock=None,
        session_id="synthetic",
        audio=True,
    ):
        data = cfg.data
        if overrides:
            from spacedrums.config import config_hash, deep_merge, validate

            data = deep_merge(cfg.data, overrides)
            validate(data)
            chash = config_hash(data)
        else:
            chash = cfg.config_hash
        clk = clock or Ticker()
        out = (
            AudioOutput(data, latency=OutputLatency.unmeasured(), device_enabled=False, clock=clk)
            if audio
            else None
        )
        return DecisionPipeline(
            data,
            registry=registry,
            session_id=session_id,
            active_arm=active,
            shadow_arms=shadow,
            hardware_id="HW-01",
            config_hash=chash,
            audio=out,
            clock=clk,
            gain_fn=(None if audio else (lambda z, p: 0.5)),
        )

    return _make


def run_sequence(
    pipeline: DecisionPipeline,
    seq,
    *,
    delta_proc_s: float = 0.0,
    switch_at: int | None = None,
    switch_to: str = "B",
):
    """Drive a synthetic sequence through the pipeline; returns the per-frame results."""
    results = []
    for k, (sample, obs) in enumerate(seq):
        if switch_at is not None and k == switch_at:
            pipeline.set_active_arm(switch_to, sample.t_frame_available + delta_proc_s)
        results.append(pipeline.step(sample, obs, t_now=sample.t_frame_available + delta_proc_s))
    return results


def all_commits(results):
    return [c for r in results for c in r.commits]


def all_candidates(results):
    return [c for r in results for h in r.hands.values() for c in h.candidates]
