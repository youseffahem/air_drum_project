# Phase 18 — Evaluation & Experiments

## Status

PENDING — development execution complete at the exit gate (2026-09-27); the pre-registration is
declared and hashed, the evaluation / live-experiment machinery is implemented and rehearsed on
SYNTHETIC data only. The offline confirmatory run (no `ds-v1.0`), the external-method pad / video
pilots, every live session with a person (ethics Open Question), reviewer action and clean
post-owner-commit reproduction remain outstanding. See the gate record.

## Codex Model for This Phase

- **Model:** GPT-6 Astra
- **Reasoning effort:** Extra High
- **Recommended profile:** Experimental ML / Evaluation
- **Why this choice:** The final pre-registered comparison combines participant-level offline analysis, counterbalanced live blocks, external synchronization, uncertainty estimates, and reproducibility. Astra fits the scientific and systems workload; Extra High is justified by causal evaluation, leakage control, and precise separation of measured action-to-sound latency from software estimates.

> Set the model and reasoning effort in the Codex picker before running this phase.
> This section is a workload recommendation only; text in the prompt does not switch the active model.
> Record the actual model and reasoning setting used in the phase evidence.
> If the recommended model is unavailable, use the strongest available compatible model and record the actual setting used.
> The selected model is not a substitute for tests, acceptance criteria, or empirical evidence.

## Purpose

Run the **final, pre-registered, confirmatory evaluation** of the project's research question: compare **A (reactive)**, **B (rule-based anticipation)**, and **C (temporal AI; plus C-GBDT as the learned baseline)** on held-out participants offline (frozen harness, frozen models, frozen operating points) and **live** (end-to-end timing measured externally), reporting prediction lead time, false positives, false negatives, timing error, zone accuracy, trajectory accuracy, intensity agreement, inference latency, end-to-end latency decomposition, and — only where externally measured — effective action-to-sound latency. The design must allow any arm to win on any metric, and the report must state limitations.

## Why This Phase Exists

Phases 09–12 produced model-selection results on CV folds and single test runs during development. Phases 13–17 changed the live system (integration, optimisation, hardening) and possibly `Δ_proc`. The thesis needs one clean, pre-registered experiment on the final system, with live measurements that no offline replay can provide (`t_audio_out`, `t_acoustic_onset`, real frame timing, real user behaviour under anticipatory sound). Success criteria 2 and 3 are decided here.

## Relationship to Research Contribution

This is the evidence for (or against) the contribution: whether causal temporal trajectory prediction yields useful lead time compared with reactive detection at acceptable FP/timing cost, and whether that translates into measurable effective-latency change in the live system.

## Inputs

- Frozen: `ds-v1.0` test participants and CV folds; labels; harness version; `W`; FP budget; operating-point rules; `Δ_proc` policy (Phase 16 values); shipped model(s) with hashes; Baseline B configuration; C-GBDT models.
- Live system (Phase 17 hardened) with arm switch, shadow mode, calibration wizard, experiment-mode overlay.
- Phase 04 audio output latency, Phase 02 capture latency, Phase 07 acoustic validation (`t_impact_phys − t_impact_est`).
- Consent for live-experiment participants (Phase 00 templates; new consent per session).
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-002, REQ-005, REQ-009 (marker labelling), REQ-011, REQ-013, REQ-040, REQ-045, REQ-050b, REQ-050c, REQ-060c, REQ-117, REQ-211, REQ-307; contributes to REQ-027, REQ-028.

## Expected Outputs

- Pre-registration document (hypotheses, conditions, metrics, analysis plan, decision rules, exclusion rules) archived with a hash **before** any confirmatory run.
- Offline confirmatory results on test participants for A, B, C-GBDT, C (all metrics; per-participant tables; CIs; primary figure).
- Live experiment results: end-to-end timing decomposition per arm; externally measured action-to-sound latency where the method succeeds; live FP/FN/timing on scripted segments; user-behaviour notes.
- Effective-latency analysis (only from external measurements), with explicit statement of what was and was not measured.
- Limitations and threats-to-validity section.
- Full result manifests and a reproducibility package.

## Dependencies

- Phases 09, 10, 11 (12 if adopted), 13, 14 (calibration wizard for live sessions), 17 Exit Gates.

## System Components

- `src/spacedrums/eval/` (frozen) + `live_eval/` (live protocol runner, external-measurement sync tools)
- `scripts/{run_offline_confirmatory, run_live_session, analyze_live, external_sync}.py`
- Measurement equipment (as available; recorded): microphone; optional high-frame-rate phone camera; optional audio loopback; practice pad.

