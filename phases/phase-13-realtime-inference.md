# Phase 13 — Real-Time Inference Integration

## Status

Planned

## Purpose

Integrate the shipped temporal model (from Phase 10/11/12 ship ADR) into the live application as **Arm C**, alongside Arms A and B, with strict causal feeding from the live tracker, per-hand model state, model export/loading with hash verification, a latency budget check, automatic fallback to Baseline B (or A) when the model is unavailable or too slow, a runtime arm switch, live timing records, and an **offline/online parity test** (`TEST-PARITY-1`) proving that the live pipeline produces the same predictions and commits as the Phase 09 replay on recorded sessions.

## Why This Phase Exists

Offline results (Phases 09–12) are only meaningful for the product and for the live evaluation (Phase 18) if the online system computes the same features, runs the same model, and applies the same geometry and commit logic with real timing. Drift between offline and online paths is a classic source of invalid claims; this phase makes the two paths provably equivalent and measures the real inference cost in the live loop.

## Relationship to Research Contribution

- Enables the live measurement of end-to-end timing and effective latency (Phase 18) for Arm C.
- Guarantees causality online (model sees only delivered frames; hidden state reset on tracking loss).
- Realises the fallback architecture that keeps the system safe when the research component cannot run.

## Inputs

- Shipped model package (export + manifest + hash), `Anticipator` adapter (Phase 10/11).
- Phase 05 application, commit policy, timing instrumentation; Phase 08 streaming features; Phase 04 geometry/audio.
- Phase 09 harness and recorded sessions for parity.
- Measured stage latencies (Phases 02/03/08/10).
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-042 (live geometry path), REQ-052, REQ-108 (online parity), REQ-304; contributes to REQ-001, REQ-044, REQ-209, REQ-302.

## Expected Outputs

- Live Arm C integration (`prediction/model_arm.py`), model loader with hash verification, per-hand state management.
- Runtime arm switch (A/B/C) and shadow mode for any arm.
- Latency-budget monitor and automatic fallback policy.
- `TEST-PARITY-1` implementation and results.
- Live inference latency and end-to-end software-stamped decomposition for Arm C (MEASURED).
- Updated config schema (`anticipator.type = model`, model path/hash, fallback rules).

## Dependencies

- Phase 05 Exit Gate; Phase 10 Exit Gate (and 11/12 if they changed the shipped model).

## System Components

- `src/spacedrums/prediction/model_arm.py`, `model_loader.py`, `fallback.py`, `budget_monitor.py`
- `src/spacedrums/app/pipeline.py` (extended), `arms.py`
- `scripts/{parity_test, live_latency}.py`
- `tests/parity/`

## Architecture

```
TrackState[h] ─► streaming features (Phase 08 ring buffer per hand) ─► model_arm[h]:
     window/hidden state per hand (reset on INVALID/STALE) ─► inference (ONNX Runtime / TorchScript; threads configured)
     ─► TrajectoryPrediction(MODEL) ─► geometry.intersect ─► StrikeCandidate ─► commit policy ─► audio
budget_monitor: per-frame inference time; if p95 over a sliding window > budget OR model failed to load/verify ─► fallback.py switches the active arm to B (or A) and logs the event; UI shows the active arm
timing: t_features_done, t_inference_done, t_candidate, t_commit, t_audio_scheduled per strike
```

- **Causal feeding:** the model receives features only from `FrameSample`s already delivered; no buffering of frames ahead of processing; the GRU hidden state is per hand and persists only while `VALID`/`DEGRADED`.
- **`dt` handling:** the live frame interval may differ from the recording FPS; the adapter's `dt_step` must match the model's training `dt_step`; if the live FPS differs (e.g. 60 vs. 30), either resample features to the training rate (candidate) or use a model trained at the live rate (Phase 16/19); mismatch is an error, not a silent condition.
- **Optional inference worker thread:** only if needed to meet the budget; it must consume a queue of already-delivered feature frames (causality preserved) and the commit step must use the prediction's own `t_capture` reference, adding the measured worker delay into `Δ_proc`.

## Detailed Tasks

