"""TEST-FI-MDL-1..5, TEST-FI-AUD-1..3, TEST-FI-SW-1: model, audio and arm-switch faults (Task 17.5).

Model faults use the analytic TorchScript fixture of ``tests/parity/live_helpers.py`` (SYNTHETIC);
audio faults run behind ``faults.FakeAudioBackend`` (no device is opened). Every run is audited by
the invariant monitor in ``raise`` mode.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from inv_helpers import Ticker, make_pipeline, run_frames

from spacedrums.app import AudioOutput, OutputLatency
from spacedrums.app import faults as F
from spacedrums.app.arms import build_model_arm
from spacedrums.app.invariants import InvariantMonitor
from spacedrums.app.synthetic import Swing, build_sequence, scenario
from spacedrums.contracts import Arm, HandId
from spacedrums.geometry import ZoneRegistry
from spacedrums.prediction.model_loader import file_hash


def _model_pipeline(model_cfg, *, factory=build_model_arm, clock=None, active="C-GRU", shadows=("A", "B")):
    model_cfg["anticipator"]["fallback"].update(
        enabled=True, window_frames=30, budget_s=1.0, processing_budget_s=10.0
    )
    registry = ZoneRegistry.from_config(model_cfg["zones"])
    return make_pipeline(
        model_cfg, registry, active=active, shadow=shadows, clock=clock, model_factory=factory
    ), registry


@pytest.mark.parametrize(
    "exception",
    [RuntimeError, TypeError, IndexError, KeyError, FloatingPointError, ZeroDivisionError, AttributeError],
)
def test_model_exception_of_any_type_falls_back(model_cfg, exception):
    """TEST-FI-MDL-1: an exception of any type inside inference is a fallback, never a crash."""

    def factory(cfg, clock):
        arm = build_model_arm(cfg, clock=clock)
        F.ModelFault(arm, kind="raise", after_calls=6, exception=exception)
        return arm

    pipe, registry = _model_pipeline(model_cfg, factory=factory)
    monitor = InvariantMonitor.for_pipeline(pipe, mode="raise")
    results = run_frames(pipe, scenario("repeated", registry, t_down=0.12), monitor=monitor)
    assert pipe.model_error and exception.__name__ in pipe.model_error
    assert pipe.active_arm is Arm.B and len(pipe.fallback_events) == 1
    t_fb = pipe.fallback_events[0]["t"]
    assert not [c for r in results for c in r.commits if c.arm is Arm.C_GRU and c.t_commit >= t_fb]


@pytest.mark.parametrize("kind", ["nan", "inf"])
def test_non_finite_model_output_falls_back(model_cfg, kind):
    """TEST-FI-MDL-2: a corrupt model producing non-finite trajectories is disabled, not silent."""

    def factory(cfg, clock):
        arm = build_model_arm(cfg, clock=clock)
        F.ModelFault(arm, kind=kind, after_calls=4)
        return arm

    pipe, registry = _model_pipeline(model_cfg, factory=factory)
    run_frames(
        pipe,
        scenario("single", registry, t_down=0.12),
        monitor=InvariantMonitor.for_pipeline(pipe, mode="raise"),
    )
    assert pipe.model_error and "non-finite" in pipe.model_error and pipe.active_arm is Arm.B


def test_slow_model_falls_back_on_budget(model_cfg):
    """TEST-FI-MDL-3: sustained slow inference trips the p95 budget; no commit in the fallback frame."""
    ticker = Ticker()
    model_cfg["anticipator"]["fallback"].update(budget_s=0.01)

    def factory(cfg, clock):
        arm = build_model_arm(cfg, clock=clock)
        F.ModelFault(arm, kind="slow", after_calls=0, delay_s=0.05, advance_clock=ticker.advance)
        return arm

    model_cfg["anticipator"]["fallback"].update(enabled=True, window_frames=4, processing_budget_s=10.0)
    registry = ZoneRegistry.from_config(model_cfg["zones"])
    pipe = make_pipeline(
        model_cfg, registry, active="C-GRU", shadow=("A", "B"), clock=ticker, model_factory=factory
    )
    run_frames(pipe, scenario("single", registry), monitor=InvariantMonitor.for_pipeline(pipe, mode="raise"))
    assert "inference p95" in pipe.model_error and pipe.active_arm is Arm.B


@pytest.mark.parametrize("fault", ["malformed_json", "wrong_types", "wrong_feature_dim", "missing_export"])
def test_package_faults_fall_back_at_load(model_cfg, fault):
    """TEST-FI-MDL-4: corrupt / wrong-schema packages are refused at load and the baseline sounds."""
    d = Path(model_cfg["anticipator"]["model"]["path"])
    manifest_path = d / "manifest.json"
    if fault == "malformed_json":
        manifest_path.write_text("{not json", encoding="utf-8")
    elif fault in ("wrong_types", "wrong_feature_dim"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if fault == "wrong_types":
            manifest["dt_step"] = "fast"
        else:
            manifest["F"] = manifest["F"] + 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        (d / "export.pt").unlink()
    model_cfg["anticipator"]["model"]["manifest_hash"] = file_hash(manifest_path)
    pipe, registry = _model_pipeline(model_cfg)
    assert pipe.model_error and pipe.model_error.startswith("load failure") and pipe.active_arm is Arm.B
    run_frames(pipe, scenario("single", registry), monitor=InvariantMonitor.for_pipeline(pipe, mode="raise"))


def test_fallback_keeps_one_sound_per_strike(model_cfg):
    """TEST-FI-MDL-5: a fallback between the model's commit and the crossing does not replay the strike."""
    registry = ZoneRegistry.from_config(model_cfg["zones"])
    frames = list(scenario("single", registry, t_down=0.12))
    probe, _ = _model_pipeline(model_cfg)
    first = next(
        i for i, r in enumerate(run_frames(probe, frames)) if any(c.arm is Arm.C_GRU for c in r.commits)
    )

    def factory(cfg, clock):
        arm = build_model_arm(cfg, clock=clock)
        F.ModelFault(arm, kind="raise", after_calls=2 * (first + 1))
        return arm

    pipe, _ = _model_pipeline(model_cfg, factory=factory)
    monitor = InvariantMonitor.for_pipeline(pipe, mode="raise")
    results = run_frames(pipe, frames, monitor=monitor)
    audible = [c for r in results for c in r.commits if not c.shadow]
    assert pipe.fallback_events and len(audible) <= len(scenario("single", registry).truth)


