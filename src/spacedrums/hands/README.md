# spacedrums.hands

**Status:** Tasks 03.1 (estimator wrapper), 03.2 (LEFT/RIGHT identity) and 03.3 (grip reference points) IMPLEMENTED (Phase 03; ADR-0014).

Layer L2 (perception). Produces two `HandObservation`s per frame (LEFT then RIGHT) in ROI-normalized y-down coordinates (ADR-0005). Imports only L0 and `spacedrums.capture.roi` (px↔normalized helper), architecture.md §2.2.

| Module | Content |
|---|---|
| `coords.py` | The coordinate boundary: estimator-native → full-frame px → ROI-normalized through `capture.roi.px_to_norm`; `DetectorInput` (ROI crop or full frame), `bbox_of` |
| `model_asset.py` | Resolves `hands.model_asset_id` in `assets/models/manifest.json`, re-verifies the SHA-256 at load (environment.md §7) |
| `landmarker.py` | `HandLandmarkerSettings` (config `hands` block, schema 1.2), `LandmarkBackend` Protocol, `MediaPipeHandLandmarkerBackend` (Tasks API, lazy import), `HandLandmarker.detect(FrameView) -> HandsFrameResult` with per-frame `processing_s`, counters (label collisions, unknown labels, timestamp bumps, visibility frames, ambiguous frames) and a `detector_id` that pins library version, model hash prefix and every parameter including the identity settings |
| `grip.py` | Task 03.3: grip point (weighted landmarks), direction prior (`KNUCKLE_ROW` default — the stick lies along the knuckle row in a fist; `WRIST_TO_GRIP`, `INDEX_MCP_TO_PIP` selectable), hand span, aspect-corrected angle |
| `identity.py` | Task 03.2: `IdentityAssigner` — estimator label + continuity to the previous wrist (gated, expiring after `max_gap_s`), exhaustive injective assignment, ambiguity margin → `handedness_score` cap (loader: `c_min ≤ cap < c_valid` ⇒ DEGRADED at most), events `LABEL_OVERRIDE` / `CONTINUITY_OVERRIDE` / `IDENTITY_JUMP` / `AMBIGUOUS`; mode `RAW` = Task 03.1 label-only baseline |

`handedness_score` in the emitted `HandObservation` is the assigner's combined identity confidence (mode TEMPORAL) or the raw estimator score (mode RAW). `swap_handedness = false` was decided by the owner check of 2026-09-21 (HW-01 image not mirrored). `landmark_visibility` is `null` for the pinned estimator (measured).

Evidence: `docs/reports/phase-03-task-03.1-hand-landmarker.md`, `docs/reports/phase-03-task-03.2-identity.md`. Tests: `tests/hands/` (`TEST-HANDS-1…4`). Script: `scripts/hands_landmark_check.py` (`--identity-mode RAW|TEMPORAL`).
