"""SYNTHETIC checks of the offline red-tip tools. No camera, microphone or speaker is opened."""

from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_red_tips  # noqa: E402
import compare_play_sessions  # noqa: E402
import tune_red_tips  # noqa: E402

from spacedrums.app import play  # noqa: E402
from spacedrums.app.synthetic import Swing, build_sequence  # noqa: E402
from spacedrums.contracts import HandId, HandObservation, StickObservation, TipMethod  # noqa: E402
from spacedrums.contracts.perception import EndpointEvidence  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402
from spacedrums.stick.red_tip_synthetic import background, draw_stick, path_frames  # noqa: E402

L, R = HandId.LEFT, HandId.RIGHT


@pytest.mark.parametrize("detector", ["redness", "colour"])
def test_frames_reports_continuity_suggests_thresholds_and_flags_red_objects_that_never_move(tmp_path,
                                                                                             detector):
    frames = tmp_path / "frames"
    frames.mkdir()
    paths = {"a": [(450.0, 150.0 + 6 * k) for k in range(40)],
             "b": [(180.0, 300.0 - 4 * k) for k in range(40)],
             "lamp": [(600.0, 40.0)] * 40}
    for k, (view, _) in enumerate(path_frames(paths, exposure_fraction=0.3)):
        cv2.imwrite(str(frames / f"frame_{k:06d}.png"), view.full)
    fragment = tmp_path / "detector.yaml"
    fragment.write_text(f"product:\n  stick_tip:\n    detector: {detector}\n")
    out = tmp_path / "out"
    argv = ["frames", str(frames), "--output", str(out), "--contact-sheet", "4",
            "--stick-tip-config", str(fragment)]
    assert analyze_red_tips.main(argv) == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["frames"] == 40 and summary["participant_evidence"] is False
    assert all(s["measured_frames"] >= 33 for s in summary["red_tip"]["slots"].values())
    records = [json.loads(r) for r in (out / "frames.jsonl").read_text().splitlines()]
    lamp = [r["frame_id"] for r in records for s in r["slots"].values()
            if s["state"] == "OBSERVED" and math.dist(s["tip"], (600 / 640, 40 / 480)) < 0.01]
    if detector == "colour":
        # Three candidates for two slots: binding waits until the tips have moved move_px (20 px: 4-5 frames
        # here) instead of guessing which two red things are sticks.
        assert summary["red_tip"]["events"]["BIND_DEFERRED"] >= 1 and not lamp
    else:
        # The evidence tracker binds at once and lets the first motion decide: the lamp, never moved, yields
        # to a moving tip within the frames the tips need to move move_px.
        assert all(fid < 6 for fid in lamp)
    still = summary["never_moved_red_objects"]
    assert len(still) == 1
    x0, y0, x1, y1 = still[0]["ignore_region"]
    assert x0 < 600 / 640 < x1 and y0 < 40 / 480 < y1
    assert (out / "contact-sheet.jpg").exists()
    assert len((out / "frames.jsonl").read_text().splitlines()) == 40
    suggested = out / "stick-tip.suggested.yaml"
    assert summary["suggested"]["s_min"] <= 200
    cfg = play.play_config(red_tips=True, stick_tip=suggested)  # the suggestion is a valid override
    assert cfg["product"]["stick_tip"]["s_min"] == summary["suggested"]["s_min"]