## Architecture

**Causality rule (README §13):** all arms in both experiments consume only observations with timestamp ≤ the current frame's `t_capture`; the frozen harness re-runs `TEST-CAUSAL-1` on the exact evaluated versions before the confirmatory run (Tests section). Ground-truth labels (Phase 07) are the only non-causal quantity and are never visible to any arm.

### Experiment 1 — Offline confirmatory (test participants)
- Arms: A; B (CV/CA at pre-declared operating points); C-GBDT (direct and trajectory-derived); C (shipped single-task and/or MT per ship ADR).
- Harness with `Δ_proc` = Phase 16 measured values (primary) and `Δ_proc = 0` (appendix).
- Metrics per README §10; per participant; pooled; by segment type; by zone; by hand; by speed tercile; by lighting/distance strata where present.
- Primary figure: lead time vs. FP/min curves per arm; operating points marked.

### Experiment 2 — Live end-to-end timing (developer + live participants)
- Setup: calibrated session (Phase 14); experiment-mode overlay; arm assigned per block (counterbalanced order across participants; recorded); shadow logging of the other arms.
- Scripted blocks (subset of the Phase 06 protocol: single hits per zone, alternating, repeated at cued tempi, fake swings, stop-before-impact).
- **External timing measurement methods** (each is Pending Benchmark until validated in a developer pilot; use those that pass):
  - **M1 Pad + microphone:** participant strikes a practice pad at a zone; microphone records both the pad impact (`t_acoustic_onset_impact`) and the speaker output (`t_acoustic_onset_sound`); the difference is the **physical action-to-sound latency** for that arm — independent of software stamps. Requires distinguishing the two onsets (different spectra; or separate mics; recorded).
  - **M2 High-frame-rate video:** a phone camera at its native high frame rate films the stick and an LED/screen flash driven at `t_audio_out` (or the speaker cone); gives impact-to-sound with frame-period resolution (recorded).
  - **M3 Software stamps + measured audio output latency:** `t_audio_out_est` from Phase 04; `t_impact_est` from the tracker; software-only — reported as an estimate, clearly labelled.
- Quantities: per strike, `t_audio_out (or acoustic) − t_impact_phys (or t_impact_est)` per arm → `L_sys` for A; `TE_audio` for B/C; distribution per arm; FP/FN on live scripted negatives; live `L_pred` where an estimated impact exists (matched via harness on the recorded session).

### Experiment 3 — Perceptual/usability notes (secondary, optional)
- Brief post-session questionnaire on perceived delay and false triggers per arm (blinded to arm where feasible; arms sound identical). Not a primary outcome; reported descriptively. Whether to include is an Open Question (time, ethics scope).

## Execution Instructions

- When this phase is authorized, automatically perform any outstanding post-owner-commit verification for its dependency phases on the current Git HEAD before dependent work; record the SHA, dirty state, and results. A commit alone does not satisfy a gate.
- Execute the entire phase end-to-end in the stated task order and automatically run executable gate conditions, without task-by-task or condition-by-condition prompting. Preserve all dependencies, optional-scope decisions, acceptance criteria, and evidence rules.
- Never fabricate participant evidence or substitute synthetic/developer evidence for it. Unavailable evidence and owner-only decisions remain PENDING; continue independent executable work and report blockers at the Exit Gate.
- Stop only at this phase's Exit Gate for owner/reviewer action under the [gate procedure](../docs/gates/gate-procedure.md). Commit, tag, and push remain owner-controlled, including release tags. Do not start another phase. When the next phase is authorized, automatically verify this phase's outstanding post-owner-commit conditions before dependent work.

## Detailed Tasks

### Task 18.1 — Pre-Registration
- **What:** Write and hash: hypotheses —
  - **H1 (lead time):** on test participants, C achieves median `L_pred > 0` at the FP budget, and greater than A's (which is negative by construction) — with the explicit note that the informative comparison is **C vs. B** (learned vs. physics anticipation) at matched FP.
  - **H2 (false positives):** C's FP/min at its operating point ≤ FP budget.
  - **H3 (timing error):** C's `TE_pred` MAE ≤ a pre-declared bound (candidate bound derived from Phase 07 acoustic validation spread and audio tolerance considerations; recorded).
  - **H4 (effective latency, live):** externally measured action-to-sound latency for C (and B) is lower than for A by more than measurement uncertainty.
  - Each hypothesis has a failure reading ("if not, we report …").
  - Conditions, arms, operating points, `W`, `Δ_proc`, exclusion rules, statistics (participant-level bootstrap CIs; paired differences per participant; no p-value fishing; multiple-comparison note), sample size statement (actual `P`), figures/tables list.
