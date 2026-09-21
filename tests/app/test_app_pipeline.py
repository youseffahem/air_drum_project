"""TEST-APP-1..8: the Phase 05 decision pipeline on labelled SYNTHETIC scenarios (Tasks 05.1-05.5, 05.7-05.10
machinery). Nothing here is real-world evidence; the counts are unit-test evidence of the machinery.
"""

from __future__ import annotations

import json

import pytest
from app_helpers import Ticker, all_candidates, all_commits, run_sequence

from spacedrums.app.session_summary import commits_from_results, compare_arms, evaluate_against_truth
from spacedrums.app.synthetic import SCENARIOS, Swing, build_sequence, scenario
from spacedrums.config import canonical_json
from spacedrums.contracts import Arm, HandId, TrackStatus
from spacedrums.contracts import schema as contract_schema

FAST = 0.12  # t_down giving a crossing speed ~2.0 ROI-norm/s (synthetic), above the candidate speed gate


def _truth(seq):
    return [t.to_dict() for t in seq.truth]


# ------------------------------------------------------------------- hit types (Task 05.7 machinery)


@pytest.mark.parametrize(
    "name",
    ["single", "repeated", "rapid", "alternating_one_zone", "alternating_two_zones", "near_simultaneous"],
)
def test_hit_types_reactive_arm_matches_synthetic_truth(name, registry, make_pipeline, capsys):
    seq = scenario(name, registry, t_down=FAST)
    pipe = make_pipeline(active="A", shadow=("B",))
    results = run_sequence(pipe, seq)
    commits, cands = commits_from_results(all_commits(results), all_candidates(results))
    ev = evaluate_against_truth(commits, cands, _truth(seq))
    a = ev["arms"]["A"]
    with capsys.disabled():
        print(
            f"\nSYNTHETIC {name}: truth={ev['n_truth']} A: matched={a['n_matched']} "
            f"FP={a['false_positives']} "
            f"FN={a['false_negatives']} dup={a['duplicates']} zone_acc={a['zone_accuracy']} "
            f"L_pred_med={a['L_pred_s']['median_s']:+.4f}s | B: "
            + (
                f"matched={ev['arms']['B']['n_matched']} FP={ev['arms']['B']['false_positives']} "
                f"FN={ev['arms']['B']['false_negatives']} "
                f"L_pred_med={ev['arms']['B']['L_pred_s']['median_s']}"
                if "B" in ev["arms"]
                else "no commits"
            )
        )
    assert a["n_matched"] == ev["n_truth"] and a["false_positives"] == 0 and a["false_negatives"] == 0
    assert a["duplicates"] == 0 and a["zone_accuracy"] == 1.0
    assert a["L_pred_s"]["max_s"] < 0  # reactive: commit after the estimated impact, by construction
    assert all(
        abs(v) < 0.02 for v in [a["TE_s"]["min_s"], a["TE_s"]["max_s"]]
    )  # sub-frame t_impact_est vs analytic
    for c in all_commits(results):
        assert contract_schema.is_valid("committed-strike", c.to_dict())


