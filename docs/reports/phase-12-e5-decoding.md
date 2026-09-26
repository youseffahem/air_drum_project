# Phase 12 E5 — better decoding (Task 12.7)

Status: IMPLEMENTED and executed on the SYNTHETIC fixture; participant CV go/no-go PENDING.
Every value is a SYNTHETIC DEVELOPMENT diagnostic (dirty tree, HEAD `91351f5`). **Nothing is
adopted.** ADR-0035.

## Runs and method

`experiments/phase-12/20260926-0541-synthetic-e5` trains `e5-resb` (24 cells) and evaluates
`e5-smooth` on the 24 reference cells of `experiments/phase-12/20260926-0528-synthetic-ref`.
CPU: `experiments/phase-12/20260926-0624-ext-latency-memory`; rule:
`experiments/phase-12/20260926-0629-synthetic-go-no-go` (`lead-vs-fp-e5.png`). Development settings,
control grid (τ only; both variants carry no probability) and budget as in the E4 report.

- `e5-resb`: point = v·τ_k + model output, v = the current frame's `vx`, `vy` de-normalised with
  the training fold's centre/scale (tested equal to Baseline B's CV extrapolation).
- `e5-smooth`: reference outputs projected greedily so that the second difference from the second
  step on stays ≤ a_max. a_max is the 99th percentile on the fold's training targets:
  74.2 / 76.5 / 79.8 / 80.5 ROI/s² for the four folds.

## Results (development; mean ± SD over 12 cells per family)

| Variant | Family | ADE | Paired ΔADE vs ref | Feasible cells | Lead ms | FP/min | FN | TE MAE ms | Paired Δlead ms (n) | Seed band ms | CPU path ratio | Development verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| reference | GRU | 0.0624 ± 0.0065 | — | 2/12 | 14.5 | 17.7 | 0.440 | 9.2 | — | undefined | 1.00 | — |
| reference | TCN | 0.0452 ± 0.0050 | — | 11/12 | 13.4 | 6.9 | 0.398 | 6.4 | — | 9.6 | 1.00 | — |
| `e5-resb` | GRU | 0.0621 ± 0.0064 | −0.0003 | 7/12 | 13.1 | 14.5 | 0.413 | 9.9 | −0.6 (2) | undefined | 1.06 | NO-GO (insufficient evidence) |
| `e5-resb` | TCN | 0.0454 ± 0.0049 | +0.0002 | 12/12 | 17.4 | 12.7 | 0.302 | 7.2 | +4.3 (11) | 9.6 | 1.00 | NO-GO |
| `e5-smooth` | GRU | 0.0629 ± 0.0069 | +0.0005 | 3/12 | 12.1 | 22.0 | 0.480 | 13.2 | +0.1 (2) | undefined | 0.99 | NO-GO (insufficient evidence) |
| `e5-smooth` | TCN | 0.0454 ± 0.0053 | +0.0002 | 11/12 | 13.4 | 6.9 | 0.398 | 6.4 | 0.0 (11) | 9.6 | 1.15 | NO-GO |

## Reading (fixture only)

- **Residual over the CV extrapolation** left trajectory error unchanged but moved more cells
  inside the development budget (GRU 7/12 vs 2/12; TCN 12/12 vs 11/12). Its TCN lead is +4.3 ms on
  paired cells, the largest lead difference of any declared variant, but below the 9.6 ms seed band,
  so the pre-declared rule says NO-GO. The fixture's strokes descend along vertical straight lines,
  which favours straight-line extrapolation (Phase 11 per-task report); participant motion may not.
- **Bounded acceleration** is almost inert: the training-target bound (74–81 ROI/s²) rarely binds
  on smooth model outputs. 19 of the 24 development picks are identical to the reference's and the
  other five differ marginally. A tighter bound would be a new declared candidate, not a post-hoc
  adjustment.
- CPU cost is at the reference's level (the E5(a) base is a few tensor operations; E5(b) is O(K)).

## Participant-stage plan (PENDING)

E5 is second in the participant priority order (entry decision). `e5-resb` needs the fs-v1
velocity features to be usable in every participant fold (checked at training). `e5-smooth` needs no
training. Resampling to the live `dt` (E5(c)) belongs to Phase 13.

## Limitations

Synthetic kinematics favour extrapolation; GRU seed band undefined; development budgets are
synthetic; latency is development compute on a dirty tree; no participant data.
