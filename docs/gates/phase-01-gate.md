# Phase 01 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 01 — System Architecture & Contracts |
| Phase document | `phases/phase-01-system-architecture.md` |
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-20 |
| Reviewer(s) | Final gate review performed by Claude **on the project owner's explicit instruction** (2026-09-21, scope in §11); project owner countersignature **pending** (gate-procedure §4: a gate is not passed by the submitter alone — the verdict below becomes effective on the owner's signature in §10) |
| Review date | 2026-09-21 |
| Code state | Phase 00 artefacts committed as `865805b93fe5bffa7775cde7b104016c0e964047` ("phase 00"). Phase 01 artefacts **uncommitted** (dirty: yes, 54 paths) at the owner's instruction; the owner's commit after signature becomes the citable `git_sha`. Specification phase; the only executable code is `scripts/validate_contracts.py` and `tests/contracts/` (schema tests). |
| **Verdict** | **PASS** — all seven acceptance criteria MET after the review corrections listed in §7; integrity checklist has no NO; Definition of Done satisfied. Effective on owner signature (§10). Follow-up obligations that are *not* conditions on this phase's criteria are listed in §9. |

## 1. Artefacts produced

| Artefact (from phase document) | Path | Status label | Present? |
|---|---|---|---|
| Architecture Specification (module map, allowed dependencies, per-hand pipeline, threading candidates, latency slots, clock model, state ownership + reset matrix, interfaces, record/replay symmetry, zone extensibility) | `docs/architecture/architecture.md` | IMPLEMENTED (specification); every module PLANNED | yes |
| Data Contract Specification | `docs/architecture/contracts.md` | IMPLEMENTED (specification) | yes |
| Machine-readable record schemas (12) + shared definitions | `schemas/common.schema.json`; `frame-sample`, `hand-observation`, `stick-observation`, `track-state`, `kinematic-features`, `trajectory-prediction`, `direct-prediction` (diagnostic-only, added at review), `strike-candidate`, `committed-strike`, `audio-event`, `timing-record`, `record-stream-header` (`*.schema.json`) | IMPLEMENTED (tests pass) | yes |
| Synthetic example records | `schemas/examples/<name>.valid.example.json` (12 new) | example / synthetic — not data | yes |
| Causality contract + test specifications (`TEST-CAUSAL-1`, `TEST-CAUSAL-2`, `TEST-PARITY-1`, `TEST-CONFORM-1…7`) | `docs/architecture/causality-tests.md` | IMPLEMENTED (specification); tests PLANNED (executed by Phases 03+) | yes |
| Configuration schema + example config | `configs/schema/config.schema.json`, `configs/example.candidate.yaml` | IMPLEMENTED (schema, tests pass); example values all *candidate* | yes |
| ADRs for Task 01.10 + Task 01.8 | `docs/decisions/ADR-0004` … `ADR-0012` + index (ADR-0007 amended at review) | Accepted (ADR-0009 partly Pending by design) | yes |
| Schema tests (`TEST-SCHEMA-1`) + standalone checker | `tests/contracts/{conftest,test_record_schemas,test_config_schema}.py`, `scripts/validate_contracts.py`, `pyproject.toml` (tool config only) | IMPLEMENTED, pass | yes |
| Layout amendment + package stubs | `docs/repo-layout.md` (P01 notes), `src/spacedrums/{contracts,timing,config}/README.md`, updated README stubs | PLANNED stubs | yes |
| RTM references | `docs/requirements/rtm.md` rows REQ-001, 004, 021, 033, 051, 052, 055, 060b, 207, 302 carry a Phase 01 evidence pointer; status stays PLANNED until the owner signs this record | — | yes |
| Gate record | this file | — | yes |

## 2. Acceptance criteria

