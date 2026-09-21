# Phase 02 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 02 — Camera Capture & Computer Vision Prototype |
| Phase document | `phases/phase-02-camera-capture.md` |
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-21 |
| Reviewer(s) | Gate review performed by Claude **on the project owner's explicit instruction** (2026-09-21, scope in §11); project owner countersignature **pending** (gate-procedure §4: a gate is not passed by the submitter alone — the verdict below becomes effective on the owner's signature in §9) |
| Review date | 2026-09-21 |
| Code state | Phase 02 tree committed and pushed by the owner as `13f0f3394fc699bb2e12eb10ae0f1da6c0ce2f61` ("phase 2", `origin/main`). Development measurement runs were taken before that commit on `568eca92…` with `git_dirty: true` (D-1); the baseline FPS cells were re-run on `13f0f33…` with `git_dirty: false` (C-3, §4). Tag `gate-02-pass` not yet created (after signature). |
| **Verdict** | **PASS-WITH-CONDITIONS** — all six acceptance criteria MET against the evidence (§2; 5 and 6 with explicitly PENDING entries that name their resolving phase); integrity checklist has no NO (§5); Definition of Done satisfied for the machine-executable scope, with the person-dependent and instrument-dependent items honestly PENDING. Conditions in §8: C-1 (FOV, deferred, not a Phase 03 blocker), C-4/O-1 (repository-artefact decision), C-5 (frozen capture config at the Phase 03 gate). Effective on owner signature (§9). Phase 03 may start once signed. |

## 1. Artefacts produced

| Artefact (from phase document) | Path | Status label | Present? |
|---|---|---|---|
| `capture` module (FrameSample production, ROI crop, bounded queue with drop counting, timestamp policies, device probing) | `src/spacedrums/capture/{roi,backend,timestamps,frame_queue,stats,source,device}.py` | IMPLEMENTED (tests pass) | yes |
| L0 packages required by capture: contracts (enums, `FrameSample`/`ImageRef`, `FrameView`, `FrameSource`, schema access), timing (`now()`, `CLOCK_ID`), config loader (fragments, validation, `config_hash`) | `src/spacedrums/{contracts,timing,config}/` | IMPLEMENTED (tests pass) | yes |
| Playing-area guide overlay | `src/spacedrums/ui/guide.py`, `scripts/show_guide.py`, screenshot `docs/figures/phase-02/guide-hw01-dshow-640x480.png` | IMPLEMENTED (prototype; `TEST-UI-1`) | yes |
| `scripts/measure_fps.py`, `scripts/measure_capture_latency.py` | `scripts/` (+ `enumerate_cameras.py`, `exposure_blur_check.py`, `distance_benchmark.py`, `_runlog.py`) | IMPLEMENTED; runs executed (§4) | yes |
| Camera profile config | `configs/camera/hw01-integrated-webcam.candidate.yaml` (schema 1.1) | candidate (measured fields null by rule) | yes |
| Camera Profile document | `docs/camera-profile-hw01-integrated-webcam.md` | MEASURED (§1–§6, §9) / PENDING (§7 placement-distance-FOV, §8 processing FPS, §6 bias) — every value labelled | yes |
| Distance-benchmark protocol | `docs/protocols/camera-distance-benchmark.md` | protocol IMPLEMENTED; table MEASURED for 0.8 / 1.0 m (owner), ≥ 1.2 m PENDING | yes |
| Lighting checklist | `docs/protocols/lighting-checklist.md` | IMPLEMENTED | yes |
| Capture-latency method | `docs/protocols/capture-latency-flash-method.md` | IMPLEMENTED; executed (§4) | yes |
| Exposure / blur procedure | `docs/protocols/exposure-blur-procedure.md` | procedure IMPLEMENTED; capability MEASURED; blur check MEASURED for L2 (owner), other conditions PENDING | yes |
| `experiments/phase-02/*.json` | **deviation** → `experiments/<run_id>/run.json` per `repo-layout.md` §3.3 (13 run directories on HW-01, git-ignored; ids in §4) | MEASURED / ABORTED as listed | yes (local) |
| ADR for the Phase 02 decisions | `docs/decisions/ADR-0013-capture-backend-timestamp-policy.md` (+ index) | Accepted (backend choice = candidate) | yes |
| Import-layer enforcement (Phase 01 follow-up F-3) | `.importlinter`, `tests/architecture/test_import_layers.py`, `import-linter` in `requirements.in/.lock` | IMPLEMENTED (4 contracts kept) | yes |
| Layout / environment / inventory / RTM updates | `docs/repo-layout.md`, `docs/environment.md`, `docs/hardware-inventory.md`, `docs/requirements/rtm.md` (evidence pointers; status PLANNED until signature), package READMEs, `pyproject.toml` (`[project]`) | — | yes |
| Gate record | this file | — | yes |

