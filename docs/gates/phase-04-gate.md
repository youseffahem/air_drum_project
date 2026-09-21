# Phase 04 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 04 — Virtual Drum Geometry & Audio Engine |
| Phase document | `phases/phase-04-drum-geometry-audio.md` |
| Submitter | Codex acting as developer for the project owner |
| Reviewer(s) | Project owner — review pending |
| Review date | 2026-09-21 |
| Code state | base `d6bc0ba97369f53e6ed12bd3e9c5ecf0e6974321` / dirty: yes (owner required no commit) |
| **Verdict** | **PROPOSED FAIL — owner verdict pending** |

The submitter cannot pass this gate. The proposed verdict is FAIL because acceptance criterion 6 is
NOT MET and integrity item I-11 is NO. Phase 05 and later work must not start.

## 1. Artefacts produced

| Artefact (from phase document) | Path | Status label | Present? |
|---|---|---|---|
| Geometry package | `src/spacedrums/geometry/` | IMPLEMENTED | yes |
| Audio package | `src/spacedrums/audio/` | IMPLEMENTED | yes |
| MVP and V1 candidate layouts | `configs/zones/mvp4.candidate.yaml`, `configs/zones/v1-7.candidate.yaml` | IMPLEMENTED; values candidate | yes |
| Sample assets, manifests, and licences | `assets/samples/` | IMPLEMENTED | yes; runtime WAVs are manifest-only/ignored |
| Audio-latency measurement machinery | `scripts/measure_audio_latency.py` | IMPLEMENTED | yes |
| Accepted physical audio-output latency | `docs/audio-profile-hw01-realtek.md` | PENDING | no |
| Geometry/audio compute measurement | `scripts/measure_geometry_audio_compute.py`, run `20260921-1536-p04-geometry-schedule-cost` | MEASURED development evidence | yes |
| Layout rendering and screenshot | `scripts/render_zone_layout.py`, `docs/figures/phase-04/mvp4-layout-synthetic.png` | IMPLEMENTED; MEASURED development evidence | yes |
| Phase report | `docs/reports/phase-04-geometry-audio.md` | IMPLEMENTED | yes |
| Gate record | `docs/gates/phase-04-gate.md` | IMPLEMENTED; reviewer decision PENDING | yes |

## 2. Acceptance criteria

| # | Criterion (verbatim from phase document) | Evidence (file / test id / run id) | Status |
|---|---|---|---|
| 1 | Zone registry loads MVP and V1 layouts; kick-compatible enum present; hand-agnostic default. | `tests/geometry/test_zones.py`, `tests/config/test_loader.py`; contract validation PASS | MET |
| 2 | Geometry tests pass, including upward-crossing rejection and one-strike-per-episode. | `tests/geometry/test_intersect.py`; focused and full pytest results in §3 | MET |
| 3 | Sub-frame crossing time implemented and tested against analytic ground truth. | `tests/geometry/test_impact.py`; asserted absolute error at most 1e-12 seconds on synthetic analytic cases | MET |
| 4 | Predicted-trajectory intersection yields `t_impact_pred`/`TTI` and matches the reactive path on identical input. | `tests/geometry/test_intersect.py` predicted/reactive equivalence tests | MET |
| 5 | Audio engine plays scheduled samples with sample-accurate placement; polyphony works; late events handled. | `tests/audio/test_device_mixer.py`, `tests/audio/test_scheduler_integration.py` | MET |
| 6 | Audio output latency measured and documented per buffer size; chosen `B` justified. | `docs/audio-profile-hw01-realtek.md`; attempted runs were rejected because capture was incomplete, inconsistent, or not known post-DAC | **NOT MET** |

## 3. Tests

All commands ran locally on HW-01 on 2026-09-21 against the dirty Phase 04 working tree. The table
records the **final** run, executed after the patch-integrity normalization and final diff review described in §3.1;
every earlier run gave the same pass/fail outcome for every command.

