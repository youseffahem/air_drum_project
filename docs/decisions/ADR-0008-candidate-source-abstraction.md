# ADR-0008 — Candidate-source abstraction: one geometry and one commit policy for arms A, B and C

| Field | Value |
|---|---|
| Status | **Accepted** (Phase 01, Task 01.10) |
| Date | 2026-09-20 |
| Deciders | Project owner (Q43: baselines remain available; Q45 comparison), recorded by Phase 01 |
| Related | `phases/README.md` §9, §10; `docs/architecture/architecture.md` §4; `schemas/strike-candidate.schema.json` (`source`), `committed-strike.schema.json` (`arm`, `shadow`); ADR-0007; REQ-043, REQ-045, REQ-114, REQ-307 |

## Context

The research comparison is Reactive (A) vs rule-based anticipation (B) vs learned anticipation (C). If each arm had its own detection, thresholding or de-duplication logic, differences in lead time or false positives could come from post-processing rather than from the anticipation method, and the pre-registered Phase 18 comparison would be confounded. Phase 05 also wants to log several arms on one live session without changing what the user hears.

## Decision

1. `StrikeCandidate.source ∈ {REACTIVE, RULE, MODEL}` is the **only** place the origin of a candidate is expressed on the decision path. `geometry.intersect` produces candidates from an *observed* trajectory (A: last two `TrackState` tip samples) or a *predicted* one (B/C: `TrajectoryPrediction.positions` prefixed by the current observed tip) through the same routine.
2. The `CommitPolicy` is **source-agnostic**: it reads `strike_probability`, `tti`, `t_impact_pred`/`t_impact_est`, `zone_id`, `hand_id` and `TrackState.status`. It never branches on `source` or `arm`. Thresholds (`tti_commit_s`, `p_commit`, refractory, gates) are one config block applied to every arm.
3. Arms can run **simultaneously**: one *active* (its commits are scheduled to audio), the others *shadow* (`CommittedStrike.shadow = true`, logged only). `CommittedStrike.arm` records which arm produced each commit; metrics treat shadow and sounding commits identically.
4. For `REACTIVE`, `t_impact_target = t_commit` and `L_pred < 0` by construction; nothing in the architecture assumes any arm is better.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Per-arm commit logic tuned for each arm | Confounds the comparison; A's FP behaviour could be "fixed" by a stricter gate than C's. Per-arm *threshold sweeps* are still done (README §10.3), but with the same policy code. |
| Compare arms only offline (no shadow mode) | Live sessions would not yield paired data; Phase 05's sanity check (B shadow vs A active) and Phase 13's parity test rely on shadow logging. |
| Encode source as separate record types (`ReactiveCandidate`, `PredictedCandidate`) | Would push branching into the commit policy and the harness; a tagged single type keeps one code path. |

## Consequences

- Phase 05 implements A and B as two producers of trajectories, not two detectors.
- Every candidate/commit record can be attributed to an arm in analysis; the primary Phase 18 figure (lead time vs FP) is a sweep of `tti_commit_s`/`p_commit` for each arm under the same policy.
- Shadow arms cost compute; Phase 16 budgets them and allows disabling in the release build.
- If both A and B/C produce candidates for the same episode, only the active arm commits audibly; the others are logged with the same `episode_id`, enabling paired timing comparisons.
- *(gate review 2026-09-21)* `derivation ∈ {GEOMETRY, DIRECT_HEAD}` is an orthogonal **diagnostic label** (ADR-0007 amendment), not a second source: the commit policy ignores it, and `source ↔ arm` is schema-bound (`REACTIVE↔A`, `RULE↔B`, `MODEL↔C-*`) so the two attribution fields cannot disagree.
