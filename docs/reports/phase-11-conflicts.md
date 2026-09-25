# Phase 11 task-conflict diagnostics (Task 11.3)

Status: IMPLEMENTED and executed on a SYNTHETIC fixture; participant diagnostics PENDING.
SYNTHETIC DEVELOPMENT values only (dirty tree, HEAD `bd0bcf8`).

## Method

`mt_train.train_mt_fold(..., conflict_every=5)` samples every fifth training step. For each task
labelled in that batch it computes the unweighted task gradient on all shared encoder parameters
(everything except `head.*`) and its cosine with the trajectory-loss gradient, plus the norm
ratio and current task weight (`conflicts.json` per model). Sampling reuses the step's graph and
does not change training; tested bit-for-bit (`test_conflict_sampling_is_read_only`).

The equal-budget comparison uses the same data, epochs, encoder size and seeds as the
trajectory-only model (bit-identical to the Phase 10 single-task model). A head "degrades beyond
seed variance" when its mean paired change (same fold, seed and family) exceeds 2 × the pooled
within-fold seed SD of trajectory-only. The rule was declared in `plan.json` before training.

## Gradient cosine with the trajectory task (1,236 sampled steps per variant/family)

Run `experiments/phase-11/20260925-0913-synthetic-weighting` (all six heads per variant):

| Variant | Family | Strike | TTI | Zone | Position | Intensity |
|---|---|---:|---:|---:|---:|---:|
| fixed-1.0 | GRU | −0.002 (0.50) | 0.006 (0.49) | −0.053 (0.58) | 0.110 (0.28) | −0.032 (0.58) |
| fixed-1.0 | TCN | −0.049 (0.59) | 0.100 (0.33) | −0.070 (0.62) | 0.113 (0.29) | 0.023 (0.45) |
| dominant-0.05 | GRU | −0.061 (0.63) | −0.046 (0.61) | −0.162 (0.76) | 0.101 (0.27) | −0.038 (0.59) |
| dominant-0.05 | TCN | −0.051 (0.60) | −0.002 (0.48) | −0.127 (0.66) | 0.129 (0.30) | 0.000 (0.50) |
| uncertainty | GRU | 0.003 (0.49) | 0.008 (0.49) | −0.055 (0.58) | 0.115 (0.28) | −0.033 (0.58) |
| uncertainty | TCN | −0.044 (0.57) | 0.095 (0.33) | −0.070 (0.61) | 0.104 (0.30) | 0.027 (0.46) |
| gradnorm | GRU | −0.016 (0.56) | 0.065 (0.35) | −0.052 (0.59) | 0.137 (0.23) | −0.007 (0.53) |
| gradnorm | TCN | −0.036 (0.56) | 0.068 (0.32) | −0.089 (0.66) | 0.138 (0.26) | 0.037 (0.42) |

Mean cosine (fraction of sampled steps with a negative cosine). Fixed-0.3 follows the same
pattern; per-step values, p10/p90 and weights are in each run's `summary.json` and `conflicts.json`.
Reading: the **zone** head's gradient opposes the trajectory in most steps for every scheme,
and more under trajectory-dominant weighting. **Position** is the only head consistently aligned
with the trajectory (positive in ~70–77 % of steps). Strike, TTI and intensity are close to
orthogonal. Near-orthogonal, noisy cosines are expected for small linear heads and do not by
themselves prove harm.

## Equal-budget comparison with the single-task model (all-heads variants)

Paired Δ = variant − traj-only; flag per the declared rule.

| Variant | Family | ΔADE | Seed SD (traj-only) | ADE | ΔFDE | FDE | Δ dev FP/min | FP |
|---|---|---:|---:|---|---:|---|---:|---|
| fixed-1.0 | GRU | +0.0270 | 0.0058 | degrades | +0.0356 | degrades | +4.2 | within |
| fixed-1.0 | TCN | +0.1135 | 0.0022 | degrades | +0.1178 | degrades | +55.5 | degrades |
| fixed-0.3 | GRU | +0.0357 | 0.0058 | degrades | +0.0405 | degrades | +11.8 | within |
| fixed-0.3 | TCN | +0.0769 | 0.0022 | degrades | +0.0776 | degrades | +62.5 | degrades |
| dominant-0.05 | GRU | +0.0217 | 0.0058 | degrades | +0.0209 | degrades | +7.0 | within |
| dominant-0.05 | TCN | +0.0344 | 0.0022 | degrades | +0.0337 | degrades | +16.0 | within |
| uncertainty | GRU | +0.0248 | 0.0058 | degrades | +0.0335 | degrades | +4.6 | within |
| uncertainty | TCN | +0.1098 | 0.0022 | degrades | +0.1113 | degrades | +60.4 | degrades |
| gradnorm | GRU | +0.0555 | 0.0058 | degrades | +0.0646 | degrades | +21.8 | degrades |
| gradnorm | TCN | +0.0798 | 0.0022 | degrades | +0.0826 | degrades | +66.3 | degrades |

"Dev FP/min" is the FP rate at each cell's development-budget pick (n=12 pairs). Lead at the
development budget has too few feasible pairs for a paired statement. Equal-τ harness rows are
in `phase-11-weighting.md`.

## Per-head attribution (single-head ablation)

Run `experiments/phase-11/20260925-0949-synthetic-ablation` trains the trajectory head plus
**one** auxiliary head at a time (`dominant-0.05` weighting, same folds/seeds). This attributes
conflict and cost to single heads:

| Head added | Family | Mean cos (fraction < 0) | ΔADE vs traj-only | ΔFDE | Flag (ADE / FDE) |
|---|---|---:|---:|---:|---|
| strike | GRU | −0.091 (0.67) | +0.0038 | +0.0020 | within / within |
| strike | TCN | −0.071 (0.51) | +0.0128 | +0.0130 | degrades / degrades |
| TTI | GRU | −0.016 (0.54) | +0.0021 | +0.0020 | within / within |
| TTI | TCN | +0.063 (0.40) | +0.0037 | +0.0043 | within / within |
| zone | GRU | −0.189 (0.83) | +0.0167 | +0.0151 | degrades / degrades |
| zone | TCN | −0.108 (0.61) | +0.0232 | +0.0183 | degrades / degrades |
| position | GRU | +0.035 (0.42) | +0.0030 | +0.0046 | within / within |
| position | TCN | +0.126 (0.32) | +0.0056 | +0.0072 | degrades / within |
| intensity | GRU | −0.061 (0.64) | +0.0085 | +0.0083 | within / within |
| intensity | TCN | −0.009 (0.50) | +0.0124 | +0.0119 | degrades / degrades |

Pooled traj-only seed SD: 0.0058 (GRU), 0.0022 (TCN). None of the single heads changed the
development-budget lead or FP/min beyond seed variance (`summary.json`).

**Flagged heads** (degrade a primary metric beyond seed variance): zone (both families); strike,
position and intensity (TCN only). The TTI head is the only one within seed variance in both
families. The most negative cosine belongs to the zone head, which also costs the most
trajectory accuracy, so the diagnostic and the outcome agree on this fixture. Under the
pre-registered rule, flagged heads would be excluded from a ship candidate unless a gate needs
them.

## Limitations

Cosines on the shared encoder only, sampled every fifth step; linear heads; one fixture.
Conflict statistics describe optimisation on this fixture, not participant motion.
