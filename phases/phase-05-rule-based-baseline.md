# Phase 05 — Rule-Based Baseline & First Playable Prototype

## Status

Planned

## Purpose

Assemble the first end-to-end playable system: tracking (Phase 03) → geometry + audio (Phase 04) with two non-learned strike sources — **Baseline A (reactive impact detection)** and **Baseline B (rule-based physics anticipation)** — behind the `Anticipator`/`Geometry` contracts, plus the per-hand **commit logic** (commit state machine, refractory, duplicate suppression, safety checks) and full `TimingRecord` instrumentation. Establish the method for measuring `L_sys` in software and verify playability with ordinary sticks for single, alternating, repeated, rapid, and near-simultaneous hits.

## Why This Phase Exists

The research question compares learned anticipation with reactive detection and with a simpler anticipation baseline. Both baselines must exist, run under the **same** geometry and commit logic as the future model, and be instrumented identically — otherwise later comparisons are confounded. This phase also produces the recording-capable pipeline needed by Phase 06 and the first evidence that the concept is playable at all (success criterion 1).

## Relationship to Research Contribution

- Baseline A defines `L_sys` (README §5.4) operationally.
- Baseline B is the "rule-based anticipation" arm of the A/B/C comparison (README §9); it establishes what lead time is achievable *without* learning, which the temporal model must be judged against.
- The commit logic implemented here is frozen as the shared post-processing stage for every arm; Phase 09's causal replay simulator reuses it unchanged.

## Inputs

- Phase 03 `TrackState` stream (both hands), primary tip method.
- Phase 04 geometry (`intersect`), audio scheduler, MVP layout.
- Phase 01 contracts: `Anticipator`, `CommitPolicy`, `StrikeCandidate`, `CommittedStrike`, `TimingRecord`, per-hand state ownership and reset matrix.
- README §8 state machine, §9 baseline naming.

## Expected Outputs

- `prediction/rule_based.py` — Baseline B extrapolator (`Anticipator` implementation, `source = RULE`).
- Reactive path wiring — Baseline A (`source = REACTIVE`) from Phase 04 observed-trajectory intersection.
- `commit/` — commit state machine, refractory, duplicate suppression, safety gates; `CommitPolicy` implementation.
- `timing/` — `TimingRecord` collection and per-session timing logs.
- `app/` — playable prototype application (capture → … → audio) with runtime switch A/B and record mode (raw video + all records) per Phase 01 Task 01.9.
- Playability report: hit-type verification with logged evidence; induced-tracking-loss safety test; first software-stamped `L_sys` decomposition.
- Frozen candidate thresholds recorded in config (all tunable).

## Dependencies

- Phase 03 Exit Gate and Phase 04 Exit Gate.

## System Components

- `src/spacedrums/prediction/base.py` (`Anticipator` ABC), `rule_based.py`.
- `src/spacedrums/commit/state_machine.py`, `policy.py`, `refractory.py`.
- `src/spacedrums/timing/records.py`, `logger.py`.
- `src/spacedrums/app/main.py`, `pipeline.py`, `recorder.py`.
- `scripts/playability_session.py` (guided hit-type script with logging), `scripts/induced_loss_test.py`.

## Architecture

```
TrackState[h] ──┬──► geometry.intersect(observed history, REACTIVE) ──► StrikeCandidate(A)
                │
                └──► rule_based.predict(history[h]) ──► TrajectoryPrediction (CV/CA extrapolation, K steps)
                         └──► geometry.intersect(predicted, RULE) ──► StrikeCandidate(B) with TTI
                                              │
commit[h].step(candidates, TrackState[h], t_now) ──► CommittedStrike ──► audio.schedule ──► AudioEvent
timing ◄── all stamps
```

### Baseline A — Reactive
- Candidate emitted on the first frame whose observed segment crosses an impact surface validly (Phase 04, Task 04.4); `t_impact_est` sub-frame; commit immediately; `t_impact_target = now`.
- By construction `L_pred = t_impact_est − t_commit < 0` (the crossing is detected after it happened plus processing).

### Baseline B — Rule-based anticipation
- From `TrackState[h]` (filtered position, velocity, acceleration), extrapolate `K` steps of `dt_step` (candidate: `dt_step` = frame period; `K` covering a horizon `H`, tunable) with constant-velocity (CV) or constant-acceleration (CA) models (both implemented; selection by experiment).
- Feed the extrapolated `(t, p̂)` list to `geometry.intersect(…, RULE)` → `StrikeCandidate` with `t_impact_pred`, `TTI`, predicted impact position, crossing velocity, and an `intensity_proxy` from the extrapolated crossing speed along the inward normal.
- Optional confidence heuristic (candidate): speed above a threshold, direction consistency over the last `m` frames, tracking `VALID`. Exposed as `strike_probability` in `[0,1]` so the commit policy is source-agnostic.
- Strictly causal: uses only `TrackState` history.

