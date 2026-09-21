# spacedrums.tracking

**Status:** IMPLEMENTED (Phase 03, Tasks 03.12–03.13; ADR-0016). Layer L3; imports only L0.

| Module | Content |
|---|---|
| `filter.py` | `alpha_beta`, `kalman_cv` (candidate default), `kalman_ca`; confidence-scaled measurement noise, variable `dt`, predict-only bridge step; `ScalarAngleFilter`; `effective_window_frames` = declared `N_eff` for `TEST-CAUSAL-2` (two-filter simulation at the lowest confidence gain) |
| `state_machine.py` | README §8: VALID / DEGRADED (observation or ≤ `g_max` prediction-only bridge) / INVALID (`GAP_EXCEEDED` / `LOW_CONFIDENCE`) / STALE (`age_max`); re-acquisition on `c_valid`; external resets reported on the next frame |
| `tracker.py` | `CausalTracker` (the `Tracker` interface): one instance per hand, one `TrackState` per frame, history window `N`, `TrackReset` events, aspect-corrected axis angle |

Causality: `TEST-CAUSAL-1` bit-identical (synthetic + recorded exp-5); `TEST-CAUSAL-2` at the declared `N_eff` (35 frames for `kalman_cv` defaults) within 1e-6 position-equivalent units. Tests: `tests/tracking/` (`TEST-TRACK-1/2/3`, `TEST-CONFORM-2`, `TEST-CAUSAL-1/2`). Evidence: `docs/reports/phase-03-tip-benchmark.md` §3.5–3.6.
