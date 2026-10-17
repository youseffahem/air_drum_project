# SpaceDrums project audit

Audit date: 17 October 2026 (Africa/Cairo). Scope: the existing working tree, including uncommitted work. This is a source and developer-evidence audit, not participant acceptance or a release gate.

## 1. Repository and inspection boundary

The initial branch is `main`, HEAD `188b4e3` (`feat: add acoustic sample support, kit layout preview UI, and developer demo tools`). There were 20 modified tracked files and 34 untracked files, including red-tip perception/tracking, native camera capture, exposure control, associated tests and documentation. No staged diff was present. These changes belong to the existing work and were preserved. No application source, configuration, tests or assets were edited for this presentation. No commit, push, reset or cleanup was performed.

`evidence/repository-snapshot.json` records the full HEAD, recent commit subjects, status and SHA-256 inventory. `evidence/existing-diff.patch` preserves the inspected tracked diff. `evidence/source-inventory.json` indexes all 207 Python source modules and their top-level symbols. There are 153 `test_*.py` files. Inventory is not a claim that every line received a formal code review. Detailed reading followed the current play loop, capture, perception, tracking, geometry, commit, calibration, UI and audio paths, with cross-checks of research/evaluation modules, tests, configs, ADRs and developer reports.

Unless a repository-root prefix is shown, source subpaths such as `app/`, `capture/` and `audio/` resolve under `src/spacedrums/`. Generic `report.json` and `observations.jsonl` filenames refer to per-session outputs.

Principal entry points are `src/spacedrums/app/play.py`, research runner `app/main.py`, calibration runner `app/calibrate.py`, the three root PowerShell launchers, and `scripts/`. Configuration fragments are under `configs/`, contracts under `schemas/` and `contracts/`, model/sample manifests under `assets/`, recorded developer evidence under ignored `data/` and `experiments/`. There is no root `README.md`; the package overview is `src/spacedrums/README.md`. Phase plans extend through final packaging, but plans are not completed deliverables.

## 2. Purpose, scope and evidence classes

SpaceDrums is a local, single-user, camera-based virtual drumming prototype and a research platform for causal strike anticipation. It maps two-dimensional image motion to virtual drum surfaces and local sample playback. Intended benefits include trying drumming without a physical kit and studying whether motion prediction can reduce perceived delay. Neither improved learning nor latency reduction has been demonstrated in a participant study.

Keep these classes separate: **implemented code**, **synthetic software checks**, **offline real recordings**, **developer live logs**, and **participant validation**. The latter is pending. `docs/reports/phase-18-final-evaluation.md` explicitly reports no confirmatory participant outcomes. `docs/gates/phase-19-gate.md` is preparation only. Phase 20–23 documents remain planned.

`docs/requirements/out-of-scope.md` excludes core cloud processing, multiple users, full-body tracking, mandatory depth, electronic sticks/IMUs, foot/kick tracking and core MIDI. Painted-tip operation is a permitted labeled marker condition, not proof of the markerless goal. A pose model used for standing calibration does not make full-body motion tracking an implemented playing feature. No mobile application or approved mobile-specific requirement was found in source, dependency/config manifests, discovery, requirements or phase plans.

## 3. Verified architecture and execution path

