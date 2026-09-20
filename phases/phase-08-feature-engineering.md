# Phase 08 — Feature Engineering

## Status

Planned

## Purpose

Define, implement, test, and version the **causal** per-hand kinematic feature schema that feeds Baseline C-GBDT (Phase 09) and the temporal models (Phases 10–12), with normalisation computed strictly on training participants, explicit handling of variable frame intervals, gaps, and tracking state, leakage tests, feature-group definitions for the Phase 19 ablations, and a measured feature-computation latency. The same code path must run offline (dataset) and online (Phase 13).

## Why This Phase Exists

The temporal model's input is not raw video; it is a sequence of kinematic descriptors of the tracked tip and hand. Choices made here — what is included, how time is represented, how gaps are masked, where normalisation statistics come from — determine both what the model can learn and whether the evaluation leaks information. Doing this once, versioned and tested, prevents each model phase from re-inventing incompatible inputs.

## Relationship to Research Contribution

- The features encode the *past motion* in "Past Motion → Causal Temporal Model → Future Trajectory".
- Feature groups (position, velocity, acceleration, stick axis, hand landmarks, zone distances, tracking confidence, time delta) map one-to-one onto the Phase 19 ablation questions.
- Feature-computation latency is a term of the end-to-end decomposition (README §5.3).

## Inputs

- `ds-v1.0`: `tracks_causal.jsonl` per session (Phase 07), `LabelRecord`s, split files, session metadata, zone layout used during recording.
- Phase 01 `KinematicFeatures` contract; Phase 03 `TrackState` fields.

## Expected Outputs

- Feature schema v1 (`feature-schema-v1.md` + machine-readable descriptor: names, units, group, causal derivation, mask rules).
- `features` module (offline batch + online streaming implementation sharing one core).
- Normalisation-statistics computation per split/fold (train participants only) with stored stats files.
- Windowing utilities (history window `N`, target horizon `K`, stride) producing model-ready tensors with masks and target trajectories from the *causal* track's future positions (see Task 08.7 for what "target" means).
- Leakage/causality tests (`TEST-CAUSAL-1/2` on features; reference-track exclusion test).
- Feature-computation latency measurement.

## Dependencies

- Phase 07 Exit Gate.

## System Components

- `src/spacedrums/features/{core.py, groups.py, normalize.py, windows.py, targets.py, streaming.py, batch.py, schema.py}`
- `scripts/{build_features, compute_norm_stats, feature_latency}.py`
- `tests/features/` including causality and leakage tests.

## Architecture

```
tracks_causal (per hand, per frame: TrackState fields, t_capture, status) + zone layout
   │
   ▼ core.py  (per frame, causal: uses frame i and stored state from ≤ i)
KinematicFeatures[i] = { values[F], mask[F], dt, feature_schema_id }
   │
   ├─ batch.py     → arrays per session/hand; windows.py → (X[N×F], M[N×F], T[K×2], aux targets) samples
   └─ streaming.py → identical values from a ring buffer at runtime (Phase 13)

normalize.py: stats (mean/std or robust median/IQR — candidate) per feature, computed from TRAIN participants of each fold; applied to train/val/test of that fold only.
```

Causality rule (README §13): every feature at frame `i` is a function of `TrackState[≤ i]` and static config only. No centred differences, no future-looking smoothing, no target-derived features.

## Detailed Tasks

### Task 08.1 — Feature Schema v1
- **What:** Define the per-hand, per-frame feature vector with groups:
  - **POS:** tip position `(x, y)` (ROI-normalized); tip position relative to each zone's impact-surface centre `(dx_z, dy_z)` for all zones `z` (fixed layout; zone count = layout size).
  - **VEL:** tip velocity `(vx, vy)`, speed `|v|`, unit direction `(v̂x, v̂y)`, vertical velocity `vy` (explicit), signed speed along each zone's inward normal `v·n_z`.
  - **ACC:** tip acceleration `(ax, ay)`, `|a|`, tangential/normal decomposition relative to `v̂` (candidate).
  - **JERK (optional):** finite-difference derivative of acceleration from filter outputs — optional group, default off; tunable.
  - **AXIS:** stick axis angle `θ`, angular velocity `θ̇`, axis confidence, apparent stick length estimate.
  - **HAND:** selected hand landmarks relative to the wrist (candidate subset: wrist, index MCP, middle MCP, thumb tip — normalised by hand size), hand bbox size (distance proxy), handedness score.
  - **ZONE:** distance from tip to each impact surface (signed, along the normal) `d_z`; time-to-surface under constant velocity `d_z / max(v·n_z, ε)` (clipped; a rule-based cue offered to the learner, tunable inclusion).
  - **CONF:** tracking status one-hot (`VALID/DEGRADED`), tip confidence, frames since last valid, `dropped_since_last`.
  - **TIME:** `dt` (actual interval since previous frame), cumulative time since window start (for models needing it).
  - Store units, ranges, mask rules, and group membership for each feature; total dimension `F` reported.
