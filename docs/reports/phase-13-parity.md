# Phase 13 — Offline/online parity

Status: PENDING gate-eligible parity evidence; development replay diagnostics below.
Hardware: HW-01, Intel i7-7820HQ, locked Windows Python 3.11 environment.
Execution date: 2026-09-26 (+03:00). Model/effort: UNVERIFIED by explicit user instruction.

These diagnostics were collected with uncommitted Phase 13 changes (`git_dirty: true`).
Under the reproducibility policy, they cannot establish MEASURED gate status. A clean
post-owner-commit rerun and participant-fold evidence remain required.

## Scope and method

The final evidence run is
`experiments/phase-13/20260926-0928-p13-gate-verification/raw-parity/parity.json`.
The run completed with unchanged source hashes; all verification commands passed.
Inputs are the three existing `data/dev-captures/swing-L2-exp-{5,6,7}` lossless raw
recordings, passed through the production MediaPipe/stick/tracking/application path.
The config, plan, image hashes, feature schema, model manifest and export hashes
are recorded. The pinned GRU was trained on the Phase 10 SYNTHETIC fixture; it is
not a shipped or participant-trained model.

The live output is compared with fresh Phase 09 feature/model/geometry/commit
state on the delivered causal tracks. Per-frame processing delay includes perception
and recorded capture delivery. Masks and all semantic fields are checked; candidate
id allocation and processing-clock exclusions are documented in ADR-0036. Committed
candidate links are independently compared. Export tolerance was retained, not tuned.
The parity config disables fallback so a mismatch fails the check instead of changing
the arm. Budget behavior is tested separately.

## Results

Development diagnostics, all three sessions PASS. Maximum absolute deviations are
zero in every compared stream, including commit-to-candidate links.

| Raw session | Frames | Features | Predictions | Candidates | Commits | Max deviation |
|---|---:|---:|---:|---:|---:|---:|
| DEV-swing-L2-exp-5 | 171 | 342 | 261 | 18 | 1 | 0 |
| DEV-swing-L2-exp-6 | 171 | 342 | 91 | 0 | 0 | 0 |
| DEV-swing-L2-exp-7 | 172 | 344 | 0 | 0 | 0 | 0 |

Features use absolute/relative tolerance 1e-10. Prediction/event numeric fields use
1e-6 absolute and 1e-5 relative tolerance; timestamps use absolute tolerance only.
Commit counts reflect this run's recorded per-frame processing delays and may change
when replay processing speed changes. Online and offline decisions use identical delays.

| Raw session | Prefix frames checked | Changed suffix frames | Causality result |
|---|---:|---:|---|
| DEV-swing-L2-exp-5 | 85 | 86 | PASS |
| DEV-swing-L2-exp-6 | 85 | 12 | PASS |
| DEV-swing-L2-exp-7 | 86 | 0 | PASS |

Exp-5 supplies nonempty prediction/candidate/commit parity. Exp-6 supplies prediction
parity with empty candidate/commit sets. Exp-7 has no model predictions or commits,
and blacking out the suffix changed no tracks; its prediction/commit causality check
is vacuous. Synthetic analytic tests provide additional nonempty two-hand coverage.

## Causality and fault coverage

`TEST-CAUSAL-1` replays each raw session with black images after its midpoint, retaining
original timestamps and baseline decision delays. It checks every earlier feature,
prediction, candidate and commit. The report counts changed suffix tracks to identify
an ineffective perturbation. Unit tests additionally use nonempty analytic trajectories,
both hands, loss/reset, jitter, drops, no-future-observation assertions, negative drift
controls, GRU/TCN exports, switch suppression and shadow audio checks.

## Limits and required evidence

- `ds-v1.0` and the designated participant fold do not exist here. No participant
  parity result is claimed. The plan reader requires every train/validation session
  of a selected fold plus developer sessions before accepting a participant plan.
- Predictions/commits measure agreement of implementations, not strike accuracy.
  No reference labels, participant outcomes or effective latency are inferred.
- Tracker/perception determinism is exercised by raw future perturbation; Phase 09
  consumes causal tracks rather than providing an independent tracker implementation.
- A session without predictions only tests feature/safety behavior. It cannot
  establish nonempty trajectory/commit parity on its own.
