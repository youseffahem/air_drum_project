# Phase 17 — Testing, Hardening & Failure Handling

## Status

Planned

## Purpose

Consolidate the test suites from all previous phases into a complete test matrix (unit / integration / system), add **failure-injection** tests for every identified failure mode (tracking loss, occlusion, lighting change, camera stall, frame drops, audio device loss, model fallback, hand swap, background people), enforce the system's **safety invariants** (no commit in `INVALID/STALE`, no future-frame access, refractory respected, one strike per episode, no strike fabrication during switches), run soak tests, decide experimentally whether `DEGRADED` commits may be enabled, and produce a failure catalogue with the system's documented behaviour in each case. This phase hardens the product and protects the validity of Phase 18.

## Why This Phase Exists

Q34–35 and Q60 make safety under tracking loss non-negotiable; Q28–29 require robustness to normal environments and background variation; success criterion 1 requires reliability. Individual phases tested their own components; this phase tests the whole under adverse conditions and turns the failure catalogues of Phases 03, 05, 10 into verified behaviours.

## Relationship to Research Contribution

- Ensures that measured FP/FN in Phase 18 reflect the anticipation method, not unrelated crashes or state bugs.
- Verifies the causality invariant at system level one final time before the confirmatory experiments.
- Documents limitations honestly (success criterion 3).

## Inputs

- Optimised integrated system (Phase 16); all prior test suites; failure catalogues (Phases 03/05/10); dataset sessions with occlusion/tracking-loss/lighting segments (Phase 06 segment types 10–13).

## Expected Outputs

- Test matrix document mapping requirements (RTM) → tests → status.
- Failure-injection test suite and results.
- Safety-invariant test suite (runs in CI and in a live-mode assertion set).
- Soak test results.
- `DEGRADED`-commit experiment result and decision (ADR).
- Failure catalogue with documented behaviour and user-facing messages.
- Error reporting/logging conventions.

## Dependencies

- Phase 16 Exit Gate.

## System Components

- `tests/{unit,integration,system,failure_injection,invariants}/`
- `src/spacedrums/app/health.py` (device/health monitors), `errors.py`
- `scripts/{soak_test, inject_faults}.py`
- `docs/testing/`

## Architecture

```
Fault injectors (replay-from-file and live):
  frame stall / drop bursts / timestamp jumps      ─► capture layer
  synthetic occlusion masks / hand-out-of-ROI       ─► frame preprocessing (replay) or physical (live)
  lighting change (gain/gamma perturbation replay; physical live)
  landmark estimator failure / hand swap injection  ─► hands layer stub
  slow / corrupt model                              ─► model loader / arm
  audio device removal                              ─► audio layer
Invariant monitors (always on in debug/test builds):
  I1 no CommittedStrike while TrackState.status ∉ {VALID (or DEGRADED if enabled)}
  I2 no record consumed with t_capture > current processing frame
  I3 refractory respected per hand×zone
  I4 ≤ 1 commit per geometry episode
  I5 no commit during arm switch/fallback transition window
  I6 audio event never scheduled without a CommittedStrike
```

**Causality rule (README §13):** invariant I2 is the system-level form of the rule — any component labelled causal consumes only observations with timestamp ≤ the current frame's `t_capture`. `TEST-CAUSAL-1/2` (Phase 01) are re-run on the hardened build in both replay and live modes as part of Task 17.2.

## Detailed Tasks

### Task 17.1 — Test Matrix
- **What:** Map every `REQ-xxx` (Phase 00 RTM) to tests by level; identify gaps; add missing tests.
- **Why:** Verification traceability.
- **Depends on:** RTM; all suites.
- **Evidence:** Matrix document; gap list closed or justified.

### Task 17.2 — Safety-Invariant Suite
- **What:** Implement I1–I6 as runtime monitors (raise in test builds, log in release) and as harness assertions over all replayed dataset sessions and developer sessions.
- **Why:** Q34–35, Q60.
- **Depends on:** Phase 05/13 modules.
- **Evidence:** Zero violations over the full replay set (MEASURED count = 0 required).

### Task 17.3 — Failure Injection: Tracking and Vision
- **What:** Replay sessions with injected occlusion (masking the hand region for intervals including ~100–300 ms and longer), hand-out-of-ROI, hand swaps, lighting perturbations; live tests with physical occlusion and lighting changes. Verify state transitions, resets, re-acquisition times (MEASURED), no fabricated strikes, and FP/FN behaviour around the events (via harness).
- **Why:** Q34–35, Q27–29.
- **Depends on:** 17.2.
- **Evidence:** Injection report with traces and counts.

### Task 17.4 — Failure Injection: Capture and Timing
- **What:** Frame stalls, drop bursts, timestamp jumps (non-monotone driver timestamps), FPS changes mid-session; verify drop accounting, `dt` handling in features/model (masking or reset rules), commit guard on drops, no crash.
- **Why:** Real webcams misbehave.
- **Depends on:** 17.2.
- **Evidence:** Report.

### Task 17.5 — Failure Injection: Model and Audio
- **What:** Slow model, corrupt model, wrong schema, model exception mid-session → fallback without fabricated strikes; audio device removal/re-attach → engine recovery, no crash, events logged; underrun bursts → late-event handling.
- **Why:** Product robustness; Phase 13 fallback verified under more conditions.
- **Depends on:** Phase 13.
- **Evidence:** Report.