| Test id / command | What it checks | Result |
|---|---|---|
| `.venv\\Scripts\\python.exe -m pytest tests\\geometry tests\\audio tests\\config tests\\contracts tests\\scripts\\test_measurement_scripts.py -ra` | Phase 04 implementation, contracts, config, and script self-tests | PASS — 208 passed in 71.56 s |
| `.venv\\Scripts\\python.exe -m pytest -ra` | Project-wide regression suite | PASS — 402 passed, 1 skipped in 102.08 s; skip is the opt-in webcam hardware test (`SPACEDRUMS_HW_TESTS=1`) |
| `.venv\\Scripts\\ruff.exe check .` | Static style/lint (declared project check) | PASS — All checks passed |
| `.venv\\Scripts\\lint-imports.exe` | Architecture/import contracts | PASS — 50 files, 103 dependencies, 4 contracts kept, 0 broken |
| `.venv\\Scripts\\python.exe scripts\\validate_contracts.py` | JSON schemas and resolved candidate config | PASS — 15 schemas loaded; `example.candidate.yaml` accepted; reserved `FOOT` trigger rejected |
| `.venv\\Scripts\\python.exe scripts\\env_smoke.py` | Python/package/runtime smoke and run-log schema | PASS — Python 3.11.9; CPU PyTorch environment verified |
| `.venv\\Scripts\\python.exe scripts\\fetch_hand_landmarker_model.py --verify` | Existing model asset hash | PASS — `sha256:fbc2a300…07cde1`, 7,819,105 bytes |
| `.venv\\Scripts\\python.exe scripts\\fetch_drum_samples.py --verify` | Seven local prerecorded WAV hashes | PASS — 7/7 OK |
| `git add -N . && git diff --check` (then `git reset`) | Whitespace/CRLF errors in tracked **and** untracked Phase 04 files | PASS — exit 0, no output |
| `.venv\\Scripts\\python.exe scripts\\generate_sample_bank.py --output <scratch>` then byte compare | Synthetic bank generator determinism | PASS — `manifest.json` and all 7 synthetic WAVs byte-identical to `assets/samples/` |
| `.venv\\Scripts\\ruff.exe format --check .` | **Informational only** — not a declared project check; Phase 01 gate S-6 treated `ruff format` as cosmetic and out of scope | 59 files would be reformatted (58 `.py`, 1 `.md`); 49 predate Phase 04; no action taken |

### 3.1 Patch-integrity normalization (final audit step)

| Finding | Fix | Verification |
|---|---|---|
| Mixed CRLF/LF endings inside four tracked files edited by Phase 04 (`src/spacedrums/contracts/records.py`, `contracts/__init__.py`, `contracts/interfaces.py`, `tests/contracts/test_config_schema.py`; all CRLF in HEAD). | Whole-file normalization to LF (done before the interruption). `test_config_schema.py` was then found to carry no substantive change and was restored to HEAD in the final review. | `git diff --check` PASS. The three converted files show inflated `git diff` line counts; review them with `git diff --ignore-cr-at-eol` (substantive: records +394/−44, interfaces +40/−5, `__init__` +19/−1). |
| `src/spacedrums/contracts/schema.py` differed from HEAD only by `ruff format`-style line wrapping (Phase 01 file). | Restored to HEAD in the final review, following Phase 01 gate S-6. | `git status` no longer lists it; `ruff check`, `lint-imports`, pytest re-run PASS. |
| All new Phase 04 `.py`/`.yaml`/`.md`/`.json` files. | Written LF, no trailing whitespace. | Byte scan: no CR, no trailing whitespace, final newline present. |
| `assets/samples/manifest.json` (new, tracked) was CRLF. Root cause: `Path.write_text` without `newline="\n"` emits CRLF on Windows. | Manifest normalized to LF; `scripts/generate_sample_bank.py` now passes `newline="\n"`. | Regenerated bank is byte-identical to the tracked manifest and local WAVs; `tests/audio/test_bank_gain.py`, `tests/geometry/test_zones.py`, `tests/scripts/test_measurement_scripts.py` — 20 passed. |
| `docs/audio-profile-hw01-realtek.md` and `docs/reports/phase-04-geometry-audio.md` used trailing double-space Markdown hard breaks (line 3). | Replaced with trailing-backslash hard breaks. | `git diff --check` PASS. |
| 10 pre-existing tracked files (e.g. `pyproject.toml`, `docs/requirements/rtm.md`, `src/spacedrums/config/loader.py`) are CRLF **in HEAD** (121/214 HEAD blobs are CRLF). | Left as-is: their Phase 04 edits match HEAD's ending style line-for-line, so converting them would create whole-file churn unrelated to this phase. | `git diff --check` PASS on these files; no mixed endings introduced. |

