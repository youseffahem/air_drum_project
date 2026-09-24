# Phase 20 — Final Integration & Release Candidate

## Status

Planned

## Codex Model for This Phase

- **Model:** GPT-6 Astra
- **Reasoning effort:** Extra High
- **Recommended profile:** Systems Integration / ML Engineering
- **Why this choice:** The release candidate freezes model/configuration hashes and combines all arms, calibration, dashboard, hardening, presets, and the full regression suite. Astra fits the large autonomous integration; Extra High is justified by cross-phase dependency tracing and proving the shipped behavior still matches the evaluated system.

> Set the model and reasoning effort in the Codex picker before running this phase.
> This section is a workload recommendation only; text in the prompt does not switch the active model.
> Record the actual model and reasoning setting used in the phase evidence.
> If the recommended model is unavailable, use the strongest available compatible model and record the actual setting used.
> The selected model is not a substitute for tests, acceptance criteria, or empirical evidence.

## Purpose

Freeze the evaluated configuration (models, thresholds, zone layouts, calibration defaults, `Δ_proc` constants), integrate every component into a single release candidate (RC) build of the application with all arms, the calibration wizard, the debug dashboard, hardening, and error handling; run the full regression suite (unit/integration/system/invariants/parity/causality) against the RC; produce demo-safe default configurations; and publish a known-issues list. No new features, no model changes.

## Why This Phase Exists

Phases 13–19 modified the system and produced evaluation results tied to specific hashes. The RC guarantees that what is demonstrated (Phase 22), documented (Phase 21), and packaged (Phase 23) is exactly what was evaluated (Phase 18/19), with every hash recorded.

## Relationship to Research Contribution

Preserves the evaluated system unchanged; ensures the demo and thesis refer to the same artefacts as the measurements.

## Inputs

- All Exit Gates 14–19; ship ADRs; Phase 18/19 reports and manifests; Phase 17 failure catalogue.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-001, REQ-004, REQ-006, REQ-050a, REQ-056.

## Expected Outputs

- `configs/release/rc1.yaml` (frozen; includes model hashes, layout, thresholds, calibration defaults).
- RC build (version tag `v1.0-rc1`), with a build manifest (git SHA, dependency lock hash, model hashes, dataset/labels versions used for evaluation).
- Full regression run results on the RC.
- Demo-safe defaults (arm choice per ship ADR, fallback enabled, experiment-mode overlay presets).
- Known-issues list (from Phase 17 catalogue + anything new).
- RC review record.

## Dependencies

- Phases 14–19 Exit Gates.

## System Components

- Whole application; `scripts/build_rc.py`, `scripts/run_full_regression.py`; `docs/release/`.

## Architecture

No architectural change. Integration checklist:

1. Config freeze — every tunable value in the RC config traced to the ADR or report that set it (Target vs. Measured labels for any value that is a planning target).
2. Model freeze — exported model files with hashes matching Phase 18 manifests.
3. Arm defaults — active arm per ship ADR (C, or B if C was not adopted); fallback enabled; shadow logging optional.
4. Calibration — wizard on first run; default layout as fallback.
5. Dashboard — experiment-mode preset and demo preset.
6. Hardening — health monitors and user messages enabled.
7. Logging — session logs with all hashes; privacy defaults (no raw video retention unless record mode is explicitly enabled by the user).

## Execution Instructions

- When this phase is authorized, automatically perform any outstanding post-owner-commit verification for its dependency phases on the current Git HEAD before dependent work; record the SHA, dirty state, and results. A commit alone does not satisfy a gate.
- Execute the entire phase end-to-end in the stated task order and automatically run executable gate conditions, without task-by-task or condition-by-condition prompting. Preserve all dependencies, optional-scope decisions, acceptance criteria, and evidence rules.
- Never fabricate participant evidence or substitute synthetic/developer evidence for it. Unavailable evidence and owner-only decisions remain PENDING; continue independent executable work and report blockers at the Exit Gate.
- Stop only at this phase's Exit Gate for owner/reviewer action under the [gate procedure](../docs/gates/gate-procedure.md). Commit, tag, and push remain owner-controlled, including release tags. Do not start another phase. When the next phase is authorized, automatically verify this phase's outstanding post-owner-commit conditions before dependent work.

## Detailed Tasks

### Task 20.1 — Configuration Freeze and Traceability
- **What:** Assemble `rc1.yaml`; for each value add a comment/reference to its source (ADR/report/task); mark any residual planning targets explicitly.
- **Why:** Reproducibility; no silent values.
- **Depends on:** All ship ADRs.
- **Evidence:** Config with references; traceability check script passes.

