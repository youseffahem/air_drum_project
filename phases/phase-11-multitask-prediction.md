# Phase 11 — Multi-Task Prediction: Time-to-Impact, Zone & Intensity

## Status

PENDING — development implementation and synthetic verification; participant evidence and reviewer gate remain pending.

## Codex Model for This Phase

- **Model:** GPT-6 Astra
- **Reasoning effort:** Extra High
- **Recommended profile:** Deep ML / Multitask Learning
- **Why this choice:** Shared-encoder training introduces masked losses, task conflicts, loss-weight search, head ablations, and geometry-consistency gates across several target semantics. Astra fits the research and implementation workload; Extra High is justified by the coupled optimization and leakage-sensitive joint evaluation while preserving the live trajectory-first invariant.

> Set the model and reasoning effort in the Codex picker before running this phase.
> This section is a workload recommendation only; text in the prompt does not switch the active model.
> Record the actual model and reasoning setting used in the phase evidence.
> If the recommended model is unavailable, use the strongest available compatible model and record the actual setting used.
> The selected model is not a substitute for tests, acceptance criteria, or empirical evidence.

## Purpose

Extend the selected Phase 10 temporal model with a **shared causal encoder and multiple task heads** — future trajectory (primary, retained), strike-within-horizon probability, Time-to-Impact, impact zone, impact position, and intensity proxy — and determine **experimentally** whether multi-task learning improves, degrades, or leaves unchanged the trajectory-first strike pipeline on lead time, FP/FN, timing error, zone accuracy, and intensity agreement, under the same harness, folds, and rules. Define how the heads' outputs may be used (consistency checks and gating) without bypassing geometry.

## Why This Phase Exists

Q41 lists strike-within-horizon, TTI, zone, impact position, and intensity as prediction targets, while Q42 fixes trajectory-first as the main direction. The two are compatible only if the additional outputs are studied *alongside* the trajectory route: as auxiliary supervision that may shape the encoder, as redundant estimates for consistency checks, or as gates for FP control. Whether any of this helps is an empirical question; assuming it would help is exactly what this phase avoids.

## Relationship to Research Contribution

- Tests whether strike-related supervision improves the encoder's usefulness for anticipation (lead time / FP) — a direct refinement of the core contribution.
- Provides the intensity-proxy and zone outputs whose agreement/accuracy are required metrics (Q45).
- Supplies head-level ablations for Phase 19 ("without intensity", "without trajectory").

## Inputs

- Phase 10 selected model family, `H`, `N`, operating-point rules, FP budget, pre-registration template, reproducibility package.
- Phase 08 samples with auxiliary targets (`strike_within_H`, `tti` + mask, `zone_id`, `impact_position`, `intensity_proxy_gt`) and their masks.
- Phase 09 harness (frozen), Baseline results.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-041 (task heads), REQ-014 (intensity agreement); contributes to REQ-109.

## Expected Outputs

- Multi-task model (`C-MT`) implementation with configurable heads and loss weighting.
- Per-task evaluation reports on CV folds; head-ablation results; consistency-check and gating evaluation; comparison against the single-task Phase 10 model and Baselines.
- Decision (ADR) on which heads ship in the live system and how each is used (informational, gating, or consistency).
- Updated `TrajectoryPrediction.aux` population rules.

## Dependencies

- Phase 10 Exit Gate.

## System Components

- `src/spacedrums/models/temporal/heads.py` (extended), `losses.py` (multi-task), `mt_train.py`, `mt_adapter.py`, `consistency.py`
- `scripts/{train_mt, eval_mt, ablate_heads, eval_consistency}.py`
- `experiments/phase-11/`

## Architecture

```
X[N×F] ──► shared causal encoder (Phase 10 family, weights shared across tasks)
              │
              ├─ Trajectory head (PRIMARY) ─► K displacements ─► decode ─► Phase 04 geometry ─► StrikeCandidate(MODEL)
              ├─ Strike head: p(strike within H)                       ─┐
              ├─ TTI head: t̂ti (regression; masked when no impact in H_max) │
              ├─ Zone head: zone logits [Z]                             ├─► aux fields on TrajectoryPrediction
              ├─ Impact-position head: (x̂, ŷ) on surface               │
              └─ Intensity head: intensity proxy (regression)           ─┘
                                                                        │
consistency.py: compare geometry-derived {zone, TTI, position, intensity} with head outputs ─► agreement flags / gates
Phase 05 commit policy: unchanged; may consume p(strike), agreement flags as optional gates (config)
```

