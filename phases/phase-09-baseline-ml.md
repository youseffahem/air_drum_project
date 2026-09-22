# Phase 09 — Baseline ML Model & Evaluation Harness

## Status

Development implementation underway; participant measurements and exit gate pending.
See `docs/gates/phase-09-gate.md` for the exact evidence and blockers.

## Purpose

Build the **evaluation harness** that every later phase reuses — a causal replay simulator that drives the real geometry and commit logic frame by frame from recorded data, event matching, and all canonical metrics (README §10) with per-participant reporting — and use it to obtain the first measured offline results for **Baseline A (reactive)** and **Baseline B (rule-based anticipation)** on the participant-level folds. Then train and evaluate the **C-GBDT** learned baseline on flattened window features. Freeze the harness, the primary matching tolerance `W`, and the reporting formats before the temporal models are built.

## Why This Phase Exists

Without a single, tested harness, A/B/C comparisons would use different matching rules, different tolerances, or different commit logic, and the primary research figure (lead time vs. false positives) would be incomparable across arms. The GBDT baseline establishes what a strong non-temporal (flattened-window) learner achieves, so that Phase 10 cannot attribute gains to "learning" when a tree model on the same features would do as well.

## Relationship to Research Contribution

- Implements the measurement of `L_pred`, FP/FN, timing error, zone accuracy, trajectory error, intensity agreement, and inference latency exactly as defined in README §10.
- Produces the first measured Baseline A `L_sys`-related quantities on participant data (software-stamped) and the first lead-time/FP curves for Baseline B — the yardsticks for the temporal model.
- C-GBDT is the "simpler learned baseline" the research must beat *or not* — the design allows either.

## Inputs

- `ds-v1.0`: causal tracks, labels, splits, session metadata, timing logs.
- Phase 08 feature samples and normalisation stats per fold.
- Phase 04 geometry, Phase 05 commit policy and rule-based anticipator (frozen versions).
- README §10 metric definitions.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-005, REQ-040, REQ-043, REQ-044, REQ-045, REQ-303, REQ-308; contributes to REQ-060b, REQ-302.

## Expected Outputs

- `eval` package: causal replay simulator, event matcher, metrics, report generator, curve plotting, result manifests.
- Harness validation report (synthetic cases with known answers).
- Baseline A and B offline results on all folds and the held-out test participants (MEASURED), including the `W` sweep and the commit-threshold sweep for B (lead time vs. FP curves).
- C-GBDT models per fold + results (MEASURED), CPU inference latency.
- Frozen primary `W`, frozen reporting templates, frozen harness version hash.

## Dependencies

- Phase 08 Exit Gate.

## System Components

- `src/spacedrums/eval/{replay.py, matching.py, metrics.py, curves.py, report.py, manifest.py}`
- `src/spacedrums/models/gbdt/{train.py, predict.py, adapter.py}` (adapter turns GBDT outputs into `TrajectoryPrediction`/`StrikeCandidate` via geometry where applicable)
- `scripts/{validate_harness, eval_baselines, train_gbdt, eval_gbdt}.py`
- `experiments/phase-09/`

## Architecture

### Causal replay simulator

```
for session in fold:
  for hand in {LEFT, RIGHT}:
    reset per-hand state (tracker state is replayed from tracks_causal; features via streaming.py; anticipator; commit)
    for frame i in order:
      t_now = t_capture[i] + simulated processing delay (configurable: 0 or measured stage latencies from Phases 03/08 + model latency)
      features_i = streaming(track[i])             # past-only
      pred = anticipator.predict(history ≤ i)      # RULE or MODEL; None for arm A
      candidates = geometry.intersect(observed ≤ i, REACTIVE) if arm A
                 = geometry.intersect(pred, RULE/MODEL) if arm B/C
      committed = commit.step(candidates, track_state[i], t_now)
      log candidates, committed (with t_commit = t_now)
```