def fingertip_session(directory: Path) -> int:
    """A SYNTHETIC --fingers session (report.json + observations.jsonl) as app.play writes it."""
    cfg = play.play_config(demo=True, kit="four")
    registry = ZoneRegistry.from_config(cfg["zones"])
    seq = build_sequence(registry, [Swing(R, "snare", 0.3 + 0.5 * i) for i in range(3)], duration_s=2.0)
    pipeline = analyze_red_tips.pipeline_for(cfg, "SYNTHETIC-FINGERS")
    rows = []
    for sample, obs in seq.frames:
        sample = replace(sample, roi_px=(0, 0, 640, 480))
        hands, sticks, evidence = {}, {}, {}
        fid, t = sample.frame_id, sample.t_capture
        for h, (_, st) in obs.items():
            hands[h] = HandObservation.absent(fid, t, h, "SYNTHETIC")
            sticks[h] = StickObservation(fid, t, h, True, TipMethod.AXIS_REFINED, st.tip, (0.0, -1.0), st.tip,
                                         0.9, 0.9, None)
            evidence[h] = EndpointEvidence(fid, t, h, "MEASURED", "FINGERTIP", st.tip, st.tip, 0.9, 10.0)
        result = pipeline.step(sample, {h: (hands[h], sticks[h]) for h in (L, R)},
                               t_now=sample.t_frame_available, endpoint_evidence=evidence)
        rows.append({"frame": sample.to_dict(), "hands": [hands[h].to_dict() for h in (L, R)],
                     "sticks": [sticks[h].to_dict() for h in (L, R)],
                     "endpoints": [evidence[h].to_dict() for h in (L, R)],
                     "commits": [c.to_dict() for c in result.commits]})
    directory.mkdir()
    (directory / "report.json").write_text(json.dumps({"session_id": "SYNTHETIC", "config": cfg}))
    (directory / "observations.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return sum(len(r["commits"]) for r in rows)


def test_replay_fingertips_renders_recorded_tips_and_compares_the_strikes(tmp_path):
    session = tmp_path / "fingers"
    assert fingertip_session(session) == 3
    out = tmp_path / "out"
    assert analyze_red_tips.main(["replay-fingertips", str(session), "--exposure-fraction", "0.0",
                                  "--output", str(out)]) == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["imagery"].startswith("SYNTHETIC") and summary["participant_evidence"] is False
    assert summary["commits"] == {"recorded_live": 3, "fingertip_replay": 3, "red_tip_replay": 3}
    assert summary["recorded_vs_fingertip_replay"]["matched"] == 3
    assert summary["red_vs_fingertip"]["matched"] == 3 and summary["red_vs_fingertip"]["extra"] == 0
    identity = summary["identity"]
    # Synthetic hands put LEFT on the image's left (the camera convention is the opposite), so the labels are
    # consistently mirrored; what matters is that they never change part-way through.
    assert identity["frames_with_both_measured"] > 50
    assert 0 in (identity["same_as_fingertip_labels"], identity["swapped_vs_fingertip_labels"])
    assert identity["flips"] == 0 and identity["flip_frames"] == []
    strikes = json.loads((out / "strikes.json").read_text())  # every strike of both pipelines, explained
    assert len(strikes["red_tip"]) == len(strikes["reference"]) == 3
    assert strikes["extra"] == [] and strikes["missing"] == []


def test_synthetic_self_test_runs_one_case(tmp_path):
    assert analyze_red_tips.main(["synthetic", "--case", "simultaneous", "--output", str(tmp_path)]) == 0
    case = json.loads((tmp_path / "summary.json").read_text())["cases"]["simultaneous"]
    assert case["truth"] == case["detected"] == case["matches_ideal"] == 2
    assert case["missed"] == case["false"] == case["extra_vs_ideal"] == 0


def session(directory: Path, commits, kinds, *, perception_ms=3.0) -> Path:
    directory.mkdir()
    rows = []
    for k, kind in enumerate(kinds):
        endpoints = [{"hand_id": "LEFT", "kind": kind}, {"hand_id": "RIGHT", "kind": "MEASURED"}]
        hits = [{"zone_id": z, "t_impact_target": t} for z, t in commits if int(t * 30) == k]
        rows.append({"endpoints": endpoints, "commits": hits})
    (directory / "observations.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    report = {"live_unique_fps": 29.5, "latency_ms": {"perception_ms": {"p50": perception_ms, "p95": 5.0},
                                                      "capture_to_schedule_ms": {"p50": 20.0, "p95": 30.0}}}
    (directory / "report.json").write_text(json.dumps(report))
    return directory


def test_compare_sessions_separates_missed_false_wrong_zone_and_duplicates(tmp_path, capsys):
    kinds = ["MEASURED"] * 10 + ["MISSING"] * 3 + ["MEASURED"] * 17  # one 3-frame gap on the left tip
    sticks = session(tmp_path / "sticks", [("snare", 0.10), ("snare", 0.40), ("snare", 0.42), ("tom1", 0.70)],
                     kinds)
    idle = session(tmp_path / "idle", [("hihat", 0.5)], ["MEASURED"] * 30)
    out = tmp_path / "comparison.json"
    argv = ["--run", "sticks", str(sticks), "snare=4", "--run", "sticks", str(idle), "none",
            "--output", str(out)]
    assert compare_play_sessions.main(argv) == 0
    result = json.loads(out.read_text())
    first, second = result["runs"]
    assert (first["correct"], first["missed"], first["wrong_zone"], first["duplicates"]) == (3, 1, 1, 1)
    assert first["continuity"]["LEFT"]["gap_frames"]["max"] == 3
    assert first["continuity"]["LEFT"]["measured_share_after_first"] == 27 / 30
    assert second["false"] == 1 and second["correct"] == 0
    mode = result["modes"]["sticks"]
    assert (mode["expected"], mode["correct"], mode["false"]) == (4, 3, 2)
    assert "| sticks | 2 | 4 | 3 | 1 | 2 |" in capsys.readouterr().out


# --- Tuning and labelled accuracy (revision 2026-10-16): SYNTHETIC images, not real-camera evidence ---------


def two_caps(size=(640, 480), caps=((200.3, 180.6), (430.7, 210.2)), radius=13.0):
    img = background(size, rng=np.random.default_rng(1), bgr=(150, 140, 90))
    for k, c in enumerate(caps):
        draw_stick(img, c, radius=radius, length=2.6 * radius, shaft_px=300, highlight=0.3, seed=k)
    return img


