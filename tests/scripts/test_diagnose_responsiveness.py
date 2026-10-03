"""``scripts/diagnose_responsiveness.py`` (live responsiveness 2026-10-02): SYNTHETIC self-test of the
probe and the analysis, the A-F frame categories, and the paced live-path camera.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from _resp import (  # noqa: E402
    PacedReplayCamera,
    category,
    entry_outcomes,
    grip_baseline,
    region_clip,
    stretches,
)
from diagnose_responsiveness import main  # noqa: E402

from spacedrums.capture import CaptureSettings, LiveFrameSource  # noqa: E402
from spacedrums.capture.backend import CameraOpenSpec  # noqa: E402


def entry(**kw):
    base = {
        "present": True,
        "stick": True,
        "status": "VALID",
        "candidates": [],
        "decisions": [],
        "commits": [],
        "limiting": None,
    }
    return {**base, **kw}


def test_synthetic_run_writes_every_report_section(tmp_path):
    assert main(["synthetic", "--output", str(tmp_path), "--scenario", "single"]) == 0
    run = tmp_path / "synthetic" / "synthetic-single"
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (run / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    for key in (
        "stages_ms",
        "processing_ms",
        "categories",
        "entries",
        "stretches_ms",
        "speed",
        "loss_diagnosis",
        "hands_model_ms_by_previous_hands_detected",
        "reacquisitions_per_min",
        "app",
    ):
        assert key in summary
    assert (
        sum(c["hand_frames"] for c in summary["categories"].values())
        == 2 * len(rows)
        == 2 * summary["frames"]
    )
    assert summary["entries"]["committed"] == summary["commits"]["total"] > 0
    assert summary["app"]["invariants"]["violations_total"] == 0


def test_categories_follow_the_documented_precedence():
    commit = {"arm": "A", "shadow": False}
    reactive = {"id": "c1", "zone": "snare", "source": "REACTIVE"}
    assert category(entry(commits=[commit], candidates=[reactive]), "A") == "F"
    assert category(entry(candidates=[reactive], status="DEGRADED"), "A") == "E"
    assert category(entry(candidates=[{**reactive, "source": "RULE"}]), "A") == "D"  # shadow arm only
    assert category(entry(present=False, stick=False, status="DEGRADED"), "A") == "A"
    assert category(entry(stick=False, status="INVALID"), "A") == "B"
    assert category(entry(status="STALE"), "A") == "C"
    assert category(entry(), "A") == "D"


def test_entry_outcomes_attribute_status_rejections_to_the_frame_limiting_factor():
    reactive = {"id": "c1", "zone": "snare", "source": "REACTIVE"}
    rows = [
        {
            "active_arm": "A",
            "hands": {
                "RIGHT": entry(
                    candidates=[reactive],
                    status="DEGRADED",
                    limiting="STICK_REJECTED_ORIENTATION",
                    decisions=[{"arm": "A", "id": "c1", "decision": "REJECT_STATUS"}],
                )
            },
        },
        {
            "active_arm": "A",
            "hands": {
                "RIGHT": entry(
                    candidates=[{**reactive, "id": "c2"}],
                    decisions=[{"arm": "A", "id": "c2", "decision": "COMMITTED"}],
                )
            },
        },
    ]
    out = entry_outcomes(rows)
    assert (out["entries"], out["committed"], out["discarded"]) == (2, 1, 1)
    assert out["reject_status_by_limiting_factor"] == {"STICK_REJECTED_ORIENTATION": 1}


def test_unresponsive_stretches_are_split_by_hand_visibility():
    def row(t, status, present):
        e = entry(status=status, present=present)
        return {"t_capture": t, "hands": {"LEFT": e, "RIGHT": e}}

    rows = [
        row(0.0, "VALID", True),
        row(0.1, "DEGRADED", True),
        row(0.2, "STALE", True),
        row(0.7, "VALID", True),
        row(0.8, "INVALID", False),
        row(1.0, "VALID", True),
    ]
    out = stretches(rows)["LEFT"]
    assert out["hand_visible"]["n"] == 1 and out["hand_visible"]["max"] == pytest.approx(700.0)
    assert out["hand_visible"]["over_0.5s"] == 1
    assert out["hand_absent"]["n"] == 1 and out["hand_absent"]["max"] == pytest.approx(300.0)


def test_paced_camera_delivers_recorded_frames_through_the_live_source_at_their_intervals():
    frames = [np.full((48, 64, 3), 40 + i, np.uint8) for i in range(4)]
    stamps = [10.0, 10.05, 10.10, 10.20]
    settings = CaptureSettings(
        camera_profile_id="paced", spec=CameraOpenSpec(width=64, height=48), roi=None, nominal_fps=30.0
    )
    with LiveFrameSource(PacedReplayCamera(frames, stamps), settings) as src:
        got = []
        while (sample := src.next_frame(timeout=1.0)) is not None:
            got.append(sample)
    assert [int(s.image_ref.array[0, 0, 0]) for s in got] == [40, 41, 42, 43]  # warm-up frames discarded
    gaps = np.diff([s.t_capture for s in got])
    assert np.all(gaps >= np.diff(stamps) - 0.004)  # never faster than recorded (scheduler jitter only adds)


def test_region_clip_reports_the_part_of_the_search_rectangle_outside_the_roi():
    from spacedrums.capture.roi import Roi
    from spacedrums.hands.grip import GripDirectionMethod, GripReference
    from spacedrums.stick.search_region import SearchRegionSettings, search_region

    roi = Roi.from_rect((0, 0, 100, 100))
    settings = SearchRegionSettings(length_factor=4.0, width_factor=1.0, back_factor=0.0, min_span_px=1.0)

    def grip(point):
        return GripReference(
            point=point, direction=(1.0, 0.0), angle_rad=0.0, hand_span=0.1,
            method=GripDirectionMethod.KNUCKLE_ROW, baseline_len=0.1, span_vec=(0.1, 0.0),
        )

    inside = search_region(grip((0.2, 0.5)), roi, settings)  # 40 px long rectangle from x 20 to 60
    half = search_region(grip((0.8, 0.5)), roi, settings)  # x 80 to 120: half of it beyond x = 100
    assert region_clip(inside) == pytest.approx(0.0)
    assert region_clip(half) == pytest.approx(0.5, abs=0.02)
    assert region_clip(None) is None


def test_grip_baseline_reads_the_frame_grip_reference():
    class Analysis:
        grip = type("G", (), {"baseline_len": 0.004})()

    assert grip_baseline(Analysis()) == pytest.approx(0.004)
    assert grip_baseline(None) is None