### 3.2 Experiment run inventory

All 14 `experiments/*-p04-*` directories are accounted for. The 9 cited runs in §4 and the audio
profile exist on disk with `run.json`. Two directories are uncited elsewhere and are recorded here:

| Run id | What it is | Disposition |
|---|---|---|
| `20260921-1528-p04-audio-b128` | First Stereo Mix attempt (B=128): 35/35 detections but bimodal 0.0018 s / 0.1218 s, spread 0.1200 s. Its `latency_trials.json` self-labels `MEASURED` because it predates the consistency guard. | **Rejected**; now listed in the audio profile attempt table; not latency evidence. |
| `20260921-1535-p04-geometry-schedule-cost` | Aborted first compute-cost run: `config.resolved.yaml` and empty `stdout.log` only, no `run.json`. | Aborted; superseded by `20260921-1536-p04-geometry-schedule-cost`. |

## 4. Measurements produced in this phase

These are development measurements only because their run records correctly say `git_dirty: true`.
They do not satisfy I-11 and are not promoted to validated results.

| Quantity | Label | Value | run_id | Method | Hardware id |
|---|---|---:|---|---|---|
| Crossing-time numerical error | SYNTHETIC analytic test evidence | <= 1e-12 s assertion bound | pytest evidence, no experiment run | closed-form synthetic crossings | HW-01 |
| Geometry + scheduling compute p50 / p95 | MEASURED development; SYNTHETIC input | 0.03970 / 0.07280 ms | `20260921-1536-p04-geometry-schedule-cost` | 5,000 synthetic trajectory intersections plus scheduling calls | HW-01 |
| Zone-overlay compute p50 / p95 | MEASURED development; SYNTHETIC input | 2.7022 / 4.9779 ms | `20260921-1527-p04-layout-render` | 500 renders on a 960x720 blank ROI | HW-01 |
| Device-clock regression residual RMS | MEASURED diagnostic only | 0.004300 s over 2,888 callback samples | `20260921-1537-p04-audio-loop-b128` | actual PortAudio input/output callback clock fit; tap location unknown | HW-01 |
| Callback xrun observations | MEASURED diagnostic only | 0 per short 35-click attempt at B=64/128/256/512 | run ids in `docs/audio-profile-hw01-realtek.md` | PortAudio diagnostic attempts | HW-01 |
| Detector injected-delay recovery | SYNTHETIC self-test | 0.017 s, 35/35 detections, zero spread for each tested buffer | `20260921-1532-p04-audio-synth-b64`, `...b128`, `...b256`, `...b512` | in-memory injected delay | HW-01 |
| Physical audio output latency | PENDING | no accepted value | rejected run ids in audio profile | no synchronized, known post-DAC capture was available | HW-01 |
| Selected audio buffer | PENDING | none | N/A | requires accepted latency and underrun evidence | HW-01 |

## 5. Integrity checklist

| # | Item | Result | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled Target / Measured / Historical / Pending | YES | §4 and both Phase 04 reports label synthetic, diagnostic, development, candidate, and pending values and cite run ids where applicable. |
| I-2 | No implementation claim without tests | YES | Focused suite 208 passed; project suite 402 passed, 1 hardware test skipped; commands in §3. |
| I-3 | No causal component consumes future frames | YES | Geometry consumes adjacent supplied points; `tests/geometry/test_intersect.py` includes prefix-invariance and observed/predicted shared-path checks. |
| I-4 | No fabricated data | YES | Synthetic inputs are named and labelled; actual attempts retain their failed/pending status; no participant recording or measurement exists. |
| I-5 | FPS reported as native only | N/A | Phase 04 makes no FPS claim. |
| I-6 | No "latency reduced" claim before Phase 18 | YES | Phase artefacts make no end-to-end reduction or before-impact guarantee. |
| I-7 | Marker condition clearly labelled | N/A | Phase 04 used neither coloured markers nor a marker condition. |
| I-8 | Participant-level split confirmed for ML results | N/A | No participants, dataset split, training, or ML result is in scope. |
| I-9 | Scope respected | YES | No Phase 05 commit/refractory logic, anticipation, MIDI, kick implementation, or realistic-kit UI was added. |
| I-10 | Status vocabulary correct | YES | Implemented components, measured development diagnostics, and pending physical evidence are distinguished; phase status matches proposed FAIL. |
| I-11 | Reproducibility fields complete | **NO** | Cited run JSON/config/hash fields validate, but every run says `git_dirty: true` because the owner prohibited a commit. Clean-tree reproduction is impossible in this run. |
| I-12 | Limitations stated | YES | Phase report and audio profile state the hardware, tap-point, consistency, dirty-tree, physical-evidence, and generalisation limitations. |

