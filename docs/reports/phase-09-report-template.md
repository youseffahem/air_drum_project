# Phase 09+ comparable result template

Use this layout for every A/B/C arm and every later temporal model. Cite the
`run.json` id and the exact `harness_hash` on each figure/table. Separate
SYNTHETIC, DEV CAPTURE and PARTICIPANT evidence; never pool them.

## Run identity

| Run ID | Source kind | Dataset/labels/split hashes | Fold/partition | Arm/mode | Config/model hashes | Seed | W | Delay policy/evidence | Harness hash |
|---|---|---|---|---|---|---:|---:|---|---|
| PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |

## Primary event table

One row per participant, followed by a pooled row. Repeat by fold and then by
hand, zone and segment type. Always show denominators; use `N/A` for undefined
rates. The pooled FP/min denominator is elapsed accepted active time once.

| Participant | GT positives | Matched | FP | FN | Active min | FP/min | FN rate | Lead median [Q1,Q3] ms | Lead >0 | TE prediction bias/MAE ms | Zone accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---:|
| PENDING | — | — | — | — | — | — | — | — | — | — | — |

## Companion figures and tables

1. Lead time versus FP/min: achieved threshold points only; mark the selected
   validation operating point and show the W/delay settings.
2. Timing-error histogram: `t_impact_pred - t_impact_est` for matched predicted
   strikes, with bias/MAE and matched count. A's observed crossing error is
   separately named `te_event_s`.
3. Zone confusion: rows actual, columns predicted, with the matched denominator.
4. FP attribution: fake swing, stop-before-impact, between zones, tracking loss,
   and every other recorded segment type. Report unattributed events explicitly.
5. W sensitivity: 25, 50, 75 and 100 ms; primary W chosen by ADR-0023 on
   validation A only.
6. Trajectory ADE/FDE against future **causal** tracker output, intensity proxy
   agreement, and batch-one CPU inference p50/p95/p99 with thread count.
7. For A, show each available software-stamped latency term and `L_sys_est`
   only if measured output latency supplied the estimate. Reserve `L_sys`
   without suffix for externally measured audio output/onset.

## Interpretation

State P (participant count), participant-level bootstrap interval when P permits,
label provenance, missing physical impact reference, tracking-loss sensitivity,
and whether the selected point met the FP/FN budgets. Never infer a live
action-to-sound improvement from offline prediction lead alone.