### Task 13.1 — Model Loader with Verification
- **What:** Load the exported model; verify hash against the manifest; verify feature schema id, `N`, `K`, `dt_step`, normalisation stats id; refuse to run on mismatch with a clear error; log model id in every session.
- **Why:** Reproducibility; prevents running a model with the wrong features.
- **Depends on:** Phase 10 manifests.
- **Evidence:** Unit tests (mismatch cases); session logs carry `model_id`.

### Task 13.2 — Live Model Arm
- **What:** Implement `model_arm.py` using the Phase 10 adapter with per-hand ring buffers and hidden state; stamps `t_features_done`/`t_inference_done`; emits `TrajectoryPrediction` and candidates via geometry.
- **Why:** Arm C online.
- **Depends on:** 13.1, Phase 08 streaming.
- **Evidence:** Integration test on live capture (dev) without exceptions; records schema-valid.

### Task 13.3 — Runtime Arm Switch and Shadow Mode
- **What:** Config/keyboard switch among A/B/C; any arm can run in shadow (logged, not sounding); the active arm is written into session metadata and every `CommittedStrike`.
- **Why:** Phase 18 live experiments need controlled arm assignment; shadow logs enable same-session comparisons.
- **Depends on:** 13.2.
- **Evidence:** Tests; logs show arm per commit.

### Task 13.4 — Latency Budget Monitor and Fallback
- **What:** Sliding-window p95 of inference time and of total per-frame processing; budget values from config (candidates derived from the frame period and the measured stage latencies; To Be Experimentally Determined in Phase 16); on breach or load failure → switch to B (or A if B is unavailable), log, show in UI; optional automatic recovery after a cool-down (tunable) — recorded.
- **Why:** Safety and product usability; the research arm must never make the system unplayable silently.
- **Depends on:** 13.2.
- **Evidence:** Fault-injection tests (slow model stub, missing file) trigger fallback; logs.

### Task 13.5 — `TEST-PARITY-1` (offline/online parity)
- **What:** Feed a recorded session (raw video) through the live pipeline in replay-from-file mode with original timestamps and compare, frame by frame, `KinematicFeatures`, `TrajectoryPrediction`, `StrikeCandidate`, and `CommittedStrike` with the Phase 09 harness outputs for the same model/config (`Δ_proc` set to the live measured values for the commit comparison). Pass criteria: features within tolerance; predictions within export-parity tolerance; identical candidate/commit sets up to timestamp differences explained by `Δ_proc`. Run on all sessions of one fold plus the developer sessions.
- **Why:** Phase 01 Task 01.9 requirement; validity of transferring offline results to the live system.
- **Depends on:** 13.2, Phase 09.
- **Evidence:** Parity report (pass/fail per session with max deviations).

### Task 13.6 — Live Inference and End-to-End Software Timing
- **What:** In live sessions (developer), measure inference latency p50/p95/p99 in the loop (not isolated), and the full software-stamped decomposition for Arm C per strike; compare with Arm A and B in the same session (shadow).
- **Why:** README §5.3; the `Δ_proc` used offline must match the live reality.
- **Depends on:** 13.2.
- **Evidence:** Timing tables (MEASURED, developer session); update of the `Δ_proc` policy constants if they differ (recorded, and offline results re-run if the difference is material — rule recorded).

### Task 13.7 — Config Schema Update and Documentation
- **What:** `anticipator: {type: model, model_path, model_hash, fallback: {enabled, to: B|A, budget_ms, window, cooldown}}`; docs for running each arm.
- **Why:** Reproducibility.
- **Depends on:** 13.4.
- **Evidence:** Schema validation; example configs.

### Task 13.8 — Causality Under Live Conditions
- **What:** Run `TEST-CAUSAL-1` in the replay-from-file live mode (perturb frames after `i`, compare outputs ≤ `i`) and a live-loop assertion that no `FrameSample` with `t_capture` greater than the current processing frame is ever visible to the arm.
- **Why:** Q60.
- **Depends on:** 13.2.
- **Evidence:** Test pass; assertion in code path.

## Data Requirements

