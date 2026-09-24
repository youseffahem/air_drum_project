# Phase 23 — Final Packaging & Release

## Status

Planned

## Codex Model for This Phase

- **Model:** GPT-6 Sol
- **Reasoning effort:** High
- **Recommended profile:** Release Engineering / Reproducibility
- **Why this choice:** Packaging verifies the accepted bundle, archive manifests, checksums, installation, licences, consent-scoped dataset decision, and final status table. Sol fits these specified release checks; High covers artifact integrity and evidence traceability, while owner and institutional decisions remain explicit gate inputs.

> Set the model and reasoning effort in the Codex picker before running this phase.
> This section is a workload recommendation only; text in the prompt does not switch the active model.
> Record the actual model and reasoning setting used in the phase evidence.
> If the recommended model is unavailable, use the strongest available compatible model and record the actual setting used.
> The selected model is not a substitute for tests, acceptance criteria, or empirical evidence.

## Purpose

Package the accepted RC as the final release (`v1.0`): installable application bundle with models, configs, presets, sample bank (licensed), documentation, and hashes; archive the project (code, docs, experiment manifests, result files, thesis material) with integrity hashes; decide and, if permitted, execute the dataset release (consent-dependent) with the dataset card; record the final per-phase status table (PLANNED / IMPLEMENTED / MEASURED / VALIDATED / PENDING) and the final requirements coverage; select licences.

## Why This Phase Exists

The project's outputs must survive beyond the demo: a reproducible archive, a runnable release for users/evaluators, and — if consent and policy allow — a reusable dataset (Q49). The final status table is the last integrity check: it states plainly what was done, measured, validated, and left pending.

## Relationship to Research Contribution

Preserves the evidence and the artefacts; enables future research on the dataset and code.

## Inputs

- Accepted RC (Phase 20); thesis material (Phase 21); demo assets (Phase 22); consent records; institutional rules on data release; licences of dependencies and samples.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-049 (dataset release), REQ-052 (offline bundle), REQ-201 to REQ-210 (coverage audit).

## Expected Outputs

- `v1.0` release bundle + installation guide + checksums.
- Project archive (code at tag, docs, experiments, manifests, models, results; raw data excluded unless released) with a top-level `ARCHIVE-MANIFEST.json`.
- Dataset release decision record; if released: pseudonymised dataset package (raw video only if consented and permitted; otherwise derived tracks/labels only), dataset card, licence, access conditions.
- Final status table and requirements coverage.
- Licence files (code, models, samples, dataset).
- Handover notes.

## Dependencies

- Phases 21 and 22 Exit Gates.

## System Components

- `scripts/{build_release, build_archive, build_dataset_release}.py`; `docs/release/`; `LICENSE*`.

## Architecture

```
RC tag ──► build_release ──► bundle (app + models + configs + samples + docs) + SHA-256 manifest
repo + docs + experiments + models + results ──► build_archive ──► archive + ARCHIVE-MANIFEST.json
ds-v1.0 + consent scope ──► release decision ──► (a) full, (b) derived-only, (c) none ──► dataset package + card
gates 00–23 ──► final status table
```

## Execution Instructions

- When this phase is authorized, automatically perform any outstanding post-owner-commit verification for its dependency phases on the current Git HEAD before dependent work; record the SHA, dirty state, and results. A commit alone does not satisfy a gate.
- Execute the entire phase end-to-end in the stated task order and automatically run executable gate conditions, without task-by-task or condition-by-condition prompting. Preserve all dependencies, optional-scope decisions, acceptance criteria, and evidence rules.
- Never fabricate participant evidence or substitute synthetic/developer evidence for it. Unavailable evidence and owner-only decisions remain PENDING; continue independent executable work and report blockers at the Exit Gate.
- Stop only at this phase's Exit Gate for owner/reviewer action under the [gate procedure](../docs/gates/gate-procedure.md). Commit, tag, and push remain owner-controlled, including release tags. Do not start another phase. When the next phase is authorized, automatically verify this phase's outstanding post-owner-commit conditions before dependent work.

## Detailed Tasks

### Task 23.1 — Release Bundle
- **What:** Build from the RC tag (or a `v1.0` tag identical in behaviour, regression re-run if any commit differs); include install instructions for the supported OS, hardware notes (camera profile, CPU used in measurements), first-run calibration guide; checksums.
- **Why:** Runnable deliverable.
- **Depends on:** Phase 20.
- **Evidence:** Bundle installs and runs on a clean machine (recorded).