- **Why:** Scientific defensibility (success criterion 3).
- **Depends on:** All frozen inputs.
- **Evidence:** `phase-18-prereg.md` with hash and date preceding all confirmatory runs.

### Task 18.2 — Offline Confirmatory Run
- **What:** Execute Experiment 1 once; produce all tables/figures; per-participant results; strata.
- **Why:** H1–H3.
- **Depends on:** 18.1.
- **Evidence:** Results with manifests (MEASURED).

### Task 18.3 — External-Measurement Pilot
- **What:** Developer pilot of M1/M2/M3: validate each method's resolution and bias (e.g. M1 with a known software-scheduled click; M2 with an LED driven at known times); record which methods are usable and their uncertainty.
- **Why:** Live claims depend on measurement validity.
- **Depends on:** Equipment.
- **Evidence:** Method validation report (MEASURED uncertainties; go/no-go per method).

### Task 18.4 — Live Protocol and Participants
- **What:** Live-session protocol (calibration → blocks per arm, counterbalanced → external measurement blocks → questionnaire if included); consent; recruit live participants (may overlap with dataset participants — allowed for live timing because no model is trained on live data; recorded — but **test-participant offline numbers must not be re-tuned after live sessions**).
- **Why:** H4; real behaviour.
- **Depends on:** 18.3.
- **Evidence:** Protocol; session logs; participant count (MEASURED).

### Task 18.5 — Live Runs and Analysis
- **What:** Run sessions; sync external recordings to `t_mono`; compute per-strike action-to-sound latency per arm; live FP/FN on scripted negatives (from harness on the recorded session with GT labels generated by the Phase 07 pipeline for the live session); live `L_pred`; decomposition tables; compare to offline expectations.
- **Why:** H4; success criterion 3.
- **Depends on:** 18.4.
- **Evidence:** Live results (MEASURED) with uncertainties; explicit list of which quantities are externally measured vs. software-stamped.

### Task 18.6 — Effective-Latency Analysis
- **What:** Using only externally measured quantities (M1/M2 where valid): `L_sys` (A) distribution; action-to-sound for B and C; difference with CIs; relation to the conceptual `max(0, L_sys − L_pred)` discussed but not substituted for measurement; sound-before-impact fraction reported for B/C with its interpretation (negative `TE_audio` = early sound; consequences for perceived timing discussed, not assumed good).
- **Why:** README §5.4 rule: no latency-reduction claim without measurement.
- **Depends on:** 18.5.
- **Evidence:** Analysis section with MEASURED numbers and uncertainty; a clear PENDING if no external method validated.

### Task 18.7 — Trajectory and Intensity Reporting
- **What:** Trajectory ADE/FDE and impact-position error per arm that produces trajectories (B, C-GBDT(iv), C); intensity-proxy agreement per arm at commit time; caveat from Phase 08 Task 08.7 on target semantics.
- **Why:** Q45 metrics.
- **Depends on:** 18.2.
- **Evidence:** Tables.

### Task 18.8 — Limitations and Threats to Validity
- **What:** Participant count; geometric ground truth (with Phase 07 acoustic offset); single camera/laptop; tracker noise in targets; layout generalisation; segment-cued behaviour vs. natural play; measurement uncertainties; developer involvement; anything else found.
- **Why:** Success criterion 3.
- **Depends on:** All above.
- **Evidence:** Section in the report.

### Task 18.9 — Reproducibility Package
- **What:** All manifests, frozen versions, scripts to regenerate every table/figure from stored results and from raw data (offline), and stored external recordings with sync metadata.
- **Why:** README §4 VALIDATED.
- **Depends on:** 18.2–18.7.
- **Evidence:** Regeneration succeeds; second-person check recorded.

## Data Requirements

- Offline: `ds-v1.0` test participants (and CV folds for appendix).
- Live: new sessions (recorded under the Phase 06 pipeline with `live_eval` extensions), external measurement recordings, consent. Count reported after the fact.

## Algorithms / Technical Approach

- Harness (frozen); external sync via clap/flash cross-correlation; onset detection (Phase 07 method); bootstrap CIs at participant level; paired differences.

## Interfaces / Contracts

