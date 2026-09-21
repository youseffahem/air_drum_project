# Phase 06 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 06 — Data Collection Pipeline |
| Phase document | `phases/phase-06-data-collection.md` |
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-21/22 |
| Reviewer(s) | Project owner — review pending |
| Review date | 2026-09-22 (submission) |
| Code state | Phase 06 tree committed by the owner as **`b8642764f0216e250b1855981034c4650b0c9f94`** ("phase 6", on top of `483f58bc…`). Development runs were taken on the dirty tree at `483f58bc…`; **all three cited runs were repeated on the clean tree at `b864276…` with `git_dirty: false` (C-06-6, §3a) and their decision-level artefacts are identical.** Tag `gate-06-pass` not created (owner; verdict pending). |
| **Verdict** | **PROPOSED PASS-WITH-CONDITIONS — owner verdict pending.** The machinery of Tasks 06.1–06.9 is IMPLEMENTED with tests (532 passed project-wide; 47 new), validated end to end on SYNTHETIC input and on an existing DEV CAPTURE (real frames), and documented. Tasks 06.10 (pilot) and 06.11 (campaign) are **NOT performed**: no person was at the camera, no new recording was made (owner decision; ethics question still open). Acceptance criteria **2, 3 (partly), 4 and 5** are therefore **NOT MET / PENDING** as measurements; criterion 1 is MET. Whether "PASS-WITH-CONDITIONS" is acceptable for a phase whose *Definition of Done* is a completed campaign is the owner's call: the honest reading is that Phase 06 is **half a phase** — the pipeline exists and is verified on non-participant input, the dataset does not exist. The phase document's Fallback Strategy ("if fewer than the target participants are available, proceed with what exists and document") does not cover zero participants; the submitter proposes conditions C-06-1…C-06-5 (C-06-6 closed) and does **not** claim the phase is Done. |

**Dependency note.** Phase 05's gate proposes PASS-WITH-CONDITIONS with C-05-1…C-05-4 still open (live playability, live induced-loss test, `L_sys_est`, tuning session) and Phase 04's proposes FAIL (audio-output latency). Phase 06 was executed on the owner's instruction. None of those conditions is reinterpreted here: the candidate config recorded in every Phase 06 session is still the untuned Phase 05 candidate, and no audio-latency value appears anywhere.

## 1. Artefacts produced

