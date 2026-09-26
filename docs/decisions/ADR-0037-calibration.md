# ADR-0037 — Calibration Wizard, calib-v1 file and calibrated live configuration

Status: IMPLEMENTED development machinery; every threshold a candidate; developer live calibrations,
`L_prior` repeatability and wizard duration PENDING (person-dependent).
Date: 2026-09-26. Phase: 14. Related: ADR-0005, ADR-0010, ADR-0011, ADR-0015, ADR-0017, ADR-0036.

## Context

Zone layout, ROI and `L_prior` have been development constants (Phase 02/03/04 candidates). Phase 14
(Q57, REQ-057) adds a wizard that fits them to a camera placement and a user without retraining and
without changing the detection/prediction architecture (Q20). Constraints found in the code:

- The Phase 08 feature fingerprint hashes the zone layout, and the Phase 13 loader and the fold
  normalisation both require the model's fingerprint. A moved layout therefore changes every
  model-bound hash. Without a rule, a calibrated layout would refuse the model outright.
- `calib` and `ui` are independent layer-L7 siblings (`.importlinter`). The table in
  architecture.md §2.1 lists `ui` among calib's inputs; the enforced contract wins, so the wizard's
  views are pure drawing and the composition lives in `app` (L8).
- The Phase 04 V1-7 candidate layout has overlapping zones (`tom1`/`tom2`); see Consequences.

## Decisions

1. **Wizard.** Six steps (`spacedrums.calib.wizard`), each INSTRUCT → COUNTDOWN → COLLECT → REVIEW,
   then accepted, retried or replaced by a documented default:
   camera check (profile id, frame size and ROI must match the config; a delivered-rate spot check
   and an exposure hint). The spot check is never a native-FPS measurement and is never written
   to the camera profile. Playing area: both hands VALID across three parts of the stand-here band.
   Distance advice comes from the Task 03.3 hand span, the unit of the Phase 03 28–31 px
   observation, instead of the landmark bbox. Stick prior: per-hand median axis support from the
   Phase 03 analysis over a still hold, with frames rejected for invalid tracking, a missing or
   degenerate axis, a weak axis or motion. A sanity range, IQR and count check each hand; failure
   falls back to the layout default with a warning. Zone placement: a 5–95 % percentile box of
   VALID tip positions from a guided sweep. Validation: cued strikes per zone scored under **Arm A
   only**. Save validates and writes the document. The wizard sees only frames and user actions,
   never a clock or a file.
2. **Calibration never depends on a model.** The wizard's decision pipeline runs Arm A only (no rule
   arm, no model), even when the base config configures a live model.
3. **Layout fit** (`calib.fit`): uniform scale + translation of the template's bounding box into the
   envelope minus a margin, clamped to `[scale_min, scale_max]` and to the ROI inset box; no rotation
   (phase Open Question, default no). A uniform scale is uniform in pixels too, so orientations, arc
   ranges and inward normals are invariant and copied. The identity is an exact deep copy (zero
   drift). Bounded per-zone nudges and per-zone sample choices (REQ-056) follow in that order.
   Overlap uses circumscribed 64-gon outlines, which is conservative. Overlap blocks accept and
   save; gaps under `ambiguity_gap` are flagged NEAR_NEIGHBOUR.
4. **calib-v1** (`schemas/calib-v1.schema.json` + `calib.schema.semantic_errors`): provenance
   (SYNTHETIC / DEVELOPER_REPLAY / DEVELOPER_LIVE / PARTICIPANT_LIVE; USER or SETUP scope with a
   pseudonym or setup tag), app version + git sha/dirty + `GEOMETRY_VERSION`, every wizard setting
   and its hash, camera profile id **and hash**, ROI, per-step results with a status, per-hand
   `L_prior`, the embedded template, the fit, nudges, sounds, the absolute zones, checks, the Arm A
   validation counts and the durations. The loader recomputes template → fit → nudges → sounds and
   requires exact equality with the stored zones, so hand edits are rejected. It also enforces
   provenance agreement: SYNTHETIC ⇔ SYNTHETIC counts, replay ⇒ validation skipped, and `t_mono`
   durations only for live runs. Identity: `calibration_hash = config_hash(document)`. Files are
   YAML, LF, sorted keys. A save is re-loaded and must hash identically. Participant files live
   under `data/` (git-ignored), never in `configs/`.
