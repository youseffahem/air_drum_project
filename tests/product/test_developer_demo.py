"""SYNTHETIC software verification. No webcam or speaker is opened by these tests."""

import json
from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from spacedrums.app import play
from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.main import Perception
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.app.synthetic import Swing, build_sequence
from spacedrums.calib.developer_demo import DeveloperDemoLayout
from spacedrums.capture import Roi
from spacedrums.config import config_hash
from spacedrums.contracts import FrameView, HandId, HandObservation, ImageRef
from spacedrums.geometry import ZoneRegistry
from spacedrums.ui.developer_demo import DemoOverlay


class SilentStream:
    def __init__(self, **kwargs):
        self.active = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        pass


def pixel_sequence(cfg, swings, duration):
    """Render visible sticks and matching synthetic hands. Endpoints are NOT supplied to perception."""
    registry = ZoneRegistry.from_config(cfg["zones"])
    for sample, observations in build_sequence(registry, swings, duration_s=duration):
        image = np.full((480, 640, 3), 60, np.uint8)
        hands = {}
        for hand, (_, stick) in observations.items():
            if not stick.present:
                hands[hand] = HandObservation.absent(sample.frame_id, sample.t_capture, hand, "SYNTHETIC")
                continue
            active = any(s.hand == hand and s.t_start <= sample.t_capture - 100 <= s.t_up_end
                         for s in swings)
            tip = np.array(stick.tip if active else
                           (0.10 if hand is HandId.LEFT else 0.94, 0.40)) * [640, 480]
            grip = tip - [0, 80]
            # A closed fist rotated 180 degrees, with its measured stick pointing down.
            lm = np.zeros((21, 2))
            lm[0] = grip - [12, 27]
            for f, k in enumerate((5, 9, 13, 17)):
                base = grip - [0, f * 10]
                lm[k] = base
                lm[k + 1], lm[k + 2], lm[k + 3] = base - [8, 0], base - [15, 0], base - [21, 0]
            lm[1], lm[2], lm[3], lm[4] = grip - [6, 10], grip - [10, 4], grip - [12, -3], grip - [13, -9]
            hands[hand] = HandObservation(
                sample.frame_id, sample.t_capture, hand, True, "SYNTHETIC",
                tuple(map(tuple, lm / [640, 480])), None, 0.95, (0, 0, 1, 1),
            )
            cv2.line(image, tuple(grip.astype(int)), tuple(tip.astype(int)), (200, 200, 200), 6)
        sample = replace(sample, roi_px=(0, 0, 640, 480), image_ref=ImageRef.memory(image))
        yield FrameView(sample, image, image), hands


def perception_for(monkeypatch, rows):
    hand_lookup = {view.sample.frame_id: hands for view, hands in rows}

    class SyntheticHands:
        def __init__(self, settings):
            self.asset = SimpleNamespace(sha256="SYNTHETIC")

        def detect(self, view):
            hands = hand_lookup[view.sample.frame_id]
            return SimpleNamespace(left=hands[HandId.LEFT], right=hands[HandId.RIGHT], processing_s=0.0)

        def close(self):
            pass

    monkeypatch.setattr("spacedrums.hands.HandLandmarker", SyntheticHands)


def pipeline_for(cfg, audio, clock, *, demo=True):
    return DecisionPipeline(
        cfg, registry=ZoneRegistry.from_config(cfg["zones"]), session_id="SYNTHETIC-DEMO",
        active_arm="A", hardware_id="SYNTHETIC", config_hash=config_hash(cfg), audio=audio,
        clock=clock, developer_demo=demo,
    )


def test_demo_opt_in_preserves_production_thresholds_and_layout():
    normal, demo = play.play_config(), play.play_config(demo=True)
    assert "developer_demo" not in normal["product"]
    for key in ("endpoint", "reach"):
        assert normal["product"][key] == demo["product"][key]
    # The demo alone may fire one camera frame early; every other stroke threshold is production's.
    assert {**normal["product"]["stroke"], "lead_s": 0.033} == demo["product"]["stroke"]
    for key in ("commit", "tracking", "geometry", "audio", "stick"):
        assert normal[key] == demo[key]
    layout = DeveloperDemoLayout(demo)
    assert layout.state == "DEMO_FIXED"
    assert not layout.report()["calibration_passed"]
    audio = AudioOutput(demo, latency=OutputLatency.unmeasured(), device_enabled=False)
    with pytest.raises(ValueError, match="opt-in"):
        pipeline_for(demo, audio, lambda: 100.0, demo=False)


