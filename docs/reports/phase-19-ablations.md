# Phase 19 — preparation report

**PREPARATION ONLY; Phase 18 remains PENDING.** No participant experiment, Phase 19
completion, preregistration approval or Phase 20 work is claimed.

Authorized preparation is implemented and checked. An earlier full suite recorded 1,556
passes, one hardware skip and one stale generated-matrix failure. After that document was
regenerated, the final preparation verification reran the complete suite: **1,557 passed,
one hardware skip, no failures**. Every other preparation check passed there, and its
32-cell synthetic results are byte-identical to all earlier complete runs. The earlier
failure remains visible in its retained log; details and source audits are below.

## Status and implementation

| Area | Status | Scope |
|---|---|---|
| Feature masks | IMPLEMENTED | Values and masks zeroed after train-fold normalization; F retained; redundant cues listed and hashed |
| History/horizon switches | IMPLEMENTED | Fresh training; rebuilt windows/targets; exact full-signature reuse check |
| Structural variants | IMPLEMENTED | Existing direct-head diagnostic, A/B harnesses, auxiliary/intensity switches |
| Frame dropping and retracking | IMPLEMENTED | Retained raw timestamps/IDs, fresh tracker/features, unchanged labels; production perception injection interface |
| Paired analysis | IMPLEMENTED | Exact cell pairing, participant aggregation/bootstrap, pooled seed band, explicit null/infeasible support |
| Manifests/reports | IMPLEMENTED | Source/config/plan/model/normalization/event/artifact hashes; stored-result regeneration; forest data/plot |
| Dependency protection | IMPLEMENTED | Missing/changed inputs, invalid approvals/gates, undeclared or test sessions refused; execution disabled |
| ADR-0036 engineering | IMPLEMENTED | Schema 1.9, independent B rule/horizon, per-arm commit/geometry, auditor deadlines, locked-setting checks |
| Study results and interpretation | REQUIRES PARTICIPANT DATA | No participant estimates supplied |
| Exact study plan and operating point | REQUIRES FROZEN REFERENCE | Final reference/model/budgets/W/delay unavailable |
| Live amendment acceptance | PENDING PHASE 18 | Actual locked settings, live recordings and reviewer decision |

The Phase 09 harness and existing training/model algorithms are reused. New ablation code
is above the evaluation layer; causal runtime modules cannot import labels or ablation
machinery. A/B synthetic comparisons exercise their existing paths. The future participant
study must use their frozen reference settings.

The deterministic fixture intentionally leaves CPU latency null. That value is not zero
and cannot establish a performance claim. Existing isolated Phase 10/11 timing utilities
remain the basis for later measurements. Native 60 FPS is not inferred from downsampling.

## Verification record

Execution began on clean Git HEAD `68c640181a48552c4b4bce63d1414323bcd2680f`.
Preparation leaves that SHA unchanged and the worktree dirty. Actual executor model and
reasoning setting cannot be verified in this session: `UNVERIFIED (Codex session)` and
`UNVERIFIED`. Every new execution record preserves that limitation.

### Dependency baseline before source edits

- `experiments/phase-19/dependencies/20260927-1740-p18-gate-verification/`:
  1,499 passed, one hardware test skipped; ruff/imports/contracts/environment/test matrix
  and preregistration-hash verification passed. Synthetic methods and live rehearsal,
  labels, sync and analysis passed.
- The offline branch of that invocation failed because an existing lock builder requires
  an absolute output path. Its failure logs are retained. No gate PASS is inferred.
- Absolute-path retry at `dependencies/absolute-retry/20260927-1757-rehearsal-lock/`,
  `20260927-1800-offline-rehearsal/` and `20260927-1812-regenerate/` passed. All six
  synthetic locked arms passed causality checks. Regeneration matched all nine tables,
  six figure datasets and PNGs; regeneration from raw inputs had zero differences.
  These were SYNTHETIC rehearsal checks on the unchanged clean SHA.

### Preparation verification — TESTED, SYNTHETIC/DEV ONLY

`experiments/phase-19/20260927-1833-preparation-verification/` passed all checks:

- 53 focused tests: masks, one-factor validation, both model families' causal window
  boundaries, structural switches, raw-frame/retracking prefix invariance, identical
  repeated training/replay, pairing/bootstrap, file and identity guards, per-arm settings,
  C-arm live/offline parity, sticky fallback, auditor deadlines and calibration version retention.
