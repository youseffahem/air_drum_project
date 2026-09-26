# Phase 12 E4 — uncertainty estimation and the crossing-probability gate (Task 12.6)

Status: IMPLEMENTED and executed on the SYNTHETIC fixture; participant CV go/no-go PENDING.
Every value is a SYNTHETIC DEVELOPMENT diagnostic (dirty tree, HEAD `91351f5`). **Nothing is
adopted**; the development verdicts only check the machinery. ADR-0034.

## Runs and method

| Run | Content |
|---|---|
| `experiments/phase-12/20260926-0528-synthetic-ref` | reference: Phase 10 trajectory-only GRU/TCN, 4 folds × 3 seeds (bit-identical to the Phase 11 `traj-only` cells, 24/24 checkpoints) |
| `experiments/phase-12/20260926-0533-synthetic-e4` | `e4-gauss` (24 trained cells) and `e4-ens3` (8 per-fold seed ensembles of the reference) |
| `experiments/phase-12/20260926-0547-exploratory-e4-posthoc` | **EXPLORATORY**, not pre-declared: `x-e4-posthoc`, see below |
| `experiments/phase-12/20260926-0624-ext-latency-memory` | isolated CPU path latency and working set |
| `experiments/phase-12/20260926-0629-synthetic-go-no-go` | the pre-declared rule applied mechanically, figures `lead-vs-fp-e4.png`, `reliability.png` |

Settings are the declared development settings (entry decision): the Phase 11 kinematic fixture, 5
identities, `P07-SPLIT-1`, N = 8, K = 4, width 16, 8 epochs, seeds 10/11/12, W 0.05 s candidate,
zero delay. Crossing probability: S = 32 antithetic common random numbers (seed 1212), shared
across steps, through the unchanged Phase 04 impact test. The candidate zone's probability
relabels `strike_probability`; the unchanged `p_commit` ∈ {0, 0.3, 0.5, 0.7} gates it, crossed with
τ_commit ∈ {0.02, 0.05, 0.10, 0.15, 0.20} s. Development budget: FP ≤ 30/min, FN ≤ 0.6
(Phase 11 SYNTHETIC constants). Calibration: the crossing probability over all zones against
`strike_within_H` on `strike_mask` windows.

## Results (development; mean ± SD over cells; lead/FP/FN/TE over budget-feasible cells)

| Variant | Family | ADE | Feasible cells | Lead ms | FP/min | FN | TE MAE ms | ECE | Brier | ROC-AUC | CPU path p95 / reference |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| reference (0/1 indicator) | GRU | 0.0624 ± 0.0065 | 2/12 | 14.5 ± 0.3 | 17.7 | 0.440 | 9.2 | 0.197 | 0.197 | 0.661 | 1.00 |
| reference (0/1 indicator) | TCN | 0.0452 ± 0.0050 | 11/12 | 13.4 ± 4.4 | 6.9 | 0.398 | 6.4 | 0.134 | 0.134 | 0.762 | 1.00 |
| `e4-gauss` | GRU | 0.0921 ± 0.0087 | 0/12 | — | — | — | — | 0.123 | 0.193 | 0.591 | 2.93 |
| `e4-gauss` | TCN | 0.1248 ± 0.0106 | 1/12 | 13.2 | 25.4 | 0.517 | 6.7 | 0.122 | 0.193 | 0.563 | 3.55 |
| `e4-ens3` | GRU | 0.0537 ± 0.0035 | 4/4 folds | 10.6 ± 2.2 | 13.9 | 0.530 | 12.9 | 0.117 | 0.149 | 0.745 | 2.55 |
| `e4-ens3` | TCN | 0.0409 ± 0.0044 | 4/4 folds | 15.0 ± 7.9 | 6.4 | 0.407 | 6.5 | 0.100 | 0.109 | 0.828 | 2.70 |
| *`x-e4-posthoc` (exploratory)* | GRU | 0.0624 (= ref) | 5/12 | 12.6 ± 2.3 | 20.8 | 0.529 | 13.7 | 0.072 | 0.130 | 0.852 | 2.48 |
| *`x-e4-posthoc` (exploratory)* | TCN | 0.0452 (= ref) | 11/12 | 16.0 ± 5.3 | 10.8 | 0.364 | 6.9 | 0.063 | 0.094 | 0.924 | 3.46 |

