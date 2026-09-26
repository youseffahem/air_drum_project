# Phase 12 E1 — longer horizon and two-rate grid (Task 12.3)

Status: IMPLEMENTED and executed on the SYNTHETIC fixture; participant CV go/no-go PENDING.
Every value is a SYNTHETIC DEVELOPMENT diagnostic (dirty tree, HEAD `91351f5`). **Nothing is
adopted.** ADR-0031.

## Runs and method

`experiments/phase-12/20260926-0611-synthetic-e1` trains `e1-k6` (K = 6, H = 0.2 s), `e1-k8`
(K = 8, H = 0.267 s) and `e1-2rate` (steps 1, 2, 3, 4, 6, 8; H = 0.267 s) for both families, 4 folds ×
3 seeds (72 cells), on windows re-exported per horizon by the Phase 08 exporter (H_max 0.3 s). Each
variant is compared with the K = 4 reference of the same fold and seed (reference, CPU and rule runs
as in the E4 report; figures `lead-vs-fp-e1.png`, `e1-error-growth.png`). The τ_commit grid extends
to 0.20 s for every variant, so a longer horizon can be exploited if the FP budget allows.

## Results (development; mean over 12 cells per family)

| Variant | Family | Error at 133 ms (ref FDE) | FDE at H | Feasible | Lead ms | FP/min | FN | TE MAE ms | Paired Δlead ms (n) | Paired ΔTE ms | CPU ratio | Development verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| reference K=4 | GRU | 0.0851 | 0.0851 | 2/12 | 14.5 | 17.7 | 0.440 | 9.2 | — | — | 1.00 | — |
| reference K=4 | TCN | 0.0696 | 0.0696 | 11/12 | 13.4 | 6.9 | 0.398 | 6.4 | — | — | 1.00 | — |
| `e1-k6` | GRU | 0.0917 | 0.1179 | 0/12 | — | — | — | — | — | — | 1.09 | NO-GO (insufficient evidence) |
| `e1-k6` | TCN | 0.0727 | 0.1000 | 10/12 | 15.7 | 12.4 | 0.334 | 8.0 | +3.3 (9) | +2.2 | 1.06 | NO-GO |
| `e1-k8` | GRU | 0.0947 | 0.1322 | 0/12 | — | — | — | — | — | — | 1.09 | NO-GO (insufficient evidence) |
| `e1-k8` | TCN | 0.0750 | 0.1232 | 10/12 | 10.4 | 9.9 | 0.494 | 12.8 | −2.2 (9) | +7.5 | 0.99 | NO-GO |
| `e1-2rate` | GRU | 0.0927 | 0.1339 | 1/12 | 14.0 | 28.0 | 0.540 | 17.4 | — | — | 1.09 | NO-GO (insufficient evidence) |
| `e1-2rate` | TCN | 0.0736 | 0.1217 | 10/12 | 12.8 | 6.6 | 0.432 | 7.5 | −0.5 (10) | +1.6 | 0.97 | NO-GO |

Seed-variance band: TCN 9.6 ms (lead), 5.1 ms (TE); GRU undefined. Error by offset (TCN, ms → ROI):
reference 33 → 0.023, 133 → 0.070; `e1-k8` 33 → 0.028, 133 → 0.075, 200 → 0.101, 267 → 0.123.

## Reading (fixture only)

- **Error grows roughly linearly with the offset**, and training for a longer horizon costs accuracy
  at the offsets the reference already covers (paired +0.003 to +0.010 ROI at 133 ms).
- **The longer horizon was not exploited.** The development picks used τ_commit = 0.02–0.05 s in all
  but one feasible cell (one `e1-k8` TCN cell at 0.10 s), exactly like the reference: points with a
  larger τ exceeded the FP budget. On this fixture lead is bounded by FP control, not by H, which is
  what the entry decision anticipated when it ranked E1 fourth.
- The two-rate grid behaves like K = 8 at a lower output count; it neither helped nor cost CPU.
- `e1-k8` TCN also worsened timing error beyond the seed band (+7.5 ms against 5.1 ms).

## Participant-stage plan (PENDING)

Run E1 only if the Phase 10 participant horizon sweep selects its largest K or shows lead bounded by
H − Δ_proc (entry decision); otherwise record E1 as skipped with that reason.

## Limitations

As in the E4 report; the fixture's downstrokes (0.15–0.26 s) are only slightly longer than the
longest declared H; no Δ_proc policy (zero delay) — lead bounded by processing delay is untested.