## 6. Deviations from the phase document

| What | Why | Impact on dependents |
|---|---|---|
| Valid physical output-latency table and evidence-based buffer selection were not produced. | Available microphone capture was incomplete/inconsistent; Stereo Mix had an unknown/upstream tap point and cannot establish post-DAC output time. | Blocking: acceptance criterion 6 is NOT MET; `t_audio_out` and buffer selection remain unavailable. |
| Audio measurement attempts used 35 clicks instead of the candidate minimum of 30. | Provides margin for detection loss without weakening the minimum. | None; rejected results remain rejected. |
| Runtime sample WAVs are manifest-only and git-ignored. | Matches the existing asset policy for downloaded binary assets; exact hashes and a restore/verify script are tracked. | Fresh checkouts must run `scripts/fetch_drum_samples.py`; runtime loading refuses a hash mismatch. |
| Candidate layouts live in `configs/zones/` rather than duplicated under `src/spacedrums/geometry/layouts/`. | Project configuration belongs under the established `configs/` hierarchy and is loaded through the Phase 01 schema. | None; paths are explicit and tested. |
| `scripts/measure_audio_latency.py` labels a *consistent* `--method microphone` run `MEASURED` with status `MEASURED_WITH_MICROPHONE_PATH_LIMITATION`. | The label denotes acoustic-onset-path latency (includes input path and propagation); it is not, and must never be promoted as, post-DAC `t_audio_out`. No microphone run passed the consistency guard, so no such label exists in any run record. | None for this gate; criterion 6 still requires a known post-DAC capture. |
| All experiment runs are dirty-tree evidence. | The owner explicitly required no commit, tag, or push. | Blocking for I-11 and gate-grade promotion; test outcomes still describe the inspected working tree. |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolution owner / point |
|---|---|---|
| Obtain synchronized known post-DAC output capture; repeat at least 30 events per candidate buffer; report median/p90 and underruns. | PENDING | Owner provides/identifies capture path; Phase 04 remains open until rerun |
| Select buffer `B` from accepted latency-versus-underrun evidence using a predeclared underrun criterion. | Pending Benchmark | Phase 04 gate rerun |
| Reproduce cited measurements from a clean committed tree. | PENDING | Owner permits/reviews a commit, then Phase 04 gate rerun |
| Decide whether the seventh V1 zone remains Ride or becomes a second cymbal. | Open Question | Project owner before layout freeze |
| Decide whether tilted cymbal surfaces improve use. | To Be Experimentally Determined | Phase 05 playtest, only after Phase 04 passes |
| Validate `v_min`, candidate positions/sizes, gain mapping, and linear versus quadratic interpolation. | To Be Experimentally Determined | Phases 05/07/11/14 as already assigned; not performed here |

## 8. Conditions

N/A — proposed verdict is FAIL, not PASS-WITH-CONDITIONS. The blocking items are in §7.

## 9. Reviewer statement

Submitter evidence assembly is complete. The project owner has not yet independently reviewed or
signed this record, and the submitter does not claim authority to pass it. Automated implementation
and regression evidence is strong for criteria 1–5. Criterion 6 lacks an accepted post-DAC
measurement and a justified buffer choice, and I-11 is NO because all runs are from a dirty tree.
The honest proposed verdict is FAIL. No Phase 05 work was started.

Signed: **PENDING — project owner**, 2026-09-21
