import subprocess
import sys

import pytest
from _p10 import bootstrap_participants, select_candidate


def test_simpler_arm_can_win_and_missing_or_infeasible_metrics_cannot():
    baseline = dict(
        settings={"arm": "B"},
        median_lead_s=0.02,
        fp_per_min=0.1,
        fn_rate=0.2,
        timing_mae_s=0.01,
        latency_p95_ms=1.0,
    )
    temporal = {**baseline, "settings": {"arm": "C-GRU"}, "median_lead_s": 0.06, "fp_per_min": 9.0}
    budgets = dict(fp_budget=0.5, fn_ceiling=0.3, timing_bound_s=0.02, latency_bound_ms=2)
    assert select_candidate([temporal, baseline], **budgets)["selected"] == baseline
    assert select_candidate([temporal], **budgets)["selected"] is None
    assert select_candidate([{**baseline, "timing_mae_s": None}], **budgets)["selected"] is None
    with pytest.raises(ValueError):
        select_candidate([], **{**budgets, "fp_budget": float("nan")})


def test_bootstrap_uses_participants_and_is_seeded():
    values = {"SYNTHETIC-A": 0.01, "SYNTHETIC-B": 0.03}
    assert bootstrap_participants(values) == bootstrap_participants(values)
    assert bootstrap_participants(values)["n"] == 2
    assert bootstrap_participants({"SYNTHETIC-A": 1})["ci95"] is None


def test_test_participant_cli_refuses_before_opening_files(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/eval_temporal.py",
            "--partition",
            "test",
            "--model-dir",
            str(tmp_path / "absent"),
            "--output",
            str(tmp_path / "output"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "PENDING" in result.stderr
    assert not (tmp_path / "output").exists()