### Task 20.2 — Model and Artefact Freeze
- **What:** Copy exported models with manifests into the release tree; verify hashes against Phase 18 manifests; loader refuses mismatches.
- **Why:** Same model as evaluated.
- **Depends on:** 20.1.
- **Evidence:** Hash verification log.

### Task 20.3 — RC Build
- **What:** Build from a tagged commit with the dependency lock; produce a build manifest; smoke run.
- **Why:** Identifiable artefact.
- **Depends on:** 20.2.
- **Evidence:** Build manifest; tag.

### Task 20.4 — Full Regression on RC
- **What:** Run all suites (unit, integration, system, invariants over the replay set, `TEST-PARITY-1`, `TEST-CAUSAL-1/2` live mode, Phase 16 regression check vs. reference metrics, soak short run).
- **Why:** The RC must equal the evaluated behaviour.
- **Depends on:** 20.3.
- **Evidence:** Regression report; zero invariant violations; parity pass.

### Task 20.5 — Demo-Safe Defaults and Presets
- **What:** Presets: `demo` (active arm per ADR, fallback on, dashboard demo preset, audio buffer per Phase 04/16), `experiment` (experiment-mode overlay, shadow logging on), `safe` (Arm A only) for adverse conditions; documented switching.
- **Why:** Phase 22 fallback plans.
- **Depends on:** 20.4.
- **Evidence:** Preset files; tested switch.

### Task 20.6 — Known-Issues List
- **What:** Consolidate from Phase 17 catalogue, Phase 18 limitations, Phase 19 findings; severity; workaround; whether it affects the demo.
- **Why:** Honesty; demo risk management.
- **Depends on:** 20.4.
- **Evidence:** `KNOWN-ISSUES.md`.

### Task 20.7 — RC Review
- **What:** Owner/supervisor review of the RC against success criteria 1–3 with the evidence pointers; decision: RC accepted / fixes required (fixes limited to bugs; any behavioural change requires re-running affected regression and, if evaluation-relevant, a documented note that results predate the fix).
- **Why:** Gate.
- **Depends on:** 20.1–20.6.
- **Evidence:** Review record.

## Data Requirements

- Replay regression set (existing). No new data.

## Algorithms / Technical Approach

- None new. Hash verification; regression tolerances from Phase 16.

## Interfaces / Contracts

- Build manifest schema; release config schema (superset of Phase 01 config with `release` block: version, hashes).

## Tests

- Everything (Task 20.4).

## Measurements

| Quantity | Label |
|----------|-------|
| Regression deltas vs. reference metrics on the RC | MEASURED |
| Invariant violations (must be 0) | MEASURED |
| Startup time, memory, CPU at idle and during play (informational) | MEASURED |

## Experimental Design

Not applicable (no new experiments; regression only).

## Acceptance Criteria

1. Frozen config with full traceability; model hashes verified.
2. RC built from a tagged commit with a manifest.
3. Full regression passes; zero invariant violations; parity and causality pass.
4. Presets and known-issues list exist.
5. RC review record: accepted.

## Definition of Done

- Acceptance criteria; gate record PASS; integrity checklist applied (RC behaviour = evaluated behaviour, or differences documented).

## Risks

- A bug fix changes behaviour → documented; evaluation results labelled Historical if affected, re-run if feasible.
- Dependency drift → lock file.

## Failure Modes

- Wrong model shipped → hash verification.
- Config value with no source → traceability check fails.

## Fallback Strategy

- If Arm C cannot be shipped as default, RC ships with Arm B default and C selectable; documented.

## Artifacts Produced

- `configs/release/rc1.yaml` + presets; `models/release/…`; build manifest; tag `v1.0-rc1`
- `docs/release/regression-rc1.md`, `KNOWN-ISSUES.md`, `docs/release/rc1-review.md`
- `docs/gates/phase-20-gate.md`

## Execution Environment Record

The Phase execution evidence MUST record:

- Codex model actually used
- Reasoning effort actually used
- execution date/time (with timezone)
- Git HEAD SHA at start
- Git HEAD SHA at final verification
- git_dirty state (at start and final verification)

Do not claim that the recommended model was actually used unless the execution evidence records it.

## Exit Gate

RC accepted. → Phases 21 and 22.

## What Must NOT Be Done Yet

- No new features, no model retraining, no threshold tuning.
- No packaging/installer (Phase 23).

## Open Questions

- Default active arm if Phase 18 results are mixed (owner decision recorded in the ship ADR).

## Decisions That Must Be Experimentally Validated

- None new; regression only.
