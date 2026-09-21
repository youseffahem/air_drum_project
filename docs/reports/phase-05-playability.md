# Phase 05 — Rule-Based Baseline & First Playable Prototype: implementation and playability report

**Phase:** 05 · **Status:** IMPLEMENTED (code + tests); every person-dependent measurement **PENDING**\
**Date:** 2026-09-21 · **Hardware:** HW-01 · **Clock:** `perf_counter` · **Config:** `configs/prototype.candidate.yaml` (`sha256:fd7d0926aa672c6815a34b5a67d057b4bb05d4d7a2fe364dbf37be32869dba85`, candidate) · **Code state:** dirty tree on `36f2d4eb5623b1c9bf2ffa8e72d5c0b9c80580b0` (owner commits after review)

> **Evidence classes used in this report** (never merged): **VERIFIED** = mechanically checked by a test or a script self-check; **SYNTHETIC** = deterministic simulated observation sequences (`spacedrums.app.synthetic`; not recordings, not real-world behaviour); **DEV CAPTURE** = the three pre-existing Phase 02 developer captures (`data/dev-captures/swing-L2-exp-{5,6,7}`, exposure/blur checks of one developer, 6 s each, replayed — no new recording was made); **PENDING / NOT VALIDATED** = needs a person with sticks at the camera or an external instrument and was not done.
>
> No participant was recorded. No new developer recording was made. Nothing here is a lead-time, latency-reduction, FPS or accuracy claim about the system (integrity I-4, I-6).

---

## 1. What was built (VERIFIED by tests)

| Piece | Module | Status |
|---|---|---|
| Baseline A — reactive arm | `spacedrums.app.pipeline` → `GeometryEngine.observe` (Phase 04) → `PerHandCommitPolicy` | IMPLEMENTED |
| Baseline B — rule-based anticipator (`Anticipator`, `source = RULE`) | `spacedrums.prediction.{base, rule_based}` | IMPLEMENTED (CV and CA) |
| Commit policy (`CommitPolicy`): state machine, refractory, duplicate suppression, safety gates, shadow flag | `spacedrums.commit.{state_machine, refractory, policy}` | IMPLEMENTED |
| `TimingRecord` class, collector, JSONL record streams with `RecordStreamHeader`, README §5.3 decomposition | `spacedrums.contracts.records.TimingRecord`, `spacedrums.timing.{records, logger, decomposition}` | IMPLEMENTED |
| Playable application: live / replay / dev-capture / synthetic sources, keyboard arm switch, record mode, overlay | `spacedrums.app.{main, pipeline, audio_out, recorder}`; `spacedrums.capture.ReplayFrameSource` | IMPLEMENTED |
| Session summaries (counts, decomposition, B-vs-A comparison, synthetic-truth evaluation, safety count) | `spacedrums.app.session_summary` | IMPLEMENTED (developer sanity-check machinery; Phase 09 owns the canonical harness) |
| Protocol / summary scripts | `scripts/{playability_session, induced_loss_test, timing_summary, shadow_compare, rule_baseline_sensitivity, render_session_frames}.py` | IMPLEMENTED; live modes PENDING (person) |
| Candidate prototype config (schema 1.3, ADR-0018) | `configs/prototype.candidate.yaml` | IMPLEMENTED; values candidate |

Tests: 485 passed / 1 skipped (full suite, HW-01, 2026-09-21; the skip is the opt-in webcam hardware test). Phase 05 focused set: 87 passed (`tests/prediction`, `tests/commit`, `tests/app`, `tests/timing`, `tests/capture/test_replay_source.py`, `tests/scripts/test_phase05_scripts.py`).

---

## 2. Rule architecture and causal data flow

