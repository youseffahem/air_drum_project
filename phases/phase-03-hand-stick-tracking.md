# Phase 03 — Hand / Stick Tracking

## Status

Planned

## Purpose

Implement per-hand hand-landmark estimation with left/right identity, **markerless** visual stick detection/segmentation, stick-axis estimation, stick-tip estimation behind a pluggable `TipEstimator` interface (three methods: markerless geometric, visual axis refinement, colored-marker fallback), and a **causal** per-hand temporal tracker with the README §8 state machine. Benchmark the tip-estimation methods against a reference and select the primary markerless method on evidence.

## Why This Phase Exists

The temporal model (Phase 10) learns from tip trajectories. The quality of those trajectories — accuracy, noise, latency, and behaviour under occlusion — bounds everything downstream. The discovery file requires markerless operation with ordinary sticks (Q9, Q30, Q31), modular comparison of tip-estimation approaches (Q31), independent hands (Q33), and safe handling of tracking loss without future information (Q34–35). This phase delivers all four.

## Relationship to Research Contribution

- Tip trajectories are the **input** to Causal Temporal Strike Anticipation; tracker noise and lag directly affect achievable lead time and false-positive behaviour.
- The tracker is the first component that must pass `TEST-CAUSAL-1/2` (Phase 01, Task 01.6).
- The `method_id` field lets Phase 19 ablate stick-axis information and Phase 18 report results per tip-estimation method (markerless primary; marker as benchmark condition).

## Inputs

- `FrameSample` stream (Phase 02), camera profile, ROI.
- Phase 01 contracts: `HandObservation`, `StickObservation`, `TrackState`, `TipEstimator`, `Tracker` interfaces; state machine (README §8).
- Developer-only test captures (not dataset).

## Expected Outputs

- `hands` module (landmark estimator wrapper, L/R identity, per-hand presence).
- `stick` module: stick detection/segmentation within a hand-anchored search region; axis estimation; three `TipEstimator` implementations (`GEOM`, `AXIS_REFINED`, `MARKER`).
- `tracking` module: per-hand causal filter + state machine + reset logic.
- Tip-estimation benchmark report (per-method error vs. reference, MEASURED).
- Tracking-quality vs. distance/lighting results (completing Phase 02 Task 02.7).
- Processing-time-per-frame measurements for each stage on the development CPU.
- Selection of the primary markerless method with written justification.

## Dependencies

- Phase 02 Exit Gate (capture, ROI, camera profile).
- Phase 01 contracts and test specifications.

## System Components

- `src/spacedrums/hands/` — `HandLandmarker` wrapper (MediaPipe Hands candidate), handedness resolution, temporal identity assignment.
- `src/spacedrums/stick/` — `search_region.py`, `segment.py`, `axis.py`, `tip_geom.py`, `tip_axis_refined.py`, `tip_marker.py`, `estimator.py` (factory by `method_id`).
- `src/spacedrums/tracking/` — `filter.py` (candidates: alpha-beta, Kalman CV, Kalman CA), `state_machine.py`, `tracker.py`.
- `scripts/benchmark_tip_methods.py`, `scripts/measure_stage_latency.py`, `tools/annotate_tip.py` (minimal frame annotation tool for reference points).

## Architecture

```
FrameSample (ROI)
   │
   ├─► hands: landmarks (21 pts, handedness) ──► identity assignment ──► HandObservation[LEFT], [RIGHT]
   │
   └─► stick (per hand, if hand present):
          search region = hand bbox expanded along the estimated grip direction (tunable factors)
          ├─ segment.py: candidate stick pixels (classical: edge/gradient + elongated-component filtering; optional learned mask)
          ├─ axis.py:   line fit (PCA / RANSAC / Hough candidates) constrained to pass near the grip landmarks
          └─ TipEstimator[method_id]:
               GEOM:         tip = grip_point + L_prior · axis_dir   (L_prior: apparent stick length prior, tunable / per-user calibrated later)
               AXIS_REFINED: tip = far endpoint of the segmented axis support, validated against GEOM
               MARKER:       tip = centroid of colored blob near the expected tip region (fallback / benchmark only)
          ──► StickObservation[hand]
   ▼
tracking[hand] (causal):
   predict(dt) → update(tip, confidence) → state machine (VALID/DEGRADED/INVALID/STALE) → TrackState[hand]
```

