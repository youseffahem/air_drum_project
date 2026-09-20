# ADR-0007 — Trajectory first: geometry is a separate deterministic stage after prediction

| Field | Value |
|---|---|
| Status | **Accepted** (Phase 01, Task 01.10) — amended at the Phase 01 gate review 2026-09-21 (§ Amendment below; pre-gate, so in place rather than by a superseding ADR) |
| Date | 2026-09-20 (amended 2026-09-21) |
| Deciders | Project owner (Q41–Q42, Core Research Direction), recorded by Phase 01 |
| Related | `phases/README.md` §1, §9; `docs/architecture/architecture.md` §1, §2.2 (`prediction` may not import `geometry`), §4; `schemas/trajectory-prediction.schema.json`; REQ-041, REQ-042, REQ-109, REQ-111, REQ-112 |

## Context

Q42 fixes the concept *Past Motion → Future Trajectory Prediction → Virtual Drum Geometry → Strike*. The roadmap adds that the neural model is never reduced to a bare strike classifier. Without a structural rule, the shortest path to a working demo would be a classifier that outputs "strike in zone Z within H", which would (a) make the impact convention (Q36–Q39) live inside the model, (b) make A/B/C comparison unfair because the geometry code path would differ per arm, and (c) make impact position/time (Q38–Q39) unavailable for evaluation.

## Decision

1. The **primary and required output** of every `Anticipator` is a `TrajectoryPrediction` whose `positions[]` (K future tip positions) is non-empty. Auxiliary heads (`aux.strike_prob_within_H`, `tti`, `zone_logits`, `impact_pos`, `intensity_proxy`) are optional (Phase 11) and **may inform** the commit policy via `strike_probability`, but **never replace** the geometric derivation of the strike.
2. `geometry.intersect(trajectory, source)` — the same deterministic code that detects observed impacts — turns the predicted trajectory into `StrikeCandidate`s with `t_impact_pred`, `tti`, `impact_position`, `zone_id`, `crossing_velocity`. The impact convention, sub-frame crossing interpolation and episode rule are implemented once, in `geometry` (Phase 04), for all sources.
3. `prediction` may not import `geometry` (import-linter contract). A model sees zones only through Phase 08 features, which are leakage-tested.
4. The learned model's outputs are decoded into `positions[]` in ROI-normalized units before geometry; any internal parameterisation (deltas, normalised targets) is the model adapter's private matter (Phase 10).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Direct strike classifier / TTI regressor as the main model | Contradicts Q42; hides the impact convention in learned weights; no impact position; not comparable with A/B under identical geometry. Kept only as a **diagnostic no-trajectory mode** in the Phase 19 ablation, clearly labelled. |
| Model predicts trajectory *and* decides the strike internally (end-to-end), geometry only for logging | Same unfairness; commit logic would differ per arm. |
| Geometry inside the anticipator interface (one call returns candidates) | Would let implementations shortcut the trajectory; separate stage keeps the trajectory observable and testable (ADE/FDE metrics need it). |

## Consequences

- Trajectory Error (ADE/FDE, impact-position error) is measurable for every anticipatory arm, including the rule-based baseline B.
- A model that predicts good trajectories but whose geometric derivation gives poor timing points at geometry or at the horizon, not at the model — the decomposition is diagnosable.
- Cost: an extra deterministic pass per frame per hand (segment–surface intersection over K steps); budgeted in the `geometry+commit` slot (Pending Benchmark).
- Multi-task heads (Phase 11) are evaluated **both** as auxiliary outputs and for whether they help the commit policy; they are never the strike decision alone.

## Amendment (Phase 01 gate review, 2026-09-21)

**Finding.** The roadmap itself defines two sanctioned paths that bypass geometry: Phase 09 Task 09.8 evaluates C-GBDT in a *direct* mode (probability + TTI → candidate) beside the trajectory-derived mode, and Phase 19 AB-NOTRAJ ablates the trajectory stage to test this very ADR's claim. The original contract (non-empty `positions` required; only `geometry` produces `StrikeCandidate`) made those paths un-representable — they would have had to fake a trajectory or bypass the contracts, which is worse for the trajectory-first claim than a labelled diagnostic path.

**Decision (added).**
5. A **diagnostic-only** record `DirectPrediction` (`contracts.md` §3.11) and interface `DirectAnticipator.predict_direct` exist for those two modes. The harness's direct-head adapter turns a `DirectPrediction` into `StrikeCandidate(source = MODEL, derivation = DIRECT_HEAD)` through the **same** commit policy.
6. `StrikeCandidate.derivation` / `CommittedStrike.derivation ∈ {GEOMETRY, DIRECT_HEAD}` is schema-enforced (`DIRECT_HEAD ⇒ source = MODEL`; `REACTIVE`/`RULE ⇒ GEOMETRY`), so direct-mode results can never be merged with trajectory-first results without a visible label; every table/figure using them says *direct / no-trajectory (diagnostic)*.
7. The live application never runs a direct path: Phase 13's loader refuses a model package that offers only a direct head; `TEST-CONFORM-3` checks that live arms implement `Anticipator`.
8. `TrajectoryPrediction.t_offsets_s` allows sparse predicted horizons (GBDT head iv) so that geometry intersects what was actually predicted; missing steps are never interpolated and presented as prediction.

**Unchanged.** `TrajectoryPrediction.positions` remains required and non-empty; `prediction` still may not import `geometry`; the strike of every live arm is still derived by geometry from a predicted trajectory.
