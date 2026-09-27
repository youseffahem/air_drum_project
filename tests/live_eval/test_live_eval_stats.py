"""Phase 18 participant statistics and the pre-registered decision rules (TEST-P18-STATS, TEST-P18-HYP)."""

from __future__ import annotations

import pytest

from spacedrums.live_eval import hypotheses as hyp
from spacedrums.live_eval.stats import bootstrap_mean, bootstrap_paired, bootstrap_ratio, paired_differences

BOOT = {"repeats": 2000, "seed": 18}


def test_bootstrap_is_seeded_order_independent_and_counts_undefined():
    values = {"P03": 0.02, "P01": 0.01, "P02": None, "P04": 0.03, "P05": 0.05}
    a = bootstrap_mean(values, **BOOT)
    b = bootstrap_mean(dict(reversed(list(values.items()))), **BOOT)
    assert a == b
    assert a["n"] == 4 and a["undefined"] == 1 and a["participants"] == ["P01", "P03", "P04", "P05"]
    assert a["estimate"] == pytest.approx(0.0275)
    lo, hi = a["ci"]
    assert 0.01 <= lo < a["estimate"] < hi <= 0.05
    assert a["degenerate"] is False and a["note"] is None


def test_small_samples_are_flagged_and_single_participants_get_no_interval():
    three = bootstrap_mean({"P1": 1.0, "P2": 2.0, "P3": 4.0}, **BOOT)
    assert three["ci"] == [1.0, 4.0] and three["degenerate"] is True and "P <= 3" in three["note"]
    one = bootstrap_mean({"P1": 1.0}, **BOOT)
    assert one["ci"] is None and one["estimate"] == 1.0 and "fewer than two" in one["note"]
    with pytest.raises(ValueError):
        bootstrap_mean({"P1": float("nan"), "P2": 1.0})


def test_paired_differences_use_only_participants_defined_in_both():
    d = paired_differences({"P1": 3.0, "P2": 2.0, "P3": None}, {"P1": 1.0, "P2": None, "P4": 0.0})
    assert d == {"P1": 2.0}
    stat = bootstrap_paired({"P1": 3.0, "P2": 2.0}, {"P1": 1.0, "P3": 0.0}, **BOOT)
    assert stat["n"] == 1 and stat["unpaired"] == ["P2", "P3"] and stat["ci"] is None


def test_pooled_ratio_resamples_participants_and_reports_empty_denominators():
    r = bootstrap_ratio(
        {"P1": 6, "P2": 0, "P3": 3}, {"P1": 120.0, "P2": 60.0, "P3": 180.0}, scale=60.0, **BOOT
    )
    assert r["estimate"] == pytest.approx(9 * 60 / 360)
    assert r["ci"][0] <= r["estimate"] <= r["ci"][1]
    z = bootstrap_ratio({"P1": 1, "P2": 2}, {"P1": 0.0, "P2": 0.0}, **BOOT)
    assert z["estimate"] is None and z["ci"] is None and z["undefined_resamples"] == BOOT["repeats"]
    with pytest.raises(ValueError):
        bootstrap_ratio({"P1": -1}, {"P1": 1.0})


@pytest.mark.parametrize(
    ("ci", "expected"),
    [
        ((0.001, 0.02), hyp.SUPPORTED),
        ((-0.02, -0.001), hyp.NOT_SUPPORTED),
        ((-0.01, 0.01), hyp.INCONCLUSIVE),
        ((-0.01, 0.0), hyp.NOT_SUPPORTED),
        (None, hyp.INCONCLUSIVE),
    ],
)
def test_decide_greater(ci, expected):
    assert hyp.decide_greater(ci) == expected


@pytest.mark.parametrize(
    ("ci", "expected"),
    [((1.0, 2.0), hyp.SUPPORTED), ((2.5, 4.0), hyp.NOT_SUPPORTED), ((1.0, 3.0), hyp.INCONCLUSIVE)],
)
def test_decide_at_most(ci, expected):
    assert hyp.decide_at_most(ci, 2.0) == expected


