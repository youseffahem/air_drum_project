# Phase 10 — Temporal AI / Future Trajectory Prediction

## Status

Planned

## Purpose

Build, train, and evaluate the **core research component**: a small **causal temporal model** (GRU and TCN candidates; Tiny Transformer deferred to Phase 12 unless justified) that, from the recent per-hand motion history (Phase 08 features), predicts the **future stick-tip trajectory** over a horizon; feed that predicted trajectory through the **unchanged Phase 04 geometry** to obtain predicted strikes with Time-to-Impact; commit through the **unchanged Phase 05 policy**; and measure, with the frozen Phase 09 harness, whether this yields useful prediction lead time against false-positive, false-negative, timing-error, trajectory-error, and CPU-latency constraints — compared with Baselines A, B, and C-GBDT. The phase selects a model family and horizon **on multi-criteria evidence**, not accuracy alone.

## Why This Phase Exists

This phase is the research contribution. The rest of the roadmap exists to make its inputs trustworthy (Phases 02–08), its measurements fair (Phase 09), and its outputs usable (Phases 13–17). Section *Algorithms / Technical Approach* answers the mandatory questions: why temporal modelling, why frame-wise classification is insufficient, why trajectory prediction, how causal context is built, how the future trajectory is represented, how the horizon is chosen experimentally, how the predicted trajectory becomes a predicted strike, how lead time is measured, how false positives are controlled, and how the model is compared with simpler baselines.

## Relationship to Research Contribution

Direct. Success criterion 2 ("useful measurable Prediction Lead Time compared with the Reactive Baseline without unacceptable False Positives") is tested here on held-out participants for the first time, with the final confirmatory run reserved for Phase 18.

## Inputs

- Phase 08 samples per fold (`X[N×F]`, masks, trajectory targets `T[K×2]`, auxiliary targets), normalisation stats, feature schema `fs-v1`.
- Phase 09 harness (frozen version), Baseline A/B/C-GBDT results, primary `W`, operating-point selection rules, reporting templates.
- Phase 04 geometry and Phase 05 commit policy (frozen versions).
- Measured stage latencies (Phases 02, 03, 08) for the `Δ_proc` policy.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-002, REQ-041, REQ-042, REQ-043, REQ-044, REQ-050b, REQ-109, REQ-112, REQ-113, REQ-117, REQ-306; contributes to REQ-005, REQ-040, REQ-060b, REQ-302.

## Expected Outputs

- `models/temporal/` package: causal GRU and causal TCN trajectory predictors, training loop, export, `Anticipator` adapter (`source = MODEL`).
- Trained models per fold and per configuration in the sweep, with manifests (config hash, seed, dataset/labels/feature versions).
- Experiment reports: horizon sweep, history-window sweep, model-family comparison, lead-time vs. FP curves per model, timing error, trajectory error (ADE/FDE, impact-position error), FN, zone accuracy (geometry-derived), CPU inference latency.
- Comparison table vs. A, B, C-GBDT on CV folds (selection) and on test participants (one confirmatory run per pre-declared operating point).
- Failure-case catalogue.
- Model-selection ADR with the multi-criteria rationale.
- Reproducibility manifest for every run.

## Dependencies

- Phase 09 Exit Gate.

## System Components

- `src/spacedrums/models/temporal/{gru.py, tcn.py, heads.py, losses.py, train.py, data.py, export.py, adapter.py, decode.py}`
- `src/spacedrums/eval/` (Phase 09; extended only with the MODEL arm wrapper)
- `scripts/{train_temporal, sweep_horizon, sweep_window, eval_temporal, latency_temporal, failure_cases}.py`
- `experiments/phase-10/`

## Architecture