5. **Binding and re-calibration triggers** (`calib.store.recalibration_triggers`): camera profile
   change (any edit of the hashed `camera_profile` block), ROI change, `GEOMETRY_VERSION` change,
   template-file change and user request. Any trigger refuses the calibration at load with the
   re-run command. The ROI is part of the binding and never silently overridden.
6. **Config schema 1.7** (ADR-0010 minor bump): user-facing `calibration_path`. The
   calibration-aware resolver writes the derived `calibration` block, the calibrated `zones` and
   `stick.geom.l_prior_by_hand` (resolved `meta.schema_version` becomes 1.7). The block holds id,
   hash, provenance, template zones, fit, per-hand `L_prior`, validation outcome and geometry
   version. The L0 loader proves the three agree (zones hash, template hash, per-hand priors).
   Plain `load_config` refuses a document that names a calibration without the block, so a run
   cannot silently use uncalibrated zones. A session's config snapshot is self-contained and
   reloads with the same `config_hash`. The live-model schema check accepts 1.6 or later.
7. **Per-hand `L_prior`** (Phase 03 Open Question): `GeomSettings.l_prior_by_hand` is used per hand
   by every tip estimator. It is absent unless a calibration is applied, which keeps uncalibrated
   runs unchanged.
8. **Model compatibility (Task 14.7).** With a calibration, `build_model_arm` verifies the package
   against a feature schema built from the calibration's **template** zones (the model's training
   layout, unchanged strict checks). ZONE and zone-relative POS/VEL features are computed from the
   **loaded, calibrated** zones. Every feature name, order, unit and group must be identical; only
   geometry may differ. The fold statistics apply per index through `LayoutAdaptedStats`, which
   asserts on every call that the features came from the calibrated schema. `check_zone_features`
   asserts at pipeline start that the model stream uses the loaded zones and the applied
   calibration hash, and `DecisionPipeline` asserts that its geometry registry uses them too. The
   session records the feature-layout provenance. **Caution:** a layout that departs from the
   training layout is untested. Scaled distances and moved absolute positions shift the model's
   normalised inputs. Phase 18/19 may test a second layout. No claim is made here.
9. **Session metadata.** `session.json` and SessionMetadata record `calibration_status`
   (CALIBRATED/UNCALIBRATED), `calibration_hash` and `calibration_id`, added as optional fields
   following the Phase 13 `model_id` precedent. A recorded session also keeps a copy of the
   applied calibration file. An unfinished wizard writes no calibration: sessions then run
   UNCALIBRATED with the config's default layout (phase Fallback Strategy), and the wizard resumes
   from its partial snapshot.
10. **Versions.** `GEOMETRY_VERSION = "p04-geometry-v1"` now lives in `spacedrums.geometry`, equal to
    the Phase 07 label constant and tested. `spacedrums.__version__` and the pyproject version
    follow the documented `0.<phase>.<patch>` rule (0.14.0). Both had been stale (0.2.0 / 0.5.0),
    and calib-v1 records the value.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Calibration overrides the ROI | The ROI defines the normalised frame of every zone and feature; a silent override would move everything. A changed ROI re-calibrates instead. |
| Relax the model fingerprint check | Would let a model run on any layout without provenance. Verifying against the template keeps the strict check and makes the departure explicit. |
| Store only template + transform | Recomputation is kept as the integrity check, but the absolute zones are stored too (phase text; readable without code). |
| Rotation in the fit | Phase Open Question, default no; revisit only if Phase 18 setups need it (calib-v2). |
| Allow saving overlapping zones with a warning | Phase text: overlap blocks save. |

## Consequences

- The Phase 04 V1-7 candidate cannot be calibrated unless nudges separate `tom1`/`tom2` (−0.03/+0.03
  suffices, within `max_nudge`). Phase 04/owner decision; not changed here.
- Every wizard threshold remains a candidate (settings file `configs/calibration/wizard.candidate.yaml`,
  embedded and hashed per calibration). Coverage/distance thresholds wait for the Phase 03 factorial
  (C-03-3). Envelope percentiles/margins and the strike count need Phase 18 setups.
- Person-dependent evidence is PENDING: a developer live wizard run, `L_prior` repeatability over
  repeated live calibrations, a MEASURED wizard duration (t_mono) and per-zone Arm A detections.