| # | Criterion (verbatim) | Evidence | Assessment |
|---|---|---|---|
| 1 | Architecture spec contains the module map, allowed-dependency rules, per-hand pipeline, threading candidates, and named latency slots. | `architecture.md` §2.1 (17 packages), §2.2–2.4 (layers, diagram, import-linter contract), §3, §7 (T1/T2/T3), §8 (nine named slots, all Pending Benchmark). | **MET** |
| 2 | Every record type in *Interfaces / Contracts* has a machine-readable schema that validates. | All 10 record types of the phase document + `RecordStreamHeader` + `DirectPrediction` have JSON Schemas; `TEST-SCHEMA-1`: **99 passed**; `validate_contracts.py`: 204 checks, `RESULT: PASS` (HW-01, `.venv` Python 3.11.9, 2026-09-21). `SessionMetadata`/`LabelRecord`/`ReferenceTrack` reserved with required fields (`contracts.md` §6). | **MET** |
| 3 | Causality tests `TEST-CAUSAL-1/2` and parity test `TEST-PARITY-1` are fully specified (inputs, procedure, pass criteria). | `causality-tests.md` §2, §3, §4 each with Inputs / Procedure / Pass criteria / Evidence, negative control for `TEST-CAUSAL-2`, tolerance rules, component list; §1.1 (added at review) fixes where non-causal artefacts may exist. | **MET** |
| 4 | Config schema exists and validates the example config. | `configs/schema/config.schema.json`; `example.candidate.yaml` accepted; 22 config tests pass. | **MET** |
| 5 | Zone-registry extensibility (open trigger-type enum, hand-agnostic zones) is specified. | `architecture.md` §10; ADR-0011; `trigger_type` enum `HAND_TIP` only with `FOOT` reserved; `allowed_hands` optional, default both; tests reject `FOOT`. | **MET** |
| 6 | ADRs written for all decisions in Task 01.10. | ADR-0004 clock, 0005 coordinates, 0006 per-hand, 0007 trajectory-first (amended), 0008 candidate source, 0009 threading, 0010 config — plus 0011 zone extensibility (Task 01.8) and 0012 contract format / layout. | **MET** |
| 7 | Reviewer confirms the spec does not contradict `project-discovery.md` (trajectory-first, markerless primary, no out-of-scope hardware, per-hand independence, causal). | Explicit check in §2.1 below against `project-discovery.md`, the Phase 00 RTM/out-of-scope register, ADR-0001…0003 and the roadmap. **One contradiction found and corrected** (direct-mode diagnostic paths, §7 D-1); no contradiction remains. | **MET** (after correction) |

### 2.1 Criterion 7 — explicit contradiction check (2026-09-21)

