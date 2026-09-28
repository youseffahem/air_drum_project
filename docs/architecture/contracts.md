# Space Drums — Data Contract Specification

**Phase:** 01 — Task 01.2 · **Status:** IMPLEMENTED as schemas (machine-readable JSON Schemas exist and their tests pass — `TEST-SCHEMA-1`); producers: `FrameSample` (Phase 02), `HandObservation`, `StickObservation`, `TrackState` (Phase 03), `TrajectoryPrediction` (rule-based, Phase 05), `StrikeCandidate` (Phase 04 geometry; fed by Phase 05 arms A/B), `CommittedStrike` (Phase 05 commit policy), `AudioEvent` (Phase 04), `TimingRecord` (Phase 05 collector) IMPLEMENTED; `KinematicFeatures`, `DirectPrediction` and the learned producers PLANNED. Phase 06 added the dataset documents (`SessionMetadata`, `session-verification`, `exclusion-record`, `raw-manifest`); Phase 07 added the label documents (`LabelRecord`, `ReferenceTrack`, `label-set`, `label-review`, `split-file`, `dataset-manifest`) — see §6.
**Schemas:** [`../../schemas/*.schema.json`](../../schemas/) (records, shared `common.schema.json`), [`../../configs/schema/config.schema.json`](../../configs/schema/config.schema.json) (config). Examples: [`../../schemas/examples/*.valid.example.json`](../../schemas/examples/) — **synthetic placeholders, not data**.
**Tests:** `tests/contracts/` (pytest) and `scripts/validate_contracts.py` (same checks, standalone). See §5.
**Related:** [`architecture.md`](architecture.md) §5 (clock), §9 (coordinates), §12 (record/replay); ADR-0004, ADR-0005, ADR-0012.

---

## 1. Conventions that apply to every record

| Rule | Detail |
|---|---|
| **Format** | JSON Schema Draft 2020-12, one file per record type, `$id = https://spacedrums.local/schemas/<name>.schema.json`; shared definitions in `common.schema.json` via `$ref` (ADR-0012). In code, records are plain dataclasses/pydantic models that serialise to exactly this JSON; the JSON Schema is the contract, the class is an implementation. |
| **`schema_version`** | Every record carries `schema_version` (const per schema, `"1.0"` now). A breaking change bumps the major part, ships an ADR with migration notes, and keeps old records readable (README Phase 01 *Risks*). |
| **Strictness** | `additionalProperties: false` everywhere: typos cannot silently create fields; a new field is a contract change. |
| **Time** | Seconds, `float`, on `t_mono` (ADR-0004). Field names `t_<event>`; durations `*_s`. Milliseconds never appear in records or keys (test `test_seconds_not_milliseconds_key_names`). |
| **Space** | ROI-normalized `[x, y]`, origin top-left, y down (ADR-0005). Exactly two components in 1.x. Pixel values only where suffixed `_px`. Velocities `[vx, vy]` in ROI-normalized units/s; accelerations units/s². Angles in radians from `+x` towards `+y`. |
| **`t_capture` rule** | Every per-frame or per-hand record carries `t_capture` of the frame it derives from (Task 01.3). Exceptions: `AudioEvent` (keyed by `strike_id`) and `RecordStreamHeader` (not per-frame). |
| **Nullability** | A field is either required-non-null, or explicitly `… | null` with the meaning of null stated. Conditional rules (e.g. "null for REACTIVE") are enforced by `if/then` in the schema. |
| **Identity** | `hand_id ∈ {LEFT, RIGHT}`; ids (`candidate_id`, `strike_id`, `episode_id`) are opaque strings unique within a session; `frame_id` is a monotone integer assigned by capture. |
| **Serialisable** | No record embeds arrays of pixels or object references; images are `image_ref`, histories are `history_ref`. This makes every record safe to log, replay, and move across threads/processes (architecture.md §7). |
| **Labels** | No field in any record is a *result*. Producers document how confidences/proxies are computed; consumers never interpret a confidence as a probability unless the producer says so. |

---

## 2. Shared vocabularies (`common.schema.json`)