# -- arm switch ------------------------------------------------------------------------------


@pytest.mark.parametrize("offset", [1, 2, 3])
def test_switch_after_anticipatory_commit_never_doubles_the_sound(cfg, registry, offset):
    """TEST-FI-SW-1: the Phase 17 finding: B commits ahead of the crossing, the user switches to A;
    A must not sound the same strike again (audible I3/I4)."""
    overrides = {"commit": {"p_commit": 0.3, "tti_commit_s": 0.1}}
    frames = list(scenario("repeated", registry, t_down=0.12))
    pipe = make_pipeline(cfg, registry, active="B", shadow=("A",), overrides=overrides)
    monitor = InvariantMonitor.for_pipeline(pipe, mode="raise")
    first = None
    for i, (sample, obs) in enumerate(frames):
        if first is not None and i == first + offset:
            pipe.set_active_arm("A", sample.t_capture)
        r = pipe.step(sample, obs, t_now=sample.t_frame_available)
        monitor.observe(r, pipe)
        if first is None and any(c.arm is Arm.B and not c.shadow for c in r.commits):
            first = i
    assert first is not None
    assert monitor.finish()["violations_total"] == 0


# -- audio -----------------------------------------------------------------------------------


def _audio(cfg, clock, backend):
    return AudioOutput(
        cfg.data, latency=OutputLatency.unmeasured(), device_enabled=True, clock=clock, stream_factory=backend
    )


def _drive(pipe, out, backend, frames, clock, *, on_frame=None):
    states = []
    for i, (sample, obs) in enumerate(frames):
        clock.t = sample.t_frame_available
        if on_frame is not None:
            on_frame(i)
        states.append(out.check_health(sample.t_frame_available))
        pipe.step(sample, obs, t_now=sample.t_frame_available)
        backend.pump(12)
    return states


def test_audio_device_removal_and_reattach_recover(cfg, registry):
    """TEST-FI-AUD-1: removal -> DOWN (no crash, commits still scheduled and logged, not queued);
    retries fail while the device is absent; re-attach -> RUNNING and later strikes sound again,
    with no backlog of stale sounds."""
    clock = Ticker(step=0.0)
    backend = F.FakeAudioBackend(clock)
    out = _audio(cfg, clock, backend)
    pipe = make_pipeline(cfg, registry, active="A", shadow=("B",), clock=clock, audio=False)
    pipe.audio, pipe.gain_fn = out, out.gain
    swings = [Swing(HandId.RIGHT, "snare", 0.4 + 0.6 * k, t_down=0.12) for k in range(10)]
    frames = list(build_sequence(registry, swings, duration_s=6.4))
    out.start()

    def events(i):
        if i == 30:  # 1.0 s
            backend.remove()
        if i == 110:  # 3.7 s
            backend.reattach()

    states = _drive(pipe, out, backend, frames, clock, on_frame=events)
    out.stop()
    down = [i for i, s in enumerate(states) if s == "DOWN"]
    assert down and down[0] <= 30 + 20 and states[-1] == "RUNNING"
    stats = out.stats()["device"]
    assert stats["outages"] == 1 and stats["recoveries"] == 1 and stats["dropped_while_down"] >= 2
    assert backend.open_failures >= 1  # at least one retry failed while the device was absent
    recovered = backend.streams[-1]
    assert recovered.callbacks > 0 and any(np.abs(f).max() > 0 for f in recovered.frames_out)


def test_audio_start_failure_is_not_a_crash(cfg):
    """TEST-FI-AUD-2: no audio device at start: the app keeps running, the state is DOWN."""
    clock = Ticker(step=0.0)
    backend = F.FakeAudioBackend(clock)
    backend.remove()
    out = _audio(cfg, clock, backend)
    out.start()
    assert out.device_state == "DOWN" and out.check_health(clock()) == "DOWN"
    backend.reattach()
    clock.t += 5.0
    assert out.check_health(clock.t) == "RUNNING"


def test_audio_underrun_burst_is_counted(cfg, registry):
    """TEST-FI-AUD-3: underrun bursts are counted and late events handled (played late, counted)."""
    clock = Ticker(step=0.0)
    backend = F.FakeAudioBackend(clock)
    out = _audio(cfg, clock, backend)
    pipe = make_pipeline(cfg, registry, active="A", shadow=("B",), clock=clock, audio=False)
    pipe.audio, pipe.gain_fn = out, out.gain
    out.start()
    backend.underruns(10)
    _drive(pipe, out, backend, list(scenario("single", registry, t_down=0.12)), clock)
    assert out.stats()["mixer"]["underruns"] == 10
    assert out.device_state == "RUNNING"