- **Causality:** the simulator exposes only frames `≤ i`; `TEST-CAUSAL-1` is run *on the simulator itself* (perturb future frames, compare logs).
- **Simulated processing delay:** `t_commit` in replay = `t_capture[i] + Δ_proc`, where `Δ_proc` is either 0 (idealised) or the measured per-stage latencies (capture + tracking + features + inference for the arm). Both settings are reported; the measured-delay setting is the primary one because lead time must be judged against real processing cost.
- **Same code** as live: geometry and commit modules are imported, not re-implemented.

### Event matching and metrics — exactly README §10.

### Reporting
- Per fold, per participant, pooled; per hand; per zone; per segment type (positives from hit segments; FPs attributed to the segment type they occur in — fake swing, stop-before-impact, between-zones, etc.).
- Curves: for each arm, sweep the commit threshold (`τ_commit`, `p_commit`) → (median `L_pred`, FP per minute, FN rate) points; primary figure = lead time vs. FP per minute.
- Result manifest per run (Phase 00 schema) with config hash, dataset/labels version, harness version, seed.

## Detailed Tasks

### Task 09.1 — Replay Simulator
- **What:** Implement the loop above with pluggable arm (`A`, `B`, `MODEL:<id>`), pluggable `Δ_proc` policy, per-hand state, and full logging.
- **Why:** Offline evaluation identical in logic to live behaviour.
- **Depends on:** Phase 04/05 modules, Phase 08 streaming features.
- **Evidence:** Replaying a Phase 05 developer session reproduces its live `CommittedStrike` log (given identical config and `Δ_proc = live stamps`).

### Task 09.2 — Event Matching
- **What:** Implement README §10.1 (per hand, greedy one-to-one by |Δt| within `W`); support a `W` sweep; output matched pairs, unmatched S (FP), unmatched G (FN), with attributes for stratification.
- **Why:** All metrics depend on it.
- **Depends on:** Phase 07 labels.
- **Evidence:** Unit tests with hand-constructed cases (multiple candidates, ties, boundary at `W`).

### Task 09.3 — Metrics Implementation
- **What:** All README §10.2 metrics; distributions (median, IQR, p10/p90), bias/MAE, counts, rates per minute of *active playing time* (defined: total accepted segment time excluding tracking-loss intervals; recorded).
- **Why:** Canonical definitions.
- **Depends on:** 09.2.
- **Evidence:** Unit tests on synthetic matched sets with known answers.

### Task 09.4 — Harness Validation on Synthetic Sessions
- **What:** Generate synthetic tracks with known impacts (parabolic swings into zones, fake swings, stops), run A and B through the simulator, and confirm: A detects every impact with negative lead time equal to the frame-quantization + `Δ_proc`; B's lead time equals the analytically expected value for CV/CA on parabolic motion; FP/FN counts match construction; `TEST-CAUSAL-1` passes on the simulator.
- **Why:** The harness must be trusted before any real result.
- **Depends on:** 09.1–09.3.
- **Evidence:** Validation report; all synthetic checks pass.

### Task 09.5 — Baseline A Offline Results
- **What:** Run A on all folds and the test participants with `Δ_proc` = measured stage latencies (Phases 02/03) and `Δ_proc = 0`; report FN/FP (A can still produce FPs — e.g. upward crossings mis-classified — and FNs from tracking loss), the distribution of `L_pred` (negative), zone accuracy, and the software-stamped `L_sys` decomposition using Phase 04's measured audio latency.
- **Why:** Defines the reactive reference for the whole thesis.
- **Depends on:** 09.4.
- **Evidence:** Result tables per participant/pooled (MEASURED); manifest.

### Task 09.6 — Baseline B Offline Results and Sweeps
- **What:** Run B (CV and CA) with sweeps over horizon `H`, `τ_commit`, `p_commit` (and `n_confirm`) on the CV folds; produce lead-time vs. FP curves; select B's operating points (e.g. an FP-matched point and a lead-time-matched point — selection rule pre-declared) on validation folds; evaluate at those points on the test participants; report timing error, zone accuracy, FN.
- **Why:** The rule-based anticipation arm of the comparison; establishes the non-learned frontier.
- **Depends on:** 09.5.
- **Evidence:** Curves and tables (MEASURED); operating points recorded in config.

