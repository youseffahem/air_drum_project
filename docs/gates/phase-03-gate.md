# Phase 03 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 03 — Hand / Stick Tracking |
| Phase document | `phases/phase-03-hand-stick-tracking.md` |
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-21 |
| Reviewer(s) | Project owner — **verdict approved 2026-09-21** (PASS-WITH-CONDITIONS); C-03-5 decided MANIFEST-ONLY; owner confirmed that **no participant recordings are required** to close any condition (developer-only captures suffice for C-03-2/C-03-3). Signature line in §9. |
| Review date | 2026-09-21 (submission and owner approval) |
| Code state | Phase 03 tree committed by the owner as **`191778882f646444395b58c71134c3942974c5d8`** ("[P03] Phase 03 gate…"). Development runs were taken on the uncommitted tree at `4dd0c2e` (`git_dirty: true`); **all cited runs were repeated on the clean tree at `1917788…` with `git_dirty: false` (C-03-4, §3a) and reproduce the development figures exactly.** Tag `gate-03-pass` not yet created (owner). |
| **Verdict** | **PASS-WITH-CONDITIONS (approved by the owner, 2026-09-21)** — the machine-executable scope of all 15 tasks is IMPLEMENTED with tests (370 passed), `TEST-CAUSAL-1/2` pass on synthetic and recorded sequences, the state machine passes every transition test, per-stage latency is MEASURED, and the benchmark machinery is executed on the existing developer captures. Three acceptance criteria are **PARTIAL** for one reason only: the evidence they need (annotated tip reference, deliberate crossings, distance × lighting captures) requires a person at the camera and no new recording was made in this phase on the owner's instruction. Each is a named condition with its resolving action (§8). The owner chose PASS-WITH-CONDITIONS over the stricter BLOCKED reading; conditions C-03-1…C-03-4 remain **PENDING** and are not weakened by the approval. Phase 05 development may start on the provisional `GEOM` method; Phase 06 participant recording may **not** start before C-03-3. |

## 1. Artefacts produced

| Artefact (from phase document) | Path | Status label | Present? |
|---|---|---|---|
| `hands` module (landmark estimator wrapper, L/R identity, per-hand presence, grip reference) | `src/spacedrums/hands/{landmarker,coords,model_asset,identity,grip}.py` | IMPLEMENTED (tests pass) | yes |
| `stick` module (search region, segmentation, axis, `GEOM` / `AXIS_REFINED` / `MARKER`, factory) | `src/spacedrums/stick/{search_region,segment,axis,estimator,tip_geom,tip_axis_refined,tip_marker}.py` | IMPLEMENTED | yes |
| `tracking` module (filters, state machine, `CausalTracker`, `TrackReset`) | `src/spacedrums/tracking/{filter,state_machine,tracker}.py` | IMPLEMENTED | yes |
| Contracts: `HandObservation`, `StickObservation`, `TrackState` classes; `TipEstimator`, `Tracker` Protocols | `src/spacedrums/contracts/{records,interfaces}.py` | IMPLEMENTED (round-trip the Phase 01 examples) | yes |
| `tools/annotate_tip.py` | `tools/annotate_tip.py` | IMPLEMENTED (interactive; SYNTHETIC self-test) — **no real annotation exists** | yes |
| `scripts/benchmark_tip_methods.py`, `scripts/measure_stage_latency.py` | `scripts/` | IMPLEMENTED (self-tested; executed on dev captures) | yes |
| Tip-estimation benchmark report | `docs/reports/phase-03-tip-benchmark.md` | MEASURED (presence, fallback, agreement, compute, traces, causality, latency); **tip error PENDING** | yes |
| Tracking quality vs distance / lighting | `docs/reports/phase-03-distance-lighting.md` | PARTIAL / PENDING (exposure-confounded stills; factorial needs a person) | yes |
| ADR primary tip method | `docs/decisions/ADR-0015-primary-tip-method.md` | Accepted (pipeline) / **Provisional** (`GEOM`) | yes |
| ADR filter choice | `docs/decisions/ADR-0016-filter-choice.md` | Accepted (`kalman_cv` candidate; thresholds candidates) | yes |
| ADR ROI / distance | `docs/decisions/ADR-0017-roi-distance.md` | **Proposed** (recommendation; factorial pending) | yes |
| Experiment logs | clean-tree (`1917788…`, `git_dirty: false`): `experiments/20260921-1447-p03-hands-check-{video,image}-idtemporal`, `20260921-1448-p03-hands-check-video-idraw`, `20260921-1452-p03-hands-check-image-idraw`, `20260921-1449-p03-tip-benchmark`, `20260921-1449-p03-stage-latency`; development originals `20260921-{1003,1004,1046}-…`, `1403/1405`, `1407` (git-ignored per repo-layout §3.3) | MEASURED | yes |
| Task evidence notes | `docs/reports/phase-03-task-03.1-hand-landmarker.md`, `phase-03-task-03.2-identity.md` | — | yes |
| Model asset + manifest | `assets/models/hand_landmarker.task` (+ `manifest.json`) | pinned (`sha256:fbc2a300…`) | yes — **MANIFEST-ONLY** (C-03-5, owner 2026-09-21): `assets/models/*.task` git-ignored; the manifest is tracked; `scripts/fetch_hand_landmarker_model.py` re-fetches and verifies the pinned file |
| Config schema 1.2 (`hands`, `stick` blocks; real `tracking.filter`) | `configs/schema/config.schema.json`, `configs/example.candidate.yaml`, camera fragment (`1.2`) | IMPLEMENTED | yes |
| Gate record | this file | — | yes |

