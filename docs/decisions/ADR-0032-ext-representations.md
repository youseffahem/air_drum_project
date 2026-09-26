# ADR-0032 — E2 richer trajectory representations and the multi-modal commit rule

Status: **IMPLEMENTED machinery; adoption PENDING** participant CV under the pre-declared rule.
Date: 2026-09-26. Related: ADR-0007, ADR-0034; `docs/experiments/phase-12-prereg.md`;
`docs/reports/phase-12-e2-representations.md`.

## Context

The Phase 10 head predicts K fixed-step displacements (a point prediction). At a stroke reversal the
same history can continue into a strike or a pull-up, so a point prediction regresses to the mean.
Task 12.4 lists velocity integration, polynomial/Bezier coefficients and multi-modal mixtures.

## Decision

1. **E2(a) `e2-vel`**: the head outputs per-step increments; positions are their cumulative sum and
   `TrajectoryPrediction.velocities` carries increment / interval.
2. **E2(b) `e2-poly`**: per axis p(τ) = Σ_{d=1..3} c_d (τ/H)^d (zero at τ = 0), evaluated at the
   output offsets, with analytic velocities. A Bezier basis of fixed degree spans the same space.
3. **E2(c) `e2-mix2`**: two displacement modes plus logits, trained by relaxed winner-takes-all
   (winner weight 1 − ε, ε = 0.05) plus 0.5 × cross-entropy of the logits on the winning mode.
   Selection keeps the Phase 10 criterion on the most probable mode.
4. **Commit rule (declared).** M1 (primary): the candidate comes from geometry on the most probable
   mode; probability null. M2: the same candidate is relabelled with the aggregated crossing
   probability Σ_m w_m·1[mode m's first impact lies in the candidate's zone] and gated by the
   unchanged `p_commit`. Both count as separate variants under the go/no-go rule; if both are GO,
   M1 is preferred unless M2 exceeds it by the seed-variance band. No rule lets a non-geometry mode
   create a candidate.
5. **Contract.** Development runs carry the modes in the reserved `uncertainty` field
   (`mixture_xy`, ADR-0034). Adopting M2 requires a dedicated `modes` field (schema bump + ADR);
   this ADR does not make that change.

## Alternatives considered

- More modes (M > 2) or a mixture density with per-mode variances: more parameters and a harder
  commit rule for the same question; not declared.
- Commit on any sufficiently probable crossing mode: rejected, because a non-point mode would then
  create a candidate.

## Consequences

- No contract change in this phase; M2 adoption would bump `TrajectoryPrediction`.
- Best-of-M and most-probable errors are reported; neither decides adoption.
- Development observations (SYNTHETIC; `docs/reports/phase-12-e2-representations.md`): all
  NO-GO or insufficient evidence; the polynomial head had the lowest trajectory error without a
  rule-level lead gain; the 2-mode mixture collapsed to one mode in most cells. They do not decide
  adoption.
