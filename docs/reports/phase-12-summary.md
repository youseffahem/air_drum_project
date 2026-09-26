# Phase 12 summary — extension go/no-go (acceptance criterion 4)

Status: **No extension adopted.** Adoption is impossible in this execution: the pre-declared rule
needs participant CV folds and the confirmatory run needs held-out participants, and neither exists.
Every number below is SYNTHETIC DEVELOPMENT evidence (dirty tree, HEAD `91351f5`) that exercises the
machinery. Date: 2026-09-26 (+03:00).

## What ran

| Step | Evidence |
|---|---|
| Entry decision and rule, archived before any extension existed | `docs/experiments/phase-12-{entry-decision,prereg}.md`; hashes in `experiments/phase-12/predeclaration/predeclaration.json` (04:59:01); every run re-checks them |
| E3 CPU feasibility gate, before any TT training | `20260926-0519-tt-feasibility`: FEASIBLE (TT p95 3.762 ms ≤ 10.074 ms budget) |
| Reference (Phase 10 GRU/TCN), bit-identical to the Phase 11 `traj-only` cells (24/24 checkpoints) | `20260926-0528-synthetic-ref` |
| E4, E5, E2, E1, E3 development grids (228 trained cells incl. the reference + 56 evaluation-only rule cells: 8 ensembles, 24 smoothing, 24 M2) | `20260926-0533-synthetic-e4`, `-0541-synthetic-e5`, `-0550-synthetic-e2`, `-0611-synthetic-e1`, `-0621-synthetic-e3` |
| EXPLORATORY post-hoc variance head (not pre-declared) | `20260926-0547-exploratory-e4-posthoc` |
| Isolated CPU path latency and working set (27 entries) | `20260926-0624-ext-latency-memory` |
| Mechanical go/no-go | `20260926-0629-synthetic-go-no-go` (`go-no-go.{json,md}`, figures); `-0627-…` is a superseded run with identical verdicts and a clipped figure title |

All run directories are under `experiments/phase-12/` (git-ignored; `run.json` hashes every artifact).

## Development go/no-go (pre-declared rule; SYNTHETIC; not adoption decisions)

Development budget FP ≤ 30/min, FN ≤ 0.6 (Phase 11 constants); δ_TE = 0; CPU factor F = 3. Seed
band = 2 × the reference's pooled within-fold seed SD: TCN 9.6 ms (lead), 5.1 ms (TE). GRU is
undefined because the GRU reference met the budget in only 2/12 cells, so every GRU comparison
is "insufficient evidence".

| Variant | Family | Feasible cells (ref) | Paired Δlead ms (n) | Paired ΔTE ms | CPU path ratio | Checks F/L/T/C | Development verdict |
|---|---|---|---:|---:|---:|---|---|
| `e1-k6` | TCN | 10/12 (11) | +3.3 (9) | +2.2 | 1.06 | N/N/Y/Y | NO-GO |
| `e1-k8` | TCN | 10/12 (11) | −2.2 (9) | +7.5 | 0.99 | N/N/N/Y | NO-GO |
| `e1-2rate` | TCN | 10/12 (11) | −0.5 (10) | +1.6 | 0.97 | N/N/Y/Y | NO-GO |
| `e2-vel` | TCN | 9/12 (11) | −3.6 (8) | +0.1 | 0.98 | N/N/Y/Y | NO-GO |
| `e2-poly` | TCN | 10/12 (11) | +3.2 (10) | +2.6 | 1.07 | N/N/Y/Y | NO-GO |
| `e2-mix2` (M1) | TCN | 3/12 (11) | −5.3 (3) | +18.1 | 1.18 | N/N/N/Y | NO-GO |
| `e2-mix2-agg` (M2) | TCN | 3/12 (11) | −5.3 (3) | +18.1 | 1.47 | N/N/N/Y | NO-GO |
| `e3-tt` | TT vs TCN | 12/12 (11) | +2.7 (11) | +1.1 | 0.75 | Y/N/Y/Y | NO-GO |
| `e4-gauss` | TCN | 1/12 (11) | −5.3 (1) | −0.8 | 3.55 | N/N/Y/N | NO-GO |
| `e4-ens3` | TCN | 4/4 folds (4) | +1.6 (4) | −0.0 | 2.70 | Y/N/Y/Y | NO-GO |
| `e5-resb` | TCN | 12/12 (11) | +4.3 (11) | +0.6 | 1.00 | Y/N/Y/Y | NO-GO |
| `e5-smooth` | TCN | 11/12 (11) | 0.0 (11) | 0.0 | 1.15 | Y/N/Y/Y | NO-GO |
| every variant | GRU (and TT vs GRU) | — | — | — | 0.75–2.93 | — | NO-GO (insufficient evidence) |