def test_rule_arm_anticipates_on_synthetic_strikes(registry, make_pipeline, capsys):
    seq = scenario("repeated", registry, t_down=FAST)
    pipe = make_pipeline(active="B", shadow=("A",))
    results = run_sequence(pipe, seq)
    commits, cands = commits_from_results(all_commits(results), all_candidates(results))
    ev = evaluate_against_truth(commits, cands, _truth(seq))
    b = ev["arms"]["B"]
    cmp = compare_arms(commits, cands)
    with capsys.disabled():
        print(
            f"\nSYNTHETIC repeated (B active): B matched={b['n_matched']}/{ev['n_truth']} "
            f"FP={b['false_positives']} "
            f"FN={b['false_negatives']} L_pred vs truth median={b['L_pred_s']['median_s']:+.4f}s "
            f"TE median={b['TE_s']['median_s']:+.4f}s; "
            f"B-vs-A lead median={cmp['L_pred_B_vs_A_s']['median_s']:+.4f}s "
            f"(positive fraction {cmp['L_pred_B_positive_fraction']}); commit advance median="
            f"{cmp['commit_advance_B_vs_A_s']['median_s']:+.4f}s"
        )
    assert b["n_matched"] == ev["n_truth"] and b["false_negatives"] == 0 and b["false_positives"] == 0
    assert cmp["n_matched"] == cmp["n_A"] == cmp["n_B"] and cmp["zone_agreement"] == 1.0
    # The rule arm commits before the reactive arm on every synthetic strike (commit advance > 0). Whether its
    # commit also precedes the impact itself (L_pred > 0) is an OUTCOME of the candidate thresholds and the
    # tracker lag, not a contract: it is reported, not asserted (see docs/reports/phase-05-playability.md).
    assert cmp["commit_advance_B_vs_A_s"]["min_s"] > 0
    assert b["L_pred_s"]["n"] == ev["n_truth"] and cmp["L_pred_B_positive_fraction"] is not None
    assert all(c.shadow for c in all_commits(results) if c.arm is Arm.A)
    assert all(not c.shadow for c in all_commits(results) if c.arm is Arm.B)


# ----------------------------------------------------------------------------- shadow safety / arm switch


def test_shadow_commits_never_reach_audio(registry, make_pipeline):
    seq = scenario("repeated", registry, t_down=FAST)
    pipe = make_pipeline(active="A", shadow=("B",))
    results = run_sequence(pipe, seq)
    commits = all_commits(results)
    sounding = [c for c in commits if not c.shadow]
    shadow = [c for c in commits if c.shadow]
    events = [e for r in results for e in r.audio]
    assert shadow and sounding
    assert all(c.arm is Arm.B for c in shadow) and all(c.arm is Arm.A for c in sounding)
    assert len(events) == len(sounding) and {e.strike_id for e in events} == {c.strike_id for c in sounding}
    assert not ({e.strike_id for e in events} & {c.strike_id for c in shadow})
    timing = [t for r in results for t in r.timing if t.kind == "STRIKE"]
    assert len(timing) == len(commits)  # shadow strikes get timing records too
    assert all(t.t_audio_scheduled is None for t in timing if t.strike_id in {c.strike_id for c in shadow})
    assert all(t.t_audio_out_est is None for t in timing)  # no MEASURED output latency -> withheld