@pytest.mark.parametrize(
    ("ci", "expected"),
    [
        ((-0.08, -0.03), hyp.SUPPORTED),
        ((-0.015, 0.01), hyp.NOT_SUPPORTED),
        ((-0.05, -0.01), hyp.INCONCLUSIVE),
    ],
)
def test_decide_reduction_needs_more_than_the_uncertainty(ci, expected):
    assert hyp.decide_reduction(ci, 0.02) == expected


def test_cb_is_neutral_and_two_sided():
    assert hyp.decide_cb((0.004, 0.02), 0.005) == (hyp.C_LONGER, True)
    assert hyp.decide_cb((0.001, 0.004), 0.005) == (hyp.C_LONGER, False)
    assert hyp.decide_cb((-0.03, -0.001), 0.005) == (hyp.B_LONGER, True)
    assert hyp.decide_cb((-0.004, -0.001), 0.005) == (hyp.B_LONGER, False)
    assert hyp.decide_cb((-0.004, 0.004), 0.005) == (hyp.NO_MATERIAL_DIFFERENCE, False)
    assert hyp.decide_cb((-0.02, 0.02), 0.005) == (hyp.INCONCLUSIVE, None)
    assert hyp.decide_cb((-0.004, 0.004), None) == (hyp.INCONCLUSIVE, None)


def test_hypothesis_records_carry_failure_readings_and_preconditions():
    lead_c = {"P1": 0.012, "P2": 0.020, "P3": 0.015, "P4": 0.018}
    lead_b = {"P1": 0.019, "P2": 0.028, "P3": 0.022, "P4": 0.030}
    lead_a = {"P1": -0.040, "P2": -0.035, "P3": -0.050, "P4": -0.045}
    assert hyp.h1a(lead_c, c_feasible=True, **BOOT)["decision"] == hyp.SUPPORTED
    assert hyp.h1b(lead_c, lead_a, c_feasible=True, **BOOT)["decision"] == hyp.SUPPORTED
    cb = hyp.cb(lead_c, lead_b, delta_lead=0.005, c_feasible=True, b_feasible=True, **BOOT)
    assert cb["decision"] == hyp.B_LONGER and "B suffices" in cb["reading"]
    infeasible = hyp.h1a(lead_c, c_feasible=False)
    assert infeasible["decision"] == hyp.NOT_TESTABLE and "feasible" in infeasible["reading"]
    h2 = hyp.h2(
        {"P1": 10, "P2": 14}, {"P1": 60.0, "P2": 60.0}, fp_budget_per_min=5.0, c_feasible=True, **BOOT
    )
    assert h2["decision"] == hyp.NOT_SUPPORTED and "does not transfer" in h2["reading"]
    h3 = hyp.h3({"P1": 0.010, "P2": 0.012}, delta_te_s=0.030, c_feasible=True, **BOOT)
    assert h3["decision"] == hyp.SUPPORTED
    assert hyp.h4({"P1": 0.01}, {"P1": 0.1}, method=None)["decision"] == hyp.PENDING
    live = hyp.h4(
        {"P1": -0.01, "P2": 0.0, "P3": 0.01},
        {"P1": 0.12, "P2": 0.10, "P3": 0.11},
        method={"status": "GO", "u_s": 0.004, "method": "M1"},
        **BOOT,
    )
    assert live["decision"] == hyp.SUPPORTED and live["u_s"] == 0.004


def test_delta_te_follows_the_declared_rule():
    assert hyp.delta_te(0.02, None) == 0.02
    assert hyp.delta_te(0.02, 0.015) == pytest.approx(0.03)
    assert hyp.delta_te(0.02, 0.005) == 0.02
    with pytest.raises(ValueError):
        hyp.delta_te(0.0, None)