GRU feasible cells (reference 2/12): `e1-k6` 0, `e1-k8` 0, `e1-2rate` 1, `e2-vel` 6, `e2-poly` 7,
`e2-mix2` 1, `e2-mix2-agg` 2, `e4-gauss` 0, `e4-ens3` 4/4 folds, `e5-resb` 7, `e5-smooth` 3 (all 12
TT cells were feasible). EXPLORATORY `x-e4-posthoc` (outside the rule): GRU 5/12 with the
crossing-probability gate against 2/12 without it; TCN lead 16.0 vs 13.4 ms at equal feasibility;
TCN path 3.46 × (above F).

## CPU path latency and memory (isolated run; development compute on HW-01)

Batch 1, one thread, TorchScript exports, 1,000 calls per entry in 10 interleaved blocks. The
*path* is forward + decoding + deterministic geometry (+ crossing probability, S = 32, where
declared), timed on validation windows whose point trajectory yields a candidate.

| Entry (fold 0, seed 10) | Parameters | Forward p95 ms | Path p50 / p95 / p99 ms | Ratio to reference | Working set after load MB |
|---|---:|---:|---|---:|---:|
| reference GRU / TCN | 6,376 / 6,648 | 1.169 / 0.680 | 0.985/1.535/1.862 · 0.632/1.008/1.319 | 1.00 | 241.5 / 241.1 |
| `e1-k8` GRU / TCN | 6,512 / 6,784 | 1.191 / 0.678 | 1.013/1.667/2.510 · 0.659/0.999/1.250 | 1.09 / 0.99 | 241.8 / 241.5 |
| `e2-mix2-agg` GRU / TCN | 6,546 / 6,818 | 1.281 / 0.746 | 1.346/2.341/3.172 · 0.982/1.479/1.904 | 1.53 / 1.47 | 241.6 / 241.4 |
| `e3-tt` | 6,456 | 0.825 | 0.665/1.157/1.747 | 0.75 | 241.8 |
| `e4-gauss` GRU / TCN | 6,512 / 6,784 | 1.261 / 0.728 | 2.590/4.503/6.106 · 2.220/3.583/4.944 | 2.93 / **3.55** | 241.4 / 241.0 |
| `e4-ens3` GRU / TCN | 19,128 / 19,944 | 3.408 / 1.972 | 2.982/3.920/5.388 · 1.865/2.724/3.793 | 2.55 / 2.70 | 241.8 / 243.1 |
| `e5-resb` GRU / TCN | 6,376 / 6,648 | 1.295 / 0.819 | 1.026/1.629/2.281 · 0.677/1.008/1.219 | 1.06 / 1.00 | 242.5 / 241.3 |

All 27 entries (including every E1/E2 variant, `e5-smooth` and the exploratory head) are in
`latency-memory.json`. Working sets are dominated by the Python/PyTorch runtime; loading a model adds
4–7 MB.

## What the owner needs to decide

1. Accept the bounded attempt as the entry decision, or replace it with a documented skip or
   deferral (the phase allows both). Phase 13 does not depend on Phase 12.
2. The compute/time budget for participant CV, and whether to declare the post-hoc variance head as
   E4(a′) before any participant run (the exploratory result motivates it).
3. The inherited Phase 10/11 owner fields (FP budget, FN ceiling, W, δ_TE, δ_lead, CPU budget).

## Limitations

One scripted fixture, one validation identity per fold, synthetic budgets, zero delay policy,
dirty-tree development timings on HW-01. No participant, DEV CAPTURE or physical-pad data. None of
these numbers may enter Phase 18/19 or the thesis as results.