## 2. Acceptance criteria

| # | Criterion (verbatim) | Evidence | Assessment |
|---|---|---|---|
| 1 | Capture module produces schema-valid `FrameSample`s with monotone `t_capture` and drop accounting. | `TEST-CAPTURE-4` (synthetic source: ids strictly increasing, `t_capture` monotone and ≤ `t_frame_available`, schema-valid, `Σ dropped_since_last == dropped`); `TEST-CAPTURE-5` on the real webcam, both backends (2 passed, opt-in run 03:21); every FPS cell reports 0 clamps on DSHOW and the single documented policy-switch clamp on MSMF. | **MET** |
| 2 | Native FPS measured and documented for the 30 FPS baseline; the 60 FPS attempt is either measured or explicitly PENDING with the reason. | Camera profile §3: 640×480 @30 → **30.15–30.18 FPS** (DSHOW, 2 repeats), **29.06–29.10** (MSMF, with padded-frame refusal); 60 FPS requested in 8 cells → delivered ≈ 29–30 FPS in every statistic → **measured as not delivered** on HW-01. Runs `20260921-0240/0249/0258/0259-p02-fps-*`. | **MET** |
| 3 | Capture-latency method executed at least once; results and limitations documented. | Runs `20260921-0314…0318-p02-latency-*-exp4/-exp5` (L0, 4 × 30 trials, 29–30 detections each): raw hand-over ≈ 116–118 ms median (upper bound incl. display latency), floor 82–100 ms; MSMF driver stamp 46–70 ms after the flash. Owner re-run under L2 with the screen at normal brightness, `20260921-0913-p02-latency-dshow` (−5): raw median 137.7 ms, p10 117.1, p90 159.6, min 105.4, max 553.1, 27/30 detected. Limitations: protocol §3 and profile §6 (display term unknown; `grab_return_bias_s` left null). Three earlier runs at −6 ABORTED (no detection) and recorded as such. | **MET** (as an upper bound) |
| 4 | ROI guide overlay works; coordinate helper tests pass. | `TEST-UI-1` (11 tests); screenshot from the live webcam; `TEST-CAPTURE-1` (15 tests: round trip, corners, y-down, crop is a view). | **MET** |
| 5 | Camera profile document complete with labels on every value. | Every row/number in `docs/camera-profile-hw01-integrated-webcam.md` carries MEASURED / inspected / advertised / candidate / PENDING and a run id where measured; PENDING entries state the reason (person needed / instrument needed). | **MET** (with PENDING entries) |
| 6 | Distance protocol written; visibility table filled. | Protocol written with tooling. Table filled by the owner on 2026-09-21 for **0.8, 1.0, 1.5 and 2.2 m** — both hands and all four zone paths inside the ROI at every distance (L2; side-cars in `data/dev-captures/distance/`); 1.2 m dropped (raw frame not overwritten), 1.8 m not captured; pixel-size columns indicative only (protocol §5 caveats). FOV (protocol §6) **PENDING** by owner decision; tracking-quality columns PENDING (Phase 03 Task 03.11). | **MET** (visibility part complete; FOV and tracking columns explicitly PENDING) |

## 3. Tests

