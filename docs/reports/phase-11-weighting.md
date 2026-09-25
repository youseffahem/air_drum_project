# Phase 11 loss-weighting comparison (Task 11.2)

Status: IMPLEMENTED and executed on a SYNTHETIC fixture; participant comparison PENDING.
Every number below is a SYNTHETIC DEVELOPMENT diagnostic, run while the tree was dirty
(`git_dirty: true`, HEAD `bd0bcf8`). None selects a weighting for the thesis.

## Run

`experiments/phase-11/20260925-0913-synthetic-weighting/run.json` — COMPLETED
2026-09-25 09:47:55 +03:00, 144 models, 432 replay evaluations, 2,632 hashed artifacts.
`plan.json` records every cell; `summary.json`, `curves.json` and `results.json` hold all values.

- Fixture: `scripts/_p11_fixture.py`, five scripted identities × 24 s at a candidate 30 Hz
  frame grid (not a camera measurement). POSITIVE labels are every valid Phase 04 crossing
  of the noiseless path; feints are `NEG_STOP_BEFORE_IMPACT`, dropouts `NEG_TRACKING_LOSS`.
  Split rule `P07-SPLIT-1` held out `SYNTHETIC-K0` (never opened) and built four folds with one
  validation identity each.
- Windows: N=8, K=4 at dt=1/30 s (H=0.133 s), H_max=0.3 s, stride 1 (candidate values).
- Encoders: GRU and TCN, hidden 16, Adam 1e-3, batch 64, 8 epochs, patience 8, seeds 10/11/12,
  one CPU thread; checkpoint by participant-macro validation ADE (Phase 10 criterion).
- Variants: `traj-only` (bit-identical to the Phase 10 single-task model) and all six heads with
  fixed λ=1, fixed auxiliary λ=0.3, trajectory-dominant (aux λ=0.05), uncertainty and GradNorm
  (α=1.5). Heads are linear; TTI direct.
- Harness: unchanged geometry/commit/metrics, candidate W=0.05 s, zero delay, τ_commit ∈
  {0.02, 0.05, 0.10} s with v_min 0.15, no confirmation frames, zone refractory 0.10 s, all
  aux-head gates off. The development budget (FP ≤ 30/min, FN ≤ 0.6) is a synthetic constant
  set after a three-cell calibration; it is not ADR-0025.

Labelled windows per fold (train / validation): 4,081–4,085 / 1,359–1,363 samples;
strike positives 937–984 / 286–333; impact-labelled (TTI/zone/position/intensity) rows
2,039–2,102 / 641–704. Validation zone counts are unbalanced (e.g. fold 0: hihat 143, snare 316,
tom1 207, crash_ride 38). Exact counts per fold are in each model's `manifest.json`.

## Per-variant results (mean ± SD over 4 folds × 3 seeds)

| Variant | Family | ADE | FDE | Strike AP | TTI MAE (ms) | Zone acc. | Pos. median | Int. MAE | Int. ρ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| traj-only | GRU | 0.0624 ± 0.0065 | 0.0851 ± 0.0072 | — | — | — | — | — | — |
| fixed-1.0 | GRU | 0.0894 ± 0.0068 | 0.1207 ± 0.0121 | 0.705 ± 0.073 | 47.5 ± 4.6 | 0.924 ± 0.012 | 0.0472 ± 0.0084 | 0.423 ± 0.114 | 0.259 ± 0.135 |
| fixed-0.3 | GRU | 0.0981 ± 0.0069 | 0.1256 ± 0.0109 | 0.677 ± 0.078 | 48.3 ± 5.3 | 0.924 ± 0.014 | 0.0524 ± 0.0074 | 0.425 ± 0.116 | 0.220 ± 0.153 |
| dominant-0.05 | GRU | 0.0841 ± 0.0067 | 0.1060 ± 0.0096 | 0.619 ± 0.070 | 51.7 ± 5.7 | 0.927 ± 0.010 | 0.0499 ± 0.0055 | 0.422 ± 0.116 | 0.208 ± 0.134 |
| uncertainty | GRU | 0.0872 ± 0.0069 | 0.1186 ± 0.0124 | 0.711 ± 0.071 | 47.3 ± 4.7 | 0.925 ± 0.012 | 0.0471 ± 0.0090 | 0.422 ± 0.113 | 0.262 ± 0.135 |
| gradnorm | GRU | 0.1179 ± 0.0135 | 0.1497 ± 0.0187 | 0.752 ± 0.068 | 48.2 ± 5.6 | 0.900 ± 0.030 | 0.0577 ± 0.0079 | 0.427 ± 0.128 | 0.318 ± 0.140 |
| traj-only | TCN | 0.0452 ± 0.0050 | 0.0696 ± 0.0066 | — | — | — | — | — | — |
| fixed-1.0 | TCN | 0.1587 ± 0.0142 | 0.1875 ± 0.0254 | 0.724 ± 0.105 | 49.9 ± 8.2 | 0.927 ± 0.014 | 0.0774 ± 0.0140 | 0.451 ± 0.126 | 0.243 ± 0.192 |
| fixed-0.3 | TCN | 0.1221 ± 0.0157 | 0.1473 ± 0.0238 | 0.744 ± 0.086 | 51.2 ± 8.2 | 0.930 ± 0.009 | 0.0726 ± 0.0135 | 0.450 ± 0.135 | 0.260 ± 0.198 |
| dominant-0.05 | TCN | 0.0796 ± 0.0084 | 0.1033 ± 0.0107 | 0.779 ± 0.067 | 54.1 ± 10.7 | 0.930 ± 0.012 | 0.0589 ± 0.0074 | 0.437 ± 0.139 | 0.244 ± 0.167 |
| uncertainty | TCN | 0.1550 ± 0.0168 | 0.1809 ± 0.0272 | 0.720 ± 0.107 | 48.8 ± 6.8 | 0.926 ± 0.017 | 0.0734 ± 0.0101 | 0.436 ± 0.126 | 0.240 ± 0.175 |
| gradnorm | TCN | 0.1250 ± 0.0233 | 0.1523 ± 0.0315 | 0.766 ± 0.071 | 48.6 ± 7.0 | 0.919 ± 0.021 | 0.1008 ± 0.0184 | 0.439 ± 0.144 | 0.308 ± 0.199 |

