"""Phase 17 scripts: the re-acquisition sweep's declared decision rule (``decide``), unit level.

The sweep itself runs in ``scripts/reacquisition_experiment.py`` (evidence in the gate record); these
tests pin the rule declared in its docstring on constructed summaries.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def sweep():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "reacquisition_experiment", ROOT / "scripts" / "reacquisition_experiment.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def point(objective: int, fabricated: int, *, posthoc: int | None = None, violations: int = 0) -> dict:
    return {
        "objective_fp_plus_fn": objective,
        "fabricated": fabricated,
        "posthoc_fabricated": fabricated if posthoc is None else posthoc,
        "violations": {"I3": violations},
        "crashes": 0,
        "posthoc_violations": {},
        "posthoc_crashes": 0,
    }


def p07(summary: dict, matched_a: dict | None = None) -> dict:
    matched_a = matched_a or {}
    return {
        "points": {
            k: {
                "arms": {
                    "A": {"matched": matched_a.get(k, 32), "fp": 0, "fn": 32 - matched_a.get(k, 32)},
                    "B": {"matched": 4, "fp": 0, "fn": 28},
                },
                "violations": {},
                "crash": None,
            }
            for k in summary
        }
    }


def test_current_kept_when_the_gain_is_below_the_margin(sweep):
    summary = {"g2|age0.50": point(571, 0), "g3|age0.50": point(585, 0)}  # 2.4 % < 5 %
    decision = sweep.decide(summary, p07(summary), {})
    assert decision["best"] == "g2|age0.50"
    assert decision["chosen"] == "g3|age0.50" and not decision["changed"]


def test_margin_reached_changes_only_if_p07_is_not_worse(sweep):
    summary = {"g2|age0.50": point(500, 0), "g3|age0.50": point(585, 0)}
    assert sweep.decide(summary, p07(summary), {})["chosen"] == "g2|age0.50"
    worse = p07(summary, matched_a={"g2|age0.50": 31})
    decision = sweep.decide(summary, worse, {})
    assert decision["chosen"] == "g3|age0.50" and not decision["p07_not_worse"]


def test_fewest_fabricated_decides_before_errors(sweep):
    summary = {"g3|age0.50": point(585, 4), "g6|age0.50": point(593, 3)}
    decision = sweep.decide(summary, p07(summary), {})
    assert decision["eligible"] == ["g6|age0.50"]
    assert decision["chosen"] == "g6|age0.50" and decision["reason"] == "current not eligible"


def test_posthoc_variant_uses_the_posthoc_fakeout_count(sweep):
    summary = {"g3|age0.50": point(585, 4, posthoc=9), "g6|age0.50": point(593, 3, posthoc=9)}
    assert sweep.decide(summary, p07(summary), {}, posthoc=True)["chosen"] == "g3|age0.50"


def test_points_with_violations_are_not_considered(sweep):
    summary = {"g2|age0.50": point(100, 0, violations=1), "g3|age0.50": point(585, 0)}
    decision = sweep.decide(summary, p07(summary), {})
    assert decision["considered"] == ["g3|age0.50"] and decision["chosen"] == "g3|age0.50"
