# ADR-0035 — E5 decoding: residual over causal extrapolation and bounded acceleration

Status: **IMPLEMENTED machinery; adoption PENDING** participant CV under the pre-declared rule.
Date: 2026-09-26. Related: ADR-0018 (Baseline B), ADR-0026; `docs/experiments/phase-12-prereg.md`;
`docs/reports/phase-12-e5-decoding.md`.

## Context

On the SYNTHETIC fixture, Baseline B's straight-line extrapolation predicted impact position and
zone better than the learned trajectory (Phase 11 per-task report), and the worst Phase 10 cases
are reversals. Task 12.7 lists cheap decoding changes that need no new architecture.

## Decision

1. **E5(a) residual over the causal CV extrapolation** (`e5-resb`): the point trajectory is
   `v · τ_k` plus the model's output, where `v` is the current frame's `vx`, `vy` features
   de-normalised with the training fold's centre/scale (saved as model buffers and in the manifest)
   and masked features contribute zero. This is Baseline B's motion model on the model's own causal
   inputs without B's speed/acceleration gates; the equality is tested against
   `prediction.rule_based.extrapolate`. The CA form (`ca`, with `ax`, `ay`) is implemented but not
   declared.
2. **E5(b) bounded-acceleration projection** (`e5-smooth`): decoded points are projected greedily
   so that the second difference, from the second step on, does not exceed `a_max`. `a_max` is the
   99th percentile of that quantity on the fold's **training** targets. The first step is free.
   The projection needs no training and applies to the reference models.
3. **E5(c) resampling to the live `dt`** is Phase 13's input-timing work (ADR-0026) and is not
   attempted here.

## Alternatives considered

- A least-squares projection (QP) onto the bounded-acceleration set: smaller deviations but a
  solver in the inference path; the greedy projection is O(K) and deterministic.
- Residual over CA: the fixture's CA acceleration is a finite difference of smoothed velocities
  and is noisy; CV is B's configured motion model (`anticipator.rule.motion_model: CV`).

## Consequences

- No contract or geometry change; E5(a) is a model-internal change exported with TorchScript.
  E5(b) is a decoder option (`ExtensionAnticipator(a_max=…)`) for a plain displacement model.
- Development observations (SYNTHETIC; `docs/reports/phase-12-e5-decoding.md`): `e5-resb` gave
  the largest paired TCN lead gain of any declared variant (+4.3 ms) but inside the 9.6 ms seed
  band (NO-GO); `e5-smooth` was almost inert (bound 74–81 ROI/s²). They do not decide adoption.
