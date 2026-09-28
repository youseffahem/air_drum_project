# Phase 19 — Ablation Study

## Status

PREPARATION ONLY under the owner's 2026-09-27 scheduling exception. Phase 18 remains PENDING.
See [preparation record](../docs/gates/phase-19-gate.md). Experimental execution and Phase 19
completion are not authorized; the experimental acceptance criteria below remain unmet.

## Codex Model for This Phase

- **Model:** GPT-6 Astra
- **Reasoning effort:** Extra High
- **Recommended profile:** Experimental ML / Ablation Analysis
- **Why this choice:** One-factor ablations change feature groups, history, horizons, trajectory structure, tip method, and frame rate under frozen folds, seeds, and operating rules. Astra fits the research workflow; Extra High is justified by confounding and leakage risks, matched participant analysis, conditional feasibility, and interpretation of null or adverse results.

> Set the model and reasoning effort in the Codex picker before running this phase.
> This section is a workload recommendation only; text in the prompt does not switch the active model.
> Record the actual model and reasoning setting used in the phase evidence.
> If the recommended model is unavailable, use the strongest available compatible model and record the actual setting used.
> The selected model is not a substitute for tests, acceptance criteria, or empirical evidence.

## Purpose

Quantify the contribution of individual inputs, temporal context, prediction horizon, the trajectory-first structure, and the frame rate to the temporal model's anticipation performance, using the frozen harness, the same participant-level folds, the same seeds, the same `W`, `Δ_proc`, and FP budget as Phase 18. Only ablations that are **implemented and experimentally feasible** are included; each answers one pre-declared question with an outcome-neutral interpretation rule.

## Why This Phase Exists

The thesis must explain *why* the temporal model performs as it does — which information it relies on, how much history it needs, how the horizon trades lead time against error, and whether the trajectory-first route contributes beyond a direct strike classifier. Without ablations, the comparison in Phase 18 is a black-box result.

## Relationship to Research Contribution

Provides the mechanistic evidence behind the contribution and the honest statement of what does *not* matter. The "without trajectory prediction" and "reactive only" ablations directly test the architectural claim of the project.

## Inputs

- Phase 18 frozen configuration (model family, `N`, `H`, operating rules, FP budget, `W`, `Δ_proc`), CV folds (ablations use CV folds; the test set is used only for a final table of the ablations that changed conclusions — Open Question, default: CV only).
- Phase 08 feature groups; Phase 10/11 training code; Phase 09 harness.
- Phase 02/16 evidence on native 60 FPS availability.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-306.

## Expected Outputs

- Ablation pre-registration (questions, variants, interpretation rules).
- Ablation results tables (per variant: lead time at FP budget, FP/min, FN, `TE_pred`, zone accuracy, trajectory ADE/FDE, latency) with seed variance and per-participant CIs.
- Interpretation report; figures for the thesis.
- Updated failure/limitation notes if ablations reveal dependencies (e.g. strong reliance on hand-size features).

## Dependencies

- Phase 18 Exit Gate.

## System Components

- `scripts/{run_ablation, ablation_report}.py`; configs under `configs/ablations/`; `experiments/phase-19/`.
- No new model code beyond configuration flags (feature masks, `N`, `H`), except the FPS ablation's resampled dataset build.

## Architecture

Each ablation = the Phase 18 reference configuration with **one** change, trained from scratch on each fold with the same seeds:

| ID | Question | Variant | Feasibility condition |
|----|----------|---------|-----------------------|
| AB-VEL | Without velocity? | Mask VEL group (model must infer from positions) | Always |
| AB-ACC | Without acceleration? | Mask ACC (and JERK if enabled) | Always |
| AB-AXIS | Without stick-axis information? | Mask AXIS group; tip still from the chosen method | Always |
| AB-HAND | Without hand information? | Mask HAND group (tip-only + zones) | Always |
| AB-ZONE | Without zone-relative features? | Mask ZONE group (model unaware of zone positions; geometry still applied after) | Always |
| AB-CONF | Without tracking-confidence features? | Mask CONF | Always |
| AB-HIST-S | Shorter temporal history? | `N` = a shorter value from the Phase 10 grid | Always |
| AB-HIST-L | Longer temporal history? | `N` = a longer value from the grid | Always |
| AB-HOR-S / AB-HOR-L | Different prediction horizons? | `H` shorter / longer than chosen | Always (reuse Phase 10 sweep where identical; re-run if configuration changed) |
| AB-NOTRAJ | Without trajectory prediction? | Strike from direct heads only (Phase 11 no-trajectory diagnostic); no geometry | Requires Phase 11 heads; diagnostic mode only |
| AB-REACT | Reactive detection only? | Arm A (no anticipation) | Always (reference from Phase 18) |
| AB-RULE | Physics anticipation only? | Arm B | Always (reference) |
| AB-INT | Without intensity head? | MT model without the intensity head (if MT shipped); intensity from geometry only | Requires MT shipped |
| AB-FPS | Different camera FPS? | See Task 19.6 | Requires native 60 FPS data or honest downsampling |
| AB-TIP | Different tip-estimation method? | Retrack dataset with `AXIS_REFINED` vs. `GEOM` (and `MARKER` where recorded) → features → model | Requires Phase 03 methods and retracking time |
| AB-AUX | Without auxiliary strike gating? | `λ_aux = 0`, no gate (if the shipped model uses gating) | Always |

