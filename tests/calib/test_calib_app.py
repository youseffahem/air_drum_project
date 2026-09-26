"""Integration: the wizard CLI produces a calibration, the app loads it, runs and records its hash."""

import json

import pytest
import yaml
from calib_helpers import LIVE_MODEL, PROTOTYPE, base_cfg

from spacedrums import __version__
from spacedrums.app import calibrate as wizard_app
from spacedrums.app import main as app_main
from spacedrums.calib import load_calibration
from spacedrums.contracts import Arm


@pytest.fixture(scope="module")
def cli_calibration(tmp_path_factory):
    out = tmp_path_factory.mktemp("cli")
    path = out / "user-synthetic-actor-hw-01.calib.yaml"
    code = wizard_app.main(
        [
            "--synthetic",
            "--user-tag",
            "synthetic-actor",
            "--output",
            str(path),
            "--summary-json",
            str(out / "summary.json"),
            "--seed",
            "6",
        ]
    )
    assert code == 0
    return path, json.loads((out / "summary.json").read_text(encoding="utf-8"))


def test_wizard_cli_saves_a_valid_calibration(cli_calibration):
    path, summary = cli_calibration
    calib = load_calibration(path)
    assert summary["status"] == "SAVED" and summary["calibration_hash"] == calib.hash
    assert calib.doc["app"]["version"] == __version__ and len(calib.doc["app"]["git_sha"]) == 40
    assert not path.with_name(path.name + ".partial.json").exists()


def test_app_session_records_the_calibration(cli_calibration, tmp_path):
    path, _ = cli_calibration
    summary_path = tmp_path / "run.json"
    code = app_main.main(
        [
            "--synthetic",
            "single",
            "--calibration",
            str(path),
            "--record",
            "--output-dir",
            str(tmp_path),
            "--no-window",
            "--summary-json",
            str(summary_path),
        ]
    )
    assert code == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    calib = load_calibration(path)
    assert summary["calibration"] == {
        "calibration_status": "CALIBRATED",
        "calibration_hash": calib.hash,
        "calibration_id": calib.calibration_id,
    }
    session = tmp_path / summary["session_id"]
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    assert meta["calibration"]["calibration_hash"] == calib.hash
    assert (session / "calibration.calib.yaml").read_bytes() == path.read_bytes()
    snap = yaml.safe_load((session / "config.snapshot.yaml").read_text(encoding="utf-8").split("\n", 3)[3])
    assert snap["zones"] == calib.doc["layout"]["zones"] and summary["counters"]["commit"]["A"]


def test_uncalibrated_session_says_so(tmp_path):
    summary_path = tmp_path / "run.json"
    assert app_main.main(["--synthetic", "single", "--no-window", "--summary-json", str(summary_path)]) == 0
    calib = json.loads(summary_path.read_text(encoding="utf-8"))["calibration"]
    assert calib == {"calibration_status": "UNCALIBRATED", "calibration_hash": None, "calibration_id": None}


def test_app_refuses_a_stale_calibration(cli_calibration, tmp_path, capsys):
    cfg = base_cfg()
    cfg["camera_profile"]["exposure"]["value"] = -5
    moved = tmp_path / "exposure-5.yaml"
    moved.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    code = app_main.main(
        [
            "--config",
            str(moved),
            "--synthetic",
            "single",
            "--calibration",
            str(cli_calibration[0]),
            "--no-window",
        ]
    )
    assert code == 2 and "CAMERA_PROFILE_CHANGED" in capsys.readouterr().out
    assert wizard_app.main(["--check", str(cli_calibration[0])]) == 0
    assert wizard_app.main(["--config", str(moved), "--check", str(cli_calibration[0])]) == 3


def test_existing_calibration_needs_an_explicit_recalibrate(cli_calibration):
    with pytest.raises(SystemExit, match="recalibrate"):
        wizard_app.main(["--synthetic", "--user-tag", "synthetic-actor", "--output", str(cli_calibration[0])])


def test_incomplete_wizard_writes_nothing_then_resumes(tmp_path):
    path = tmp_path / "resume.calib.yaml"
    args = ["--synthetic", "--user-tag", "synthetic-actor", "--output", str(path), "--seed", "2"]
    assert wizard_app.main([*args, "--max-frames", "700"]) == 1
    partial = path.with_name(path.name + ".partial.json")
    assert not path.exists() and partial.exists()
    assert json.loads(partial.read_text(encoding="utf-8"))["step_index"] >= 2
    assert wizard_app.main([*args, "--resume"]) == 0
    doc = load_calibration(path).doc
    assert doc["durations_s"]["resumed"] is True and not partial.exists()


def test_wizard_pipeline_is_arm_a_only_even_with_a_model_config():
    from spacedrums.config import load_config

    cfg = load_config(LIVE_MODEL).data  # anticipator.type = model: still never loaded by the wizard
    pipe = wizard_app.build_pipeline(cfg, cfg["zones"], audio=None, session_id="x", hardware_id="HW-01")
    assert pipe.arms == (Arm.A,) and pipe.model_arm is None and pipe.anticipators == {}


def test_participant_calibrations_stay_out_of_configs(tmp_path):
    with pytest.raises(SystemExit, match="data/"):
        wizard_app.main(
            [
                "--participant",
                "--user-tag",
                "P01",
                "--no-window",
                "--output",
                str(PROTOTYPE.parent / "calibration" / "P01.calib.yaml"),
            ]
        )
