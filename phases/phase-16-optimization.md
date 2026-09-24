# Phase 16 — Performance Optimization

## Status

Planned

## Codex Model for This Phase

- **Model:** GPT-6 Astra
- **Reasoning effort:** Extra High
- **Recommended profile:** Performance Engineering / Realtime Optimization
- **Why this choice:** Threading or multiprocessing, model quantisation, and native-FPS handling can alter frame order, predictions, processing delay, and offline lead-time interpretation. Astra fits the system-wide profiling and code work; Extra High is justified by incremental before/after attribution, regression tolerances, causality/parity checks, and safe rollback decisions.

> Set the model and reasoning effort in the Codex picker before running this phase.
> This section is a workload recommendation only; text in the prompt does not switch the active model.
> Record the actual model and reasoning setting used in the phase evidence.
> If the recommended model is unavailable, use the strongest available compatible model and record the actual setting used.
> The selected model is not a substitute for tests, acceptance criteria, or empirical evidence.

## Purpose

Profile the integrated live pipeline (Phase 13 + 15) on the target CPU, establish per-stage latency budgets from measurements, reduce end-to-end processing latency and frame drops through targeted optimisations (ROI-limited processing, threading/multiprocessing, model export/quantisation, allocation and copy reduction), attempt **true native 60 FPS** end-to-end if the camera delivers it (Phase 02 evidence), and verify with the Phase 09 harness that no optimisation changes the system's predictions or commits beyond a stated tolerance. Every change is reported as measured before/after.

## Why This Phase Exists

Useful lead time is bounded by `H − Δ_proc`: every millisecond of processing delay is a millisecond less of anticipation the system can deliver in practice. Also, Q23 sets 60 FPS as a target if hardware allows; the lower frame period halves frame-quantization delay and doubles the temporal resolution of the trajectory, which may change model results (Phase 19 FPS ablation). Optimisation is done only after correctness is proven (Phases 13/15) so that speed never trades silently against validity.

## Relationship to Research Contribution

- Reduces `Δ_proc` (feeds the `Δ_proc` policy in Phases 09/10/18) and thereby the achievable `L_pred` and `L_sys`.
- Enables the 60 FPS condition for Phase 19 if achievable.
- Preserves result validity via regression checks against the frozen harness.

## Inputs

- Phase 13 application, Phase 15 overlay (experiment mode), Phase 02 camera profile (60 FPS evidence), stage latency measurements (Phases 02/03/08/10/13).
- Phase 09 harness and a fixed regression session set.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-023 (native 60 FPS attempt), REQ-304.

## Expected Outputs

- Profiling report (per-stage p50/p95, allocation hot spots, thread contention).
- Latency budget table (measured baseline → target → achieved), all labelled.
- Optimised implementation with before/after tables.
- 60 FPS attempt report: native camera delivery (from Phase 02) × processing capability → achieved end-to-end FPS (MEASURED) or documented shortfall.
- Regression report: harness metrics before vs. after on the regression set within tolerance.
- Updated `Δ_proc` constants (recorded change; offline re-runs if material).

## Dependencies

- Phase 13 and Phase 15 Exit Gates.

## System Components

- Profiling scripts `scripts/profile_pipeline.py`, `scripts/fps_end_to_end.py`, `scripts/regression_check.py`
- Optimised modules across `capture`, `hands`, `stick`, `tracking`, `features`, `prediction`, `geometry`, `audio`, `ui`
- `docs/perf/`

## Architecture

Optimisation candidates (each individually measured and reversible):

1. **ROI-limited processing:** run `hands` and `stick` on the ROI crop only (already) and consider a lower-resolution detection pass with full-resolution stick refinement in the hand region (accuracy impact measured with Phase 03 benchmark subset).
2. **Threading/multiprocessing:** capture thread (exists); `hands`+`stick` in a worker process with shared memory frames; inference in a worker thread (Phase 13 option); GIL contention measured; causality preserved by design (workers consume delivered frames only).
3. **Landmark estimator settings:** model complexity/threads; measured trade-off of latency vs. landmark presence/tip error.
4. **Model export/quantisation:** ONNX graph optimisation, int8 quantisation (accuracy/lead-time regression checked), operator fusion; stateful GRU vs. windowed.
5. **Allocation/copy reduction:** preallocated buffers, avoiding per-frame array copies, vectorised feature computation.
6. **Audio buffer:** revisit `B` (Phase 04 measurement) with the optimised loop.
7. **60 FPS mode:** camera at native 60 FPS (if Phase 02 shows delivery); processing must sustain the frame period; model `dt_step` mismatch handled (Phase 13 rule: features resampled to the training rate, or a model trained at 60 FPS in Phase 19).

