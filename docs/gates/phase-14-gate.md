# Phase 14 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 14 — Calibration |
| Phase document | `phases/phase-14-calibration.md` |
| Submitter | Claude Code agent acting for the project owner |
| Reviewer(s) | Project owner — PENDING |
| Review date | PENDING |
| Code state | start `a8ea862d41bc6846421596b523777d689a31f5f9` clean; final verification same HEAD, **dirty** (Phase 14 changes uncommitted) |
| **Verdict** | **PENDING reviewer. Submitter proposes FAIL for the full phase** (criterion 4 NOT MET, criterion 1 PARTIAL: both need a developer at the camera). Criteria 2 and 3 are MET as tested machinery. |

## Execution environment

| Item | Value |
|---|---|
| Model actually used | **Claude Opus 5.5** (`claude-opus-5-5`) via Claude Code. The phase document's recommended GPT-6 Astra / High was **not** used. |
| Reasoning effort actually used | max (session setting reported to the agent by the harness) |
| Execution start | 2026-09-26T09:46:41+03:00 |
| Git HEAD at start | `a8ea862d41bc6846421596b523777d689a31f5f9`, git_dirty = false |
| Final verification | 2026-09-26T10:58:27+03:00, HEAD `a8ea862d41bc6846421596b523777d689a31f5f9`, git_dirty = true |
| Record | `experiments/phase-14/20260926-execution/{execution-start,execution-final}.json`; the verification run's `execution.json` names the executor |

## Dependency verification (before any Phase 14 edit)

`scripts/verify_phase13.py --require-clean --parity-config experiments/phase-13/20260926-integration/parity.config.yaml --plan experiments/phase-13/20260926-integration/parity.plan.json`
ran on the owner commit `a8ea862…` with a **clean** tree, 2026-09-26 09:46:56 → 10:01:28 +03:00:
**all 10 commands passed** (pytest 1,138 passed, 1 skipped; lint, seven import contracts, contract
validation, environment smoke, diff check, raw parity/causality on three developer sessions, six
injected faults, two replay timing runs). Source hashes did not change and git_dirty was false at both
ends. Evidence: `experiments/phase-13/20260926-0946-p13-gate-verification/`. That run's
`execution.json` says UNVERIFIED, which `scripts/_p13.py` hard-codes. The executor of this rerun was
the model named above (`experiments/phase-14/20260926-execution/execution-start.json`). This closes
Phase 13's executable post-commit check (its action 5) only. The Phase 13 reviewer signature,
participant-fold parity, shipped model and live strike timing remain PENDING; Phase 13 has no PASS.
The owner authorised Phase 14 with Phase 13's gate unsigned, as in earlier phases. This is recorded,
not assumed.

## 1. Artefacts produced

| Artefact (phase document) | Path | Status label | Present? |
|---|---|---|---|
| Calibration Wizard + `calibration` module | `src/spacedrums/calib/{wizard,steps,schema,store,fit,synthetic}.py` | IMPLEMENTED | yes |
| Wizard views | `src/spacedrums/ui/wizard_views.py` | IMPLEMENTED | yes |
| Wizard application (runner, keys, resume, `--check`) | `src/spacedrums/app/calibrate.py` | IMPLEMENTED | yes |
| Calibration schema | `schemas/calib-v1.schema.json` (+ SYNTHETIC example `schemas/examples/calib-v1.valid.example.json`) | IMPLEMENTED | yes |
| Calibration files | `configs/calibration/wizard.candidate.yaml` (settings, candidates), `configs/calibration/synthetic-selftest.calib.yaml` (SYNTHETIC example), `configs/calibration/README.md` | IMPLEMENTED; developer file PENDING | yes (developer: no) |
| Pipeline config `calibration_path`, calibrated zones, per-hand `L_prior` | `configs/schema/config.schema.json` 1.7, `src/spacedrums/config/loader.py`, `src/spacedrums/stick/estimator.py` | IMPLEMENTED | yes |
| `SessionMetadata.calibration_hash` (+ status, id), `session.json` | `schemas/session-metadata.schema.json`, `src/spacedrums/app/main.py`, `scripts/record_session.py` | IMPLEMENTED | yes |
| Model compatibility (Task 14.7) | `src/spacedrums/app/arms.py`, `src/spacedrums/app/pipeline.py` | IMPLEMENTED | yes |
| User procedure | `docs/user/calibration.md` | IMPLEMENTED (not yet tried by a person) | yes |
| Developer notes / decision | `src/spacedrums/calib/README.md`, `docs/decisions/ADR-0037-calibration.md` | IMPLEMENTED | yes |
| Repeatability report | `docs/reports/phase-14-repeatability.md` | MEASURED quantities PENDING; SYNTHETIC/replay diagnostics | yes |
| Scripts | `scripts/{verify_phase14,calibration_repeatability,render_calibration,_p14}.py` | IMPLEMENTED | yes |
| Gate record | this file | submitted | yes |

