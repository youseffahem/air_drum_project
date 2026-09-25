# ADR-0030 — Phase 11 ship decision: C-MT, single-task or baseline

Status: PENDING the single confirmatory participant run (Task 11.9). **Nothing is selected.**
Date: 2026-09-25.
Related: ADR-0007, ADR-0025, ADR-0027, ADR-0028, ADR-0029; `docs/experiments/phase-11-prereg.md`.

## Context

Phase 11 must decide, on held-out participants and once, whether the live system uses the
multi-task model (C-MT), the Phase 10 single-task model, or a baseline, and how each shipped
head is used (informational, gating or consistency). That decision needs the Phase 09/10
gates, reviewed ds-v1.0 folds, owner budgets and the Phase 11 CV evidence, none of which exists.

## Decision (rule only)

The rule is the pre-registered one: discard arms violating the FP budget, FN ceiling, timing
or CPU bounds; prefer C-MT over single-task only if it is non-inferior on participant-paired
lead (95 % CI lower bound above −δ_lead) **and** materially better on FP/min, zone accuracy or
intensity agreement **and** within latency/memory budget; otherwise ship the single-task model,
or Baseline B if only B is feasible. Heads not used by the shipped gate or intensity source are
informational and are dropped if they cost more than δ_cpu at p95. A negative or neutral result
completes the phase (fallback strategy).

Invariant for any outcome: committed zone, `t_impact_pred` and impact position come from
geometry on the predicted trajectory; heads may only gate a geometry candidate, be logged,
or supply the intensity proxy if ADR-0029 selects the head. The no-trajectory diagnostic is
never a ship candidate.

## Development observations (SYNTHETIC; not evidence for this decision)

See `docs/reports/phase-11-head-ablation.md`, `phase-11-gating.md` and `phase-11-per-task.md`.
Fixture results only exercise the machinery; the owner must not read them as a preference.

## Consequences

Phase 13 integrates whichever arm this ADR eventually records (Phase 13 may start with the
Phase 10 arm if the owner decides so). Until then `commit.aux_heads` stays absent/off in every
configuration and no C-MT package is marked for live use.
