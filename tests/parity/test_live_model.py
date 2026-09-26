import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
import torch
from live_helpers import compare_records, parity, pipeline
from live_helpers import model_cfg as _model_cfg

from spacedrums.app.arms import ArmSwitch, build_model_arm
from spacedrums.app.synthetic import Swing, build_sequence, scenario
from spacedrums.config import ConfigError, validate
from spacedrums.contracts import Arm, HandId
from spacedrums.geometry import ZoneRegistry
from spacedrums.prediction.budget_monitor import BudgetMonitor
from spacedrums.prediction.model_loader import file_hash

model_cfg = _model_cfg


def sequence(cfg, **kwargs):
    return scenario("repeated", ZoneRegistry.from_config(cfg["zones"]), t_down=0.12, **kwargs)


def test_test_parity_1_nonempty_commits_and_features(model_cfg):
    report, _ = parity(model_cfg, sequence(model_cfg), session_id="synthetic-parity", measured_delay=False)
    assert report["passed"] and not report["empty_prediction_set"] and not report["empty_commit_set"]
    assert report["comparisons"]["features"]["max_abs_deviation"] == 0


def test_parity_tracking_loss_both_hands_jitter_drops(model_cfg):
    r = ZoneRegistry.from_config(model_cfg["zones"])
    seq = build_sequence(
        r,
        [Swing(HandId.LEFT, "snare", 0.4, t_down=0.12), Swing(HandId.RIGHT, "snare", 1.2, t_down=0.12)],
        duration_s=2.4,
        occluded={HandId.LEFT: set(range(12, 24))},
        dropped={35: 3},
        jitter_dt=0.002,
        name="synthetic-loss",
    )
    report, results = parity(model_cfg, seq, session_id="loss", measured_delay=False)
    assert report["passed"]
    assert any(h.track.status == "INVALID" for r in results for h in r.hands.values())
    assert all(
        h.model_prediction is None
        for r in results
        for h in r.hands.values()
        if h.track.status in ("INVALID", "STALE")
    )


def test_causal_1_future_perturbation_live_loop(model_cfg):
    seq = list(sequence(model_cfg))
    cut = len(seq) // 2
    changed = copy.deepcopy(seq)
    for i in range(cut, len(changed)):
        sample, obs = changed[i]
        changed[i] = sample, {h: (ho, replace(so, tip=(0.99, 0.99))) for h, (ho, so) in obs.items()}
    _, a = parity(model_cfg, seq, session_id="causal", measured_delay=False)
    _, b = parity(model_cfg, changed, session_id="causal", measured_delay=False)
    for i in range(cut):
        compare_records(a[i].commits, b[i].commits)
        for h in HandId:
            compare_records([a[i].hands[h].features], [b[i].hands[h].features])
            p, q = a[i].hands[h].model_prediction, b[i].hands[h].model_prediction
            assert (p is None) == (q is None)
            if p:
                compare_records([p], [q], ignored=("t_inference_done",))


def test_no_future_observation_and_duplicate_delivery(model_cfg):
    p = pipeline(model_cfg, "future")
    sample, obs = next(iter(sequence(model_cfg)))
    altered = dict(obs)
    ho, so = altered[HandId.LEFT]
    altered[HandId.LEFT] = replace(ho, t_capture=ho.t_capture + 0.1), so
    with pytest.raises(AssertionError, match="delivered"):
        p.step(sample, altered)
    p.step(sample, obs, t_now=sample.t_frame_available)
    with pytest.raises(ValueError, match="strictly increase"):
        p.step(sample, obs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("N", 3),
        ("family", "tcn"),
        ("feature_schema_id", "bad"),
        ("hash", "sha256:" + "1" * 64),
        ("manifest_hash", "sha256:" + "1" * 64),
    ],
)
def test_loader_refuses_mismatch(model_cfg, field, value):
    model_cfg["anticipator"]["model"][field] = value
    with pytest.raises(ValueError, match="mismatch"):
        build_model_arm(model_cfg, clock=lambda: 1.0)