- **Why:** Q41 inputs list (position, velocity, speed, acceleration, direction, vertical velocity, distance to zones, tracking confidence, time delta, optional jerk, recent trajectory history); ablation groups (Phase 19).
- **Depends on:** Phase 03 `TrackState`, Phase 04 zone layout.
- **Evidence:** Schema document + descriptor file; dimension `F` computed and recorded.

### Task 08.2 — Causal Core Implementation
- **What:** Implement feature computation from `TrackState` using filter outputs (velocity/acceleration from the Phase 03 filter, not re-differenced unless the filter lacks them), backward differences for any additional derivatives, variable `dt` from `t_capture`. State kept per hand (previous values) with reset on `INVALID/STALE`.
- **Why:** Same code online and offline; causal by construction.
- **Depends on:** 08.1.
- **Evidence:** Unit tests on synthetic tracks; `TEST-CAUSAL-1/2` pass.

### Task 08.3 — Masking and Gap Handling
- **What:** Rules: frames with `INVALID/STALE` → all features masked (`mask = 0`) and value set to a sentinel that is neutral after normalisation (0); `DEGRADED` → features present, `CONF` group flags it; windows containing more than `g_win` masked frames (tunable) are dropped from training/evaluation *of anticipation*, but retained for the safety analysis (Phase 17/18: no commits must occur there). Reset semantics documented.
- **Why:** Q34–35; models must learn that missing data is not motion.
- **Depends on:** 08.2.
- **Evidence:** Unit tests for masking; window-drop statistics reported per split.

### Task 08.4 — Normalisation Statistics
- **What:** Per fold: compute per-feature statistics on **training participants only** (candidates: z-score; robust median/IQR for heavy-tailed speed/acceleration — choose per feature group, recorded). Apply the same stats to that fold's validation and test. Store stats with fold id, dataset version, feature schema id. Angles encoded as `(sin θ, cos θ)` to avoid wrap-around (no normalisation).
- **Why:** Participant-level leakage prevention (README §13).
- **Depends on:** Phase 07 splits.
- **Evidence:** Stats files per fold; test asserting stats differ across folds and never include test participants.

### Task 08.5 — Windowing and Targets
- **What:** Build samples at each valid frame `i` (stride tunable): `X = features[i−N+1 … i]`, `M = mask`, targets from the **causal** track's own future: `T = tip[i+1 … i+K]` expressed relative to `tip[i]` (displacement representation; absolute stored too), and auxiliary targets from `LabelRecord`s: `strike_within_H` (any GT impact with `t_impact_est ∈ (t_i, t_i + H]`), `tti = t_impact_est − t_i` for the next GT impact (masked if none within `H_max`), `zone_id` of that impact, `impact_position`, `intensity_proxy_gt`. `N`, `K`, `H`, stride are **sweep parameters**, not fixed here. Also emit `t_i`, `hand_id`, `session_id`, `participant` for grouping.
- **Why:** Trajectory-first: primary target is future motion; strike-related targets are auxiliary. Using the causal track's future positions as the trajectory target keeps train/test consistent with what the online system can observe; using the reference track as trajectory target is an optional experiment (recorded in Phase 10 Open Questions) — never as model input.
- **Depends on:** 08.3, Phase 07 labels.
- **Evidence:** Sample builder tests (shapes, alignment of `t`, no future feature leakage: `X` uses only frames ≤ i); sample counts per fold/class reported.

### Task 08.6 — Reference-Track Exclusion Test
- **What:** A test that scans the `features/` and `models/` packages and their data loaders for any read of `tracks_reference*` and fails if found; plus a runtime guard in the loader.
- **Why:** The reference (non-causal) track is label-only (Phase 07).
- **Depends on:** Phase 07 file conventions.
- **Evidence:** Test in CI.

### Task 08.7 — Target Semantics Documentation
- **What:** Document precisely: (i) trajectory target = future *causal-tracked* tip positions (with their own noise), (ii) strike targets = from reference-derived GT labels, (iii) the implications: trajectory error is measured against the tracked future, strike timing against GT `t_impact_est`. Note that the model may legitimately learn to predict where the tracker will say the tip goes.
- **Why:** Prevents mis-interpretation of trajectory-error numbers in Phases 10/18.
- **Depends on:** 08.5.
- **Evidence:** Section in the schema document; referenced by Phase 10/18.

### Task 08.8 — Streaming Parity
- **What:** `streaming.py` computes the same `KinematicFeatures` from a ring buffer of live `TrackState`s; parity test: batch features on a recorded session == streaming features fed frame by frame (exact or tolerance).
- **Why:** Phase 13 online integration; `TEST-PARITY-1` groundwork.
- **Depends on:** 08.2.
- **Evidence:** Parity test passes on all sessions of one fold.

### Task 08.9 — Feature-Computation Latency
- **What:** Measure per-frame streaming feature computation time on the development CPU (p50/p95) for the full schema and for the largest ablation subset.
- **Why:** README §5.3 feature-extraction latency.
- **Depends on:** 08.8.
- **Evidence:** Experiment-log JSON; table.