**Invariant:** the committed strike's `zone_id`, `t_impact_pred`, and `impact_position` come from **geometry on the predicted trajectory**. Head outputs may (a) gate the candidate (`p_aux`, agreement), (b) be logged for evaluation, (c) provide the intensity proxy *as an alternative* to the geometric crossing speed — the choice is an experiment (Task 11.7) and is recorded. No head output creates a candidate on its own.

## Execution Instructions

- When this phase is authorized, automatically perform any outstanding post-owner-commit verification for its dependency phases on the current Git HEAD before dependent work; record the SHA, dirty state, and results. A commit alone does not satisfy a gate.
- Execute the entire phase end-to-end in the stated task order and automatically run executable gate conditions, without task-by-task or condition-by-condition prompting. Preserve all dependencies, optional-scope decisions, acceptance criteria, and evidence rules.
- Never fabricate participant evidence or substitute synthetic/developer evidence for it. Unavailable evidence and owner-only decisions remain PENDING; continue independent executable work and report blockers at the Exit Gate.
- Stop only at this phase's Exit Gate for owner/reviewer action under the [gate procedure](../docs/gates/gate-procedure.md). Commit, tag, and push remain owner-controlled, including release tags. Do not start another phase. When the next phase is authorized, automatically verify this phase's outstanding post-owner-commit conditions before dependent work.

## Detailed Tasks

### Task 11.1 — Multi-Task Heads and Masked Losses
- **What:** Implement heads and losses: trajectory (Phase 10 loss), strike BCE, TTI regression (L1/Huber, masked to samples with an impact within `H_max`; alternatives: regress `log(tti)` or classify TTI bins — candidates), zone cross-entropy (masked to positives), impact-position L1/L2 (masked), intensity regression (L1/Huber, masked). Each loss has a weight `λ_task` (tunable). Missing labels are masked per sample per task; no imputation.
- **Why:** Q41 targets; missing-label handling stated explicitly.
- **Depends on:** Phase 08 targets.
- **Evidence:** Loss tests with masks; a sample with no impact contributes only to trajectory + strike-negative losses.

### Task 11.2 — Loss Weighting Strategies
- **What:** Candidates: fixed weights (grid); uncertainty-based weighting (learned log-variances); gradient-norm balancing; trajectory-dominant scheme (`λ_traj = 1`, others small). Run a bounded comparison on CV folds; record.
- **Why:** Task conflicts can degrade the primary trajectory objective; weighting must be chosen on evidence.
- **Depends on:** 11.1.
- **Evidence:** Weighting comparison table (trajectory ADE, lead time at FP budget, per-task metrics).

### Task 11.3 — Task-Conflict Diagnostics
- **What:** Measure per-task gradient cosine similarity with the trajectory task during training (sampled); measure trajectory ADE/FDE and harness lead-time/FP of the MT model vs. the single-task model at equal budget; flag heads whose inclusion degrades the primary metrics beyond seed variance.
- **Why:** Multi-task learning does not automatically help; conflicts must be detected, not assumed away.
- **Depends on:** 11.2.
- **Evidence:** Conflict report.

### Task 11.4 — Per-Task Evaluation
- **What:** On CV folds (and once on test participants at the end, Task 11.9):
  - Strike head: precision-recall / ROC on frames; **but** the research-relevant evaluation is through the harness (as a gate), not frame AUC alone.
  - TTI head: MAE/bias vs. GT `tti` on pre-impact frames, stratified by true TTI; compared with the geometry-derived TTI from the trajectory head and with Baseline B's TTI.
  - Zone head: accuracy/confusion vs. GT; compared with geometry-derived zone.
  - Impact-position head: error vs. GT position; compared with geometry-derived position.
  - Intensity head: r, ρ, MAE vs. `intensity_proxy_gt`; compared with the geometric crossing-speed proxy from the predicted trajectory and with Baseline B's proxy.