| Artefact (from phase document) | Path | Status label | Present? |
|---|---|---|---|
| Recording tool (`recorder` + guided-protocol UI: segment markers, cues, countdown, metadata prompts, file naming, post-segment quick check) | `src/spacedrums/data/recorder.py` (hooks), `scripts/record_session.py` (composition with `spacedrums.app.main`; `--live` PERSON-DEPENDENT, `--synthetic`, `--devcapture`), `spacedrums.app.main` hooks (`source_factory`, `draw_hook`, `on_key`, `--regenerated`, live `capture_stats`) | IMPLEMENTED; live run with a person PENDING | yes |
| Recording Protocol document + cue definitions | `docs/protocols/recording-protocol.md` (v0.1-draft), `src/spacedrums/data/protocol.py` (`SegmentType`, `SegmentSpec`, `build_protocol`, seeded zone order, `check_segment_markers`) | IMPLEMENTED (draft); **v1.0 freeze PENDING** (needs the pilot) | yes |
| Session Metadata schema + validator | `schemas/session-metadata.schema.json` (1.0), `src/spacedrums/data/metadata.py`; example `schemas/examples/session-metadata.valid.example.json` (SYNTHETIC) | IMPLEMENTED | yes |
| Storage layout, naming, checksums, manifest builder | `src/spacedrums/data/manifest.py`, `scripts/build_raw_manifest.py` (build / check / withdraw), `schemas/raw-manifest.schema.json`, `data/manifests/README.md` (+ `.gitignore` exception), ADR-0019 §3 | IMPLEMENTED; **`ds-raw-v0.x-pilot` and `ds-raw-v1.0` do not exist** (no sessions) | yes (builder) / **no** (manifests) |
| Unusable-recording policy + exclusion log format | `docs/policies/unusable-recording-policy.md`, `schemas/exclusion-record.schema.json`, `validation.exclusion_record` / `write_exclusions`, `<version>.exclusions.jsonl` | IMPLEMENTED; thresholds candidates; applied to SYNTHETIC / DEV CAPTURE only | yes |
| Session verification script | `src/spacedrums/data/validation.py`, `scripts/verify_session.py`, `schemas/session-verification.schema.json` | IMPLEMENTED | yes |
| Setup checklist + participant instructions | `docs/protocols/operator-checklist.md`, `docs/protocols/participant-instructions.md`, `scripts/session_checklist.py` | IMPLEMENTED (drafts); signed checklist per session PENDING | yes |
| Pad + microphone capture (ADR-0002) | `src/spacedrums/data/audio_capture.py` (`AudioCapture` on `t_mono`, `detect_onsets`, `sync_check`) | IMPLEMENTED; feasibility / sync residual **Pending Benchmark** (pilot); no pad or microphone inventoried | yes |
| Raw video retention ADR + storage estimate + re-track check | `docs/decisions/ADR-0019-raw-retention-storage-versioning.md`; `scripts/regenerate_session.py` | Proposed; storage **DEV CAPTURE estimate**; re-track **DEV CAPTURE DECISION-IDENTICAL** | yes |
| Pilot report | `docs/reports/phase-06-pilot.md` | **PENDING** (machinery validation only) | yes (template + machinery evidence) |
| Campaign report | `docs/reports/phase-06-campaign.md` | **PENDING** (template; no counts) | yes (template) |
| Participant recordings, pad+mic subset | `data/raw/P*/` | **PENDING — none exist** | **no** |
| Gate record | `docs/gates/phase-06-gate.md` | IMPLEMENTED; reviewer decision PENDING | yes |

Not built, by the phase document's "What Must NOT Be Done Yet": no labels, no train/val/test split files, no feature statistics, no dataset release (Phase 07+).

## 2. Acceptance criteria

| # | Criterion (verbatim from phase document) | Evidence (file / test id / run id) | Status |
|---|---|---|---|
| 1 | Recording tool, metadata schema, verification script, and manifest builder implemented and tested. | `tests/data/` (TEST-DATA-1…6, 40 tests), `tests/scripts/test_phase06_scripts.py` (TEST-SCRIPTS-3, 7 tests), `tests/contracts` (dataset schemas), `scripts/validate_contracts.py`; runs `20260922-0040-p06-record-synthetic` (SYNTHETIC, ACCEPT), `20260922-0041-p06-record-devcapture` (DEV CAPTURE ingest, integrity PASS), `20260922-0041-p06-regenerate-session` (DECISION-IDENTICAL) | **MET** (VERIFIED on SYNTHETIC input and on a replayed DEV CAPTURE; a live session with a person PENDING) |
| 2 | Protocol v1.0 frozen after a pilot; participant instruction sheet and operator checklist exist. | Protocol **v0.1-draft** (`recording-protocol.md`, `protocol.py`); instruction sheet and checklist exist as drafts; **no pilot** | **PARTIAL** — documents exist; **v1.0 freeze NOT MET / PENDING** (C-06-1) |
| 3 | Unusable-recording policy documented and applied; exclusion log exists. | `docs/policies/unusable-recording-policy.md`; applied by `verify_session` to the SYNTHETIC session (0 exclusions; ACCEPT) and the DEV CAPTURE ingest (9 segment exclusions, `LOW_TRACKING_VALIDITY`, REVIEW); log format `exclusion-record` + `<version>.exclusions.jsonl` (self-test manifests in tests); `data/raw/exclusions.jsonl` for real sessions does not exist | **PARTIAL** — documented and applied to SYNTHETIC / DEV CAPTURE only; thresholds candidates; application to pilot / participant sessions PENDING (C-06-2) |
| 4 | Pad+mic condition go/no-go recorded with measured sync residual. | Machinery: `audio_capture.py`, `sync_check`, SYNTHETIC click-track path in `record_session.py --synthetic --pad-zone` (2/2 markers, spread 8.5e-14 s — generated clicks, not a microphone); no pad, no microphone, no pilot | **NOT MET / PENDING** (C-06-3) |
| 5 | Campaign completed with actual counts reported; `ds-raw-v1.0` manifest with hashes; all sessions schema-valid; consent records complete. | No participant recorded; `ds-raw-v1.0` refused/absent by construction; campaign report is a template with every count PENDING | **NOT MET / PENDING** (C-06-4) |