| Definition | Values | Notes |
|---|---|---|
| `hand_id` | `LEFT`, `RIGHT` | The tracked-point identity space is **open by contract**: `LEFT_FOOT`/`RIGHT_FOOT` are reserved names (`OOS-REF:REQ-207`) added only by schema bump + ADR + scope expansion. |
| `track_status` | `VALID`, `DEGRADED`, `INVALID`, `STALE` | README §8. |
| `tip_method` | `GEOM`, `AXIS_REFINED`, `MARKER` | README §14. `MARKER` results are always labelled fallback/benchmark (REQ-211, integrity I-7). |
| `candidate_source` | `REACTIVE`, `RULE`, `MODEL` | README §9; ADR-0008. Invariant with `arm`: `REACTIVE ↔ A`, `RULE ↔ B`, `MODEL ↔ C-*` (schema-enforced on `CommittedStrike`). |
| `candidate_derivation` | `GEOMETRY`, `DIRECT_HEAD` | *(gate review 2026-09-21)* `GEOMETRY` = trajectory → `geometry.intersect` (the only derivation in the live app). `DIRECT_HEAD` = diagnostic harness modes only (Phase 09 C-GBDT direct mode, Phase 19 AB-NOTRAJ), `MODEL` sources only; results labelled *direct / no-trajectory (diagnostic)*. |
| `arm` | `A`, `B`, `C-GBDT`, `C-GRU`, `C-TCN`, `C-MT`, `C-TT` | README §9; same as the experiment-log enum minus `NA`. |
| `trigger_type` | `HAND_TIP` | Open enum; `FOOT` reserved (ADR-0011). |
| `zone_id` | `^[a-z][a-z0-9_]*$` | ADR-0003 ids: `snare`, `hihat`, `tom1`, `tom2`, `floor_tom`, `crash_ride`, … |
| `point2`, `vector2`, `unit_vector2`, `rect_px`, `rect_norm` | fixed-length numeric arrays | §1 conventions. |
| `confidence` | number in `[0, 1]` | producer-defined semantics. |
| `sha256` | `sha256:<64 hex>` | model/config/dataset hashes. |

---

## 3. Record types

Producer/consumer per `architecture.md` §2. "Frame" columns: `t_mono` (seconds) / ROI-norm / px / — (dimensionless).

### 3.1 `FrameSample` — `frame-sample.schema.json` (producer: `capture`, Phase 02)

| Field | Type | Frame | Null? | Meaning |
|---|---|---|---|---|
| `schema_version` | const `"1.0"` | — | no | |
| `frame_id` | int ≥ 0 | — | no | Monotone per session; dropped frames consume no id. |
| `t_capture` | float | `t_mono` | no | Capture/exposure instant (architecture.md §5.2). |
| `t_frame_available` | float | `t_mono` | no | Hand-over to the application; ≥ `t_capture`. |
| `timestamp_source` | `DRIVER_MAPPED` \| `GRAB_RETURN` \| `REPLAY` | — | no | How `t_capture` was obtained. |
| `frame_size_px` | `[w, h]` int | px | no | Full frame size. |
| `roi_px` | `[x, y, w, h]` int | px | no | The fixed playing ROI — origin of all normalized coordinates. |
| `image_ref` | `{kind: MEMORY}` \| `{kind: FILE, path, index, crop: FULL\|ROI}` | — | no | Where the pixels are. Record mode always writes `FILE`. |
| `camera_profile_id` | str | — | no | Camera profile whose measured properties apply. |
| `dropped_since_last` | int ≥ 0 | — | no | Queue drops since the previous delivered frame. |

Added vs the phase document's field list: `timestamp_source`, `frame_size_px` (needed to reconstruct pixel coordinates and to label the timestamp method).

### 3.2 `HandObservation` — `hand-observation.schema.json` (producer: `hands`, Phase 03)

| Field | Type | Frame | Null? | Meaning |
|---|---|---|---|---|
| `schema_version`, `frame_id`, `t_capture`, `hand_id` | as above | | no | |
| `present` | bool | — | no | False ⇒ the nullable fields below are null. |
| `detector_id` | str | — | no | Landmark model + config id. |
| `landmarks` | `[21 × point2]` | ROI-norm | if `!present` | MediaPipe 21-keypoint ordering (README §14). |
| `landmark_visibility` | `[21 × confidence]` | — | yes | Only if the estimator provides it. |
| `handedness_score` | confidence | — | if `!present` | Confidence that `hand_id` is correct. |
| `bbox` | `[x, y, w, h]` | ROI-norm | if `!present` | |

Two `HandObservation`s are emitted per frame (one per `hand_id`), `present=false` when a hand is not detected. Extra detected hands (a second person, REQ-204/REQ-029) are **not** emitted; Phase 03 decides the rejection rule and logs counts.

*Producer status (Phase 03, Task 03.1, ADR-0014):* class `spacedrums.contracts.HandObservation` and producer `spacedrums.hands.HandLandmarker` IMPLEMENTED. With the pinned MediaPipe Tasks model `landmark_visibility` is always `null` (the estimator provides no per-landmark score — measured, `docs/reports/phase-03-task-03.1-hand-landmarker.md` §2.3). `hand_id` is assigned by `spacedrums.hands.identity` (Task 03.2, ADR-0014 §10): estimator label + continuity to the previous wrist; `handedness_score` is the assigner's combined identity confidence and is capped at `hands.identity.ambiguous_score_cap` (loader-enforced `< tracking.c_valid`) in ambiguous frames, so an uncertain identity can only be `DEGRADED` downstream. Consumers (Tasks 03.7/03.13) must not let `tip_confidence` exceed the hand's `handedness_score`. Mode `RAW` (label only, higher score wins a same-label collision) remains as the measurement baseline. `detector_id` format is fixed in ADR-0014 §4 and carries the identity parameters.

### 3.3 `StickObservation` — `stick-observation.schema.json` (producer: `TipEstimator` in `stick`, Phase 03)

