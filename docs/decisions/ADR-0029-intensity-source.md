# ADR-0029 — Commit-time intensity-proxy source for C-MT

Status: PENDING participant evidence (Task 11.7). Development default: **geometry** (unchanged).
Date: 2026-09-25.
Related: ADR-0027 (inward-normal proxy of the MODEL wrapper), ADR-0028, REQ-014, Q14, Q45;
labelling rule R2 (`intensity_proxy_gt` = inward-normal velocity at `t_impact_est`).

## Context

A committed strike needs an intensity proxy when it is committed, before the impact. Three
sources exist at that moment: (a) the inward-normal crossing speed of the **predicted**
trajectory at its predicted crossing (the Phase 10 MODEL wrapper, `eval/temporal.py`), (b) the
Phase 11 intensity head, (c) Baseline B's extrapolated crossing speed. Q14/Q45 require the
proxy's agreement with `intensity_proxy_gt`; it remains a proxy, never force.

## Decision

- Metric: agreement with `intensity_proxy_gt` of the matched label, evaluated **at the commit**
  of each matched C-MT strike (not at impact): Spearman ρ primary (a volume mapping needs order),
  MAE and Pearson r secondary, coverage reported. (b) is read from the prediction at the commit
  frame; (c) from Baseline B's candidate at the same hand/frame and zone
  (`scripts/eval_consistency.py`, `_p11.commit_time_intensity`). Baseline B's own committed
  value (Phase 04 speed magnitude) is reported separately and is not the same definition.
- Rule (pre-registered): choose the head only if its participant-macro ρ exceeds geometry's with
  a bootstrap CI excluding geometry's estimate; otherwise keep geometry, which adds no learned
  dependency. Baseline B is eligible only when B is the shipped arm.
- Until that evidence exists, `commit.aux_heads.intensity_source` stays `geometry` (the default).
- Open alternative (recorded, not implemented): update the proxy at the predicted impact time
  instead of at commit. It would change the scheduled sound after commit and is out of scope for
  V1's commit-once policy.

## Development observations (SYNTHETIC; not evidence)

Run `experiments/phase-11/20260925-1007-synthetic-gating` (24 all-heads `dominant-0.05` cells,
τ 0.05 s, matched C-MT commits): Spearman ρ of (a) geometry 0.33 (GRU) / 0.31 (TCN), MAE 0.89 /
0.97; (b) head 0.32 / 0.21, MAE 0.40 / 0.40; (c) Baseline B same-frame inward speed 0.70 / 0.62,
MAE 0.66 / 0.72, coverage 0.81 / 0.89. The head is best calibrated, but its ranking is not better
than geometry's (except GRU at τ 0.10). The rule would therefore keep geometry. The fixture's
straight, accelerating strokes favour B's extrapolation. Details and limitations:
`docs/reports/phase-11-gating.md`. None of this is evidence for the participant decision.

## Consequences

The committed `intensity_proxy` of C-MT is the geometric inward crossing speed unless and until
a participant result satisfies the rule above. Phase 04's gain mapping is unchanged.
