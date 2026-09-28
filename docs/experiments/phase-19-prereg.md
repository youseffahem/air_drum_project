# Phase 19 ablation protocol — DRAFT, NOT APPROVED OR ARCHIVED

**PREPARATION ONLY. Phase 18 remains PENDING.** The owner authorized a scheduling
exception for engineering preparation on 2026-09-27. This document supplies no
participant evidence, approval, frozen reference, or authority to execute experiments.
There is no Phase 19 preregistration hash ledger yet. Existing ledgers are unchanged.

## Prerequisites and scope

REQUIRES FROZEN REFERENCE: the approved Phase 18 preregistration, valid reviewer gate
decision, actual ds-v1.0 manifest, reviewed labels, frozen CV and test rosters, selected
model/export and normalization, base configuration, matching W, accepted measured
processing delay, operating rule and budgets, and frozen participant reference results.
REQUIRES PARTICIPANT DATA: all study estimates and mechanistic interpretations.

Default scope is CV only. Reserved test participants cannot enter training, normalization,
operating-point selection, or this runner. A final test table requires a later explicit
protocol amendment and authorization; the present interface refuses it. Phase 20 is outside scope.

The reference descriptor follows `schemas/ablation-reference.schema.json`. It names
existing files by relative path and SHA-256, including each CV session and label directory.
It is an inventory of genuine inputs, not a replacement for them. No sample participant
reference is provided. `--check-dependencies` is read-only and never authorizes execution.

## Candidate variants and one-factor rules

Each eligible model variant is retrained from scratch for the same fold/seed pairs.
Use the reference training schedule, model family and all settings except the declared
factor. Refit normalization on the same training participants only. Rebuild windows and
targets when N or K changes. The final folds, seeds, history/horizon grid values, compute
budget and feasible subset are PENDING the frozen reference and owner review.

| Variant | Prepared mechanism | Feasibility still required |
|---|---|---|
| AB-VEL | Zero VEL values/masks after normalization, plus TTS and tangent/normal acceleration cues | Frozen feature schema |
| AB-ACC | Zero ACC and JERK, if present | Frozen feature schema |
| AB-AXIS / HAND / CONF | Zero the corresponding group, retaining F and architecture | Frozen feature schema |
| AB-ZONE | Zero ZONE, position offsets and inward-speed features | Frozen feature schema; downstream geometry remains |
| AB-HIST-S/L | Change N only, rebuild histories | Eligible smaller/larger Phase 10 grid entries |
| AB-HOR-S/L | Change K only at the original step, rebuild targets | Eligible horizons within H_max |
| AB-NOTRAJ | Remove trajectory head; existing direct-head diagnostic adapter and explicit harness flag | MT trajectory/strike/TTI/zone heads; never live eligible |
| AB-REACT / RULE | Existing A/B harness paths | Read genuine Phase 18 reference arms at locked settings |
| AB-INT | Remove intensity head; geometry intensity; remove intensity agreement check if enabled | MT with intensity head |
| AB-AUX | Remove auxiliary strike head/loss and disable auxiliary gate | Auxiliary head/gate used by reference |
| AB-FPS | Drop whole raw frames before perception/tracking; preserve source IDs/timestamps; recompute dt/features | Matched recordings; 30→15, or evidenced native 60→30 |
| AB-TIP | Fresh perception producer, tracking and causal features; reference labels unchanged | Raw frames; MARKER only where recorded, explicitly benchmark condition |

Feature removal tests the explicit input channel. Positions and remaining signals can
still imply motion; upstream perception/tracking can still use hand and axis information.
The mask specification names every removed index and hashes the unchanged feature schema.
No statistical-independence claim follows from zeroing a group.

FPS analysis must declare the matching interval, missing-frame policy, horizon in seconds,
and history duration. Changes required by the new sampling interval must be recorded before
execution; do not silently change both history duration and horizon. Retracking tests do not
establish native delivery rate or camera quality. Raw reference hashes, perception versions,
method parameters and label hashes must accompany each retracked session.

Reuse a Phase 10 horizon result only when the complete cell signature matches: dataset,
labels, split, normalization, features, model and training settings, seed/fold, harness,
W, processing delay, operating rule, budgets and sources. Otherwise retrain.

## Evaluation and statistics

Use the unchanged Phase 09 harness and Phase 18 aggregation. For each model variant,
reselect its operating point on validation participants by the same frozen selection
rule. Do not tune on the reserved test set. The development runner uses an explicitly
labelled FP/FN-only rule; it does not instantiate pending participant timing/CPU budgets.

Collect per participant/fold/seed: median L_pred at the budget, FP/min, FN rate,
TE_pred MAE, zone accuracy, ADE/FDE, and inference-to-candidate latency. Undefined
metrics remain null. An infeasible cell has no primary estimate. Retain selection
details, missing cells, raw event digests and denominator counts. A/B remain fixed
reference comparisons in the participant study. Their synthetic rehearsal merely
exercises their existing harness paths.

Draft primary statistic: mean over participants of paired variant-minus-reference
differences, first averaged over matching folds/seeds within each participant.
Reject mismatched or duplicate cell keys. Exclude and explicitly list any participant
with incomplete paired support; never treat seeds/events/frames as independent people.
Report feasibility counts separately. Candidate seed band: twice the pooled within-fold
SD of the reference seed-level participant-macro lead (consistent with Phase 12).
The band is undefined unless every fold has at least two seeds with identical complete
participant support. The precise rule remains subject to approval before data.

Use 10,000 participant-bootstrap resamples, seed 19, 95% percentile intervals. A primary
change is material only if its absolute estimate exceeds the seed band and its CI
excludes zero. Otherwise report no material effect; undefined support is insufficient
support. Direction and all secondary metrics accompany the primary result. Small-P
warnings from the Phase 18 bootstrap remain attached. Intervals are unadjusted and
descriptive; no multiplicity-adjusted significance or adoption decision is claimed.

## Verification and reproducibility

Before accepting results, rerun harness self-checks and TEST-CAUSAL-1/2 for masking,
window changes, no-trajectory diagnostics and raw-frame transformations. The synthetic
runner checks its exact trained adapters by future perturbation/truncation before metrics.
Unit tests cover declared-window truncation for GRU/TCN and every prepared input/head path.
Empty output sets and ineffective perturbations remain visible in causality records.

Record source hashes, plan/config hashes, dataset/split/normalization hashes, exports,
mask definitions, fold/seed pairs, command, environment, executor attribution and Git
SHA/dirty state. Dirty SYNTHETIC/DEV checks cannot establish participant validation.
Regenerate reports from stored results and compare repeated deterministic runs.
CPU timing must be measured separately under the approved timing protocol; null is not zero.

## Pending approval fields

All of these are PENDING: reference digest, study plan digest, participant folds/seeds,
final variant list and infeasibility reasons, operating selection rule and budgets,
W/delay, paired-support rule, runtime measurement plan, execution budget and reviewer
approval. Only after these exist may the owner archive and approve a final preregistration
and explicitly authorize experimental execution. The preparation CLI keeps execution disabled.