| Field | Type | Frame | Null? | Meaning |
|---|---|---|---|---|
| `schema_version`, `frame_id`, `t_capture`, `hand_id` | | | no | |
| `present` | bool | — | no | False ⇒ geometry fields null, confidences 0. |
| `method_id` | `tip_method` | — | no | Which estimator produced it (benchmark label). |
| `axis_origin` | point2 | ROI-norm | if `!present` | Point on the axis near the hand. |
| `axis_dir` | unit_vector2 | ROI-norm | if `!present` | From origin towards the tip. |
| `tip` | point2 | ROI-norm | if `!present` | May lie outside `[0,1]²`. |
| `tip_confidence` | confidence | — | no | Consumed by tracking against `c_valid`/`c_min`. |
| `axis_confidence` | confidence | — | no | |
| `stick_length_est` | float ≥ 0 | ROI-norm | yes | Apparent length if estimated. |

*Producer status (Phase 03, Tasks 03.4–03.9, ADR-0015):* class `spacedrums.contracts.StickObservation` and producers `spacedrums.stick.{GeomTipEstimator, AxisRefinedTipEstimator, MarkerTipEstimator}` IMPLEMENTED (`TEST-CONFORM-1`). `stick_length_est` is in ROI-height units (px / roi.h; the ROI-normalized frame is anisotropic). `tip_confidence` is producer-defined and bounded by the hand's `handedness_score`.

### 3.4 `TrackState` — `track-state.schema.json` (producer: `Tracker` in `tracking`, Phase 03)

| Field | Type | Frame | Null? | Meaning |
|---|---|---|---|---|
| `schema_version`, `frame_id`, `t_capture`, `hand_id` | | | no | |
| `status` | `track_status` | — | no | README §8. |
| `tracker_id` | str | — | no | Implementation + config id. |
| `tip_method` | `tip_method` | — | yes | Method of the observation consumed this frame (I-7 labelling). |
| `tip_filtered` | point2 | ROI-norm | null iff `INVALID`/`STALE` | Filtered tip. |
| `tip_velocity` | vector2 | ROI-norm/s | idem | |
| `tip_acceleration` | vector2 | ROI-norm/s² | yes | |
| `axis_angle` | float | rad | yes | From `+x` towards `+y`. |
| `axis_angular_velocity` | float | rad/s | yes | |
| `confidence` | confidence | — | no | Feeds VALID/DEGRADED decision. |
| `frames_since_valid` | int ≥ 0 | — | no | 0 on a fresh VALID frame. |
| `last_valid_t` | float | `t_mono` | yes | Null since the last reset if no VALID yet. |
| `history_ref` | `{n, oldest_frame_id}` | — | yes | Metadata about the causal window; the window is reconstructible from the record stream. |
| `reset_reason` | enum | — | yes | Set on the frame where a reset occurred (`architecture.md` §6.2). |

Exactly one `TrackState` per hand per processed frame, whatever the status, so gaps are explicit in every stream.

Added vs the phase document: `tracker_id`, `tip_method`, `reset_reason`.

### 3.5 `KinematicFeatures` — `kinematic-features.schema.json` (producer: `features`, Phase 08)

| Field | Type | Null? | Meaning |
|---|---|---|---|
| `schema_version`, `frame_id`, `t_capture`, `hand_id` | | no | |
| `feature_schema_id` | str | no | Names the Phase 08 feature schema that defines `values[]` (e.g. `fs-v1`); consumers refuse a mismatch. |
| `values` | `[F × float]` | no | NaN/Inf forbidden. |
| `mask` | `[F × bool]` | no | False = not computable causally at this frame (insufficient history). |
| `dt` | float s | no | Actual interval to the previous processed frame for this hand. |
| `track_status` | `track_status` | no | Carried to avoid joins. |

This record fixes only the **envelope**; feature semantics and their leakage tests are Phase 08's.

### 3.6 `TrajectoryPrediction` — `trajectory-prediction.schema.json` (producer: `Anticipator`, Phases 05, 09–13)

