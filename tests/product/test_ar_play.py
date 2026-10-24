"""SYNTHETIC play-loop checks of --view ar. No webcam or speaker is opened; GPU tests skip without OpenGL."""

import json

import pytest
from test_developer_demo import perception_for, pixel_sequence

from spacedrums.app import play
from spacedrums.app.ar_controls import SessionControls, output_scale_for, v_min_for
from spacedrums.app.synthetic import Swing
from spacedrums.calib.developer_demo import DeveloperDemoLayout
from spacedrums.capture import Roi
from spacedrums.contracts import HandId
from spacedrums.geometry.four_pad import SAMPLES
from spacedrums.ui.ar import gl as ar_gl


def gl_available():
    try:
        ar_gl.GLRenderer(16, 16).release()
    except ar_gl.GLUnavailable:
        return False
    return True


def run_loop(monkeypatch, tmp_path, argv, *, keys=(), swings=None, cfg=None):
    cfg = cfg or play.play_config(demo=True, kit="reference")
    rows = list(pixel_sequence(cfg, swings or [Swing(HandId.RIGHT, "snare", 0.3)], 1.0))
    perception_for(monkeypatch, rows)

    class SyntheticReplay:
        def __init__(self, *a, **kw):
            self.roi = Roi(0, 0, 640, 480)

        def __iter__(self):
            return iter(v.sample for v, _ in rows)

        def view(self, sample):
            return rows[sample.frame_id][0]

    shown, callbacks = [], []
    keys = iter(list(keys) + [-1] * 200)
    monkeypatch.setattr(play, "ReplayFrameSource", SyntheticReplay)
    for name in ("namedWindow", "resizeWindow", "destroyAllWindows"):
        monkeypatch.setattr(play.cv2, name, lambda *a, **k: None)
    monkeypatch.setattr(play.cv2, "setMouseCallback", lambda name, fn: callbacks.append(fn))
    monkeypatch.setattr(play.cv2, "imshow", lambda name, img: shown.append(img.shape))
    monkeypatch.setattr(play.cv2, "pollKey", lambda: next(keys))
    output = tmp_path / "run"
    assert play.main([*argv, "--replay", "SYNTHETIC", "--output", str(output)]) == 0
    return json.loads((output / "report.json").read_text()), shown, callbacks


def test_reference_kit_config_uses_four_pad_ids_and_samples():
    cfg = play.play_config(demo=True, kit="reference")
    assert [z["zone_id"] for z in cfg["zones"]] == ["crash_ride", "tom1", "snare", "hihat"]
    assert all(z["sample_id"] == SAMPLES[z["zone_id"]] for z in cfg["zones"])
    assert cfg["audio"]["sample_bank"]["manifest"].endswith("recorded-manifest.json")
    assert DeveloperDemoLayout(cfg).report()["profile"]["profile_id"] == "reference-kit-v1"
    # every threshold is the classic demo's: only zones differ
    classic = play.play_config(demo=True, kit="four")
    for key in ("geometry", "commit", "tracking", "stick", "audio"):
        assert cfg[key] == classic[key]
    assert cfg["product"]["stroke"] == classic["product"]["stroke"]


def test_slider_defaults_leave_hit_detection_and_loudness_unchanged():
    assert v_min_for(0.7, 0.15) == 0.15 and output_scale_for(0.8) == 1.0
    assert v_min_for(1.0, 0.15) < 0.15 < v_min_for(0.4, 0.15) <= 0.60
    assert output_scale_for(0.0) == 0.0 and output_scale_for(1.0) == pytest.approx(1.25)
    c = SessionControls(0.15)
    assert c.report()["v_min"] == 0.15 and c.report()["output_scale"] == 1.0


def test_the_layout_preview_stays_a_classic_view_tool():
    with pytest.raises(SystemExit):
        play.main(["--view", "ar", "--demo", "--kit", "full", "--layout-preview"])


def test_ar_view_without_opengl_falls_back_to_the_classic_view(monkeypatch, tmp_path):
    def no_gl(*a, **k):
        raise ar_gl.GLUnavailable("SYNTHETIC: no context")

    monkeypatch.setattr("spacedrums.ui.ar.view.GLRenderer", no_gl)
    report, shown, _ = run_loop(monkeypatch, tmp_path, ["--demo", "--view", "ar"])
    assert report["error"] is None and report["commits_by_drum"]["snare"] == 1
    assert report["view"] == "ar" and "no context" in report["ar_view"]["fallback"]
    assert set(shown) == {(480, 640, 3)}  # the developer overlay of the reference kit


@pytest.mark.skipif(not gl_available(), reason="no OpenGL 3.3 context")
def test_ar_view_plays_the_reference_kit_and_logs_its_costs(monkeypatch, tmp_path):
    report, shown, callbacks = run_loop(monkeypatch, tmp_path, ["--demo", "--view", "ar"])
    assert report["error"] is None
    assert report["commits_by_drum"] == {"crash_ride": 0, "tom1": 0, "snare": 1, "hihat": 0}
    assert set(shown) == {(720, 960, 3)}  # replay has no native frame: the tracking frame at 1.5x
    assert callbacks, "the mouse drives the control bar"
    ar = report["ar_view"]
    assert ar["renderer"]["renderer"] and ar["fallback"] is None
    assert ar["controls"]["v_min"] == report["config"]["geometry"]["v_min"]
    assert ar["controls"]["output_scale"] == 1.0
    for key in ("render_ms", "ar_upload_ms", "ar_draw_ms", "ar_readback_ms", "ar_hud_ms", "imshow_ms"):
        assert report["latency_ms"][key]["p50"] >= 0, key


@pytest.mark.skipif(not gl_available(), reason="no OpenGL 3.3 context")
def test_control_keys_reach_the_session_and_the_report(monkeypatch, tmp_path):
    keys = [ord("["), ord("["), ord("-"), ord("v"), ord("s")]
    report, shown, _ = run_loop(monkeypatch, tmp_path, ["--demo", "--view", "ar"], keys=keys)
    c = report["ar_view"]["controls"]
    assert c["sensitivity"] == pytest.approx(0.6) and c["volume"] == pytest.approx(0.75)
    assert c["v_min"] == pytest.approx(v_min_for(0.6, report["config"]["geometry"]["v_min"]))
    assert report["audio"]["device"]["output_scale"] == pytest.approx(0.75 / 0.8)
    assert [ch["control"] for ch in c["changes"]] == ["sensitivity", "sensitivity", "volume", "viewpoint"]
    assert report["error"] is None


@pytest.mark.skipif(not gl_available(), reason="no OpenGL 3.3 context")
def test_settings_can_switch_to_the_classic_view_and_back(monkeypatch, tmp_path):
    from spacedrums.ui.ar.controls import Controls

    original = Controls.toggle

    def toggle_classic_on_g(self, key):  # stand-in for clicking "Classic view" in the Settings popup
        return original(self, "classic" if key == "ghost" else key)

    monkeypatch.setattr(Controls, "toggle", toggle_classic_on_g)
    report, shown, _ = run_loop(
        monkeypatch, tmp_path, ["--demo", "--view", "ar"], keys=[-1, -1, ord("g"), -1, -1, ord("a")]
    )
    assert (480, 640, 3) in shown and (720, 960, 3) in shown
    views = [ch["value"] for ch in report["ar_view"]["controls"]["changes"] if ch["control"] == "view"]
    assert views == ["classic", "ar"]
