# Phase 03 — Tip-Estimation Benchmark and Checkpoint B/C/D Evidence (Tasks 03.3–03.10, 03.12–03.15)

| Field | Value |
|---|---|
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-21 |
| Code state | Uncommitted working tree on `4dd0c2e` (owner rule: no assistant commits). Every run below carries `git_dirty: true` and is **development evidence**; a clean-tree repeat is a gate condition, as in Phase 02. |
| Hardware | HW-01 — Intel i7-7820HQ (4C/8T), Windows 11 22621, mains power, `cv2.getNumThreads() = 8` |
| Data | Phase 02 developer captures only (owner, **not** dataset recordings): `swing-L2-exp-5/6/7` (171/171/172 frames, L2, manual exposure −5/−6/−7, DSHOW 640×480, ROI `[40, 20, 560, 440]`), `distance/d080…d220` single frames. **No new recording was made in Phase 03.** |
| Runs | `20260921-1403-p03-tip-benchmark` (captures), `20260921-1405-p03-tip-benchmark` (distance stills), `20260921-1407-p03-stage-latency`; config `sha256:aca65e8026ebb55ac…` (example base + HW-01 fragment, all values candidates) |
| Related | ADR-0014 (§12 grip), ADR-0015 (stick pipeline, provisional primary method), ADR-0016 (filter, state machine); `docs/reports/phase-03-distance-lighting.md` (Task 03.11); Task 03.1/03.2 notes |

## 1. What was built (per task)

| Task | Implementation | Tests |
|---|---|---|
| 03.3 Grip reference points | `hands/grip.py`: grip point = weighted mean of {index MCP 0.4, thumb IP 0.2, thumb tip 0.2, middle MCP 0.2} (tunable); direction prior `KNUCKLE_ROW` (pinky MCP → index MCP; default, ADR-0014 §12), `WRIST_TO_GRIP`, `INDEX_MCP_TO_PIP`; hand span = max(wrist→middle MCP, pinky→index MCP); aspect-corrected image angle. Config `hands.grip`. | `TEST-HANDS-5` (10 cases) |
| 03.4 Search region | `stick/search_region.py`: rotated rectangle from the grip along the prior, length/width/back factors × hand span, Sutherland–Hodgman clip to the ROI, debug polygon + mask | `TEST-STICK-1` (clipping, rotation, degenerate cases) |
| 03.5 Candidate pixels | `stick/segment.py`: blur → Canny → region mask → closing → connected components → elongation ≥ 2.0 and orientation within 0.7 rad of the prior; failure reasons per component | `TEST-STICK-1` (synthetic stick vs blob, wrong orientation) |
| 03.6 Axis | `stick/axis.py`: PCA / RANSAC (through the grip) / HOUGH candidates; span-relative inlier band; PCA refinement; grip-proximity gate; orientation away from the hand; **connected** support; confidence = inlier ratio × grip proximity; deterministic (re-seeded per call) | `TEST-STICK-1` (synthetic lines with noise + outliers, 3 methods) |
| 03.7 `GEOM` | `stick/tip_geom.py`: tip = grip + L·axis_dir, L prior 0.27 ROI-height units, prior-direction fallback without axis, optional causal online L refinement (off) | `TEST-STICK-2`, `TEST-CONFORM-1` |
| 03.8 `AXIS_REFINED` | `stick/tip_axis_refined.py`: far end of the connected support gated vs GEOM (≤ 0.35 L) and minimum support (≥ 0.5 L); GEOM fallback × 0.6 confidence; fallback counted | `TEST-STICK-2`, `TEST-CONFORM-1` |
| 03.9 `MARKER` | `stick/tip_marker.py`: HSV blob in the search region, optional axis consistency; WARNING on instantiation; labelled fallback/benchmark | `TEST-STICK-2`, `TEST-CONFORM-1` |
| 03.10 Benchmark | `scripts/benchmark_tip_methods.py` (all methods on the same frames, per-method rates, agreement, tracker traces, reference error when an annotation file exists, overlays); `tools/annotate_tip.py` (click tool, stratified sampling, disjoint re-annotation subsets, SYNTHETIC self-test file refused by default) | `TEST-SCRIPTS-1` (synthetic + reference path) |
| 03.12 Filters | `tracking/filter.py`: alpha-beta, Kalman CV, Kalman CA (confidence-scaled noise, variable dt, predict-only bridge), scalar angle filter, `N_eff` declaration by simulation | `TEST-TRACK-1` (synthetic CV / parabolic: lag, RMSE) |
| 03.13 State machine + tracker | `tracking/state_machine.py`, `tracking/tracker.py` (`CausalTracker`, `TrackReset` events, history window) | `TEST-TRACK-2` (every transition), `TEST-CONFORM-2`, `TEST-TRACK-3` (occlusion trace), `TEST-CAUSAL-1/2` |
| 03.14 Stage latency | `scripts/measure_stage_latency.py` | `TEST-SCRIPTS-1` |
| 03.15 Overlay | `ui/overlay.py`: landmarks, grip + prior, region, candidates, axis, tip coloured by method (MARKER tagged), filtered tip + velocity, status line | exercised by the benchmark self-test (figure artefacts) |
| Contracts | `StickObservation`, `TrackState`, `HistoryRef` record classes; `TipEstimator`, `Tracker` Protocols | `tests/contracts` round-trips of the Phase 01 examples |

