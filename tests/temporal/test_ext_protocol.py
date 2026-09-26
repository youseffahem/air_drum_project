"""Phase 12 script protocol: held-out and participant refusal, the E3 feasibility precondition, the
declared variant registry, and the mechanical go/no-go rule (docs/experiments/phase-12-prereg.md)."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from _p12 import CROSSING, F_CPU, PROBABILITIES, RULES, TAUS, VARIANTS
from compare_extensions import band, paired, verdict

ROOT = Path(__file__).resolve().parents[2]
PREREG = (ROOT / "docs/experiments/phase-12-prereg.md").read_text(encoding="utf-8")


def _run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=ROOT)


@pytest.mark.parametrize(
    "extra,message",
    [
        (["--partition", "test", "--extension", "ref", "--synthetic-fixture"], "PENDING"),
        (["--plan", "absent.json", "--extension", "ref"], "PENDING"),
        (["--extension", "e4", "--synthetic-fixture"], "--reference-run"),
        (["--extension", "e5", "--synthetic-fixture"], "--reference-run"),
        (["--extension", "e3", "--synthetic-fixture"], "feasibility"),
    ],
)
def test_grids_refuse_before_creating_a_run(tmp_path, extra, message):
    result = _run("scripts/eval_extension.py", *extra, "--output", str(tmp_path / "runs"))
    assert result.returncode != 0 and message in result.stderr
    assert not (tmp_path / "runs").exists()


def test_tiny_transformer_training_requires_a_feasible_gate(tmp_path):
    gate = tmp_path / "gate"
    gate.mkdir()
    (gate / "run.json").write_text(json.dumps({"status": "COMPLETED"}))
    (gate / "feasibility.json").write_text(json.dumps({"verdict": "INFEASIBLE"}))
    result = _run(
        "scripts/eval_extension.py",
        "--extension",
        "e3",
        "--synthetic-fixture",
        "--feasibility-run",
        str(gate),
        "--output",
        str(tmp_path / "runs"),
    )
    assert result.returncode != 0 and "INFEASIBLE" in result.stderr
    assert not (tmp_path / "runs").exists()


def test_code_registry_matches_the_declared_protocol():
    declared = set(re.findall(r"^\| `([a-z0-9-]+)`(?:, `([a-z0-9-]+)`)? \|", PREREG, flags=re.M))
    ids = {i for pair in declared for i in pair if i}
    assert ids == set(VARIANTS) | set(RULES)
    assert "τ_commit ∈ {0.02, 0.05, 0.10, 0.15, 0.20}" in PREREG and TAUS == (0.02, 0.05, 0.10, 0.15, 0.20)
    assert "{0, 0.3, 0.5, 0.7}" in PREREG and PROBABILITIES == (0.0, 0.3, 0.5, 0.7)
    assert "S = 32 antithetic" in PREREG and "(seed 1212)" in PREREG
    assert CROSSING == {"samples": 32, "seed": 1212, "correlation": "shared"}
    assert "**F = 3**" in PREREG and F_CPU == 3.0
    assert "2 × the reference's pooled within-fold" in PREREG


def _rows(values, *, timing=0.02, feasible=True):
    """Rows keyed by (fold, seed) with a development lead value (None = infeasible)."""
    return [
        {
            "fold": fold,
            "seed": seed,
            "harness": {
                "feasible": feasible and value is not None,
                "median_lead_s": value,
                "timing_mae_s": None if value is None else timing,
            },
        }
        for (fold, seed), value in values.items()
    ]


REFERENCE = {(f, s): 0.010 + 0.001 * s for f in (0, 1) for s in (0, 1, 2)}  # seed SD 0.001 per fold


def test_band_is_the_pooled_within_fold_seed_sd():
    sd, complete = band(_rows(REFERENCE), ("harness", "median_lead_s"))
    assert sd == pytest.approx(0.001) and complete
    sparse = dict(REFERENCE)
    sparse[(1, 1)] = sparse[(1, 2)] = None
    assert band(_rows(sparse), ("harness", "median_lead_s"))[1] is False


def test_rule_go_requires_lead_beyond_band_timing_and_cpu():
    reference = _rows(REFERENCE)
    cpu_ok = {"within_budget": True, "ratio_to_reference": 1.2}
    better = _rows({k: v + 0.003 for k, v in REFERENCE.items()})  # +3 ms > 2 x 1 ms band
    assert verdict("x", "tcn", better, reference, cpu_ok)["outcome"] == "GO"
    marginal = _rows({k: v + 0.0015 for k, v in REFERENCE.items()})  # inside the band
    assert verdict("x", "tcn", marginal, reference, cpu_ok)["outcome"] == "NO-GO"
    slow = {"within_budget": False, "ratio_to_reference": 3.5}
    assert verdict("x", "tcn", better, reference, slow)["outcome"] == "NO-GO"
    late = _rows({k: v + 0.003 for k, v in REFERENCE.items()}, timing=0.05)  # TE MAE +30 ms
    result = verdict("x", "tcn", late, reference, cpu_ok)
    assert result["outcome"] == "NO-GO" and result["checks"]["timing"] is False
    fewer = dict({k: v + 0.003 for k, v in REFERENCE.items()})
    fewer[(0, 0)] = None
    assert verdict("x", "tcn", _rows(fewer), reference, cpu_ok)["checks"]["feasibility"] is False
    assert verdict("x", "tcn", better, reference, None)["outcome"] == "NO-GO"  # CPU unmeasured


def test_rule_without_a_complete_band_is_insufficient_evidence():
    sparse = dict(REFERENCE)
    sparse[(1, 0)] = sparse[(1, 1)] = None
    result = verdict("x", "gru", _rows(REFERENCE), _rows(sparse), {"within_budget": True})
    assert result["outcome"] == "NO-GO (insufficient evidence)"


def test_ensemble_pairs_per_fold_against_the_reference_seed_mean():
    reference = _rows(REFERENCE)
    ensemble = [
        {"fold": f, "seed": "ensemble", "harness": {"feasible": True, "median_lead_s": 0.02}} for f in (0, 1)
    ]
    delta = paired(ensemble, reference, ("harness", "median_lead_s"), ensemble=True)
    assert delta["n"] == 2 and delta["mean"] == pytest.approx(0.02 - 0.011)