@pytest.mark.parametrize("fault", ["corrupt_export", "missing_stats", "stats_tamper", "dt", "fps", "schema"])
def test_loader_other_faults(model_cfg, fault):
    m = model_cfg["anticipator"]["model"]
    if fault == "corrupt_export":
        (Path(m["path"]) / "export.pt").write_bytes(b"bad")
    elif fault == "missing_stats":
        m["norm_stats_path"] += ".missing"
    elif fault == "stats_tamper":
        Path(m["norm_stats_path"]).write_text("{}")
    elif fault == "dt":
        model_cfg["anticipator"]["dt_step_s"] *= 2
    elif fault == "fps":
        model_cfg["camera_profile"]["requested_fps"] = 60
    else:
        model_cfg["features"]["groups"] = ["POS"]
    with pytest.raises((OSError, ValueError)):
        build_model_arm(model_cfg, clock=lambda: 1.0)


def test_budget_percentile_and_bounded_window():
    b = BudgetMonitor(0.01, 5)
    assert not any(b.observe(x) for x in [0.001] * 4)
    assert b.observe(0.1)
    for _ in range(5):
        b.observe(0.001)
    assert b.p95 == 0.001 and len(b.samples) == 5
    with pytest.raises(ValueError):
        b.observe(float("nan"))


@pytest.mark.parametrize("rule,expected", [(True, Arm.B), (False, Arm.A)])
def test_missing_model_falls_back_without_fabricated_strike(model_cfg, rule, expected):
    model_cfg["anticipator"]["fallback"]["enabled"] = True
    model_cfg["anticipator"]["model"]["path"] += "/missing"
    if not rule:
        model_cfg["anticipator"]["rule"] = None
    p = pipeline(model_cfg, "missing")
    assert p.active_arm == expected and p.fallback_events and p.model_error
    sample, obs = next(iter(sequence(model_cfg)))
    assert not p.step(sample, obs, t_now=sample.t_frame_available).commits
    with pytest.raises(ValueError, match="unavailable"):
        p.set_active_arm("C-GRU", 1.0)


def test_slow_model_fault_disables_inference_and_preserves_shadow_active(model_cfg):
    model_cfg["anticipator"]["fallback"].update(
        enabled=True, window_frames=1, budget_s=0.01, processing_budget_s=10
    )
    ticks = [0.0]

    def clock():
        return ticks[0]

    def factory(cfg, clock):
        arm = build_model_arm(cfg, clock=clock)
        original = arm.adapter.predict

        def slow(*args):
            ticks[0] += 0.1
            return original(*args)

        arm.adapter.predict = slow
        return arm

    p = pipeline(model_cfg, "slow", clock=clock, model_factory=factory, active="A", shadows=("B", "C-GRU"))
    sample, obs = next(iter(sequence(model_cfg)))
    assert not p.step(sample, obs, t_now=sample.t_frame_available).commits
    assert p.active_arm == Arm.A and "inference p95" in p.model_error
    n = ticks[0]
    sample, obs = list(sequence(model_cfg))[1]
    p.step(sample, obs, t_now=sample.t_frame_available)
    assert ticks[0] == n and len(p.fallback_events) == 1


def test_total_budget_includes_perception(model_cfg):
    model_cfg["anticipator"]["fallback"].update(enabled=True, window_frames=1, processing_budget_s=0.02)
    p = pipeline(model_cfg, "total", clock=lambda: 100.0)
    sample, obs = next(iter(sequence(model_cfg)))
    p.step(sample, obs, t_now=sample.t_frame_available, processing_started=99.0)
    assert p.active_arm == Arm.B and "total processing" in p.model_error


def test_rate_mismatch_detected_online(model_cfg):
    model_cfg["anticipator"]["fallback"]["enabled"] = True
    p = pipeline(model_cfg, "rate", clock=lambda: 100.0)
    for sample, obs in sequence(model_cfg, dt=1 / 60):
        p.step(sample, obs, t_now=sample.t_frame_available)
    assert "FPS" in p.model_error and p.active_arm == Arm.B


def test_arm_switch_and_c_shadow_never_sound(model_cfg):
    p = pipeline(model_cfg, "switch", active="A", shadows=("B", "C-GRU"))
    rows = []
    for i, (sample, obs) in enumerate(sequence(model_cfg)):
        if i == 50:
            p.set_active_arm("C-GRU", sample.t_capture)
        r = p.step(sample, obs, t_now=sample.t_frame_available)
        if i == 50:
            assert not r.commits
        rows.extend(r.commits)
    assert any(c.arm == Arm.C_GRU and c.shadow for c in rows)
    assert any(c.arm == Arm.C_GRU and not c.shadow for c in rows)
    assert all(c.shadow == (c.arm != (Arm.A if c.frame_id < 50 else Arm.C_GRU)) for c in rows)
    s = ArmSwitch(("A", "B"), "A")
    with pytest.raises(ValueError):
        s.select("C-TCN", 1.0)


