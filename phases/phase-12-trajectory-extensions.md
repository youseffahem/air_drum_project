# Phase 12 — Trajectory Prediction Extensions

## Status

Planned

## Codex Model for This Phase

- **Model:** GPT-6 Astra
- **Reasoning effort:** Extra High
- **Recommended profile:** Deep ML / Trajectory Prediction
- **Why this choice:** If this optional phase is attempted, causal attention, longer horizons, multimodal trajectories, uncertainty propagated through geometry, and decoding changes each need CPU feasibility and pre-declared go/no-go comparisons. Astra fits the experimental architecture work; Extra High is justified for reasoning across those interacting representations, causality tests, and baseline comparisons. A documented skip requires no model execution.

> Set the model and reasoning effort in the Codex picker before running this phase.
> This section is a workload recommendation only; text in the prompt does not switch the active model.
> Record the actual model and reasoning setting used in the phase evidence.
> If the recommended model is unavailable, use the strongest available compatible model and record the actual setting used.
> The selected model is not a substitute for tests, acceptance criteria, or empirical evidence.

## Purpose

Investigate **optional** extensions of the trajectory predictor — longer horizons, richer trajectory representations, temporal attention / Tiny Transformer, uncertainty estimation, and improved trajectory decoding — each with an explicit go/no-go criterion measured with the frozen harness. This phase is **not mandatory**: if Phases 10–11 already provide the research contribution (measured lead time vs. FP comparison against baselines), Phase 12 may be skipped with a written justification, or reduced to the subset of extensions that is computationally and temporally affordable.

## Why This Phase Exists

Phase 10 fixes a simple, defensible representation (fixed-step displacements, deterministic point prediction). Several known limitations of that choice — regression-to-the-mean near stroke reversals, no notion of confidence for FP gating, horizon limited by trajectory error growth — have standard remedies whose benefit for *this* task is unknown. The extensions are separated so that the core result (Phase 10) does not depend on them and so that they can be dropped without harming the thesis.

## Relationship to Research Contribution

Potential refinements of the core contribution: larger useful lead time (longer horizon with acceptable error), better FP control (uncertainty-aware gating), or better timing (better decoding). Any improvement must be shown on the same lead-time-vs-FP axes; otherwise the extension is not adopted.

## Inputs

- Phase 10/11 selected model, reproducibility package, pre-registration template, FP budget, `W`, folds.
- Phase 09 harness.
- Compute/time budget available (Open Question for the owner at phase entry).
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-044 (Tiny Transformer go/no-go); contributes to REQ-109.

## Expected Outputs

- Phase-entry decision record: which extensions are attempted (with justification), or a skip record.
- For each attempted extension: implementation, CV-fold results vs. the Phase 10/11 reference, latency/memory, and a go/no-go ADR.
- If any extension is adopted: updated model package, updated reproducibility package, single confirmatory test run.

## Dependencies

- Phase 10 Exit Gate (Phase 11 optional but recommended before 12 so that the reference is the shipped model).

## System Components

- `src/spacedrums/models/temporal/ext/{long_horizon.py, representations.py, attention.py, tiny_transformer.py, uncertainty.py, decoding.py}`
- `scripts/{eval_extension, compare_extensions}.py`
- `experiments/phase-12/`

## Architecture

Extensions plug into the Phase 10 pipeline at defined points:

| Extension | Plug-in point | Output change | Consumer change |
|-----------|---------------|---------------|-----------------|
| E1 Longer horizon | trajectory head (`K` larger; optionally coarser `dt_step` beyond a near-field) | more/farther steps | geometry unchanged |
| E2 Richer representation | head + `decode.py` (absolute + velocity; polynomial/Bezier coefficients; multi-modal mixture) | `velocities`, mode weights | geometry consumes each mode; commit uses best/most-probable mode (rule) |
| E3 Temporal attention / Tiny Transformer | encoder (causal self-attention with masked future; small depth/width) | none | none |
| E4 Uncertainty estimation | head (per-step variance / quantiles / MC-dropout / ensembles) | `uncertainty[K×…]` | commit gate: crossing probability from uncertainty propagation through geometry |
| E5 Better decoding | `decode.py` (physically constrained smoothing; residual over Baseline B extrapolation) | none | none |

**Causality rule (README §13):** every extension's encoder, head, and decoder consumes only observations with timestamp ≤ the current frame's `t_capture`. Attention variants must mask all future positions; uncertainty sampling uses only the current prediction; every new component must pass `TEST-CAUSAL-1/2` before any result is reported.

**Core requirement vs. optional extension**