## 3. Tests

All commands ran on HW-01, 2026-09-21/22, `.venv` Python 3.11.9, dirty tree on `483f58bc…` (development); the reruns of §3a were taken on the clean committed tree `b864276…`.

| Test id / command | What it checks | Result |
|---|---|---|
| `.venv\Scripts\python.exe -m pytest tests/data tests/scripts/test_phase06_scripts.py tests/contracts -o addopts="" -q --strict-markers` | Phase 06 focused suite: TEST-DATA-1 protocol (vocabulary, seeded order, PAD invariants, marker integrity), TEST-DATA-2 metadata (kinds, promotion refusal, consent gating, `has_phys_gt`, re-takes, round trip), TEST-DATA-3 recorder hooks (half-open contiguous markers, keys, quick check, determinism, cues), TEST-DATA-4 audio capture (t_mono mapping, WAV, onsets, sync, determinism), TEST-DATA-5 verification (intact ACCEPT; missing image / config tamper / frame order / malformed record / dangling id / forged kind → caught; policy thresholds → exclusions + quarantine; determinism), TEST-DATA-6 manifests (hashing, ordering, kind gating, refusal, tamper, withdrawal, empty refusal), TEST-SCRIPTS-3 (scripts in SYNTHETIC / DEV CAPTURE modes; `--live` refuses without `--kind`), TEST-SCHEMA-1 + dataset schemas | PASS — 192 passed in 108 s |
| `.venv\Scripts\python.exe -m pytest -o addopts="" --strict-markers -q` | Project-wide regression suite | PASS — **532 passed, 1 skipped** in 232 s (skip = opt-in webcam hardware test; 485 at the Phase 05 gate) |
| `.venv\Scripts\ruff.exe check .` | Lint | PASS — All checks passed |
| `.venv\Scripts\lint-imports.exe --config .importlinter` | Layer contract (`spacedrums.data` now populated, below `app`, imports nothing from `app`/`ui`) | PASS — 6 contracts kept, 0 broken |
| `.venv\Scripts\python.exe scripts\validate_contracts.py` | Record schemas + the four Phase 06 dataset schemas (examples accepted; required fields / unknown field rejected; SYNTHETIC document relabelled PARTICIPANT / given a pseudonym / a participant dataset version rejected) | PASS — `RESULT: PASS` |
| `.venv\Scripts\python.exe scripts\env_smoke.py` | Environment + experiment-log schema | PASS |
| `.venv\Scripts\python.exe scripts\fetch_hand_landmarker_model.py --verify` | Model asset hash | PASS — `sha256:fbc2a300…07cde1`, 7,819,105 bytes |
| `.venv\Scripts\python.exe scripts\fetch_drum_samples.py --verify` | Seven sample hashes | PASS — 7/7 OK |
| `git add -N . && git diff --check` (then `git reset`) | Whitespace / CRLF in tracked and untracked changes | PASS — exit 0 (new files LF; the three CRLF-in-HEAD files untouched) |
| `tests/data/test_recorder.py::test_recorder_is_deterministic…`, `tests/data/test_validation.py::test_verification_is_deterministic`, `tests/data/test_manifest.py::test_tamper_detection_and_hash_determinism`, `tests/data/test_audio_capture.py::test_synthetic_pipeline_is_deterministic` | Deterministic generation / validation / hashing | PASS |
| `scripts/regenerate_session.py data/raw/DEV/dev-p06-ingest-exp-5` (run `20260922-0041-p06-regenerate-session`) | Re-track from raw frames vs recorded derived records (Task 06.3; replay determinism of the causal pipeline on real frames) | **DECISION-IDENTICAL** (max numeric noise 1.1e-14; not bit-exact across processes — ADR-0019 §1) |
| Causality (`TEST-CAUSAL-1/2` tracker, anticipator, commit policy — Phases 03/05) | unchanged, re-run in the full suite | PASS |
| Leakage / split tests | **N/A** — no splits in Phase 06 (Phase 07); the structural kind gating (metadata schema + manifest admission) is the Phase 06 counterpart | tested (TEST-DATA-2/6) |

