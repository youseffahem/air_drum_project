# Phase 09 — Harness validation

Status: DEVELOPMENT VERIFIED on synthetic and developer inputs; participant validation pending.
Run evidence: `experiments/phase-09/20260922-2326-p09-development-verification/run.json`
(dirty-tree development run). The executable checks are in `tests/eval/`.
The run completed all 12 checks: focused and full regression tests, Ruff,
import-linter, A/B replay on both available inputs, three synthetic GBDT fold
diagnostics, trained-model event replay, and CPU timing.

## Known-answer checks

| Case | Expected | Observed | Evidence |
|---|---|---|---|
| Analytic straight downstroke, crossing at t=10.075 s | A commits on first inside frame at t=10.080 s, lead −5 ms | Exact in test | SYNTHETIC unit |
| Add 12 ms processing delay | A commit shifts by 12 ms | Exact in test | SYNTHETIC unit |
| CV extrapolation on the same stroke | B commits at t=10.040 s for predicted crossing t=10.075 s, lead +35 ms | Exact in test | SYNTHETIC unit |
| Stop above impact surface | A makes no commit | Exact in test | SYNTHETIC unit |
| Future track change after a cut | A/B and model modes have identical prefix candidates/commits | PASS | CAUSAL test |
| Matching tie, tolerance boundary and wrong-zone match | Deterministic one-to-one assignment; wrong zone enters confusion table | PASS | UNIT test |
| Overlapping accepted/loss intervals | Union subtraction, no double count | PASS | UNIT test |
| Mixed matched/FP rows | Parquet retains all event columns and nulls | PASS | SERIALIZATION test |

The existing Phase 05 developer replay `dev-p05-swing-L2-exp-5` is reconstructed from its
recorded causal TrackState stream, exact per-frame `t_frame_available - t_capture` delays
and dropped-frame counts. The A commit projection (frame, hand, zone, `t_commit`) matches
both recorded commits exactly. This is DEV CAPTURE reproduction, not participant accuracy.

The harness reuses `GeometryEngine` and `PerHandCommitPolicy` without copied decision
logic. Each replay owns fresh hand state. Model replay consumes aligned Phase 08 causal
feature records and only exposes the current window to its adapter.

## Remaining validation

The Phase 08 participant parity gate, clean committed-tree rerun, participant W selection,
and measured-delay participant replay have not happened. `W_PRIMARY_S` is unset.
`docs/decisions/ADR-0023-matching-tolerance-and-active-time.md` records the selection rule.