| Field | Type | Frame | Null? | Meaning |
|---|---|---|---|---|
| `schema_version`, `frame_id`, `hand_id` | | | no | |
| `t_capture` | float | `t_mono` | no | **Reference time `t_ref`**: latest frame the prediction was allowed to see. Step `k` (1-based) is at `t_ref + k·dt_step`. |
| `anticipator_id` | str | — | no | e.g. `rule-cv-v1`, `gru-traj-ds-v1.0-17-3fa9c2e1`. |
| `model_hash` | sha256 | — | null for rule-based | Verified at load (Phase 13). |
| `K` | int ≥ 1 | — | no | Steps = `len(positions)`. |
| `dt_step` | float s > 0 | — | no | Step interval for uniform predictions; horizon `H = K·dt_step`. |
| `t_offsets_s` | `[K × float > 0]` | s | yes | *(gate review 2026-09-21)* Null = uniform steps at `t_ref + k·dt_step`. Otherwise strictly increasing explicit offsets, one per position — for anticipators that predict sparse horizons (Phase 09 GBDT head iv). Geometry intersects the polyline as given; missing steps are never interpolated into a denser trajectory. |
| `positions` | `[K × point2]` | ROI-norm | no, non-empty | **Primary output** (trajectory-first, ADR-0007). A prediction without a trajectory is not a `TrajectoryPrediction`; it is a `DirectPrediction` (§3.11, diagnostic only). |
| `velocities` | `[K × vector2]` | ROI-norm/s | yes | |
| `uncertainty` | `[K × [m × float]]` | — | yes (reserved, Phase 12) | Layout named by `uncertainty_kind`. *(Phase 12, ADR-0034; development layouts, adoption PENDING)* `sigma_xy`: (std_x, std_y) per step around `positions`; `members_xy`: (dx, dy) per ensemble member, offsets from `positions`, equal weights; `mixture_xy`: (w, dx, dy) per mode, weights repeated on every step (E2c development encoding; adopting commit rule M2 needs a dedicated `modes` field, ADR-0032). Read by `geometry/probabilistic.py` (`intersect_prob`), which only ever relabels an existing geometry candidate's `strike_probability`. |
| `uncertainty_kind` | str | — | yes | e.g. `sigma_xy`, `cov_xy`; Phase 12 also uses `members_xy`, `mixture_xy`. |
| `aux` | object | — | fields nullable | `strike_prob_within_H`, `tti` (s from `t_ref`), `zone_logits` + `zone_ids`, `impact_pos`, `intensity_proxy` (Phase 11 heads). **Never used instead of `positions` to decide a strike**; geometry decides. |
| `aux.consistency_flags` | `{zone, tti, position, intensity}` of bool/null | — | yes | *(Phase 11, schema 1.1, ADR-0028)* Agreement of the heads with the candidate geometry derived from **this** prediction, set after geometry by `models/temporal/consistency.py`; null without a candidate or a head. May gate a geometry candidate via `commit.aux_heads` (config 1.5); never creates one. 1.0 records are read as null. |
| `t_inference_done` | float | `t_mono` | no | |

### 3.7 `StrikeCandidate` — `strike-candidate.schema.json` (producer: `geometry`, Phase 04; fed by Phases 05/09–13)

| Field | Type | Frame | Null? | Meaning |
|---|---|---|---|---|
| `schema_version`, `frame_id`, `t_capture`, `hand_id` | | | no | Frame whose trajectory produced the candidate. |
| `candidate_id` | opaque id | — | no | |
| `zone_id` | zone_id | — | no | |
| `source` | `candidate_source` | — | no | ADR-0008. |
| `derivation` | `candidate_derivation` | — | no | *(gate review 2026-09-21)* `GEOMETRY` for every live candidate; `DIRECT_HEAD` only with `source = MODEL` in diagnostic harness modes (schema-enforced). |
| `anticipator_id` | str | — | null iff `REACTIVE` | |
| `t_impact_pred` | float | `t_mono` | null iff `REACTIVE` | Predicted impact time. |
| `t_impact_est` | float | `t_mono` | non-null iff `REACTIVE` | Sub-frame interpolated observed crossing. |
| `tti` | float s | — | null iff `REACTIVE` | `t_impact_pred − t_capture`. |
| `impact_position` | point2 | ROI-norm | no | Crossing point on the impact surface (Q38). |
| `crossing_velocity` | vector2 | ROI-norm/s | no | |
| `strike_probability` | confidence | — | yes | Source-agnostic confidence for the commit policy. |
| `intensity_proxy` | float | — | no | README §6; not force. |
| `t_candidate` | float | `t_mono` | no | Emission instant. |

The `if/then` rules make a `REACTIVE` candidate with a `t_impact_pred`, or a `RULE`/`MODEL` candidate without one, invalid; `DIRECT_HEAD` with a non-`MODEL` source is invalid.

### 3.8 `CommittedStrike` — `committed-strike.schema.json` (producer: `CommitPolicy`, Phase 05)

| Field | Type | Frame | Null? | Meaning |
|---|---|---|---|---|
| `schema_version`, `frame_id`, `t_capture`, `hand_id`, `zone_id`, `source` | | | no | `frame_id` = frame at which the decision was taken. |
| `strike_id`, `candidate_id`, `episode_id` | opaque ids | — | no | One commit per episode (README §14). |
| `derivation` | `candidate_derivation` | — | no | *(gate review 2026-09-21)* Copied from the candidate so results can be filtered without a join; `DIRECT_HEAD` never occurs live. |
| `arm` | `arm` | — | no | Which arm produced it (Phase 13 rule). **Invariant (schema-enforced):** `source = REACTIVE ⇒ arm = A`; `RULE ⇒ B`; `MODEL ⇒ C-*`. `source` is the decision-path tag the commit policy may see; `arm` is analysis attribution only. |
| `shadow` | bool | — | no | True ⇒ logged only, never scheduled to audio; `t_commit` then means "the instant this arm *would* have committed". |
| `t_commit` | float | `t_mono` | no | Sound now inevitable (unless shadow). |
| `t_impact_target` | float | `t_mono` | no | `t_impact_pred` for anticipatory sources; `t_commit` for `REACTIVE`. |
| `intensity_proxy` | float | — | no | |
| `gain` | float ≥ 0 | — | no | From the configured monotone mapping (Phase 04, Task 04.10). |
| `refractory_until` | float | `t_mono` | no | Persists across resets (architecture.md §6.2). |
| `commit_policy_id` | str | — | no | |