**Causality rule (README §13):** every ablation variant consumes only observations with timestamp ≤ the current frame's `t_capture`; masking, downsampling, and the diagnostic no-trajectory mode are new code paths and must pass `TEST-CAUSAL-1/2` before their results are reported.

Interpretation rule (pre-declared): a change is "material" if the per-participant paired difference in the primary metric (median `L_pred` at FP budget) exceeds the seed-variance band and its participant-bootstrap CI excludes zero; otherwise "no material effect". Secondary metrics reported alongside; no cherry-picking.

## Execution Instructions

- When this phase is authorized, automatically perform any outstanding post-owner-commit verification for its dependency phases on the current Git HEAD before dependent work; record the SHA, dirty state, and results. A commit alone does not satisfy a gate.
- Execute the entire phase end-to-end in the stated task order and automatically run executable gate conditions, without task-by-task or condition-by-condition prompting. Preserve all dependencies, optional-scope decisions, acceptance criteria, and evidence rules.
- Never fabricate participant evidence or substitute synthetic/developer evidence for it. Unavailable evidence and owner-only decisions remain PENDING; continue independent executable work and report blockers at the Exit Gate.
- Stop only at this phase's Exit Gate for owner/reviewer action under the [gate procedure](../docs/gates/gate-procedure.md). Commit, tag, and push remain owner-controlled, including release tags. Do not start another phase. When the next phase is authorized, automatically verify this phase's outstanding post-owner-commit conditions before dependent work.

## Detailed Tasks

### Task 19.1 — Ablation Pre-Registration
- **What:** List the ablations to run (subset of the table by feasibility and time), the interpretation rule, seeds, folds, and the exact reference configuration hash.
- **Why:** Prevent post-hoc selection.
- **Depends on:** Phase 18 freeze.
- **Evidence:** `phase-19-prereg.md` with hash.

### Task 19.2 — Feature-Group Ablations (AB-VEL, AB-ACC, AB-AXIS, AB-HAND, AB-ZONE, AB-CONF)
- **What:** Train/evaluate each masked variant on all folds × seeds; harness metrics at pre-declared operating rules (re-select the operating point per variant on validation folds by the same rule — a masked model may need a different threshold; recorded).
- **Why:** Prompt §28 questions 1–4; Phase 08 groups.
- **Depends on:** 19.1.
- **Evidence:** Results table with CIs.

### Task 19.3 — History Ablations (AB-HIST-S/L)
- **What:** Train/evaluate at shorter and longer `N`; report lead time/FP/timing and latency.
- **Why:** §28 questions 5–6.
- **Depends on:** 19.1.
- **Evidence:** Table + curve.

### Task 19.4 — Horizon Ablations (AB-HOR-S/L)
- **What:** Reuse Phase 10 sweep if the configuration is unchanged (cite manifests); otherwise re-run at two alternative horizons.
- **Why:** §28 question 7.
- **Depends on:** Phase 10.
- **Evidence:** Table + curve.

### Task 19.5 — Structural Ablations (AB-NOTRAJ, AB-REACT, AB-RULE, AB-AUX, AB-INT)
- **What:** AB-NOTRAJ in diagnostic harness mode (direct heads → candidate with `t_impact_pred = now + tti_head`, zone from head; same commit policy); AB-REACT/AB-RULE from Phase 18 references; AB-AUX and AB-INT if applicable.
- **Why:** §28 questions 8–10; tests the trajectory-first claim directly.
- **Depends on:** Phase 11 heads (for AB-NOTRAJ/AB-INT).
- **Evidence:** Table; explicit statement of what the trajectory route adds (or does not).

### Task 19.6 — FPS Ablation (AB-FPS)
- **What:** Only if Phase 02/16 established native 60 FPS delivery **and** a 60 FPS recording subset exists (new recordings would be needed — Open Question / scope decision): compare models trained/evaluated at 60 FPS vs. the same recordings *downsampled to 30 FPS by frame dropping* (honest downsampling; no interpolation). If no native 60 FPS data exists, the only feasible variant is **30 FPS vs. 15 FPS by frame dropping** (to show sensitivity to temporal resolution), clearly labelled as a downsampling experiment, not a 60 FPS result. Report lead time (in ms), FP, timing error, and latency per condition.
- **Why:** §28 question 11 — honestly bounded by available hardware.
- **Depends on:** Phase 02/16 evidence; data availability.
- **Evidence:** Table with the exact condition labels; or PENDING with reason.

