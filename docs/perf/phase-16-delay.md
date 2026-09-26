# Phase 16 processing-delay reconciliation

Status: **PENDING** representative live strokes, shipped model and reviewer acceptance.
Date: 2026-09-26 (+03:00), HW-01. Numerical values below are development diagnostics.

`eval/constants.py` now declares `DELTA_PROC_LIVE_S = None` and the Phase 13
candidate materiality threshold `DELTA_PROC_MATERIAL_CHANGE_S = 0.001`. A changed
commit set also triggers review. `None` is explicit missing evidence, not zero
processing time. The application keeps its existing measured live clock and
explicit replay delay policy; no new numeric live constant is silently applied.

## Before/after policy check

Run: `experiments/phase-16/20260926-1357-delay-reconciliation/`.
`rerun-manifest.json` records source profile paths/hashes, same model hash,
all nine evaluations and complete commit records.

The compute proxy is the median of the nine per-session-run p95 values for
perception plus decision, excluding overlay and decode. It uses the application's
existing timer, separate from the full-loop budget table. This is not live
capture-to-commit `Δ_proc`: live queueing, scheduling and representative workload
remain unmeasured.

| Version | Fixed replay proxy |
|---|---:|
| Historical baseline (`20260926-1255-baseline`) | 52.7674 ms |
| Current (`20260926-1345-gate-verification/profile/20260926-1356-profile`) | 52.3853 ms |
| Current minus historical | -0.3821 ms |

This proxy change is below the predeclared 1 ms p95 rule. The fixed-policy raw
regression preserves all commits. Full-loop p95, which also includes the overlay,
changes from 58.429 to 56.302 ms; that is not substituted for the decision-path
proxy. Neither observation waives the pending representative live measurement.

## Same-model synthetic reruns

The original SYNTHETIC-trained float GRU hash stays
`sha256:b90fbc7fdb321f0b6e9845e9ae4daa2b440c6a42ff288562e8a097cfe212c7f0`.
Its pinned synthetic validation session is evaluated through the unchanged
Phase 09 harness at historical zero, historical proxy and current proxy. No
training, model selection, participant data or held-out test partition is used.

| Version | Arm A commits | Arm B commits | Arm C commits / false positives |
|---|---:|---:|---:|
| Historical zero added delay | 0 | 0 | 4 / 4 |
| Historical replay proxy | 0 | 0 | 0 / 0 |
| Current replay proxy | 0 | 0 | 0 / 0 |

All nine evaluations have zero matched impacts and six false negatives. Lead-time
medians and timing errors are undefined, so these reruns establish harness
execution and delay sensitivity only. Introducing either roughly 52 ms proxy
changes Arm C's commits relative to zero, which itself warrants review; it cannot
be silently presented as an accepted headline update. Historical and current
proxy commit sets agree.

Actual Phase 09/10 participant headline reruns remain PENDING. Once representative
live `Δ_proc` is accepted, evaluate the same frozen models and selected settings,
save Historical and Current manifests, and compare commits and informative lead
metrics under the Phase 13 materiality rule. Do not retrain to offset a delay change.