| Test id | What it checks | Result | Where run |
|---|---|---|---|
| `TEST-SCHEMA-1` (`tests/contracts/`, 77 + 22 cases, Phase 01) + 13 record-class cases (`test_record_classes.py`) | schemas; `FrameSample`/`ImageRef` serialise to exactly the schema, invariants, Phase 01 example round-trips | pass | HW-01, `.venv` Python 3.11.9, pytest 9.1.1, 2026-09-21 |
| `TEST-TIMING-1` (5) | single clock accessor; static rule "no `time.*`/`datetime.now` outside `spacedrums.timing`" | pass | same |
| `TEST-CONFIG-1` (17) | fragment merge, schema 1.1 (1.0 documents still valid), cross-field checks, canonical hash, resolved snapshot | pass | same |
| `TEST-CAPTURE-1…4` (15 + 8 + 6 + 9) | ROI helper; interval stats / stall detector / drop-oldest queue with slow consumer; timestamp mapper (identity detection, foreign clock, non-monotone); `LiveFrameSource` contract incl. `TEST-CONFORM-7` live case, duplicate refusal, per-frame labels, drop accounting | pass | same |
| `TEST-CAPTURE-5` (hardware, opt-in, 2) | 4 s capture on the webcam per backend: no exceptions, schema-valid, monotone, drops sum, ROI view | pass (`SPACEDRUMS_HW_TESTS=1`) | same, 03:21 |
| `TEST-UI-1` (11) | guide overlay drawing, band placement (y-down), text, no input mutation | pass | same |
| `TEST-ARCH-1` (3) | layer table by AST; contracts is a leaf; `import-linter` (4 contracts kept, 0 broken) | pass | same |
| `TEST-SCRIPTS-1` (5) | every measurement script in `--synthetic` mode writes a schema-valid COMPLETED `run.json` with config snapshot and hashed artefacts; latency self-test recovers an injected 20 ms | pass | same |
| **Total** | 191 collected, **191 passed** (+2 hardware tests in the opt-in run) | pass | same |
| `ruff check .` | lint, whole repository | All checks passed | same |
| `scripts/validate_contracts.py` (204 checks) | Phase 01 checker still passes with schema 1.1 | RESULT: PASS | same |
| `scripts/env_smoke.py` | environment regression (new lock) | RESULT: PASS | same |
| `TEST-CAUSAL-1/2`, `TEST-PARITY-1`, `TEST-CONFORM-1…6` | not applicable to capture (no causal component, no replay source yet) | — | — |

## 4. Measurements produced in this phase

All on HW-01, 2026-09-21, lighting L0 (dark room, screen at 0 % brightness — profile §9), `git_dirty: true` (D-1). Values are quoted from the camera profile; the run directories hold `run.json`, `config.resolved.yaml`, `stdout.log` and the per-cell/per-trial JSON.

