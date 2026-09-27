"""TEST-SYS-1..5: the application entry point end to end (Phase 17, Tasks 17.1 / 17.2 / 17.9).

``spacedrums.app.main`` with the safety monitors on: SYNTHETIC scenarios and (when present) the
developer capture replay with ``--invariants raise``; a crash writes a report with the config and
model hashes; a missing camera is a user message and exit code 3; an injected observation fault
through the test-build hook keeps every invariant. No camera or audio device is opened.
"""

from __future__ import annotations

import json

import pytest
from inv_helpers import ROOT, RULE_CONFIG

from spacedrums.app import faults as F
from spacedrums.app import main as app_main
from spacedrums.app.errors import ReportedError
from spacedrums.commit import InvariantViolation
from spacedrums.contracts import HandId


def _args(*extra):
    return app_main.build_parser().parse_args(
        ["--config", str(RULE_CONFIG), "--no-window", "--no-audio", *extra]
    )


@pytest.mark.parametrize("scenario", ["repeated", "alternating_two_zones", "near_simultaneous"])
@pytest.mark.parametrize("arm", ["A", "B"])
def test_synthetic_session_runs_with_invariants_raising(scenario, arm):
    summary = app_main.run(_args("--synthetic", scenario, "--arm", arm, "--invariants", "raise"))
    counters = summary["counters"]
    assert counters["invariants"]["violations_total"] == 0 and counters["invariants"]["mode"] == "raise"
    assert counters["invariants"]["checks"]["I2"] > 0
    assert counters["health"]["final"]["model"]["level"] == "OFF"


@pytest.mark.skipif(
    not (ROOT / "data/dev-captures/swing-L2-exp-5/frames.jsonl").exists()
    or not (ROOT / "assets/models/hand_landmarker.task").exists(),
    reason="developer capture or MediaPipe model file absent (git-ignored)",
)
def test_devcapture_replay_session_with_invariants_raising(tmp_path):
    summary = app_main.run(
        _args(
            "--source",
            "devcapture",
            "--capture",
            "swing-L2-exp-5",
            "--invariants",
            "raise",
            "--max-frames",
            "80",
            "--log-dir",
            str(tmp_path),
        )
    )
    assert summary["counters"]["invariants"]["violations_total"] == 0
    assert summary["counters"]["events"]["log"] is not None


def test_crash_writes_a_report_with_hashes(tmp_path):
    def broken(sample, obs):
        if sample.frame_id == 5:
            raise KeyError("injected application fault")
        return obs

    with pytest.raises(KeyError):
        app_main.run(_args("--synthetic", "single", "--log-dir", str(tmp_path)), observation_hook=broken)
    reports = list(tmp_path.rglob("crash-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["code"] == "SD-APP-001" and report["exception"]["type"] == "KeyError"
    assert report["config_hash"].startswith("sha256:") and "model" in report and report["frames"] == 5
    assert any("injected application fault" in line for line in report["traceback"])


@pytest.mark.skipif(
    not (ROOT / "assets/models/hand_landmarker.task").exists(),
    reason="perception is initialised before the camera; MediaPipe model file absent (git-ignored)",
)
def test_missing_camera_is_a_message_and_exit_code(monkeypatch, capsys, tmp_path):
    class NoCamera:
        def open(self, spec):
            raise RuntimeError(f"cannot open camera index {spec.index}")

        def close(self):
            pass

    monkeypatch.setattr(app_main, "camera_factory", NoCamera)
    code = app_main.main(
        [
            "--config",
            str(RULE_CONFIG),
            "--no-window",
            "--no-audio",
            "--source",
            "live",
            "--log-dir",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 3 and "[SD-CAM-001]" in out and "Traceback" not in out
    with pytest.raises(ReportedError):
        app_main.run(_args("--source", "live", "--log-dir", str(tmp_path)))


def test_observation_fault_hook_is_test_build_only(monkeypatch):
    monkeypatch.delenv(F.ENV, raising=False)
    with pytest.raises(RuntimeError, match="test builds only"):
        app_main.run(_args("--synthetic", "single"), observation_hook=lambda s, o: o)
    monkeypatch.setenv(F.ENV, "1")

    def occlude(sample, obs):
        return F.drop_hand(obs, HandId.RIGHT) if 10 <= sample.frame_id < 25 else obs

    summary = app_main.run(
        _args("--synthetic", "repeated", "--invariants", "raise"), observation_hook=occlude
    )
    assert summary["counters"]["invariants"]["violations_total"] == 0


def test_raise_mode_stops_a_session_on_a_violation(monkeypatch, tmp_path):
    """Negative control through the app: a pipeline defect (a commit with a future frame stamp) raises."""
    original = app_main.DecisionPipeline.step

    def corrupted(self, sample, observations, **kw):
        import dataclasses

        result = original(self, sample, observations, **kw)
        for hf in result.hands.values():
            hf.commits[:] = [dataclasses.replace(c, t_capture=c.t_capture + 1.0) for c in hf.commits]
        return result

    monkeypatch.setattr(app_main.DecisionPipeline, "step", corrupted)
    with pytest.raises(InvariantViolation):
        app_main.run(_args("--synthetic", "single", "--invariants", "raise", "--log-dir", str(tmp_path)))