## 2. Acceptance criteria

| # | Criterion (verbatim) | Evidence | Status |
|---|---|---|---|
| 1 | Both hands tracked with stable identity on dev captures; swap rate reported. | Identity assigner (Task 03.2): exp-5 — 0 identity jumps, 4 label overrides / 170 detected frames (0.024), 0 ambiguous; exp-6 — 0 jumps, 28 overrides (0.25), 4 ambiguous frames capped to DEGRADED (`20260921-1046-p03-hands-check-video-idtemporal`). Synthetic crossings with label noise: 0 swaps (`TEST-HANDS-4`). **Deliberate-crossing capture does not exist** (P-03.2-1 deferred to the Task 03.11 session). | **PARTIAL** — reported on available captures; crossing condition pending (C-03-2) |
| 2 | All three tip methods implemented behind `TipEstimator`; benchmark executed; per-method error and failure rates reported with strata. | Three estimators + `TEST-CONFORM-1` (37 stick tests). Benchmark executed on 3 captures × 3 methods (run `20260921-1403`): presence / failure (no-axis, fallback) / low-confidence / compute / agreement per capture condition (exposure). **Error vs reference: PENDING** — no annotated frames (person-dependent), no marker capture; the script computes the error tables and speed terciles the moment an annotation file exists. | **PARTIAL** — failure rates and strata by condition MET; error rows PENDING (C-03-1) |
| 3 | Primary markerless method selected and justified in an ADR (markerless only; `MARKER` remains fallback/benchmark). | ADR-0015: **provisional `GEOM`** justified on presence, fallback rate (AXIS_REFINED 43 %), confidence and robustness to blur; explicitly *not* on accuracy; reversal rule stated. `MARKER` fallback/benchmark by construction (WARNING, labels). | **PARTIAL** — selected and justified as far as evidence allows; final on C-03-1 |
| 4 | Tracker passes `TEST-CAUSAL-1/2`; state machine passes all transition tests; induced-occlusion test shows no fabricated observations. | `TEST-CAUSAL-1` bit-identical: 3 filters × 9 cuts × 3 kinds (synthetic), 17 cuts on recorded exp-5. `TEST-CAUSAL-2`: declared `N_eff` 290/35/134, max dev 3.2e-15 / 1.2e-7 / 2.8e-12 (synthetic), 5.6e-7 on exp-5 (14 cuts), negative control differs. `TEST-TRACK-2`: 11 transition tests. Occlusion trace `V…V D D D I I I I I V…`, one `GAP_EXCEEDED` reset; dev-capture traces in the report §3.5. | **MET** |
| 5 | Per-stage latency measured and documented. | `20260921-1407-p03-stage-latency` (HW-01, exp-5, 166 frames): hands 23.7 / 39.6 ms (p50 / p95), stick GEOM 5.5 / 6.9, tracking 0.48 / 0.54; sum p50 29.7 ms vs 33.3 ms period; report §4. | **MET** (development run; clean repeat C-03-4) |
| 6 | Distance/lighting table complete; ROI/distance recommendation recorded. | Table rows from the Phase 02 stills are exposure-confounded (landmarks only at 1.5 m, exposure −6); lighting: L2 only. Recommendation recorded (ADR-0017 Proposed: 1.0 m, 640×480, exposure −5). Factorial needs a person. | **PARTIAL** — recommendation recorded; table not complete (C-03-3) |

