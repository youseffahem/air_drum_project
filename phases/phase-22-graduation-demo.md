# Phase 22 — Graduation Demo Preparation

## Status

Planned

## Codex Model for This Phase

- **Model:** GPT-6 Sol
- **Reasoning effort:** High
- **Recommended profile:** Demo Engineering / Reliability
- **Why this choice:** The demo prepares a script, venue pre-flight, calibrated presets, fallback drills, rehearsals, and evidence slides from the accepted release candidate. Sol fits this bounded integration and presentation work; High covers runtime contingency planning and checking every spoken or shown claim against the thesis audit.

> Set the model and reasoning effort in the Codex picker before running this phase.
> This section is a workload recommendation only; text in the prompt does not switch the active model.
> Record the actual model and reasoning setting used in the phase evidence.
> If the recommended model is unavailable, use the strongest available compatible model and record the actual setting used.
> The selected model is not a substitute for tests, acceptance criteria, or empirical evidence.

## Purpose

Prepare and rehearse a live demonstration of the RC that (a) shows real-time virtual drumming with ordinary drumsticks, (b) communicates the research contribution — causal trajectory prediction → geometry → anticipated strike — using the debug dashboard as visible evidence, (c) shows the measured results (Phase 18/19 figures) with their labels, and (d) is robust to venue conditions through an environment checklist and layered fallbacks. Visual polish is added only where it does not touch pipeline logic.

## Why This Phase Exists

Q59: scientific correctness first, but the demo must still look like a polished application. A live CV system is sensitive to lighting, background, camera placement, and audio setup; rehearsal and fallbacks convert that risk into a plan.

## Relationship to Research Contribution

Makes the contribution *visible*: predicted trajectory, predicted crossing, TTI countdown, commit before the tip reaches the zone (when it happens), and side-by-side arm switching — all with the honest timing panel labels from Phase 15.

## Inputs

- RC with presets (Phase 20); dashboard (Phase 15); calibration wizard (Phase 14); Phase 18/19 figures; known-issues list; failure catalogue; environment/lighting checklist (Phase 02).
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-003, REQ-006, REQ-050a, REQ-059, REQ-310; contributes to REQ-020.

## Expected Outputs

- Demo script (timed): setup, calibration, playing showcase (single, alternating, rapid, near-simultaneous), arm comparison (A vs. B vs. C live with shadow overlay), evidence slides (primary figure, decomposition table, limitations), Q&A prompts.
- Venue environment checklist and pre-flight test procedure.
- Fallback ladder: C → B → A → recorded replay of a live session (clearly labelled as recording) → video.
- Rehearsal log (≥ N rehearsals, N recorded) with issues and fixes (fixes limited to presentation/config; no pipeline changes without re-running Phase 20 regression).
- Optional visual polish (zone skins, hit animations) implemented in the UI layer only, with overhead measured (Phase 15 method).

## Dependencies

- Phase 20 Exit Gate; Phase 21 material available (figures).

## System Components

- `demo/` (script, presets, slides, replay sessions), `src/spacedrums/ui/skins.py` (optional), `scripts/demo_preflight.py`.

## Architecture

```
Pre-flight (venue): camera profile spot-check (FPS, exposure) → lighting per checklist → ROI/distance marks → audio device + buffer check → calibration wizard → validation strikes → choose preset (demo/safe)
Demo run: RC demo preset ─► live play ─► arm switch segment (dashboard visible) ─► evidence slides
Fallback ladder triggered by pre-flight or live failure
```

## Execution Instructions

- When this phase is authorized, automatically perform any outstanding post-owner-commit verification for its dependency phases on the current Git HEAD before dependent work; record the SHA, dirty state, and results. A commit alone does not satisfy a gate.
- Execute the entire phase end-to-end in the stated task order and automatically run executable gate conditions, without task-by-task or condition-by-condition prompting. Preserve all dependencies, optional-scope decisions, acceptance criteria, and evidence rules.
- Never fabricate participant evidence or substitute synthetic/developer evidence for it. Unavailable evidence and owner-only decisions remain PENDING; continue independent executable work and report blockers at the Exit Gate.
- Stop only at this phase's Exit Gate for owner/reviewer action under the [gate procedure](../docs/gates/gate-procedure.md). Commit, tag, and push remain owner-controlled, including release tags. Do not start another phase. When the next phase is authorized, automatically verify this phase's outstanding post-owner-commit conditions before dependent work.

## Detailed Tasks