def test_tuner_saves_a_fragment_that_app_play_loads(tmp_path, capsys):
    image = tmp_path / "caps.png"
    cv2.imwrite(str(image), two_caps())
    out = tmp_path / "red-tip.tuned.yaml"
    argv = [str(image), "--no-window", "--set", "s_min=150", "--save", "--output", str(out)]
    assert tune_red_tips.main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    caps = sorted(d["cap"] for d in report["detections"]["0"])
    assert [round(c[0]) for c in caps] == [200, 431] and report["saved"] == str(out)
    cfg = play.play_config(red_tips=True, stick_tip=out)
    assert cfg["product"]["stick_tip"]["s_min"] == 150 and "camera_profile" in cfg  # nothing else overridden


def test_tuner_refuses_unknown_or_inconsistent_settings(tmp_path):
    image = tmp_path / "caps.png"
    cv2.imwrite(str(image), two_caps())
    with pytest.raises(SystemExit, match="unknown"):
        tune_red_tips.main([str(image), "--no-window", "--set", "s_minimum=150"])
    with pytest.raises(ValueError, match="weak floors"):
        tune_red_tips.main([str(image), "--no-window", "--set", "s_min_weak=200"])


def test_frames_scores_a_native_size_image_against_clicked_labels(tmp_path):
    native = [(300.45, 270.9), (646.05, 315.3)]  # cap centres in a 960 x 720 (native-window) image
    image = tmp_path / "native.png"
    cv2.imwrite(str(image), two_caps((960, 720), native, radius=19.5))
    tracking = [(x * 2 / 3, y * 2 / 3) for x, y in native]
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"labels": {"1": [tracking[1], tracking[0]], "2": [tracking[1], None]}}))
    out = tmp_path / "out"
    argv = ["frames", str(image), "--scale", str(2 / 3), "--repeat", "3", "--labels", str(labels),
            "--output", str(out)]
    assert analyze_red_tips.main(argv) == 0
    acc = json.loads((out / "summary.json").read_text())["accuracy_vs_labels"]
    assert acc["labelled_frames"] == 2 and acc["labelled_tips"] == 3 and acc["matched_tips"] == 3
    assert acc["detection_rate"] == 1.0 and acc["missed_tips"] == 0
    assert acc["measured_tips_near_no_label"] == 1  # frame 2: B was left unlabelled
    assert acc["error_px"]["max"] < 1.5
    assert acc["identity"] == {"A": "LEFT", "B": "RIGHT"} and acc["identity_disagreements"] == 0


def test_label_scoring_counts_misses_strays_and_identity_disagreements():
    labels = {1: [(100.0, 100.0), (300.0, 100.0)], 2: [(102.0, 100.0), (302.0, 100.0)],
              3: [(104.0, 100.0), (304.0, 100.0)], 4: [(106.0, 100.0), None],
              5: [(108.0, 100.0), (308.0, 100.0)]}
    measured = {1: {"LEFT": (101.0, 100.0), "RIGHT": (300.0, 103.0)},
                2: {"LEFT": (302.0, 100.0), "RIGHT": (102.0, 100.0)},  # swapped
                3: {"LEFT": (104.0, 100.0), "RIGHT": None},  # B missed
                4: {"LEFT": (106.0, 100.0), "RIGHT": (500.0, 400.0)},  # a measured tip far from any label
                5: {"LEFT": (108.0, 100.0), "RIGHT": (308.0, 100.0)}}
    acc = analyze_red_tips.score_labels(measured, labels, 12.0)
    assert acc["labelled_tips"] == 9 and acc["matched_tips"] == 8 and acc["missed_tips"] == 1
    assert acc["measured_tips_near_no_label"] == 1
    assert acc["identity"] == {"A": "LEFT", "B": "RIGHT"} and acc["identity_disagreements"] == 2
    assert acc["error_px"]["max"] == 3.0


def test_dark_paint_calibration_from_labelled_caps_writes_a_loadable_profile(tmp_path, capsys):
    frames = tmp_path / "frames"
    frames.mkdir()
    caps = [(300.0 + 3 * k, 150.0) for k in range(6)]
    labels = {}
    for k, cap in enumerate(caps):
        img = background(rng=np.random.default_rng(k), bgr=(160, 129, 66))
        draw_stick(img, cap, angle_deg=-90, shaft_px=150, hue=150, sat=105, val=40, radius=5.5, length=13.0,
                   highlight=0.3)
        cv2.imwrite(str(frames / f"frame_{k:06d}.png"), img)
        labels[str(k)] = [list(cap), None]
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"labels": labels}))
    out = tmp_path / "tuned.yaml"
    assert tune_red_tips.main([str(frames), "--calibrate-dark", str(path), "--output", str(out)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["caps"] == 6 and report["updated"]["dark_paint"] is True
    assert report["updated"]["dark_hue_min"] < -20 < report["updated"]["dark_hue_max"] + 30
    cfg = play.play_config(red_tips=True, stick_tip=out)
    assert cfg["product"]["stick_tip"]["dark_paint"] is True
