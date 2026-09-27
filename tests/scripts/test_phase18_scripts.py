"""Phase 18 scripts: lock template, runner refusals, report determinism, regeneration (TEST-P18-SCRIPTS).

The runner refusals are what makes the confirmatory run "once, after the pre-registration": each is
checked before any data is read. Report tests use constructed SYNTHETIC results.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from spacedrums.eval.report import evaluate_session
from spacedrums.live_eval import hypotheses as hyp
from spacedrums.live_eval import offline
from spacedrums.live_eval.prereg import lock_errors
from spacedrums.live_eval.stats import bootstrap_paired

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
EXAMPLE_LOCK = ROOT / "schemas/examples/confirmatory-lock.valid.example.json"


@pytest.fixture(scope="module")
def scripts_on_path():
    sys.path.insert(0, str(SCRIPTS))
    yield
    sys.path.remove(str(SCRIPTS))


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=300)


def test_lock_templates_list_every_field_and_cannot_be_archived(scripts_on_path):
    module = importlib.import_module("confirmatory_lock")
    for kind in ("offline", "live"):
        template = module.template(kind)
        assert template["lock_kind"] == kind and template["evidence"] == "PARTICIPANT"
        assert lock_errors(template), "a PENDING template must never validate"


def test_runner_refuses_before_reading_data(tmp_path):
    lock = json.loads(EXAMPLE_LOCK.read_text(encoding="utf-8"))
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    missing = _run("scripts/run_offline_confirmatory.py", "--lock", str(path))
    assert missing.returncode == 2 and "--rehearsal is required" in missing.stderr
    unarchived = _run(
        "scripts/run_offline_confirmatory.py", "--rehearsal", "--lock", str(path), "--output", str(tmp_path)
    )
    assert unarchived.returncode == 2 and "refused" in unarchived.stdout
    assert not any(p.name.endswith("offline-rehearsal") for p in tmp_path.iterdir())
    lock["evidence"] = "PARTICIPANT"
    path.write_text(json.dumps(lock), encoding="utf-8")
    dirty = _run("scripts/run_offline_confirmatory.py", "--lock", str(path))
    assert dirty.returncode == 2 and "--require-clean" in dirty.stderr


def _session(arm_shift: float, participant: str, session: str):
    labels = [
        {
            "session_id": session,
            "hand_id": "RIGHT",
            "label_id": f"{session}-g{i}",
            "label_class": "POSITIVE",
            "t_impact_est": 10.0 * (i + 1),
            "zone_id": "snare",
            "excluded": False,
            "qc_status": "PENDING_REVIEW",
            "review": {"reviewed": False},
            "segment_type": "SINGLE_HITS",
            "t_start": None,
            "t_end": None,
            "source_kind": "SYNTHETIC",
            "impact_position": [0.5, 0.6],
            "intensity_proxy_gt": 1.0 + i,
        }
        for i in range(5)
    ]
    strikes = [
        {
            "strike_id": f"{session}-s{i}",
            "session_id": session,
            "hand_id": "RIGHT",
            "zone_id": "snare",
            "t_commit": 10.0 * (i + 1) - arm_shift,
            "t_impact_pred": 10.0 * (i + 1) + 0.004,
            "t_impact_est": None,
            "impact_position": [0.5, 0.61],
            "intensity_proxy": 1.1 + i,
        }
        for i in range(5)
    ]
    segments = [
        {
            "segment_id": "u",
            "t_start": 0.0,
            "t_end": 60.0,
            "eligible": True,
            "hands": ["RIGHT"],
            "type": "SINGLE_HITS",
        }
    ]
    ev = evaluate_session(strikes, labels, segments, w_s=0.05, include_unreviewed_selftest=True)
    return {
        "participant": participant,
        "session_id": session,
        "evaluation": ev,
        "strikes": strikes,
        "labels": labels,
    }


def _fake_results() -> dict:
    shifts = {"A": -0.03, "B-CV": 0.01, "C": 0.02}
    arms, per = {}, {}
    for arm, shift in shifts.items():
        sessions = [_session(shift + 0.001 * k, f"P{k}", f"{arm}-s{k}") for k in range(1, 4)]
        block = {
            "per_participant": offline.participant_metrics(sessions),
            "pooled": offline.pooled_metrics(sessions),
        }
        per[arm] = block["per_participant"]
        controls = {
            "tti_commit_s": 0.05,
            "p_commit": 0.0,
            "n_confirm_frames": 0,
            "v_min": 0.15,
            "refractory_zone_s": 0.1,
        }
        arms[arm] = {
            "spec": {
                "arm_id": arm,
                "role": "primary",
                "replay_arm": "A" if arm == "A" else "B",
                "controls": controls,
                "rule": None,
                "operating_point": {"feasible": True},
            },
            "delay_primary_s": 0.03,
            "primary": {
                **block,
                "strata": offline.strata(sessions, speed_edges=[2.0, 4.0]),
                "trajectory": None,
            },
            "s1": block,
            "zero_delay": block,
            "curve": [
                {
                    "settings": controls,
                    "median_lead_s": block["pooled"]["lead_median_s"],
                    "fp_per_min": block["pooled"]["fp_per_min"],
                    "fn_rate": block["pooled"]["fn_rate"],
                    "frozen": True,
                }
            ],
            "validation": {"median_lead_s": 0.01, "fp_per_min": 1.0, "fn_rate": 0.2},
            "events": offline.event_summary(sessions),
        }
    lead = {a: {p: m["lead_median_s"] for p, m in per[a].items()} for a in per}
    boot = {"repeats": 500, "seed": 18}
    hypotheses = [
        hyp.h1a(lead["C"], c_feasible=True, **boot),
        hyp.h1b(lead["C"], lead["A"], c_feasible=True, **boot),
        hyp.cb(lead["C"], lead["B-CV"], delta_lead=0.005, c_feasible=True, b_feasible=True, **boot),
    ]
    return {
        "label": "SYNTHETIC REHEARSAL (test)",
        "lock": {"sha256": "sha256:" + "0" * 64},
        "run_id": "test",
        "prereg": {"version": 1, "sha256": "sha256:" + "1" * 64},
        "w_primary_s": 0.05,
        "dataset": {"p_test": 3},
        "speed_tercile_edges": [2.0, 4.0],
        "budgets": {"fp_budget_per_min": 5.0},
        "c_primary": "C",
        "b_primary": "B-CV",
        "a_arm": "A",
        "arms": arms,
        "hypotheses": hypotheses,
        "sensitivity_s1": hypotheses,
        "paired": {"C - B-CV": {"lead_median_s": bootstrap_paired(lead["C"], lead["B-CV"], **boot)}},
    }


def test_report_renders_every_table_and_figure_deterministically(scripts_on_path, tmp_path):
    report = importlib.import_module("_p18_report")
    results = _fake_results()
    first = report.render(results, tmp_path / "a")
    second = report.render(results, tmp_path / "b")
    assert len(first["tables"]) == 9 and len(first["figures"]) == 6
    assert first["tables"] == second["tables"] and first["figure_data"] == second["figure_data"]
    t3 = (tmp_path / "a" / "T3-hypotheses.md").read_text(encoding="utf-8")
    assert "SYNTHETIC REHEARSAL (test)" in t3 and "**SUPPORTED**" in t3 and "P ≤ 3" in t3
    assert (tmp_path / "a" / "F1-lead-vs-fp.png").stat().st_size > 1000


def test_regeneration_comparison_tolerates_only_float_noise(scripts_on_path):
    regen = importlib.import_module("regenerate_phase18")
    a = {"arms": {"C": {"x": 0.1, "y": [1, 2]}}, "run_id": "one"}
    assert regen.compare(a, {"arms": {"C": {"x": 0.1 + 1e-12, "y": [1, 2]}}, "run_id": "two"}) == []
    assert regen.compare(a, {"arms": {"C": {"x": 0.2, "y": [1, 2]}}, "run_id": "one"})
    assert regen.compare(a, {"arms": {"C": {"x": 0.1, "y": [1]}}, "run_id": "one"})
    stored = {**a, "lock": {"sha256": "x"}, "self_checks": {}}  # run-specific keys only on the stored side
    assert regen.compare(stored, {"arms": {"C": {"x": 0.1, "y": [1, 2]}}}) == []
    assert regen.compare({"arms": {"C": {"lock": 1}}}, {"arms": {"C": {}}})  # nested keys still count


def test_exploratory_click_diagnostic_survives_band_limiting_where_the_declared_ncc_fails(scripts_on_path):
    """SYNTHETIC: a band-limited click path defeats template correlation but not the envelope onset."""
    import numpy as np
    from scipy.signal import butter, lfilter

    from spacedrums.live_eval import acoustic

    pilot = importlib.import_module("external_methods_pilot")
    stim, pairs = pilot.click_stimulus(12)
    b, a = butter(4, [800 / 24000, 4000 / 24000], btype="band")
    delay = int(0.0931 * pilot.RATE)
    rec = np.concatenate([np.zeros(delay), lfilter(b, a, stim)])[: len(stim)] * 0.5
    rec = rec + np.random.default_rng(3).normal(0, 0.002, len(stim))
    assert acoustic.click_pair_validation(rec, pilot.RATE, pilot.click_signature(), pairs)["n_detected"] == 0
    d = pilot.exploratory_click_diagnostic(rec, stim, pairs)
    assert d["alignment_valid"]
    assert d["ncc_max_near_expected"]["max"] < 0.3
    assert d["delay_estimate_s"] == pytest.approx(0.0931, abs=0.001)
    assert d["envelope_onset_pairs"]["n"] == 12 and d["envelope_onset_pairs"]["e95_s"] < 1e-3
    noise = np.random.default_rng(4).normal(0, 0.05, len(stim))  # no click train at all
    assert pilot.exploratory_click_diagnostic(noise, stim, pairs)["alignment_valid"] is False


def test_verifier_chains_steps_through_evidence_lines(scripts_on_path):
    verify = importlib.import_module("verify_phase18")
    assert verify.evidence_dir(b"...\nEVIDENCE: C:/x/run-1\nmore\nEVIDENCE: C:/x/run-2\n") == "C:/x/run-2"
    assert verify.evidence_dir(b"no evidence") is None