| Quantity | Label | Value | run_id | Method | Hardware id |
|---|---|---|---|---|---|
| Delivered native FPS, 640×480 @30 — **clean tree (C-3)** | Measured, `git_dirty: false`, git_sha `13f0f33…` | DSHOW **30.16 / 30.18** (1801 / 1802 unique, 0 drops, 0 duplicates); MSMF **29.03 / 29.06** (1732 / 1734 unique, 0 drops, 59 / 57 duplicates refused) | `20260921-0931-p02-fps-dshow-manual-clean`, `20260921-0933-p02-fps-msmf-manual-clean` | `measure_fps.py`, 60 s cells ×2, unique-frame (N−1)/span, manual exposure −6; identical `config_hash` to the development runs | HW-01 |
| Delivered native FPS, 640×480 @30 — development runs | Measured (dirty tree) | DSHOW 30.15 / 30.18; MSMF 29.08 / 29.08 | `20260921-0249-p02-fps-dshow-manual`, `20260921-0240-p02-fps-msmf-manual` | same | HW-01 |
| Delivered FPS with 60 requested (all modes) | Measured | 29.06–30.18 (identical to the 30 FPS request) → 60 FPS not delivered | same runs | same | HW-01 |
| Delivered FPS, 1280×720 @30 | Measured | MSMF 29.06–29.10; DSHOW 10.06 (YUY2) | same runs | same | HW-01 |
| Frame-interval jitter (std / p1 / p99), 640×480 @30 | Measured | DSHOW 4.5–4.6 / 28.3–28.8 / 48.6–49.0 ms; MSMF 6.0–6.2 / 31.6–31.7 / 66.7 ms | same runs | same | HW-01 |
| Queue drops / stalls / duplicates | Measured | drops 0 in all cells; DSHOW 0 duplicates; MSMF ~56 padded frames per minute refused; auto-exposure: ~10 FPS both backends, MSMF 591 duplicates / 30 s | same + `…-0258-p02-fps-msmf-auto`, `…-0259-p02-fps-dshow-auto` | same | HW-01 |
| Timestamp-mapping residual (MSMF driver clock) | Measured | slope −1 = 10⁻⁵…10⁻⁶ (identity map); hand-over lag p50 38–39 ms, LS residual std 10.7–11.1 ms | MSMF FPS runs | `DriverTimestampMapper` statistics | HW-01 |
| Hand-over lag `t_frame_available − t_capture` | Measured | DSHOW p50 0.2–0.8 ms; MSMF p50 42–51 ms | FPS runs | per-frame stamps | HW-01 |
| Capture-thread CPU | Measured | ≤ 1 % (640×480), 2–3 % (720p MSMF) | FPS runs | thread CPU time / wall | HW-01 |
| Capture latency (flash method), L0 | Measured **upper bound** (incl. display latency; not `L_sys`) | raw median 115.8–118.2 ms, floor 82–100 ms (both backends, exposure −4/−5); MSMF driver stamp 46–70 ms after flash | `20260921-0314…0318-p02-latency-*` | protocol `capture-latency-flash-method.md` | HW-01 |
| Capture latency (flash method), L2, screen at normal brightness (C-2) | Measured **upper bound** (incl. display latency; not `L_sys`) | DSHOW/GRAB_RETURN, −5: raw median 137.7 ms, p10 117.1, p90 159.6, min 105.4, max 553.1; `t_capture − t_flash` median 137.4; half-period-corrected 121.7; **27/30 detected** (3 not detected within 1.0 s); 640×480 YUY2, `stamp_after = RETRIEVE`, no driver ts | `20260921-0913-p02-latency-dshow` (owner) | same protocol | HW-01 |
| Grab-return bias (`grab_return_bias_s`) | **PENDING** | null (0) — not separable from display latency with this method | — | — | — |
| Exposure controls / low-light frame-rate cap | Measured | manual exposure available on both backends; ≤ 31 ms → ~30 FPS, 62 ms → ~16 FPS, auto (dark) → ~10 FPS | `20260921-0309-p02-exposure-inspect` | `exposure_blur_check.py inspect` | HW-01 |
| Exposure setting + blur check, L2 | Measured (owner, 2026-09-21) | −5: 30.1 FPS, lum 68, sharp, proxy 46.6; −6: 29.7 FPS, lum 36, sharp, 38.8; −7: 29.6 FPS, lum 13, streaked, 32.9; selected −5 (owner decision; §3.6-literal pick would be −6) | `20260921-0904-p02-exposure-inspect`; captures `data/dev-captures/swing-L2-exp-5/-6/-7` (dev captures, no run.json) | protocol `exposure-blur-procedure.md` §3 | HW-01 |
| Blur proxy, other lighting conditions | **PENDING** | L1, L3–L5 | — | scripts ready | — |
| Visibility per distance; lens height / tilt | Measured (owner, 2026-09-21, L2) | hands + all four zone paths inside the ROI at 0.8, 1.0, 1.5, 2.2 m (yes/yes each); lens 0.75 m / 0° | side-cars `data/dev-captures/distance/d080`, `d100`, `d150`, `d220` (dev captures, no run.json) | `distance_benchmark.py` capture + live guide check | HW-01 |
| Apparent stick length / hand size vs distance | Measured, **indicative only** (click variance exceeds the assumed ±5 px; protocol §5 caveats) | stick 134.1 / 120.0 / 135.6 / 64.0 px, hand 90 / 122 / 105.5 / 53.7 px at 0.8 / 1.0 / 1.5 / 2.2 m | same side-cars | interactive clicks | HW-01 |
| FOV / visible playing area | **PENDING** (owner decision: no further manual calibration before Phase 03) | none | — | protocol §6 | — |
| Enumerated modes | inspected / advertised | camera profile §2 | `20260921-0300-p02-enumerate-cameras` | `enumerate_cameras.py` | HW-01 |
| ABORTED runs (not citable) | — | `20260921-0305-p02-latency-dshow`, `…-0306-p02-latency-msmf`, `…-0310-p02-latency-dshow` (flash undetectable at −6 / baseline before settling; marked ABORTED with a note) | — | — | — |

