# Phase 09 — Exit Gate

Submitted 2026-09-22. Submitter: Codex. Reviewer: project owner, pending.
**Proposed verdict: FAIL for the full Phase 09 Definition of Done.**

The reusable harness, synthetic validation, Phase 05 developer-session replay,
A/B self-test sweeps, and C-GBDT training/inference machinery are implemented.
Development verification: `experiments/phase-09/20260922-2326-p09-development-verification/run.json`.
That completed run passed all 12 development checks.
All nonparticipant numbers are labelled SYNTHETIC or DEV CAPTURE, and the run is
`git_dirty: true`. No participant result is represented as measured thesis evidence.

| Exit criterion | Current status |
|---|---|
| Synthetic harness and causal validation | IMPLEMENTED; development tests |
| Developer-session commit reproduction | IMPLEMENTED; exact A commit stamps |
| A/B fold and held-out participant results | BLOCKED: reviewed `ds-v1.0` absent |
| Primary W freeze | BLOCKED: validation participants absent; candidate default only |
| C-GBDT models per participant fold and both event modes | BLOCKED: participant Phase 08 exports absent |
| CPU latency on participant-trained models | BLOCKED; synthetic fixture timing only |
| Frozen templates/harness and clean-tree reproduction | PENDING owner commit and data-backed review |

## Closure conditions

1. Close Phase 07 C-07-6 and Phase 08 C-08-1: consented recordings, reviewed
   geometric labels, frozen `ds-v1.0` manifest and participant splits, and
   Phase 08 fold samples/stats with verified provenance.
2. Run A/B validation folds at zero and measured stage-delay policies, choose W
   using ADR-0023, set and record FP/FN budgets and validation operating points
   using ADR-0024, then evaluate held-out participants once.
3. Train participant C-GBDT fold models, evaluate direct and trajectory modes
   through replay, produce per-participant/pooled tables and curves, and measure
   batch-one CPU latency on those models.
4. Commit the implementation, rerun the complete verification on a clean tree,
   freeze the harness source hash and reporting format, and obtain reviewer verdict.

No gate PASS or claim that anticipation improves participant action-to-sound
latency is warranted by the current inputs.