```
FrameSample ─► hands ─► stick ─► tracking[h].update ─► TrackState[h] (p, v, a, status, confidence; causal history)
                                                             │
        ┌────────────────────────────────────────────────────┴───────────────────────────────────────┐
        │ Baseline A (REACTIVE)                               │ Baseline B (RULE)                     │
        │ geometry.observe(last two observed tips)            │ anticipator.predict(history[-N:])     │
        │   first valid inward entry per episode,             │   kinematic state at t_ref            │
        │   sub-frame t_impact_est (Phase 04, unchanged)      │   K-step CV / CA extrapolation        │
        │                                                     │   heuristic strike_probability        │
        │                                                     │ geometry.intersect_prediction(...)    │
        │                                                     │   SAME impact definition, t_impact_pred, tti │
        └───────────────► StrikeCandidate(A) ◄────────────────┴────────────► StrikeCandidate(B) ◄─────┘
                                  │                                                  │
                    commit[A][h].step(...)                                commit[B][h].step(...)
                                  │                                                  │
                          CommittedStrike (shadow = arm is not active)  ──► audio.play() only when shadow = false
                                  └──────────────► TimingRecord(STRIKE) for every commit, shadow included
```

- **Causality.** The anticipator reads only the last `N = max(direction_window_frames, 2, n_min_frames)` tracker states, all with `t_capture ≤` the current frame's; the commit policy reads the current frame's candidates, `TrackState` and `t_now`. No interface has a look-ahead argument. `TEST-CAUSAL-1/2` results: §7.
- **Coordinates.** ROI-normalized `[x, y]`, origin top-left, **y down** (ADR-0005); velocity ROI-norm/s, acceleration ROI-norm/s². "Downward" = increasing `y`; what counts as an approach is the zone's `inward_normal` in geometry, never a hard-coded direction.
- **Equations.** CV: `p̂_k = p + v·kΔ`; CA: `p̂_k = p + v·kΔ + ½a(kΔ)²`, `v̂_k = v + a·kΔ`; `k = 1..K`, `Δ = dt_step_s`, horizon `H = KΔ` (candidate `K = 6`, `Δ = 1/30 s` → `H = 0.2 s`, arithmetic). The prediction is prefixed with the current observed tip (`t_ref`) and intersected as a polyline by the Phase 04 routine (linear sub-step interpolation between predicted samples).
- **Probability heuristic** (candidate form, monotone): `speed_gate = clip((|v| − lo)/(hi − lo), 0, 1)`; `direction_gate = mean_i max(0, cos∠(v_i, v_now))` over the last `m` velocities (1.0 with a single sample); `validity_gate = 1` (VALID) or `confidence` (DEGRADED); combined by product (default) or min.
- **Times.** `tti = t_impact_pred − t_ref` (README §6). Prediction lead time `L_pred = t_impact_est − t_commit` (README §5.4): **positive = the commit happened before the estimated impact**. `L_pred` is not `L_sys`, not the audio output latency, not the capture latency and not the frame period; those are separate terms of the §5.3 decomposition (§6 below). For the reactive arm `L_pred < 0` by construction.
- **Shadow vs committed.** A shadow commit is a `CommittedStrike` with `shadow = true`: the instant that arm *would* have committed; logged and timed, never scheduled (the Phase 04 scheduler raises on a shadow commit — `tests/audio/test_scheduler_integration.py`; `tests/app/test_app_pipeline.py::test_shadow_commits_never_reach_audio`).

### 2.1 Commit policy gates (shared by A, B and later C)

| # | Gate | Threshold (config `commit.*`, candidate) | Note |
|---|---|---|---|
| 1 | status | `allow_degraded_commits = false` → VALID only | non-VALID frame: every candidate discarded, all zone machines → IDLE, refractory timers persist |
| 2 | frame-drop guard | `max_dropped_since_last = 1` | no commit on a frame whose `dropped_since_last` exceeds it |
| 3 | zone validity | registry + `allowed_hands` | |
| 4 | stale prediction | `stale_prediction_tolerance_s = 0.02` | anticipatory candidate whose `t_impact_pred` is further in the past |
| 5 | confidence | `p_commit = 0.5` | `strike_probability ≥ p_commit`; a null probability (observed crossing) is not gated |
| 6 | time-to-impact | `tti_commit_s = 0.05` | `t_ref − t_now ≤ τ_commit`; reactive always passes |
| 7 | refractory | `refractory_zone_s = 0.10`, `refractory_hand_s = 0.04` | per (hand, zone) and per hand; persist across resets except SESSION_START |
| 8 | episode | — | one commit per geometry episode; anticipatory commits keep the zone blocked until the observed entry/exit or `t_impact_target + stale tolerance` |
| 9 | hysteresis | `n_confirm_frames = 0` | consecutive passing frames before COMMITTED (ARMED); 0 = off |