### Task 22.1 — Demo Script
- **What:** Minute-by-minute script; what to say about each dashboard element; which claims are allowed (from the claims audit) and their labels; explicit statement of limitations in the talk.
- **Why:** Q59; consistency with the thesis.
- **Depends on:** Phase 21 audit.
- **Evidence:** Script document.

### Task 22.2 — Venue Checklist and Pre-Flight
- **What:** Lighting, background, camera mount/height/distance marks, power, audio output, display mirroring/latency (dashboard on a second screen), network not required (offline); `demo_preflight.py` runs FPS/tracking/audio checks and prints go/no-go per preset.
- **Why:** Environmental risk.
- **Depends on:** Phase 02/17 tooling.
- **Evidence:** Checklist; pre-flight script output from rehearsals.

### Task 22.3 — Fallback Ladder
- **What:** Define triggers and actions: tracking unstable → `safe` preset (Arm A); model fallback → B (automatic); persistent failure → replay of a recorded live session in the replay viewer (labelled "recording"); total failure → video. Prepare replay sessions and video in advance (from real sessions; labelled).
- **Why:** Demo reliability without misrepresentation.
- **Depends on:** Phase 20 presets; Phase 15 replay viewer.
- **Evidence:** Fallback assets; drill executed in rehearsal.

### Task 22.4 — Optional Visual Polish
- **What:** Zone skins, hit flash/animations, cleaner layout — UI layer only; measure overhead; must be disable-able; no change to geometry rendering semantics (impact surfaces still visible in debug view).
- **Why:** Q20/Q59 later-stage polish.
- **Depends on:** Phase 15.
- **Evidence:** Overhead measurement; toggle test.

### Task 22.5 — Rehearsals
- **What:** Rehearse in a room resembling the venue (and, if possible, the venue); log issues; fix presentation/config only; re-run pre-flight; time the demo.
- **Why:** Reliability.
- **Depends on:** 22.1–22.4.
- **Evidence:** Rehearsal log with timings and outcomes.

### Task 22.6 — Evidence Slides
- **What:** Primary figure (lead time vs. FP), decomposition table, live measurement summary, ablation forest plot, limitations; every number with its label; no numbers not in the thesis.
- **Why:** Scientific communication.
- **Depends on:** Phase 21 figures.
- **Evidence:** Slides; cross-check against the claims audit.

## Data Requirements

- Recorded live sessions for replay fallback (from Phase 18 or new developer sessions; labelled).

## Algorithms / Technical Approach

- None new.

## Interfaces / Contracts

- Demo presets (Phase 20); replay viewer.

## Tests

- Pre-flight script; fallback drills; overhead of polish.

## Measurements

| Quantity | Label |
|----------|-------|
| Pre-flight results per rehearsal (FPS, tracking validity, audio) | MEASURED |
| Demo duration per rehearsal | MEASURED |
| Polish overhead | MEASURED |

## Experimental Design

Not applicable.

## Acceptance Criteria

1. Script, checklist, pre-flight, fallback ladder, slides complete.
2. Rehearsals logged; fallback drills executed at least once.
3. Polish (if any) measured and toggleable; no pipeline logic changes.
4. All spoken/shown claims consistent with the claims audit.

## Definition of Done

- Acceptance criteria; gate record PASS; integrity checklist applied to slides/script.

## Risks

- Venue lighting/background unknown → checklist; `safe` preset; replay fallback.
- Audience expectation of "sound before impact" → script explains what was measured and what was not.

## Failure Modes

- Camera not recognised on venue hardware → bring the tested laptop/camera; pre-flight.

## Fallback Strategy

- The ladder (Task 22.3).

## Artifacts Produced

- `demo/script.md`, `demo/venue-checklist.md`, `demo/fallback-ladder.md`, `demo/slides/…`, `demo/replay-sessions/…`, `demo/rehearsal-log.md`
- `scripts/demo_preflight.py`, optional `src/spacedrums/ui/skins.py`
- `docs/gates/phase-22-gate.md`

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

Reviewer verifies rehearsal log, fallback drill, claims consistency. PASS → Phase 23.

## What Must NOT Be Done Yet

- No pipeline or model changes (would invalidate the RC).
- No demo content implying unmeasured performance.

## Open Questions

- Venue details (room, lighting, screen setup).
- Whether a second display for the dashboard is available.

## Decisions That Must Be Experimentally Validated

- Preset choice per venue conditions (pre-flight decides).