## 3. Tests

Run 2026-09-21 on HW-01, `.venv` Python 3.11.9, from both PowerShell and Git Bash on the development tree and **again on the clean tree at `1917788…`**: **370 passed, 1 skipped** (`tests/capture/test_hardware_capture.py`, opt-in webcam). `ruff check .` clean; `lint-imports` 4 kept / 0 broken; `scripts/validate_contracts.py` PASS; `scripts/env_smoke.py` PASS; `scripts/fetch_hand_landmarker_model.py --verify` PASS.

| Test id | What it checks | Result | Suite |
|---|---|---|---|
| `TEST-SCHEMA-1` (+ record classes) | schemas; `HandObservation` / `StickObservation` / `TrackState` classes round-trip the Phase 01 examples; config 1.2 blocks | pass | `tests/contracts` (142) |
| `TEST-CONFIG-1` | loader, fragment merge, cross-field rules (`hands`/`stick` need 1.2; ambiguity cap in `[c_min, c_valid)`) | pass | `tests/config` (24) |
| `TEST-HANDS-1…5` | coordinate boundary; wrapper (injected backend); real model (skips if absent); identity on synthetic sequences; grip | pass | `tests/hands` (56) |
| `TEST-STICK-1/2`, `TEST-CONFORM-1` | region / segmentation / axis on synthetic images; three estimators; per-frame causality guard | pass | `tests/stick` (37) |
| `TEST-TRACK-1/2/3`, `TEST-CONFORM-2` | filters on synthetic trajectories (lag / RMSE); every state-machine transition; tracker, history, resets, occlusion | pass | `tests/tracking` (44 incl. causal) |
| `TEST-CAUSAL-1`, `TEST-CAUSAL-2` | tracker, synthetic + recorded exp-5 | pass | `tests/tracking/test_causal.py` |
| `TEST-ARCH-1` | layer table (AST + import-linter) with `hands`, `stick`, `tracking` present | pass | `tests/architecture` (3) |
| `TEST-SCRIPTS-1` | every Phase 02/03 script in `--synthetic` mode writes a schema-valid run | pass | `tests/scripts` (10) |
| Phase 02 suites | unchanged | pass | `tests/{capture,timing,ui}` (54) |

### 3a. Clean-tree reproduction (C-03-4, 2026-09-21, commit `191778882f646444395b58c71134c3942974c5d8`, `git_dirty: false`)

The Phase 03 tree was committed by the owner and every cited run was repeated on the clean tree (tree verified clean before each run). Detection outputs are deterministic and reproduced **exactly**; wall-clock timings differ within run-to-run noise.