Added vs the phase document: `frame_id`, `t_capture`, `arm`, `shadow`, `commit_policy_id`.

### 3.9 `AudioEvent` — `audio-event.schema.json` (producer: `AudioScheduler`, Phase 04)

| Field | Type | Frame | Null? | Meaning |
|---|---|---|---|---|
| `schema_version`, `strike_id`, `sample_id` | | | no | |
| `t_audio_scheduled` | float | `t_mono` | no | Request received. |
| `t_target_play` | float | `t_mono` | no | = `CommittedStrike.t_impact_target`. |
| `t_audio_out_est` | float | `t_mono` | no | Placement instant + **measured** output latency of `audio_profile_id`; an **estimate**, never a measured `t_audio_out`. |
| `audio_late_s` | float ≥ 0 | s | no | How late the target already was when placed (Phase 04 late-event rule). |
| `gain` | float ≥ 0 | — | no | |
| `audio_profile_id` | str | — | no | Profile holding the measured latency. |

### 3.10 `TimingRecord` — `timing-record.schema.json` (collector: `timing`; complete from Phase 05)

One record per frame (`kind = FRAME`; `strike_id`/`hand_id` null) and one per committed strike (`kind = STRIKE`). Fields are exactly the README §5.2 symbols plus provenance:

| Group | Fields | Null when |
|---|---|---|
| Frame stamps | `t_capture`, `t_frame_available`, `t_tracking_done`, `t_features_done`, `t_inference_done` | features/inference: arms without that stage |
| Strike stamps | `t_candidate`, `t_commit`, `t_audio_scheduled`, `t_audio_out_est` | kind = FRAME |
| **External measurements** | `t_audio_out`, `t_acoustic_onset` | **always null unless measured externally (Phase 18)** |
| Impact references | `t_impact_est`, `t_impact_pred`, `t_impact_phys` | not (yet) observed / not anticipatory / no pad condition (ADR-0002) |
| Provenance | `arm`, `hardware_id`, `config_hash`, `clock_id` | `arm` null for FRAME records of arm-independent stages |

Latency components and `L_sys`, `L_pred`, `TE_audio`, `TE_pred` are computed from this record by `eval` (Phase 09) and are never stored fields.

**Estimated vs measured audio-out — labelling rule (made explicit at the gate review, 2026-09-21).** README §5.2 defines one symbol `t_audio_out` with two admissible provenances ("estimated from measured audio output latency, or measured externally"). This contract splits them so the two can never be confused:

| Field | Provenance | May feed a quantity labelled… |
|---|---|---|
| `t_audio_out_est` | software: sample-placement instant + the **MEASURED** output latency `L_out` of `audio_profile_id` (Phase 04). Always present once audio runs. | `L_sys_est`, `TE_audio_est` — reported as **software-estimated** with the audio profile and its `L_out` uncertainty stated (Phase 05, Task 05.9 wording). Never as `L_sys` / `TE_audio`, never as MEASURED end-to-end latency. |
| `t_audio_out` | **external measurement** of the DAC output (Phase 18 instrument), null otherwise | `L_sys`, `TE_audio` (README §5.4) — MEASURED, with the instrument, method and run id. |
| `t_acoustic_onset` | external microphone onset of the drum sound, null otherwise | `L_sys` / `TE_audio` against `t_acoustic_onset`, stated as such. |

Rules: (1) `eval` names any latency quantity derived from `t_audio_out_est` with the `_est` suffix and the label *software-estimated*; (2) a quantity named `L_sys`/`TE_audio` without suffix requires `t_audio_out` or `t_acoustic_onset` non-null; (3) `L_pred = t_impact_est − t_commit` uses no audio timestamp and is unaffected; (4) `L_eff` remains conceptual (README §5.4) and is never computed from `_est` values; (5) the two fields are never merged, averaged, or substituted for one another in a table without a per-row provenance column.

### 3.11 `DirectPrediction` — `direct-prediction.schema.json` (diagnostic only; added at the gate review, 2026-09-21)

| Field | Type | Null? | Meaning |
|---|---|---|---|
| `schema_version`, `frame_id`, `t_capture`, `hand_id`, `anticipator_id`, `t_inference_done` | as `TrajectoryPrediction` | no | `t_capture` = causal reference time. |
| `model_hash` | sha256 | **no** | Always a learned model; rule-based anticipators have no direct mode. |
| `diagnostic_mode` | `P09_GBDT_DIRECT` \| `P19_AB_NOTRAJ` | no | The sanctioned path that produced it; anything else is a contract violation. |
| `strike_prob_within_H`, `horizon_s` | confidence, s | no | Head (i). |
| `tti` | s | yes | Head (ii); adapter sets `t_impact_pred = t_capture + tti`; no candidate when null. |
| `zone_logits` + `zone_ids` | arrays | yes | Head (iii). |
| `impact_pos`, `intensity_proxy` | point2, float | yes | Optional heads. |

