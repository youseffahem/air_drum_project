# Phase 14 — Calibration

## Status

Planned

## Purpose

Implement the Calibration Wizard (Q57) that determines, for a given camera placement and user, the playing area (ROI confirmation and "stand here" fit), the virtual drum-zone positions and sizes (scaled fixed layouts with optional adjustment), per-user parameters that the tracker benefits from (apparent stick-length prior `L_prior`, hand-size reference), and the coordinate mappings — persisted as a versioned calibration file that the pipeline loads. Include a validation step (test strikes) and re-calibration triggers. The wizard must not change the core detection/prediction architecture (Q20) and must keep zone geometry deterministic.

## Why This Phase Exists

Until now, zone layout, ROI, and `L_prior` are candidate constants tuned on the development setup. A different room, camera height, user height, or stick length changes what the camera sees. Because the strike is determined by geometry on predicted trajectories — not by a classifier trained on fixed zone positions — zones can be moved by calibration without retraining, which is one of the arguments for trajectory-first; this phase realises that benefit for users.

## Relationship to Research Contribution

- Enables the live evaluation (Phase 18) to be run with participants of different sizes at documented calibrations rather than a single hard-coded layout.
- Demonstrates the geometry/learning separation in practice (zones move; model unchanged).
- Records calibration parameters as metadata for every live session (reproducibility).

## Inputs

- Phase 13 application; Phase 04 zone layouts; Phase 03 `L_prior` mechanism; Phase 02 ROI helper and camera profile.

## Expected Outputs

- Calibration Wizard (guided UI steps) and `calibration` module.
- Calibration file schema (`calib-v1`), loader, validation, versioning.
- Validation-strike step with pass/fail feedback.
- Re-calibration triggers (camera profile change, ROI change, manual).
- Documentation: user procedure and developer notes.

## Dependencies

- Phase 13 Exit Gate (so the wizard runs on the integrated pipeline; may run in parallel with Phase 15).

## System Components

- `src/spacedrums/calib/{wizard.py, steps.py, schema.py, store.py, fit.py}`
- `src/spacedrums/ui/wizard_views.py`
- `configs/calibration/<user_or_setup>.calib.yaml`

## Architecture

```
Step 1 Camera check: profile confirmation, measured FPS spot-check, exposure hint
Step 2 Playing area: show ROI + guide; user stands; wizard checks both hands detected across the ROI band for T seconds (tunable); suggests moving closer/farther based on hand bbox size vs. the Phase 03 recommended range
Step 3 Stick prior: user holds sticks still in view; wizard estimates L_prior per hand from axis support length over T seconds (median), stores per-hand values; sanity range check
Step 4 Zone placement: select layout (MVP-4 / V1-7); scale/translate the fixed layout to the user's reach envelope estimated from a short guided sweep (tunable margins); optional manual nudge per zone (bounded); impact surfaces/normals recomputed deterministically
Step 5 Validation: user strikes each zone N times (cued); wizard reports per-zone detection under Arm A (reactive — calibration must not depend on the model) and flags zones with low detection or ambiguous geometry
Step 6 Save: calib-v1 file with camera profile id, ROI, L_prior per hand, zone layout (absolute), reach envelope, validation results, timestamp, app version
```

- Calibration uses **Arm A only** for validation so that calibration outcomes do not depend on model behaviour.
- The calibration file is an input to the pipeline config; zone geometry remains deterministic (Phase 04).

## Detailed Tasks

### Task 14.1 — Calibration Schema and Store
- **What:** `calib-v1` fields (above), validation, versioning, hash; pipeline loads it and records its hash in session metadata.
- **Why:** Reproducibility of live sessions.
- **Depends on:** Phase 01 config schema.
- **Evidence:** Schema tests; round-trip save/load test.

### Task 14.2 — Playing-Area Step
- **What:** Detection-coverage check across the ROI band; distance advice from hand bbox size (thresholds from Phase 03 Task 03.11 recommendation, tunable).
- **Why:** Q19 — system-defined standing position.
- **Depends on:** Phase 03 outputs.
- **Evidence:** Integration test with a dev user; step outputs logged.

### Task 14.3 — Stick-Prior Step
- **What:** Per-hand `L_prior` estimation from axis support over time; range check; fallback to layout default with warning.
- **Why:** Phase 03 Open Question (per-user `L_prior`).
- **Depends on:** Phase 03 axis estimation.
- **Evidence:** Repeatability test: two consecutive estimations for the same user agree within a tolerance (MEASURED).