def test_pixels_to_shared_pipeline_and_production_mixer(monkeypatch, tmp_path):
    cfg = play.play_config(demo=True)
    swings = [Swing(HandId.RIGHT, "snare", 0.2 + i * 0.5) for i in range(5)]
    swings += [Swing(HandId.RIGHT, z, 3.0 + i * 0.6) for i, z in enumerate(("crash_ride", "hihat", "tom1"))]
    swings += [Swing(h, z, 5.0) for h, z in ((HandId.LEFT, "snare"), (HandId.RIGHT, "crash_ride"))]
    rows = list(pixel_sequence(cfg, swings, 5.8))
    perception_for(monkeypatch, rows)
    perception = Perception(cfg)
    current = [100.0]
    audio = AudioOutput(cfg, latency=OutputLatency.unmeasured(), device_enabled=True,
                        clock=lambda: current[0], stream_factory=SilentStream)
    audio.start()
    pipeline = pipeline_for(cfg, audio, lambda: current[0])
    overlay = DemoOverlay()
    commits, sounds, signal = [], [], []
    for view, _ in rows:
        current[0] = view.sample.t_frame_available
        obs = perception(view)
        result = pipeline.step(view.sample, obs, t_now=current[0],
                               endpoint_evidence=perception.estimator.evidence)
        commits.extend(result.commits)
        sounds.extend(result.audio)
        signal.append(audio.mixer.mix(1600, current[0]))
        rendered = overlay.render(
            view.full, Roi(0, 0, 640, 480), pipeline.registry, perception.estimator.evidence, result,
            dropped=0, perception_ms=0, audio_state=audio.device_state,
            stroke_diagnostics=pipeline.geometry.diagnostics,
        )
        assert np.array_equal(view.full, view.roi)
    audio.stop()
    perception.close()
    assert len(commits) == len(sounds) == audio.events == 10
    assert [c.zone_id for c in commits[:5]] == ["snare"] * 5
    assert all(e.sample_id == pipeline.registry[c.zone_id].sample_id
               for c, e in zip(commits, sounds, strict=True))
    assert commits[-1].frame_id == commits[-2].frame_id
    assert len({c.strike_id for c in commits}) == 10
    # Mixer counts one contribution per voice per callback buffer, not unique hits.
    assert audio.mixer.stats.events_mixed >= 10
    assert np.max(np.abs(np.concatenate(signal))) > 0
    cv2.imwrite(str(tmp_path / "SYNTHETIC-demo-preview.png"), rendered)


def test_demo_launcher_logs_real_decisions_without_calibration(monkeypatch, tmp_path):
    cfg = play.play_config(demo=True)
    rows = list(pixel_sequence(cfg, [Swing(HandId.RIGHT, "snare", 0.3)], 1.0))
    perception_for(monkeypatch, rows)

    class SyntheticReplay:
        def __init__(self, *a, **kw):
            self.roi = Roi(0, 0, 640, 480)

        def __iter__(self):
            return iter(v.sample for v, _ in rows)

        def view(self, sample):
            return rows[sample.frame_id][0]

    def forbidden(*a, **kw):
        pytest.fail("offline demo test must not open camera, pose model or speaker")

    monkeypatch.setattr(play, "ReplayFrameSource", SyntheticReplay)
    monkeypatch.setattr(play, "OpenCvCamera", forbidden)
    monkeypatch.setattr(play, "BodyLandmarker", forbidden)
    monkeypatch.setattr("sounddevice.OutputStream", forbidden)
    output = tmp_path / "run"
    argv = ["--demo", "--kit", "four", "--replay", "SYNTHETIC", "--no-window", "--output", str(output)]
    assert play.main(argv) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["error"] is None
    assert report["commits_by_drum"]["snare"] == 1
    assert report["calibration"] is None
    assert report["live_physical_verification"] == "NOT_YET_VERIFIED"
    assert report["live_unique_fps"] is None
    assert report["audio"]["device_enabled"] is False
    records = [json.loads(line) for line in (output / "observations.jsonl").read_text().splitlines()]
    hits = [r for r in records if r["commits"]]
    assert len(hits) == 1
    assert hits[0]["audio_events"][0]["sample_id"] == "tr505-snare"
    assert hits[0]["decisions"]["RIGHT"]["gates"][0]["decision"] == "COMMITTED"