Why it exists: Phase 09 Task 09.8 evaluates C-GBDT in a **direct** mode (probability + TTI → candidate, no geometry) beside the trajectory-derived mode, and Phase 19 AB-NOTRAJ ablates the trajectory stage. Without this record those paths would have to fake a `TrajectoryPrediction` or bypass the contracts. Rules: it is produced only inside the harness by a `DirectAnticipator` (`architecture.md` §11); it is consumed only by the harness's direct-head adapter, which emits `StrikeCandidate(source=MODEL, derivation=DIRECT_HEAD)` through the **same** commit policy; it is never produced by the live application, never consumed by `geometry`, and Phase 13's loader refuses a model package that offers only a direct head. It passes `TEST-CAUSAL-1/2` like any anticipator output.

---

## 4. Record streams on disk — `RecordStreamHeader` (`record-stream-header.schema.json`)

Record mode (architecture.md §12.2) writes one JSONL file per record type. **Line 1 is a `RecordStreamHeader`**, lines 2… are records. The header pins:

| Field | Meaning |
|---|---|
| `record_type`, `record_schema_version` | Which record follows and its contract version. |
| `units` | `{time: "s", clock: "t_mono", position: "roi_norm", velocity: "roi_norm_per_s", angle: "rad"}` — **const**; a stream in other units cannot validate (this is the "wrong units flag" test). |
| `session_id`, `config_hash`, `git_sha`, `clock_id` | Provenance needed to regenerate or compare. |
| `producer` | `LIVE` / `REPLAY` / `REGENERATED`. |
| `derived` | False only for `FrameSample` streams beside raw video; true for everything regenerable (§12.3). |

---

## 5. Schema tests — `TEST-SCHEMA-1`

Implemented now (`tests/contracts/`, 99 tests; `scripts/validate_contracts.py`, 204 checks) and re-run by every later phase that touches a schema:

1. Each schema is valid Draft 2020-12 and cross-file `$ref`s resolve.
2. Each `schemas/examples/<name>.valid.example.json` is accepted.
3. Removing **any** required field is rejected; an unknown field is rejected; `schema_version` other than the pinned const is rejected.
4. `t_capture` absent or non-numeric is rejected on every per-frame record.
5. Wrong units flag in a stream header is rejected (`time = "ms"`, `clock = "wall"`, `position = "px"`, `angle = "deg"`).
6. Semantic conditionals: `hand_id` outside `{LEFT, RIGHT}` rejected; 3-component points rejected; present-hand without landmarks rejected; `INVALID` state with a position rejected; `REACTIVE` candidate with `t_impact_pred` rejected; anticipatory candidate without it rejected; empty `positions` rejected; `kind = FRAME` timing record with a `strike_id` rejected; `arm = NA` rejected in `CommittedStrike`; negative `audio_late_s` rejected; *(gate review)* `source`↔`arm` mismatch rejected; `DIRECT_HEAD` with a non-`MODEL` source rejected; `DirectPrediction` without `model_hash` or with an unsanctioned mode rejected; non-positive `t_offsets_s` rejected.
7. Config: example accepted; every top-level block required; unknown key rejected; `trigger_type = FOOT` rejected; `allowed_hands` optional; native FPS without `run_id` rejected; no `*_ms` keys.

Result on 2026-09-20 (submission): 90 passed / 183 checks. Result on 2026-09-21 (gate review, after the corrections in §9), HW-01, `.venv` Python 3.11.9: **99 passed** (pytest), **RESULT: PASS** (204 checks). Recorded in `docs/gates/phase-01-gate.md`.

---

## 6. Reserved record names (defined later, constrained now)

> **Phase 06 (2026-09-21, ADR-0019):** `SessionMetadata` is now **defined** — `schemas/session-metadata.schema.json` (1.0), `spacedrums.data.metadata`; every reserved field below is present, plus `session_kind` (`SYNTHETIC | DEV_CAPTURE | PILOT | PARTICIPANT`) with conditional rules that make developer / synthetic material structurally unable to carry participant ids, consent or dataset versions. Companion Phase 06 documents: `session-verification` (verify.json), `exclusion-record`, `raw-manifest` (the dataset manifest reserved in the table).

> **Phase 07 (2026-09-22):** `LabelRecord` and `ReferenceTrack` are now **defined** — `schemas/label-record.schema.json` (1.0) and `schemas/reference-track.schema.json` (1.0), `spacedrums.data.labels`. Every reserved field below is present under its reserved name (`qc_status` and `labeller_id` stay top-level; the review detail lives in a `review` object beside them). Added beyond the reservation: `labels_version`, `source_kind`, `label_class`, `level`, `t_event`, `t_start`/`t_end`, `frames`, `episode_id`, `segment_id`/`take`/`type`, `crossing_velocity`, `intensity_secondary`, `approach`, `confidence`, `reference_quality`, `phys`, `review`, `runtime_reference`, `causal` (const `false`), `provenance`, `excluded`/`exclusion_ref`, `notes`. Companion Phase 07 documents: `label-set` (the per-session label set), `label-review` (the QC log), `split-file` (participant-level splits) and `dataset-manifest` (`ds-v*`). Two rules are structural: (i) every label and every reference track carries `causal: false` as a schema `const`, and `RecordStreamHeader.record_type` still has no value naming a label artefact, so a label file cannot be opened as a record stream; (ii) `dataset_version` is gated on `source_kind` exactly as Phase 06 gates raw manifests — a `SYNTHETIC` or `DEV_CAPTURE` label can only carry `ds-none-v0.0` or `ds-v0.0-selftest*` and can never carry `t_impact_phys`.