Suite: **370 passed, 1 skipped** (opt-in hardware test), `ruff` clean, `lint-imports` 4 kept / 0 broken, `scripts/validate_contracts.py` PASS.

## 2. Development sweep that fixed the segmentation / axis defaults (exp-5, 273 hand-frames; MEASURED, development)

| closing | min elongation | axis fit | axis found | rate | confidence p50 | support p50 (px) | residual RMS p50 (px) | ms / hand |
|---|---|---|---|---|---|---|---|---|
| 1 | 2.0 | RANSAC | 241 | 0.88 | 0.56 | 115 | 2.9 | 2.8 |
| 1 | 2.0 | PCA | 240 | 0.88 | 0.42 | 115 | 2.7 | 1.9 |
| 1 | 2.0 | HOUGH | 232 | 0.85 | 0.42 | 114 | 2.5 | 2.8 |
| **3** | **2.0** | **RANSAC** | **248** | **0.91** | **0.61** | 115 | 3.8 | 2.9 |
| 3 | 2.0 | PCA | 248 | 0.91 | 0.48 | 115 | 3.3 | 1.9 |
| 3 | 2.0 | HOUGH | 240 | 0.88 | 0.41 | 114 | 3.2 | 2.9 |
| 3 | 3.0 | RANSAC | 230 | 0.84 | 0.61 | 116 | 3.8 | 2.9 |

Selected candidates: closing 3 px, elongation ≥ 2.0, RANSAC. The support (≈ 115 px) matches Phase 02's click-measured 120 px stick at 1.0 m; the inlier band relative to the hand span (0.3 × ≈ 30 px) makes the fitted line the stick centre between the two Canny edges (single-edge fits with a 2.5 px band gave inlier ratios ≈ 0.2).

## 3. Benchmark on the dev captures (run `20260921-1403-p03-tip-benchmark`; MEASURED, development)

"hand-frames" = frames × hands with landmarks present (Tasks 03.1–03.2 output). Low-confidence = `tip_confidence < c_valid (0.6)`.

### 3.1 exp-5 (exposure −5, 171 frames, 273 hand-frames)

| Method | present | present rate | low-conf rate | no-axis frames | fallback (rate) | tip_conf p50 / p90 | axis_conf p50 / p90 | support px p50 / p90 (n) | compute ms p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|
| GEOM (markerless) | 272/273 | 0.996 | 0.14 | 24 | — | 0.75 / 0.86 | 0.59 / 0.76 | 110 / 126 (248) | 3.1 / 4.8 |
| AXIS_REFINED (markerless) | 272/273 | 0.996 | 0.45 | 24 | 118 (0.43) | 0.66 / 0.85 | 0.59 / 0.76 | 110 / 126 (248) | 2.9 / 4.3 |
| MARKER (**fallback / benchmark**; uncalibrated placeholder range, no marker on the sticks) | 28/273 | 0.10 | 1.00 | — | — | 0.16 / 0.35 | 0.56 / 0.74 | 117 / 126 (21) | 4.6 / 6.3 |