Threshold origin: every value is the Phase 01 example's candidate or the phase document's candidate wording, carried into `configs/prototype.candidate.yaml` and labelled **provisional**; none was tuned on data (Task 05.6 is PENDING, §6). The SYNTHETIC sensitivity sweep (§5.4) documents which knobs matter on synthetic strokes; it is not a tuning.

---

## 3. Determinism and replay (VERIFIED)

- Same input sequence + config → identical `TrackState`, `TrajectoryPrediction`, `StrikeCandidate` and `CommittedStrike` records (canonical JSON equality; decisions independent of the wall clock) — `tests/app/test_app_pipeline.py::test_deterministic_replay_reproduces_every_decision`.
- Record mode → `ReplayFrameSource` → fresh pipeline reproduces the recorded committed-strike list exactly (ids, times, zones, arms, shadow flags) — `tests/app/test_app_recorder_summary.py::test_replay_of_the_recording_reproduces_the_committed_strike_list`. Every persisted stream validates against its schema with a valid `RecordStreamHeader`.
- Replay `t_now = t_frame_available + replay_delta_proc_s` (default 0.0, provisional; ADR-0018 §6).
- Debug rendering of a recorded session (`scripts/render_session_frames.py`): `docs/figures/phase-05/synthetic-repeated-commit-frame.png` — a **SYNTHETIC** session (`--synthetic repeated`, blank frames, no person) at the frame of a reactive candidate: zones, both filtered tips, the rule arm's predicted trajectory, the candidate's impact position and the shadow commit label. Illustration of the tool only; not evidence.

---

## 4. Failure cases (SYNTHETIC unit-test evidence; `tests/prediction/test_rule_based.py`, `tests/app/test_app_pipeline.py`)

| Case | Behaviour | Evidence |
|---|---|---|
| stopped stick / hover | anticipator declines `LOW_SPEED`; no candidate; no commit | `test_failure_cases_decline_or_produce_no_candidate`, scenario `hover` |
| low velocity approach (`slow`) | anticipator declines `LOW_SPEED` (76 frames); no B commit; reactive commit depends on `geometry.v_min` | `test_slow_approach_rule_arm_declines_low_speed` |
| upward movement | prediction exists, geometry yields no candidate (inward test) | `upward` scenario, unit test |
| lateral movement / between zones | no candidate | `lateral`, `between_zones` |
| stop-before-impact (fake swing) | no reactive commit; B commit possible and counted as a false positive by design; pending episode released after target + tolerance | `stop_short`, `test_stop_before_impact_after_commit_is_a_false_positive_by_design` |
| noisy trajectory / timestamp jitter | records stay schema-valid; safety invariants hold | `test_noisy_and_jittered_sequence_stays_schema_valid_and_safe` |
| insufficient history | decline `INSUFFICIENT_HISTORY` / `EMPTY_HISTORY` | conformance test |
| high acceleration | CA declines `HIGH_ACCELERATION` (`a_max`) | unit test |
| crossing outside the horizon | no candidate (bounded `K·Δ`) | unit test |
| predicted crossing outside every zone | no candidate | unit test |
| multiple possible zones | earliest valid crossing along the trajectory wins (Phase 04 rule) | `test_multiple_zones_resolve_to_earliest_crossing` |
| tracking reset / stale / invalid | anticipator declines `STATUS_NOT_LIVE`; commit policy discards candidates and goes IDLE; refractory persists | conformance + policy tests, induced loss (§5.2) |
| timestamp irregularity (non-monotonic) | decline `NON_MONOTONIC_TIME` (tracker itself raises on decreasing `t_capture`) | unit test |
| frame drop on the crossing frame | no commit on that frame; episode rule prevents a late re-commit | `test_frame_drop_guard_blocks_commit_on_that_frame` |