- **Why:** Q45 metrics per output; each head must be judged against the trajectory-derived equivalent.
- **Depends on:** 11.1.
- **Evidence:** Per-task tables (MEASURED).

### Task 11.5 — Consistency Checks and Gating
- **What:** Implement `consistency.py`: agreement flags when head zone == geometry zone, |head TTI − geometry TTI| ≤ tolerance, |head position − geometry position| ≤ tolerance (tolerances tunable). Evaluate commit gating variants through the harness: no gate; `p_aux` gate; agreement gate; both. Report lead-time vs. FP curves for each.
- **Why:** The heads' most plausible value in a trajectory-first system is redundancy for FP control; test it.
- **Depends on:** 11.4.
- **Evidence:** Gating report (MEASURED).

### Task 11.6 — Head Ablations (within phase)
- **What:** Train variants: trajectory-only (Phase 10 reference), +strike, +TTI, +zone, +position, +intensity, all heads; also **no-trajectory** variant (heads only, strike from `p(strike)` + TTI head, *no geometry*) as a diagnostic of what trajectory-first contributes — this variant is evaluated but is **not** a candidate for the live system by design. Same seeds/folds.
- **Why:** Phase 19 requires head ablations; the no-trajectory diagnostic quantifies the value of the geometric route.
- **Depends on:** 11.2.
- **Evidence:** Ablation table (MEASURED) with seed variance.

### Task 11.7 — Intensity Proxy Source Decision
- **What:** Compare intensity proxies available at commit time: (a) predicted crossing speed along the normal (geometry on the trajectory), (b) intensity head, (c) Baseline B extrapolated crossing speed; metric = agreement with `intensity_proxy_gt` at the *commit* time (not at impact). Decide the live source (ADR); remains a proxy, not force.
- **Why:** Q14; Q45.
- **Depends on:** 11.4.
- **Evidence:** Table; ADR.

### Task 11.8 — Latency and Memory of the MT Model
- **What:** Export; parity; batch-1 latency p50/p95/p99 vs. the single-task model; parameter count; memory.
- **Why:** CPU-first selection criteria.
- **Depends on:** 11.2.
- **Evidence:** Latency table (MEASURED).

### Task 11.9 — Confirmatory Test-Participant Run and Ship Decision
- **What:** Pre-declare which MT configuration (heads, weights, gates) is the candidate; run once on test participants alongside the Phase 10 single-task model; decide (ADR) whether the live system uses the MT model, the single-task model, or a baseline, based on lead time at FP budget, timing error, zone accuracy, intensity agreement, latency, and memory.
- **Why:** Ship decision on evidence; test data used once.
- **Depends on:** 11.5–11.8.
- **Evidence:** Test report; ship ADR; updated reproducibility package.

## Data Requirements

- `ds-v1.0` with auxiliary targets; positives per fold reported (TTI/zone/position/intensity heads train only on positives → small sample; report).

## Algorithms / Technical Approach

- Shared encoder (GRU/TCN from Phase 10) + linear/MLP heads.
- Masked multi-task loss with candidate weighting schemes.
- Gradient-conflict diagnostics via cosine similarity of task gradients on the shared parameters.
- Consistency gates in post-processing; commit policy unchanged except for optional gate inputs.

## Interfaces / Contracts

- `TrajectoryPrediction.aux` fields populated: `strike_prob_within_H`, `tti`, `zone_logits`, `impact_pos`, `intensity_proxy` (head), plus `consistency_flags` (new nullable field, schema-version bump with ADR).
- Commit policy config gains optional gate parameters (`use_p_aux`, `p_aux`, `use_agreement`, tolerances) — defaults off.

## Tests

- **Unit:** masked losses; head shapes; consistency flags; gate logic.
- **Causality:** `TEST-CAUSAL-1/2` on the MT model.
- **Leakage/determinism/export parity:** as in Phase 10.
- **Invariant test:** no `CommittedStrike` can be produced without a geometry-derived candidate (the no-trajectory diagnostic runs only in an explicitly flagged harness mode that is rejected by the live app).