| Record | Defined in | Required fields reserved by this phase |
|---|---|---|
| `SessionMetadata` (`schemas/session-metadata.schema.json`) | Phase 06 | `schema_version`, `dataset_version`, `session_id`, `participant_id` (pseudonym), `hardware_id`, `camera_profile_id`, `audio_profile_id`, `config_hash`, `git_sha`, `clock_id`, `started_at` (wall clock) + `t_mono_at_start`, `arm_active`, `arms_shadow[]`, `fallback_events[]`, `has_phys_gt: bool` + `segments[]` (see invariant below), `audio_track_ref: str|null` + `audio_alignment_residual_s: float|null` (ADR-0002), `capture_stats` (Phase 02), `video_codec` + parameters, `tip_method_condition` (markerless vs marker, REQ-211), `lighting`/`background` descriptors (Q27–Q29), `consent_record_id`. |
| `LabelRecord` (`schemas/label-record.schema.json`) — **DEFINED, Phase 07** | Phase 07 | `schema_version`, `dataset_version`, `session_id`, `hand_id`, `zone_id`, `t_impact_est` (offline, non-causal by design), `impact_position`, `intensity_proxy_gt`, `t_impact_phys: float|null`, `label_rule_id`, `qc_status`, `labeller_id`. |
| Dataset manifest | Phase 06 | `dataset_version`, per-file `path`, `bytes`, `sha256` (`repo-layout.md` §3.4). |

| `ReferenceTrack` (`schemas/reference-track.schema.json`; a file, **not** a stream record type) — **DEFINED, Phase 07** | Phase 07 | *(gate review 2026-09-21)* Offline, **non-causal** smoothed/bidirectionally-filtered tip trajectory used only to construct labels (`t_impact_est` labels, intensity GT). Required: `schema_version`, `dataset_version`, `session_id`, `hand_id`, `method_id` (smoother), `causal: false` (const), samples `[(t, p)]`. Lives under `labels/`; never under `records/`; never a `TrackState`. See `causality-tests.md` §1.1. |

**`has_phys_gt` — semantics and invariant (audited at the gate review, 2026-09-21).** ADR-0002 asked for `has_phys_gt` on `FrameSample`/`SessionMetadata`. Physical ground truth is **not constant within a session**: ADR-0002's condition is recorded as *pad segments* inside a session (the participant strikes the practice pad in some protocol segments and air-drums in others), the pad coincides with **one** zone's impact surface (strikes on other zones in a pad segment have no physical GT), and the microphone track may be missing or unusable for part of a session. The placement is therefore **three-level**, and the flag is correct only with this invariant:

| Level | Field | Meaning |
|---|---|---|
| Session | `SessionMetadata.has_phys_gt: bool` | **Availability only**: true iff a microphone track mapped onto `t_mono` exists for the session (`audio_track_ref` non-null, alignment residual recorded) **and** at least one segment has `condition = PAD`. It never implies that any particular strike has physical GT. |
| Segment | `SessionMetadata.segments[] {segment_id, t_start, t_end, condition: AIR \| PAD, pad_zone_id: zone_id \| null}` (reserved here) | Which protocol segments were pad segments and which zone the pad coincided with. `pad_zone_id` non-null iff `condition = PAD`. |
| Strike | `LabelRecord.t_impact_phys: float \| null`, `TimingRecord.t_impact_phys: float \| null` | The **only** per-strike truth. Non-null iff the strike falls in a `PAD` segment, on `pad_zone_id`, with a labelled acoustic onset (Phase 07 rule). |