---

## 5. Measurements

### 5.1 Hit-type verification (Task 05.7)

**Live protocol (developer with two sticks): PENDING / NOT VALIDATED.** `scripts/playability_session.py --live` runs the 16-segment scripted session (single hits per zone and hand, alternating on one/two zones, repeated with increasing rate, rapid, near-simultaneous, movement between zones, fake swings, stop-before-impact) in record mode with on-screen instructions and stores the segment boundaries; the per-hit-type counts (committed / missed / extra) require the person's manual review of the recording and are not fabricated here. The maximum hit rate at which the prototype separates hits is therefore also PENDING.

**SYNTHETIC self-test (`scripts/playability_session.py --synthetic`, run `20260921-1917-p05-playability-synthetic`, dirty tree; the same table is produced by `tests/app/test_app_pipeline.py` with faster synthetic strokes):** machinery evidence only — synthetic strokes are constant-acceleration downstrokes with a symmetric rebound, no appearance model; the numbers say nothing about real strokes.

| Scenario (SYNTHETIC) | Arm | truth | commits | matched | FP | FN | dup | zone acc | L_pred median s | TE median s |
|---|---|---|---|---|---|---|---|---|---|---|
| single | A | 1 | 1 | 1 | 0 | 0 | 0 | 1.0 | −0.0074 | +0.0023 |
| repeated | A | 4 | 4 | 4 | 0 | 0 | 0 | 1.0 | −0.0074 | +0.0023 |
| rapid | A | 6 | 6 | 6 | 0 | 0 | 0 | 1.0 | −0.0224 | +0.0023 |
| rapid | B (shadow) | 6 | 6 | 6 | 0 | 0 | 0 | 1.0 | +0.0110 | +0.0243 |
| alternating_one_zone | A | 4 | 4 | 4 | 0 | 0 | 0 | 1.0 | −0.0074 | +0.0023 |
| alternating_two_zones | A | 4 | 4 | 4 | 0 | 0 | 0 | 1.0 | −0.0074 | +0.0023 |
| near_simultaneous | A | 2 | 2 | 2 | 0 | 0 | 0 | 1.0 | −0.0190 | +0.0020 |
| near_simultaneous | B (shadow) | 2 | 1 | 1 | 0 | 1 | 0 | 1.0 | +0.0026 | +0.0049 |
| between_zones, stop_short, hover, lateral, upward | — | 0 | 0 | 0 | 0 | 0 | 0 | — | — | — |
| slow | A | 1 | 1 | 1 | 0 | 0 | 0 | 1.0 | −0.0242 | +0.0003 |

`rapid` uses the faster synthetic stroke (`t_down = 0.10 s`); the run's stdout carries the exact figures. With the default synthetic stroke (`t_down = 0.20 s`, crossing speed ≈ 1.2 ROI-norm/s) the rule arm's candidates are rejected by the probability gate (`p_commit = 0.5`) on the single/repeated/alternating scenarios (0 B commits, 0 FP); with faster strokes (`t_down = 0.12 s`, ≈ 2.0 ROI-norm/s, `tests/app`) B matches every synthetic strike with 0 FP / 0 FN. Zero commits on non-VALID frames in every scenario.

### 5.2 Induced tracking-loss safety test (Task 05.8)

**Live test (developer occludes a hand / covers the camera): PENDING / NOT VALIDATED** — `scripts/induced_loss_test.py --live` records the session and counts commits on non-VALID frames from the recorded streams.