### Task 19.7 — Tip-Method Ablation (AB-TIP)
- **What:** Retrack the dataset with alternative tip methods (Phase 03), regenerate causal features (labels unchanged — they come from the reference track; note this), train/evaluate; report the effect of tip-estimation quality on anticipation; include `MARKER` only for sessions where the marker block exists, clearly labelled as benchmark condition.
- **Why:** Links tracking quality to anticipation performance; supports the markerless-primary decision or reveals its cost.
- **Depends on:** Phase 03 methods; compute time.
- **Evidence:** Table; note on label/track separation.

### Task 19.8 — Interpretation Report
- **What:** For each ablation: material / not material, direction, size with CI, and a one-paragraph mechanistic reading; a summary figure (forest plot of paired differences); updates to the limitations list.
- **Why:** Thesis discussion chapter.
- **Depends on:** 19.2–19.7.
- **Evidence:** Report.

## Data Requirements

- `ds-v1.0` CV folds (test participants only if pre-declared for a final table).
- Optional native 60 FPS recordings (scope decision) for AB-FPS.
- Retracked feature sets for AB-TIP.

## Algorithms / Technical Approach

- Feature masking at the loader (mask = 0 and value = 0 after normalisation; the model architecture unchanged) or by schema subset (dimension changes) — choose one and record; masking keeps architecture identical, subset reduces parameters — both acceptable if stated.
- Frame-dropping downsampler for AB-FPS with `dt` features recomputed.
- Statistics: participant-level bootstrap of paired differences; seed-variance band from the reference runs.

## Interfaces / Contracts

- Ablation config schema (`ablation_id`, `changes{}`), results schema as Phase 09.

## Tests

- Masking correctness (masked groups are exactly zero and flagged); downsampler timestamp correctness; harness self-check on the frozen version.
- Causality tests re-run for any new code path (downsampler, diagnostic mode).

## Measurements

| Quantity | Label |
|----------|-------|
| Per ablation: `L_pred` at FP budget, FP/min, FN, `TE_pred`, zone accuracy, ADE/FDE, latency; seed variance; per-participant CIs | MEASURED |
| Paired differences vs. reference with CIs | MEASURED |

## Experimental Design

- One-factor-at-a-time relative to the frozen reference; identical folds/seeds; operating point re-selected per variant by the same rule on validation folds; paired analysis; pre-declared interpretation rule; compute budget recorded and any dropped ablations listed with reasons.

## Acceptance Criteria

1. Pre-registration archived.
2. All feasible pre-declared ablations executed with full tables and CIs; infeasible ones documented as PENDING with reasons.
3. Structural ablations (AB-NOTRAJ, AB-REACT, AB-RULE) reported.
4. FPS ablation reported with honest condition labels or PENDING.
5. Interpretation report and summary figure produced.

## Definition of Done

- Acceptance criteria; manifests; gate record PASS; integrity checklist applied (no ablation described as run unless run; downsampled conditions never called "60 FPS").

## Risks

- Compute time (many trainings) → prioritise by pre-registration; reduce seeds only if recorded.
- Small effects below seed variance → reported as "no material effect", not spun.
- AB-NOTRAJ may perform comparably on some metrics → reported; the trajectory-first argument then rests on explainability/geometry generality, which must be stated as such.

## Failure Modes

- Masking leaks information through correlated features (e.g. speed present while velocity masked) → group definitions in Phase 08 must be exclusive; verify.
- Operating-point re-selection tuned on test → CV-only rule.

## Fallback Strategy

- Run the minimal set (AB-VEL, AB-ACC, AB-AXIS, AB-HAND, AB-HIST-S/L, AB-HOR-S/L, AB-NOTRAJ, AB-REACT, AB-RULE) if time is short; list the rest as PENDING.

## Artifacts Produced

- `docs/experiments/phase-19-prereg.md`
- `configs/ablations/*.yaml`, `experiments/phase-19/…`
- `docs/reports/phase-19-ablations.md` (+ figures)
- `docs/gates/phase-19-gate.md`

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

Reviewer verifies pre-registration, completeness vs. the declared list, labelling. PASS → Phase 20/21.

## What Must NOT Be Done Yet

- No changes to the shipped model based on ablation results without a new pre-registered evaluation (would be future work or a documented post-hoc change).
- No claims about 60 FPS without native 60 FPS data.

## Open Questions

- Use the test set for a final ablation table, or CV only? (default CV only)
- Record a native 60 FPS subset for AB-FPS? (scope/time decision by owner)
- Include AB-TIP given retracking cost?

## Decisions That Must Be Experimentally Validated

- Every ablation outcome (by definition).
- Masking vs. subset implementation equivalence (small check on one ablation).