## Execution Instructions

- When this phase is authorized, automatically perform any outstanding post-owner-commit verification for its dependency phases on the current Git HEAD before dependent work; record the SHA, dirty state, and results. A commit alone does not satisfy a gate.
- Execute the entire phase end-to-end in the stated task order and automatically run executable gate conditions, without task-by-task or condition-by-condition prompting. Preserve all dependencies, optional-scope decisions, acceptance criteria, and evidence rules.
- Never fabricate participant evidence or substitute synthetic/developer evidence for it. Unavailable evidence and owner-only decisions remain PENDING; continue independent executable work and report blockers at the Exit Gate.
- Stop only at this phase's Exit Gate for owner/reviewer action under the [gate procedure](../docs/gates/gate-procedure.md). Commit, tag, and push remain owner-controlled, including release tags. Do not start another phase. When the next phase is authorized, automatically verify this phase's outstanding post-owner-commit conditions before dependent work.

## Detailed Tasks

### Task 16.1 — Baseline Profiling
- **What:** Profile the live loop in experiment mode on the target CPU: per-stage wall time distributions, CPU utilisation per thread, allocations, frame drops; on a fixed set of replay sessions (deterministic) and one live session.
- **Why:** Optimise what is measured, not assumed.
- **Depends on:** Phase 13/15.
- **Evidence:** Profiling report (MEASURED).

### Task 16.2 — Latency Budget Table
- **What:** From 16.1, set per-stage targets consistent with the 30 FPS frame period (and 60 FPS if attempted) leaving headroom (target values are planning targets, labelled *Target*); record the sum and compare to the frame period.
- **Why:** Phase 01 budget slots are filled here.
- **Depends on:** 16.1.
- **Evidence:** Table with Baseline (Measured) / Target / Achieved (Measured after) columns.

### Task 16.3 — Regression Set and Tolerances
- **What:** Fix a set of dataset sessions (one fold) + developer sessions; run the harness with the *current* system to produce reference metrics and commit logs; define tolerances (candidate: identical commit sets except explained timing shifts; lead-time median within a stated band; trajectory error within export-parity tolerance) — recorded before optimising.
- **Why:** Optimisations must not change behaviour silently.
- **Depends on:** Phase 09.
- **Evidence:** Reference results + tolerance document.

### Task 16.4 — Apply Optimisations Incrementally
- **What:** For each candidate (1–6 above): implement, measure before/after (latency, drops, CPU), run the regression check; keep or revert with a recorded reason. Order by expected gain from profiling.
- **Why:** Attribution of gains; reversibility.
- **Depends on:** 16.2, 16.3.
- **Evidence:** Per-optimisation entries in the perf log with numbers (MEASURED) and regression outcome.

### Task 16.5 — 60 FPS Attempt
- **What:** If Phase 02 measured native 60 FPS delivery: run the optimised pipeline at 60 FPS; measure delivered processing FPS, drops, stage latencies; handle `dt_step` mismatch per the Phase 13 rule; verify no interpolation is used anywhere; report achieved end-to-end FPS. If the camera cannot deliver 60 FPS, record PENDING with the reason and, if an external camera becomes available, repeat Phase 02 measurements first.
- **Why:** Q23 target, honestly.
- **Depends on:** 16.4.
- **Evidence:** 60 FPS report (MEASURED or PENDING).

### Task 16.6 — Model Cost Reduction
- **What:** Quantisation/graph optimisation of the shipped model; measure latency and harness metrics vs. the float model; keep only if within regression tolerance.
- **Why:** CPU-first.
- **Depends on:** 16.3.
- **Evidence:** Table (MEASURED).