def test_preflight_never_opens_devices(monkeypatch):
    def forbidden(*a, **kw):
        pytest.fail("preflight must not initialize live devices")
    monkeypatch.setattr(play, "Perception", forbidden)
    monkeypatch.setattr(play, "OpenCvCamera", forbidden)
    monkeypatch.setattr(play, "AudioOutput", forbidden)
    assert play.main(["--demo", "--check"]) == 0


def test_failed_start_is_preserved_as_failure(monkeypatch, tmp_path):
    def failed_model(*a, **kw):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(play, "Perception", failed_model)
    output = tmp_path / "failed-start"
    assert play.main(["--demo", "--no-window", "--output", str(output)]) == 1
    report = json.loads((output / "report.json").read_text())
    assert report["acceptance"] == "RUNTIME_ERROR"
    assert report["error"] == "RuntimeError: model unavailable"
    assert report["audio"] is None
    assert report["calibration"] is None
    assert report["live_unique_fps"] is None


def test_full_kit_demo_has_seven_pieces_without_kick_and_loads_all_samples():
    cfg = play.play_config(demo=True, kit="full")
    assert cfg["product"]["developer_demo"]["profile_id"] == "full-kit-v1"
    ids = [z["zone_id"] for z in cfg["zones"]]
    assert sorted(ids) == sorted(["crash", "ride", "hihat", "snare", "tom1", "tom2", "floor_tom"])
    assert len({z["sample_id"] for z in cfg["zones"]}) == 7
    assert play.check_assets(cfg)["assets"] == "HASH_VERIFIED"
    layout = DeveloperDemoLayout(cfg)
    assert len(layout.zones) == 7 and layout.report()["profile"]["profile_id"] == "full-kit-v1"


def test_full_kit_window_loop_renders_the_stage_and_toggles_diagnostics(monkeypatch, tmp_path):
    cfg = play.play_config(demo=True, kit="full")
    rows = list(pixel_sequence(cfg, [Swing(HandId.RIGHT, "snare", 0.3)], 1.0))
    perception_for(monkeypatch, rows)

    class SyntheticReplay:
        def __init__(self, *a, **kw):
            self.roi = Roi(0, 0, 640, 480)

        def __iter__(self):
            return iter(v.sample for v, _ in rows)

        def view(self, sample):
            return rows[sample.frame_id][0]

    shown, keys = [], iter([ord("d"), ord("d")] + [-1] * 100)
    monkeypatch.setattr(play, "ReplayFrameSource", SyntheticReplay)
    monkeypatch.setattr(play.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(play.cv2, "resizeWindow", lambda *a, **k: None)
    monkeypatch.setattr(play.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(play.cv2, "imshow", lambda name, img: shown.append(img.shape))
    monkeypatch.setattr(play.cv2, "pollKey", lambda: next(keys))
    output = tmp_path / "run"
    assert play.main(["--demo", "--replay", "SYNTHETIC", "--output", str(output)]) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["error"] is None and report["commits_by_drum"]["snare"] == 1
    assert set(report["commits_by_drum"]) == {"crash", "ride", "hihat", "snare", "tom1", "tom2", "floor_tom"}
    assert report["latency_ms"]["render_ms"]["p50"] > 0
    assert (720, 960, 3) in shown and (480, 640, 3) in shown  # stage view, then diagnostics after 'd'
