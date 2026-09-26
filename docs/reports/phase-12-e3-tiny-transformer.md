# Phase 12 E3 — Tiny Transformer (arm C-TT; Task 12.5, REQ-044)

Status: feasibility gate MEASURED (development CPU compute, dirty tree): **FEASIBLE**. Development
training executed on the SYNTHETIC fixture; participant CV go/no-go PENDING. **Nothing is adopted.**
ADR-0033.

## Feasibility gate (before any TT training)

`experiments/phase-12/20260926-0519-tt-feasibility` (COMPLETED 05:19:20 +03:00; the first E3
training started at 06:21:54). Randomly initialised TorchScript models at the declared development
size, batch 1, one thread, random inputs of shape [1, 8, 56] with an 80 % mask, 10 interleaved blocks
× 100 calls after 100 warm-up calls, `spacedrums.timing.now`.

| Model | Parameters | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|
| GRU (Phase 10, width 16) | 6,376 | 1.431 | 3.358 | 9.295 |
| TCN (Phase 10, width 16) | 6,648 | 1.033 | 3.211 | 8.049 |
| **TT** (width 16, 2 heads, 2 layers, FF 32) | 6,456 | 0.978 | **3.762** | 8.972 |
| TT width 32, 4 heads (informational only) | 21,096 | 0.912 | 2.415 | 7.066 |

Budget = F × max(GRU p95, TCN p95) = 3 × 3.358 = **10.074 ms**; TT p95 3.762 ms → **FEASIBLE**.
The isolated trained-model run later measured lower absolute values for every model (forward p95:
GRU 1.169, TCN 0.680, TT 0.825 ms; `experiments/phase-12/20260926-0624-ext-latency-memory`), which
confirms the verdict with a large margin. The cause of the session-to-session difference was not
investigated, so only within-session ratios are used.

## Development training

`experiments/phase-12/20260926-0621-synthetic-e3`: 12 cells (tt × 4 folds × 3 seeds), arm
`MODEL:C-TT` through the unchanged geometry and commit policy, compared with each reference family
(pre-declared).

| Model | ADE | FDE | Feasible | Lead ms | FP/min | FN | TE MAE ms | Path p95 ms (ratio) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| reference GRU | 0.0624 ± 0.0065 | 0.0851 | 2/12 | 14.5 | 17.7 | 0.440 | 9.2 | 1.535 |
| reference TCN | 0.0452 ± 0.0050 | 0.0696 | 11/12 | 13.4 | 6.9 | 0.398 | 6.4 | 1.008 |
| `e3-tt` | 0.0525 ± 0.0055 | 0.0867 | **12/12** | 15.8 ± 4.0 | 14.8 | 0.246 | 7.5 | 1.157 (0.75) |

Development verdicts: against TCN, paired Δlead +2.7 ms (n = 11) < 9.6 ms band, ΔTE +1.1 ms,
CPU 0.75 × → **NO-GO**; against GRU → NO-GO (insufficient evidence; GRU band undefined).

## Reading (fixture only)

- **Computationally justified on HW-01**: the causal TT costs no more than the Phase 10 encoders at
  this size, in both sessions.
- On the fixture the TT's trajectory error lies between the GRU and the TCN. It was the only model
  feasible in every cell, with the lowest FN rate. Its lead gain against the TCN stays inside the
  seed band, so the pre-declared rule does not adopt it.
- Attention over 8 frames has little room to exploit long-range structure. A longer history N is a
  Phase 10/19 factor, not an E3 change made here.

## REQ-044 status

CPU half: development evidence (dirty tree; clean rerun and the target-CPU budget of Phase 13/16
PENDING). Validation half: PENDING participant CV. The RTM row stays PLANNED until a reviewer signs.

## Limitations

As in the E4 report; feasibility uses random weights and inputs (cost depends on the architecture,
not the values); timings are development compute on HW-01.