## 5. Integrity checklist (filled at the review, 2026-09-21)

| # | Item | YES / NO / N/A | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled | YES | Camera profile: every value MEASURED/inspected/advertised/candidate/PENDING with run ids; config fragment keeps `native_fps_measured` and `grab_return_bias_s` null (candidate file rule); protocol documents carry only candidate thresholds and arithmetic examples labelled as such. |
| I-2 | No implementation claim without tests | YES | Re-run at the review on the committed tree `13f0f33…`: 191 collected / 191 passed, `ruff` clean, `validate_contracts.py` PASS, `lint-imports` 4 kept / 0 broken, `env_smoke.py` PASS; every IMPLEMENTED artefact has a test id; scripts have synthetic self-tests. |
| I-3 | No causal component consumes future frames | N/A (no causal component in capture) | `LiveFrameSource` delivers frames in capture order; no look-ahead exists; `TEST-CAUSAL-*` start in Phase 03. |
| I-4 | No fabricated data | YES | All numbers come from executed runs on HW-01 with `run.json`; aborted runs are marked ABORTED, not deleted (one directory that never received a `run.json` was removed and is listed in D-6); synthetic self-test runs write to temp directories or carry `-synthetic` in their slug and are never cited; the two synthetic dev captures were deleted; the person-dependent measurements are PENDING, not invented. |
| I-5 | FPS reported as native only | YES | Delivered FPS from unique-frame `t_capture` spans; padded duplicates refused and counted (591 in 30 s under auto-exposure would otherwise have read as 30 FPS); 60 FPS requests reported as not delivered; requested vs delivered kept in separate fields (schema). |
| I-6 | No "latency reduced" claim | YES | Reviewer grep (reduce/reduced/faster than/before impact/guarantee) over the camera profile, protocols, ADR-0013 and this record: no hit; every latency figure is labelled *upper bound incl. display latency* and none is called `L_sys`. |
| I-7 | Marker condition labelled | N/A | No tracking. |
| I-8 | Participant-level split confirmed | N/A | No ML, no data. |
| I-9 | Scope respected | YES | No sensor, marker, depth, MIDI, cloud or multi-user element; `OOS-REF` tags unchanged; enums extended only via ADR-0013 (config keys, not scope). |
| I-10 | Status vocabulary correct | YES | Phase document `## Status` = IMPLEMENTED + MEASURED with the gate verdict; every PENDING item names its resolving phase (FOV → C-1/owner, tracking vs distance and ROI → Phase 03 Task 03.11, grab-return bias → instrument, processing FPS → Phase 03/16, other lighting conditions → Phase 03/06); nothing VALIDATED; RTM rows advance only on the owner's signature (gate-procedure §4). |
| I-11 | Reproducibility fields complete | **YES with a stated gap** | Every `run.json` validates against the experiment-log schema, has config snapshot + hash, lock hash, hardware snapshot (CPU, RAM, OS, power). The baseline FPS cells now have `git_dirty: false` runs on `13f0f33…` (C-3). Remaining gap: the 60 FPS / 720p / auto-exposure cells, the exposure inspection, the latency runs and the owner's L2 runs (`…-0904-…`, `…-0913-…`) were taken on the dirty tree and are cited only as this phase's engineering evidence; any thesis citation of them requires a clean-tree repeat. |
| I-12 | Limitations stated | YES | Camera profile §10; protocol limitation sections; lighting condition (L0 / L2) attached to every table; latency bound explained; pixel-size columns of the distance table marked indicative only; owner's exposure selection recorded with the §3.6-literal alternative. |

