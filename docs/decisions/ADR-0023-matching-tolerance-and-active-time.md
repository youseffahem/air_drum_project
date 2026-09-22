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