```
X[N×F] (causal window, masked, normalised per fold)
   │
   ▼ Causal temporal encoder
   ├─ GRU: unidirectional, 1–2 layers (candidate), hidden size h (tunable); state carried across frames online
   └─ TCN: stack of causal dilated 1-D convolutions (left-padded only), receptive field ≥ N (kernel/dilation tunable)
   │
   ▼ Trajectory head (PRIMARY): K future tip displacements Δp̂_k = p̂_{i+k} − p_i, k = 1..K  (linear or small MLP; optional velocity outputs)
   ▼ Auxiliary head (OPTIONAL in this phase): strike_within_H logit  (used for gating experiments only, never as the sole strike source)
   │
   ▼ decode.py: reconstruct absolute (t_i + k·dt_step, p_i + Δp̂_k), k = 1..K
   │
   ▼ Phase 04 geometry.intersect(predicted, MODEL) ──► StrikeCandidate {t_impact_pred, TTI, zone, impact_pos, crossing_velocity, intensity_proxy}
   │
   ▼ Phase 05 commit policy (unchanged) ──► CommittedStrike
```

- **Causal encoder guarantee:** GRU is unidirectional; TCN uses left padding only; no bidirectional layers, no attention over future positions, no batch-norm statistics from future frames at inference (use layer/instance norm or frozen running stats).
- **Trajectory-first is structural:** there is no code path from the model to a `CommittedStrike` that bypasses `geometry.intersect`. The auxiliary strike logit may only *gate* a geometry-derived candidate (Task 10.9).
- **Per-hand:** one model applied independently to each hand's window (shared weights; `hand_id` is not an input unless an experiment says otherwise — ablation candidate).

## Detailed Tasks

### Checkpoint 10.A — Model infrastructure

#### Task 10.1 — Data Loader and Fold Protocol
- **What:** Load Phase 08 samples per fold; apply fold-specific normalisation; sampling strategy for imbalance (candidates: uniform over frames; over-sampling of pre-impact windows with a recorded ratio; none) — recorded; deterministic shuffling by seed.
- **Why:** Reproducible, leakage-free training.
- **Depends on:** Phase 08 outputs.
- **Evidence:** Loader tests (fold isolation, mask alignment); seed determinism test.

#### Task 10.2 — Causal GRU Predictor
- **What:** Unidirectional GRU encoder → trajectory head; hidden size, layers, dropout **tunable**; stateful mode for online use (carry hidden state per hand; reset on `INVALID/STALE`); stateless windowed mode for offline training/eval; test that both modes agree on a recorded sequence.
- **Why:** Q44 candidate; lightweight on CPU.
- **Depends on:** 10.1.
- **Evidence:** Unit tests; `TEST-CAUSAL-1/2` pass (future perturbation; truncation to `N`); stateful/stateless agreement test.

#### Task 10.3 — Causal TCN Predictor
- **What:** Causal dilated conv stack with residual blocks; kernel size, dilations, channels **tunable**; receptive field computed and asserted ≥ `N`; left padding only.
- **Why:** Q44 candidate; fixed receptive field, parallel training, often low CPU latency.
- **Depends on:** 10.1.
- **Evidence:** Receptive-field test; `TEST-CAUSAL-1/2` pass.

#### Task 10.4 — Losses
- **What:** Trajectory loss candidates: L1, L2 (MSE), Huber on displacements; optional per-step weighting (emphasise near-horizon steps, or emphasise steps near the impact — candidates); optional velocity-consistency term. Auxiliary BCE for `strike_within_H` with weight `λ_aux` (tunable; `λ_aux = 0` is the pure-trajectory configuration and is the **default** for this phase). Masked steps (`T_mask`) excluded.
- **Why:** The primary objective is future motion; strike information is auxiliary by design.
- **Depends on:** 10.2/10.3.
- **Evidence:** Loss unit tests (masking, weighting).

