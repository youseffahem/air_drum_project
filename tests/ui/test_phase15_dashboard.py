from __future__ import annotations

import json
import time
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from spacedrums.capture import Roi
from spacedrums.contracts import HandId, TimingRecord
from spacedrums.eval.matching import match_events
from spacedrums.ui.dashboard import (
    DashboardModel,
    DashboardRecord,
    DashboardWorker,
    RecordBus,
    render_dashboard,
    timing_row,
)
from spacedrums.ui.export import ExportIdentity, export_annotated_frame, export_timing_csv
from spacedrums.ui.overlay import OverlayConfig, OverlayRecords, draw_scientific_overlay
from spacedrums.ui.replay_viewer import ReplaySession, _match_ids
from spacedrums.ui.theme import DEFAULT_THEME

ROOT = Path(__file__).resolve().parents[2]
DEV_SESSION = ROOT / "data" / "dev-sessions" / "dev-p05-swing-L2-exp-5"
SYNTH_SESSION = ROOT / "data" / "raw" / "SYNTHETIC" / "synthetic-p07-labels"
SYNTH_LABELS = ROOT / "data" / "labels" / "synthetic-p07-labels" / "labels.jsonl"


def strike_timing(*, impact_est=None, impact_pred=None) -> TimingRecord:
    return TimingRecord(
        kind="STRIKE",
        frame_id=7,
        strike_id="strike-1",
        hand_id="LEFT",
        arm="B",
        t_capture=1.0,
        t_frame_available=1.01,
        t_tracking_done=1.02,
        t_features_done=None,
        t_inference_done=1.025,
        t_candidate=1.026,
        t_commit=1.03,
        t_audio_scheduled=1.031,
        t_audio_out_est=None,
        t_audio_out=None,
        t_acoustic_onset=None,
        t_impact_est=impact_est,
        t_impact_pred=impact_pred,
        t_impact_phys=None,
        hardware_id="HW-01",
        config_hash="sha256:" + "0" * 64,
        clock_id="perf_counter",
    )


def test_record_bus_is_drop_if_full_and_never_replaces_capture_drop_count():
    bus = RecordBus()
    sub = bus.subscribe("slow", maxsize=1)
    record = DashboardRecord(1, 1.0, "A", capture_drops=4)
    for _ in range(4):
        bus.publish(record)
    assert sub.stats() == {
        "name": "slow",
        "published": 1,
        "dropped": 3,
        "queued": 1,
        "capacity": 1,
    }
    assert sub.get().capture_drops == 4


def test_worker_consumes_on_separate_thread():
    bus = RecordBus()
    sub = bus.subscribe("worker", maxsize=2)
    worker = DashboardWorker(sub)
    worker.start()
    bus.publish(DashboardRecord(1, 1.0, "A", processing_s=0.002))
    deadline = time.monotonic() + 1.0
    while worker.latest_image is None and time.monotonic() < deadline:
        time.sleep(0.005)
    worker.stop()
    assert worker.latest_image is not None
    assert worker.model.frames[-1].frame_id == 1


def test_timing_labels_never_call_live_prediction_estimated():
    live = timing_row(strike_timing(impact_pred=1.08), live=True)
    assert live.impact_label == "predicted impact"
    assert live.lead_label.startswith("predicted lead")
    assert "estimated" not in live.lead_label
    replay = timing_row(strike_timing(impact_est=1.075, impact_pred=1.08), live=False)
    assert replay.impact_label == "estimated impact"
    assert replay.lead_label.startswith("L_pred (estimated")
    assert "tracking" not in replay.components and "commit" not in replay.components
    assert "capture" in replay.components and "inference" in replay.components


def test_overlay_off_is_pixel_identity_and_presets_are_distinct():
    image = np.zeros((120, 180, 3), np.uint8)
    roi = Roi(10, 10, 140, 90)
    off = draw_scientific_overlay(image, roi, config=OverlayConfig.off(), records=OverlayRecords())
    assert np.array_equal(off, image)
    assert OverlayConfig.experiment() != OverlayConfig()
    assert OverlayConfig.experiment().trajectories is False
    assert OverlayConfig().trajectories is True


def test_every_overlay_element_is_individually_toggleable():
    full = OverlayConfig()
    for item in fields(full):
        toggled = replace(full, **{item.name: not getattr(full, item.name)})
        assert getattr(toggled, item.name) is not getattr(full, item.name)
        assert all(
            getattr(toggled, other.name) == getattr(full, other.name)
            for other in fields(full)
            if other.name != item.name
        )


