# Phase 12 entry decision (Task 12.1)

Status: **Submitter proposal**, recorded 2026-09-26 (+03:00) before any Phase 12 extension was
implemented, trained or evaluated. The phase's compute/time budget is an owner decision and is
**PENDING (Open Question)**; the owner may replace this proposal (including by a skip) at the gate.
Submitter: Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code, acting for the project owner.

## Situation at entry

| Input the phase document expects | State on 2026-09-26 |
|---|---|
| Phase 10/11 selected (shipped) model, FP budget, `W`, folds | **None.** Phase 10 and 11 gates PENDING reviewer, proposed FAIL; ADR-0025/0026/0027/0030 PENDING; `W_PRIMARY_S` unset; no reviewed ds-v1.0 participant folds |
| Phase 10/11 reproducibility package | Development only. Clean-tree reruns passed: Phase 10 on `bd0bcf8`, Phase 11 on `91351f5` (`experiments/phase-11/20260926-0445-p11-gate-verification`) |
| Failure-case catalogue | SYNTHETIC only (`phase-10-failure-cases.md`, Phase 11 reports). The participant catalogue is PENDING |
| Compute/time budget | Open Question (owner) |

No extension can be **adopted** in this execution: the go/no-go rule (Task 12.2) needs participant
CV folds, and Task 12.8 needs held-out participants. The choice is therefore between a documented
skip and a bounded development attempt that leaves every adoption decision PENDING.

## Decision (proposed)

**Bounded development attempt of E1–E5, no adoption.** Each extension is implemented, tested for
causality, export parity and latency, and exercised once through the frozen harness on the SYNTHETIC
Phase 11 kinematic fixture (`scripts/_p11_fixture.py`). The same pre-declared rule then runs
mechanically, as a machinery check labelled *development verdict (SYNTHETIC)*, never as adoption.
Participant CV runs follow the priority order and conditions below, within an owner budget.

Why not skip: the phase says to skip when Phases 10–11 already provide the research contribution.
They do not yet: no participant lead-vs-FP comparison exists. A deferral would also leave REQ-044
(Tiny Transformer go/no-go) without its CPU feasibility evidence, which needs no participant data.
Why bounded: the phase warns against a time sink. The variant list, fixture, folds, seeds, epochs
and encoder sizes are fixed here, one development run per extension, no hyperparameter search for
any extension, and nothing is combined (combinations only after individual adoption).

## Priority order and justification

Evidence below is SYNTHETIC development evidence (fixture only). It orders the work; it proves
nothing about participants. Re-derive the order from the participant failure catalogue (Phase 10
Task 10.12) before any participant CV run; a different ordering there supersedes this one.

| Priority | Extension | Phase heuristic it matches | Synthetic signal (source) |
|---|---|---|---|
| 1 | **E4 uncertainty** → geometry-grounded crossing probability as a commit gate | "FPs dominate → E4 first" | Ungated C-MT at τ 0.05 s: 58.7 (GRU) / 80.9 (TCN) FP/min with FN 0.55/0.36; the development budget (30 FP/min, FN 0.6) was feasible in only 2/12 GRU and 7/12 TCN cells (`phase-11-gating.md`). Lowest trained points were ~5–25 FP/min, which is why that budget had to be so loose |
| 2 | **E5 better decoding** (residual over Baseline B extrapolation; bounded acceleration) | "reversal errors dominate → E2/E5" | Straight-line Baseline B beat the learned trajectory near impact: impact-position median error 0.0068 vs 0.027–0.033 ROI, zone accuracy 0.97 vs 0.90–0.91 (`phase-11-per-task.md`); worst Phase 10 cases are scripted reversals (`phase-10-failure-cases.md`). Cheapest extension |
| 3 | **E2 richer representation** (velocity integration, polynomial, 2-mode mixture) | "reversal errors dominate → E2/E5" | Feints (stop-before-impact, 12–22 % of fixture strokes) are the strike/pull-up ambiguity a mixture targets; FPs at larger τ suggest committing to the wrong branch |
| 4 | **E1 longer horizon** (K 6, 8; two-rate grid) | "lead horizon-bound → E1" | *Not* horizon-bound on the fixture: median leads 7–36 ms against H = 133 ms (K = 4), limited by FP control. Kept because it is cheap and the participant horizon sweep may end at the grid edge |
| 5 | **E3 Tiny Transformer** | REQ-044 go/no-go, "only if computationally justified" | No accuracy signal favours attention over 8-frame windows. A CPU feasibility gate on a randomly initialised model runs first. Training happens only if the gate passes |