## 6. Deviations from the phase document

| Id | What | Why | Impact on dependents |
|---|---|---|---|
| D-1 | Development measurement runs taken on a dirty tree (`git_dirty: true`). | The owner instructed "do not commit"; the measuring code is the code under submission. | Baseline FPS cells re-run clean on `13f0f33…` (C-3, closed); the other dirty runs serve Phase 03's mode/backend decision only and need a clean repeat before any thesis citation or VALIDATED status. |
| D-2 | Runs live in `experiments/<run_id>/` (git-ignored) instead of `experiments/phase-02/*.json`. | `repo-layout.md` §3.3 + reproducibility policy (Phase 00) fix the run-directory rule; the phase document predates it. | Reviewer opens the run directories on HW-01; Open Question O-1 whether to un-ignore `run.json`. |
| D-3 | Config schema minor bump 1.0 → 1.1 (`pixel_format`, `grab_return_bias_s`) and loader cross-field checks; `meta.schema_version` accepts both. | Reproducibility of the negotiated format (720p at 10 vs 30 FPS depends on it) and the bias field architecture.md §5.2 refers to; contracts.md §8 procedure followed (ADR-0013). | Phase 01 example config unchanged and still valid; 22 config tests pass. |
| D-4 | Duplicate-frame refusal added to capture (not in the phase document). | MSMF pads the stream with byte-identical frames carrying fresh driver timestamps; counting them would violate I-5 and corrupt velocities. | `CaptureStats.duplicates` reported with every FPS figure; Phase 06 session metadata gains the field (reserved `capture_stats`). |
| D-5 | Flash-latency measurement executed at exposure −4/−5 instead of the profile's −6, with a lowered detection floor. | The room was lit only by the laptop screen at 0 % brightness; at −6 the flash contrast was 4.8 σ (undetectable). The screen brightness was deliberately not changed (owner's machine, night). | Results are upper bounds at longer exposure; re-run under L2 lighting at −6 is condition C-2. |
| D-6 | One run directory (`20260921-0311-p02-latency-msmf`) was deleted instead of marked ABORTED. | It was killed before `run.json` existed; a partial cleanup removed its `config.resolved.yaml` while `stdout.log` was still locked, leaving nothing citable. | None; recorded here for the audit trail. |
| D-7 | Import-linter contract marks not-yet-existing packages as optional layers; the `prediction→geometry` and `commit→perception` forbidden contracts are deferred to Phase 05. | `import-linter` refuses references to absent modules; the AST test (`TEST-ARCH-1`) enforces those rules already. | Phase 05 adds the two forbidden contracts when it creates the packages. |
| D-8 | `requirements.lock` regenerated by installing `import-linter` into the existing venv (+ `pip freeze --exclude-editable`), not from a recreated venv. | Avoids a 1 GB re-download at 3 AM; every previously pinned version is byte-identical. | `environment.md` §6 records it; clean regeneration folds into the pending clean-machine row (Phase 00 C-1). |
| D-9 | `experiments/phase-02` FPS "histogram" is stored in `fps_cells.json` (40-bin counts), not rendered as a figure. | No plotting library chosen yet (Phase 21 decision). | None. |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase / owner |
|---|---|---|
| O-1 Un-ignore `experiments/*/run.json` + `config.resolved.yaml` so evidence is committed? | Open Question | Owner (policy change to `reproducibility-policy.md` if yes) |
| Baseline backend/resolution: DSHOW 640×480 (candidate) vs MSMF 1280×720 (~40 ms hand-over lag) | Pending Benchmark (tracking quality) | Phase 03, Task 03.11 → ADR-0013 amendment |
| `grab_return_bias_s` for DSHOW (needs LED/photodiode or known-latency display) | Pending Benchmark | Owner equipment decision; Phase 04/18 timing |
| ROI size/placement (`roi.px`) | candidate | Task 02.7 rows (C-1) + Phase 03 |
| Exposure per lighting condition (L1–L5) and the luminance floor for tracking | To Be Experimentally Determined | Phase 03 / 06 |
| 60 FPS target | Target (not achievable on HW-01) | Phase 16 with an external camera (HW-02 not inventoried) |
| Tripod / stick / pad / mic / tape inventory | Open Question (unchanged from Phase 00) | Owner |
| Queue size (2) and stall factor (2.0) | candidate (no drops observed with a trivial consumer) | Phase 16 |
| `ReplayFrameSource` (`timestamp_source = REPLAY`) | not yet implemented | Phase 05/09 (record/replay) |
| Phase 00/01 carried items (ethics, dataset release, Python minor version, clean-machine re-install, `gate-00/01-pass` tags — still unsigned) | as in `phase-01-gate.md` §8–§9 | Owner |