Development verdicts under the pre-declared rule (`phase-12-summary.md` has the full table):
`e4-gauss` NO-GO for both families (GRU: insufficient evidence; TCN: feasibility, lead and CPU
fail, 3.55 × the reference path > F = 3). `e4-ens3` NO-GO. For TCN, the paired lead difference
against the per-fold reference seed mean is +1.6 ms (n = 4), below the 9.6 ms seed-variance band.
The timing difference is 0.0 ms and CPU 2.70 ×; GRU has insufficient evidence (reference band
undefined). The exploratory variant is outside the rule by construction.

Gate effect (reported only; same curve with and without `p_commit > 0` points): `e4-ens3` chose a
gated point in 0/4 GRU and 2/4 TCN folds (+0.8 ms mean where both feasible). The exploratory
post-hoc head chose a gated point in 5/5 feasible GRU cells: gating made 5/12 GRU cells
budget-feasible against 2/12 without it. It also chose a gated point in 5/11 TCN cells, raising the
TCN mean lead from 13.4 to 16.0 ms at equal feasibility (11/12).

## Reading (fixture only)

- **The declared E4(a) coupling failed on this fixture.** Fitting log σ by NLL through the shared
  encoder degraded the mean trajectory (ADE +48 % GRU, +176 % TCN), so the variant rarely met the
  development budget, whatever the gate did. A likely cause is the gradient scale. log σ starts
  near 0 (σ ≈ 1 ROI) while the per-step residual RMS is about 0.03–0.08 ROI (log ≈ −3.6 to −2.6 in
  the exploratory fit), so the NLL gradients are O(1) against O(10⁻²) Huber gradients on small
  displacements. They
  dominate the shared encoder and, through global gradient clipping, the whole update. The
  exploratory run below supports this reading; it does not prove it.
- **The seed ensemble** lowered trajectory error (ADE −14 % GRU, −10 % TCN) and was feasible in
  every fold, with better calibration than the reference indicator (TCN AUC 0.83 vs 0.76). Its lead
  gain did not exceed the seed-variance band, and it costs about 2.6–2.7 × the reference path (three
  forward passes plus propagation).
- **The exploratory post-hoc variance head** keeps the reference mean exactly (every gate-off pick
  reproduces the reference's development pick). It is the best-calibrated of all (TCN ECE 0.063,
  AUC 0.92). On this fixture the crossing-probability gate then moved operating points inside the
  FP budget, which is the E4 mechanism the phase asked about. Its TCN path, like `e4-gauss`, exceeds
  the declared CPU factor (3.46 ×) at S = 32. Fewer samples or an analytic approximation would be
  new declared candidates, not a post-hoc change.
- With few positives per fold, calibration bins at high probability hold few windows (see
  `reliability.png`); the ECE values are coarse.

## Exploratory diagnostic (not pre-declared)

`scripts/explore_posthoc_sigma.py` was written after the `e4-gauss` result was seen. It freezes
each reference model and fits only a linear log-σ head on the detached encoder state: bias
initialised at the log RMS training residual per step and axis, weights zero, Gaussian NLL, Adam
1e-2, 20 epochs, checkpoint by validation NLL. Packages are exported and replayed exactly like the
declared variants. It never enters the go/no-go table. It may only inform the participant-stage
pre-registration: the submitter proposes declaring this post-hoc head as **E4(a′)** before
participant CV (owner decision), keeping `e4-gauss` as declared.

## Participant-stage plan (PENDING)

Participant CV (after ds-v1.0, the Phase 09/10 gates and owner budgets) runs `e4-ens3` and, if the
owner declares it, E4(a′), against the selected reference with participant-macro aggregation of
the operating points across each fold's validation participants. That aggregation is not
implemented yet: the development pick takes one fold's single validation identity. Calibration
is reported per participant.

## Limitations

One scripted fixture with vertical strokes and one validation identity per fold; the GRU reference
has too few feasible cells to define its seed band, so every GRU comparison is "insufficient
evidence"; development budgets are synthetic constants; S = 32 Monte-Carlo samples add sampling
noise to probabilities near a surface; latency is development compute on HW-01 on a dirty tree;
no participant, DEV CAPTURE or physical-pad data.
