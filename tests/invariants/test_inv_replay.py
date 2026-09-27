"""TEST-INV-3: CI subset of the Phase 17 invariant replay (Task 17.2).

Every SYNTHETIC scenario under arms A and B active, the recorded SYNTHETIC P07 session's observations
and one developer capture (when present) through the live loop with the monitor in ``raise`` mode.
The full replay set runs in ``scripts/invariant_replay.py`` (evidence in the gate record).
"""

from __future__ import annotations

import importlib.util
import sys

import pytest
from inv_helpers import ROOT, make_pipeline, run_frames

from spacedrums.app.invariants import InvariantMonitor
from spacedrums.app.synthetic import SCENARIOS, scenario


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("active,shadow", [("A", ("B",)), ("B", ("A",))])
def test_every_scenario_zero_violations(cfg, registry, name, active, shadow):
    pipe = make_pipeline(cfg, registry, active=active, shadow=shadow)
    monitor = InvariantMonitor.for_pipeline(pipe, mode="raise")
    run_frames(pipe, scenario(name, registry, noise=0.003, seed=11), monitor=monitor)
    assert monitor.finish()["violations_total"] == 0


def _script():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "invariant_replay", ROOT / "scripts" / "invariant_replay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not (ROOT / "data/raw/SYNTHETIC/synthetic-p07-labels/records/HandObservation.jsonl").exists(),
    reason="SYNTHETIC P07 session not present (git-ignored; regenerable by scripts/_p07_examples.py)",
)
def test_synthetic_p07_session_observations_zero_violations(cfg):
    script = _script()
    frames = script.recorded_observations(ROOT / script.SYNTHETIC_SESSION)[:400]
    results, summary, _ = script.live_loop(cfg.data, script.SETUPS["B-active"], frames)
    assert summary["violations_total"] == 0 and summary["checks"]["I2"] > 0


@pytest.mark.skipif(
    not (ROOT / "data/raw/SYNTHETIC/synthetic-p07-labels/tracks_causal.jsonl").exists()
    and not (ROOT / "data/labels/synthetic-p07-labels/tracks_causal.jsonl").exists(),
    reason="SYNTHETIC P07 labels not present",
)
def test_harness_assertions_on_synthetic_p07():
    script = _script()
    out = script.harness_assertions(ROOT / script.SYNTHETIC_SESSION, ROOT / script.SYNTHETIC_LABELS)
    assert all(v["violations"] == 0 for v in out.values())
    assert sum(v["commits"] for v in out.values()) > 0