- **Causality rule:** the tracker's `update` receives only the current observation and its own state; there is no lookahead argument or buffer of future frames. Smoothing that uses future frames is permitted **only** in offline label generation (Phase 07) and is implemented there, not here.
- **Per-hand independence:** two `Tracker` instances; no shared state except the identity-assignment step in `hands`.

## Detailed Tasks

### Checkpoint 03.A — Hand landmarks

#### Task 03.1 — Hand Landmark Estimator Wrapper
- **What:** Wrap the candidate landmark estimator (MediaPipe Hands) to output `HandObservation` in ROI-normalized y-down coordinates; expose model complexity/confidence parameters via config; record `detector_id` and version.
- **Why:** Q10, Q31 — hand landmarks are the primary reference for stick geometry.
- **Depends on:** Phase 02 `FrameSample`.
- **Evidence:** Integration test on a dev capture: landmarks present for both hands in ≥ N frames (N reported, not targeted); schema validation; per-frame processing time logged.

#### Task 03.2 — Left/Right Identity Assignment
- **What:** Combine the estimator's handedness score with temporal continuity (nearest previous wrist position, tunable gating distance) to assign `LEFT`/`RIGHT` stably; detect and log swaps; when ambiguous, mark both hands `DEGRADED` rather than guessing.
- **Why:** Q33 — independent per-hand state requires stable identity; a swap corrupts both trajectories.
- **Depends on:** 03.1.
- **Evidence:** Swap-rate measurement on dev captures with deliberate hand crossings; unit tests on synthetic sequences.

#### Task 03.3 — Grip Reference Points
- **What:** Define the grip point (candidate: a weighted combination of index MCP, thumb tip/IP, and middle MCP landmarks — weights tunable) and the grip direction prior (candidate: from wrist through the grip point, or from the index MCP to index PIP) used to anchor the stick search region and the `GEOM` tip.
- **Why:** Q32 — natural grip with variation; the anchor must tolerate grip variation.
- **Depends on:** 03.1.
- **Evidence:** Visual overlay check on dev captures across several grips; documented definition.

### Checkpoint 03.B — Markerless stick detection / segmentation

#### Task 03.4 — Hand-Anchored Search Region
- **What:** Compute a rotated rectangle extending from the grip point along the grip direction prior by a length factor (tunable) and width factor (tunable); clip to ROI; expose as a debug polygon.
- **Why:** Restricts stick search to a plausible region, reducing false axes from background edges and cutting compute.
- **Depends on:** 03.3.
- **Evidence:** Unit tests (clipping, rotation); processing-time measurement.

#### Task 03.5 — Stick Pixel Candidate Extraction
- **What:** Classical pipeline first: grayscale/edge or gradient response within the search region, morphological filtering, elongated connected-component selection with aspect-ratio and orientation consistency with the grip direction prior (tunable thresholds). Optional second candidate: a lightweight learned segmentation model — only if the classical pipeline fails the benchmark (Pending Benchmark; training such a model would require annotated masks and is a scope addition recorded as an Open Question).
- **Why:** Q9/Q30 — ordinary stick colors, markerless.
- **Depends on:** 03.4.
- **Evidence:** Qualitative overlays across lighting conditions from the Phase 02 checklist; quantitative axis-fit residuals; failure catalogue (background edges, sleeve, skin).

#### Task 03.6 — Stick Axis Estimation
- **What:** Fit a line to candidate pixels (candidates: PCA on component pixels; RANSAC line fit; probabilistic Hough) constrained to pass within a tolerance of the grip point; output `axis_origin`, `axis_dir` (oriented away from the hand), `axis_confidence` (from inlier ratio / residual), and the axis support length.
- **Why:** The axis is needed for `GEOM` and `AXIS_REFINED` tips and as a feature (angle, angular velocity) for Phase 08.
- **Depends on:** 03.5.
- **Evidence:** Unit tests on synthetic lines with noise; residual and confidence distributions on dev captures.

