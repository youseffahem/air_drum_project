# Phase 10 history and auxiliary gating

Status: PENDING participant experiment; candidate development machinery IMPLEMENTED.

The development plan uses N={4,16} at candidate K=4 and dt=1/30s, both families,
three synthetic folds and three seeds, with lambda_aux=0 or .1. The horizon run
also supplies pure-trajectory N=8. Candidate H is not selected from participant
evidence. Every N/H combination regenerates Phase 08 windows, normalization-bound
inputs and the matching auxiliary labels before training.

The auxiliary head only estimates strike-within-H. Its probability travels with
the trajectory to geometry and is applied by unchanged Phase 05 after a candidate
exists. The pure model has no trained classifier and no probability gate. Tests
show that even a high auxiliary logit cannot produce a strike without a crossing.

Full replay control tables retain null metrics when no event matches, rather than
replacing them with favorable zeroes. Fixture-identity bootstrap diagnostics are
not participant CIs. All settings and source hashes are archived per run. The
completed development run, table and parity results are recorded below.

Participant history selection, auxiliary trade-off conclusions, mean/variance
across actual participants and the best lead/FP curve remain PENDING. Five-epoch
fixture training is an engineering test, not evidence for or against temporal AI.

## Completed development sweep

`experiments/phase-10/20260924-1936-synthetic-window/run.json` completed at
2026-09-24 20:16:50 +03:00 with 72 models, 1,296 replay evaluations and 4,807
hashed artifacts. All 72 all-sample export parity checks and export-reload metric
checks passed (atol=1e-6, rtol=1e-5). Every family/N/auxiliary cell has three
fixture folds and seeds 10,11,12. Auxiliary training uses lambda_aux=.1.

| N | Family | Auxiliary trained | Mean ADE | Mean FDE | p95 CPU range (ms) |
|---:|---|---|---:|---:|---:|
| 4 | GRU | No | 0.16603 | 0.16868 | 0.636–3.744 |
| 4 | GRU | Yes | 0.18303 | 0.19551 | 2.216–5.670 |
| 4 | TCN | No | 0.09290 | 0.11976 | 2.126–5.699 |
| 4 | TCN | Yes | 0.14433 | 0.16903 | 2.074–6.243 |
| 16 | GRU | No | 0.19233 | 0.18236 | 3.063–23.347 |
| 16 | GRU | Yes | 0.21493 | 0.21756 | 2.869–8.718 |
| 16 | TCN | No | 0.11160 | 0.14286 | 0.724–1.459 |
| 16 | TCN | Yes | 0.15094 | 0.20239 | 1.898–8.275 |

Means average nine fold/seed diagnostics; errors are ROI-normalized. Timing ranges
are individual models' development p95 values, not CIs. CPU contention from other
repository checks makes them unsuitable for a controlled performance ranking.
Longer history changes eligible sample counts: fold 0 has 436/218 train/validation
windows at N=4 and 340/170 at N=16, with 52/26 and 40/20 positive auxiliary labels
respectively. Every model manifest records its own counts and source hashes.

The supplementary figure
`experiments/phase-10/synthetic-window-figures/lead-vs-fp-by-history-aux.png`
separates history length, family and auxiliary threshold. Its generating script
and source-curve hash are retained. The figure was visually inspected. Undefined
lead is omitted from the scatter but counted in the legends and preserved in raw
tables. All 432 evaluations with p_aux=.7 had no matches; that is not a successful
FP-control operating point. TCN N16 with p_aux=.3 also had no matches. The full
FN/FP/timing/zone/intensity tables remain available in the immutable replay files.

These are SYNTHETIC DEVELOPMENT outcomes, with candidate W=.05s and zero replay
delay. They do not select N, auxiliary use, a threshold, or a model family.