### Task 08.10 — Feature Descriptive Statistics
- **What:** Per fold (train only): distributions of speed, `v·n_z`, `d_z`, `dt`; correlation of rule-based `time-to-surface` with GT `tti` in the pre-impact window (informational; not a result about any model).
- **Why:** Sanity checks and thesis material on the data; informs GBDT/temporal loss scaling.
- **Depends on:** 08.4.
- **Evidence:** Report with MEASURED distributions.

## Data Requirements

- `ds-v1.0` with splits; no new data.
- Sample counts per class per fold reported (MEASURED), not targeted.

## Algorithms / Technical Approach

- Backward finite differences with actual `dt`; filter outputs preferred for `v`, `a`.
- Signed distance to impact surface: point-to-segment/arc distance with sign from the inward normal.
- Angle encoding via `(sin, cos)`.
- Normalisation: z-score / robust scaling per group (candidate), train-only.
- Window construction: fixed `N` frames (not fixed seconds) with `dt` included as a feature so variable frame intervals are visible to the model; alternative time-resampled windows = Phase 12 option.

## Interfaces / Contracts

- Produces `KinematicFeatures` (Phase 01) with `feature_schema_id = "fs-v1"`.
- Sample format: `{X:[N,F], M:[N,F], T:[K,2], T_mask:[K], aux:{strike_within_H, tti, tti_mask, zone_id, impact_pos, intensity}, meta:{t_i, hand_id, session_id, participant, fold}}` serialised per fold (candidate: NPZ/Parquet).
- Normalisation stats file format.

## Tests

- **Unit:** each feature's derivation on synthetic tracks with known analytic values; masking; angle encoding; signed distance; window alignment.
- **Causality:** `TEST-CAUSAL-1` (future perturbation) and `TEST-CAUSAL-2` (history truncation to `N`) on the feature pipeline.
- **Leakage:** train-only stats; reference-track exclusion; participant disjointness re-checked at sample level.
- **Parity:** batch vs. streaming.

## Measurements

| Quantity | Method | Label |
|----------|--------|-------|
| Feature dimension `F`; per-group dimensions | schema | recorded |
| Sample counts per fold/class; dropped-window rate | Task 08.5/08.3 | MEASURED |
| Feature computation latency (p50/p95) | Task 08.9 | MEASURED |
| Descriptive distributions | Task 08.10 | MEASURED |

## Experimental Design

- No model experiments here. The sweep grids for `N`, `K`, `H`, stride are declared (candidate ranges chosen relative to the measured frame rate, e.g. `N` spanning roughly a quarter second to one second of history; `H` spanning one to several frames ahead — exact values recorded as candidates in the schema document) and consumed by Phases 09–10.

## Acceptance Criteria

1. Feature schema v1 documented with groups, units, derivations, masks.
2. Causal core implemented; `TEST-CAUSAL-1/2` pass; streaming parity passes.
3. Normalisation stats are train-only per fold; tests enforce it.
4. Sample builder produces aligned windows/targets; counts reported.
5. Reference-track exclusion test in place.
6. Feature latency measured.

## Definition of Done

- Implementation, tests, schema doc, stats files, latency measurement, descriptive report, gate record PASS; integrity checklist applied.

## Risks

- Feature explosion with many zones (`d_z`, `v·n_z` per zone) → dimension reported; Phase 19 ablation can test zone-relative features; consider nearest-zone-only variant (candidate).
- Filter-derived acceleration may be noisy → include both filter and finite-difference variants as candidates; Phase 19 decides.
- Variable `dt` under frame drops → `dt` feature + masks; window-drop rate reported.

## Failure Modes

- Accidental centred difference → causality test fails.
- Stats computed on all participants → leakage test fails.
- Streaming state not reset on `INVALID` → parity test fails after gaps.

## Fallback Strategy

- If the full schema is too slow online, define `fs-v1-lite` (subset) with parity and latency measured; the model phases record which schema was used.

## Artifacts Produced

- `docs/features/feature-schema-v1.md`, `schemas/feature-schema-v1.json`
- `src/spacedrums/features/`, `tests/features/`
- `data/features/ds-v1.0/fs-v1/fold-*/{samples.*, norm_stats.json}`
- `docs/reports/phase-08-feature-stats.md`
- `experiments/phase-08/*.json`
- `docs/gates/phase-08-gate.md`

## Exit Gate

Reviewer verifies schema, causality/leakage tests, parity, latency. PASS → Phase 09.

## What Must NOT Be Done Yet

- No model training, no metric of any model.
- No feature selection using test participants.
- No use of reference tracks as input.
- No fixed choice of `N`, `K`, `H` (sweeps happen in Phases 09–10).

## Open Questions

- Include rule-based time-to-surface as a feature for learned models, or reserve it for Baseline B only? (Both variants kept; Phase 19 ablation.)
- Nearest-zone-only vs. all-zone relative features (Phase 19).
- Time-resampled windows (Phase 12 option).

## Decisions That Must Be Experimentally Validated

- Normalisation scheme per group (Phase 09 quick comparison).
- Whether jerk helps (Phase 19).
- Hand-landmark subset (Phase 19 "without hand information").
- `g_win` window-drop threshold (Phase 09).