- **Core (already delivered by Phase 10/11):** causal trajectory prediction → geometry → predicted strike, compared to baselines with lead time / FP / timing error / latency.
- **Optional (this phase):** E1–E5. Each is *optional individually*; adoption requires measured improvement under the go/no-go rule.

## Execution Instructions

- When this phase is authorized, automatically perform any outstanding post-owner-commit verification for its dependency phases on the current Git HEAD before dependent work; record the SHA, dirty state, and results. A commit alone does not satisfy a gate.
- Execute the entire phase end-to-end in the stated task order and automatically run executable gate conditions, without task-by-task or condition-by-condition prompting. Preserve all dependencies, optional-scope decisions, acceptance criteria, and evidence rules.
- Never fabricate participant evidence or substitute synthetic/developer evidence for it. Unavailable evidence and owner-only decisions remain PENDING; continue independent executable work and report blockers at the Exit Gate.
- Stop only at this phase's Exit Gate for owner/reviewer action under the [gate procedure](../docs/gates/gate-procedure.md). Commit, tag, and push remain owner-controlled, including release tags. Do not start another phase. When the next phase is authorized, automatically verify this phase's outstanding post-owner-commit conditions before dependent work.

## Detailed Tasks

### Task 12.1 — Phase-Entry Decision
- **What:** Given Phase 10/11 results and remaining time/compute, decide which of E1–E5 to attempt, in priority order justified by the failure-case catalogue (e.g. if FPs dominate → E4 first; if lead time is horizon-bound → E1; if reversal errors dominate → E2/E5). Record the decision, or a skip with justification.
- **Why:** The phase must not consume time that the evaluation (Phase 18) needs.
- **Depends on:** Phase 10/11 reports.
- **Evidence:** `phase-12-entry-decision.md`.

### Task 12.2 — Go/No-Go Rule (pre-declared)
- **What:** For each attempted extension: adopt only if, on CV folds with the same seeds/folds/`W`/FP budget, it improves the pre-declared primary criterion (candidate: median `L_pred` at the FP budget) by more than the seed-variance band **and** does not worsen timing error MAE beyond a bound **and** stays within the CPU latency budget (Phase 13/16 budget if known, else the Phase 10 measured latency × a factor recorded here).
- **Why:** Prevents adopting complexity for marginal or noisy gains.
- **Depends on:** 12.1.
- **Evidence:** Rule in the pre-registration addendum.

### Task 12.3 — E1 Longer Horizon
- **What:** Extend `K`/`H` beyond the Phase 10 chosen value (grid); optional two-rate representation (fine near steps, coarse far steps); evaluate lead-time vs. FP and FDE growth; check whether commit thresholds can exploit the longer horizon without FP explosion.
- **Why:** Lead time is bounded by `H − Δ_proc`.
- **Depends on:** 12.2.
- **Evidence:** Report; go/no-go ADR.

### Task 12.4 — E2 Richer Representation
- **What:** Candidates: (a) predict velocities per step and integrate; (b) polynomial/Bezier coefficients decoded to points; (c) multi-modal mixture (M modes with weights) — geometry evaluated per mode; commit on the most probable mode, or on aggregated crossing probability (rule recorded). Evaluate ADE/FDE (best-of-M and most-probable), lead time/FP.
- **Why:** Reversal-point ambiguity (strike vs. pull-up) is inherently multi-modal.
- **Depends on:** 12.2.
- **Evidence:** Report; ADR.