## 8. Conditions (for PASS-WITH-CONDITIONS)

Open at the verdict: **C-1 (FOV part), C-4/O-1, C-5**. Closed before the verdict: C-2, C-3 (kept below for the trail).

| Condition | Owner | Must be closed by |
|---|---|---|
| C-1 — **visibility part closed 2026-09-21** (rows 0.8 / 1.0 / 1.5 / 2.2 m, all yes/yes; lens 0.75 m / 0°). *Correction to the earlier wording:* a partial/no answer can only appear closer than 0.8 m, so "extend outward until partial/no" was not a meaningful stop condition and is withdrawn. **Remaining:** FOV and visible playing area by the protocol §6 two-marks method (owner deferred it; ~5 min at the camera when convenient). Not a Phase 03 blocker: Phase 03 needs the captures (present), not the FOV number. | Project owner | Phase 03 gate (FOV) |
| C-2 — **closed 2026-09-21.** Blur part: L2 inspect run `20260921-0904-p02-exposure-inspect`, captures `swing-L2-exp-5/-6/-7`, grades sharp/sharp/streaked, owner selected −5 (profile §5.1). Latency part: `20260921-0913-p02-latency-dshow` (DSHOW, GRAB_RETURN, −5, L2, screen at normal brightness): raw median 137.7 ms, p10 117.1, p90 159.6, min 105.4, max 553.1 ms, 27/30 detected (trials 8, 11, 24 not detected) — upper bound incl. display latency, not `L_sys` (profile §6). | Project owner | closed |
| C-3 — **closed 2026-09-21** (re-run part): tree committed as `13f0f33…`, cells re-run with `git_dirty: false` — `20260921-0931-p02-fps-dshow-manual-clean` (30.16 / 30.18 FPS, 0 dup) and `20260921-0933-p02-fps-msmf-manual-clean` (29.03 / 29.06 FPS, 59 / 57 dup refused); profile §3 cites them. Freezing the fragment (`capture.hw01.v1.yaml` with `native_fps_measured`) is **deferred by design**: it would pin the ROI/backend (Phase 03 Task 03.11) and an exposure (−6) that differs from the owner's L2 selection (−5); the candidate fragment may not carry the value (ADR-0010). Freeze at the Phase 03 gate, v1. | Project owner | re-run: closed; freeze: Phase 03 gate |
| C-4 / O-1: decide whether `experiments/*/run.json` + `config.resolved.yaml` are un-ignored and committed (reproducibility-policy change if yes). Repository-artefact decision; does not affect Phase 03's inputs. | Project owner | Phase 03 gate |
| C-5: Freeze the capture configuration (`configs/camera/capture.hw01.v1.yaml`, `meta.status: frozen`, `native_fps_measured` from `20260921-0931-p02-fps-dshow-manual-clean`) once Phase 03 Task 03.11 has settled the ROI/backend and the exposure per lighting condition. | Phase 03 submitter + owner | Phase 03 gate |

## 9. Reviewer statement