def test_runtime_arm_switch(registry, make_pipeline):
    seq = scenario("repeated", registry, t_down=FAST)
    pipe = make_pipeline(active="A", shadow=("B",))
    results = run_sequence(pipe, seq, switch_at=len(seq) // 2, switch_to="B")
    assert pipe.active_arm is Arm.B and pipe.counters()["arm_switches"][0]["from"] == "A"
    half_t = seq.frames[len(seq) // 2][0].t_frame_available
    for c in all_commits(results):
        expected_shadow = (c.arm is Arm.B) if c.t_commit < half_t else (c.arm is Arm.A)
        assert c.shadow == expected_shadow, c
    with pytest.raises(ValueError):
        pipe.set_active_arm("C-GRU", 0.0)


# ------------------------------------------------------------------- determinism / replay (Task 05.5)


def _decision_dump(results):
    commits = [c.to_dict() for c in all_commits(results)]
    cands = [c.to_dict() for c in all_candidates(results)]
    preds = [h.prediction.to_dict() for r in results for h in r.hands.values() if h.prediction is not None]
    tracks = [h.track.to_dict() for r in results for h in r.hands.values()]
    return canonical_json({"commits": commits, "candidates": cands, "predictions": preds, "tracks": tracks})


@pytest.mark.parametrize("name", ["repeated", "alternating_two_zones"])
def test_deterministic_replay_reproduces_every_decision(name, registry, make_pipeline):
    seq = scenario(name, registry, t_down=FAST, noise=0.002, seed=4)
    a = _decision_dump(run_sequence(make_pipeline(active="A", shadow=("B",), clock=Ticker()), seq))
    b = _decision_dump(run_sequence(make_pipeline(active="A", shadow=("B",), clock=Ticker()), seq))
    assert a == b
    # the same commits with a *different* wall clock (stamps differ, decisions must not)
    c = run_sequence(make_pipeline(active="A", shadow=("B",), clock=Ticker(start=900.0, step=0.01)), seq)
    strip = lambda d: {k: v for k, v in d.items() if k not in ("t_candidate",)}  # noqa: E731
    assert [c_.to_dict() for c_ in all_commits(c)] == [
        c_.to_dict()
        for c_ in all_commits(run_sequence(make_pipeline(active="A", shadow=("B",), clock=Ticker()), seq))
    ]
    assert [strip(x.to_dict()) for x in all_candidates(c)] == [
        strip(x.to_dict())
        for x in all_candidates(run_sequence(make_pipeline(active="A", shadow=("B",), clock=Ticker()), seq))
    ]


# ------------------------------------------------------------------- induced tracking loss (Task 05.8)


def test_induced_tracking_loss_zero_commits_while_not_valid(registry, make_pipeline, capsys):
    """Occlude the RIGHT hand across a strike (long gap -> INVALID) and briefly (bridged DEGRADED)."""
    L, R = HandId.LEFT, HandId.RIGHT
    swings = [
        Swing(R, "snare", 0.4, t_down=FAST),
        Swing(R, "snare", 1.2, t_down=FAST),
        Swing(R, "snare", 2.0, t_down=FAST),
        Swing(L, "hihat", 1.2, t_down=FAST),
    ]
    # first strike: 12 occluded frames around the crossing (~400 ms: beyond g_max 3 -> INVALID);
    # second strike: 2 occluded frames right before the crossing (bridged, DEGRADED -> no commit)
    occluded = {R: set(range(12, 24)) | {40, 41}}
    seq = build_sequence(registry, swings, duration_s=2.8, occluded=occluded, name="induced_loss")
    pipe = make_pipeline(active="A", shadow=("B",))
    results = run_sequence(pipe, seq)
    status = {(r.sample.frame_id, h): r.hands[h].track.status for r in results for h in (L, R)}
    commits = all_commits(results)
    during_non_valid = [c for c in commits if status[(c.frame_id, c.hand_id)] is not TrackStatus.VALID]
    trace = "".join(
        {TrackStatus.VALID: "V", TrackStatus.DEGRADED: "D", TrackStatus.INVALID: "I", TrackStatus.STALE: "S"}[
            status[(k, R)]
        ]
        for k in range(len(seq))
    )
    resets = pipe.counters()["tracker_resets"]["RIGHT"]
    with capsys.disabled():
        print(
            f"\nSYNTHETIC induced loss RIGHT: {trace}\n  resets="
            f"{[(r['frame_id'], r['reason']) for r in resets if r['frame_id'] is not None]} commits="
            f"{[(c.arm.value, c.hand_id.value, c.frame_id, status[(c.frame_id, c.hand_id)].value) for c in commits]}"  # noqa: E501
        )
    assert not during_non_valid  # hard requirement: zero commits while status != VALID
    assert "I" in trace and "D" in trace
    assert any(r["reason"] == "GAP_EXCEEDED" for r in resets)
    right_a = [c for c in commits if c.arm is Arm.A and c.hand_id is R]
    assert (
        len(right_a) == 1 and right_a[0].t_commit > seq.frames[41][0].t_capture
    )  # only the third strike commits
    assert [
        c for c in commits if c.arm is Arm.A and c.hand_id is L
    ]  # the other hand is unaffected (independence)
    # re-enable: after re-acquisition the rule arm predicts again
    assert pipe.counters()["anticipator"]["RIGHT"]["predictions"] > 0


# ----------------------------------------------------------------------------- failure cases (H)


@pytest.mark.parametrize("name", ["stop_short", "hover", "lateral", "upward", "between_zones"])
def test_non_strike_motions_produce_no_reactive_commit(name, registry, make_pipeline, capsys):
    seq = scenario(name, registry, t_down=FAST if name in ("stop_short", "lateral") else None)
    pipe = make_pipeline(active="A", shadow=("B",))
    results = run_sequence(pipe, seq)
    commits = all_commits(results)
    a = [c for c in commits if c.arm is Arm.A]
    b = [c for c in commits if c.arm is Arm.B]
    with capsys.disabled():
        print(
            f"\nSYNTHETIC non-strike {name}: A commits={len(a)} B shadow commits={len(b)} "
            f"(B commits here are false positives by definition: no crossing occurs)"
        )
    assert not seq.truth and not a
    if name in ("hover", "upward", "lateral", "between_zones"):
        assert not b


def test_slow_approach_rule_arm_declines_low_speed(registry, make_pipeline, capsys):
    """A very slow stroke (crossing speed ~0.2 ROI-norm/s, SYNTHETIC) is below v_min_predict: the rule arm
    emits no prediction; whether the reactive arm accepts it depends on geometry.v_min (candidate)."""
    seq = scenario("slow", registry)
    pipe = make_pipeline(active="B", shadow=("A",))
    results = run_sequence(pipe, seq)
    commits = all_commits(results)
    counters = pipe.counters()
    with capsys.disabled():
        print(
            f"\nSYNTHETIC slow: A commits={sum(c.arm is Arm.A for c in commits)} B commits="
            f"{sum(c.arm is Arm.B for c in commits)} declines={counters['anticipator']['RIGHT']['declines']}"
        )
    assert not [c for c in commits if c.arm is Arm.B]
    assert counters["anticipator"]["RIGHT"]["declines"].get("LOW_SPEED", 0) > 0


def test_frame_drop_guard_blocks_commit_on_that_frame(registry, make_pipeline):
    seq = scenario("single", registry, t_down=FAST)
    ref = all_commits(run_sequence(make_pipeline(active="A", shadow=()), seq))
    assert len(ref) == 1
    frame = ref[0].frame_id
    dropped = scenario("single", registry, t_down=FAST, dropped={frame: 3})
    got = all_commits(run_sequence(make_pipeline(active="A", shadow=()), dropped))
    assert got == []  # the crossing frame was guarded; the episode rule prevents a later re-commit


def test_noisy_and_jittered_sequence_stays_schema_valid_and_safe(registry, make_pipeline):
    seq = scenario("repeated", registry, t_down=FAST, noise=0.006, jitter_dt=0.004, seed=8)
    pipe = make_pipeline(active="B", shadow=("A",))
    results = run_sequence(pipe, seq)
    for r in results:
        for h in r.hands.values():
            assert contract_schema.is_valid("track-state", h.track.to_dict())
            if h.prediction is not None:
                assert contract_schema.is_valid("trajectory-prediction", h.prediction.to_dict())
            for c in h.candidates:
                assert contract_schema.is_valid("strike-candidate", c.to_dict())
        for t in r.timing:
            assert contract_schema.is_valid("timing-record", t.to_dict())
    counters = pipe.counters()
    assert counters["timing_records"]["frame"] == len(seq)
    assert json.dumps(counters)  # serialisable


# ----------------------------------------------------------------------------- construction rules


def test_pipeline_refuses_missing_geometry_block_and_unsupported_arms(cfg, registry, make_pipeline):
    data = {k: v for k, v in cfg.data.items() if k != "geometry"}
    from spacedrums.app import DecisionPipeline

    with pytest.raises(ValueError, match="geometry"):
        DecisionPipeline(
            data,
            registry=registry,
            session_id="x",
            active_arm="A",
            hardware_id="HW-01",
            config_hash=cfg.config_hash,
            audio=None,
            gain_fn=lambda z, p: 0.5,
        )
    with pytest.raises(ValueError, match="arms A and B"):
        make_pipeline(active="C-GRU")
    with pytest.raises(ValueError):
        DecisionPipeline(
            cfg.data,
            registry=registry,
            session_id="x",
            active_arm="A",
            hardware_id="HW-01",
            config_hash=cfg.config_hash,
            audio=None,
        )


def test_every_scenario_runs_without_exception(registry, make_pipeline):
    for name in SCENARIOS:
        seq = scenario(name, registry)
        run_sequence(make_pipeline(active="B", shadow=("A",)), seq)