**SYNTHETIC self-test (`scripts/induced_loss_test.py --synthetic`, run `20260921-1918-p05-induced-loss-synthetic`; also `tests/app/test_app_pipeline.py::test_induced_tracking_loss_zero_commits_while_not_valid`):** occlusions of 100 / 200 / 300 / 500 ms (3 / 6 / 9 / 15 frames at the synthetic 30 FPS) injected during a swing, right before the crossing and outside any swing, for each hand; A active, B shadow. Result: **24/24 cases OK, 0 commits on non-VALID frames**; 100 ms losses are bridged (`DEGRADED`, `g_max = 3`), longer losses go `INVALID` with a `GAP_EXCEEDED` reset and re-acquire to `VALID`; the other hand is unaffected. Example trace (RIGHT, 300 ms during the swing): `VVVVVVVDDDIIIIIIVVVV…`.

**DEV CAPTURE:** on the three replayed captures (§5.5) the safety count `commits_during_non_valid` is 0 in each session, including exp-6 (mostly STALE/DEGRADED) and exp-7 (INVALID on every frame — no hand detected in the dark capture).

### 5.3 Timing instrumentation and software-stamped `L_sys` decomposition (Tasks 05.4 / 05.9)

`TimingRecord` (FRAME per frame; STRIKE per commit, shadow included) is populated on every path (VERIFIED: schema-valid records in every app test and recorded session). Decomposition terms (README §5.3) as implemented in `spacedrums.timing.decomposition`:

`L_sys_est = frame_quantization + capture + tracking + commit + audio_dispatch + audio_out_est` with `frame_quantization = t_capture(commit frame) − t_impact_est`, `capture = t_frame_available − t_capture`, `tracking = t_tracking_done − t_frame_available`, `commit = t_commit − (t_inference_done | t_tracking_done)`, `audio_dispatch = t_audio_scheduled − t_commit`, `audio_out_est = t_audio_out_est − t_audio_scheduled`; `L_sys_est = t_audio_out_est − t_impact_est` (reactive strikes only; **software-estimated**, `_est` suffix mandatory, contracts.md §3.10).

**Status: PENDING / NOT VALIDATED for the live decomposition.** Two prerequisites are missing: (1) a live developer session (person); (2) `t_audio_out_est` requires the audio profile's MEASURED output latency, which Phase 04 criterion 6 left PENDING on HW-01 — the collector therefore leaves `t_audio_out_est` null and the table prints the PENDING row instead of a number (no placeholder is ever turned into an estimate). On replayed/synthetic sessions the cross-clock terms (`tracking`, `commit`, `audio_dispatch`, `audio_out_est`, `L_sys_est`) are N/A by construction (recorded clock vs live re-stamped clock); the computable terms of the exp-5 replay are in §5.5.

### 5.4 SYNTHETIC sensitivity of the rule arm (thresholds rationale, not tuning)

`scripts/rule_baseline_sensitivity.py`, run `20260921-1920-p05-rule-sensitivity-synthetic` (noise σ = 0.003 ROI-norm, seed 0). Grid: motion CV/CA × filter kalman_cv/kalman_ca × `tti_commit_s` 0.05/0.10 × `p_commit` 0.3/0.5, on `repeated@0.20 s`, `repeated@0.12 s`, `rapid@0.10 s` and the fake swing `stop_short@0.12 s`. Excerpt (ms; `L_pred(truth)` = vs analytic crossing; `adv` = `t_commit(A) − t_commit(B)`):

| motion | filter | τ_commit | p_commit | repeated@0.20: matched/FN/FP, L_pred(truth), adv | repeated@0.12 | rapid@0.10 | fake-swing FP |
|---|---|---|---|---|---|---|---|
| CV | kalman_cv | 0.05 | 0.5 (candidate) | 2/2/0, +9.3, +33 | 4/0/0, −6.0, +33 | 2/4/0, +11.0, +33 | 0 |
| CV | kalman_cv | 0.05 | 0.3 | 4/0/0, +26.0, +33 | 4/0/0, −6.0, +33 | 5/1/0, +11.0, +33 | 0 |
| CA | kalman_cv | 0.05 | 0.3 | 4/0/0, +26.0, +33 (TE 3.5 vs CV 9.7) | 4/0/0, −6.0, +33 | 5/1/0, +11.0, +33 | 0 |
| CV/CA | kalman_ca | 0.05 | 0.5 | 3/1/0, −7.4, +33 | 0/4/0 | 0/6/0 | 0 |

