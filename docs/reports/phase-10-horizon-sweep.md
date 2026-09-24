# Phase 10 horizon sweep

Status: PENDING participant CV experiment; synthetic development sweep executed.
Date: 2026-09-24 (+03:00). Hardware HW-01; CPU identity, power/environment and
source hashes are in the run manifests. Evidence class: SYNTHETIC DEVELOPMENT,
not participant MEASURED or VALIDATED evidence.

Run: `experiments/phase-10/20260924-1926-synthetic-horizon/run.json`.
The 54 configurations cover GRU/TCN, K=1/2/4, three fixture folds and seeds
10/11/12, at candidate N=8 and dt_step=1/30s. All models used five development
training epochs, hidden size 12, uniform sampling, Huber loss, lambda_aux=0,
one inference thread. There are 648 candidate operating-point replay evaluations.
No held-out participant or synthetic test archive was read by training.

Each model directory contains its manifest, checkpoint, TorchScript export,
training curves, validation metrics, all-sample batch-1/batch-31 parity, raw CPU
timings, metric-reload reproduction, and per-point Phase 09 replay event tables.
All 54 export parity reports passed atol=1e-6/rtol=1e-5. ADE/FDE are ROI-normalized
errors against the future causal-track fixture, not physical tip accuracy.
FDE uses the final fixed-grid point only; per-step support is retained.

## Development diagnostic table (no research winner)

Means below average the nine fold/seed diagnostics in each cell. Latency ranges
span those models' measured development p95 values. They are not confidence
intervals. Other repository checks ran during development timing; this is not an
isolated deployment benchmark or an approved CPU operating budget.

| Family | K | Candidate H (ms) | Mean ADE | Mean FDE | p95 CPU range (ms) |
|---|---:|---:|---:|---:|---:|
| GRU | 1 | 33.33 | 0.12493 | 0.12493 | 1.710–4.462 |
| GRU | 2 | 66.67 | 0.10570 | 0.10154 | 1.117–3.433 |
| GRU | 4 | 133.33 | 0.17314 | 0.16776 | 1.265–3.746 |
| TCN | 1 | 33.33 | 0.10061 | 0.10061 | 0.548–2.544 |
| TCN | 2 | 66.67 | 0.12205 | 0.10830 | 0.537–1.105 |
| TCN | 4 | 133.33 | 0.10033 | 0.15401 | 0.652–1.945 |

Full lead/FP/FN/timing/zone/intensity/impact-position results are in `curves.json`
and each model's replay `results.json`; per-step trajectory errors, counts and
fixture-identity values are in `validation.json`. `lead-vs-fp.png` plots achieved
points without inventing interpolation. Zero matched points retain null lead and
are not treated as useful predictions. `comparison.json` exercises grouping-key
bootstrap after seed averaging; those keys are not real participants.

Prediction lead uses the frozen Phase 09 formula with zero-delay diagnostics and
candidate W=.05s. W is not frozen for participants. Measured full stage-delay
policy results remain PENDING; inference timing alone cannot replace Delta_proc.

Horizon selection remains PENDING: the synthetic fixture cannot justify an FP
budget, timing/CPU bounds, or which horizon offers useful participant lead.
See ADR-0026 and phase-10-prereg.md. No test-participant run occurred.

## Bounded GRU state cost

DEVELOPMENT diagnostic from the same completed run: across 27 GRU models, the
median ratio of bounded-cache p50 to windowed p50 was 1.68989. Cache counters
recorded 1,890 rebuilds (including warmup), with zero incremental reuse steps.
The Phase 08 window_elapsed feature changes overlapping rows as the window moves,
so the exact-parity cache cannot reuse those states. These timings include the
development contention noted above and are not participant latency estimates.
No O(1) carried-state speedup is claimed. The recorded-sequence parity result is
independent evidence that the bounded implementation agrees within tolerance.