### Commit policy (shared by A, B, and future C)
Per hand, per zone:

```
IDLE ──(candidate with TTI ≤ τ_commit AND prob ≥ p_commit AND track VALID)──► COMMITTED
IDLE ──(candidate persists for ≥ n_confirm frames, optional)──► ARMED ──(conditions)──► COMMITTED
COMMITTED ──► REFRACTORY(zone, until t_commit + r_zone) ──(timer)──► IDLE
any state ──(track INVALID/STALE)──► IDLE (candidates discarded; refractory timers persist)
```

- `τ_commit` (commit when predicted impact is within this time), `p_commit`, `n_confirm`, `r_zone` (per-zone refractory), `r_hand` (per-hand minimum inter-commit interval, allows rapid alternating on different zones) — all tunable, recorded in config.
- **Duplicate suppression:** one commit per geometry episode (Phase 04) **and** no commit for the same hand+zone while refractory; if both A and B candidates exist for the same episode (when both are enabled for logging), only the active arm commits; the other is logged as shadow.
- **Safety gates:** no commit unless `TrackState.status == VALID` (`DEGRADED` commits off by default; enabling is an explicit experiment); no commit if `t_impact_pred` is in the past by more than a tolerance (stale prediction); no commit if `dropped_since_last` exceeds a threshold (frame drop guard) — tunable.
- **Near-simultaneous hits:** hands are independent; both may commit in the same frame; audio mixer is polyphonic.
- **Cancellation:** V1 does **not** cancel a committed sound (a commit is final by definition of `t_commit`). "Stop-before-impact after commit" is therefore a false positive and is counted as such — this is intentional and central to the FP analysis.

### Shadow logging
Both arms may run simultaneously with one *active* (commits sound) and the other *shadow* (logged only). This allows collecting A and B candidates on the same session for later offline comparison without altering audio behaviour.

## Detailed Tasks

### Task 05.1 — Reactive Arm (Baseline A) Wiring
- **What:** Connect `TrackState` history to `geometry.intersect(…, REACTIVE)`; immediate commit path; `t_impact_target = now`.
- **Why:** Defines `L_sys`; success criterion 1 baseline.
- **Depends on:** Phase 04 Task 04.4.
- **Evidence:** Integration test on a recorded dev capture: strikes appear where the tip visibly enters zones; `TimingRecord` complete.

### Task 05.2 — Rule-Based Extrapolator (Baseline B)
- **What:** Implement CV and CA extrapolation producing `TrajectoryPrediction` (K steps, `dt_step`); heuristic `strike_probability`; `anticipator_id = "rule-cv"/"rule-ca"`.
- **Why:** Non-learned anticipation arm; also the runtime fallback for Phase 13.
- **Depends on:** Phase 03 filter outputs.
- **Evidence:** Unit tests on synthetic parabolic trajectories (predicted crossing time vs. analytic); `TEST-CAUSAL-1/2` pass.

### Task 05.3 — Commit State Machine and Policy
- **What:** Implement the state machine above with all parameters in config; episode + refractory duplicate suppression; safety gates; per-hand independence; shadow logging.
- **Why:** Q12, Q34–35; shared post-processing for all arms.
- **Depends on:** 05.1, 05.2.
- **Evidence:** Unit tests for every transition and gate; property test: no `CommittedStrike` is ever emitted while status ≠ `VALID`.

### Task 05.4 — Timing Instrumentation
- **What:** Populate every `TimingRecord` field available on the software path (`t_capture … t_audio_scheduled`, `t_audio_out_est` from Phase 04 measured latency); per-session timing log; summary script producing the README §5.3 decomposition table.
- **Why:** README §5; Phase 18 needs this exact instrumentation.
- **Depends on:** 05.3.
- **Evidence:** Timing log from a dev session; decomposition table (MEASURED, software-stamped, labelled as such).

### Task 05.5 — Playable Application and Record Mode
- **What:** Application loop: capture → hands → stick → tracking → (A | B) → geometry → commit → audio, both hands, with zone rendering, minimal overlay (Phase 03 Task 03.15 + zones + candidates), keyboard switch A/B, and record mode persisting raw video with `t_capture` and every record type per frame (Phase 01 Task 01.9).
- **Why:** Success criterion 1; Phase 06 recording tool builds on this.
- **Depends on:** 05.1–05.4.
- **Evidence:** Application runs a full session without exceptions; recorded session can be replayed (basic replay source) producing identical records (first parity check, informal here; formal `TEST-PARITY-1` in Phase 13).