Line endings: new files are LF; `src/spacedrums/app/main.py` (LF in HEAD) received LF edits.

### 3a. Clean-tree reruns (condition C-06-6) — 2026-09-22, HW-01, commit `b8642764f0216e250b1855981034c4650b0c9f94`

| Rerun (run_id) | Command | `git_sha` / `git_dirty` | Result vs the dirty-tree run |
|---|---|---|---|
| `20260922-0040-p06-record-synthetic` | `scripts/record_session.py --synthetic --pad-zone snare --verify --duration-scale 0.1 --slug protocol-selftest` | `b864276…` / **false** | COMPLETED; 1131 frames, 25 takes, verify ACCEPT, 0 commits on non-VALID frames, sync 2/2; checks, per-take verdicts and event counts identical to `20260921-2351-p06-record-synthetic` |
| `20260922-0041-p06-record-devcapture` | `scripts/record_session.py --devcapture swing-L2-exp-5 --verify --duration-scale 0.02 --slug p06-ingest-exp-5` | `b864276…` / **false** | COMPLETED; 171 frames, 20 takes, verify REVIEW (9/20 core takes `LOW_TRACKING_VALIDITY`), 0 non-VALID commits; checks, per-take verdicts and event counts identical to `20260921-2352-p06-record-devcapture` (the earlier session directory is kept aside as `dev-p06-ingest-exp-5.dirty-483f58b`) |
| `20260922-0041-p06-regenerate-session` | `scripts/regenerate_session.py data/raw/DEV/dev-p06-ingest-exp-5` | `b864276…` / **false** | COMPLETED; DECISION-IDENTICAL, max \|Δ\| 1.12e-14 — identical verdict and deviation |

Every `run.json` validates against `schemas/experiment-log.schema.json` with `status: COMPLETED`, `phase: "06"`, the committed SHA and `git_dirty: false`. No recording was made: the reruns re-generate the SYNTHETIC session and re-process the existing git-ignored Phase 02 developer capture. Integrity item I-11 is therefore **YES** for the cited runs (§5 updated).

## 4. Measurements produced in this phase

Every cited run below is the clean-tree rerun on `b864276…` (`git_dirty: false`, §3a). Their labels (SYNTHETIC / DEV CAPTURE / PENDING) are unchanged: a clean tree makes them citable, not validated.

| Quantity | Label | Value | run_id / test | Method | Hardware id |
|---|---|---|---|---|---|
| Full-protocol SYNTHETIC session: frames, takes, verdict, safety count | SYNTHETIC | 1131 frames, 25 takes (24 core/variation + pad), verify ACCEPT, 0 commits on non-VALID frames, sync 2/2 | `20260922-0040-p06-record-synthetic` | `record_session.py --synthetic --pad-zone snare --verify --duration-scale 0.1` | HW-01 |
| DEV CAPTURE ingest: integrity checks, delivered FPS, drops, stalls, segment exclusions | DEV CAPTURE (replay of the Phase 02 capture; no new recording) | all hard checks PASS; 29.93 FPS delivered vs 30 requested (0.2 %); 1 drop; 0 stalls; 9/20 core takes excluded (one-hand capture) → REVIEW; 2 reactive commits (same as Phase 05) | `20260922-0041-p06-record-devcapture` | `record_session.py --devcapture swing-L2-exp-5 --verify --duration-scale 0.02` | HW-01 |
| Storage per frame (PNG level 1, 640×480 real frames, L2) | DEV CAPTURE **estimate** | 414,715 bytes/frame → ≈ 0.75 GB/min at 30 FPS (arithmetic) | same run, `verify.json → quality.storage` | file sizes | HW-01 |
| Regeneration vs recording | DEV CAPTURE | DECISION-IDENTICAL; max |Δ| 1.12e-14; HandObservation bit-identical | `20260922-0041-p06-regenerate-session` | `regenerate_session.py` | HW-01 |
| Session length, storage per real session, validity-ratio distribution, `q_seg`/`q_sess`, sync residual, pad go/no-go, participants / sessions / segments / minutes | **PENDING** | none | — | need a pilot / campaign | — |