## 2. Acceptance criteria

| # | Criterion (verbatim) | Evidence | Result |
|---|---|---|---|
| 1 | Wizard completes all steps; calibration file saved/loaded; pipeline uses it. | All six steps complete with the SYNTHETIC closed-loop actor (`tests/calib/test_calib_wizard_flow.py`, verifier `wizard-synthetic`). The file round-trips losslessly (`test_calib_schema_store.py`). The app loads it, runs, and records the hash in `session.json` and SessionMetadata; the recorded session keeps a copy (`test_calib_app.py`, verifier `app-session`, `session-check`, `record-session`, `metadata-check`). The real Phase 03 perception on three recorded developer captures completes every step except validation, which is skipped (`replay-*`). **The phase's integration test with a dev user following the wizard live is PENDING.** | PARTIAL |
| 2 | Regression test shows zero drift for the recording layout. | FIXED fit of the MVP-4 recording layout: calibrated zones equal the Phase 04 fragment exactly (dict and canonical-JSON bytes). The resolved config equals the prototype zones, and the feature fingerprint equals the Phase 04 one and the pinned Phase 10 manifest's `feature_schema_hash` (`test_calib_regression.py`, verifier `regression`). | MET |
| 3 | Validation-strike step reports per-zone detection; re-calibration triggers work. | Per-zone cued/detected/wrong-zone/duplicate counts and flags under Arm A only; the wizard pipeline has arms `(A,)` and no model even with a model config (`test_calib_steps.py`, `test_calib_wizard_flow.py`, `test_calib_app.py`). Triggers for camera-profile change, ROI change, geometry version, template change and user request (`test_calib_triggers.py`; verifier `trigger-valid` exit 0, `trigger-camera` exit 3, `app-refuses-stale` exit 2). **Live per-zone detection counts are PENDING (Measurements).** | MET (machinery) |
| 4 | `L_prior` repeatability measured and documented. | Method and script (`calibration_repeatability.py`) implemented and documented (`docs/reports/phase-14-repeatability.md`). A SYNTHETIC machinery check exists, but **no live repeated calibration of a developer exists**. | NOT MET |

## 3. Tests