| Area | Source of truth | What the Phase 01 artefacts say | Finding |
|---|---|---|---|
| Software-only / webcam-first | Q1, Q7, Q8, Q22; REQ-201–203 | Module map has one sensing input (`capture` ← webcam / replay file); no sensor, IMU, microcontroller, MIDI or network element anywhere; `camera_profile.device` accommodates a later external/phone camera (Q22) | no contradiction |
| Markerless hand + stick tracking | Q9, Q10, Q30, Q31; REQ-210, REQ-211; ADR-0001 stack | `TipEstimator` with `method_id ∈ {GEOM, AXIS_REFINED, MARKER}` — the three methods Q31 asks to compare; `MARKER` labelled fallback/benchmark on `StickObservation` and carried into `TrackState.tip_method` for I-7; nothing assumes stick colour or markers; hands + stick both tracked (Q10) | no contradiction |
| Trajectory-first research direction | Q41, Q42, Core Research Direction; README §1, §9; **Phase 09 Task 09.8, Phase 19 AB-NOTRAJ** | `TrajectoryPrediction.positions` required non-empty; geometry derives the strike (ADR-0007); `prediction` cannot import `geometry`. **But** the roadmap's sanctioned *direct* diagnostic modes (C-GBDT direct mode; AB-NOTRAJ) were not representable — a real gap that would have forced Phase 09/19 to fake a trajectory or bypass the contracts | **contradiction with roadmap decisions → corrected (D-1)**: `derivation ∈ {GEOMETRY, DIRECT_HEAD}` + diagnostic-only `DirectPrediction`, never live, always labelled |
| Causal runtime processing | Q34, Q35, Q60; README §13; REQ-060b, REQ-302 | No interface has a look-ahead argument; `Tracker.history` ≤ current; replay in `frame_id` order; workers see delivered frames only; `TEST-CAUSAL-1/2` specified for every causal component including the direct path | no contradiction |
| Offline future-aware labelling forbidden at runtime | README §13 (label generation is the only non-causal place); Phase 07/08 | Made explicit at review (`causality-tests.md` §1.1, `contracts.md` §6 `ReferenceTrack`): non-causal trajectories live only under `labels/`, are never a stream record type (schema enum), never an input to any `Tracker`/`Anticipator`/`DirectAnticipator`/feature/`Geometry`/`CommitPolicy`, never a training *feature*; harness loads labels only after all arms have run | no contradiction (rule was implicit; now explicit) |
| Virtual drum geometry | Q16–Q21; ADR-0003; Phase 04 zone model | Config `zones[]` = Phase 04's model (ELLIPSE/POLYGON, SEGMENT/ARC impact surface, explicit `inward_normal`, `sample_id`, `gain_curve_id`); ROI-normalized 2-D (ADR-0005); zones fixed within a session (Q18) | no contradiction |
| Impact definition | Q36–Q39; README §6 | First valid downward/inward entry per episode via `inward_normal` (Q36/37); `impact_position` + `zone_id` retained (Q38); `t_impact_est` sub-frame interpolated, set only from *observed* crossings (Q39); episodes keyed `(hand, zone)` | no contradiction |
| Latency terminology | README §5.2–§5.4; Q5, Q60; Phase 05 Task 05.9 | Field names are the README symbols; README's dual-provenance `t_audio_out` is split into `t_audio_out_est` (software estimate) and `t_audio_out` (external measurement). The rule that `L_sys`/`TE_audio` may only be computed from the measured field, and that estimate-derived quantities carry `_est`, **was implicit → made explicit (D-2)**; `L_eff` conceptual only; no latency-reduction claim in any artefact (I-6 grep) | no contradiction (clarified) |
| Physical ground-truth scope | ADR-0002; README §5.2 `t_impact_phys`; consent B1/C3b | `t_impact_phys` null unless recorded and labelled; `has_phys_gt` audited (§3.2 below): session-level = availability only; per-segment condition; per-strike truth on `LabelRecord`/`TimingRecord`; metrics state strike counts (ADR-0002) | no contradiction (invariant now explicit, D-3) |
| MVP / V1 drum-zone scope | Q16, Q17, Q55; ADR-0003; REQ-207 | Example config = the 4 ADR-0003 MVP zones with the stable ids; `kick` reserved with no layout/sample/trigger; `FOOT` rejected by schema; 7th-zone question untouched (Phase 04 gate) | no contradiction |
| Offline / local execution | Q52; REQ-209; `environment.md` (Azure EP forbidden) | No module has a network dependency; model referenced by local path + SHA-256 verified at load (Phase 13); Phase 23 offline-bundle test owns the end-to-end check | no contradiction |
| Phase 00 policies | `reproducibility-policy.md` §3 (canonical hash), `repo-layout.md` §3 (naming), `integrity-checklist.md` | `config_hash` rule referenced verbatim; `run_id` regex identical to the experiment-log schema; `*.candidate.yaml` form added by ADR-0010 (allowed: layout amendable by ADR); test ids conform to `TEST-<AREA>-<N>` after renumbering (D-6) | no contradiction |

## 3. Review audits requested by the owner

### 3.1 Schema additions beyond the phase document's field lists