1. **Composition and configuration.** `app/play.py:play_config` merges prototype/product fragments, explicit developer geometry, optional red-tip settings and camera overrides, then validates the result. `run` owns lifecycle and logs. `play-spacedrums.ps1` calls it directly; `demo-spacedrums.ps1` adds `--demo --fingers`; `demo-sticks-spacedrums.ps1` adds `--demo --red-tips`.
2. **Capture.** `capture/backend.py:OpenCvCamera` and `capture/source.py:LiveFrameSource` use OpenCV and a background capture thread with a bounded queue, freshness/drop accounting and timestamps. `capture/native.py:NativeCapture` verifies native delivery and crops/downscales to the 640×480 tracking view. Current CLI default is native capture: request 1920×1080 to negotiate the HW-01 1280×720 mode, crop 960×720 at x=159, then downscale. This is not 1080p delivery. Standard fallback is explicit. `capture/exposure.py` guards low delivered FPS. `ReplayFrameSource` reads saved images and original timestamps without a camera.
3. **Perception alternatives.** `app/main.py:Perception` runs `hands/landmarker.py:HandLandmarker` and an endpoint estimator. `--fingers` substitutes `stick/visible.py:FingertipEndpointEstimator`: landmark 8 is the index tip, landmark 5 its origin. Without either mode flag, product play uses `VisibleEndpointEstimator` and visible image support around a hand-guided stick axis. `app/red_tip_perception.py:RedTipPerception` runs HSV color segmentation and temporal blob association for painted tips; hand inference is off unless `--hand-assist` is requested.
4. **Contracts and tracking.** `FrameSample`/`FrameView`, `HandObservation`, `StickObservation` and `EndpointEvidence` feed `app/pipeline.py:DecisionPipeline.step`. Frame IDs, timestamps and hand IDs must agree. `tracking/tracker.py:CausalTracker` maintains per-hand history and VALID/DEGRADED/INVALID/STALE behavior. Product measured output uses current accepted endpoints, while predicted gaps are degraded and cannot commit under the product settings.
5. **Strike and target selection.** Product mode requires active Arm A only. `geometry/strokes.py:MeasuredStrokeGeometry.observe` checks recent accepted measurements, downward speed/direction, minimum travel, gap history and top-edge intersection. The earliest eligible crossing selects one zone per uninterrupted downstroke. Rebound rearms it. `commit/policy.py:PerHandCommitPolicy.step` applies tracking status, frame-drop, episode and refractory gates before creating `CommittedStrike`.
6. **Audio.** `app/audio_out.py:AudioOutput.play` passes non-shadow commits to `audio/scheduler.py:AudioScheduler.schedule`. Zone `sample_id` and gain select a WAV or grouped variant. `CallbackMixer` queues polyphonic voices, starts within a buffer, clips output and counts underruns/late events. `SoundDeviceOutput` uses sounddevice/PortAudio. Stream health and recovery are implemented; recovery clears old voices.
7. **Display and logs.** `ui/stage.py:StageRenderer` draws the full kit, `ui/developer_demo.py:DemoOverlay` the diagnostic view and `ui/kit.py:render_kit` the product/calibration view. They consume frames and pipeline results; the UI does not generate artificial hits. `ui/preview_tone.py:PreviewTone` changes display brightness by default, not tracker input. `--tracking-tone auto` is a separate optional hand-model path. `observations.jsonl` and `report.json` store evidence, decisions and software timing.

The research runner additionally supports rule Arm B and model arms via `app/arms.py`, `prediction/model_arm.py`, streaming features and temporal model adapters. Those paths are not the current product demo's active inference path. Backend here means local Python orchestration, not a web API or remote server.

## 4. Implementation and limitations by component

