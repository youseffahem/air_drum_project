# Phase 12 E2 — richer trajectory representations (Task 12.4)

Status: IMPLEMENTED and executed on the SYNTHETIC fixture; participant CV go/no-go PENDING.
Every value is a SYNTHETIC DEVELOPMENT diagnostic (dirty tree, HEAD `91351f5`). **Nothing is
adopted.** ADR-0032.

## Runs and method

`experiments/phase-12/20260926-0550-synthetic-e2` trains `e2-vel`, `e2-poly` and `e2-mix2` (72 cells)
and evaluates rule M2 (`e2-mix2-agg`) on the 24 mixture cells. Reference, CPU and rule runs as in the
E4 report (`lead-vs-fp-e2.png`, `reliability.png`). Development settings and budget as declared; M1
variants use the τ grid only, M2 adds `p_commit` ∈ {0, 0.3, 0.5, 0.7} on the aggregated crossing
probability (the modes as weighted trajectories through the unchanged impact test).

## Results (development; mean ± SD over 12 cells per family)

| Variant | Family | ADE | Paired ΔADE | Feasible | Lead ms | FP/min | FN | TE MAE ms | Paired Δlead ms (n) | Paired ΔTE ms | CPU ratio | Development verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| reference | GRU | 0.0624 ± 0.0065 | — | 2/12 | 14.5 | 17.7 | 0.440 | 9.2 | — | — | 1.00 | — |
| reference | TCN | 0.0452 ± 0.0050 | — | 11/12 | 13.4 | 6.9 | 0.398 | 6.4 | — | — | 1.00 | — |
| `e2-vel` | GRU | 0.0651 ± 0.0059 | +0.0028 | 6/12 | 11.8 | 13.1 | 0.515 | 12.2 | +2.4 (2) | +0.2 | 1.06 | NO-GO (insufficient evidence) |
| `e2-vel` | TCN | 0.0486 ± 0.0051 | +0.0034 | 9/12 | 10.7 | 5.9 | 0.523 | 6.7 | −3.6 (8) | +0.1 | 0.98 | NO-GO |
| `e2-poly` | GRU | 0.0557 ± 0.0057 | −0.0067 | 7/12 | 13.2 | 9.8 | 0.476 | 14.3 | −4.9 (2) | +13.7 | 1.10 | NO-GO (insufficient evidence) |
| `e2-poly` | TCN | 0.0431 ± 0.0047 | −0.0021 | 10/12 | 16.5 | 10.7 | 0.371 | 9.0 | +3.2 (10) | +2.6 | 1.07 | NO-GO |
| `e2-mix2` (M1) | GRU | 0.0831 ± 0.0114 | +0.0208 | 1/12 | 8.8 | 10.2 | 0.540 | 4.2 | −5.8 (1) | −6.5 | 1.18 | NO-GO (insufficient evidence) |
| `e2-mix2` (M1) | TCN | 0.0919 ± 0.0100 | +0.0467 | 3/12 | 6.9 | 26.2 | 0.312 | 25.0 | −5.3 (3) | +18.1 | 1.18 | NO-GO |
| `e2-mix2-agg` (M2) | GRU | same models | — | 2/12 | 11.3 | 19.1 | 0.351 | 13.3 | −5.8 (1) | −6.5 | 1.53 | NO-GO (insufficient evidence) |
| `e2-mix2-agg` (M2) | TCN | same models | — | 3/12 | 6.9 | 26.2 | 0.312 | 25.0 | −5.3 (3) | +18.1 | 1.47 | NO-GO |

Seed-variance band: TCN 9.6 ms (lead), 5.1 ms (TE); GRU undefined (reference feasible in 2/12 cells).
Mixture diagnostics (reported, never deciding): best-of-M / most-probable ADE 0.0771 / 0.0829 (GRU)
and 0.0887 / 0.0916 (TCN). One mode took more than 95 % of the validation windows in 8/12 GRU and
11/12 TCN cells (median minority-mode share 0.007 and 0.000).

## Reading (fixture only)

- **Polynomial coefficients** (a smoothness prior over the horizon) gave the lowest trajectory error
  of any declared variant (paired ADE −0.0067 GRU, −0.0021 TCN) and more feasible GRU cells (7/12 vs
  2/12). The TCN lead gain (+3.2 ms) stays inside the seed band, and the GRU timing error grew. On
  this fixture a better trajectory did not become a rule-level lead gain, the phase's anticipated
  failure mode ("improves ADE but not lead time/FP → not adopted").
- **Velocity integration** slightly increased trajectory error; no lead gain.
- **The two-mode mixture collapsed** to one mode in most cells under the declared relaxed
  winner-takes-all setting and budget (8 epochs, ε 0.05). Its point trajectory was worse than the
  reference, and rule M2 could not help. The fixture's feints are rare (12–22 % of strokes), so a
  second mode has little data to specialise on, and the collapse may reflect the data as much as the
  loss. Anti-collapse measures (a mode-balance term, longer training) would be new declared
  candidates.
- CPU cost: the representation heads cost 1.0–1.2 × the reference path; M2's two-sample propagation
  costs about 1.5 ×.

## Participant-stage plan (PENDING)

E2 runs after E4/E5 (entry decision). If rule M2 were ever adopted, the development `mixture_xy`
layout must be replaced by a `modes` contract field (schema bump + ADR, ADR-0032).

## Limitations

As in the E4 report. Additionally, mode collapse makes the mixture comparison mostly a comparison of
a worse point predictor; it does not test multi-modality as such.
