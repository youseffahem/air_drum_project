# spacedrums.calib

**Status:** IMPLEMENTED development machinery (Phase 14, ADR-0037). Every threshold is a candidate;
developer live calibrations, `L_prior` repeatability and a measured wizard duration are PENDING
(person-dependent). User procedure: [`docs/user/calibration.md`](../../../docs/user/calibration.md).

Calibration Wizard and calibration file I/O, layer L7. It imports geometry, hands, stick, capture and
config. It never imports `ui` (an independent sibling) or the app. The live runner is
`spacedrums.app.calibrate` and the views are `spacedrums.ui.wizard_views`.

| Module | Role |
|---|---|
| `fit.py` | Deterministic layout fit: exact zone extents, percentile reach envelope, uniform scale + translation (identity = exact copy), bounded nudges, per-zone sounds, circumscribed-outline overlap test, ROI check, `zones_hash`. |
| `steps.py` | `WizardFrame` + one accumulator per step: `CameraCheck`, `PlayingArea`, `StickPrior`, `ReachSweep`, `ValidationStrikes` (with the deterministic cue `ValidationSchedule`). Pure: no clock, camera or file. |
| `wizard.py` | `CalibrationWizard` state machine (6 steps, INSTRUCT/COUNTDOWN/COLLECT/REVIEW), `WizardSettings` (candidates; `configs/calibration/wizard.candidate.yaml`), `Template`, `setup_binding`, plain-data `view()`, `snapshot`/`restore` (resume), `autopilot` (unattended runs). |
| `schema.py` | calib-v1 constants, provenance kinds, step statuses, `semantic_errors` (exact layout recomputation, hashes, provenance agreement), `validate_document`. |
| `store.py` | `save_calibration` / `load_calibration` (YAML, LF, lossless round trip), `calibration_hash`, `recalibration_triggers`, `apply_calibration`, `load_calibrated_config` (entry point of every session-producing run). |
| `synthetic.py` | SYNTHETIC closed-loop actor for self-tests (never evidence). |

Developer notes:

- **Arm A only.** The wizard's pipeline (`app.calibrate.build_pipeline`) runs the reactive arm alone,
  with no rule arm and no model, so a calibration never depends on model behaviour.
- **No drift.** FIXED mode (or any identity transform) copies the template byte for byte. The
  regression tests compare canonical JSON with the Phase 04 fragment and the model fingerprint.
- **Determinism.** Same frames and actions give the same document; the loader recomputes the layout
  and refuses hand edits.
- **Binding.** Camera profile (hashed), ROI and `GEOMETRY_VERSION`, plus template-file drift. Any
  change is a re-calibration trigger, never a silent override.
- **Model compatibility.** A calibration carries its template. `app.arms.build_model_arm` verifies
  the package against the template and feeds features computed from the calibrated zones
  (`LayoutAdaptedStats`, `check_zone_features`). Model behaviour on a moved layout is untested.
- **Tests:** `tests/calib/` (fit, steps, schema/store, triggers, apply, regression, wizard flow, app
  integration, model compatibility), `tests/stick/test_stick_l_prior_by_hand.py`,
  `tests/ui/test_ui_wizard_views.py`, `tests/contracts/test_calib_contracts.py`.
- **Scripts:** `scripts/verify_phase14.py` (gate runner), `scripts/calibration_repeatability.py`,
  `scripts/render_calibration.py`, `scripts/_p14.py`.