### Task 23.2 — Project Archive
- **What:** Archive code, docs, ADRs, gate records, experiment manifests and results, models with hashes, thesis sources/figures, demo assets; exclude raw participant data unless released; produce `ARCHIVE-MANIFEST.json` with hashes and a README describing structure.
- **Why:** Reproducibility and handover.
- **Depends on:** Phases 20–22.
- **Evidence:** Manifest verification script passes.

### Task 23.3 — Dataset Release Decision and Package
- **What:** Check consent opt-ins (Phase 00 form (ii)/(iii)) per participant and institutional policy; decide: full release (only participants who consented; others excluded), derived-only (tracks/labels/metadata without video), or none; if releasing: pseudonymisation check (no faces if the ROI includes them — Open Question: does the ROI include faces? If so, video release requires blurring or is not released), dataset card, licence, access conditions (e.g. request-based), versioned package with hashes.
- **Why:** Q49; ethics.
- **Depends on:** Consent records.
- **Evidence:** Decision record; package + card if released.

### Task 23.4 — Licences
- **What:** Choose and add licences for code, models, documentation, dataset (if released); verify third-party licences (samples, dependencies) compatibility; list in `THIRD-PARTY-NOTICES.md`.
- **Why:** Legal clarity for reuse.
- **Depends on:** Phase 04 sample licences; dependency list.
- **Evidence:** Licence files; notices.

### Task 23.5 — Final Status Table
- **What:** One row per phase: status (PLANNED / IMPLEMENTED / MEASURED / VALIDATED / PENDING), key evidence links, open items; plus success criteria 1–3 with their evidence and status; plus the list of PENDING measurements (e.g. external latency method if it failed, 60 FPS if not achieved).
- **Why:** README §4; Q60.
- **Depends on:** All gates.
- **Evidence:** `FINAL-STATUS.md`.

### Task 23.6 — Handover Notes and Future Work
- **What:** How to continue: kick/foot zone (architecture hooks), depth, external camera/60 FPS, free-play protocol, MIDI, multi-user, realistic visuals, learned segmentation; open questions list consolidated from all phases.
- **Why:** Continuity.
- **Depends on:** All.
- **Evidence:** `HANDOVER.md`.

## Data Requirements

- Consent records; `ds-v1.0` for the release decision.

## Algorithms / Technical Approach

- Hashing; packaging; optional face-blurring if video release is pursued (would need a documented method and verification — Pending decision).

## Interfaces / Contracts

- Release bundle layout; archive manifest schema; dataset package layout.

## Tests

- Clean-machine install test; archive manifest verification; dataset package integrity and pseudonymisation checks.

## Measurements

- None new. Install test outcome recorded.

## Experimental Design

Not applicable.

## Acceptance Criteria

1. Release bundle built, checksummed, installed on a clean machine.
2. Archive built with verified manifest.
3. Dataset release decision recorded; package and card if released; consent compliance verified.
4. Licences and third-party notices in place.
5. Final status table and handover notes complete.

## Definition of Done

- Acceptance criteria; final gate record PASS; integrity checklist applied to the final status table (statuses match evidence).

## Risks

- Consent scope does not permit release → derived-only or none; documented.
- Faces in ROI → video release blocked or blurred; decision recorded.

## Failure Modes

- Archive missing a manifest referenced by the thesis → verification script cross-checks thesis manifest references.

## Fallback Strategy

- Release code/models/docs without dataset; dataset available on request under conditions if permitted.

## Artifacts Produced

- `release/v1.0/…` + checksums; `docs/release/install.md`
- `archive/…` + `ARCHIVE-MANIFEST.json`
- `docs/release/dataset-release-decision.md` (+ dataset package if released)
- `LICENSE`, `THIRD-PARTY-NOTICES.md`
- `FINAL-STATUS.md`, `HANDOVER.md`
- `docs/gates/phase-23-gate.md`

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

Final review: all artefacts present; statuses truthful. Project complete.

## What Must NOT Be Done Yet

- Nothing follows; no post-release changes without a new version and changelog.

## Open Questions

- Does the ROI include faces (affects video release)?
- Institutional policy on dataset release and hosting.
- Licence choices (owner/institution).

## Decisions That Must Be Experimentally Validated

- None.
