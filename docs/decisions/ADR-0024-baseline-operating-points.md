# ADR-0024 — Validation-only baseline operating points

Status: PREDECLARED PROCEDURE; budget and selected points PENDING participant data. Date: 2026-09-22.

Baseline B candidates sweep CV/CA, K=3/6, `tti_commit_s`=0.05/0.10,
`p_commit`=0.3/0.5 and `n_confirm_frames`=0/2. These are development grid values,
not selected settings. All arms use the production geometry and commit policy, the
same delay policy and the same matching W. A is evaluated at its Phase 05 settings.

On each validation fold, first measure A's FP/min and FN rate. Set the FP budget and
allowed FN margin in a dated protocol entry before looking at held-out test participants.
Select the B point with highest median lead among candidates inside both budgets; break
ties by lower FP/min, lower FN rate, then the lexicographic settings tuple. If no point is
feasible, report that outcome and the minimum-FP candidate as diagnostic, rather than
silently relaxing a budget. Repeat the same rule independently for C-GBDT direct and
trajectory modes. Record the exact selected settings, fold, model hash, W and validation
results in an operating-point file; the test evaluator requires that file. A lead-matched
diagnostic chooses the lowest-FP candidate whose median lead is at least A's median lead,
with the same tie rules.

The FP budget cannot be justified from participant playability or A's participant FP
rate yet. No participant operating point has been selected, and no held-out test run
has occurred. Self-test curves are machinery diagnostics only.