| Component | What source proves | Status and limits |
|---|---|---|
| Camera and replay | Live/replay sources, queue/drop/timestamp diagnostics, native verification, exposure guard | Implemented; one HW-01 profile, light-dependent frame delivery and exposure blur |
| HAND | MediaPipe wrapper, identity tracking, fingertip estimator, replay integration | Implemented; hand visibility while gripping sticks is intermittent; a confidence value is not calibrated accuracy |
| Visible-stick mode | `stick/visible.py:VisibleEndpointEstimator` requires supported axis/endpoints and rejects temporal outliers | Implemented candidate; missing endpoints remain a live blocker |
| Red painted tips | `RedTipDetector`, `RedTipTracker`, `RedTipEndpointEstimator` and typed bridge | Implemented, uncommitted candidate; default red mode fails frequently on dark paint at playing distance |
| Dark-paint fallback | Optional pixel/blob constraints, contextual births and `DARK` evidence | Experimental, off by default; more coverage can include distractors and identity changes |
| Strike detection | Measured motion, intersection, one pad per stroke, rebound, commit gates | Implemented; physical recall, false hits and wrong-zone rate remain unverified |
| Calibration | `calib/automatic.py:AutomaticCalibration`: STAND, REACH, VERIFY, READY or RETRY; `calib/reach.py:fit_reach` | Machinery implemented; developer standing/reach attempts do not establish reliable independent acceptance |
| UI | Full seven-piece kit, four-pad guide, diagnostics, layout preview and saved layout YAML | Implemented desktop OpenCV UI; no web/mobile frontend |
| Audio | Hash-checked samples, gain curves, deterministic layers/round-robin, scheduler, polyphonic mixer and recovery | Implemented; current device audibility was not retested in this audit; physical action-to-sound delay remains unknown |
| Research AI | LightGBM training/adapter; PyTorch GRU/TCN, multi-task and extension code, export/parity, features/evaluation | Development implementations; no accepted participant-trained winning model or demonstrated superiority |
| Data/research machinery | Recording, labels/splits, evaluation, failure injection, preregistration locks and ablations | Implemented tools and synthetic/developer evidence; participant study, final integration/release acceptance pending |
| Mobile | No verified native app, mobile build or transport | Not implemented; approved scope unresolved |

### Important strike details

Product settings use `max_gap_s=0.115`, `min_travel=0.018`, `rebound=0.014` in ROI-normalized units and hand/zone refractory times 25/35 ms. These are candidate settings, not independently optimized human-performance thresholds. `configs/demo.professor.candidate.yaml` adds `lead_s=0.033`. With two downward samples, a projected near-future edge can trigger immediately. A stroke that stops short can therefore sound in developer demo mode. Normal product mode defaults to `lead_s=0`.

Missing, ambiguous, clipped or prediction-only red-tip states do not become measured endpoints. `OBSERVED`, `WEAK` and optional `DARK` can. Their configured confidences (0.9, 0.75, 0.8) are evidence classes, not estimated probabilities of correctness. LEFT/RIGHT red-tip slots are stable identity labels rather than guaranteed anatomical hands. Identity resets restart stroke history.

Lower-row selection requires approaching from the gap between rows. A continuous downstroke through an upper pad first consumes that stroke. This can explain a wrong intended drum without proving the implementation is free from other target-selection errors. A counted, time-aligned test is still required.

Calibration collects six strokes per pad with at least two per hand, fits geometry, then checks another set. Verification requires >=90% matched strokes, no wrong-zone matches, >=80% measured endpoint coverage and no leftover commits. These are internal checks against measured motion, not independent physical truth. **Audio starts in VERIFY**, after a fitted layout exists, before READY. RETRY stops the pipeline/audio. Developer demo bypasses calibration with a fixed guide and never establishes that calibration passed.

### Audio details

`play_config` chooses `assets/samples/acoustic-manifest.json` for `--demo --kit full` (Salamander bank) and `assets/samples/recorded-manifest.json` for other paths (TR-505 bank). `audio/bank.py:SampleBank.load` verifies sample hashes. `audio/variants.py:VariantSelector.pick` selects soft below gain 0.55 if available, otherwise hard, then rotates takes deterministically. The configured stream is 48 kHz, 128 frames, stereo output. 128/48000 = 2.67 ms is a buffer duration, **not total latency**. `OutputLatency.unmeasured()` carries a 0.0 scheduling placeholder and a PENDING flag. Neither `AUDIO OK`, a running stream, a commit counter nor a scheduled `AudioEvent` proves that a listener heard the right sound.

## 5. Tests and reproducibility checks

Fresh checks on 17 October use the existing `.venv` and current working tree. Results are summarized in `validation-results.md`, with full logs under `evidence/`.