### Task 16.7 — Update `Δ_proc` and Offline Re-Runs
- **What:** Update the `Δ_proc` policy constants to the optimised measured stage latencies; if the change is material (rule from Phase 13 Task 13.6), re-run Phase 09/10 headline evaluations with the new `Δ_proc` (same models) and record both versions (Historical vs. current).
- **Why:** Consistency between offline lead-time numbers and the live system.
- **Depends on:** 16.4.
- **Evidence:** Updated constants; re-run manifests.

### Task 16.8 — Stability Under Load
- **What:** Long-run (soak, candidate duration recorded) at the optimised settings: drops, memory growth, audio underruns, fallback events.
- **Why:** Optimisations can introduce instability.
- **Depends on:** 16.4.
- **Evidence:** Soak report (MEASURED); full soak testing continues in Phase 17.

## Data Requirements

- Regression session set (dataset fold + developer sessions); no new participant data.

## Algorithms / Technical Approach

- Sampling/instrumented profiling; shared-memory frame passing; ONNX Runtime graph optimisation and quantisation; vectorised NumPy; preallocation.

## Interfaces / Contracts

- No contract changes allowed in this phase without an ADR; any change triggers `TEST-PARITY-1` and the regression check.

## Tests

- Regression check against the reference set; `TEST-CAUSAL-1` and `TEST-PARITY-1` re-run after threading changes; all unit suites; soak test.

## Measurements

| Quantity | Label |
|----------|-------|
| Per-stage latency p50/p95 before/after each optimisation | MEASURED |
| End-to-end processing FPS and drops at 30 FPS; at 60 FPS if attempted | MEASURED / PENDING |
| Model latency float vs. quantised; harness deltas | MEASURED |
| CPU utilisation, memory | MEASURED |
| Regression deltas vs. tolerances | MEASURED |

## Experimental Design

- Paired before/after on identical replay sessions; live sessions for capture/threading effects; multiple runs to characterise variance (count recorded).

## Acceptance Criteria

1. Profiling and budget table complete.
2. Each optimisation has before/after numbers and a regression outcome; kept changes pass tolerances.
3. 60 FPS attempt reported honestly (achieved or PENDING with reason).
4. `Δ_proc` constants updated and offline re-runs done if material.
5. Causality and parity tests pass after all changes; soak run completed.

## Definition of Done

- Reports, perf log, updated constants, gate record PASS; integrity checklist applied (achieved FPS is native; targets labelled).

## Risks

- Python multiprocessing overhead may erase gains → measured; revert.
- Quantisation may shift predictions → regression check.
- 60 FPS may be unattainable on the laptop → documented; external camera path.

## Failure Modes

- Worker desynchronisation creating future-frame access → `TEST-CAUSAL-1` in live mode.
- Optimisation changes commit behaviour → regression check fails → revert.

## Fallback Strategy

- Ship the best configuration that passes regression; keep 60 FPS as a documented Target.

## Artifacts Produced

- `docs/perf/phase-16-profiling.md`, `phase-16-budget.md`, `phase-16-perf-log.md`, `phase-16-60fps.md`, `phase-16-soak.md`
- `scripts/{profile_pipeline,fps_end_to_end,regression_check}.py`
- Updated `eval/constants.py` (`Δ_proc`), re-run manifests
- `docs/gates/phase-16-gate.md`

## Execution Environment Record

The Phase execution evidence MUST record:

- Codex model actually used
- Reasoning effort actually used
- execution date/time (with timezone)
- Git HEAD SHA at start
- Git HEAD SHA at final verification
- git_dirty state (at start and final verification)

Do not claim that the recommended model was actually used unless the execution evidence records it.

## Exit Gate

Reviewer verifies before/after evidence, regression, causality/parity. PASS → Phase 17.

## What Must NOT Be Done Yet

- No interpolation-based frame-rate increase.
- No re-training to compensate for optimisation effects without recording it as a new model.
- No participant experiments.

## Open Questions

- External camera acquisition for 60 FPS (owner).
- Multiprocessing vs. threading final choice (Pending Benchmark here).

## Decisions That Must Be Experimentally Validated

- Every optimisation's retention (Task 16.4).
- Budget values (Task 16.2 → achieved).
- Quantisation adoption (Task 16.6).