- Recorded sessions from `ds-v1.0` (one fold) and developer sessions for parity/timing. No new participant data.

## Algorithms / Technical Approach

- ONNX Runtime CPU (or TorchScript) with configured intra-op threads (recorded); stateful GRU via exported state inputs/outputs or windowed re-computation (choice by latency measured in Phase 10 Task 10.7).
- Sliding-window percentile monitor.
- Parity comparison with tolerances.

## Interfaces / Contracts

- `Anticipator` implementation `ModelArm(model_id)`; `ArmSwitch` API; `FallbackEvent { t, from_arm, to_arm, reason }` logged; `SessionMetadata.arm_active` and `.fallback_events[]`.

## Tests

- **Unit:** loader verification; budget monitor; fallback transitions; arm switch.
- **Integration:** live dev session; replay-from-file mode.
- **Parity:** `TEST-PARITY-1`.
- **Causality:** `TEST-CAUSAL-1` live mode; no-future-frame assertion.
- **Fault injection:** slow model, corrupt model, missing stats → fallback with logs; no strikes fabricated during the switch.

## Measurements

| Quantity | Label |
|----------|-------|
| Live in-loop inference latency p50/p95/p99 (Arm C) | MEASURED |
| Software-stamped end-to-end decomposition per arm (developer session) | MEASURED |
| Parity deviations per session | MEASURED |
| Fallback trigger behaviour under injected faults | MEASURED (trace) |
| Frame drops with Arm C active vs. A/B | MEASURED |

## Experimental Design

- Parity: all sessions of one fold + developer sessions; tolerances pre-set from export parity.
- Timing: same developer session with A active/B+C shadow, then C active/A+B shadow; compare decompositions.

## Acceptance Criteria

1. Arm C runs live with verified model; per-hand state resets on tracking loss; causality tests pass in live mode.
2. Arm switch and shadow mode work; active arm recorded per commit.
3. Fallback triggers on injected faults; no fabricated strikes during switches.
4. `TEST-PARITY-1` passes on the designated sessions (deviations within tolerance; any failure explained and fixed).
5. Live inference and end-to-end software timing measured; `Δ_proc` constants reconciled with offline.

## Definition of Done

- Implementation, tests, parity report, timing report, config docs, gate record PASS; integrity checklist applied (no effective-latency claims; live numbers are developer sessions).

## Risks

- Python overhead makes in-loop latency exceed budget → Phase 16 optimisation; fallback keeps the system usable.
- Live FPS differs from training FPS → explicit mismatch handling (no silent resampling).
- Parity failures reveal feature-state drift → fix in Phase 08 code (shared path), re-run.

## Failure Modes

- Hidden state not reset after a gap → parity fails after gaps; test covers gaps.
- Worker thread introduces unaccounted delay → included in `Δ_proc`; measured.

## Fallback Strategy

- Ship Arm B as the default live arm if Arm C cannot meet the budget; keep C as an experimental option; record in the ship ADR.

## Artifacts Produced

- `src/spacedrums/prediction/{model_arm,model_loader,fallback,budget_monitor}.py`, `src/spacedrums/app/arms.py`
- `tests/parity/`, `docs/reports/phase-13-parity.md`, `phase-13-live-timing.md`
- `configs/live.arm-C.candidate.yaml`, docs
- `experiments/phase-13/…`
- `docs/gates/phase-13-gate.md`

## Exit Gate

Reviewer verifies parity, causality, fallback, timing. PASS → Phases 14, 15 (parallel), then 16.

## What Must NOT Be Done Yet

- No optimisation claims (Phase 16).
- No calibration wizard (Phase 14) — fixed layout still.
- No participant live experiments (Phase 18).
- No cancellation of committed sounds.

## Open Questions

- Worker thread vs. in-loop inference on the target laptop (Pending Benchmark, Phase 16).
- Automatic recovery from fallback: enabled by default?

## Decisions That Must Be Experimentally Validated

- Latency budget values and monitor window (Phase 16).
- Stateful vs. windowed inference online (Task 10.7 / 13.6).
- Fallback target (B vs. A) based on B's live behaviour.