| Development run (dirty tree, `4dd0c2e`) | Clean-tree rerun (`1917788`) | Comparison |
|---|---|---|
| `20260921-1003-p03-hands-check-video` (RAW identity, VIDEO) | `20260921-1448-p03-hands-check-video-idraw` | both-hands frames 99 / 10 / 0 → **99 / 10 / 0** (exp-5/6/7), identical; estimator p50 33.8 → 25.2 ms (exp-5) |
| `20260921-1004-p03-hands-check-image` (RAW identity, IMAGE) | `20260921-1452-p03-hands-check-image-idraw` | 69 / 2 / 0 → **69 / 2 / 0**, identical; p50 46.9 → 38.3 ms |
| `20260921-1046-p03-hands-check-video-idtemporal` | `20260921-1447-p03-hands-check-video-idtemporal` | 103 / 32 / 0 → **103 / 32 / 0**; label overrides 4 / 28, identity jumps 0 / 0, ambiguous 0 / 4 — all identical |
| `20260921-1046-p03-hands-check-video-idraw` | `20260921-1448-p03-hands-check-video-idraw` | identical (99 / 10 / 0; 0 overrides) |
| — (new comparison point) | `20260921-1447-p03-hands-check-image-idtemporal` | IMAGE + TEMPORAL identity: 83 / 8 / 0 both-hands frames |
| `20260921-1403-p03-tip-benchmark` (+ `1405` distance) | `20260921-1449-p03-tip-benchmark` (captures + distance in one run) | per-method presence / no-axis / fallback / tip-confidence / agreement identical to every printed digit; every tracker histogram, reset list and state trace identical; distance rows identical |
| `20260921-1407-p03-stage-latency` | `20260921-1449-p03-stage-latency` | hands p50 23.7 → 23.8 ms, stick GEOM 5.5 → 5.2, tracking 0.48 → 0.49; sum p50 29.7 → **29.5 ms** vs 33.3 ms; sum p95 47.0 → 47.2 ms |

Clean-tree checks: `pytest` **370 passed, 1 skipped**; `ruff` clean; `lint-imports` 4 kept / 0 broken; `validate_contracts.py`, `env_smoke.py`, `fetch_hand_landmarker_model.py --verify` all PASS. Config hash of the captures/latency runs unchanged (`sha256:aca65e8026ebb55ac…`).

## 4. Measurements produced in this phase (all MEASURED on HW-01; development run ids below, each reproduced exactly by the clean-tree run listed in §3a; details in the reports)

| Quantity | Value | run_id |
|---|---|---|
| Landmark presence, both hands (exp-5 / -6 / -7, VIDEO) | 99 / 10 / 0 of 171–172 frames (RAW identity); 103 / 32 / 0 (TEMPORAL) | `1003-…-video`, `1046-…-idtemporal` |
| Estimator processing (exp-5, VIDEO / IMAGE) | p50 33.8 / 46.9 ms per 560×440 frame | `1003`, `1004` |
| Identity: label overrides / identity jumps / ambiguous (exp-5, exp-6) | 4 / 0 / 0; 28 / 0 / 4 | `1046-…-idtemporal` |
| Axis found (dev sweep, exp-5) | 84–91 % of 273 hand-frames; support p50 ≈ 115 px | development sweep (report §2) |
| Tip presence GEOM / AXIS_REFINED / MARKER (exp-5) | 272 / 272 / 28 of 273; AXIS_REFINED fallback 118 (43 %) | `1403-p03-tip-benchmark` |
| AXIS_REFINED vs GEOM tip distance (exp-5) | p50 1.1 px, p90 13.2 px | `1403` |
| Tip error vs reference | **PENDING** (no reference) | — |
| Tracker status histograms, resets | report §3.5 | `1403` |
| `TEST-CAUSAL-2` max deviation | ≤ 5.6e-7 (declared 1e-6) | `tests/tracking/test_causal.py` |
| Filter lag / RMSE (SYNTHETIC) | report (ADR-0016 table) | tests |
| Per-stage latency (exp-5) | hands 23.7 / stick 5.5 / tracking 0.48 ms p50; sum 29.7 ms vs 33.3 ms | `1407-p03-stage-latency` |
| Distance stills (exposure −6) | landmarks only at 1.5 m (1 frame each) | `1405-p03-tip-benchmark` |