Readings (synthetic only): (i) the rule arm commits **one frame earlier than the reactive arm** (`adv ≈ +33 ms`) whenever it commits at all; whether that is before the crossing (`L_pred > 0`) depends on the stroke: on the fastest synthetic strokes the Kalman-CV velocity lags the accelerating tip enough that the TTI gate passes only on the frame in which the crossing happens (`L_pred ≈ −6 ms`); (ii) `p_commit` is the dominant miss knob (the speed gate reflects the lagged filtered speed); (iii) CA reduces the timing error on the exact parabola (`TE` 3.5 vs 9.7 ms) without changing the commit frame; (iv) the `kalman_ca` filter with the shared `q/r` candidates lags more and misses fast strokes; (v) 0 false positives on the fake swing in every configuration. None of this transfers to real strokes; Phase 09/18 decide on data.

### 5.5 DEV CAPTURE runs (Task 05.1 integration; Task 05.10 informal comparison)

The full pipeline (MediaPipe hands → GEOM stick → `kalman_cv` tracker → A + B → commit → timing) was run on the three existing Phase 02 captures with `python -m spacedrums.app.main --source devcapture --record --no-audio` (A active, B shadow; recordings under `data/dev-sessions/dev-p05-swing-L2-exp-{5,6,7}`, git-ignored). Per-frame processing (perception + decision, PNG decoding excluded, software-stamped, development only): exp-5 p50 31.2 ms / p95 47.4 ms; exp-6 36.9 / 46.0; exp-7 25.5 / 37.3 on HW-01.

| Capture | Frames | RIGHT status V/D/I/S | LEFT status V/D/I/S | predictions | candidates REACTIVE/RULE | commits A / B | commits on non-VALID |
|---|---|---|---|---|---|---|---|
| exp-5 (exposure −5) | 171 | 143/25/3/0 | 90/56/25/0 | 163 | 4 / 4 | 2 / 0 | 0 |
| exp-6 (−6) | 171 | 11/66/2/92 | 7/49/26/89 | 75 | 0 / 0 | 0 / 0 | 0 |
| exp-7 (−7) | 172 | 0/0/172/0 | 0/0/172/0 | 0 | 0 / 0 | 0 / 0 | 0 |