### Task 05.6 — Threshold Tuning Session (Developer)
- **What:** Manually tune `v_min`, `τ_commit`, `p_commit`, `n_confirm`, `r_zone`, `r_hand`, zone positions/sizes for playability on the development setup; record each tried configuration and the qualitative outcome in the experiment log; freeze a *candidate* config for Phase 06 recording. Tuning here is for playability only; research thresholds are re-derived in Phases 09/18 on data.
- **Why:** Q13 — realistic beginner/intermediate playing; zone layout confirmation (Q16).
- **Depends on:** 05.5.
- **Evidence:** Tuning log; frozen `configs/prototype.candidate.yaml`; explicit statement that these are playability candidates.

### Task 05.7 — Hit-Type Verification Protocol
- **What:** Scripted developer session covering: single hits per zone (both hands), alternating L/R on one zone and on two zones, repeated hits on one zone at increasing rates, rapid consecutive hits, near-simultaneous two-hand hits, movement between zones without striking, fake swings, stop-before-impact. Log committed strikes with timing; count observed misses/extras by manual review of the recording.
- **Why:** Q12–13; documents what the prototype does and does not handle — including the maximum hit rate at which the prototype still separates hits (a MEASURED capability of *this* prototype, not a project claim).
- **Depends on:** 05.6.
- **Evidence:** Playability report with per-hit-type counts (MEASURED on the developer; not participant data); recording archived under `data/dev-sessions/`.

### Task 05.8 — Induced Tracking-Loss Safety Test
- **What:** Cover the camera / occlude a hand for controlled intervals (including the ~100–300 ms range from Q35 and longer) during and outside swings; verify no commits during `INVALID`, correct resets, and re-enable after valid tracking returns.
- **Why:** Q34–35 non-negotiable safety.
- **Depends on:** 05.3.
- **Evidence:** Test log with state traces; zero commits during `INVALID` (hard requirement).

### Task 05.9 — First Software-Stamped `L_sys` Decomposition
- **What:** For Baseline A on the dev session, compute per-strike: frame-quantization delay, capture latency (from Phase 02 profile), tracking, features (n/a for A), commit, audio scheduling, audio output (from Phase 04 profile); report distributions and the sum with its exact term list. Label as *software-stamped estimate*; external measurement is Phase 18.
- **Why:** README §5.4; gives the first quantitative sense of what anticipation must overcome — without claiming any reduction.
- **Depends on:** 05.4.
- **Evidence:** Table in the playability report with MEASURED (software-stamped) label and term list.

### Task 05.10 — Baseline B Shadow Comparison (informal)
- **What:** Run the dev session with A active and B shadow; compute B's candidate `t_impact_pred` vs. A's `t_impact_est` for matching episodes (informal lead time and timing error, developer data only) to sanity-check the extrapolator.
- **Why:** Early detection of gross defects before data collection; not a research result.
- **Depends on:** 05.5.
- **Evidence:** Informal table clearly labelled "developer sanity check — not an experimental result".

## Data Requirements

- Developer sessions only (`data/dev-sessions/`). Not part of the participant dataset. May be reused as pilot recordings for the Phase 06 pipeline test if labelled as pilot.

## Algorithms / Technical Approach

- Reactive: Phase 04 valid-entry test on the last two filtered tip positions.
- Extrapolation: CV `p̂_k = p + v·kΔ`; CA `p̂_k = p + v·kΔ + ½a(kΔ)²`; from the causal filter state.
- Heuristic probability: product/min of normalized gates (speed, direction consistency, validity) — candidate; any form is acceptable as long as it is monotone and documented.
- Commit: finite-state machine per hand×zone with timers.
- Timing: stamp collection with `t_mono`.

## Interfaces / Contracts

- Implements `Anticipator` (rule-based) and `CommitPolicy` (Phase 01).
- Consumes `TrackState`; produces `TrajectoryPrediction` (RULE), `StrikeCandidate`, `CommittedStrike`, `TimingRecord`.
- Record mode writes: `session/video.*`, `session/frames.jsonl` (`FrameSample` meta), `session/records/*.jsonl` per record type, `session/config.snapshot.yaml`, `session/timing.jsonl`.

## Tests