### Task 17.6 — Background People/Objects
- **What:** Live tests with a second person moving in the background and objects in view; verify that hand identity stays with the user (single-user assumption: choose the hands closest to the ROI band / largest; rule recorded) and that no strikes are produced by background motion.
- **Why:** Q29.
- **Depends on:** Phase 03.
- **Evidence:** Report with counts (developer/volunteer, labelled).

### Task 17.7 — `DEGRADED`-Commit Experiment
- **What:** Using the harness on dataset sessions, compare commits allowed only in `VALID` vs. also in `DEGRADED` (bridge ≤ `g_max`): FN reduction vs. FP increase around occlusion segments and elsewhere. Decide default (ADR).
- **Why:** Phase 01/05 Open Question, resolved with data.
- **Depends on:** Phase 09 harness.
- **Evidence:** Table (MEASURED); ADR.

### Task 17.8 — Soak Test
- **What:** Extended live run (duration recorded; candidate ≥ 1 hour) with periodic scripted playing: memory, drops, underruns, fallback events, crashes.
- **Why:** Demo and experiment reliability.
- **Depends on:** Phase 16.
- **Evidence:** Soak report (MEASURED).

### Task 17.9 — Error Reporting and User Messages
- **What:** Structured error/log conventions; user-facing messages for: camera not found, low FPS, poor tracking (with guidance), model fallback active, audio device issue; crash reports with config/model hashes.
- **Why:** Usability and diagnosability during Phase 18/22.
- **Depends on:** All above.
- **Evidence:** Message catalogue; tests.

### Task 17.10 — Failure Catalogue and Limitations
- **What:** Consolidate: each failure mode → detection → system behaviour → user message → residual risk; explicitly list unresolved limitations (e.g. fast hits beyond the measured rate, dark sticks in dim light, layouts far from recorded ones).
- **Why:** Success criterion 3; Phase 21 limitations section.
- **Depends on:** 17.3–17.8.
- **Evidence:** Catalogue document.

## Data Requirements

- Dataset sessions (for replay injection and the `DEGRADED` experiment); developer/volunteer live sessions for physical injections.

## Algorithms / Technical Approach

- Deterministic replay injection; runtime invariant monitors; harness-based FP/FN accounting around injected events.

## Interfaces / Contracts

- `HealthStatus { camera, tracking, model, audio }` exposed to UI; `FaultInjector` test interface (test builds only).

## Tests

- All levels; the suites listed above; CI runs unit + integration + invariant replay on a small session subset; full replay invariant run before Phase 18.

## Measurements

| Quantity | Label |
|----------|-------|
| Invariant violations over full replay set (must be 0) | MEASURED |
| Re-acquisition time after occlusion | MEASURED |
| FP/FN around injected events per arm | MEASURED |
| `DEGRADED`-commit FN/FP trade-off | MEASURED |
| Soak: memory growth, drops, underruns, fallbacks, crashes | MEASURED |
| Background-motion false strikes (must be reported; target 0) | MEASURED |

## Experimental Design

- Injection at controlled intervals/positions (during approach, at impact, during idle) with replication; per-arm comparison via harness.
- `DEGRADED` experiment: paired comparison on the same sessions.

## Acceptance Criteria

1. Test matrix complete; gaps closed or justified.
2. Zero invariant violations on the full replay set and in live injection tests.
3. All injection categories executed with reports.
4. `DEGRADED` decision recorded.
5. Soak completed without crashes (or crashes fixed and re-run).
6. Failure catalogue and user messages done.

## Definition of Done

- All acceptance criteria; reports; ADR; gate record PASS; integrity checklist applied.

## Risks

- Physical injection tests are labour-intensive → prioritise replay injection; physical for a subset.
- Invariant violations found late → this phase exists to find them before Phase 18; fix and re-run parity/regression.

## Failure Modes

- Background person's hands adopted as the user's → identity rule; report.
- Timestamp jump breaks filters → reset rule; test.

## Fallback Strategy

- If a failure mode cannot be fixed in time, document it in the catalogue with a user message and, if it threatens experiment validity, exclude affected conditions from Phase 18 with justification.

## Artifacts Produced

- `docs/testing/test-matrix.md`, `failure-injection-report.md`, `soak-report.md`, `failure-catalogue.md`, `user-messages.md`
- `tests/…`, `scripts/{soak_test,inject_faults}.py`, `src/spacedrums/app/{health,errors}.py`
- `docs/decisions/ADR-<n>-degraded-commits.md`
- `docs/gates/phase-17-gate.md`

## Exit Gate

Reviewer verifies invariant results, injection reports, soak, catalogue. PASS → Phase 18.

## What Must NOT Be Done Yet

- No participant experiments (Phase 18).
- No model changes (a model change here would require re-running Phases 13/16 checks).

## Open Questions

- Identity rule for the single user among multiple detected people (choose and record).
- Whether to include a "fast-hit limit" test to measure the maximum separable hit rate per arm (recommended; developer only).

## Decisions That Must Be Experimentally Validated

- `DEGRADED` commits default (Task 17.7).
- Frame-drop commit guard threshold (Task 17.4).
- Re-acquisition thresholds `g_max`, `age_max` final values (Tasks 17.3/17.7).