### Task 14.4 — Zone-Placement Step
- **What:** Reach-envelope estimation from a guided sweep (tip positions' convex hull or percentile box); layout scaling/translation into the envelope with margins; bounded manual nudge; deterministic recomputation of impact surfaces/normals; overlap check.
- **Why:** Q16/Q18 — fixed layouts adapted per setup; geometry stays deterministic.
- **Depends on:** Phase 04 layouts.
- **Evidence:** Unit tests (scaling, overlap); screenshots.

### Task 14.5 — Validation-Strike Step
- **What:** Cued strikes per zone under Arm A; per-zone detection counts; flags; option to repeat placement.
- **Why:** Objective check before playing/experiments.
- **Depends on:** 14.4.
- **Evidence:** Validation results stored in the calibration file (MEASURED per calibration).

### Task 14.6 — Re-Calibration Triggers and UX
- **What:** Trigger on camera profile change, ROI change, app version with geometry changes, or user request; wizard resumable; clear instructions.
- **Why:** Q57.
- **Depends on:** 14.1.
- **Evidence:** Tests for triggers; user procedure doc.

### Task 14.7 — Model Compatibility Check
- **What:** Verify that the calibrated zone layout is within the range of layouts the model was trained/evaluated with only in the sense that zone-relative features (Phase 08 ZONE group) are computed from the *calibrated* zones at runtime; document that the model's inputs adapt via features, and record a caution that large layout departures from the recording layout are untested (Phase 18/19 may test a second layout).
- **Why:** Honest limitation; feature/geometry coupling.
- **Depends on:** Phase 08/13.
- **Evidence:** Documentation note; runtime assertion that ZONE features use the loaded calibration.

## Data Requirements

- Developer calibration runs; no participant data required. Phase 18 live participants will each run the wizard (their calibration files become session metadata).

## Algorithms / Technical Approach

- Coverage check: fraction of frames with both hands `VALID` across ROI sub-regions.
- `L_prior`: median axis-support length over a still-hold window.
- Reach envelope: percentile bounding box of tip positions during the sweep.
- Layout fit: similarity transform (scale + translation; no rotation by default) into the envelope with margins; overlap check via shape intersection tests.

## Interfaces / Contracts

- `calib-v1` schema; `SessionMetadata.calibration_hash`.
- Pipeline config gains `calibration_path`.

## Tests

- Unit: schema; layout fit; overlap; trigger logic.
- Integration: full wizard run on a dev user; pipeline loads the produced file and runs.
- Regression: with the recording layout as calibration input, zone geometry equals Phase 04's layout exactly (no drift).

## Measurements

| Quantity | Label |
|----------|-------|
| `L_prior` repeatability (same user, repeated) | MEASURED |
| Wizard duration | MEASURED |
| Validation-strike detection per zone under Arm A (per calibration) | MEASURED |

## Experimental Design

- Repeatability: repeat the wizard several times for the same user/setup; report variance of `L_prior` and zone positions.

## Acceptance Criteria

1. Wizard completes all steps; calibration file saved/loaded; pipeline uses it.
2. Regression test shows zero drift for the recording layout.
3. Validation-strike step reports per-zone detection; re-calibration triggers work.
4. `L_prior` repeatability measured and documented.

## Definition of Done

- Implementation, tests, measurements, user procedure doc, gate record PASS; integrity checklist applied.

## Risks

- Reach-envelope estimation may be biased by the sweep instruction → margins tunable; manual nudge available.
- Users with very different heights may push zones outside the ROI → wizard warns; distance advice.

## Failure Modes

- Calibration saved with a different camera profile than the session → hash mismatch detected at load.
- Overlapping zones → overlap check blocks save.

## Fallback Strategy

- If the wizard cannot complete (tracking issues), fall back to the default layout with a warning; session metadata records "uncalibrated".

## Artifacts Produced

- `src/spacedrums/calib/`, `src/spacedrums/ui/wizard_views.py`
- `schemas/calib-v1.schema.json`, `configs/calibration/*.calib.yaml`
- `docs/user/calibration.md`, `docs/reports/phase-14-repeatability.md`
- `docs/gates/phase-14-gate.md`

## Exit Gate

Reviewer verifies wizard, regression test, repeatability. PASS → Phase 16 (with Phase 15).

## What Must NOT Be Done Yet

- No model retraining for calibration.
- No depth estimation or 3-D calibration.
- No automatic zone learning from user behaviour (future work).

## Open Questions

- Should rotation be allowed in the layout fit (tilted camera)? Default no; revisit if Phase 18 setups need it.
- Per-user vs. per-setup calibration files (both supported; naming decision).

## Decisions That Must Be Experimentally Validated

- Coverage/distance thresholds (from Phase 03 data).
- Envelope percentiles and margins.
- Validation-strike count per zone.