Invariants: `has_phys_gt = false ⇒` every `t_impact_phys` in the session is null; `t_impact_phys ≠ null ⇒ has_phys_gt = true` and the strike lies in a `PAD` segment on its `pad_zone_id`. Any metric using `t_impact_phys` states the number of strikes it covers (ADR-0002). A per-frame flag on `FrameSample` (ADR-0002's wording) is not needed and would be misleading: the frame does not know whether a strike will be labelled. Conclusion: session-level placement is **correct as an availability flag**; the per-segment and per-strike levels carry the varying truth. *(Phase 06 defined `SessionMetadata`; Phase 07 defined `LabelRecord` and enforces the per-strike level in `spacedrums.data.labels.acoustic` and in the label validator, which raises `PHYS_INVARIANT` when `t_impact_phys` appears outside a `PAD` segment on its `pad_zone_id`.)*

---

## 7. Interface value types (not stored; used by `architecture.md` §11)

| Type | Shape | Notes |
|---|---|---|
| `Trajectory` | `{point_id: str, kind: OBSERVED \| PREDICTED, samples: [(t: float, p: point2), …]}` | Time-ordered; for `PREDICTED`, the first sample is the current observed tip so the segment into the future is continuous. `point_id` is a `hand_id` in V1 (reserved foot names, §2). |
| `FrameView` | ROI crop of the frame as an in-memory array + the `FrameSample` | Never serialised; `TipEstimator` input. |
| `ResetReason` | `GAP_EXCEEDED`, `LOW_CONFIDENCE`, `STALE`, `MANUAL`, `ARM_SWITCH`, `CONFIG_RELOAD`, `SESSION_START` | Same enum as `TrackState.reset_reason`. |

---

## 8. Versioning and migration

- A field is **added** → minor bump (`1.1`), old records remain valid if the field is nullable with a documented default; ADR required.
- A field's meaning, unit, or nullability **changes**, or a field is removed → major bump (`2.0`); readers keep a migration path for `1.x`; ADR with migration notes required.
- A field is **never repurposed** (Phase 01 *Fallback Strategy*).
- Enums (`hand_id`, `trigger_type`, `tip_method`, `candidate_source`, `candidate_derivation`, `arm`) are extended only by bump + ADR; scope-touching values additionally need the `out-of-scope.md` §2 procedure.

---

## 9. Changes made at the Phase 01 gate review (2026-09-21)

All changes below were made **before** the gate verdict, while `schema_version` is still `1.0` and no consumer exists; they are therefore not bumps. Each is listed in `docs/gates/phase-01-gate.md` §6 with the finding that motivated it.

| Change | Finding | Files |
|---|---|---|
| `StrikeCandidate.derivation`, `CommittedStrike.derivation` (`GEOMETRY` \| `DIRECT_HEAD`) with `DIRECT_HEAD ⇒ source = MODEL` | Phase 09 Task 09.8 "direct" evaluation mode and Phase 19 AB-NOTRAJ were not representable without faking a trajectory (contradiction with roadmap decisions; trajectory-first claim needs a labelled diagnostic path, not a hidden one). | `strike-candidate`, `committed-strike`, `common.schema.json`; ADR-0007 amendment |
| New diagnostic-only record `DirectPrediction` (§3.11) + `DirectAnticipator` protocol | same | `direct-prediction.schema.json`, `record-stream-header` enum, `architecture.md` §11 |
| `TrajectoryPrediction.t_offsets_s` (nullable) | Phase 09 GBDT head (iv) predicts sparse horizons; uniform steps would force interpolation to be presented as prediction. | `trajectory-prediction.schema.json` |
| `source ↔ arm` invariant on `CommittedStrike` | Two attribution fields without a stated relation were ambiguous. | `committed-strike.schema.json` |
| Estimated-vs-measured audio-out labelling rule (§3.10) | Rule existed only implicitly; `L_sys` could have been computed from `t_audio_out_est` and reported without the `_est` label. | this file; `architecture.md` §5.4 |
| `has_phys_gt` three-level invariant + `segments[]`, `audio_alignment_residual_s`, `capture_stats` reservations (§6) | Physical GT varies within a session (pad segments, single pad zone); session flag is availability only. | this file |
| `ReferenceTrack` reserved as a non-causal **label** artefact, never a stream record | The causality rule did not say explicitly where offline-smoothed trajectories may live. | this file; `causality-tests.md` §1.1 |
| Conformance test ids renumbered `TEST-CONFORM-1…7` | `repo-layout.md` §3.5 pattern `TEST-<AREA>-<N>`. | `causality-tests.md`, ADR-0006 |

## Phase 08 implementation note

The KinematicFeatures envelope is unchanged at 1.0; its concrete fs-v1 implementation is
`features.schema.KinematicFeatures`. The semantic descriptor and parameter/layout hash are
defined in `docs/features/feature-schema-v1.md` and `schemas/feature-schema-v1.json`.
Feature targets are offline-only; data composition resides in `data.feature_dataset`.
Optional same-frame hand/stick/frame observations supply fields absent from TrackState.

## Phase 11 contract change (2026-09-25, ADR-0028)

`TrajectoryPrediction` 1.0 → **1.1** (minor, §8): `aux.consistency_flags` added, nullable, required in 1.1
records, absent in 1.0 records (read as null). Writers emit 1.1. Config 1.4 → **1.5**: optional
`commit.aux_heads` (defaults off; rejected in documents declaring < 1.5). C-MT aux population
rules are in ADR-0028 §2. The harness gained the `MODEL:C-MT` arm, a post-geometry candidate
gate and the explicitly flagged `diagnostic_direct` mode for `DIRECT_HEAD` candidates; no enum,
StrikeCandidate or CommittedStrike field changed.

## Phase 19 preparation contract note (2026-09-27, ADR-0043)

No causal record envelope or frozen Phase 09 matching rule changes. Config schema 1.9 adds
complete optional per-arm live settings for ADR-0036. `confirmatory-lock`'s live branch
requires its pinned offline parent and base config; archive/verify checks compare resolved
settings and the preregistration binding. Separate `ablation-plan` and `ablation-reference`
documents belong to the offline tooling layer. Their validation never constitutes approval
or a participant gate. The only checked-in plan example is SYNTHETIC/DEV.