## 5. Integrity checklist

| # | Item | Result | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled | YES | every number in this record, the reports, the ADR and the protocol is labelled SYNTHETIC / DEV CAPTURE / candidate / arithmetic / PENDING |
| I-2 | No implementation claim without tests | YES | §3; every Phase 06 module and script has tests |
| I-3 | No causal component consumes future frames | YES | no new causal component; the recorder consumes the pipeline's per-frame results only; markers are placed on the current frame's `t_capture`; re-track uses the same pipeline (`TEST-CAUSAL` suites unchanged) |
| I-4 | No fabricated data | YES | no recording made; synthetic sessions carry `synthetic-` ids, `session_kind = SYNTHETIC`, `participant_id = SYNTHETIC`; schema + manifest rules refuse relabelling; participant counts are PENDING everywhere |
| I-5 | FPS reported as native only | YES | delivered FPS from `t_capture` intervals (Phase 02 method); the profile value is labelled "REQUESTED mode (no measured native FPS in the profile)" when no measurement is cited |
| I-6 | No "latency reduced" claim | YES | none |
| I-7 | Marker condition labelled | N/A / YES | `tip_method_condition` field enforced by the schema; all sessions `MARKERLESS` |
| I-8 | Participant-level split | N/A | no splits (Phase 07); kind gating tested |
| I-9 | Scope respected | YES | no labels, no splits, no feature statistics, no release; `OOS-REF` unchanged |
| I-10 | Status vocabulary | YES | phase document `## Status` = IMPLEMENTED (machinery) / PENDING (pilot, campaign) |
| I-11 | Reproducibility fields complete | YES | every cited run is a clean-tree rerun on `b864276…` with `git_dirty: false`, schema-valid `run.json`, config snapshot and artefact hashes (§3a; C-06-6 closed) |
| I-12 | Limitations stated | YES | pilot report §6, campaign report §3, ADR-0019 risks, protocol §5 |

## 6. Deviations from the phase document

| What | Why | Impact on dependents |
|---|---|---|
| Tasks 06.10 and 06.11 not performed | No person at the camera; owner decision "no new recordings"; ethics Open Question | Criteria 2 (freeze), 4, 5 NOT MET; Phase 07 has no data; conditions C-06-1…C-06-4 |
| Protocol stays v0.1-draft | v1.0 requires the pilot | Phase 07 labelling rules key on `SegmentType`, which is stable; durations may change |
| `metadata.json` added next to Phase 05's `session.json` rather than replacing it | Phase 01 rule: never repurpose a field / file | architecture.md §12.2 amended (ADR-0019) |
| Regeneration compared with a numeric tolerance instead of bit-for-bit | perception stage is decision-deterministic but not bit-exact across processes (ADR-0019 §1) | Phase 13 `TEST-PARITY-1` must state a tolerance |
| `spacedrums.app.main` gained hooks (`source_factory`, `draw_hook`, `on_key`), `--regenerated`, live `capture_stats` | `data` sits below `app` in the layer contract, so the recorder cannot own the loop | additive; Phase 05 behaviour unchanged (full suite passes) |
| No annotation, labelling or split machinery | phase document "What Must NOT Be Done Yet" | Phase 07 |
| Storage estimate from one DEV CAPTURE instead of the pilot | no pilot | ADR-0019 labels it an estimate; pilot value PENDING |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase / owner |
|---|---|---|
| Ethics approval | Open Question | Owner (before any pilot) |
| Protocol v1.0: durations, counts, tempi | To Be Experimentally Determined | pilot (C-06-1) |
| `q_seg`, `q_sess`, FPS / drop / stall tolerances, sync tolerance | To Be Experimentally Determined | pilot (C-06-2) |
| Pad + microphone feasibility, equipment, subset size | Pending Benchmark / Open Question | pilot (C-06-3); `hardware-inventory.md` |
| Record-mode PNG write cost per frame | Pending Benchmark | pilot; Phase 16 |
| Active arm A only vs balanced A/B; taped-stick benchmark block; free play; 7th zone; final lighting set and room | Open Question | Owner before the freeze |
| Bit-reproducible perception stage (or tolerance policy) | Pending Architecture Decision | Phase 13 / 16 |
| Phase 04 criterion 6 (audio latency), Phase 05 C-05-1…C-05-4 | PENDING | unchanged |