| Check | What it verifies | Result | Log |
|---|---|---|---|
| `pytest` | full regression suite (1244 passed, 1 skipped, 107 warnings in 543.54s (0:09:03)) | pass (exit 0) | `00-pytest.log` |
| `ruff` | lint | pass (exit 0) | `01-ruff.log` |
| `import-contracts` | seven import-linter contracts (layers, no-peek, commit-blind, ...) | pass (exit 0) | `02-import-contracts.log` |
| `validate-contracts` | all JSON Schemas + examples incl. calib-v1 rules | pass (exit 0) | `03-validate-contracts.log` |
| `env-smoke` | environment | pass (exit 0) | `04-env-smoke.log` |
| `diff-check` | whitespace/EOL of tracked changes | pass (exit 0) | `05-diff-check.log` |
| `wizard-synthetic` | all six wizard steps end to end, SYNTHETIC actor, file saved | pass (exit 0) | `06-wizard-synthetic.log` |
| `render` | layout + review screenshots (Task 14.4) | pass (exit 0) | `07-render.log` |
| `app-session` | app loads the calibration and runs a SYNTHETIC session in record mode | pass (exit 0) | `08-app-session.log` |
| `session-check` | session.json calibration hash, copied file, self-contained snapshot | pass (exit 0) | `09-session-check.log` |
| `record-session` | Phase 06 recorder with --calibration | pass (exit 0) | `10-record-session.log` |
| `metadata-check` | SessionMetadata.calibration_hash | pass (exit 0) | `11-metadata-check.log` |
| `regression` | zero drift: recording layout -> Phase 04 zones, config, feature fingerprint (+ pinned model) | pass (exit 0) | `12-regression.log` |
| `model-compat` | pinned SYNTHETIC-trained Phase 10 GRU on the calibrated layout (template-verified, ZONE features calibrated) | pass (exit 0) | `13-model-compat.log` |
| `trigger-valid` | --check on the same setup (exit 0) | pass (exit 0) | `14-trigger-valid.log` |
| `trigger-camera` | --check after a camera-profile edit (exit 3, CAMERA_PROFILE_CHANGED) | pass (exit 3) | `15-trigger-camera.log` |
| `app-refuses-stale` | app refuses the stale calibration (exit 2) | pass (exit 2) | `16-app-refuses-stale.log` |
| `repeat-1` | SYNTHETIC calibration for the repeatability machinery check | pass (exit 0) | `17-repeat-1.log` |
| `repeat-2` | SYNTHETIC calibration for the repeatability machinery check | pass (exit 0) | `18-repeat-2.log` |
| `repeat-3` | SYNTHETIC calibration for the repeatability machinery check | pass (exit 0) | `19-repeat-3.log` |
| `repeat-4` | SYNTHETIC calibration for the repeatability machinery check | pass (exit 0) | `20-repeat-4.log` |
| `repeat-5` | SYNTHETIC calibration for the repeatability machinery check | pass (exit 0) | `21-repeat-5.log` |
| `repeatability` | repeatability analysis over 5 SYNTHETIC calibrations | pass (exit 0) | `22-repeatability.log` |
| `replay-swing-L2-exp-5` | DEVELOPER_REPLAY diagnostic on data/dev-captures/swing-L2-exp-5 | pass (exit 0) | `23-replay-swing-L2-exp-5.log` |
| `replay-swing-L2-exp-6` | DEVELOPER_REPLAY diagnostic on data/dev-captures/swing-L2-exp-6 | pass (exit 0) | `24-replay-swing-L2-exp-6.log` |
| `replay-swing-L2-exp-7` | DEVELOPER_REPLAY diagnostic on data/dev-captures/swing-L2-exp-7 | pass (exit 0) | `25-replay-swing-L2-exp-7.log` |

Run `experiments/phase-14/20260926-1047-p14-gate-verification` (2026-09-26T10:47:28+03:00 → 2026-09-26T10:58:27+03:00; HEAD `a8ea862d41bc6846421596b523777d689a31f5f9`, git_dirty true; status **COMPLETED**). All commands passed: True; source unchanged during the run: True; untracked-file whitespace problems: 0. Executor recorded in `execution.json`: Claude Opus 5.5 (claude-opus-5-5).

## 4. Measurements produced in this phase

None MEASURED. Every Phase 14 quantity needs a person following the wizard. **PENDING:** `L_prior`
repeatability, wizard duration, and validation-strike detection per zone under Arm A. Development
diagnostics are labelled and are not measurements:

| Quantity | Label | Value | run | Method |
|---|---|---|---|---|
| `L_prior` spread over 5 scripted calibrations | SYNTHETIC (never evidence) | LEFT SD 0.00079, RIGHT SD 0.00026 (true 0.29 / 0.26) | `20260926-1047-p14-gate-verification` | scripted actor, noise 0.002 / 0.004 |
| swing-L2-exp-5: delivered-rate spot check / ROI grey | DEVELOPER_REPLAY diagnostic (not native FPS) | 31.2 FPS / 74 | `20260926-1047-p14-gate-verification` | recorded `t_capture`, windows ×0.2 |
| swing-L2-exp-6: delivered-rate spot check / ROI grey | DEVELOPER_REPLAY diagnostic (not native FPS) | 31.2 FPS / 38 | `20260926-1047-p14-gate-verification` | recorded `t_capture`, windows ×0.2 |
| swing-L2-exp-7: delivered-rate spot check / ROI grey | DEVELOPER_REPLAY diagnostic (not native FPS) | 31.2 FPS / 17 | `20260926-1047-p14-gate-verification` | recorded `t_capture`, windows ×0.2 |
| Wizard duration | PENDING (SYNTHETIC clock 60.0 s is simulated time) | - | - | live t_mono run required |

## 5. Integrity checklist (submitter assessment; reviewer must verify)

| # | Item | YES / NO / N/A | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled Target / Measured / Historical / Pending | YES | Thresholds are candidates (`wizard.candidate.yaml`, ADR-0037). Diagnostics are labelled SYNTHETIC / DEVELOPER_REPLAY. Phase quantities are PENDING. The "about 61 s" duration is arithmetic from the settings. |
| I-2 | No implementation claim without tests | YES | New tests `tests/calib/` (9 files), `tests/stick/test_stick_l_prior_by_hand.py`, `tests/ui/test_ui_wizard_views.py`, `tests/contracts/test_calib_contracts.py`; full suite in the final run |
| I-3 | No causal component consumes future frames | YES | The wizard and steps consume delivered frames in order (time from `t_capture`), and the calibration pipeline is the unchanged Phase 05/13 `DecisionPipeline` (Arm A). The model path keeps Phase 13's delivered-frame assertions. Calibration results change configuration between sessions, never inside a causal step. |
| I-4 | No fabricated data | YES | Actor output is SYNTHETIC in id, provenance and label, and the schema forbids SYNTHETIC with MEASURED counts. Replayed captures are existing developer recordings labelled DEVELOPER_REPLAY with validation skipped. No person-dependent value was written. |
| I-5 | FPS reported as native only | YES | The camera step's rate is labelled a delivered-rate spot check, never a native-FPS measurement, and is never written to `camera_profile.native_fps_measured`. |
| I-6 | No "latency reduced" claim before Phase 18 | YES | No latency claim |
| I-7 | Marker condition clearly labelled | YES | Markerless GEOM path unchanged; no marker use |
| I-8 | Participant-level split confirmed for ML results | N/A | No model trained or selected; pinned SYNTHETIC-trained development package only verified/run |
| I-9 | Scope respected (out-of-scope register) | YES | No depth / 3-D calibration, no retraining, no automatic zone learning, no rotation (Open Question), no multi-user. Participant files are refused under `configs/`. |
| I-10 | Status vocabulary correct | YES | Phase PENDING; RTM rows unchanged (pointer paragraph only); no submitter PASS |
| I-11 | Reproducibility fields complete | NO | Phase 14 changes are uncommitted: every run is `git_dirty: true`. A clean rerun after the owner commit is required (§8, C-14-5). |
| I-12 | Limitations stated | YES | ADR-0037 (untested model behaviour on moved layouts, candidates, V1-7 overlap), report §1–§3, this record §6–§7 |

## 6. Deviations from the phase document