- **Unit:** extrapolators; commit transitions; refractory timers; duplicate suppression; safety gates; probability heuristic monotonicity.
- **Causality:** `TEST-CAUSAL-1/2` on the rule-based anticipator and the commit policy (commit depends only on past/current candidates).
- **Integration:** recorded dev capture → identical `CommittedStrike` list on replay (determinism check); induced-loss test → zero commits during `INVALID`.
- **System:** full application session without exceptions; audio audible on commits (manual).

## Measurements

| Quantity | Method | Label |
|----------|--------|-------|
| Per-hit-type counts (committed / missed / extra) on the developer session | Task 05.7 | MEASURED (developer only) |
| Software-stamped `L_sys` decomposition for A | Task 05.9 | MEASURED (software-stamped) |
| Commits during INVALID (must be 0) | Task 05.8 | MEASURED |
| Per-frame end-to-end processing time | profiling | MEASURED |
| Informal B-vs-A lead time on developer data | Task 05.10 | sanity check only |

## Experimental Design

- No participant experiment. Developer sessions follow the scripted protocol so that later Phase 06 recordings can reuse the segment definitions.
- Threshold tuning is logged as a sequence of (config, qualitative outcome) pairs; no optimisation claims.

## Acceptance Criteria

1. Baseline A and Baseline B run under the shared commit policy; runtime switch and shadow logging work.
2. All commit-policy and safety tests pass; zero commits during `INVALID` in the induced-loss test.
3. Playable with ordinary sticks on the MVP layout: single, alternating, repeated, rapid, and near-simultaneous hits each demonstrated and logged in the playability report with counts.
4. Record mode persists raw video + all records + config snapshot; replay reproduces the committed-strike list.
5. `TimingRecord` populated; software-stamped `L_sys` decomposition reported with its term list.
6. Candidate prototype config frozen and labelled as candidate.

## Definition of Done

- Implementation, tests, playability report, safety-test log, timing decomposition, frozen candidate config, gate record PASS; integrity checklist applied (no lead-time or latency-reduction claims; developer data labelled as such).

## Risks

- Prototype may be unplayable at realistic speeds on the laptop CPU (tracking latency) → measured; Phase 16 target; still record for Phase 06 if minimally usable.
- Extrapolation may produce many false candidates on fake swings → expected; this is what the research measures; commit thresholds are candidates only.
- Zone layout may need iteration → allowed here (candidates), frozen for data collection to keep the dataset consistent.

## Failure Modes

- Commit fires on grazing/upward motion → geometry `v_min` + entry test; log for Phase 07 label review.
- Sound plays during occlusion → violates safety; hard test failure.
- Timing stamps missing on some path → `TimingRecord` validation fails the session.

## Fallback Strategy

- If markerless tracking is too unreliable for playability, run Phase 05 and Phase 06 with `MARKER` as a labelled fallback (Phase 03 fallback rule) and keep markerless benchmark recordings in parallel.
- If Baseline B is unusable in real time, keep it as an offline arm only; Phase 13 fallback becomes Baseline A.

## Artifacts Produced

- `src/spacedrums/prediction/`, `src/spacedrums/commit/`, `src/spacedrums/timing/`, `src/spacedrums/app/`
- `scripts/playability_session.py`, `scripts/induced_loss_test.py`
- `configs/prototype.candidate.yaml`
- `docs/reports/phase-05-playability.md` (hit-type counts, timing decomposition, safety test, tuning log)
- `data/dev-sessions/` (developer only)
- `docs/gates/phase-05-gate.md`

## Exit Gate

Reviewer verifies playability report, safety test, and timing instrumentation. PASS → Phase 06 may start.

## What Must NOT Be Done Yet

- No learned model of any kind.
- No participant recordings.
- No claims of lead time, latency reduction, FPS, or accuracy beyond the labelled developer measurements.
- No calibration wizard (fixed layout config only).
- No cancellation of committed sounds.

## Open Questions

- Should `DEGRADED` commits ever be enabled? (experiment in Phase 17 with data)
- Should the 7th V1 zone be added before data collection or after? (affects dataset consistency — recommend deciding before Phase 06 freeze)
- CV vs. CA extrapolation as the default rule-based arm (Phase 09 decides on data).

## Decisions That Must Be Experimentally Validated

- `τ_commit`, `p_commit`, `n_confirm`, `r_zone`, `r_hand`, `v_min` — Phases 09/18 on participant data.
- Zone positions/sizes — Phase 05 playtest (candidate), Phase 14 calibration.
- Horizon `H`/`K` and `dt_step` for Baseline B — Phase 09 sweep.
- Frame-drop guard threshold — Phase 17.