exp-5 detail (runs `20260921-1924-p05-timing-summary`, `20260921-1924-p05-shadow-compare`): the two reactive commits have `frame_quantization` 4.5 / 20.3 ms and `L_pred(A)` −4.6 / −20.4 ms (computable replay terms; the rest N/A). The four rule candidates were rejected (2 × status not VALID, 2 × probability < 0.5), so the B-vs-A comparison has **0 matched pairs** on this capture — no lead-time figure exists for B on developer data. **Manual review by the submitter** of the rendered commit frames 7–9 and 134–136 (produced from the git-ignored session with `scripts/render_session_frames.py --session-dir data/dev-sessions/dev-p05-swing-L2-exp-5 --frames 8 135 --context 1`; the renderings show the developer's own image and are therefore **not** kept in the repository — they are regenerable on demand from the git-ignored dev session and are not required as evidence; the finding is recorded here in prose): the RIGHT/Tom 1 commit at frame 135 coincides with the stick tip visibly entering Tom 1 through its upper-left boundary; the LEFT/snare commit at frame 8 is **spurious** — the GEOM tip estimate for the LEFT hand sat on the torso rather than on the stick during the first frames after acquisition, and that mis-estimated tip crossed the snare boundary. This is a Phase 03 tip-estimation error surfacing through the reactive arm (the arm did what the observed trajectory told it); it is recorded here as one visible false commit on developer data, not counted as a playability result (the captures were not aimed at zones, and the reviewer is the submitter).

---

## 6. Threshold tuning session (Task 05.6) and frozen candidate config

**PENDING / NOT VALIDATED.** The tuning session needs a person with sticks; no configuration was tried on a person. `configs/prototype.candidate.yaml` records the candidate values (all provisional; §2.1 and the file's comments) so that Phase 06 has a labelled starting point. Tuning log: empty (no session). `arms.active = A` is the default for the first live session because the reactive arm is the safe reference; the `b` key switches at runtime.

---

## 7. Causality (VERIFIED, SYNTHETIC inputs; `git_sha 36f2d4e…` dirty)

| Component | Test | Result |
|---|---|---|
| Rule-based anticipator (CV, CA) | `TEST-CAUSAL-1` (GARBAGE, REMOVED, SHIFTED; \|I\| = 11 / 12) | PASS, 0 differing tuples |
| Rule-based anticipator | adversarial: future `TrackState`s appended/mutated after a prediction | PASS (prediction unchanged) |
| Rule-based anticipator (CV, CA) | `TEST-CAUSAL-2` with declared `N = 3`, `N_min = 2` (\|I\| = 23) | PASS; negative control (window 2) differs in 23/23 cuts |
| Commit policy | `TEST-CAUSAL-1` (\|I\| = 57; 38 commits in the reference run) | PASS, 0 differing tuples |
| Commit policy | `TEST-CAUSAL-2` with declared `N_eff = 7` frames (time-bounded memory; open episodes excluded) | PASS; negative control (window 1) differs in 2/73 cuts |
| Reactive arm | Phase 04 geometry (adjacent observed samples only) — unchanged | Phase 04 tests |

Files: `tests/prediction/test_causal_anticipator.py`, `tests/commit/test_causal_commit.py`. The evidence lines are printed by the tests (`-s`).

---

## 8. Regression (VERIFIED)

Phase 01 contracts (`tests/contracts`: 145 passed incl. the new schema 1.3 cases), Phase 02 capture (`tests/capture`, unchanged semantics; replay source added), Phase 03 hands/stick/tracking (`tests/hands`, `tests/stick`, `tests/tracking` unchanged and green), Phase 04 geometry/audio (`tests/geometry`, `tests/audio` unchanged and green; the scheduler still refuses shadow commits). Import-linter: 6 contracts kept, 0 broken (two new: prediction ↛ geometry, commit ↛ hands/stick/prediction/features).

---

## 9. Limitations and pending items

1. **Playability itself is unmeasured**: no live session, no hit-type counts, no maximum hit rate, no induced-loss log with real occlusions, no audible check — all require a person at the camera.
2. **No `L_sys_est` figure**: needs a live session and the audio profile's MEASURED output latency (Phase 04 criterion 6, still PENDING); `t_audio_out_est` is null until then. Phase 04's documented gate verdict remains FAIL and is not reinterpreted here.
3. **B-vs-A lead time on developer data does not exist** (0 matched pairs on exp-5); SYNTHETIC lead times are properties of the synthetic stroke model.
4. **Thresholds are candidates**, not tuned; the synthetic sweep is a sensitivity table, not an optimisation.
5. **`v_min = 0.15`** is a candidate; the reactive arm's behaviour on slow strokes and the tip-estimation errors seen on exp-5 (Phase 03 gate condition C-03-1 still open) directly affect the reactive reference.
6. **Commit-policy memory**: open episodes (tip resting inside a zone after a commit) are unbounded by design; `TEST-CAUSAL-2` covers the time-bounded part.
7. **Replay `Δ_proc = 0`** is provisional (Phase 09 decides); live and replay commit sets may differ at the TTI/stale boundaries.
8. **Audio in replay** plays as soon as possible (targets are on the recorded clock); replay audio timing is not meaningful and is not reported.
9. Dev captures are 6 s exposure checks of one developer, not aimed at zones; exp-6/exp-7 are too dark for tracking.
