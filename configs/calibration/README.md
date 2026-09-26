# configs/calibration/

Phase 14 (ADR-0037). Calibration files (`*.calib.yaml`, schema `calib-v1`) and the wizard settings.

| File | What |
|---|---|
| `wizard.candidate.yaml` | Every Calibration Wizard tunable. **All values are candidates** (coverage/distance thresholds, envelope percentiles and margins, strike count must be validated experimentally). Each calibration embeds and hashes the settings it used. |
| `synthetic-selftest.calib.yaml` | **SYNTHETIC** example produced by the scripted wizard actor (`python -m spacedrums.app.calibrate --synthetic ...`). It shows the format and exercises `--calibration`; the app prints a SYNTHETIC warning when it is loaded. Never evidence and never for a real session. |

Naming (phase Open Question "per-user vs per-setup": both supported):

- per user: `user-<pseudonym>-<hardware id>.calib.yaml` (`--scope USER --user-tag <pseudonym>`);
- per setup: `setup-<setup tag>.calib.yaml` (`--scope SETUP --setup-tag <tag>`).

Rules:

- Pseudonyms only; never a real name (the schema restricts tags to `[A-Za-z0-9_-]`).
- **Participant calibrations (Phase 18) are stored under `data/calibration/`**, which git ignores, and
  never here. The wizard refuses a participant output path inside `configs/`.
- Calibration files are written by the wizard only; hand edits are rejected at load time.
- A file stops loading when the camera profile, ROI, geometry version or template layout changes.
  Re-run the wizard (`--recalibrate` replaces a still-valid file).
- Developer live calibrations (the phase's measured `L_prior` repeatability and wizard duration) are
  PENDING: they need a person at the camera (`docs/reports/phase-14-repeatability.md`).