- Ruff, seven import contracts, schema validation, environment smoke, test-matrix freshness,
  whitespace/diff and the unchanged Phase 18 preregistration hash check passed.
- Missing-reference preflight and experimental execution each returned the required refusal
  (exit 2). The latter refuses before opening any supplied reference or data path.
- The complete generated plan ran 32 cells (reference plus 15 variants, one synthetic CV
  fold and two seeds). Every evaluated cell passed the exact-adapter causal self-check.
  FPS and tip study runs stayed PENDING raw reference recordings; their transformation
  interfaces were tested separately. No `samples.test.npz` was exported.
- Stored report regeneration matched. All 32-cell results also exactly matched the first
  complete synthetic run at `20260927-1825-preparation-verification/20260927-1827-synthetic-dev/`.
  That earlier verifier failed only its untracked-file CRLF check; its logs are retained.
  New files now use LF. A later identity guard rejects mismatched CV metadata before any
  stream opens, with its own negative-control test in the final 53-test run.
- The final verification's source snapshot was unchanged throughout. Full-suite execution
  is explicitly skipped in this wrapper because it is recorded by the dependency verifier below.

All 15 primary comparisons in the short fixture have undefined paired feasible estimates.
The forest figure therefore contains no effect markers. This is not a null scientific
finding. Separate controlled statistical tests establish known paired effects, missing-data
behavior and bootstrap reproducibility. No participant or performance conclusion is drawn.

### Dependency re-verification after the amendment

Phase 17 run `dependencies-final/20260927-1836-p17-gate-verification/` preserved its
unchanged-source audit. All twelve non-pytest checks passed: lint/imports/contracts,
environment/diff/matrix, frozen Phase 16 regression, raw Phase 13 parity, invariant replay,
failure injection, degraded tracking and reacquisition. The last three campaigns used
their explicit reduced grids (`--quick-campaigns`). Invariant replay covered 96 replays,
11,598 frames and 387 audited commits, with zero live-loop/harness violations and passing
future-frame causality checks. The eight-suite fault campaign had no crashes or invariant
violations; it retains induced detection errors and the `corrupt_export_rehashed` case
without fallback. These development outcomes do not close live robustness obligations.

That run remains failed overall: pytest reported 1,551 passed, one skipped and one stale
schema test that expected version 1.9 to be unknown. Version 1.9 now defines per-arm live
settings. The assertion now rejects version 1.10; all 35 config-schema tests passed after
the correction. At that point, this was the only source-file change since the successful
Phase 19 preparation run and the Phase 17 runtime checks. Their original failure logs are retained.
`experiments/phase-19/source-transition-audit.json` verifies that exact one-file difference.

Phase 18 verification after the schema-test correction is at
`dependencies-final/20260927-1913-p18-gate-verification/`. Its full suite passed:
**1,552 passed, one skipped, 139 warnings in 647.47 seconds**. Ruff, all seven import
contracts, schemas, environment, diff, test-matrix freshness, the unchanged preregistration
hash/citation and synthetic external-method self-test also passed. Rehearsal lock creation,
synthetic live recording, labels, sync and analysis passed, with an unchanged-source audit.
The offline branch exposed a mixed-inventory integration error: its package scan assumed
every pinned file had a Python package path, but the amended lock also freezes the base
configuration. Replay failed before loading data; regeneration consequently had no input.
Those failure logs are retained and this wrapper is not reported as a pass.

The source verifier now hashes all pinned files and scans only package paths for newly
added Python files. Five new regression cases cover an unchanged inventory, changed and
missing configuration, changed source, and added source; all 11 Phase 18 script tests passed.
The final repository/preparation verifier is `20260927-1932-preparation-verification/`.
Its full suite recorded **1,556 passed, one skipped, one failed** in 694.46 seconds. The
failure was the generated test matrix, which still counted six functions in the Phase 18
script test file instead of seven. The matrix was regenerated; all three matrix tests
then passed, and the verifier's subsequent matrix-freshness check passed. The full-suite
failure log is retained; the full suite was not repeated for this documentation-only fix.
All other checks in that verifier passed: 53 focused tests, ruff, seven import contracts,
schemas, environment, refreshed matrix, unchanged preregistration hash, both dependency
refusals, the 32-cell synthetic run, report regeneration and diff checks. Source hashes stayed
unchanged and no untracked whitespace problems remained. The latest synthetic results and
report manifest exactly match the earlier complete run, so all three 32-cell runs agree.
`experiments/phase-19/final-review/final-checks.json` records the retained full-suite result,
successful matrix rechecks and exact result/report comparisons. The wrapper's original
failed status is preserved rather than relabelled as a clean full-suite pass.