| Addition | Why it exists | Changes an existing semantic? | Ambiguity? | Contradicts Phase 00? | Necessary or optional |
|---|---|---|---|---|---|
| `CommittedStrike.arm` | Phase 13 Task 13.3 requires the active arm in every commit; README §9 arm codes | No — `source` stays the decision-path tag; `arm` is attribution | Was ambiguous vs `source` → **resolved**: schema-bound `REACTIVE↔A`, `RULE↔B`, `MODEL↔C-*` (D-4) | No | **Necessary** (multi-arm shadow logging; Phase 18 attribution) |
| `CommittedStrike.shadow` | Phase 05 shadow logging (active vs logged-only arms) | Defines `t_commit` for shadow commits as "would have committed" — stated | None after the wording fix | No | **Necessary** (without it a shadow commit is indistinguishable from a sounding one → FP accounting and parity would be wrong) |
| `CommittedStrike.derivation`, `StrikeCandidate.derivation` *(review addition)* | Label the sanctioned diagnostic direct path (D-1) | No — commit policy ignores it | None: schema-enforced `DIRECT_HEAD ⇒ MODEL`, `REACTIVE/RULE ⇒ GEOMETRY` | No; protects the trajectory-first claim | **Necessary** for integrity of Phase 09/19 results |
| `TrackState.tip_method` | Integrity item I-7: every result labelled by marker condition | No (copy of `StickObservation.method_id` for the consumed observation) | Per-frame granularity is the finest possible; consistency with `StickObservation` is a conformance check (`TEST-CONFORM-2`) | No | Denormalised but **integrity-relevant**; kept |
| `TrackState.reset_reason` | Reset matrix evidence; replay can prove where resets happened; Phase 17 failure injection | No | None (null except on the reset frame; enum fixed) | No | **Necessary** (not derivable from other records) |
| `TrackState.tracker_id`, `KinematicFeatures.feature_schema_id`/`track_status`, `StrikeCandidate.anticipator_id`, `CommittedStrike.commit_policy_id`, `AudioEvent.audio_profile_id`, `TimingRecord.clock_id`/`config_hash`/`hardware_id` | Provenance: which implementation/config produced the record | No | `KinematicFeatures.track_status` must equal the `TrackState` of the same `(frame_id, hand_id)` — stated as an invariant | No; follows `reproducibility-policy.md` | Provenance ids **necessary**; `track_status` copy is optional convenience with a stated invariant |
| `TimingRecord.t_audio_out_est` vs `t_audio_out` | README §5.2 gives one symbol two provenances; a single field could present an estimate as a measurement | Refines, does not change: README `t_audio_out` ↔ measured field when present, else `_est` with label | None after D-2 | No — implements README §5.4 "measured or estimated with a documented method" | **Necessary** |
| `TimingRecord.kind`, `arm` | FRAME vs STRIKE records; arm per strike | No | None (`kind` conditionals enforced) | No | **Necessary** |
| `FrameSample.timestamp_source`, `frame_size_px` | Label the timestamp method (I-5, Phase 02 Task 02.2); reconstruct pixel coordinates from normalized ones | No | None | No | **Necessary** |
| `TrajectoryPrediction.uncertainty_kind`, `aux.zone_ids`, `t_offsets_s` *(review addition)* | Interpret nullable arrays; sparse horizons (Phase 09 head iv) without interpolation | No; `t_offsets_s = null` keeps the original uniform semantics | None (`len == K`, strictly increasing) | No | `uncertainty_kind`/`zone_ids` **necessary** when the arrays are non-null; `t_offsets_s` **necessary** for honest sparse predictions |
| `AudioEvent.audio_late_s` | Phase 04 late-event rule ("record the lateness") | No | None | No | **Necessary** |
| `RecordStreamHeader` (record type) | Pins units/provenance per stream; gives the "wrong units flag" test a concrete meaning | No | None | No | **Necessary** for record/replay symmetry |
| `DirectPrediction` (record type) *(review addition)* | D-1 | No — separate record; `TrajectoryPrediction` unchanged | None: `diagnostic_mode` enum, `model_hash` required | No | **Necessary** for Phase 09 direct mode / Phase 19 AB-NOTRAJ |