#### Task 10.5 — Training Loop and Model Selection Protocol
- **What:** Per fold: train with early stopping on a **validation criterion that is not plain trajectory loss alone** — candidates: (a) trajectory ADE, (b) harness-derived FP-matched lead time on the validation participants (expensive; evaluate every `E` epochs), (c) a combined pre-declared score. Record the criterion used. Fixed epoch budget, seeds (≥ 3 seeds per configuration — candidate; minimum 2 if compute-limited, recorded), learning rate/schedule/optimizer tunable, gradient clipping candidate. Checkpoints with manifests.
- **Why:** Selection on the research-relevant criterion prevents choosing a model that predicts smooth trajectories but commits poorly.
- **Depends on:** 10.4, Phase 09 harness.
- **Evidence:** Training logs; manifests; validation curves.

#### Task 10.6 — `Anticipator` Adapter and Decoding
- **What:** Wrap a trained model as an `Anticipator`: window assembly from streaming features (Phase 08), inference, decode displacements to absolute positions with `dt_step` (= frame period at the recording FPS by default; the adapter must interpolate/resample if the live `dt` differs — Phase 13), emit `TrajectoryPrediction` (`anticipator_id`, `model_hash`), then geometry → candidates. Predicted `crossing_velocity` from consecutive predicted points; `intensity_proxy` from `v̂·n_in` at the predicted crossing.
- **Why:** Trajectory-first bridge; identical for offline replay and live.
- **Depends on:** 10.2/10.3, Phase 04.
- **Evidence:** Adapter tests; replay through Phase 09 harness produces candidates/commits.

#### Task 10.7 — Export and CPU Latency
- **What:** Export to ONNX (and/or TorchScript); verify numerical parity with the PyTorch model on a fold's samples (tolerance recorded); measure batch-1 latency p50/p95/p99 on the development CPU for each configuration in the final comparison (thread count recorded); also measure the stateful-GRU per-frame cost vs. windowed re-computation.
- **Why:** README §10 inference latency; CPU-first; selection criterion.
- **Depends on:** 10.6.
- **Evidence:** Parity report; latency tables (MEASURED).

### Checkpoint 10.B — Experiments (on CV folds)

#### Task 10.8 — Prediction-Horizon Sweep
- **What:** For each model family, train/evaluate over a grid of `K` (steps) / `H = K·dt_step` (candidate grid spanning from one frame ahead to several frames ahead; exact values recorded relative to the measured FPS). For each `H`: trajectory ADE/FDE by step; via the harness: lead-time distribution, FP/min, FN, timing error, zone accuracy at a sweep of `τ_commit`/`p_commit` (candidate = geometry-derived candidates gated by predicted TTI ≤ τ_commit). Produce, per `H`, the lead-time vs. FP curve. Report the trade-off table (lead time, FP, timing error, latency) — the horizon is **chosen from this table by a pre-declared rule** (e.g. maximise median `L_pred` subject to FP/min ≤ the FP budget defined in Task 10.11 and timing-error MAE ≤ a bound — the budget/bound values themselves are To Be Experimentally Determined from Baseline A's FP behaviour and from the audio-timing tolerance discussion in Phase 18's protocol, and are written down *before* the test-participant run).
- **Why:** Q40 — lead time is determined experimentally; longer horizons increase potential lead time but increase trajectory error and FP.
- **Depends on:** 10.5–10.7.
- **Evidence:** Sweep report with curves and tables (MEASURED, CV folds).

#### Task 10.9 — History-Window Sweep and Auxiliary Gating
- **What:** Sweep `N` (candidate grid from short to long history); at the chosen `H`, report the same metrics. Separately test auxiliary gating: candidates from geometry are additionally required to have `strike_within_H` probability ≥ `p_aux` (sweep) — compare the lead-time/FP curve with and without gating (`λ_aux = 0` vs. `> 0`). Gating is *optional post-processing*, never a replacement for geometry.
- **Why:** Ablation groundwork (Phase 19 short/long history); FP control mechanism evaluation.
- **Depends on:** 10.8.
- **Evidence:** Report (MEASURED).