AXIS_REFINED vs GEOM tip distance where both present (272): p50 **1.1 px**, p90 13.2 px, p95 18.9 px, max 41.6 px (ROI 560×440; identical on the 155 non-fallback frames by construction of the gate).

### 3.2 exp-6 (exposure −6, 144 hand-frames) and exp-7 (−7, 0 hand-frames)

| Method | present | low-conf rate | no-axis | fallback (rate) | tip_conf p50 | support px p50 (n) |
|---|---|---|---|---|---|---|
| GEOM | 144/144 | 0.88 | 100 | — | 0.39 | 52 (44) |
| AXIS_REFINED | 144/144 | 0.99 | 100 | 142 (0.99) | 0.23 | 52 (44) |
| MARKER | 0/144 | — | — | — | — | — |

exp-7: no landmarks on any frame (Task 03.1 finding); every method emits `present = false`; every tracker stays INVALID; all records schema-valid.

### 3.3 Tip error vs reference — **PENDING**

No annotated reference exists: `tools/annotate_tip.py` requires a person to click the tips, and no marker-equipped recording exists; no new recording was permitted in this phase. The benchmark script computes the per-method error tables (median, p90 in px and ROI-height units; failure rate on the reference frames; speed terciles from finite differences of the reference; per-capture condition) as soon as `data/dev-annotations/<capture>/tips.jsonl` exists, and its reference path is self-tested on a labelled SYNTHETIC file that it refuses by default. **No error number is reported in this phase.** The primary-method choice is therefore provisional (ADR-0015).

### 3.4 Failure catalogue (from the overlays and event counts; qualitative)

| Observed failure | Where | Effect | Mitigation in place |
|---|---|---|---|
| Hand lost during a fast swing (motion blur of the fist) | exp-5 frame ≈ 120 (RIGHT) | landmarks absent → no stick → tracker `GAP_EXCEEDED` reset after 3 bridged frames | designed: no fabricated state; the phase's blur risk stands |
| Under-exposure removes the hands | exp-6 / exp-7 | 100/144 hand-frames without axis at −6; nothing at −7 | exposure per lighting (ADR-0017 §2); not a stick-pipeline fix |
| Uncalibrated `MARKER` range matches the teal wall | exp-5 | 28 false low-confidence blobs | calibration is mandatory; label + warning; trackers never left INVALID (conf < c_min) |
| Same-label estimator collisions in dim light | exp-6 | raw identity unusable | Task 03.2 assigner (28 overrides) |
| Finger edges compete with the stick edges in the region | exp-5 (component list: `not_elongated`, `orientation` rejections) | occasional no-axis frames (24/273 at −5) | elongation + orientation gates; GEOM prior fallback |
| Search region leaves the ROI at the image edge | exp-5 LEFT at the right border | region clipped, fewer candidates | clipping; lower confidence propagates |

### 3.5 Tracker traces (README §8 behaviour on real observations; GEOM, `kalman_cv`, `c_valid 0.6`, `c_min 0.3`, `g_max 3`, `age_max 0.5 s`)

| Capture | Hand | VALID | DEGRADED | INVALID | STALE | resets (frame, reason) |
|---|---|---|---|---|---|---|
| exp-5 | RIGHT | 143 | 25 | 3 | 0 | (120, GAP_EXCEEDED) |
| exp-5 | LEFT | 90 | 56 | 25 | 0 | (42, 55, 75, 81, 113 — all GAP_EXCEEDED) |
| exp-6 | RIGHT | 11 | 66 | 2 | 92 | (69, STALE) |
| exp-6 | LEFT | 7 | 49 | 26 | 89 | (29 STALE, 45 GAP, 62 GAP, 74 STALE) |
| exp-7 | both | 0 | 0 | 172 | 0 | none (nothing to reset) |

Every `TrackState` validates against the schema; exactly one state per hand per frame; no VALID state without a usable observation (structural, `TEST-TRACK-2`). Induced-occlusion trace (SYNTHETIC, frames 8–15 absent, `g_max 3`): `V V V V V V V V D D D I I I I I V V …`, one `GAP_EXCEEDED` reset at frame 11 — no fabricated VALID.

### 3.6 Causality (`TEST-CAUSAL-1/2`, docs/architecture/causality-tests.md)