### Checkpoint 03.C — Tip estimation (pluggable)

#### Task 03.7 — `GEOM` Markerless Geometric Tip
- **What:** `tip = grip_point + L_prior · axis_dir`. `L_prior` = apparent stick length in ROI-normalized units; initial value from the Phase 02 distance benchmark (pixel stick length at the chosen distance); optionally refined online from the axis support length when `axis_confidence` is high (causal running estimate, tunable). Confidence from landmark visibility and axis confidence.
- **Why:** Simplest markerless method; works even when the far stick end is blurred or out of the search region.
- **Depends on:** 03.3, 03.6.
- **Evidence:** Benchmark error vs. reference (Task 03.10).

#### Task 03.8 — `AXIS_REFINED` Visual Axis Refinement Tip
- **What:** Tip = far endpoint of the axis support (last inlier along `axis_dir`), gated by consistency with the `GEOM` estimate (reject if farther than a tunable tolerance; fall back to `GEOM` with reduced confidence).
- **Why:** Potentially more accurate when the full stick is visible and sharp; the gating protects against truncation by blur/occlusion.
- **Depends on:** 03.7.
- **Evidence:** Benchmark error vs. reference; fallback rate.

#### Task 03.9 — `MARKER` Colored-Marker Fallback / Benchmark Tip
- **What:** HSV (or similar) color segmentation for a colored tape band near the tip; tip = blob centroid (or far edge along the axis); requires a calibration of the color range. Clearly labelled as **fallback / benchmark condition only**, not the primary interaction mode.
- **Why:** Q9 — fallback if markerless proves unreliable, and a controlled condition for benchmarking the markerless methods.
- **Depends on:** 03.6 (optional axis consistency check).
- **Evidence:** Benchmark error vs. reference; documented as fallback in config (`method_id: MARKER` must emit a warning in the UI/log that the marker condition is active).

#### Task 03.10 — Tip-Estimation Benchmark
- **What:** Build a reference: (a) manual annotation of the visible tip on a sampled subset of dev-capture frames using `tools/annotate_tip.py` (sampling stratified by speed and lighting; count reported); and/or (b) the `MARKER` estimate on marker-equipped recordings as a secondary reference (with its own annotated error). Run all three methods on the same frames; report per-method error (median, p90, in pixels and normalized units), failure rate (no estimate / low confidence), and per-frame compute time. Stratify by lighting, speed (from finite differences of the reference), and distance.
- **Why:** Q31 — modular comparison; primary method must be chosen on evidence.
- **Depends on:** 03.7–03.9.
- **Evidence:** Benchmark report with MEASURED tables; annotation count and inter-annotator agreement on a re-annotated subset.

#### Task 03.11 — Tracking Quality vs. Distance and Lighting
- **What:** Execute the tracking-quality columns of the Phase 02 distance protocol: at each candidate distance × lighting condition, record landmark presence rate, axis confidence distribution, tip error (where annotated), and swap rate. Recommend the ROI/distance for Phases 05–06 on evidence.
- **Why:** Q25, Q27.
- **Depends on:** 03.10.
- **Evidence:** Completed distance table (MEASURED); recommendation recorded as an ADR.

### Checkpoint 03.D — Causal temporal tracking

#### Task 03.12 — Per-Hand Causal Filter
- **What:** Implement pluggable filters: alpha-beta, Kalman constant-velocity, Kalman constant-acceleration (state: position, velocity, [acceleration]; measurement: tip position with confidence-scaled noise). Variable `dt` from `t_capture`. Output filtered position, velocity, acceleration; axis angle and angular velocity tracked by a separate scalar filter. All parameters tunable.
- **Why:** Velocity/acceleration features (Phase 08) need smoothing; raw finite differences at 30 FPS are noisy. Must remain causal.
- **Depends on:** 03.7–03.9 outputs.
- **Evidence:** Unit tests on synthetic trajectories (constant velocity, parabolic) comparing lag and RMSE per filter; `TEST-CAUSAL-1/2` pass.