def test_config_schema_and_missing_manifest_pin(model_cfg):
    validate(model_cfg)
    del model_cfg["anticipator"]["model"]["manifest_hash"]
    with pytest.raises(ConfigError, match="missing fields"):
        validate(model_cfg)


def test_parity_negative_control_detects_prediction_drift(model_cfg):
    _, results = parity(model_cfg, sequence(model_cfg), session_id="negative", measured_delay=False)
    pred = next(h.model_prediction for r in results for h in r.hands.values() if h.model_prediction)
    changed = replace(pred, positions=tuple((x + 0.01, y) for x, y in pred.positions))
    with pytest.raises(AssertionError):
        compare_records([pred], [changed])


def test_tcn_export_uses_same_live_harness_path(model_cfg):
    from spacedrums.models.temporal.config import TemporalConfig, build_model

    m = model_cfg["anticipator"]["model"]
    path = Path(m["path"])
    manifest = json.loads((path / "manifest.json").read_text())
    c = TemporalConfig(**{**manifest["config"], "family": "tcn"})
    model = build_model(c).eval()
    torch.jit.script(model).save(str(path / "export.pt"))
    manifest.update(
        family="tcn", config=c.to_dict(), config_hash=c.config_hash, export_hash=file_hash(path / "export.pt")
    )
    (path / "manifest.json").write_text(json.dumps(manifest))
    m.update(family="tcn", hash=manifest["export_hash"], manifest_hash=file_hash(path / "manifest.json"))
    report, _ = parity(model_cfg, sequence(model_cfg), session_id="tcn", measured_delay=False)
    assert report["passed"] and not report["empty_prediction_set"]


def test_model_hand_loss_clears_only_that_hand(model_cfg):
    p = pipeline(model_cfg, "hands")
    frames = list(sequence(model_cfg))
    for sample, obs in frames[:5]:
        r = p.step(sample, obs, t_now=sample.t_frame_available)
    model = p.model_arm
    right_before = list(model.stream.rings["RIGHT"])
    track = r.hands[HandId.LEFT].track
    invalid = replace(
        track,
        frame_id=5,
        t_capture=frames[5][0].t_capture,
        status="INVALID",
        frames_since_valid=1,
        confidence=0.0,
        history_ref=None,
        tip_filtered=None,
        tip_velocity=None,
        tip_acceleration=None,
        axis_angle=None,
        axis_angular_velocity=None,
    )
    assert model.step(invalid, delivered_t=invalid.t_capture) is None
    assert len(model.histories[HandId.LEFT]) == 1
    assert list(model.stream.rings["RIGHT"]) == right_before
    with pytest.raises(AssertionError, match="future"):
        model.step(invalid, delivered_t=invalid.t_capture - 0.1)


def test_model_shadow_audio_and_timing_records(model_cfg):
    from spacedrums.app.audio_out import AudioOutput, OutputLatency

    p = pipeline(model_cfg, "audio", active="A", shadows=("B", "C-GRU"))
    p.audio = AudioOutput(model_cfg, latency=OutputLatency.unmeasured(), device_enabled=False)
    commits, events, stamps = [], [], []
    for sample, obs in sequence(model_cfg):
        r = p.step(sample, obs, t_now=sample.t_frame_available)
        commits.extend(r.commits)
        events.extend(r.audio)
        stamps.extend(t for t in r.timing if t.kind == "STRIKE" and t.arm == Arm.C_GRU)
    shadow_ids = {c.strike_id for c in commits if c.arm == Arm.C_GRU}
    assert shadow_ids and events and not shadow_ids.intersection(e.strike_id for e in events)
    assert all(t.t_features_done <= t.t_inference_done <= t.t_candidate for t in stamps)
    assert all(t.t_audio_scheduled is None for t in stamps)


def test_parity_timestamp_tolerance_does_not_scale_with_epoch(model_cfg):
    _, results = parity(model_cfg, sequence(model_cfg), session_id="clock", measured_delay=False)
    strike = next(c for r in results for c in r.commits if c.arm == Arm.C_GRU)
    original = replace(strike, t_commit=125000.0)
    delayed = replace(original, t_commit=125000.01)
    with pytest.raises(AssertionError):
        compare_records([original], [delayed])
