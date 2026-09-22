# Phase 07 — Sub-frame interpolation comparison (Table 1: estimator only)

**Reference:** analytic crossing of the SYNTHETIC swing — sampled measurements, no smoother

**Evidence class:** SYNTHETIC — generated trajectories with an analytically known crossing; evidence about the estimators, not about real recordings

**Decision rule (declared before the run):** smaller IQR wins; within 10 % of each other, smaller |bias| wins; within 10 % on both, keep LINEAR (the Phase 04 estimator, fewer assumptions). Declared before the run.

| Estimator | n | bias (median) | IQR | max |error| |
|---|---:|---:|---:|---:|
| LINEAR (Phase 04) | 24 | -0.734 ms | 2.047 ms | 3.821 ms |
| QUADRATIC | 24 | 0.000 ms | 1.067 ms | 1.832 ms |

**Decision: `QUADRATIC`** — IQR differs by more than 10 % (0.00204739 s vs 0.00106685 s)

# Table 2 — the same strokes through the reference smoother

**Reference:** analytic crossing of the SYNTHETIC swing — through `rts-kalman-cv-v1`

**Evidence class:** SYNTHETIC — generated trajectories with an analytically known crossing; evidence about the estimators, not about real recordings

**Decision rule (declared before the run):** smaller IQR wins; within 10 % of each other, smaller |bias| wins; within 10 % on both, keep LINEAR (the Phase 04 estimator, fewer assumptions). Declared before the run.

| Estimator | n | bias (median) | IQR | max |error| |
|---|---:|---:|---:|---:|
| LINEAR (Phase 04) | 24 | -0.660 ms | 1.401 ms | 5.033 ms |
| QUADRATIC | 24 | -0.226 ms | 1.284 ms | 1.435 ms |

**Decision: `QUADRATIC`** — IQRs within 10 %; |bias| differs (-0.000660169 s vs -0.000226227 s)

> **Not a real-world measurement.** The reference is the analytic crossing of a generated trajectory. The comparison against a physical reference (`t_impact_phys`, pad + microphone) and against manual frame annotations near impacts remains **PENDING / NOT VALIDATED**: no such recording exists.
>
> Table 1 isolates the interpolation estimator (24 events, no smoother). Table 2 shows the same strokes through the reference smoother `rts-kalman-cv-v1` (24 events); there the error also carries how the smoother treats the reversal at impact, which is Task 07.2's question (`docs/reports/phase-07-reference-smoother.md`).
>
> Measurement noise 0.0. The decision below is taken on **Table 1**, because that is the table that isolates the estimator under test.
