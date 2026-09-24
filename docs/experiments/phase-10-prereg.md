# Phase 10 pre-registration

Status: PENDING — draft protocol, not an approved participant pre-registration.
Created 2026-09-24 (+03:00). No held-out Phase 10 evaluation has run.

The Phase 09 gate is not passed, `W_PRIMARY_S` is unset, and reviewed ds-v1.0
participant folds are absent. The owner must resolve the budget fields below
using participant validation evidence. This document does not authorize a test
run merely by existing. Preserve a timestamped, hashed copy of the completed
protocol and selected configurations before any held-out access.

## Candidates and fixed procedures

- Shared per-hand causal GRU or causal residual TCN; no hand-id input, reference
  input, extra task head, attention or uncertainty. Pure trajectory is default;
  the only auxiliary head is strike-within-H, enabled with positive lambda.
- Candidate K={1,2,4}, N={4,8,16}; dt_step=1/30 s in the development fixture.
  That grid is a candidate motivated by prior approximately 30 FPS developer
  capture, not a fresh camera FPS measurement. For participant data, record
  measured native recording FPS and finalize the grid before CV selection.
- Interpolate target displacements onto the fixed grid only within the contiguous
  valid future causal-track span, anchored at displacement zero. No extrapolation
  and no bridging resets, missing targets or segment boundaries. Rebuild Phase 08
  windows for N/H changes; never relabel an auxiliary target by changing K alone.
- Apply Phase 08 train-only normalization once. Training reads only train/val
  archives; verify disjoint participant rosters including the reserved test roster,
  fold/session/schema provenance and archive hashes. No normalization refit.
- Three distinct seeds per model/fold cell. Development seeds: 10,11,12, five
  epochs, hidden size 12, Adam lr .001, clipping 1, batch 64, one CPU thread.
  These are fixture settings, not tuned participant hyperparameters. Candidate
  loss options L1/MSE/Huber; default Huber, uniform step weights, no velocity term,
  uniform shuffled samples. Optional near/far weighting and recorded oversampling.
- Early stopping: lowest participant-macro validation ADE, strict improvement,
  patience recorded in each manifest. This differs from the training Huber loss
  but is not an event-level utility score. Family/horizon/operating-point selection
  must subsequently use the event constraints, not this checkpoint criterion alone.
- Report fixed-horizon FDE only on sequences observed at step K; report support
  counts and per-step errors. ADE targets the noisy future causal tracker, not the
  physical tip or smoothed reference trajectory.

## Selection rule and fields requiring owner/validation evidence

| Field | Status |
|---|---|
| Dataset / labels / splits | PENDING ds-v1.0 reviewed and frozen; labels-v1.0 |
| Phase 09 frozen harness and primary matching W | PENDING Phase 09 gate |
| FP/min budget | PENDING owner choice justified by Baseline A and playability |
| FN-rate ceiling | PENDING validation protocol/owner |
| Timing-error MAE bound | PENDING audio-timing tolerance rationale |
| CPU inference p95 ceiling | PENDING development CPU budget |
| Minimum meaningful lead/difference | PENDING owner/stakeholder interpretation |
| Measured stage-delay composition and source hashes | PENDING complete applicable stage evidence |
| H/N/family/seed aggregation and final fit recipe | PENDING CV comparison |
| Per-arm frozen operating points | PENDING validation selection |

On validation participants only, maximize participant-macro median prediction lead
among achieved operating points satisfying **all** FP, FN, timing and CPU bounds.
Tie-break by lower FP, lower timing MAE, lower p95 inference cost, then canonical
settings JSON. The rule accepts A/B/C-GBDT as well as temporal arms and may choose
a simpler arm. If no arm is feasible, report that outcome; do not relax bounds
after viewing held-out data. If selected lead is nonpositive, report no useful
positive lead. Material superiority additionally needs the predeclared difference
threshold and participant uncertainty; a positive fixture number proves nothing.

Control candidates: tau_commit={.02,.05,.10}s, auxiliary p={.3,.7} where trained,
n_confirm={0,2}, inward crossing-speed floor={.15,.30} ROI/s,
zone refractory={.10,.20}s. Each control is varied around a recorded reference
point; these are candidates, not playability recommendations. Pure trajectory
carries probability null. An auxiliary probability only gates a geometry-derived
candidate through unchanged Phase 05. Commit tracking gate remains VALID by default.

## Comparability and uncertainty

Use identical participant partitions, W, geometry, commit implementation, active
time denominators, recording condition and delay policy for all arms. Include
Baseline A, B CV/CA, and C-GBDT direct/trajectory. Use fixed-grid target-only
conversion for the GBDT trajectory comparison to avoid unequal time horizons.
Preserve original archive hashes and the conversion procedure. Report all
per-participant metrics, seed variance, parameter/storage cost, impact-position
and crossing-speed agreement; bootstrap participants, never frames or seeds as
independent people. Synthetic grouping CIs are diagnostics only.

Replay stamps t_commit=t_capture+Delta_proc. Show zero-delay diagnostics separately
from the policy containing measured capture/tracking/features/model stages with
explicit inclusions/exclusions; never infer missing stage costs from inference
alone. Useful lead is limited by H-Delta_proc. The development sweep uses zero delay
because it cannot freeze a participant processing-delay policy.

Frozen Phase 09 TE_pred is predicted impact minus GT impact: positive means a later
predicted impact. It does not mean that sound was early. L_pred is GT impact minus
commit time. No physical sound/latency claim follows from either offline quantity.

## Held-out access and reproducibility

Before Task 10.13: reviewer checks all upstream gates, completed budget values,
CV-derived selection, final training recipe, every arm's model/config hashes,
dataset/split/norm/harness hashes and the archived pre-registration timestamp.
Create one immutable experiment ledger entry for each predeclared operating point
before execution; reserve it even on failure, with failures reviewed before retry.
Do not run a parameter sweep on held-out participants. Additional analyses must
be labelled exploratory, with no retuning represented as confirmation.

The current eval_temporal CLI refuses `--partition test` before opening model/data
files. The confirmatory runner and immutable ledger remain PENDING until the
actual frozen protocol exists; there is no placeholder test result. Export reload
and metric comparison at atol=1e-6/rtol=1e-5 are development reproduction. VALIDATED
requires a second person or clean environment, plus the selected participant model.

## Outcome-neutral report

Report exactly the supported outcome: temporal model better, no material
difference, or baseline better. Preserve sparse-positive denominators and CIs.
Do not declare a winner, useful participant lead, or effective latency reduction
from development fixtures. The latter requires Phase 18 live measurements.