### Task 12.5 — E3 Temporal Attention / Tiny Transformer (only if computationally justified)
- **What:** Causal self-attention encoder (small depth/width/heads; future-masked; relative time encoding using `dt`), and/or an attention layer on top of the GRU/TCN. Justification gate: CPU latency within budget at batch 1 — measured *before* full training (a randomly initialised model's latency is sufficient to decide feasibility). Evaluate as in Phase 10.
- **Why:** Q44 optional candidate; attention may capture stroke-phase structure; cost may be prohibitive on CPU.
- **Depends on:** 12.2.
- **Evidence:** Feasibility latency report; if feasible, results report; ADR.

### Task 12.6 — E4 Uncertainty Estimation
- **What:** Candidates: heteroscedastic per-step Gaussian outputs (NLL loss), quantile regression, MC-dropout, small ensembles (latency multiplies). Propagate uncertainty through geometry: probability that the trajectory crosses the impact surface within the horizon (Monte-Carlo sampling of trajectories or analytic approximation) → a *geometry-grounded* strike probability used as a commit gate. Evaluate calibration (reliability of crossing probability vs. observed outcome) and lead-time vs. FP.
- **Why:** Principled FP control that stays trajectory-first.
- **Depends on:** 12.2.
- **Evidence:** Calibration plots; curves; ADR.

### Task 12.7 — E5 Better Decoding
- **What:** Candidates: predict residuals over Baseline B extrapolation (model learns the correction); physically constrained smoothing of decoded points (e.g. bounded acceleration); time-resampling to the live `dt`. Evaluate trajectory error, timing error, lead time/FP.
- **Why:** Cheap improvements that may reduce timing error without new architecture.
- **Depends on:** 12.2.
- **Evidence:** Report; ADR.

### Task 12.8 — Confirmatory Run and Package Update (only if something is adopted)
- **What:** Single test-participant run of the adopted configuration vs. the Phase 10/11 reference; update the reproducibility package and ship ADR.
- **Why:** Test data used once per shipped configuration.
- **Depends on:** Adopted extension(s).
- **Evidence:** Test report; updated package.

## Data Requirements

- `ds-v1.0` folds and test participants; no new data.

## Algorithms / Technical Approach

- E1: larger `K`; two-rate decoding.
- E2: velocity integration; polynomial bases; mixture density heads.
- E3: causal masked self-attention; relative positional/time encoding.
- E4: heteroscedastic NLL; quantile loss; MC-dropout; ensembles; Monte-Carlo crossing probability through Phase 04 geometry.
- E5: residual-over-physics; constrained smoothing; resampling.

## Interfaces / Contracts

- `TrajectoryPrediction` optional fields used: `velocities`, `uncertainty`; new optional `modes` field (schema-version bump + ADR) if E2 multi-modal is adopted.
- `geometry.intersect` gains an optional probabilistic variant `intersect_prob(samples) -> crossing_probability, t_impact_pred_distribution` (Phase 04 module extension; deterministic path unchanged).
- Commit policy optional gate on crossing probability.

## Tests

- Causality tests on every new encoder/head (attention masks in particular).
- Decoding round-trips; mixture head shape/weights; uncertainty propagation on synthetic trajectories with known crossing probabilities.
- Export parity and latency for each attempted extension.

## Measurements

| Quantity | Label |
|----------|-------|
| Per-extension: ADE/FDE, lead time at FP budget, FP/min, FN, timing error, zone accuracy, latency, memory, seed variance | MEASURED (if attempted) |
| E4 calibration (reliability diagram, ECE) | MEASURED (if attempted) |
| E3 feasibility latency | MEASURED (if attempted) |

## Experimental Design

- Same folds/seeds/`W`/FP budget/operating rules as Phase 10; pre-registered go/no-go rule; one confirmatory test run only if adopted.
- Extensions evaluated independently against the reference; combinations only if individually adopted (record).

## Acceptance Criteria

1. Entry decision recorded (attempt list or skip with justification).
2. Go/no-go rule pre-declared.
3. Each attempted extension has a results report and an ADR.
4. If adopted: confirmatory test run and updated packages; if none adopted: a summary stating so.

## Definition of Done

- Acceptance criteria; gate record PASS; integrity checklist applied.

## Risks

- Time sink → entry decision and go/no-go rule bound the effort.
- Transformer latency on CPU → feasibility gate before training.
- Uncertainty calibration may be poor with few positives → reported.

## Failure Modes

- Extension improves ADE but not lead time/FP → not adopted (rule).
- Multi-modal decoding creates more candidates → FP increase → not adopted or gated.

## Fallback Strategy

- Skip the phase or any extension; the core contribution stands on Phases 10–11.

## Artifacts Produced

- `docs/experiments/phase-12-entry-decision.md`, `phase-12-prereg.md`
- `src/spacedrums/models/temporal/ext/…`
- `docs/reports/phase-12-<extension>.md` per attempted extension
- `docs/decisions/ADR-<n>-ext-<name>.md`
- `experiments/phase-12/…`
- `docs/gates/phase-12-gate.md`

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

Reviewer verifies entry decision, rule, reports/ADRs (or skip record). PASS → Phase 13 proceeds with the shipped configuration.

## What Must NOT Be Done Yet

- No live integration (Phase 13).
- No adoption without the go/no-go rule.
- No bidirectional or future-attending layers under any name.

## Open Questions

- Compute/time budget for this phase (owner).
- Whether E4's crossing probability should replace `τ_commit`-style gating entirely (only if adopted and measured).

## Decisions That Must Be Experimentally Validated

- Every extension's adoption (Tasks 12.3–12.7).
- Commit rule for multi-modal outputs (Task 12.4).
