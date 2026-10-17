"""SYNTHETIC red painted tips through the shared product pipeline. No webcam, hand model or speaker opens.

Red-tip pixels are rendered from ``app.synthetic`` swings; the reference is the same pipeline fed the
swings' own tips (perfect measurements), so any difference is what red-tip perception changes.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_developer_demo import SilentStream, perception_for, pixel_sequence

from spacedrums.app import play
from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.app.red_tip_perception import RedTipPerception
from spacedrums.app.synthetic import Swing, build_sequence
from spacedrums.config import config_hash, load_config
from spacedrums.contracts import HandId, ResetReason, StickObservation, TipMethod
from spacedrums.contracts.perception import EndpointEvidence
from spacedrums.geometry import ZoneRegistry
from spacedrums.stick.red_tip import RedTipSettings
from spacedrums.stick.red_tip_synthetic import tip_frames

ROOT = Path(__file__).resolve().parents[2]
L, R = HandId.LEFT, HandId.RIGHT


def forbidden(*a, **kw):
    pytest.fail("red-tip mode must not open the hand model, camera, pose model or speaker here")


def pipeline_for(cfg, audio=None):
    return DecisionPipeline(
        cfg, registry=ZoneRegistry.from_config(cfg["zones"]), session_id="SYNTHETIC-RED", active_arm="A",
        hardware_id="SYNTHETIC", config_hash=config_hash(cfg), audio=audio,
        gain_fn=None if audio else (lambda zone, v: 1.0), developer_demo=True,
    )


def red_run(cfg, seq, monkeypatch, **render):
    """Red-tip pixels -> RedTipPerception -> pipeline -> audio; returns (commits, audio events, frames)."""
    monkeypatch.setattr("spacedrums.hands.HandLandmarker", forbidden)
    perception = RedTipPerception(cfg)
    clock = [0.0]
    audio = AudioOutput(cfg, latency=OutputLatency.unmeasured(), device_enabled=True, clock=lambda: clock[0],
                        stream_factory=SilentStream)
    audio.start()
    pipeline = pipeline_for(cfg, audio)
    commits, sounds, frames = [], [], []
    for view, _ in tip_frames(seq, **render):
        clock[0] = view.sample.t_frame_available
        obs = perception(view)
        frame = perception.estimator.frame
        for hand in frame.resets:
            pipeline.reset_hand(hand)
        evidence = perception.estimator.evidence
        result = pipeline.step(view.sample, obs, t_now=clock[0], endpoint_evidence=evidence)
        commits.extend(result.commits)
        sounds.extend(result.audio)
        frames.append((view, frame, dict(perception.estimator.evidence), obs))
    audio.stop()
    return commits, sounds, frames


def measured(sample, obs, *, method=TipMethod.MARKER, kind="MEASURED", shift=0.0, hidden=()):
    """Observations + evidence from the synthetic tips themselves (perfect measurements)."""
    fid, t = sample.frame_id, sample.t_capture
    sticks, evidence = {}, {}
    for h, (hand, st) in obs.items():
        if st.present and h not in hidden:
            stick = StickObservation(fid, t, h, True, method, st.tip, (0.0, -1.0), st.tip, 0.9, 0.0, None)
            tip = (st.tip[0] + shift, st.tip[1])
            evidence[h] = EndpointEvidence(fid, t, h, kind, "IDEAL", tip, stick.tip, 0.9, 1.0)
        else:
            stick = StickObservation.absent(fid, t, h, method)
            evidence[h] = EndpointEvidence(fid, t, h, "MISSING", "IDEAL")
        sticks[h] = (hand, stick)
    return sticks, evidence


def ideal_commits(cfg, seq, occluded=()):
    """The same pipeline fed the synthetic tips themselves (perfect measurements, labelled MARKER)."""
    pipeline = pipeline_for(cfg)
    commits = []
    for sample, obs in seq.frames:
        sample = replace(sample, roi_px=(0, 0, 640, 480))
        hidden = {h for h in (L, R) if (h, sample.frame_id) in occluded}
        sticks, evidence = measured(sample, obs, hidden=hidden)
        commits.extend(pipeline.step(sample, sticks, t_now=sample.t_frame_available,
                                     endpoint_evidence=evidence).commits)
    return commits


def same_strikes(red, ideal, *, frames=1):
    """Zone for zone, within ``frames``; hands may carry either label but each maps to exactly one.

    Commits of one frame are listed in hand-label order, so simultaneous hits are compared by zone.
    """
    red = sorted(red, key=lambda c: (c.frame_id, c.zone_id))
    ideal = sorted(ideal, key=lambda c: (c.frame_id, c.zone_id))
    assert [c.zone_id for c in red] == [c.zone_id for c in ideal]
    assert all(abs(a.frame_id - b.frame_id) <= frames for a, b in zip(red, ideal, strict=True))
    mapping = {}
    for a, b in zip(red, ideal, strict=True):
        assert mapping.setdefault(b.hand_id, a.hand_id) == a.hand_id  # a consistent identity, never swapped
    assert len(set(mapping.values())) == len(mapping)


def sequence(kit, swings):
    cfg = play.play_config(demo=True, kit=kit, red_tips=True)
    registry = ZoneRegistry.from_config(cfg["zones"])
    return cfg, registry, build_sequence(registry, swings, duration_s=max(s.t_up_end for s in swings) + 0.4)


def test_red_tip_config_is_additive_and_the_other_modes_keep_their_configuration():
    for kw in ({}, {"demo": True, "kit": "four"}, {"demo": True, "kit": "full"}):
        plain, red = play.play_config(**kw), play.play_config(red_tips=True, **kw)
        assert "stick_tip" not in plain["product"]
        assert {**red, "product": {k: v for k, v in red["product"].items() if k != "stick_tip"}} == plain
    direct = load_config(ROOT / "configs/prototype.candidate.yaml", ROOT / "configs/product.candidate.yaml")
    assert direct.data["product"] == play.play_config()["product"]
    # The documented candidate values are exactly the code defaults.
    assert RedTipSettings.from_config(play.play_config(red_tips=True)) == RedTipSettings()


# app.synthetic parks a hand at its first swing's start; LEFT is offset so the two tips never coincide
# (two sticks on one point are genuinely ambiguous, see test_red_tip_tracker). Zone orders are chosen so the
# straight path between two swings does not itself cross a pad edge (it would, for perfect tips too).
FOUR_PAD = ([Swing(R, "snare", 0.2 + i * 0.5) for i in range(5)]
            + [Swing(R, z, 3.0 + i * 0.6) for i, z in enumerate(("crash_ride", "tom1", "hihat"))]
            + [Swing(L, "snare", 5.0, x_offset=-0.04), Swing(R, "crash_ride", 5.0)])
FULL_KIT_RIGHT = [Swing(R, z, 0.3 + 0.6 * i) for i, z in enumerate(("snare", "tom1", "floor_tom", "ride"))]
FULL_KIT_LEFT = [Swing(L, z, 0.3 + 0.6 * i) for i, z in enumerate(("hihat", "snare", "tom2", "crash"))]


@pytest.mark.parametrize(("kit", "swings"),
                         [("four", FOUR_PAD), ("full", FULL_KIT_RIGHT), ("full", FULL_KIT_LEFT)])
@pytest.mark.parametrize("exposure", [0.0, 0.5])
def test_red_tip_strikes_match_perfect_measurements_zone_for_zone(kit, swings, exposure, monkeypatch):
    cfg, registry, seq = sequence(kit, swings)
    red, sounds, _ = red_run(cfg, seq, monkeypatch, exposure_fraction=exposure)
    ideal = ideal_commits(cfg, seq)
    assert [c.zone_id for c in ideal] == [e.zone_id for e in seq.truth]  # the scene is a fair reference
    same_strikes(red, ideal)
    assert [e.sample_id for e in sounds] == [registry[c.zone_id].sample_id for c in red]
    assert len({c.strike_id for c in red}) == len(red)
    if kit == "four":  # the simultaneous pair sounds in one frame, from two independent sticks
        assert red[-1].frame_id == red[-2].frame_id and red[-1].hand_id != red[-2].hand_id


def test_rapid_alternating_roll_sounds_every_stroke_exactly_once(monkeypatch):
    roll = [Swing(R if i % 2 else L, "snare", 0.3 + 0.16 * i, t_down=0.12,
                  x_offset=0.035 if i % 2 else -0.035) for i in range(12)]
    cfg, _, seq = sequence("four", roll)
    red, _, _ = red_run(cfg, seq, monkeypatch, exposure_fraction=0.5)
    ideal = ideal_commits(cfg, seq)
    assert len(ideal) == 12
    same_strikes(red, ideal)
    for hand in {c.hand_id for c in red}:
        times = [c.t_impact_target for c in red if c.hand_id is hand]
        assert all(b - a > 0.25 for a, b in zip(times, times[1:], strict=False))  # no double triggers


@pytest.mark.parametrize("swing", [Swing(R, "snare", 0.3, kind="hover"),
                                   Swing(L, "hihat", 0.3, kind="stop_short", depth=-0.03),
                                   Swing(R, "tom1", 0.3, kind="lateral"),
                                   Swing(L, "crash_ride", 0.3, kind="upward")])
def test_movement_that_is_not_a_strike_never_sounds(swing, monkeypatch):
    cfg, _, seq = sequence("four", [swing])
    red, sounds, _ = red_run(cfg, seq, monkeypatch, exposure_fraction=0.5)
    assert ideal_commits(cfg, seq) == [] and red == [] and sounds == []


def test_a_crossing_seen_only_as_a_prediction_never_strikes(monkeypatch):
    cfg, _, seq = sequence("four", [Swing(R, "snare", 0.3)])
    assert len(ideal_commits(cfg, seq)) == 1
    hidden = set(range(12, 19))  # disappears moving down above the edge, reappears moving up above it
    red, sounds, frames = red_run(cfg, seq, monkeypatch, exposure_fraction=0.0, hidden={R: hidden})
    assert red == [] and sounds == []
    assert ideal_commits(cfg, seq, occluded={(R, k) for k in hidden}) == []
    for view, frame, evidence, obs in frames:
        if view.sample.frame_id in hidden:
            coasting = [h for h, st in frame.slots.items() if st.state == "PREDICTED"]
            assert len(coasting) == 1  # the hidden stick keeps its identity ...
            h = coasting[0]
            assert frame.slots[h].predicted is not None and frame.slots[h].tip is None
            assert evidence[h].kind == "UNCERTAIN" and evidence[h].tip is None  # ... but no coordinates
            sticks = {hand: stick for hand, (_, stick) in obs.items()}
            assert not sticks[h].present and sticks[h].tip is None
            assert sum(s.present for s in sticks.values()) == 1  # only the other, visible stick is measured


def test_reset_hand_restarts_strokes_but_keeps_refractory_timers():
    cfg, _, seq = sequence("four", [Swing(R, "snare", 0.3)])
    pipeline = pipeline_for(cfg)
    results = []
    for k, (sample, obs) in enumerate(seq.frames[:2]):
        sample = replace(sample, roi_px=(0, 0, 640, 480))
        if k == 1:
            timers = pipeline.policies[pipeline.active_arm][R].timers.snapshot()
            pipeline.reset_hand(R)
        sticks, evidence = measured(sample, obs)
        t_now = sample.t_frame_available
        results.append(pipeline.step(sample, sticks, t_now=t_now, endpoint_evidence=evidence))
    result = results[-1]
    assert result.hands[R].track.reset_reason is ResetReason.LOW_CONFIDENCE
    assert result.hands[L].track.reset_reason is None
    assert pipeline.geometry.diagnostics[R]["reason"] == "NEED_RECENT_TRAJECTORY"
    assert pipeline.policies[pipeline.active_arm][R].timers.snapshot() == timers


def test_product_pipeline_accepts_marker_tips_and_still_refuses_mismatched_evidence():
    cfg, _, seq = sequence("four", [Swing(R, "snare", 0.3)])
    sample, obs = seq.frames[0]
    sample = replace(sample, roi_px=(0, 0, 640, 480))

    def step(method, kind="MEASURED", shift=0.0):
        sticks, evidence = measured(sample, obs, method=method, kind=kind, shift=shift)
        t_now = sample.t_frame_available
        return pipeline_for(cfg).step(sample, sticks, t_now=t_now, endpoint_evidence=evidence)

    assert step(TipMethod.MARKER).hands[R].track.tip_method is TipMethod.MARKER
    with pytest.raises(ValueError, match="must match"):
        step(TipMethod.MARKER, shift=0.01)
    with pytest.raises(ValueError, match="must match"):
        step(TipMethod.GEOM)
    # Non-measured evidence: a red-tip stick stays MARKER; every other method keeps the AXIS_REFINED label.
    assert step(TipMethod.MARKER, kind="UNCERTAIN").hands[R].track.tip_method is TipMethod.MARKER
    assert step(TipMethod.GEOM, kind="UNCERTAIN").hands[R].track.tip_method is TipMethod.AXIS_REFINED
    assert step(TipMethod.AXIS_REFINED, kind="UNCERTAIN").hands[R].track.tip_method is TipMethod.AXIS_REFINED


class SyntheticReplay:
    rows = []

    def __init__(self, *a, **kw):
        from spacedrums.capture import Roi

        self.roi = Roi(0, 0, 640, 480)

    def __iter__(self):
        return iter(v.sample for v, _ in self.rows)

    def view(self, sample):
        return self.rows[sample.frame_id][0]


def launch(monkeypatch, tmp_path, argv, rows, *, window=False):
    SyntheticReplay.rows = rows
    monkeypatch.setattr(play, "ReplayFrameSource", SyntheticReplay)
    monkeypatch.setattr(play, "OpenCvCamera", forbidden)
    monkeypatch.setattr(play, "BodyLandmarker", forbidden)
    monkeypatch.setattr("sounddevice.OutputStream", forbidden)
    shown = []
    if window:
        keys = iter([ord("d"), ord("d")] + [-1] * 1000)
        monkeypatch.setattr(play.cv2, "namedWindow", lambda *a, **k: None)
        monkeypatch.setattr(play.cv2, "resizeWindow", lambda *a, **k: None)
        monkeypatch.setattr(play.cv2, "destroyAllWindows", lambda *a, **k: None)
        monkeypatch.setattr(play.cv2, "imshow", lambda name, img: shown.append(img.shape))
        monkeypatch.setattr(play.cv2, "pollKey", lambda: next(keys))
    output = tmp_path / "run"
    assert play.main([*argv, "--replay", "SYNTHETIC", "--output", str(output)]) == 0
    report = json.loads((output / "report.json").read_text())
    records = [json.loads(line) for line in (output / "observations.jsonl").read_text().splitlines()]
    return report, records, shown


def test_red_tip_launcher_logs_marker_diagnostics_without_the_hand_model(monkeypatch, tmp_path):
    monkeypatch.setattr("spacedrums.hands.HandLandmarker", forbidden)
    cfg, _, seq = sequence("four", [Swing(R, "snare", 0.3)])
    argv = ["--demo", "--kit", "four", "--red-tips", "--no-window"]
    report, records, _ = launch(monkeypatch, tmp_path, argv, list(tip_frames(seq)))
    assert report["error"] is None and report["commits_by_drum"]["snare"] == 1
    assert report["tip_method"] == "MARKER" and report["red_tip"]["method_id"] == "MARKER"
    assert report["red_tip"]["hand_assist"] is False and report["models"]["hands"] is None
    assert report["model_sha256"]["hands"] is None
    assert report["config"]["product"]["stick_tip"] == RedTipSettings().as_dict()
    assert report["red_tip"]["slots"]["LEFT"]["measured_frames"] > 0
    assert report["latency_ms"]["red_tip_ms"]["p50"] > 0
    assert "RED_TIP" in report["endpoint_reasons"]
    assert all(r["red_tip"]["slots"].keys() == {"LEFT", "RIGHT"} for r in records)
    assert all(h["detector_id"] == "red-tip-only" and not h["present"] for r in records for h in r["hands"])
    assert {s["method_id"] for r in records for s in r["sticks"]} == {"MARKER"}
    hits = [r for r in records if r["commits"]]
    assert len(hits) == 1 and hits[0]["decisions"][hits[0]["commits"][0]["hand_id"]]["gates"]


def test_red_tip_full_kit_window_shows_the_stage_and_the_tip_diagnostics(monkeypatch, tmp_path):
    monkeypatch.setattr("spacedrums.hands.HandLandmarker", forbidden)
    cfg, _, seq = sequence("full", [Swing(R, "snare", 0.3)])
    rows = list(tip_frames(seq))
    report, _, shown = launch(monkeypatch, tmp_path, ["--demo", "--red-tips"], rows, window=True)
    assert report["error"] is None and report["commits_by_drum"]["snare"] == 1
    assert (720, 960, 3) in shown and (480, 640, 3) in shown  # stage view, then diagnostics after 'd'


def test_tip_mode_flags_are_validated(tmp_path):
    for argv in (["--red-tips", "--fingers"], ["--hand-assist"], ["--stick-tip-config", "x.yaml"]):
        with pytest.raises(SystemExit):
            play.main([*argv, "--check"])
    with pytest.raises(ValueError, match="--red-tips"):
        play.play_config(hand_assist=True)
    bad = tmp_path / "bad.yaml"
    bad.write_text("commit:\n  refractory_zone_s: 0.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="only product: stick_tip"):
        play.play_config(red_tips=True, stick_tip=bad)
    good = tmp_path / "good.yaml"
    good.write_text("product:\n  stick_tip:\n    s_min: 100\n    ignore_regions: [[0.0, 0.0, 0.1, 0.1]]\n",
                    encoding="utf-8")
    cfg = play.play_config(red_tips=True, stick_tip=good, hand_assist=True)
    settings = RedTipSettings.from_config(cfg)
    assert settings.s_min == 100 and settings.hand_assist
    assert settings.ignore_regions == ((0.0, 0.0, 0.1, 0.1),)
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("product:\n  stick_tip:\n    s_min: 999\n", encoding="utf-8")
    with pytest.raises(Exception, match="999"):
        play.play_config(red_tips=True, stick_tip=invalid)


def test_fingertip_mode_is_unchanged_by_the_red_tip_option(monkeypatch, tmp_path):
    cfg = play.play_config(demo=True)
    rows = list(pixel_sequence(cfg, [Swing(R, "snare", 0.3)], 1.0))
    perception_for(monkeypatch, rows)
    calls = []
    from spacedrums import hands as hands_module

    synthetic = hands_module.HandLandmarker

    class CountingHands(synthetic):
        def detect(self, view):
            calls.append(view.sample.frame_id)
            return super().detect(view)

    monkeypatch.setattr("spacedrums.hands.HandLandmarker", CountingHands)
    argv = ["--demo", "--kit", "four", "--fingers", "--no-window"]
    report, records, _ = launch(monkeypatch, tmp_path, argv, rows)
    assert report["error"] is None
    assert "red_tip" not in report and "tip_method" not in report
    assert report["models"]["hands"] == cfg["hands"]["model_asset_id"] and report["model_sha256"]["hands"]
    assert "stick_tip" not in report["config"]["product"]
    assert set(report["endpoint_reasons"]) <= {"FINGERTIP", "HAND_MISSING", "WEAK_OR_SHORT_SUPPORT"}
    assert calls == list(range(len(rows)))  # the hand model runs on every frame, as before
    assert all("red_tip" not in r for r in records)
    assert {s["method_id"] for r in records for s in r["sticks"]} == {"AXIS_REFINED"}


@pytest.mark.parametrize("mode", [["--fingers"], []])
def test_hand_modes_never_build_the_red_tip_perception(monkeypatch, tmp_path, mode):
    """HAND regression (2026-10-16 revision): fingertip and visible-stick runs never construct the colour
    perception, and their configuration carries no stick_tip block."""
    cfg = play.play_config(demo=True)
    rows = list(pixel_sequence(cfg, [Swing(R, "snare", 0.3)], 1.0))
    perception_for(monkeypatch, rows)
    monkeypatch.setattr(play, "RedTipPerception", forbidden)
    argv = ["--demo", "--kit", "four", *mode, "--no-window"]
    report, records, _ = launch(monkeypatch, tmp_path, argv, rows)
    assert report["error"] is None
    assert "stick_tip" not in report["config"]["product"] and "red_tip" not in report
    assert all("red_tip" not in r for r in records)