## 8. Conditions (proposed PASS-WITH-CONDITIONS)

| Condition | Owner | Must be closed by |
|---|---|---|
| **C-06-1** Pilot (Task 06.10) with the developer and 1–2 volunteers after the ethics answer: run `scripts/record_session.py --live --kind PILOT …`, `session_checklist.py`, `verify_session.py`; measure session length, storage per session, tool stability, PNG write cost; fill `docs/reports/phase-06-pilot.md` §2–§5; freeze protocol v1.0 (`PROTOCOL_VERSION`, `recording-protocol.md` change log). Person-dependent. | Project owner (sessions) + submitter (tables, freeze) | before any participant session |
| **C-06-2** Set `q_seg`, `q_sess` and the tolerances from the pilot validity-ratio distribution; record them in `unusable-recording-policy.md` §2–§3 and as the default `VerifyThresholds`; apply the policy to every pilot session (`exclusions.jsonl` exists). | Submitter | with C-06-1 |
| **C-06-3** Pad + microphone go/no-go: inventory a pad and a microphone, record the pad block in the pilot with claps at start and end, report the clap-onset residual (`verify.json → sync`) in the pilot report; decide go / no-go. If no equipment: record "dropped" with the evidence; `t_impact_phys` stays PENDING. | Project owner + submitter | with C-06-1 |
| **C-06-4** Campaign (Task 06.11): record the participants under protocol v1.0, verify every session, build `ds-raw-v1.0` (+ pilot manifest if pilots consented), fill `docs/reports/phase-06-campaign.md` with MEASURED counts, confirm consent records. | Project owner + submitter | before Phase 07 labelling |
| **C-06-5** Owner decisions before the freeze: active arm policy, taped-stick block, free play, 7th zone, lighting set / room (protocol §5). | Project owner | before C-06-1 |
| **C-06-6** Clean-tree reruns of the cited runs (`p06-record-synthetic`, `p06-record-devcapture`, `p06-regenerate-session`) after the owner commits the Phase 06 tree; update run ids here and in the pilot report. | Submitter | **CLOSED 2026-09-22** — three reruns on `b864276…`, all `git_dirty: false`, schema-valid, decision-level artefacts identical (§3a); run ids updated in this record, the pilot report, ADR-0019, the policy and the phase status |

## 9. Reviewer statement

Submitter evidence assembly is complete. The project owner has not yet reviewed or signed this record, and the submitter does not claim authority to pass it. What was inspected/run by the submitter: every command in §3; the three SYNTHETIC / DEV CAPTURE runs in §4 and their artefacts; the regenerated dev session diff (record by record); the schema examples. What was **not** done: any session with a person, any pilot, any participant, any microphone or pad, any measurement of session length, storage of a real session, tracking validity of real participants, or sync accuracy. **There is no participant data and no dataset.** What was done after the commit: the three clean-tree reruns of §3a (C-06-6 closed 2026-09-22); no pilot, no participant, no recording. The honest proposed verdict is **PASS-WITH-CONDITIONS for the pipeline (criterion 1) with criteria 2–5 open under C-06-1…C-06-5, if the owner accepts a gate that passes machinery without the campaign; otherwise FAIL** (the Definition of Done — campaign report, `ds-raw-v1.0` — is not satisfied and cannot be satisfied without recording people). No Phase 07 work was started.

Signed: **PENDING — project owner**, 2026-09-22
