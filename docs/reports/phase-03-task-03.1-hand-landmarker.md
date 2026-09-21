# Phase 03 — Task 03.1 Evidence Note: Hand Landmark Estimator Wrapper

| Field | Value |
|---|---|
| Task | 03.1 — Hand Landmark Estimator Wrapper (`phases/phase-03-hand-stick-tracking.md`, Checkpoint 03.A) |
| Status | **IMPLEMENTED** (code + tests) · integration evidence **MEASURED** on two dev-capture runs · owner handedness check **CLOSED 2026-09-21** (§6, P-03.1-1) |
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-21 |
| Code state | Uncommitted working tree on `4dd0c2e` (owner rule: the assistant does not commit; runs below carry `git_dirty: true` and are development evidence — a clean-tree repeat is due at the Phase 03 gate, as Phase 02 did for its FPS cells) |
| Hardware | HW-01 (`docs/hardware-inventory.md`): Intel i7-7820HQ, 4C/8T, Windows 11 22621, on mains power; `cv2.getNumThreads() = 8` |
| Related | ADR-0014; `docs/architecture/contracts.md` §3.2; `docs/environment.md` §7; Phase 02 gate items F-3, C-5 |

## 1. What was built

| Artefact | Path | Tests |
|---|---|---|
| `HandObservation` record class (frozen, `to_dict`/`from_dict`, invariants mirroring the schema's `if present` rule) | `src/spacedrums/contracts/records.py` | `tests/contracts/test_record_classes.py` (7 cases + 12 invariant parametrisations; round-trips the Phase 01 example) |
| Coordinate boundary native → ROI-normalized (ROI or FULL detector input; one code path through `capture.roi.px_to_norm`) | `src/spacedrums/hands/coords.py` | `tests/hands/test_coords.py` (`TEST-HANDS-1`) |
| Estimator wrapper: backend Protocol, MediaPipe Tasks backend (lazy import), `detector_id`, per-frame `processing_s`, LEFT/RIGHT emission with collision/unknown counters, VIDEO-mode timestamps from `t_capture` | `src/spacedrums/hands/landmarker.py` | `tests/hands/test_landmarker.py` (`TEST-HANDS-2`, 17 cases, injected backend) |
| Model-asset resolution with SHA-256 re-verification at load | `src/spacedrums/hands/model_asset.py` | `tests/hands/test_landmarker_model.py` (`TEST-HANDS-3`, real model; skips with reason if the file is absent) |
| Model fetch + manifest (`assets/models/hand_landmarker.task`, 7 819 105 bytes, `sha256:fbc2a300…7cde1`, Apache-2.0, versioned URL `float16/1`) | `scripts/fetch_hand_landmarker_model.py`, `assets/models/manifest.json` | `--verify` → `RESULT: PASS` |
| Config schema 1.2: optional `hands` block; loader cross-field check; example + HW-01 fragment updated | `configs/schema/config.schema.json`, `src/spacedrums/config/loader.py`, `configs/*.yaml` | `tests/contracts/test_config_schema.py` (+3, 8 reject cases), `tests/config/test_loader.py` (+2) |
| Dev-capture replay reader (script helper) and the integration/measurement script | `scripts/_devcapture.py`, `scripts/hands_landmark_check.py` | `tests/scripts/test_measurement_scripts.py::test_hands_landmark_check_synthetic` (stub backend) |

Suite after the task: **250 passed, 1 skipped** (hardware capture test, opt-in), `ruff check .` clean, `lint-imports` 4 kept / 0 broken, `scripts/validate_contracts.py` PASS, `scripts/env_smoke.py` PASS. Run from both PowerShell and Git Bash.

## 2. Integration evidence on dev captures (MEASURED)

Method: `scripts/hands_landmark_check.py --capture swing-L2-exp-{5,6,7}` replays the Phase 02 Task 02.5 developer captures (person = the owner; **not** dataset recordings; L2 lighting; DSHOW 640×480; ROI `[40, 20, 560, 440]` → 560×440 crop fed to the estimator) with their recorded `t_capture`, `timestamp_source = REPLAY`. Every emitted `HandObservation` (2 per frame) is validated against `hand-observation.schema.json` and written to the run directory. Config: `hands` block of `configs/example.candidate.yaml` merged with the HW-01 fragment (`num_hands 2`, thresholds 0.5/0.5/0.5, `input ROI`, `swap_handedness false`); two runs differ only in `running_mode`.

| Run id | Mode | `detector_id` | config_hash |
|---|---|---|---|
| `20260921-1003-p03-hands-check-video` | VIDEO | `mediapipe-hand-landmarker@1.0.1:fbc2a30080c3:video:nh2:d0.50:p0.50:t0.50:roi:swap0` | `sha256:109a597a0491d2e1b…` |
| `20260921-1004-p03-hands-check-image` | IMAGE | `…:image:nh2:d0.50:p0.50:t0.50:roi:swap0` | `sha256:54e52de4f993fd648…` |

### 2.1 Landmark presence per capture (N **reported, not targeted**)

| Capture (exposure, L2) | Mode | Frames | LEFT present | RIGHT present | **Both present** | Any | Detections/frame 0 / 1 / 2 | Label collisions | Schema-valid |
|---|---|---|---|---|---|---|---|---|---|
| exp-5 (MANUAL −5) | VIDEO | 171 | 105 | 164 | **99** | 170 | 1 / 67 / 103 | 4 | 342/342 |
| exp-5 (MANUAL −5) | IMAGE | 171 | 103 | 120 | **69** | 154 | 17 / 71 / 83 | 14 | 342/342 |
| exp-6 (MANUAL −6) | VIDEO | 171 | 23 | 99 | **10** | 112 | 59 / 80 / 32 | 22 | 342/342 |
| exp-6 (MANUAL −6) | IMAGE | 171 | 38 | 67 | **2** | 103 | 68 / 95 / 8 | 6 | 342/342 |
| exp-7 (MANUAL −7) | VIDEO | 172 | 0 | 0 | **0** | 0 | 172 / 0 / 0 | 0 | 344/344 |
| exp-7 (MANUAL −7) | IMAGE | 172 | 0 | 0 | **0** | 0 | 172 / 0 / 0 | 0 | 344/344 |

Unknown labels: 0 in every run. Timestamp bumps: 0 (recorded `t_capture` never repeated a millisecond). Overlay frames (`overlay.<capture>.frame*.png` in each run directory) show the landmarks on the hands in full-frame pixels — the ROI-normalized → pixel round trip is visually confirmed for exp-5 frame 2 and exp-6 frame 13.

### 2.2 Per-frame processing time of the estimator call (MEASURED, ms, wall-clock around the backend call; 560×440 input; HW-01)

| Capture | Mode | p50 | p95 | max | mean | p50 / p95 excluding first 5 frames |
|---|---|---|---|---|---|---|
| exp-5 | VIDEO | 33.8 | 54.6 | 77.5 | 36.9 | 33.3 / 54.6 |
| exp-5 | IMAGE | 46.9 | 71.6 | 102.9 | 49.0 | 46.6 / 71.7 |
| exp-6 | VIDEO | 43.3 | 60.1 | 92.3 | 42.6 | 43.4 / 60.2 |
| exp-6 | IMAGE | 50.1 | 73.6 | 93.0 | 51.2 | 50.6 / 73.7 |
| exp-7 (no hands) | VIDEO | 30.4 | 49.2 | 59.6 | 30.3 | 30.4 / 49.2 |
| exp-7 (no hands) | IMAGE | 32.3 | 55.8 | 126.6 | 33.6 | 32.2 / 55.9 |

Reading: the estimator alone takes about one 30 FPS frame period (33.3 ms, arithmetic) per frame on HW-01 in VIDEO mode and ~1.4× that in IMAGE mode. This is the `hands` slot of architecture.md §8 for this configuration; Task 03.14 measures it again with the full stage chain, and Phase 16 owns the budget. No "real-time" claim is made here.

### 2.3 Findings that answer questions in the phase document

| Question / item | Finding | Evidence |
|---|---|---|
| Open Question: "Are landmark visibility scores available from the chosen estimator?" | **No.** `visibility`/`presence` are `None` on every landmark; `landmark_visibility` is `null` in every record. Task 03.7 must derive confidence otherwise (e.g. from `handedness_score`, bbox stability, axis confidence). | `visibility_frames = 0` over 514 frames in both runs |
| "Expose model complexity … via config" | The Tasks API has no complexity parameter; the model file (`hands.model_asset_id`) is the only model-level choice. Confidence thresholds and running mode are exposed. | ADR-0014 §Decision 3 |
| Which image side each raw label lands on | Well-exposed capture: `RIGHT` mean wrist x ≈ 0.38 (image-left), `LEFT` ≈ 0.66 (image-right). In the dark capture both labels drift to the image-left side (0.42 / 0.35): raw labels are unstable when detection is marginal. | `mean_wrist_x_roi_norm` in both `run.json` |
| Exposure vs. presence (feeds Phase 02 F-3 / C-5 and Task 03.11) | At L2 on HW-01, manual exposure −5 keeps both hands detectable in 99/171 frames; −6 drops to 10/171 with 59 empty frames; −7 gives no detection at all. The exposure that maximised the sensor's unique-frame rate in Phase 02 is not the one that keeps hands detectable. | §2.1 |
| VIDEO vs IMAGE running mode (candidates) | On these captures VIDEO gives more frames with both hands (99 vs 69 at −5) and is faster (p50 33.8 vs 46.9 ms). Not a decision yet: three captures, one lighting condition, one person. | §2.1–2.2 |

## 3. Acceptance evaluation against the task's evidence requirement

Task 03.1 evidence requirement: *"Integration test on a dev capture: landmarks present for both hands in ≥ N frames (N reported, not targeted); schema validation; per-frame processing time logged."*

| Requirement | Result |
|---|---|
| Integration test on a dev capture | Done on three captures × two running modes (§2); reproducible via `tests/hands/test_landmarker_model.py::test_dev_capture_integration_via_script` when the capture is present |
| Landmarks present for both hands in ≥ N frames, N reported | **N = 99 / 171** (exp-5, VIDEO); full table in §2.1; no target was set or implied |
| Schema validation | 2 056 / 2 056 `HandObservation` records valid across both runs (`schema_valid_all: true` per capture); record class round-trips the Phase 01 example |
| Per-frame processing time logged | `per_frame.<capture>.json` per run + p50/p95/max/mean in `run.json` (§2.2) |
| Contract: ROI-normalized y-down coordinates at the `hands` boundary | `TEST-HANDS-1`; overlay round-trip check |
| Contract: `detector_id` and version recorded | `detector_id` embeds library version, model hash prefix and every parameter; `run.json.metrics.detector` carries the full model entry |
| Config exposure of parameters | `hands` block, schema 1.2, cross-field check, example + fragment |

**Task verdict proposed to the owner: Task 03.1 complete (IMPLEMENTED; evidence MEASURED on development runs).** Task 03.2 may start. Not a phase gate: Phase 03's Exit Gate is at Task 03.15.

## 4. Integrity checklist items touched by this task

| # | Item | Answer | Pointer |
|---|---|---|---|
| I-1 | Numbers labelled | YES | every number above is MEASURED with run id, or arithmetic/candidate and says so |
| I-2 | No IMPLEMENTED without tests | YES | §1 table; 250 passed |
| I-3 | No future frames | YES (per-frame stage) | VIDEO mode uses the estimator's previous-frame ROI only; timestamps derive from the current frame's `t_capture`; no buffer of later frames exists; `TEST-CAUSAL-1/2` apply from Task 03.12 |
| I-4 | No fabricated data | YES | dev captures are the owner's Phase 02 developer captures (`purpose` field says so); synthetic self-test labelled SYNTHETIC in `run.json.description` and slug |
| I-5 | FPS native only | N/A | no FPS figure produced |
| I-7 | Marker condition labelled | N/A | no marker |
| I-9 | Scope respected | YES | hands only; no stick, tracking, zones or audio code; `LEFT_FOOT` remains a rejected value (test) |
| I-10 | Status vocabulary | YES | phase document `## Status` updated to *In progress* with this task IMPLEMENTED; RTM untouched until the gate |
| I-11 | Reproducibility fields | PARTIAL | both `run.json` validate, config snapshots and hashes present; `git_dirty: true` by construction (owner does not want assistant commits) — clean repeat due at the gate |
| I-12 | Limitations stated | YES | §5 |

## 5. Limitations

- Three captures, one person, one lighting condition (L2), one distance, one camera mode (DSHOW 640×480). Presence rates and timings are HW-01 development evidence, not a benchmark; Task 03.11 runs the distance × lighting factorial.
- `git_dirty: true` on both runs (the measuring code is the code under submission and the assistant does not commit). Phase 02 precedent: dirty development runs may be cited in a task note; the gate record needs a clean-tree repeat.
- The `hands` slot timing includes BGR→RGB conversion inside the wrapper but excludes image decoding from PNG (replay) — live capture hands frames from memory, so the number transfers; it is the *estimator* cost, not the loop cost.
- `swap_handedness` resolved by the owner check (§6, P-03.1-1): `hand_id` = the estimator's label = the anatomical hand on HW-01's non-mirrored image.
- No claim is made about tracking accuracy, latency budgets or playability.

## 6. Pending items (owner / later tasks)

| Id | Item | Owner | Due |
|---|---|---|---|
| P-03.1-1 | **CLOSED 2026-09-21 (owner check, no recording):** Step 1 — overlay `20260921-1003-…-video/overlay.swing-L2-exp-5.frame00002.png`: image-left hand labelled `Right->RIGHT` (confirmed). Step 2 — live guide window (`scripts/show_guide.py`): the owner's raised **anatomical right** hand appears on the **image-left** side. Conclusion: the HW-01 DSHOW image is **not mirrored**; the estimator's `Right` label is the anatomical right hand. **Decision: `hands.swap_handedness = false`** (unchanged). | Project owner | closed |
| P-03.1-2 | **CLOSED 2026-09-21 (Phase 03 gate C-03-5): MANIFEST-ONLY** — binary git-ignored, manifest tracked, fetch script re-creates it. | Project owner | closed |
| P-03.1-3 | Clean-tree repeat of the two runs in §2 once the Task 03.x code is committed by the owner. | Submitter | Phase 03 gate |
| P-03.1-4 | Phase 02 F-3 / C-5: the exposure-vs-presence finding (§2.3) is input to the fragment's `exposure.value` decision; Task 03.11 quantifies it per lighting condition. | Project owner + Task 03.11 | C-5 |
| P-03.1-5 | Phase 02 test robustness fix made here: `tests/architecture/test_import_layers.py` decodes the `lint-imports` output as UTF-8 (the test failed only when `PYTHONIOENCODING=utf-8` made `rich` print a UTF-8 banner into a cp1252 decoder). Test-only change; recorded for the Phase 03 gate trail. | — | recorded |