The affected offline replay and raw regeneration passed at
`dependencies-final/20260927-1932-p18-offline-reverification/`, using the already-built
synthetic lock with unchanged runtime/configuration pins. All six locked arms passed
causality checks; the evaluation and live-evaluation self-tests passed (7 and 52 tests).
Regeneration matched nine tables, six figure datasets and all six PNGs. Raw regeneration
had zero differences. The retry's source audit was unchanged throughout.

`experiments/phase-19/final-source-transition-audit.json` records the exact differences
between verification snapshots: the source-inventory verifier and two test files. Runtime
libraries, schemas and configurations stayed identical. Every Phase 17/18 machine-check
branch has now been exercised successfully at its stated scope; neither phase gate is
approved by these checks. Clean-SHA owner verification and all person-dependent work remain pending.

### Final preparation verification — complete suite after the matrix correction

`experiments/phase-19/20260927-2025-preparation-verification/` is the final preparation
verification. It started from the unchanged working tree after the matrix regeneration
(matrix `sha256:b1179f14…c3d381`, freshness check passed before launch) and ran the same
wrapper without `--skip-full`. The wrapper passed all 13 checks and exited 0:

- Full suite: **1,557 passed, one skipped, no failures, 139 warnings in 614.70 seconds**.
  The skip is the webcam module (`SPACEDRUMS_HW_TESTS` unset). The earlier run's one
  failure is now a pass; the collected total is unchanged.
- 53 focused tests, ruff, all seven import contracts, schema validation, environment smoke,
  test-matrix freshness, `git diff --check` and the untracked-file whitespace check passed.
- The Phase 18 preregistration check passed: version 1, `sha256:e901f280…793ba0`, no problems.
- Dependency guards: the missing-reference preflight returned BLOCKED (19 missing frozen
  inputs) and `--execute` was refused before opening any input, both with exit 2.
- The 32-cell synthetic run's `results.json` (`sha256:3305c20c…87e1ec`) and report manifest
  (`sha256:79c848c3…bb8870`) are byte-identical to the 1825, 1833 and 1932 runs. Stored-result
  regeneration matched. The source snapshot stayed unchanged in the wrapper and synthetic audits.

`experiments/phase-19/final-verification/final-verification.json` records these results. It
also shows the eight Phase 18 protected files byte-identical to HEAD and the earlier audit, the
preregistration ledger with one version, no locks and no approvals, and Phase 20 untouched.
Git HEAD is `68c6401…` with a dirty worktree of 55 changed entries, matching the file inventory.
This run was executed in a Claude Code session and records its executor as
`claude-opus-5-5 (Claude Code session; self-reported, not independently verified)` with effort
`UNVERIFIED`. That is not verified attribution. No participant data, participant claim or
approval was introduced; every result above is SYNTHETIC/DEV.

## Files and protected artifacts

See the [complete file inventory](phase-19-files.md). The changes include ablation tooling,
schemas/configs, runtime and audit integration, tests, and preparation documentation.
`experiments/phase-19/final-protected-input-audit.json` compares the eight tracked Phase 18
preregistration/ledger/report files against HEAD; all are byte-for-byte unchanged. It also
checks the 55-file inventory, empty approval/lock lists, unchanged Git SHA and untouched Phase 20.

## Boundaries and remaining limitations

The checked-in protocol is a DRAFT, not archived or approved. The repository contains
no Phase 19 participant reference example, no invented ds-v1.0 and no participant results.
The Phase 18 preregistration text/hash ledger, its experimental reports/results, and all
approval entries remain untouched. New synthetic artifacts are under `experiments/phase-19/`.

The synthetic plan is a machinery fixture, with candidate constants, short training and
generated grouping identities. Its operating selector exercises FP/FN feasibility only;
it does not replace the pending participant timing/CPU constraints. Null metrics and
insufficient statistical support are retained rather than filled in.

The Phase 19 study is blocked until all owner actions in the
[preparation gate record](../gates/phase-19-gate.md) are satisfied. The Phase 18 obligations
listed there remain open, including participant data/results, live and external timing,
participant regeneration, approvals/frozen inputs, live ADR-0036 verification, reviewer
decision and executor attribution. No commit, tag or push was made.
