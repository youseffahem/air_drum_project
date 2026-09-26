# ADR-0033 — E3 Tiny Transformer (arm C-TT): CPU feasibility gate and go/no-go (REQ-044)

Status: **Feasibility gate MEASURED on HW-01 (development CPU compute, dirty tree): FEASIBLE.**
Adoption **PENDING** participant CV under the pre-declared rule. Date: 2026-09-26.
Related: ADR-0007, ADR-0026, ADR-0027; `docs/experiments/phase-12-prereg.md`;
`docs/reports/phase-12-e3-tiny-transformer.md`.

## Context

REQ-044 asks for a Tiny Transformer evaluation "only if computationally justified", selecting on
validation performance **and** real-time CPU cost. Phase 12 Task 12.5 requires the justification
before training: the batch-1 CPU latency of a randomly initialised model decides feasibility.
No Phase 13/16 CPU budget exists yet, so the pre-registration declared the fallback budget
F × the Phase 10 reference latency, F = 3.

## Decision

1. **Architecture (candidate).** Causal self-attention encoder over the last N frames: tokens are
   the Phase 10 masked inputs `[x * mask, mask]` projected to width 16; two pre-LayerNorm blocks
   (2 heads, feed-forward 32, GELU); a learned relative-position bias per head indexed by the frame
   distance i − j; every future position masked before the softmax; readout at the current frame;
   the Phase 10 displacement head. Time enters through the fs-v1 `dt` and `window_elapsed` features
   inside each token. LayerNorm acts per token, so there is no statistic over time. The module is
   `models/temporal/ext/{attention,tiny_transformer}.py`. The replay gained the arm label
   `MODEL:C-TT` (`Arm.C_TT` already existed in the contracts); geometry and commit are unchanged.
2. **Feasibility gate (measured before any TT training).** Run
   `experiments/phase-12/20260926-0519-tt-feasibility`: random-initialised TorchScript GRU, TCN
   (Phase 10 development size) and TT, batch 1, one thread, 10 interleaved blocks × 100 calls.
   p95: GRU 3.358 ms, TCN 3.211 ms, TT 3.762 ms. Budget 3 × 3.358 = 10.074 ms. **Verdict
   FEASIBLE.** A width-32 TT (21,096 parameters) was timed for information only (p95 2.415 ms).
   These p95 values are higher than Phase 11's isolated GRU/TCN measurements (1.63/1.34 ms);
   the cause was not investigated (random inputs and weights, a different session and background
   load are all possible). The rule therefore compares models only within one session.
3. **Adoption.** Only by the pre-declared go/no-go rule on participant CV folds, compared against
   both reference families, and only on the target CPU's budget once Phase 13/16 defines it.

## Alternatives considered

- Attention on top of the GRU/TCN state: not attempted (a second architecture to validate; TT
  alone answers REQ-044).
- Absolute (learned or sinusoidal) positional encoding: rejected in favour of a relative bias,
  which does not depend on where the window starts.
- Bidirectional attention inside the window: forbidden (Phase 12 "What must not be done";
  README section 13), even though all positions precede the current frame.

## Consequences

- REQ-044's CPU half has development evidence on HW-01. The accuracy half and the target-CPU
  re-measurement remain PENDING, and the clean-tree rerun is a gate condition.
- The development result on the SYNTHETIC fixture is reported in
  `docs/reports/phase-12-e3-tiny-transformer.md`: feasible in 12/12 cells, path 0.75 × the slower
  reference, paired lead +2.7 ms against TCN inside the 9.6 ms seed band (NO-GO). It is not evidence
  for adoption.