## 5. Integrity checklist

| # | Item | YES / NO / N/A | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled | YES | reports label MEASURED (development) with run ids, SYNTHETIC, arithmetic, candidate; no target is implied |
| I-2 | No IMPLEMENTED without tests | YES | §3; every module has a suite |
| I-3 | No causal component consumes future frames | YES | `TEST-CAUSAL-1/2` pass (tracker); per-frame estimators guarded; identity assigner prefix-invariance test; no interface has a look-ahead argument |
| I-4 | No fabricated data | YES | only the owner's Phase 02 developer captures; synthetic sequences/images labelled SYNTHETIC in file names, run descriptions and reports; the SYNTHETIC annotation file is refused by the benchmark by default; no reference or error number was invented |
| I-5 | FPS native only | N/A | no FPS figure produced; frame period stated as arithmetic |
| I-6 | No "latency reduced" claim | YES | latency reported as stage costs vs period; no reduction claim; grep of the phase documents for reduce/faster/before impact/guarantee finds only a processing-time comparison of two running modes (measured) and the AXIS_REFINED confidence multiplier — no latency claim |
| I-7 | Marker condition labelled | YES | `MARKER` logs a WARNING, every record carries `method_id`, overlay tags it, reports label it fallback/benchmark; no result derives from it |
| I-8 | Participant-level split | N/A | no ML result |
| I-9 | Scope respected | YES | no strike/zone/audio logic, no anticipation beyond the filter's one-step prediction, no non-causal smoothing, no participant recordings, no foot tracking; `LEFT_FOOT` remains a rejected value |
| I-10 | Status vocabulary | YES | phase document status updated; RTM rows advance only on signature; PENDING items name their resolving action |
| I-11 | Reproducibility fields | YES | every `run.json` validates, config snapshots + hashes present; the cited clean-tree runs (§3a) carry `git_dirty: false` and `git_sha = 1917788…` |
| I-12 | Limitations stated | YES | report §6, distance report, ADR limitations |

## 6. Deviations from the phase document

