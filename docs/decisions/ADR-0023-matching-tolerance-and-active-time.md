# ADR-0023 — Phase 09 matching tolerance and active time

Status: PREDECLARED RULE; primary tolerance PENDING participant validation. Date: 2026-09-22.

The evaluator matches committed strikes to positive geometric labels within each session and
hand. It greedily takes the available pair with smallest absolute difference between `t_commit`
and `t_impact_est`, including the tolerance boundary. Ties are resolved by earlier commit,
earlier impact, then stable input order. Zone is omitted from matching cost so a wrong-zone
strike can be matched and counted against zone accuracy. The match is one-to-one. Ambiguous
and excluded labels are not ground truth; predictions inside their intervals or within W of
an ambiguous event are withheld from FP counts.

The candidate W sweep is 25, 50, 75 and 100 ms. **Before reading test-participant results**,
choose the smallest candidate W whose validation-fold match rate on accepted, clean single-hit
segments is within one percentage point of the maximum among candidates. Use Baseline A only
for this choice. If fewer than 20 such events exist, do not freeze W; collect more data or
record a protocol amendment. The current 50 ms CLI default is a development candidate, not
the primary tolerance. `W_PRIMARY_S` remains `None`, and the test evaluator refuses to run
without a frozen value.

Active time is the union of accepted segment intervals minus the union of tracking-loss
intervals. For each hand, the segment must permit that hand. Pooled FP/min divides by elapsed
accepted playing time once, not by two hand-minutes. Ambiguous intervals remain in active
time because the participant was still playing; they are excluded only from event numerators.
Both the denominator and excluded-label count are written to results. A zero denominator
produces a null rate, not zero. Sensitivity to excluding ambiguous intervals remains a
participant-data analysis task.

This rule has been implemented and tested on synthetic/developer data. Its empirical choice
and freeze are blocked by the absent reviewed `ds-v1.0` validation folds. Phase 07's synthetic
interpolation error is not a substitute for participant label uncertainty.

## Clarification — 2026-09-27 (Phase 18 owner decision A1)

README §10.1 describes matching by a reference time `t_ref` (`t_impact_pred` for anticipatory
sources, the detected `t_impact_est` for Baseline A). The harness implements this ADR's
commit-time rule instead, and this ADR did not record the difference before Phase 18.

The owner decided on 2026-09-27 (decision A1) that this ADR's commit-time matching stays the
primary confirmatory rule. README §10.1 reference-time matching stays the pre-declared sensitivity
S1 of the Phase 18 pre-registration (§4.2), computed without changing the harness
(`spacedrums.live_eval.offline.reference_time_evaluation`). As declared there (§4.1), every
matched lead is bounded by W, and a commit made more than W before the estimated impact counts as
one false positive and one false negative. The matching rule, the W procedure and `W_PRIMARY_S`
(still `None`) are unchanged.