def test_candidate_pixels_toggle_enters_renderer_without_leaking_search_region():
    image = np.zeros((120, 180, 3), np.uint8)
    roi = Roi(10, 10, 140, 90)
    with patch(
        "spacedrums.ui.overlay.draw_debug_overlay", side_effect=lambda frame, *_args, **_kwargs: frame
    ) as draw:
        draw_scientific_overlay(
            image,
            roi,
            config=replace(OverlayConfig.off(), candidate_pixels=True),
        )
    draw.assert_called_once()
    grip_only = SimpleNamespace(region=None, grip_px=(20, 20), prior_dir_px=None, segment=None, axis=None)
    output = draw_scientific_overlay(
        image,
        roi,
        config=replace(OverlayConfig.off(), filtered_tip=True),
        analyses={HandId.LEFT: grip_only},
    )
    assert np.array_equal(output, image)


def test_dashboard_render_is_screenshot_ready():
    model = DashboardModel(live=True)
    model.update(
        DashboardRecord(
            7,
            1.0,
            "B",
            processing_s=0.004,
            timing=(strike_timing(impact_pred=1.08),),
            strike_zones=(("strike-1", "snare"),),
        )
    )
    image = render_dashboard(model)
    assert image.shape == (620, 720, 3)
    assert np.count_nonzero(image) > 1000
    assert model.strikes[-1].zone == "snare"


def test_dashboard_rolling_plots_show_hand_data_and_commit_markers():
    model = DashboardModel(live=True)
    for frame_id, tip_y in ((7, 0.25), (8, 0.40)):
        model.update(
            DashboardRecord(
                frame_id,
                float(frame_id),
                "B",
                processing_s=0.003 + frame_id * 0.0001,
                timing=(strike_timing(impact_pred=1.08),) if frame_id == 7 else (),
                hands=(
                    {
                        "hand_id": "LEFT",
                        "track": {"tip_filtered": [0.5, tip_y], "tip_velocity": [0.0, 0.2]},
                        "candidates": ({"tti": 0.04},),
                    },
                ),
            )
        )
    image = render_dashboard(model)
    plots = image[365:505, 24:696]
    assert np.any(np.all(plots == DEFAULT_THEME.left, axis=2))
    assert np.any(np.all(plots == DEFAULT_THEME.error, axis=2))


def test_ui_matcher_has_phase09_one_to_one_semantics():
    strikes = [
        {"strike_id": "s1", "session_id": "x", "hand_id": "LEFT", "t_commit": 1.01},
        {"strike_id": "s2", "session_id": "x", "hand_id": "LEFT", "t_commit": 1.03},
    ]
    labels = [
        {"label_id": "g1", "session_id": "x", "hand_id": "LEFT", "t_impact_est": 1.0},
        {"label_id": "g2", "session_id": "x", "hand_id": "LEFT", "t_impact_est": 2.0},
    ]
    phase09 = match_events(strikes, labels, w_s=0.05)
    matched, false_positive = _match_ids(strikes, labels, window_s=0.05)
    assert matched == {pair[1]["label_id"] for pair in phase09.pairs}
    assert false_positive == {row["strike_id"] for row in phase09.false_positives}


def test_replay_indexes_by_frame_id_and_renders():
    session = ReplaySession(DEV_SESSION)
    assert len(session.source) == 171
    assert not session.has_labels and not session.false_positive_ids
    frame_id = session.source.samples[2].frame_id
    assert all(
        record.frame_id == frame_id for rows in session.frame_records(frame_id).values() for record in rows
    )
    rendered = session.render(2, config=OverlayConfig.experiment())
    assert rendered.shape[2] == 3


def test_ground_truth_matched_and_unmatched_status(tmp_path: Path):
    rows = [json.loads(line) for line in SYNTH_LABELS.read_text(encoding="utf-8").splitlines()]
    event = next(row for row in rows if row.get("t_impact_est") is not None and not row.get("excluded"))
    extra = {
        **event,
        "label_id": "forced-unmatched",
        "t_impact_est": 100.01,
        "t_event": 100.01,
        "impact_position": [0.5, 0.5],
        "frames": {**event["frames"], "before_event": 0, "after_event": 1},
    }
    label_path = tmp_path / "labels.jsonl"
    label_path.write_text("\n".join(json.dumps(row) for row in [*rows, extra]) + "\n", encoding="utf-8")
    session = ReplaySession(SYNTH_SESSION, labels=label_path)
    statuses = {row["match_status"] for values in session.gt_by_frame.values() for row in values}
    assert statuses == {"MATCHED", "UNMATCHED"}
    assert np.count_nonzero(session.render(0)) > 1000


def test_export_names_include_session_arm_model_and_files_open(tmp_path: Path):
    assert ExportIdentity("session one", "C-GRU", "model:1").stem == "session-one__C-GRU__model-1"
    session = ReplaySession(DEV_SESSION)
    frame = export_annotated_frame(session, 0, tmp_path)
    timing = export_timing_csv(session, tmp_path)
    assert session.session_id in frame.name and "__A__none__" in frame.name
    assert cv2.imread(str(frame)) is not None
    assert timing.read_text(encoding="utf-8").startswith("strike_id,frame_id")