| What | Why | Impact |
|---|---|---|
| Grip direction prior default is `KNUCKLE_ROW`, not one of the two named candidates | Both named candidates run along the fingers, perpendicular to a stick held in a fist (overlay evidence, Task 03.3) | none downstream; both candidates remain selectable (ADR-0014 §12) |
| `TEST-CAUSAL-2` run with a declared effective window `N_eff` > `N` | filters have decaying, not hard, memory (causality-tests.md §3 allows a declared `N_eff` with justification) | Phase 19 history-length ablation uses `N` for features; the filter memory is declared separately |
| Tip error vs reference not reported; primary method provisional | no annotated reference; annotation is person-dependent; no new recordings | C-03-1 |
| Distance × lighting factorial not run | needs a person; existing stills exposure-confounded | C-03-3; ADR-0017 Proposed |
| Deliberate-crossing swap rate not measured | no crossing capture | C-03-2 (folded into C-03-3's session) |
| Dev-capture replay implemented as a script helper (`scripts/_devcapture.py`) rather than `capture.ReplayFrameSource` | Phase 02 owns `capture`; the full replay source is Phase 09/13 | promote then; no re-implementation |
| Test robustness fix in a Phase 02 test (`tests/architecture/test_import_layers.py` decodes `lint-imports` output as UTF-8) | environment-dependent failure (P-03.1-5) | none |
| Phase 02 F-2 closed here (`distance_benchmark.py` checks `cv2.imwrite`) | assigned to the Phase 03 submitter | none |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase / owner |
|---|---|---|
| Learned stick segmentation needed? | Open Question (classical pipeline finds the axis on ≥ 84 % of hand-frames at exposure −5; failure catalogue at other lighting pending) | after C-03-3 |
| `L_prior` per-user calibration | Open Question (likely; Phase 14) | 14 |
| Landmark visibility scores from the estimator | **Answered: no** (Task 03.1); confidences derived from identity + axis | — |
| VIDEO vs IMAGE running mode | candidate VIDEO (more presence, faster on exp-5) | Task 03.11 factorial / Phase 16 |
| `.task` model binary git-tracked or manifest-only | **Decided: MANIFEST-ONLY** (C-03-5, 2026-09-21) | closed |
| Phase 02 C-1 (FOV), C-4/O-1 (committing `run.json`), C-5 (frozen capture config) | carried; C-5 cannot close before C-03-3 (ADR-0017) | owner |
| State-machine thresholds `c_valid`, `c_min`, `g_max`, `age_max` | To Be Experimentally Determined (candidates; exp-6 shows STALE dominates at low confidence) | 05 / 17 |

## 8. Conditions (PASS-WITH-CONDITIONS) — status at owner approval, 2026-09-21

No participant recordings are required for any condition (owner statement); C-03-2 and C-03-3 use developer-only captures.

| Condition | Status | Owner | Must be closed by |
|---|---|---|---|
| **C-03-1** Annotate the tip on a stratified subset of the dev captures (`tools/annotate_tip.py --capture swing-L2-exp-5 --every 10`, plus a disjoint `--offset 5` subset for agreement), re-run `scripts/benchmark_tip_methods.py`, fill the error tables in the benchmark report, and finalise ADR-0015 (keep or supersede `GEOM`). Person-dependent, ≈ 30 min. | **PENDING** | Project owner (annotation) + submitter (re-run, report) | before any Phase 05 result is reported; before Phase 18 |
| **C-03-2** Deliberate-crossing developer capture (P-03.2-1) → swap-rate row in the Task 03.2 note. | **PENDING** | Project owner | with C-03-3 |
| **C-03-3** Distance × lighting factorial per `docs/reports/phase-03-distance-lighting.md` §5 (developer only, ≈ 10 s per cell, exposure per lighting), fill the table, move ADR-0017 to Accepted, then close Phase 02 C-5 (frozen capture config with exposure −5 at L2 and `native_fps_measured`). | **PENDING** | Project owner + submitter | **before Phase 06 records any participant** |
| **C-03-4** Clean-tree repeat of the cited runs (`hands-check`, `tip-benchmark`, `stage-latency`) after the owner commits the Phase 03 tree; update run ids in the reports. | **CLOSED 2026-09-21** — six reruns on `1917788…`, all `git_dirty: false`, detection/tracking figures identical, timings within noise (§3a); reports updated | Submitter | at signature |
| **C-03-5** Decide git-tracking of `assets/models/hand_landmarker.task` (P-03.1-2). | **CLOSED — MANIFEST-ONLY** (`.gitignore`: `assets/models/*.task`; manifest tracked; fetch script re-creates the file) | Project owner | closed 2026-09-21 |

## 9. Reviewer statement

Submitter's statement: every artefact in §1 was written and every test/run in §3–§4 executed in one assistant session on HW-01 on 2026-09-21 without a person at the camera and without any new recording. Inspected by the submitter: all overlays cited in the reports (frames 2/30/100/140 of exp-5 during development; benchmark overlays at frames 0–160; exp-6 frame 22 for identity), the run directories' `run.json` (all validate), the printed causality lines. Not done: anything person-dependent (annotation, crossings, factorial), any commit/tag/push.

Owner's review (2026-09-21): verdict **PASS-WITH-CONDITIONS approved**; C-03-1, C-03-2, C-03-3 PENDING; C-03-4 PENDING until the clean-tree reruns; C-03-5 decided MANIFEST-ONLY; no participant recordings are required.

C-03-4 closure (submitter, 2026-09-21, after the owner's commit `1917788…`): tree verified clean before each of the six reruns; results in §3a; C-03-1/2/3 untouched and still PENDING; verdict unchanged. Pending evidence is not fabricated by this approval: the conditions stay open until their runs exist.

Signed: project owner (approval recorded in the conversation of 2026-09-21; countersignature on commit), 2026-09-21