- `LiveSessionMetadata` extends `SessionMetadata` with `arm_blocks[]`, `external_methods[]`, sync markers, calibration hash.
- Results schema as Phase 09.

## Tests

- Harness self-checks (synthetic) re-run on the frozen version before the confirmatory run.
- Sync tooling tests on synthetic recordings.
- Pre-registration hash verified in the report.

## Measurements

| Quantity | Source | Label |
|----------|--------|-------|
| `L_pred`, FP/min, FN, `TE_pred`, zone accuracy per arm (test participants) | Exp. 1 | MEASURED |
| Trajectory ADE/FDE, impact-position error; intensity agreement | Exp. 1 | MEASURED |
| Inference latency per arm (live loop) | Exp. 2 | MEASURED |
| End-to-end decomposition per arm | Exp. 2 (software) | MEASURED (software-stamped) |
| Action-to-sound latency per arm (external) | Exp. 2 (M1/M2) | MEASURED or PENDING |
| Effective-latency difference C/B vs. A | Task 18.6 | MEASURED or PENDING |
| Live FP/FN on scripted negatives | Exp. 2 | MEASURED |
| Questionnaire (if included) | Exp. 3 | descriptive |

## Experimental Design

- **Offline:** between-arm comparison on identical held-out data; paired per participant; pre-declared operating points; primary metric = median `L_pred` at FP budget; secondary = FP/min, FN, `TE_pred`, zone accuracy; strata reported.
- **Live:** within-participant, arm as a blocked factor with counterbalanced order; external measurement on a subset of strikes per block; uncertainties propagated.
- **Neutrality:** report templates include outcomes where A or B is preferable; no post-hoc metric selection; exploratory analyses labelled.

## Acceptance Criteria

1. Pre-registration archived with hash before runs.
2. Offline confirmatory results complete for all arms with per-participant CIs and the primary figure.
3. External-measurement methods validated (or documented as failed) and live results reported with uncertainties.
4. Effective-latency analysis based solely on external measurements (or PENDING).
5. Limitations section complete; reproducibility package regenerates all outputs.

## Definition of Done

- All acceptance criteria; final evaluation report; gate record PASS; integrity checklist applied (every number labelled; hypotheses reported as supported / not supported / inconclusive).

## Risks

- External methods may not achieve sufficient resolution → H4 reported as inconclusive/PENDING; no claim.
- Few live participants → descriptive statistics; CIs wide.
- Anticipatory sound may alter participant motion (they hear sound before completing the stroke) → observed and reported; this is a genuine phenomenon of the system, not an artefact to hide.

## Failure Modes

- Accidental re-tuning after seeing test results → pre-registration hash and frozen manifests make it detectable.
- Sync failure in live recordings → session excluded by rule; reported.

## Fallback Strategy

- If live external measurement fails entirely, the thesis reports offline lead time and software-stamped decomposition with explicit limits; effective-latency reduction remains unclaimed.

## Artifacts Produced

- `docs/experiments/phase-18-prereg.md` (+ hash record)
- `docs/reports/phase-18-offline-confirmatory.md`, `phase-18-external-methods.md`, `phase-18-live-results.md`, `phase-18-effective-latency.md`, `phase-18-limitations.md`, `phase-18-final-evaluation.md`
- `src/spacedrums/live_eval/`, scripts
- `experiments/phase-18/…`, external recordings + sync metadata
- `docs/gates/phase-18-gate.md`

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

Reviewer verifies pre-registration precedence, completeness, labelling, reproducibility. PASS → Phase 19 and Phase 20.

Gate record: [Phase 18](../docs/gates/phase-18-gate.md) — PENDING reviewer, submitted 2026-09-27.

## What Must NOT Be Done Yet

- No model or threshold changes after pre-registration (any change = new pre-registered run, reported as such).
- No ablations (Phase 19).
- No claims in the thesis beyond this report's labelled results.

## Open Questions

- Include the perceptual questionnaire (Experiment 3)?
- Which external method(s) are feasible with available equipment?
- Number of live participants and whether they overlap with dataset participants.

## Decisions That Must Be Experimentally Validated

- Validity/uncertainty of M1/M2 (Task 18.3).
- Whether anticipatory sound changes user motion (observed in Task 18.5).

Phase 08 target contract reference: `docs/features/feature-schema-v1.md`, “Window and target
semantics”. Trajectory error is against future causal tracker output; strike timing is against
geometric `t_impact_est`, with physical-reference interpretation only when separately validated.
This reference does not start Phase 18 or claim evaluation results.