| Test | Component | Sequence | |I| | kinds | Result |
|---|---|---|---|---|---|
| CAUSAL-1 | Tracker (alpha_beta, kalman_cv, kalman_ca) | SYNTHETIC (80 frames, gaps, low-conf frames, dt jitter) | 9 | GARBAGE, REMOVED, SHIFTED | **PASS** (bit-identical, 0 differing tuples) |
| CAUSAL-1 | Tracker (kalman_cv, config) | recorded exp-5 observations (171 frames, RIGHT, 143 VALID) | 17 | GARBAGE, REMOVED | **PASS** |
| CAUSAL-1 (regression guard) | every TipEstimator | SYNTHETIC frames | — | later frames fed | **PASS** (per-frame function) |
| CAUSAL-2 | Tracker alpha_beta / kalman_cv / kalman_ca | SYNTHETIC 400-frame VALID run | 21 / 72 / 53 | window = declared N_eff 290 / 35 / 134, tolerance 1e-6 | **PASS**, max dev 3.2e-15 / 1.2e-7 / 2.8e-12; negative control (window 2) differs |
| CAUSAL-2 | Tracker kalman_cv | recorded exp-5 | 14 | window 35 | **PASS**, max dev 5.6e-7 |

Declared for the default tracker: `N = 16` (feature window), `N_eff = 35` frames, `N_min = 1`, tolerance 1e-6 position-equivalent units (velocity × dt, acceleration × dt²).

## 4. Stage latency (Task 03.14; run `20260921-1407-p03-stage-latency`; MEASURED, development)

exp-5 replayed from memory (PNG decoding excluded; capture hand-over excluded — Phase 02 measured ≈ 0.2 ms for DSHOW), 166 frames after 5 warm-up frames, HW-01, `cv2` threads 8.

| Stage (both hands) | p50 ms | p95 ms | max ms |
|---|---|---|---|
| hands (estimator + identity + grip) | 23.7 | 39.6 | 56.4 |
| stick GEOM | 5.5 | 6.9 | 8.1 |
| stick AXIS_REFINED (alternative) | 5.2 | 6.9 | 8.8 |
| stick MARKER (fallback/benchmark) | 8.4 | 10.6 | 16.6 |
| tracking | 0.48 | 0.54 | 0.63 |
| **sum of p50 (hands + stick GEOM + tracking)** | **29.7** | — | — |
| sum of p95 | — | **47.0** | — |
| frame period at requested 30 FPS (arithmetic) | 33.3 | | |

Reading: the estimator dominates; the GEOM pipeline's p50 sum is 0.89 of the frame period and its p95 sum exceeds it. This is the `hands`/`stick`/`tracking` slot of architecture.md §8 for this configuration on HW-01; Phase 16 owns the budget. No latency-reduction claim is made (I-6). The `hands` p50 here (23.7 ms) is lower than in the Task 03.1 runs (33.8 ms); both are development runs on the same machine at different times and are reported as such.

## 5. Overlays (Task 03.15)

`overlay.<capture>.frame*.png` in the benchmark run (every 40th frame) and the Task 03.3 development overlays: landmarks, grip point (cyan) with the KNUCKLE_ROW prior arrow, search region (yellow), candidate pixels (magenta), axis + connected support (green), GEOM tip (red), AXIS_REFINED tip (magenta ring), filtered tip (status-coloured cross) with velocity arrow, per-hand status line with reset reason. Frame 120 of exp-5 shows the blurred-swing loss (RIGHT INVALID, `GAP_EXCEEDED`) and a DEGRADED LEFT with an inflated velocity after a tip jump — both correct per README §8 and both inputs to the Phase 05 threshold tuning.

## 6. Limitations

- One person, one lighting condition (L2), three exposures, one distance with motion; two of the three captures are under-exposed. Nothing here generalises beyond HW-01 at 1.0 m.
- No tip-error numbers: the reference does not exist (person-dependent). Presence, fallback, agreement and compute time are not accuracy.
- All runs `git_dirty: true` (assistant does not commit); clean repeat at the gate.
- Config values everywhere are candidates from a 12-cell development sweep on one capture.
- `MARKER` is implemented and unit-tested only; no marker-equipped capture exists; its colour range is a placeholder.