#### Task 10.10 — Model-Family Comparison (GRU vs. TCN vs. C-GBDT vs. B)
- **What:** At the chosen `H`, `N`, and per-arm validation-selected operating points (same rules as Phase 09), compare all arms on the CV folds: lead time (median, IQR, fraction `> 0`), FP/min, FN, timing error (MAE, bias), zone accuracy, trajectory ADE/FDE (for trajectory-producing arms), intensity-proxy agreement (predicted crossing speed vs. GT proxy), inference latency, parameter count, memory. Per-participant tables with bootstrap CIs.
- **Why:** Q44 — selection not by accuracy alone; the comparison must allow B or C-GBDT to win.
- **Depends on:** 10.8, 10.9, Phase 09 results.
- **Evidence:** Comparison report; ADR for model selection listing every criterion and the trade-offs.

#### Task 10.11 — False-Positive Budget and Control Mechanisms
- **What:** Define (pre-declared, before test-participant evaluation) an FP budget in FP/min or FP fraction, justified from Baseline A's measured FP behaviour and playability considerations (candidate: "no worse than A by more than a stated margin" or a stakeholder-set absolute value — Open Question for the owner, resolved and recorded before Task 10.13). Evaluate control mechanisms: `τ_commit`, `p_commit` (aux), `n_confirm` (temporal consistency of consecutive predictions), predicted-crossing-speed threshold, refractory. Report which mechanisms trade lead time for FP most favourably. FP attribution by segment type (fake swing, stop-before-impact, between zones, tracking loss).
- **Why:** The primary analysis is lead time vs. FP; the control knobs must be understood.
- **Depends on:** 10.8–10.10.
- **Evidence:** FP-control report (MEASURED); budget ADR.

#### Task 10.12 — Failure-Case Catalogue
- **What:** Extract and visualise the worst cases: largest positive timing error (sound too early), FPs on fake swings/stops, FNs on fast hits, wrong zone on adjacent zones, behaviour after tracking gaps, behaviour at the ROI boundary, per-participant outliers (e.g. unusual grip). Include predicted vs. actual trajectories.
- **Why:** Q59/60 honest limitations; feeds Phase 17 hardening and Phase 21 thesis.
- **Depends on:** 10.10.
- **Evidence:** Catalogue with figures.

### Checkpoint 10.C — Confirmatory evaluation

#### Task 10.13 — Test-Participant Evaluation (single pre-declared run)
- **What:** With `H`, `N`, model family, operating points, FP budget, and `W` all frozen from CV results, run **once** on the held-out test participants for A, B, C-GBDT, and the selected temporal model(s); report the full metric set with per-participant CIs. No re-tuning after seeing test results. Additional exploratory analyses on test data are labelled exploratory.
- **Why:** Unbiased estimate; Phase 18 will repeat this as the final confirmatory experiment (with live measurements added), so the protocol must already be clean here.
- **Depends on:** 10.8–10.12.
- **Evidence:** Test report (MEASURED); frozen-config manifest with hashes that predates the run.

#### Task 10.14 — Reproducibility Package
- **What:** For the selected model: config, seeds, dataset/labels/feature/harness versions, training logs, checkpoints, exported model + hash, evaluation manifests; a script that re-runs evaluation from the exported model and reproduces the reported numbers (tolerance recorded).
- **Why:** README §4 VALIDATED requires reproduction.
- **Depends on:** 10.13.
- **Evidence:** Re-run matches; VALIDATED status recorded only after a second person (or clean environment) reproduces.

## Data Requirements

- `ds-v1.0` folds and test participants only; no new data.
- Sample counts and positives per fold reported; if positives per fold are few, report CIs and avoid over-claiming.

## Algorithms / Technical Approach

