"""TEST-APP-11..14: health monitor, message catalogue, structured event log, crash report (Task 17.9).

SYNTHETIC inputs; no device is opened.
"""

from __future__ import annotations

import json

import pytest

from spacedrums.app.errors import CATALOGUE, EventLog, ReportedError, Severity, user_text, write_crash_report
from spacedrums.app.health import HealthMonitor, HealthSettings, Level
from spacedrums.contracts import FrameSample, ImageRef, TimestampSource

REQUIRED = {
    "camera not found": "SD-CAM-001",
    "low FPS": "SD-CAP-001",
    "poor tracking": "SD-TRK-001",
    "model fallback active": "SD-MDL-001",
    "audio device issue": "SD-AUD-001",
}


def test_catalogue_covers_every_required_message_with_guidance():
    for what, code in REQUIRED.items():
        spec = CATALOGUE[code]
        assert spec.user_message and spec.guidance, what
    assert all(code.startswith("SD-") and spec.code == code for code, spec in CATALOGUE.items())
    assert {s.severity for s in CATALOGUE.values()} <= set(Severity)
    for spec in CATALOGUE.values():  # messages never promise timing or latency
        assert "guarantee" not in spec.user_message.lower() and "latency" not in spec.user_message.lower()
    assert user_text("SD-CAM-001", "index 0").startswith("[SD-CAM-001] Camera not found")
    with pytest.raises(ValueError):
        ReportedError("SD-NOPE-000")


def test_event_log_is_structured_and_bounded(tmp_path):
    log = EventLog(
        tmp_path / "s" / "events.jsonl",
        context={"session_id": "x", "config_hash": "sha256:" + "0" * 64},
        keep=3,
    )
    for _ in range(5):
        log.emit("SD-CAP-002", detail={"drops_in_window": 4}, t_mono=1.0)
    rows = [json.loads(line) for line in (tmp_path / "s" / "events.jsonl").read_text().splitlines()]
    assert len(rows) == 5 and len(log.recent) == 3 and log.counts["SD-CAP-002"] == 5
    assert (
        rows[0]["code"] == "SD-CAP-002" and rows[0]["severity"] == "WARNING" and rows[0]["session_id"] == "x"
    )
    assert set(rows[0]) >= {"ts_wall", "t_mono", "component", "message", "detail", "config_hash"}


def test_crash_report_has_provenance(tmp_path):
    log = EventLog(None)
    log.emit("SD-AUD-001")
    try:
        raise TypeError("boom")
    except TypeError as exc:
        path = write_crash_report(
            exc, tmp_path, context={"config_hash": "sha256:1", "model": {"hash": "h"}}, events=log
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["exception"] == {"type": "TypeError", "message": "boom"}
    assert report["model"] == {"hash": "h"} and report["recent_events"][0]["code"] == "SD-AUD-001"
    second = write_crash_report(ValueError("x"), tmp_path, context={})
    assert second != path


class _Hand:
    def __init__(self, status):
        self.track = type("T", (), {"status": status})()


class _Result:
    def __init__(self, sample, statuses):
        self.sample = sample
        self.hands = {h: _Hand(s) for h, s in statuses.items()}


def _samples(n, dt=1 / 30, drops=0):
    return [
        FrameSample(
            i,
            100 + i * dt,
            100 + i * dt + 0.004,
            TimestampSource.REPLAY,
            (640, 480),
            (0, 0, 640, 480),
            ImageRef.memory(None),
            "x",
            drops,
        )
        for i in range(n)
    ]


def test_health_levels_for_low_fps_drops_tracking_model_and_audio():
    events = EventLog(None)
    monitor = HealthMonitor(HealthSettings(nominal_fps=30.0), events=events)
    ok = {"LEFT": "VALID", "RIGHT": "VALID"}
    for s in _samples(40):
        st = monitor.observe_frame(
            _Result(s, ok), None, t_now=s.t_capture, audio_state="RUNNING", audio_underruns=0
        )
    assert st.worst() is Level.OK and st.model.level is Level.OFF
    monitor = HealthMonitor(HealthSettings(nominal_fps=30.0), events=events)
    for s in _samples(40, dt=1 / 15):
        st = monitor.observe_frame(_Result(s, ok), None, t_now=s.t_capture, audio_state="RUNNING")
    assert st.camera.code == "SD-CAP-001" and st.camera.level is Level.WARN
    monitor = HealthMonitor(HealthSettings(nominal_fps=30.0), events=events)
    for s in _samples(40):
        st = monitor.observe_frame(
            _Result(s, {"LEFT": "INVALID", "RIGHT": "DEGRADED"}), None, t_now=s.t_capture, audio_state="DOWN"
        )
    assert st.tracking.code == "SD-TRK-001" and st.audio.code == "SD-AUD-001" and st.worst() is Level.FAIL
    assert any(line.startswith("[SD-TRK-001]") for line in st.messages())
    stalled = monitor.observe_no_frame(st.t + 1.0)
    assert stalled.camera.code == "SD-CAM-002" and stalled.camera.level is Level.FAIL
    assert events.counts.get("SD-CAM-002") == 1 and events.counts.get("SD-TRK-001") == 1


def test_health_reports_model_fallback():
    pipe = type(
        "P", (), {"model_label": "C-GRU", "model_error": "inference failure: TypeError: x", "active_arm": "B"}
    )()
    monitor = HealthMonitor(HealthSettings(nominal_fps=30.0))
    s = _samples(1)[0]
    st = monitor.observe_frame(_Result(s, {"LEFT": "VALID", "RIGHT": "VALID"}), pipe, t_now=s.t_capture)
    assert st.model.code == "SD-MDL-001" and st.model.detail["active_arm"] == "B"
    pipe.model_error = "load failure: ValueError: model F mismatch"
    s2 = _samples(2)[1]
    st = monitor.observe_frame(_Result(s2, {"LEFT": "VALID", "RIGHT": "VALID"}), pipe, t_now=s2.t_capture)
    assert st.model.code == "SD-MDL-002"


def test_user_messages_document_lists_every_catalogue_code():
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[2] / "docs" / "testing" / "user-messages.md").read_text(
        encoding="utf-8"
    )
    for code, spec in CATALOGUE.items():
        assert f"| {code} | {spec.severity} |" in doc, code
        assert spec.title in doc and spec.guidance in doc, code