#### Task 03.13 — Tracking State Machine and Reset Logic
- **What:** Implement README §8 (`VALID/DEGRADED/INVALID/STALE`) with thresholds `c_valid`, `c_min`, `g_max`, `age_max` (tunable). On `INVALID`/`STALE`: reset filter state and history; emit a reset event with reason. `DEGRADED` bridging: at most `g_max` frames of prediction-only (causal) with confidence decaying; no observation invented.
- **Why:** Q34–35 — safe tracking loss; no fabricated strikes.
- **Depends on:** 03.12.
- **Evidence:** Unit tests for every transition; integration test with induced occlusion (hand covered for a controlled interval) showing the state trace; log of reset events.

#### Task 03.14 — Stage Latency Measurement
- **What:** Measure per-frame wall-clock time for `hands`, `stick` (per method), `tracking`, on the development CPU, at the chosen mode; report p50/p95 and the sum vs. the frame period.
- **Why:** README §5.3 tracking latency; feeds Phase 16 budget.
- **Depends on:** All above.
- **Evidence:** Experiment-log JSON; table in the phase report.

#### Task 03.15 — Debug Overlay (minimal)
- **What:** Draw landmarks, search region, axis, tip (color by method), state, velocity vector. Minimal; the full dashboard is Phase 15.
- **Why:** Needed to develop and to produce benchmark screenshots.
- **Depends on:** All above.
- **Evidence:** Screenshots in the benchmark report.

## Data Requirements

- Developer-only test captures (the developer and possibly one or two volunteers who are **not** counted as dataset participants unless they later consent under Phase 06 protocol) covering: several grips, lighting conditions from the checklist, several distances, deliberate occlusions, hand crossings, and marker-equipped sticks for the `MARKER` condition.
- Annotated reference frames for the tip benchmark (count reported; stored under `data/dev-annotations/`).
- None of this is the research dataset.

## Algorithms / Technical Approach

- Hand landmarks: 21-keypoint 2-D model with handedness (MediaPipe Hands candidate).
- Identity assignment: Hungarian/greedy matching on wrist position + handedness prior with gating.
- Stick candidate extraction: gradient/edge response → morphology → connected components → elongation/orientation filter.
- Axis: PCA / RANSAC / Hough (candidates; select by benchmark).
- Tip: `GEOM` (length prior along axis), `AXIS_REFINED` (support endpoint with gating), `MARKER` (color blob).
- Tracking: alpha-beta / Kalman CV / Kalman CA with confidence-scaled measurement noise; variable `dt`.
- All causal; all parameters tunable and recorded in config.

## Interfaces / Contracts

- Implements `TipEstimator` and `Tracker` (Phase 01, Task 01.5).
- Produces `HandObservation`, `StickObservation`, `TrackState`.
- Emits `TrackReset { hand_id, t, reason }` events for logging.

## Tests

- **Unit:** coordinate conversion at the `hands` boundary; identity assignment on synthetic swaps; search-region geometry; axis fit on synthetic lines; each tip method on synthetic images; each filter on synthetic trajectories; every state-machine transition.
- **Causality:** `TEST-CAUSAL-1` and `TEST-CAUSAL-2` on the tracker with recorded dev captures.
- **Integration:** full `FrameSample → TrackState` on dev captures without exceptions; schema validation; induced-occlusion trace shows `INVALID` and reset, never a fabricated `VALID`.
- **Conformance:** interface conformance suite from Phase 01.

## Measurements

| Quantity | Method | Label |
|----------|--------|-------|
| Tip error per method (median, p90; px and normalized) | Task 03.10 | MEASURED |
| Tip failure / low-confidence rate per method | Task 03.10 | MEASURED |
| Axis-fit residual and confidence distributions | Task 03.6 | MEASURED |
| L/R swap rate | Task 03.2 | MEASURED |
| Landmark presence rate by distance × lighting | Task 03.11 | MEASURED |
| Filter lag and RMSE on synthetic trajectories | Task 03.12 | MEASURED |
| State-machine behaviour under induced occlusion | Task 03.13 | MEASURED (trace) |
| Per-stage processing time (p50/p95) | Task 03.14 | MEASURED |

## Experimental Design