## Declared scope per extension

| Extension | Attempted (development) | Not attempted, and why |
|---|---|---|
| E1 | uniform K = 6 and K = 8 (dt = 1/30 s); two-rate grid at steps (1, 2, 3, 4, 6, 8) (H = 0.267 s, 6 outputs, contract field `t_offsets_s`) | coarser far steps beyond 2·dt; K > 8 (fixture H_max = 0.3 s) |
| E2 | (a) per-step increments integrated (velocities emitted); (b) cubic polynomial in τ/H without constant term; (c) 2-mode mixture, relaxed winner-takes-all, commit rules M1 (most probable mode) and M2 (aggregated crossing probability) | more modes (M > 2); mixture density with per-mode variance; Bezier basis (equivalent to (b) for fixed degree) |
| E3 | causal Tiny Transformer (d 16, 2 heads, 2 layers, FF 32, relative position bias, time features `dt`/`window_elapsed` in the token), feasibility-gated | attention on top of the GRU/TCN (a second architecture to validate; TT alone answers REQ-044) |
| E4 | (a) heteroscedastic per-step Gaussian (NLL on the variance, detached mean); (b) seed ensemble of the three reference models per fold (no new training); Monte-Carlo crossing probability through the unchanged Phase 04 impact test; calibration | quantile regression (no joint trajectory distribution for geometry without an extra copula assumption); MC-dropout (needs dropout-trained encoders, i.e. a different reference, and T× latency) |
| E5 | (a) residual over the causal CV extrapolation of the current velocity (Baseline B's motion model); (b) bounded-acceleration projection of decoded points, bound fitted on training targets only | (c) resampling to the live `dt`: Phase 13 (live input timing; ADR-0026) |

Fixed development settings (all extensions and the reference): fixture 5 identities × 24 s,
`P07-SPLIT-1` (1 held-out identity never opened, 4 folds); N = 8; dt_step = 1/30 s; hidden/model
width 16; 8 epochs, patience 8; Adam 1e-3; batch 64; clip 1; Huber; seeds 10, 11, 12; one torch
thread per worker; W = 0.05 s candidate; zero delay policy. The reference is the Phase 10
trajectory-only GRU/TCN trained by the unchanged `train.train_fold` (same cells as the Phase 11
`traj-only` ablation cells).

## Participant-stage plan (PENDING owner budget)

Run participant CV only after the Phase 09/10 gates, reviewed ds-v1.0 folds, the owner budgets
(FP, FN, timing, CPU) and a selected Phase 10/11 reference exist. Then, in priority order:

1. E4 and E5 (both families of the selected reference only).
2. E2, E1: E1 only if the Phase 10 participant horizon sweep selects the largest candidate K or
   shows lead bounded by H − Δ_proc; otherwise record E1 as skipped with that reason.
3. E3 only if its feasibility gate passed on the target CPU.

If the owner's budget is smaller, drop from the end of the list. Each participant run uses the
pre-declared rule in [`phase-12-prereg.md`](phase-12-prereg.md) unchanged. Cost unit:
variants × families × folds × seeds cells; the development plan above is 228 trained cells.

## What this decision does not do

No adoption, no confirmatory held-out run, no schema bump (development uncertainty layouts use
the reserved `uncertainty`/`uncertainty_kind` fields), no live integration (Phase 13), no change to
the frozen Phase 04 geometry files, Phase 05 commit policy or Phase 09 matching/metrics.