## Measurements

| Quantity | Label |
|----------|-------|
| Per-task metrics (strike PR/ROC; TTI MAE/bias; zone accuracy/confusion; position error; intensity r/ρ/MAE) | MEASURED |
| Trajectory ADE/FDE (MT vs. single-task) | MEASURED |
| Harness metrics (lead time, FP/min, FN, timing error, zone accuracy) per gating variant | MEASURED |
| Head-ablation deltas with seed variance | MEASURED |
| Gradient-conflict statistics | MEASURED |
| Latency/memory | MEASURED |

## Experimental Design

- Same folds, `W`, `Δ_proc`, FP budget, operating-point rules as Phase 10; ≥ 3 seeds per variant (candidate; recorded).
- Pre-registration addendum (`phase-11-prereg.md`) listing the variants and the ship-decision rule before the test run.
- Outcome-neutral reporting: MT better / no difference / worse.

## Acceptance Criteria

1. MT model implemented with masked losses and configurable weighting; causal tests pass.
2. Loss-weighting comparison, conflict diagnostics, per-task evaluation, gating evaluation, head ablations executed on CV folds.
3. Intensity source ADR recorded.
4. Single confirmatory test run; ship ADR recorded with all criteria.
5. Latency/memory measured; reproducibility package updated.

## Definition of Done

- All acceptance criteria; reports; ADRs; gate record PASS; integrity checklist applied (no assumption that MT helps; per-task numbers only as measured).

## Risks

- Too few positives for the positive-only heads → noisy heads; report; consider training those heads only if the data supports it.
- Head gating may reduce FP at the cost of lead time → trade-off reported on the curve, not hidden.
- Schema change to `aux` → version bump with ADR.

## Failure Modes

- MT degrades trajectory ADE → detected by 11.3; ship decision may revert to single-task.
- Zone head disagrees systematically with geometry near zone boundaries → consistency gate may suppress valid strikes (FN) — reported.

## Fallback Strategy

- Ship the single-task model or Baseline B if MT offers no measurable benefit within the FP budget and latency constraints; the phase is still complete with a negative/neutral result.

## Artifacts Produced

- `src/spacedrums/models/temporal/{heads,losses,mt_train,mt_adapter,consistency}.py`
- `docs/experiments/phase-11-prereg.md`
- `docs/reports/phase-11-weighting.md`, `phase-11-conflicts.md`, `phase-11-per-task.md`, `phase-11-gating.md`, `phase-11-head-ablation.md`, `phase-11-test-run.md`
- `docs/decisions/ADR-<n>-intensity-source.md`, `ADR-<n>-ship-model.md`, `ADR-<n>-aux-schema-bump.md`
- `models/temporal/<mt_model_id>/…`, `experiments/phase-11/…`
- `docs/gates/phase-11-gate.md`

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

Gate record: [phase-11-gate.md](../docs/gates/phase-11-gate.md) — proposed FAIL for the full phase; reviewer PENDING, 2026-09-25.

Reviewer verifies pre-registration, ablation and gating reports, ship ADR. PASS → Phase 12 (optional) and/or Phase 13.

## What Must NOT Be Done Yet

- No attention/Transformer/uncertainty (Phase 12).
- No live integration (Phase 13).
- No head-only strike path in the live application.
- No re-tuning on test participants.

## Open Questions

- Should TTI be regressed directly or via bins? (candidate comparison within Task 11.1 budget)
- Should the intensity proxy be computed at commit time or updated at predicted impact time? (Task 11.7 defines at commit; alternative recorded)
- Is the no-trajectory diagnostic worth reporting in the thesis as evidence for trajectory-first? (recommended yes, with its label)

## Decisions That Must Be Experimentally Validated

- Loss weighting scheme (Task 11.2).
- Which heads ship and how they are used (Task 11.9).
- Consistency tolerances and gates (Task 11.5).
- Intensity proxy source (Task 11.7).