- Full configured suite: `.venv\Scripts\python.exe -m pytest -ra`: **1 failed, 1,997 passed, 1 skipped, 139 warnings in 1,020.06 s**. `tests/product/test_full_kit.py::test_a_run_around_the_kit_sounds_each_piece_in_order` expected snare at index 5 but received tom2. A focused rerun also failed (4.63 s), confirming reproducibility in this tree. It uses synthetic swing frames and checks commit order; it does not validate physical audibility. No application fix was applied. Hardware tests remain opt-in (`SPACEDRUMS_HW_TESTS` unset). Tests are not a real-world accuracy measurement.
- Read-only lint: `.venv\Scripts\python.exe -m ruff check . --output-format concise`. **Fails with one E501** at `src/spacedrums/stick/visible.py:245` (113 characters vs 110). No autofix applied. Config excludes `.venv`, `data`, `experiments`.
- `.venv\Scripts\lint-imports.exe --no-cache`: **7 kept, 0 broken**, 198 analyzed files, 564 dependencies. The layer contract intentionally ignores two `features` imports of geometry zone types, as declared in `.importlinter`.
- `app.play --demo --fingers --check` and `--demo --red-tips --check`: model/sample assets hash verified, no devices opened. These preflights do not validate normal-mode pose initialization, live camera behavior, audibility or tracking accuracy.
- Running application replay screenshots were captured with `--no-audio`. An initial attempt to replay `dev-product-20261016-003327-975be6cd` failed because it has no `frames.jsonl`; a verified frame-bearing session was used instead. Nothing was manufactured to fill that gap.

Installed versions are in `evidence/environment.json` (Python 3.11.9; OpenCV 5.0.0.93, MediaPipe 1.0.1, NumPy 2.4.6, PyTorch 2.14.0+cpu, sounddevice 0.5.6 in this environment). `pyproject.toml` omits MediaPipe although `requirements.in` includes it and runtime imports require it. A fresh install from package metadata alone may be incomplete. Dependency declarations are broader than the pinned environment; do not call this a verified portable release.

## 6. Measurements and their conditions

These are existing developer records inspected during the audit. New replay runs occurred alongside tests and are not used as performance benchmarks.

| Evidence | Result | Conditions and interpretation |
|---|---|---|
| `experiments/camera-quality-20261016-compare-exp5-redtips/report.json` | Standard 30.15 / 30.20 FPS; native 30.16 / 30.15 FPS | HW-01, DirectShow, exposure -5, two 10 s trials each, alternating arms, no player, red-tip processing; capture capability, not playable accuracy |
| Same A/B, native vs standard | Native crop/downscale about 3.4–3.5 ms median; hand-over about 3.6–3.7 ms vs 0.1 ms | Pipeline stage durations, not physical latency; see source report and `docs/perf/camera-quality-native-720p.md` |
| `experiments/red-tip-lit/summary.json` | 39/572 measured LEFT, 9/572 RIGHT (6.8% / 1.6%); detector/tracker p50 2.86 ms, p95 4.19 ms | Offline recording `dev-product-20261017-005812-ccdb76de`, default red-only settings, 640×480 frames; `accuracy_vs_labels=null`. Folder name “lit” does not establish good lighting or successful tracking |
| `experiments/red-tip-dark/summary.json` | 406/572 LEFT, 474/572 RIGHT (71.0% / 82.9%); p50 9.18 ms, p95 12.87 ms | Same recording, optional dark mode. No labels. More measured frames can include wrong objects. This is coverage, not accuracy |
| `.../v3-distance/distance-default-test/summary.json` | 0/28 labeled cap matches | Older 622-frame recording `dev-product-20261016-225435-80f3552c`; 27 labeled test frames, match radius 12 px |
| `.../v3-distance/distance-dark-test/summary.json` | 23/28 matches; matched error p50 1.83 px, p95 4.62 px; 15 measured tips near no label | Assistant-derived silhouette labels, caps against wall only. Dark defaults used the whole recording, so this is not independent held-out generalization. No strike/crossing accuracy claim |
| `data/dev-product/dev-product-20261017-005812-ccdb76de/report.json` | 23.34 source-timeline FPS, 1 commit, audio state RUNNING | Live developer recording with synchronous PNG writes, default red mode; no counted truth or audibility confirmation |
| `data/dev-product/dev-product-20261017-010510-6b507f56/report.json` | 30.14 FPS, 56 commits, audio state RUNNING, `action_to_sound_ms=null` | Live dark-mode developer log, no raw frames. Count is software events, not 56 correct hits |