ADE/FDE/position are ROI-normalised; intensity is the rule-R2 proxy in ROI units/s (not force).
Frame-level head metrics use labelled validation rows only (strike: `strike_mask`; others:
an impact within H_max).

## Harness at equal τ_commit (mean over 12 cells; ~84 labelled impacts per validation identity)

| Variant | Family | τ (s) | Matched | Median lead (ms) | FP/min | FN rate | Timing MAE (ms) |
|---|---|---:|---:|---:|---:|---:|---:|
| traj-only | GRU | 0.02 / 0.05 / 0.10 | 18.4 / 39.2 / 40.0 | 6.8 / 11.5 / 18.0 | 11.4 / 31.9 / 112.3 | 0.781 / 0.536 / 0.525 | 5.2 / 16.2 / 31.5 |
| fixed-1.0 | GRU | 0.02 / 0.05 / 0.10 | 28.1 / 51.8 / 43.5 | 7.7 / 16.1 / 24.7 | 16.0 / 69.6 / 204.4 | 0.667 / 0.387 / 0.484 | 5.5 / 14.9 / 29.7 |
| dominant-0.05 | GRU | 0.02 / 0.05 / 0.10 | 18.2 / 38.2 / 44.1 | 7.3 / 11.2 / 21.9 | 17.7 / 58.7 / 208.7 | 0.781 / 0.545 / 0.476 | 5.9 / 19.0 / 35.2 |
| uncertainty | GRU | 0.02 / 0.05 / 0.10 | 28.7 / 52.0 / 42.5 | 7.8 / 17.0 / 24.4 | 16.7 / 68.4 / 198.4 | 0.659 / 0.383 / 0.495 | 5.4 / 14.6 / 28.0 |
| traj-only | TCN | 0.02 / 0.05 / 0.10 | 33.6 / 57.0 / 28.3 | 7.0 / 18.5 / 25.3 | 0.6 / 19.0 / 144.2 | 0.606 / 0.329 / 0.664 | 4.1 / 8.4 / 15.4 |
| dominant-0.05 | TCN | 0.02 / 0.05 / 0.10 | 38.1 / 54.0 / 33.1 | 13.9 / 21.0 / 25.8 | 22.4 / 80.9 / 224.1 | 0.546 / 0.358 / 0.606 | 7.4 / 14.1 / 24.5 |
| fixed-1.0 | TCN | 0.02 / 0.05 / 0.10 | 22.8 / 36.2 / 38.2 | 16.5 / 15.9 / 14.7 | 61.9 / 196.5 / 394.2 | 0.731 / 0.566 / 0.544 | 11.4 / 21.0 / 38.2 |

Fixed-0.3 and GradNorm follow the same pattern (all rows in `curves.json`; the full table,
including the zone accuracy of matched strikes, is reproducible from it). Leads are bounded by W
and the fixed H; positive fixture lead is not a latency claim.

## Development choice and outcome

The rule `experiments/phase-11/weighting-choice-rule.json` was declared at 09:26 +03:00, while
the run had finished 74 of 144 cells and before any summary existed. Applied mechanically by
`scripts/_p11_grid.py::choose_weighting`: **every multi-task scheme degraded ADE beyond seed
variance for both families** (paired Δ, next section), so step 4 chose the smallest mean ADE
degradation, `dominant-0.05`. It parameterises the development head ablation only.

On this fixture, multi-task training **worsened** the primary trajectory objective under every
scheme, and at equal τ it raised FP/min, in the TCN strongly. For the GRU, λ=1/uncertainty
matched more impacts at τ=0.05 s (FN 0.39 versus 0.54) at roughly twice the FP/min: a trade-off
on the curve, not a dominance. The development budget was met by traj-only in 13/24 cells,
by dominant-0.05 in 9/24, by fixed-1.0 and uncertainty in 4/24 each, and never by fixed-0.3
or GradNorm. Frame-level head quality was similar across schemes; GradNorm gave the highest
intensity ρ in both families and the highest GRU strike AP, but the worst GRU trajectory. Outcome-neutral reading: on this synthetic
fixture multi-task supervision is **worse** for the trajectory route. Real participant motion
may differ, so the participant comparison remains PENDING.

## Limitations

Single scripted fixture; five identities; eight epochs; one hidden size; linear heads; direct TTI
(log/bins compared separately in `phase-11-per-task.md`); no hyper-parameter search per scheme. The
development FP budget and zero-delay replay are synthetic conventions. Grid latency was measured
with three parallel workers and is not used here (see `phase-11-latency.md`).