- **Tip benchmark:** within-frame comparison (all methods on the same annotated frames); stratified by lighting (checklist), speed tercile, distance; report per-stratum tables; annotation subset size and agreement reported.
- **Distance × lighting:** full factorial over the candidate distances and lighting conditions with a fixed short movement script (same script reused in Phase 06 as a warm-up segment).
- **Filter selection:** synthetic + dev captures; criteria = lag (frames), RMSE, behaviour on gaps; selection recorded as ADR with the trade-off table.

## Acceptance Criteria

1. Both hands tracked with stable identity on dev captures; swap rate reported.
2. All three tip methods implemented behind `TipEstimator`; benchmark executed; per-method error and failure rates reported with strata.
3. Primary markerless method selected and justified in an ADR (markerless only; `MARKER` remains fallback/benchmark).
4. Tracker passes `TEST-CAUSAL-1/2`; state machine passes all transition tests; induced-occlusion test shows no fabricated observations.
5. Per-stage latency measured and documented.
6. Distance/lighting table complete; ROI/distance recommendation recorded.

## Definition of Done

- Implementation, tests, measurements, benchmark report, ADRs, gate record PASS; integrity checklist applied (no "tracking accuracy" claims beyond the measured tables).

## Risks

- Markerless stick segmentation may be unreliable against cluttered backgrounds or with dark sticks in dim light → documented failure catalogue; `MARKER` fallback remains available and labelled.
- Motion blur at strike speeds may truncate the axis support → `AXIS_REFINED` gating; `GEOM` as robust default.
- Landmark estimator latency may consume most of the frame budget on the laptop CPU → measured here; Phase 16 addresses.
- Manual annotation is time-consuming → limit to a stratified subset; report its size.

## Failure Modes

- Hand identity swap during crossing → both hands `DEGRADED`, no commits, logged.
- Axis fit locks onto a background edge → axis-confidence gate and grip-proximity constraint; failure logged.
- Tracker diverges after a gap → `INVALID` + reset rather than extrapolating indefinitely (`g_max` bound).

## Fallback Strategy

- If no markerless method meets a usable error/failure level (threshold To Be Experimentally Determined against Phase 05 playability), proceed with `MARKER` as a **clearly labelled** fallback for Phases 05–06 while continuing markerless work; every result then states the tip method used.
- If the learned segmentation option is needed, open an ADR and a scope decision (annotation cost).

## Artifacts Produced

- `src/spacedrums/hands/`, `src/spacedrums/stick/`, `src/spacedrums/tracking/`
- `tools/annotate_tip.py`, `scripts/benchmark_tip_methods.py`, `scripts/measure_stage_latency.py`
- `docs/reports/phase-03-tip-benchmark.md`, `docs/reports/phase-03-distance-lighting.md`
- `docs/decisions/ADR-<n>-primary-tip-method.md`, `ADR-<n>-filter-choice.md`, `ADR-<n>-roi-distance.md`
- `experiments/phase-03/*.json`
- `docs/gates/phase-03-gate.md`

## Exit Gate

Reviewer verifies benchmark report, causality test results, and the primary-method ADR. PASS → Phase 05 may start (Phase 04 may already be complete in parallel).

## What Must NOT Be Done Yet

- No strike/impact logic, no zones, no audio.
- No anticipation or extrapolation beyond the filter's internal one-step prediction.
- No non-causal smoothing in the tracker.
- No participant dataset recordings.
- No full-body or foot tracking.

## Open Questions

- Is a learned stick-segmentation model needed, and is the annotation cost acceptable? (Pending Benchmark → Open Question)
- Should `L_prior` be per-user calibrated in Phase 14? (likely; depends on benchmark)
- Are landmark visibility scores available from the chosen estimator, or must confidence be derived otherwise?

## Decisions That Must Be Experimentally Validated

- Primary markerless tip method (Task 03.10).
- Filter type and parameters (Task 03.12).
- State-machine thresholds `c_valid`, `c_min`, `g_max`, `age_max` (Task 03.13, revisited in Phases 05/17).
- ROI/distance for data collection (Task 03.11).
- Search-region factors and segmentation thresholds (Tasks 03.4–03.5).
