"""TEST-SCRIPTS-1: the Phase 02/03 measurement scripts produce schema-valid experiment logs.

Every script is run in its ``--synthetic`` mode (no camera, no window) into a temporary
experiments directory; run.json must validate against schemas/experiment-log.schema.json,
be COMPLETED, carry the config snapshot and list its artefacts with hashes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from spacedrums.contracts import schema as contract_schema

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _run(args: list[str], tmp: Path) -> Path:
    # global options go right after the script path (sub-command scripts parse them first)
    res = subprocess.run([sys.executable, args[0], "--experiments-dir", str(tmp), *args[1:]], cwd=ROOT,
                         capture_output=True, text=True, timeout=180, check=False)
    assert res.returncode == 0, res.stdout[-2000:] + res.stderr[-2000:]
    runs = [p for p in tmp.iterdir() if p.is_dir()]
    assert len(runs) == 1
    return runs[0]


def _check_run(run_dir: Path, phase_task: str, min_artefacts: int = 1) -> dict:
    rec = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    errs = contract_schema.errors("experiment-log", rec)
    assert not errs, errs
    phase = phase_task.split(".")[0]
    assert rec["status"] == "COMPLETED" and rec["phase"] == phase and rec["task"] == phase_task
    assert (run_dir / "config.resolved.yaml").exists() and (run_dir / "stdout.log").exists()
    assert len(rec["artefacts"]) >= min_artefacts
    for a in rec["artefacts"]:
        assert (run_dir / a["path"]).exists() and len(a["sha256"]) == 64
    assert rec["environment"]["lock_hash"].startswith("sha256:")
    assert rec["hardware"]["cpu_model"]
    return rec


def test_measure_fps_synthetic(tmp_path):
    run_dir = _run([str(SCRIPTS / "measure_fps.py"), "--synthetic", "--duration", "1.5",
                    "--modes", "64x48@100"], tmp_path)
    rec = _check_run(run_dir, "02.4")
    cell = next(iter(rec["metrics"]["cells"].values()))
    assert cell["fps_delivered"] is not None and cell["n_frames"] > 50
    assert cell["duplicates"] > 0  # the synthetic camera pads every 10th frame; refused, counted
    cells = json.loads((run_dir / "fps_cells.json").read_text(encoding="utf-8"))["cells"]
    assert cells[0]["interval_stats"]["nominal_s"] == pytest.approx(0.01)


def test_measure_capture_latency_synthetic(tmp_path):
    run_dir = _run([str(SCRIPTS / "measure_capture_latency.py"), "--synthetic", "--trials", "3",
                    "--baseline", "0.8"], tmp_path)
    rec = _check_run(run_dir, "02.8")
    m = rec["metrics"]
    assert m["detected"] == 3
    # the synthetic camera injects 20 ms; the half-period-corrected median must land near it
    assert 0.012 < m["corrected_half_period_median_s"] < 0.032
    assert m["capture_latency_raw_median_s"] >= 0.02


def test_enumerate_cameras_synthetic(tmp_path):
    run_dir = _run([str(SCRIPTS / "enumerate_cameras.py"), "--synthetic"], tmp_path)
    _check_run(run_dir, "02.1")


def test_exposure_inspect_synthetic(tmp_path):
    run_dir = _run([str(SCRIPTS / "exposure_blur_check.py"), "--synthetic", "inspect"], tmp_path)
    _check_run(run_dir, "02.5")


def test_show_guide_synthetic_headless(tmp_path):
    shot = tmp_path / "guide.png"
    res = subprocess.run([sys.executable, str(SCRIPTS / "show_guide.py"), "--synthetic", "--no-window",
                          "--duration", "0.8", "--screenshot", str(shot)], cwd=ROOT,
                         capture_output=True, text=True, timeout=120, check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    assert shot.exists() and shot.stat().st_size > 1000


def test_hands_landmark_check_synthetic(tmp_path):
    """Phase 03, Tasks 03.1/03.2: stub backend, in-memory frames (10 static + 20 SYNTHETIC crossing)."""
    run_dir = _run([str(SCRIPTS / "hands_landmark_check.py"), "--synthetic"], tmp_path)
    rec = _check_run(run_dir, "03.1", min_artefacts=4)
    m = rec["metrics"]["captures"]["synthetic"]
    assert rec["metrics"]["synthetic"] is True and "SYNTHETIC" in rec["description"]
    assert m["n_frames"] == 30 and m["frames_right_present"] == 30 and m["frames_both_present"] == 25
    assert m["unknown_labels"] == 1 and m["schema_valid_all"] is True and m["visibility_available"] is False
    ident = m["identity"]
    assert ident["mode"] == "TEMPORAL"
    # crossing scenario: labels flip on 3 frames x 2 hands -> continuity overrides, identities never jump;
    # at the crossing frame itself the correct labels win over the nearest previous wrist (2 events)
    assert ident["label_overrides"] == 6 and ident["identity_jumps"] == 0 and ident["ambiguous_frames"] == 0
    assert ident["continuity_overrides"] == 2
    assert m["label_collisions"] == 6  # TEMPORAL mode reports label overrides under the same key
    lines = (run_dir / "hand_observations.synthetic.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 60
    for line in lines:
        assert not contract_schema.errors("hand-observation", json.loads(line))
    events = [json.loads(e) for e in
              (run_dir / "identity_events.synthetic.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = [e["kind"] for e in events]
    assert kinds.count("LABEL_OVERRIDE") == 6 and kinds.count("CONTINUITY_OVERRIDE") == 2 and len(events) == 8
    assert any(a["kind"] == "figure" for a in rec["artefacts"])


def test_hands_landmark_check_synthetic_raw_mode(tmp_path):
    """RAW identity mode (Task 03.1 baseline): flipped labels swap the emitted identities."""
    run_dir = _run([str(SCRIPTS / "hands_landmark_check.py"), "--synthetic", "--identity-mode", "RAW"],
                   tmp_path)
    rec = _check_run(run_dir, "03.1", min_artefacts=4)
    m = rec["metrics"]["captures"]["synthetic"]
    assert m["identity"]["mode"] == "RAW" and m["identity"]["label_overrides"] == 0
    assert m["label_collisions"] == 1  # the frame-7 same-label collision of the static scenario
    rows = json.loads((run_dir / "per_frame.synthetic.json").read_text(encoding="utf-8"))["rows"]
    # in the crossing frames with flipped labels the RAW mode follows the label: RIGHT jumps sides
    obs = [json.loads(line) for line in
           (run_dir / "hand_observations.synthetic.jsonl").read_text(encoding="utf-8").splitlines()]
    right_x = {o["frame_id"]: o["landmarks"][0][0] for o in obs if o["hand_id"] == "RIGHT" and o["present"]}
    assert abs(right_x[15] - right_x[14]) > 0.2 and len(rows) == 30


def test_benchmark_tip_methods_synthetic(tmp_path):
    """Phase 03 Task 03.10 benchmark self-test: stub hands, drawn stick; all three methods + trackers."""
    run_dir = _run([str(SCRIPTS / "benchmark_tip_methods.py"), "--synthetic", "--overlay-every", "6"],
                   tmp_path)
    rec = _check_run(run_dir, "03.10", min_artefacts=5)
    cap = rec["metrics"]["captures"]["synthetic"]
    assert set(cap["methods"]) == {"GEOM", "AXIS_REFINED", "MARKER"}
    assert cap["methods"]["GEOM"]["present_rate"] == 1.0
    assert cap["methods"]["GEOM"]["error_vs_reference"]["status"] == "PENDING"  # no reference: never invented
    assert "FALLBACK" in cap["methods"]["MARKER"]["label"]
    for meth in cap["trackers"].values():
        for hand in meth.values():
            assert hand["schema_valid_all"] and hand["one_state_per_frame"]
    assert cap["trackers"]["GEOM"]["RIGHT"]["status_histogram"].get("VALID", 0) > 0
    assert any(a["kind"] == "figure" for a in rec["artefacts"])


def test_benchmark_tip_methods_synthetic_reference_path(tmp_path):
    """The reference path runs only on an explicitly allowed SYNTHETIC annotation file (labelled)."""
    ann_dir = tmp_path / "ann"
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "annotate_tip.py"), "--synthetic",
                          "--synthetic-dir", str(ann_dir)], cwd=ROOT, capture_output=True, text=True,
                         timeout=180, check=False)
    assert res.returncode == 0, res.stdout[-2000:] + res.stderr[-2000:]
    lines = [json.loads(line)
             for line in (ann_dir / "tips.SYNTHETIC.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines and all(a["synthetic"] is True for a in lines)
    # point the benchmark at it via the annotations root: refused without the flag
    import os

    env = dict(os.environ)
    dev_ann = ROOT / "data" / "dev-annotations" / "synthetic"
    dev_ann.mkdir(parents=True, exist_ok=True)
    target = dev_ann / "tips.SYNTHETIC.jsonl"
    target.write_text((ann_dir / "tips.SYNTHETIC.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    try:
        run_dir = _run([str(SCRIPTS / "benchmark_tip_methods.py"), "--synthetic", "--overlay-every", "0"],
                       tmp_path / "a")
        rec = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        geom = rec["metrics"]["captures"]["synthetic"]["methods"]["GEOM"]
        assert geom["error_vs_reference"]["status"] == "PENDING"
        run_dir2 = _run([str(SCRIPTS / "benchmark_tip_methods.py"), "--synthetic", "--overlay-every", "0",
                         "--allow-synthetic-reference"], tmp_path / "b")
        rec2 = json.loads((run_dir2 / "run.json").read_text(encoding="utf-8"))
        e = rec2["metrics"]["captures"]["synthetic"]["methods"]["GEOM"]["error_vs_reference"]
        assert e["status"] == "MEASURED" and "SYNTHETIC" in e["reference_kind"]
        assert 1.0 < e["error_px"]["p50"] < 4.0  # the fake click is offset by (2, -1) px
    finally:
        target.unlink(missing_ok=True)
        for d in (dev_ann, dev_ann.parent):
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
    assert env is not None


def test_measure_stage_latency_synthetic(tmp_path):
    run_dir = _run([str(SCRIPTS / "measure_stage_latency.py"), "--synthetic"], tmp_path)
    rec = _check_run(run_dir, "03.14")
    m = rec["metrics"]
    assert m["synthetic"] is True and m["frames_measured"] == 15
    assert set(m["stages"]) >= {"hands", "stick_GEOM", "stick_AXIS_REFINED", "stick_MARKER", "tracking"}
    assert m["sum_of_stage_p50_s"] > 0 and m["frame_period_s_arithmetic"] > 0
