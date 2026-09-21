# ADR-0016 — Per-hand causal filter and tracking state machine (filter candidate: Kalman CV)

| Field | Value |
|---|---|
| Status | **Accepted** (Phase 03, Tasks 03.12–03.13). The filter *family* choice (`kalman_cv`) is a candidate selected on synthetic evidence + dev-capture behaviour; thresholds `c_valid`, `c_min`, `g_max`, `age_max` remain candidates revisited in Phases 05/17 (phase document). |
| Date | 2026-09-21 |
| Deciders | Project owner (via the Phase 03 gate), recorded by the Phase 03 submitter |
| Related | ADR-0004 (clock), ADR-0006 (per-hand independence, reset matrix), ADR-0014 §10 (ambiguity cap); `docs/architecture/causality-tests.md` §2–3; README §8; REQ-034, REQ-035, REQ-107; `tests/tracking/` |

## Context

Phase 08 features need smoothed velocity/acceleration; raw finite differences at 30 FPS are noisy. The tracker must remain causal (`TEST-CAUSAL-1/2`), implement README §8 and the reset matrix, and never fabricate an observation during a loss (Q34–Q35). Three filter candidates were implemented behind one interface: alpha-beta, Kalman constant-velocity (CV), Kalman constant-acceleration (CA), all with variable `dt` from `t_capture` and measurement noise scaled by `1 / tip_confidence`.

**Synthetic evidence (`tests/tracking/test_filters.py`, labelled SYNTHETIC; noise σ = 0.004 ROI-norm, dt = 1/30 s, default candidate parameters):**

| trajectory | filter | RMSE (ROI-norm) | lag (frames) |
|---|---|---|---|
| constant velocity | alpha_beta | 0.0040 | 0 |
| constant velocity | kalman_cv | 0.0048 | 0 |
| constant velocity | kalman_ca | 0.0039 | 0 |
| parabolic (a = 6 units/s²) | alpha_beta | 0.0120 | 0 |
| parabolic | kalman_cv | 0.0054 | 0 |
| parabolic | kalman_ca | 0.0041 | 0 |

**Causality (`tests/tracking/test_causal.py`):** `TEST-CAUSAL-1` bit-identical for all three filters (synthetic, |I| = 9, GARBAGE/REMOVED/SHIFTED) and for `kalman_cv` on the recorded exp-5 observations (|I| = 17). `TEST-CAUSAL-2` — none of the filters has a hard window; each declares an effective window `N_eff` at tolerance 1e-6 (position-equivalent units) by simulating a cold start against a long-running instance at the lowest confidence gain: `alpha_beta` 290, `kalman_cv` 35, `kalman_ca` 134 frames (defaults). Measured max deviations at the declared windows: 3.2e-15 / 1.2e-7 / 2.8e-12 (synthetic); `kalman_cv` on exp-5: 5.6e-7 over 14 cuts. Negative control (window 2) differs in every case.

**Dev-capture behaviour (`20260921-1403-p03-tip-benchmark`; clean-tree rerun `20260921-1449-p03-tip-benchmark` on `1917788…` identical — GEOM observations, `kalman_cv`, `c_valid 0.6`, `c_min 0.3`, `g_max 3`, `age_max 0.5 s`):** exp-5 RIGHT 143 VALID / 25 DEGRADED / 3 INVALID over 171 frames, 1 `GAP_EXCEEDED` reset (frame 120, a blurred swing); LEFT 90 / 56 / 25 with 5 resets. exp-6 (under-exposed): mostly DEGRADED → STALE. No VALID state was ever emitted without a usable observation (the state machine's rules make that impossible; `TEST-TRACK-2` covers every transition).

## Decision

1. **Filter candidate for Phases 05–08: `kalman_cv`** (`q = 5.0`, `r_base = 1e-4`, `c_floor = 0.2`; candidates). Grounds: comparable RMSE to CA on the synthetic tests at a third of CA's effective memory (35 vs 134 frames — a shorter `N_eff` is a smaller state to reset on `INVALID` and a tighter causality declaration); no explicit acceleration state that a noisy tip would excite; alpha-beta's fixed gains give the largest parabolic error and a 290-frame effective memory at the low-confidence gain. `kalman_ca` stays available (`tracking.filter.type`) for Phase 08 if acceleration features prove to need it; Phase 19 can ablate.
2. **State machine (README §8) as implemented in `spacedrums.tracking.state_machine`:** observation with `conf ≥ c_valid` → VALID; `c_min ≤ conf < c_valid` → DEGRADED (observation used, noise scaled); otherwise a prediction-only DEGRADED bridge for ≤ `g_max` frames with confidence × `bridge_decay` per frame, then INVALID with reason `LOW_CONFIDENCE` (hand seen but untrustworthy) or `GAP_EXCEEDED` (no hand); `t − last_valid_t > age_max` → STALE (reason `STALE`, once); re-acquisition requires `conf ≥ c_valid` (`acquire_on_degraded = false`). Reset clears the filter, the angle filter and the history window; `last_valid_t` is kept for the STALE decision (reset matrix). Every reset is emitted as a `TrackReset {hand_id, t, reason, frame_id}`.
3. **TEST-CAUSAL-2 declaration rule:** a tracker declares `N` (config `history_n`, the feature window) **and** `N_eff` (filter memory at the declared tolerance, simulated by the filter itself); the test measures the real deviation and fails if the declaration is too small. Tolerance is stated in position-equivalent units (velocity × dt, acceleration × dt²). `history_ref` is window metadata and is excluded from the comparison by definition.
4. **Axis angle** is filtered by a separate scalar alpha-beta filter with wrap-around; the angle is the image-plane angle (aspect-corrected from the normalized `axis_dir`).

## Alternatives considered

| Alternative | Why not |
|---|---|
| `kalman_ca` as default | Similar RMSE on the synthetic tests, 4× the effective memory, an extra state excited by tip jitter; kept selectable. |
| alpha-beta as default | Worst parabolic RMSE; 290-frame effective memory at the low-confidence gain. |
| Re-acquire on a DEGRADED observation | Would start tracks from untrustworthy tips; tunable (`acquire_on_degraded`) for a Phase 05/17 experiment. |
| Immediate INVALID on `conf < c_min` (no bridge) | README §8 defines the ≤ `g_max` bridge; the low-confidence frame counts as a gap frame and is named in the reset reason. |

## Consequences

- `tracking` IMPLEMENTED with `TEST-CONFORM-2`, `TEST-TRACK-1/2/3`, `TEST-CAUSAL-1/2`; `TrackState` producer exists; `history_n = 16` is the declared feature window for Phase 08.
- Thresholds are candidates: on the under-exposed capture the tracker spends most frames DEGRADED/STALE, which is the correct safe behaviour but shows the thresholds interact with the estimator's confidence scale (Task 03.7 formula) — Phase 05 playability tuning revisits both together.
- `example.candidate.yaml` now carries a real filter (`kalman_cv`) instead of the Phase 01 placeholder; `tracker_id` in the example remains `example-tracker` (candidate document).