Review performed 2026-09-21 by Claude on the project owner's explicit instruction ("Perform the Phase 02 owner review now using the existing evidence and gate procedure"), scope §11. Inspected against the evidence, not the descriptions: the six acceptance criteria of `phases/phase-02-camera-capture.md` (§2 above); the 17 run directories under `experiments/` (10 COMPLETED dirty-tree development runs, 3 ABORTED and labelled not citable, 2 owner runs under L2, 2 COMPLETED clean-tree runs with `git_dirty: false` on `13f0f33…`); the candidate config fragment (`native_fps_measured` and `grab_return_bias_s` confirmed `null`, status candidate); the dev captures (`distance/d080, d100, d150, d220` measured, `d120` dropped; `swing-L2-exp-5/-6/-7`); the guide screenshot; the camera profile's labels row by row. Ran: `pytest` (191/191), `ruff check .` (clean), `scripts/validate_contracts.py` (PASS), `lint-imports` (4/0), `scripts/env_smoke.py` (PASS), the I-6 keyword grep, a relative-link check (0 broken). Verified honestly PENDING and **not** inferred: FOV / visible playing area, tracking quality vs. distance and the final ROI (Phase 03), grab-return bias (instrument), processing FPS, lighting conditions other than L0/L2. Not verified: no new physical measurement was made; the owner's visibility answers and blur grades are taken as recorded in the side-cars.

Verdict **PASS-WITH-CONDITIONS** (C-1 FOV, C-4/O-1, C-5), effective on the owner's signature (gate-procedure §4). On signature: RTM rows REQ-019, 022, 023, 024, 025, 026, 027, 101, 102 → IMPLEMENTED/MEASURED per their evidence pointers; tag `gate-02-pass`; Phase 03 may start with Task 03.1.

Signed (owner): ____________________, YYYY-MM-DD

Submitter's statement: everything in §1–§6 was executed in one assistant session on HW-01 on 2026-09-21 between 00:20 and 03:25 local time without a person at the camera. Inspected/run by the submitter: all tests (191 + 2 hardware), `ruff`, `validate_contracts.py`, `env_smoke.py`, `lint-imports`; 13 measurement run directories (10 COMPLETED, 3 ABORTED); the guide screenshot from the live webcam. Not done: anything requiring a person or an instrument (C-1, C-2 blur part), and no commit/tag/push.

## 10. Follow-up obligations (not conditions on this phase's criteria)

| Id | Obligation | Owner | By |
|---|---|---|---|
| F-1 | Sign §9, then tag `gate-02-pass`; also close the still-untagged Phase 00/01 gates (`gate-00-pass`, `gate-01-pass`) and Phase 00 C-3 / OQ-ENV-1/2. | Project owner | Phase 03 start |
| F-2 | `scripts/distance_benchmark.py`: check the return value of `cv2.imwrite` and refuse to proceed when `frame.png` cannot be written (defect found during C-1: a locked file left a stale frame beside a fresh side-car). | Phase 03 submitter (any code change is a Phase 03+ commit) | Phase 03 gate |
| F-3 | Move the config fragment's `exposure.value` to the owner's L2 selection (−5) or record why −6 stays, before the C-5 freeze. | Project owner | C-5 |
| F-4 | Any thesis citation of the dirty-tree runs (60 FPS attempt, 720p, auto-exposure, exposure inspection, latency) requires a clean-tree repeat under a described lighting condition. | Phase 18/21 submitters | their gates |

## 11. Review scope as instructed by the owner (2026-09-21)

1. Review every acceptance criterion against the actual evidence — done, §2 (no criterion weakened, none deleted).
2. Complete the integrity checklist per gate-procedure §3–§4 — done, §5 (no NO).
3. Record the verdict in §9 — done: PASS-WITH-CONDITIONS, effective on owner signature.
4. Preserve all PENDING items with their resolving phase; no FOV/tracking/bias value inferred — done (§2, §4, §7, §8).
5. Commit only the Phase 02 documentation changes; no tag, no push, no Phase 03 work.