Full source paths and copied analysis summaries are in `evidence/`. No FPS/latency ranking should combine no-player capture trials, offline replay compute and live recording as equivalent workloads. The built-in microphone click pilot described by Phase 18 failed (0/40 pairs), so accepted physical latency evidence is still missing.

## 7. Documentation contradictions and integration risks

| Claim or stale description | Current evidence / resolution for this package |
|---|---|
| Standing-product guide describes `demo-spacedrums.ps1` as visible endpoints and four pads | Launcher sets `--fingers`; parser defaults to `--kit full` with seven zones. Show current code behavior |
| Demo guide says thresholds unchanged | Demo fragment sets `lead_s=0.033`; disclose predictive edge triggering and stop-short risk |
| Product comments imply no sound until calibration succeeds | `play.run` starts audio at VERIFY, before READY. Explain fitted-layout verification playback |
| Older camera text says 640×480 only, or native preview remains darkened | Current CLI native default and product preview settings supersede those paragraphs; tracking remains 640×480 |
| Package README calls implemented packages “PLANNED stubs”; tests README says “Everything else PLANNED” | Actual files and tests implement later phases. Status paragraphs are stale |
| Early red-tip report sections say real cap accuracy has never been measured | Later distance section contains limited assistant-labeled offline analysis; latest 572-frame recording remains unlabeled |
| Phase 18 threats say per-arm settings integration is pending | `DecisionPipeline` supports `live_arm_settings`, `app/arms.py` and `tests/app/test_per_arm_settings.py` exist. Code implementation does not close the participant evaluation gate |
| Historic no-marker research scope vs red-tip demo | MARKER condition is explicit in red-tip config, estimator and records; never present it as markerless |
| Frame report FPS near 30 implies acceptable music interaction | Raw capture rate excludes correctness and physical response delay; those remain unresolved |

No frontend-to-server API exists to connect a mobile client. Research model configs/feature layouts require compatible verified manifests and zone hashes. Calibration, hand visibility and timestamp/queue gaps can prevent accepted strike candidates even when the camera renders smoothly. Dark-mode association may accept the wrong object. Independent intent labels are missing, so incorrect drum-zone selection is unresolved as a validation question rather than assigned a fabricated error rate.

## 8. Missing work and next steps

First label both true tips and intended strikes in representative recorded sessions, including occlusion, crossing, body backgrounds and non-strike movement. Separate tuning and evaluation recordings. Compare default red, optional dark and HAND modes with the same kit and conditions. Use precision/recall, false hits per minute, wrong-zone rate, identity swaps and coverage separately. Diagnose which pipeline gate rejected each missed strike.

Then repeat standing/reach verification with independent counted truth, test the fixed guide versus fitted layouts, and decide the demo look-ahead policy. Measure physical action-to-sound delay with an accepted external reference, including measurement uncertainty. Retain per-stage software timing but label it separately. Run regression/integration checks after actual fixes. Participant protocol approvals, dataset collection and model selection precede confirmatory claims. Portable packaging and mobile scope are future decisions, not completed work.

## 9. Claims prohibited by the available evidence

- “The system is complete, production-ready, fully calibrated or validated with users.”
- “Red-tip tracking is markerless,” “dark mode solves tracking,” or “coverage is accuracy.”
- “A test pass count proves real-world strike accuracy.”
- “The demo uses a participant-trained neural model to predict hits.”
- “30 FPS is guaranteed during play,” “the camera delivers 1080p/60 FPS,” or “all frames are processed.”
- “Latency is zero/2.7 ms,” “sound precedes impact,” or “prediction reduces physical latency.”
- “Every displayed hit was correct and audible,” or an invented wrong-zone/error rate.
- “Mobile is implemented/approved,” or named individual authorship inferred from Git.
- “A fixed guide is a passed calibration,” or “the demo waits for a measured crossing in every case.”