### 3.2 `has_phys_gt` audit

- **Can physical ground truth vary within a session?** Yes. ADR-0002 records the condition as *pad segments* within a session; the pad coincides with **one** zone's impact surface, so strikes on other zones in a pad segment have no physical GT; the microphone track may be missing or unusable for part of a session.
- **Is session-level placement correct?** Only as an **availability flag**. `SessionMetadata.has_phys_gt = true` iff a `t_mono`-aligned microphone track exists **and** ≥ 1 segment has `condition = PAD`. It never implies that any particular strike has physical GT.
- **Invariant (documented in `contracts.md` §6):** `has_phys_gt = false ⇒` every `t_impact_phys` in the session is null; `t_impact_phys ≠ null ⇒ has_phys_gt = true ∧` the strike lies in a `PAD` segment on its `pad_zone_id`. Per-strike truth lives **only** in `LabelRecord.t_impact_phys` / `TimingRecord.t_impact_phys` (nullable).
- **Correction made:** reserved `SessionMetadata.segments[] {segment_id, t_start, t_end, condition: AIR|PAD, pad_zone_id|null}` and `audio_alignment_residual_s` (three-level model). No JSON Schema exists yet for `SessionMetadata`/`LabelRecord` (Phases 06/07), so nothing was silently changed; the reservation text is the correction. A per-frame flag on `FrameSample` (ADR-0002's wording) is not needed and would mislead.
- **Conclusion:** session-level flag **correct with the invariant**; the varying truth is carried at segment and strike level.

### 3.3 Timing-semantics audit

| Check | Result |
|---|---|
| `t_audio_out_est` explicitly an estimate | Yes — `AudioEvent` and `TimingRecord` descriptions say "ESTIMATED … never a measured `t_audio_out`". |
| `t_audio_out` explicitly measured/observed | Yes — "Externally MEASURED DAC output instant; null unless an external measurement exists (Phase 18)"; example record has it null. |
| Estimated timestamps never presented as measured latency | **Rule made explicit (D-2)**: quantities derived from `t_audio_out_est` carry the `_est` suffix and the label *software-estimated* with the audio profile's measured `L_out`; `L_sys`/`TE_audio` without suffix require `t_audio_out` or `t_acoustic_onset`; the two fields are never merged or substituted in a table without a provenance column (`contracts.md` §3.10, `architecture.md` §5.4). |
| `L_sys` not derived from an estimate and reported as measured | Guaranteed by the rule above; `L_pred` uses no audio timestamp; `L_eff` stays conceptual (README §5.4) and is never computed from `_est` values. |
| Terminology consistent with README §5 | Field names are the README symbols; the only refinement (est/measured split) implements README §5.4's "measured or estimated with a documented method" and Phase 05 Task 05.9's "software-stamped estimate" wording. |

**Conclusion:** consistent; one implicit rule made explicit, no field changed.

### 3.4 Causality audit

- Every online/runtime input (`FrameSample` → `HandObservation`/`StickObservation` → `TrackState` history → `KinematicFeatures` → `Anticipator`/`DirectAnticipator` → `Geometry` → `CommitPolicy`) is produced from frames with `t_capture ≤` the current frame; no interface has a look-ahead argument; `Tracker.history` exposes only past states; replay preserves `frame_id` order; workers (T2/T3) see delivered frames only and must re-pass `TEST-CAUSAL-1` live.
- Offline-smoothed / future-aware trajectories (`ReferenceTrack`) and offline `t_impact_est` labels are **allowed only for annotation / ground-truth construction** (Phase 07): they live under `labels/`, cannot be a stream record type (schema enum), never enter any tracker, anticipator, feature, geometry or commit call, and are never training *features* (Phase 08 reference-track exclusion test). The harness loads labels only in the event-matching stage after all arms have run; `TEST-CAUSAL-1` on the harness proves it (`causality-tests.md` §1.1, added at review).
- The diagnostic direct path is subject to the same rule and tests.

**Conclusion:** causal; one implicit boundary made explicit, no contract changed.

## 4. Tests

| Test id | What it checks | Result | Where run |
|---|---|---|---|
| `TEST-SCHEMA-1` (`tests/contracts/`, 99 cases: 77 record + 22 config) | Every schema valid Draft 2020-12; `$ref` resolution; valid examples accepted; each required field enforced; unknown fields rejected; `t_capture` absent/non-numeric rejected; pinned `schema_version`; semantic conditionals (status/source/kind/derivation nullability, `source↔arm`, 21 landmarks, 2-D points, closed `hand_id`, sparse offsets, `DirectPrediction` rules); stream-header units pinned; config example accepted and every negative config case rejected | **99 passed** | HW-01, `.venv` Python 3.11.9, pytest 9.1.1, 2026-09-21 |
| `scripts/validate_contracts.py` (204 checks) | Standalone equivalent for gate reviewers | **RESULT: PASS** | same |
| `ruff check .` (whole repository, `.venv` excluded) | Lint of all Python files | **All checks passed** | same |
| ENV-SMOKE (`scripts/env_smoke.py`, Phase 00) | Regression: environment still imports; experiment-log schema still validates | **RESULT: PASS** | same |
| `TEST-CAUSAL-1/2`, `TEST-PARITY-1`, `TEST-CONFORM-1…7` | specified only | not executable yet (no components exist) | — |

Submission-time figures (2026-09-20): 90 passed / 183 checks — superseded by the above after the review corrections.

## 5. Measurements produced in this phase

None — this phase produces no measurements. The only numbers in the artefacts are: quoted discovery values, frame-period arithmetic labelled *arithmetic, not a measurement*, `# candidate` config placeholders, *candidate* test tolerances (fixed by Phases 09/10), and test counts.

## 6. Integrity checklist

| # | Item | YES / NO / N/A | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled | YES | §5. `native_fps_measured` is schema-forced to `null` or `{value, run_id, method}`. |
| I-2 | No implementation claim without tests | YES | Only schemas, example config, `validate_contracts.py` and `tests/contracts/` are called IMPLEMENTED; they are their own tests (99 pass). Every module PLANNED; `src/spacedrums/` has no code. |
| I-3 | No causal component consumes future frames | N/A (no code) | Tests fully specified; non-causal artefact boundary explicit (§3.4). |
| I-4 | No fabricated data | YES | Examples named `*.valid.example.json`, placeholder ids, zero hashes, described as synthetic; no recording/participant/label/result exists. |
| I-5 | FPS reported as native only | N/A / YES by construction | No FPS figure exists; a measured value cannot be stored without its `run_id`. |
| I-6 | No "latency reduced" claim | YES | Grep of all Phase 01 documents: only "monotonicity guarantees", "structural guarantees", "never reduced to a bare classifier". `_est` labelling rule now explicit. |
| I-7 | Marker condition labelled | N/A (no results) | `tip_method` carried on `StickObservation` and `TrackState`; `MARKER` documented as fallback/benchmark only. |
| I-8 | Participant-level split confirmed | N/A | No ML. |
| I-9 | Scope respected | YES | `grep -r OOS-REF` → reserved hooks only (schemas, config comment, tests, ADR-0011, architecture §16, RTM); `FOOT` rejected by schema; no MIDI/cloud/IMU/ESP32/depth element. |
| I-10 | Status vocabulary correct | YES | Phase document `## Status` = IMPLEMENTED (specification-only); each artefact labelled; RTM rows PLANNED with evidence pointers only (advanced by the owner's signature, not before). |
| I-11 | Reproducibility fields complete | N/A | No runs. Test results cite hardware id, interpreter, date; `git_sha` = owner's commit (follow-up F-1). |
| I-12 | Limitations stated | YES | `architecture.md` §15; `causality-tests.md` §7; `contracts.md` §6, §9; §8 below. |

## 7. Deviations from the phase document (D = review correction; S = submission deviation)

| Id | What | Why | Impact on dependents |
|---|---|---|---|
| **D-1** | Added `StrikeCandidate.derivation` / `CommittedStrike.derivation` (`GEOMETRY` \| `DIRECT_HEAD`), diagnostic-only record `DirectPrediction` + `DirectAnticipator` protocol, ADR-0007 amendment, ADR-0008 note. | Phase 09 Task 09.8 "direct" mode and Phase 19 AB-NOTRAJ were not representable under the submitted contract (criterion 7). | Phase 09/19 have a labelled path; Phase 13 must refuse direct-only models (`TEST-CONFORM-3`); live contract unchanged (`positions` still required). |
| **D-2** | Estimated-vs-measured audio-out labelling rule (`contracts.md` §3.10, `architecture.md` §5.4). | Implicit rule could have let `L_sys` be computed from `t_audio_out_est`. | Phase 05/09/18 name estimate-derived quantities with `_est`. |
| **D-3** | `has_phys_gt` three-level invariant; reserved `SessionMetadata.segments[]`, `audio_alignment_residual_s`, `capture_stats`. | Physical GT varies within a session. | Phase 06 schema must include them; Phase 07 per-strike rule unchanged. |
| **D-4** | `source ↔ arm` invariant on `CommittedStrike`. | Two attribution fields without a stated relation. | None beyond validation. |
| **D-5** | `TrajectoryPrediction.t_offsets_s` (nullable). | Sparse GBDT horizons must not be interpolated and presented as prediction. | Phase 04 geometry intersects the polyline as given; Phase 09 adapter sets offsets. |
| **D-6** | Conformance ids renumbered `TEST-CONFORM-1…7`; `ReferenceTrack` reserved; `causality-tests.md` §1.1 added; counts/cross-references updated. | Naming rule `TEST-<AREA>-<N>`; explicit non-causal boundary. | None. |
| S-1 | Phase 01 was executed while the Phase 00 gate verdict is unsigned (started on explicit owner instruction, 2026-09-20). Phase 00 condition C-2 half-closed (commit exists, tag `gate-00-pass` does not). | Owner decision. | None on content; owner signs Phase 00 record before or with this one (F-2). |
| S-2 | Field additions beyond the phase document (listed and audited in §3.1). | Required by other stated requirements. | No field removed or renamed. |
| S-3 | `RecordStreamHeader` record type added. | Units flag + provenance for record/replay symmetry. | Phase 05/06 write it as line 1 of each JSONL stream. |
| S-4 | `has_phys_gt` on `SessionMetadata` rather than `FrameSample`. | Per-session/segment condition (§3.2). | Phase 06. |
| S-5 | Interfaces as `Protocol` signatures in the spec, not code; `pyproject.toml` tool-config only; layout amended by ADR-0010/0012. | "No functional code" rule; `repo-layout.md` §4 scheduled `pyproject.toml` for Phase 01. | Phase 02 creates the code from §11 verbatim. |
| S-6 | A cosmetic `ruff format` change to `scripts/env_smoke.py` (Phase 00 file) was reverted. | Keep Phase 00's committed state intact. | None. |

## 8. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase / owner |
|---|---|---|
| Threading vs multiprocessing; cross-process clock consistency | Pending Benchmark | Phase 16 (ADR-0009 supersession) |
| Whether `DEGRADED` commits should ever be allowed | To Be Experimentally Determined | Phase 05/17 |
| Per-step uncertainty in `TrajectoryPrediction` in V1 | Open Question (field reserved, nullable) | Phase 12 |
| `Δ_proc` policy for replayed commit decisions (`TEST-PARITY-1`) | Pending Architecture Decision | Phase 09 define, Phase 13 validate |
| Test tolerances for non-deterministic model paths (candidates `1e-6` / `1e-5`) | candidate | Phase 10 fixes before runs |
| Lossless vs lossy recording codec | Pending Architecture Decision | Phase 06 |
| Latency-slot targets | To Be Experimentally Determined | Phase 16 |
| Concrete `t_mono` function (`perf_counter` candidate) | candidate | Phase 02 (ADR-0004 amendment if changed) |
| Filter family, tip method, model family, thresholds | not chosen (interfaces only) | 03, 03, 10–13, 05/09/18 |
| Phase 13 document writes `fallback.budget_ms`; the config schema uses seconds (`budget_s`, no `_ms` keys) | naming heads-up | Phase 13 conforms to the schema |
| Phase 00 carried items (ethics approval, dataset release, Python minor version, hash-pinned locks, 7th zone, equipment, clean-machine re-install) | as in `phase-00-gate.md` §7 | unchanged; ethics/version questions were due "before the Phase 01 gate" and are **still open** (owner) |

## 9. Follow-up obligations (not conditions on this phase's criteria)

| Id | Obligation | Owner | By |
|---|---|---|---|
| F-1 | Commit the Phase 01 artefacts and tag `gate-01-pass` after signing (dirty tree at review). | Project owner | Phase 02 start |
| F-2 | Sign the **Phase 00** gate record and tag `gate-00-pass` (or record FAIL); answer Phase 00 C-3 (ethics/dataset release) and OQ-ENV-1/2 — overdue since this gate. | Project owner (+ supervisor for ethics) | Ethics before any recording; version before Phase 06 |
| F-3 | Phase 02 adds `import-linter` to `requirements.in`/`.lock` and commits the `.importlinter` contract from `architecture.md` §2.4 with its first module. | Phase 02 submitter | Phase 02 gate |
| F-4 | Phase 13 loader refuses direct-only model packages; Phase 09/19 label every `DIRECT_HEAD` result *direct / no-trajectory (diagnostic)*. | Phase 09/13/19 submitters | Their gates |

## 10. Reviewer statement

Review performed 2026-09-21 by Claude on the project owner's explicit instruction ("Perform a final Phase 01 gate review only"), scope §11. Inspected: `project-discovery.md` Q1–Q60 and closing sections against every Phase 01 artefact for the eleven contradiction classes in §2.1; the Phase 00 RTM, out-of-scope register, reproducibility policy, repo layout and ADR-0001…0003; the roadmap README §5–§10 and Phases 02–19 for expectations on Phase 01 contracts. Ran: `pytest` (99 passed), `scripts/validate_contracts.py` (PASS, 204 checks), `ruff check .` (clean), `scripts/env_smoke.py` (PASS), I-6 keyword grep, relative-link check (0 broken). Not verified: nothing was executed against a camera, audio device or data — none exists in this phase.

Verdict **PASS**, effective on the owner's signature (gate-procedure §4).

Signed (owner): ____________________, YYYY-MM-DD

## 11. Review scope as instructed by the owner (2026-09-21)

1. Criterion 7 verified explicitly against `project-discovery.md`, Phase 00 requirements, Phase 00 ADRs and core decisions for: software-only/webcam-first; markerless hand + stick tracking; trajectory-first; causal runtime; offline future-aware labelling forbidden at runtime; virtual drum geometry; impact definition; latency terminology; physical ground-truth scope; MVP/V1 zone scope; offline/local execution → §2.1.
2. Every schema addition audited (why / semantic change / ambiguity / Phase 00 contradiction / necessity) → §3.1.
3. `has_phys_gt` audited → §3.2.
4. Timing semantics audited → §3.3.
5. Causality verified → §3.4.
6. `pytest`, `validate_contracts.py`, `ruff check .` run → §4.
7. Gate record updated → this file.
8. Verdict set → PASS. No commit, no tag, Phase 02 not started.