### Why temporal modelling is necessary
A strike is defined by a *future* event (entry through an impact surface). Whether the current motion leads to an entry depends on the recent history — acceleration profile, direction consistency, distance and closing speed to the surface, phase of the stroke (upstroke vs. downstroke), stick-axis rotation — not on a single frame's position/velocity. Fake swings and stop-before-impact motions share single-frame states with real strikes at some instants; only the temporal evolution separates them. A causal temporal model can integrate this history and output a prediction *before* the entry occurs, which is the only way to obtain lead time.

### Why frame-by-frame classification is insufficient
1. A per-frame "strike now" classifier can at best fire on the frame at which the entry is observed — i.e. it is Baseline A with extra steps and zero lead time.
2. A per-frame "strike within `H`" classifier without trajectory has no notion of *when* within `H` or *where*; committing sound on such an output produces timing error up to `H` and cannot schedule audio at the impact time.
3. It cannot explain a decision (which zone, which trajectory), cannot be tuned per zone geometry, and cannot generalise to a changed zone layout (Phase 14 calibration) without retraining, because the geometry is baked into the labels.
4. It offers no path to Time-to-Impact, impact position, or an intensity proxy other than adding more independent heads — which is Phase 11's multi-task question, evaluated *against* the trajectory route, not instead of it.

### Why trajectory prediction is useful
- **Lead time with timing:** a predicted trajectory crossing the impact surface at `t_impact_pred` gives both *whether* and *when* → audio can be scheduled at the predicted impact (Phase 04/05), not merely "soon".
- **Separation of learning and geometry:** the model learns motion; geometry decides impact under the same rules as the reactive baseline and the labels; zones can move (calibration) without retraining.
- **Explainability:** the debug overlay (Phase 15) can show the predicted path and the predicted crossing; failures are diagnosable (bad trajectory vs. bad geometry vs. bad commit threshold).
- **Multi-output for free:** zone, impact position, crossing velocity (intensity proxy), TTI all derive from one predicted trajectory.
- **Extensibility:** the same route works for any tracked point (future kick/foot zone; README §12).

### How causal temporal context is constructed
Phase 08: a window of the last `N` frames of per-hand features (positions, velocities, accelerations, axis, hand, zone-relative distances, confidence, `dt`), masked for invalid frames, normalised with train-only statistics. The model sees only frames `≤ i`. Online (Phase 13), the same features come from a ring buffer; GRU hidden state is carried per hand and reset on tracking loss.

### How the future trajectory is represented
Primary: `K` future displacements of the tip relative to the current tip at fixed `dt_step` (candidates: `dt_step` = frame period). Alternatives to record as Phase 12 options: absolute positions; polynomial coefficients; predicted velocities per step; multi-modal (mixture) outputs; uncertainty per step. The displacement representation is translation-invariant and matches how geometry consumes points.

### How the prediction horizon is selected experimentally
Task 10.8: sweep `H`; for each, obtain the lead-time/FP/timing-error/latency table; choose by a pre-declared rule with an FP budget (Task 10.11). Longer `H` ⇒ potentially larger lead time but larger FDE and more FPs; shorter `H` ⇒ lead time bounded by `H` minus processing delay. The useful lead time is bounded by `H − Δ_proc`; a horizon shorter than `Δ_proc` cannot help.

### How trajectory prediction connects to virtual geometry
`decode` → `(t, p̂)` list → `geometry.intersect(…, MODEL)` (Phase 04, Task 04.5): first valid downward/inward entry of the predicted path through an impact surface → `t_impact_pred`, `TTI`, zone, impact position, crossing velocity. Predicted paths that never cross, or cross upward, produce no candidate.

### How a predicted trajectory becomes a predicted strike
`StrikeCandidate(source=MODEL)` → Phase 05 commit policy: commit when `TTI ≤ τ_commit`, optional `n_confirm` consecutive consistent predictions (same zone, `t_impact_pred` stable within a tolerance), optional aux-probability gate, tracking `VALID`, not in refractory. `t_commit` is stamped; audio scheduled at `t_impact_pred`.