| What | Why | Impact on dependents |
|---|---|---|
| Distance advice uses the Task 03.3 hand span, not the landmark bbox | The Phase 03 recommendation (28–31 px at 1.0 m, ADR-0017) is expressed in that unit; bbox sizes are not comparable to it | None; the bbox is still in the hand records |
| The ROI is *confirmed* (bound) by calibration, not re-fitted | The ROI defines the normalised frame of every zone and feature; a changed ROI is a re-calibration trigger instead of a silent override (ADR-0037 §5) | Phase 18 set-ups must keep the configured ROI or re-calibrate |
| Model verification against the calibration's template + `LayoutAdaptedStats` | The Phase 08 fingerprint hashes the zone layout, so without this rule any moved layout would refuse the model (Task 14.7) | Phase 16/18 live model runs on calibrated layouts carry the documented "untested departure" caution |
| SessionMetadata calibration fields are optional additions without a schema-version bump | Follows the Phase 13 `model_id` precedent; older documents stay valid | Reviewer may prefer a bump (Open Question) |
| `GEOMETRY_VERSION` moved to `spacedrums.geometry` (labels keep their copy, tested equal); package version 0.2.0/0.5.0 → 0.14.0 | Trigger needs a runtime geometry identity; the calib file records the app version under the documented `0.<phase>.<patch>` rule | Reinstall (`pip install -e .`) updates the installed metadata; nothing reads it |
| Config test sentinel `1.7` → `1.8` (first *unknown* schema version); live-model schema check accepts 1.6 or later | Schema 1.7 now exists (same edit Phase 13 made for 1.6) | None |
| ADR index: missing ADR-0036 row added | Phase 13 omitted it | None |
| V1-7 template overlap (`tom1`/`tom2`) found, not fixed | Phase 04 candidate layout, owner decision (seventh zone open); overlap blocks save unless nudged apart | V1-7 calibrations need nudges until Phase 04/owner fixes the layout |
| Integration test "with a dev user" replaced by SYNTHETIC closed-loop + real-frame replay runs | No person at the camera in this session; person-dependent evidence stays PENDING (execution instructions) | Criterion 1 PARTIAL |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase |
|---|---|---|
| Developer live wizard runs: `L_prior` repeatability, wizard duration, per-zone Arm A validation | PENDING (person-dependent) | Phase 14 re-gate (owner) |
| Coverage / distance thresholds (`span_px_range`, both-VALID fraction) | To Be Experimentally Determined (Phase 03 factorial C-03-3) | 14 re-gate / 18 |
| Envelope percentiles and margins; scale bounds; validation-strike count; detection / cross-talk thresholds; `L_prior` tolerance | To Be Experimentally Determined | 18 |
| Rotation in the layout fit (tilted camera) | Open Question (default no) | 18 if set-ups need it |
| Per-user vs per-setup naming | Open Question; both supported (`--scope USER|SETUP`) | owner |
| Model behaviour on layouts departing from the training layout | Pending (untested) | 18 / 19 (second layout) |
| V1-7 candidate `tom1`/`tom2` overlap | Open Question (Phase 04 layout, owner) | owner / 18 |
| SessionMetadata schema-version policy for optional fields | Open Question | owner |

## 8. Conditions (proposed, if the reviewer chooses PASS-WITH-CONDITIONS instead of FAIL)

| Condition | Owner | Must be closed by |
|---|---|---|
| C-14-1 Developer live calibration: all steps at the camera, file saved, app session with it | Project owner (developer) | before Phase 18 |
| C-14-2 `L_prior` repeatability: ≥ 3 repeated live calibrations analysed with `calibration_repeatability.py` | Project owner | before Phase 18 |
| C-14-3 Wizard duration (t_mono) and per-zone Arm A validation counts recorded from those runs | Project owner | before Phase 18 |
| C-14-4 Review candidate thresholds against the live runs | Owner / reviewer | Phase 18 pre-registration |
| C-14-5 Clean-tree rerun: `scripts/verify_phase14.py --require-clean --executor-model <m> --executor-effort <e>` after the owner commit | Next authorised phase (automatic) | before dependent work |

## 9. Reviewer statement

PENDING. Nothing in this record has been reviewed by the owner. The submitter did not run a live
wizard (no person at the camera), did not commit, tag or push, and did not start another phase.

Signed: PENDING