### Task 09.7 — `W` Sweep and Primary Tolerance Freeze
- **What:** Report A and B metrics across the `W` sweep; choose the primary `W` by a pre-declared rule (candidate rule: smallest `W` at which A's match rate on clean single-hit segments saturates, or a value justified from the measured `t_impact_est` uncertainty in Phase 07); freeze it for Phases 10–19; keep the sweep in appendices.
- **Why:** Tolerance choice must not be tuned to favour any arm later.
- **Depends on:** 09.5, 09.6.
- **Evidence:** ADR with the rule and the chosen `W`.

### Task 09.8 — C-GBDT Baseline
- **What:** Flatten the Phase 08 window `X[N×F]` (masks as extra inputs or masked-value encoding); train gradient-boosted trees per fold for: (i) `strike_within_H` (binary), (ii) `tti` regression (on positives), (iii) zone classification (on positives), (iv) coarse future displacement regression at a few horizons (e.g. `k ∈ {K/2, K}`, candidates) — head (iv) allows a *trajectory-derived* strike via geometry so that C-GBDT can also be run through the trajectory-first path, not only through a direct probability. Hyperparameters (trees, depth, learning rate, class weights) **tunable** by validation-fold search with a fixed budget recorded. Seeds fixed. Two evaluation modes: **direct** (probability + tti → candidate) and **trajectory-derived** (displacements → geometry → candidate); both go through the same commit policy.
- **Why:** Q44 baseline; guards against over-attributing gains to temporal architectures.
- **Depends on:** Phase 08 samples; 09.1.
- **Evidence:** Models per fold with hashes; results tables and curves in both modes (MEASURED); validation-search log.

### Task 09.9 — C-GBDT Inference Latency
- **What:** Measure per-call latency (batch 1) on the development CPU for the flattened feature vector; p50/p95/p99; thread count recorded.
- **Why:** README §10 inference latency; CPU-first.
- **Depends on:** 09.8.
- **Evidence:** Experiment-log JSON.

### Task 09.10 — Reporting Templates and Harness Freeze
- **What:** Standard tables/figures (per-arm metric table; per-participant table; lead-time vs. FP curve; timing-error histogram; zone confusion; FP-by-segment-type breakdown); harness version hash frozen; a "how to add an arm" note for Phase 10.
- **Why:** Phases 10–19 must produce comparable outputs.
- **Depends on:** All above.
- **Evidence:** Templates; frozen version recorded.

## Data Requirements

- `ds-v1.0` folds and test participants; Phase 08 samples.
- Synthetic sessions for validation (generated by test code, clearly not data).

## Algorithms / Technical Approach

- Replay: deterministic loop with injected processing delay.
- Matching: greedy by |Δt| (Hungarian as an optional check that results do not differ materially — recorded).
- Metrics: as defined.
- GBDT: LightGBM/XGBoost candidates; class-weighting or focal-style reweighting as candidates for imbalance (reported).
- Curves: threshold sweep with interpolation-free plotting of achieved operating points.

## Interfaces / Contracts

- Arm interface: `Arm.run(session, hand, config) -> (candidates, committed)`; MODEL arms wrap an `Anticipator`.
- Results schema: `results.json` per run (metrics keyed by stratum), `events.parquet` (matched/unmatched with attributes), `curve.json`.
- Frozen constants file: `eval/constants.py` (`W_primary`, active-time definition, `Δ_proc` policy names).

## Tests

- **Unit:** matching cases; each metric on synthetic sets; active-time computation; curve point generation.
- **Causality:** `TEST-CAUSAL-1` on the simulator; on the GBDT arm (future frame perturbation).
- **Reproduction:** replaying a Phase 05 developer session reproduces its live commit log (Task 09.1).
- **Leakage:** GBDT training uses only fold-train participants; stats from Phase 08 per fold.

## Measurements

| Quantity | Arm | Label |
|----------|-----|-------|
| FN, FP (rate, per minute), `L_pred` distribution, zone accuracy, timing error | A, B (CV/CA), C-GBDT (direct, trajectory-derived) | MEASURED per fold/test |
| Lead-time vs. FP curves | B, C-GBDT | MEASURED |
| Software-stamped `L_sys` decomposition | A | MEASURED |
| Trajectory ADE/FDE | C-GBDT (iv) | MEASURED |
| Inference latency p50/p95/p99 | C-GBDT | MEASURED |
| Harness validation checks | synthetic | pass/fail |

## Experimental Design

- **Folds:** Phase 07 participant-grouped CV for selection; frozen test participants for final numbers; report both.
- **Pre-declared selection rules** for operating points and `W` (written before running on test participants).
- **Statistics:** per-participant medians with bootstrap CIs (participant-level resampling); paired comparisons between arms on the same events where applicable; no significance claims beyond what the sample size supports (state `P`).
- **No arm is favoured:** same commit policy, same `W`, same `Δ_proc` policy, same folds.

## Acceptance Criteria

1. Harness validated on synthetic sessions; `TEST-CAUSAL-1` passes on the simulator; developer-session reproduction passes.
2. Baseline A and B results reported on folds and test participants with curves and per-participant tables.
3. Primary `W` frozen by a pre-declared rule (ADR).
4. C-GBDT trained per fold, evaluated in both modes, latency measured.
5. Reporting templates and harness version frozen.

## Definition of Done

- Implementation, tests, validation report, baseline results, GBDT results, ADRs, gate record PASS; integrity checklist applied (all numbers MEASURED with manifests; no interpretation that the temporal model "will" beat these).

## Risks

- Baseline B might already achieve substantial lead time with acceptable FP → this is a legitimate outcome; Phase 10 must then show whether learning adds anything.
- Small `P` → wide CIs; reported honestly.
- Class imbalance (few positives per minute) → reweighting candidates; FP-per-minute metric is imbalance-robust.

## Failure Modes

- Harness bug inflating lead time (e.g. using `t_impact_est` from the future to gate commits) → synthetic validation + causality test.
- Different `Δ_proc` between arms → single policy enforced in `constants.py`.

## Fallback Strategy

- If GBDT training is impractical on the flattened dimension, reduce `N` or use the Phase 08 lite schema — recorded, and the same reduction offered to Phase 10 for fairness.

## Artifacts Produced

- `src/spacedrums/eval/`, `src/spacedrums/models/gbdt/`
- `docs/reports/phase-09-harness-validation.md`, `phase-09-baselines-AB.md`, `phase-09-gbdt.md`
- `docs/decisions/ADR-<n>-W-primary.md`, `ADR-<n>-operating-point-rules.md`
- `experiments/phase-09/<run_id>/{results.json, events.parquet, curve.json, config.snapshot.yaml}`
- `models/gbdt/fold-*/model.* + manifest.json`
- `docs/gates/phase-09-gate.md`

## Exit Gate

Reviewer verifies harness validation, baseline results with manifests, `W` ADR, GBDT results. PASS → Phase 10.

## What Must NOT Be Done Yet

- No GRU/TCN/Transformer training.
- No changes to commit policy tuned on test participants.
- No live integration of GBDT (Phase 13 decides which arms go live).
- No latency-reduction or "prediction works" claims.

## Open Questions

- Should the Hungarian matcher replace greedy if results differ? (check; record)
- Should `AMBIGUOUS` events be excluded from FP counting only, or also from active time? (decide; record in constants)
- Use idealised `Δ_proc = 0` as a secondary headline, or appendix only?

## Decisions That Must Be Experimentally Validated

- Primary `W` (Task 09.7).
- B's default extrapolation model (CV vs. CA) and horizon (Task 09.6).
- GBDT hyperparameters and imbalance handling (Task 09.8).
- Active-time definition's sensitivity (report both with and without excluding loss intervals).