### How lead time is measured
Phase 09 harness: `L_pred = t_impact_est(GT) − t_commit` for matched events (`W` frozen), with `t_commit = t_capture[i] + Δ_proc` in replay (`Δ_proc` = measured stage latencies incl. model inference). Distributions per participant; fraction `> 0`; compared with B and C-GBDT at FP-matched operating points.

### How false positives are controlled
Commit-threshold sweep (`τ_commit`), temporal consistency (`n_confirm`), aux gating (`p_aux`), predicted crossing-speed floor (`v_min` on the predicted path), refractory, and the structural rule that commits require `VALID` tracking. FP budget pre-declared (Task 10.11). FPs attributed by segment type to show which behaviours cause them.

### How the model is compared with simpler baselines
Same folds, same `W`, same `Δ_proc` policy, same geometry and commit policy, same operating-point rules (Phase 09). B and C-GBDT curves on the same axes; per-participant paired differences with bootstrap CIs; latency and memory alongside. The selection ADR must state explicitly if a simpler arm is preferable on the combined criteria.

## Interfaces / Contracts

- Implements `Anticipator` (`source = MODEL`); emits `TrajectoryPrediction` with `anticipator_id`, `model_hash`, `K`, `dt_step`, positions (and optional aux).
- Model manifest: `{model_id, family, N, K, dt_step, F, feature_schema_id, norm_stats_id, fold, seed, config_hash, git_sha, dataset_version, labels_version, export_format, export_hash, latency_report_id}`.
- Harness MODEL-arm wrapper interface (Phase 09).

## Tests

- **Unit:** layers' causality (`TEST-CAUSAL-1/2` on each model); receptive-field assertion (TCN); stateful/stateless agreement (GRU); loss masking; decode round-trip; adapter output schema.
- **Leakage:** training loader fold isolation; normalisation stats source; no reference-track reads (Phase 08 test re-run).
- **Export parity:** PyTorch vs. ONNX/TorchScript outputs within tolerance.
- **Determinism:** same seed/config → same metrics within tolerance (recorded).
- **Harness integration:** MODEL arm through the replay simulator on one session produces schema-valid logs.

## Measurements

| Quantity | Where | Label |
|----------|-------|-------|
| Trajectory ADE/FDE per step and per `H` | Task 10.8 | MEASURED |
| `L_pred` distribution; fraction `> 0` | Tasks 10.8–10.13 | MEASURED |
| FP/min, FP fraction, FN rate; FP by segment type | Tasks 10.8–10.13 | MEASURED |
| Timing error `TE_pred` (MAE, bias, distribution) | Tasks 10.8–10.13 | MEASURED |
| Zone accuracy (geometry-derived); impact-position error | Tasks 10.10, 10.13 | MEASURED |
| Intensity-proxy agreement (r, ρ, MAE) | Task 10.10 | MEASURED |
| Inference latency p50/p95/p99; parameters; memory | Task 10.7 | MEASURED |
| Seed variance of all above | Task 10.5 | MEASURED |

## Experimental Design

- **Unit of analysis:** participant (folds grouped by participant; CIs by participant bootstrap).
- **Factors (CV):** model family {GRU, TCN}; `H` grid; `N` grid; `λ_aux ∈ {0, >0}`; commit-control knobs (sweeps). Seeds ≥ 3 per cell (candidate; recorded).
- **Pre-declared rules** (written to `docs/experiments/phase-10-prereg.md` before test runs): horizon selection rule, FP budget, operating-point rules, `W`, `Δ_proc` policy, success/failure interpretation (including what counts as "no useful lead time").
- **Comparators:** A (reference), B (CV/CA at its operating points), C-GBDT (both modes).
- **Confirmatory run:** one pass on test participants (Task 10.13).
- **Outcome neutrality:** the report template has sections for "temporal model better", "no material difference", and "baseline better" — whichever the data supports.

## Acceptance Criteria

1. GRU and TCN predictors implemented, causal tests pass, export parity verified, latency measured.
2. Horizon and window sweeps executed on CV folds with full metric tables and curves.
3. FP budget and all selection rules pre-declared and archived before the test run.
4. Model-family comparison vs. A/B/C-GBDT completed with per-participant CIs and a selection ADR that weighs all criteria.
5. Single confirmatory test-participant run executed and reported.
6. Failure-case catalogue produced.
7. Reproducibility package re-runs to the reported numbers.

## Definition of Done

- All acceptance criteria; reports with manifests; ADRs; gate record PASS; integrity checklist applied (no claim beyond measured CV/test numbers; effective-latency reduction not claimed — that requires Phase 18 live measurement).

## Risks

- Positives are sparse → high variance; mitigated by per-participant CIs and seed repeats; may limit conclusions — reported.
- Trajectory targets come from the causal tracker (noisy) → the model may learn tracker artefacts; reference-target experiment is an option (Open Question), never as input.
- Useful lead time may be bounded by processing delay on the laptop CPU → the `Δ_proc` policy makes this visible; Phase 16 may change it; report both `Δ_proc` settings.
- Baseline B may match the model → legitimate finding; ADR must say so.

## Failure Modes

- Model commits on fake swings → FP analysis by segment type; control knobs; Phase 11 aux heads may help or not.
- Model predicts smooth average trajectories (regression to the mean) → large FDE near reversal points; consider loss weighting or Phase 12 multi-modal outputs.
- Online/offline drift → Phase 13 parity test.

## Fallback Strategy

- If neither GRU nor TCN improves on B at the FP budget, the project still has a defensible negative/neutral result; Phases 11–12 investigate whether aux heads/extensions change it; Phase 13 integrates the best arm on evidence (which may be B).
- If CPU latency of the best model is too high, select the best model within the latency budget and record the trade-off.

## Artifacts Produced

- `src/spacedrums/models/temporal/`
- `docs/experiments/phase-10-prereg.md`
- `docs/reports/phase-10-horizon-sweep.md`, `phase-10-window-aux.md`, `phase-10-model-comparison.md`, `phase-10-fp-control.md`, `phase-10-failure-cases.md`, `phase-10-test-run.md`
- `docs/decisions/ADR-<n>-fp-budget.md`, `ADR-<n>-model-selection.md`, `ADR-<n>-horizon.md`
- `models/temporal/<model_id>/{checkpoint, export, manifest.json, latency.json}`
- `experiments/phase-10/<run_id>/…`
- `docs/gates/phase-10-gate.md`

## Exit Gate

Reviewer verifies pre-registration predates the test run, causality/leakage tests, comparison report, ADRs, reproducibility re-run. PASS → Phase 11 (and Phase 13 may start integration of the selected arm in parallel with 11/12 if the owner decides so; recorded).

## What Must NOT Be Done Yet

- No multi-task heads beyond the single optional aux logit (Phase 11).
- No Transformer, attention, or uncertainty outputs (Phase 12).
- No live integration (Phase 13).
- No re-tuning on test participants.
- No claims of effective-latency reduction (Phase 18).
- No use of future frames anywhere in inference or evaluation.

## Open Questions

- FP budget value/rule (owner decision before Task 10.13).
- Reference-track trajectory targets as an experiment (labels only; never input)?
- Should `hand_id` be an input (shared model) or should separate models per hand be tried? (ablation candidate)
- Selection criterion for early stopping: trajectory loss vs. harness-derived metric (Task 10.5; cost trade-off).

## Decisions That Must Be Experimentally Validated

- Horizon `H`/`K` (Task 10.8).
- History window `N` (Task 10.9).
- Model family and size (Task 10.10).
- `λ_aux` and gating (Task 10.9).
- Loss type and step weighting (Task 10.4 sweep within budget).
- Commit-control operating points (Task 10.11).
- Sampling/imbalance strategy (Task 10.1).
