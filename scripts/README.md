# scripts/

One-off tools. Run from the repository root with the development venv (`.venv\Scripts\python.exe`).

## Phase 14

- `python -m spacedrums.app.calibrate ...` is the wizard itself (see `docs/user/calibration.md`).
- `calibration_repeatability.py --calibrations <files> --output-dir <dir> [--tolerance 0.05]` reports
  per-hand `L_prior` spread and consecutive-pair agreement, layout, envelope, duration and validation
  spread for repeated calibrations of one subject. MEASURED only when every input is a live
  calibration; SYNTHETIC inputs make it a machinery check.
- `render_calibration.py --calibration <file> --output-dir <dir> [--frame <png>]` renders the
  calibrated layout and the review screens (Task 14.4 screenshots).
- `verify_phase14.py [--require-clean] --executor-model <m> --executor-effort <e>` runs the full
  gate suite plus the Phase 14 machinery (SYNTHETIC wizard, session/metadata hash, zero-drift
  regression, pinned model on a calibrated layout, triggers, SYNTHETIC repeatability, replay
  diagnostics). `_p14.py` holds its checks. No script issues a verdict or commits.

## Phase 13

- `parity_test.py --config <resolved-yaml> --plan <json> --output <new-dir>` runs
  TEST-PARITY-1 and raw-image TEST-CAUSAL-1. A developer plan declares
  `source_kind: DEV_CAPTURE` and `sessions: [{id, path, kind: DEV_CAPTURE}, ...]`.
  A participant plan additionally supplies `fold_manifest` (the reviewed
  `cv_folds.json`) and integer `fold`; it must list every train/validation session
  of that fold plus developer sessions. No plan labels synthetic data as a participant.
- `live_latency.py --config <yaml> --source live|replay --output <new-dir>` records
  the app loop, switches from A active to configured C halfway through the requested
  frame count, and reports inference/software stamps. Use `--session-dir` for replay,
  `--max-frames` and `--switch-frame` for block size. Replay is explicitly not live
  timing. Audio scheduling is logged with the device disabled.
- `phase13_faults.py --config <yaml> --output <new-dir>` records six SYNTHETIC
  injected-fault cases with controlled clocks and zero transition-frame commits.
- `verify_phase13.py --parity-config <yaml> --plan <json> [--require-clean]`
  runs the full executable gate suite and final raw replay/timing/fault evidence.
  `--require-clean` is the required follow-up after the owner commits. No script
  issues the research gate verdict, commits, tags, pushes, or starts another phase.

Phase 13 reports: `docs/reports/phase-13-parity.md`, `phase-13-live-timing.md`.
Full phase status and owner actions: `docs/gates/phase-13-gate.md`.

| Script | Phase | Purpose |
|---|---|---|
| `env_smoke.py` | 00 | environment import + experiment-log schema check |
| `validate_contracts.py` | 01 | schema self-check (`RESULT: PASS|FAIL`) |
| `_runlog.py` | 02 | shared experiment-log writer for the measurement scripts (run dir, `run.json`, `config.resolved.yaml`, `stdout.log`; replaced by `eval` in Phase 09) |
| `enumerate_cameras.py` | 02 (Task 02.1) | cameras, backends, candidate modes — *advertised*, not measured |
| `measure_fps.py` | 02 (02.4 + 02.2) | native delivered FPS, jitter, drops/duplicates, timestamp-mapping residuals, capture-thread CPU per requested mode |
| `measure_capture_latency.py` | 02 (02.8) | screen-flash capture-latency method (upper bound; see `docs/protocols/capture-latency-flash-method.md`) |
| `exposure_blur_check.py` | 02 (02.5) | `inspect` exposure controls (machine); `record` / `analyze` a stick swing for the blur check (needs a person) |
| `show_guide.py` | 02 (02.6) | live "stand here" guide window + screenshot |
| `distance_benchmark.py` | 02 (02.7) | capture + pixel-size measurement per user distance (needs a person) |
| `fetch_hand_landmarker_model.py` | 03 (03.1) | one-time download of the MediaPipe Hand Landmarker task file into `assets/models/` + SHA-256 manifest; `--verify` is offline (ADR-0014) |
| `_devcapture.py` | 03 | replay reader for `data/dev-captures/<name>/` (recorded `t_capture`, `timestamp_source = REPLAY`); script helper, promoted to `capture.ReplayFrameSource` by Phase 09/13 |
| `benchmark_tip_methods.py` | 03 (03.10, 03.11, 03.13, 03.15) | all three tip methods + one tracker per hand per method on the same replayed frames; per-method rates, agreement, tracker traces, distance-still rows (`--distance`), overlays; tip error only where `tools/annotate_tip.py` annotations exist (else PENDING) |
| `measure_stage_latency.py` | 03 (03.14) | per-stage processing time (hands, stick per method, tracking) on a dev capture replayed from memory; sum vs frame period |
| `hands_landmark_check.py` | 03 (03.1, 03.2) | estimator wrapper + identity assignment on dev captures: per-frame timing, presence per hand (N reported), schema validation of every record, identity events/rates (`--identity-mode RAW\|TEMPORAL`), overlay PNG; `--synthetic` self-test (incl. a SYNTHETIC crossing) |
| `fetch_drum_samples.py` | 04 (04.6) | fetch or offline-verify the hash-pinned public-domain prerecorded TR-505 runtime bank |
| `generate_sample_bank.py` | 04 (04.6) | regenerate deterministic SYNTHETIC WAV fixtures used only by tests |
| `measure_audio_latency.py` | 04 (04.7, 04.9) | self-test the detector with injected delay or attempt synchronized microphone/digital-loopback output-latency capture; rejected attempts remain PENDING |
| `measure_geometry_audio_compute.py` | 04 (04.3, 04.8) | profile geometry intersection plus scheduling on labelled SYNTHETIC trajectories |
| `render_zone_layout.py` | 04 (04.11) | render candidate zones/surfaces/normals on a SYNTHETIC blank ROI and profile overlay cost |
| `_p05.py` | 05 | shared helper for the Phase 05 scripts (runs `spacedrums.app.main` on SYNTHETIC scenarios in record mode; hit-type table) |
| `playability_session.py` | 05 (05.7) | `--live`: guided 16-segment hit-type protocol in record mode (needs a person with sticks); `--synthetic`: self-test through every synthetic scenario |
| `induced_loss_test.py` | 05 (05.8) | `--live`: occlusion safety test on a recorded session (needs a person); `--synthetic`: 100/200/300/500 ms occlusions injected, zero non-VALID commits asserted |
| `timing_summary.py` | 05 (05.4, 05.9) | README §5.3 decomposition of a session's `timing.jsonl` with labels and the `L_sys_est` term list (`L_sys_est` PENDING until Phase 04's audio latency is measured) |
| `shadow_compare.py` | 05 (05.10) | informal B-vs-A comparison on a session (lead time, commit advance, timing error; "developer sanity check — not an experimental result") |
| `_p06.py` | 06 | shared helper for the Phase 06 scripts: metadata options → `SessionMetadata`, SYNTHETIC full-protocol observation sequence, git provenance |
| `record_session.py` | 06 (06.1, 06.10) | recording tool: `--live --kind PARTICIPANT\|PILOT\|DEV_CAPTURE …` (PERSON-DEPENDENT; guided protocol, cues, markers, quick checks, `metadata.json`, optional microphone); `--synthetic` full-protocol self-test (SYNTHETIC click track with `--pad-zone`); `--devcapture <name>` DEV CAPTURE ingest check; `--verify` runs the verification |
| `session_checklist.py` | 06 (06.5) | files the operator checklist answers as `<session_dir>/checklist.json` (never pre-filled) |
| `verify_session.py` | 06 (06.7, 06.8) | post-session verification → `verify.json`: integrity checks, quality report, per-take verdicts, `ACCEPT \| REVIEW \| QUARANTINE`, exclusion records (thresholds = candidates) |
| `build_raw_manifest.py` | 06 (06.9) | `build <version>` (kind-gated: participant / pilot / self-test), `check <manifest>` (re-hash), `withdraw` (withdrawal record); refuses an empty participant manifest |
| `regenerate_session.py` | 06 (06.3) | re-track a session from its raw PNG frames (`producer = REGENERATED`) and compare the derived streams: BIT-IDENTICAL / DECISION-IDENTICAL (numeric tolerance) / DIFFERENT |
| `rule_baseline_sensitivity.py` | 05 (05.2, 05.6) | SYNTHETIC sensitivity grid of the rule arm (motion model × filter × τ_commit × p_commit); not tuning |
| `render_session_frames.py` | 05 | render commit/candidate frames of a recorded session with zones, tips and predictions for manual review |
| `_p07.py` | 07 | shared helper for the Phase 07 scripts: paths, dataset/labels version options, thresholds and smoother construction, session/label discovery, git provenance |
| `_p07_examples.py` | 07 | regenerate `schemas/examples/{label-record,reference-track,label-set,label-review,split-file,dataset-manifest}.valid.example.json` from the real producers (SYNTHETIC) |
| `build_labels.py` | 07 (07.2, 07.3) | generate a session's label set: causal track copy + NON-CAUSAL reference track + `labels.jsonl` + `labels.meta.json`; `--synthetic` self-test, `--check-determinism`, `--validate`; kind-gated (a SYNTHETIC / DEV CAPTURE session can only enter `ds-v0.0-selftest*`) |
| `validate_labels.py` | 07 (07.7) | label validator (`RESULT: PASS\|FAIL`): referential integrity, times, episodes, quarantine, provenance/version, non-causality, `has_phys_gt` invariant, track separation; `--selftest` injects every failure mode and asserts it is caught |
| `label_stats.py` | 07 (07.9) | label statistics grouped by `source_kind` and never summed across kinds; writes `docs/reports/phase-07-label-stats.md` |
| `build_splits.py` | 07 (07.8) | participant-level splits under rule `P07-SPLIT-1` (ADR-0021); `--plan` prints the rule table, `--selftest` exercises the leakage checks and the refusals; refuses to write a participant split while `P = 0` |
| `build_dataset_manifest.py` | 07 (07.10) | `build` / `check` / `card` / `selftest` for a `ds-v*` labelled dataset; kind-gated, one `labels_hash` per dataset, empty participant manifest refused; `card --pending` renders the card of a dataset that does not exist yet |
| `acoustic_onset.py` | 07 (07.6) | pair microphone onsets with pad-zone labels and report `t_impact_phys - t_impact_est`; PENDING with a reason where no microphone track exists; `--selftest` on a SYNTHETIC click track with an injected offset |
| `subframe_interpolation.py` | 07 (07.4) | linear vs quadratic sub-frame crossing comparison against the analytic crossing of SYNTHETIC strokes, under a pre-declared decision rule (ADR-0020) |
| `reference_smoother_check.py` | 07 (07.2) | how each candidate reference smoother treats the velocity reversal at impact: entry survival, crossing bias/spread, depth error (SYNTHETIC) |

`tools/review_labels.py` (Task 07.5) is the label review / QC tool: frame scrub with reference-tip, causal-tip, zone, impact-surface and `t_impact_est` overlays, accept / reject / adjust / defer / note keys, an append-only review log, and `--agreement` (Cohen's kappa on presence, |dt| on timing). `--selftest` runs a scripted, non-interactive pass so the round-trip is testable without a person; its numbers are SYNTHETIC machinery evidence and are never inter-annotator agreement. `tools/annotate_tip.py` (Task 03.10) is the manual tip-annotation tool (person-dependent; `--synthetic` writes a labelled SYNTHETIC self-test file the benchmark refuses by default). Every measurement script has a `--synthetic` self-test mode used by `tests/scripts/`; real runs write `experiments/<YYYYMMDD>-<HHMM>-<slug>/` (git-ignored) and their numbers are quoted with the run id in the camera profile.

## Phase 08 feature tools

`build_features.py` and `compute_norm_stats.py` accept a frozen participant manifest/split pair,
or `--synthetic-fixture` for an explicitly labelled in-memory UNIT TEST fixture.
Single existing DEV/SYNTHETIC session diagnostics use `--session PATH --labels PATH --selftest`.
All runs require explicit `--n --k --h --h-max --stride --g-win --out`; existing output directories
are not overwritten. `feature_latency.py --synthetic` measures CPU extraction cost.
`verify_phase08.py --require-clean` executes the complete post-owner-commit gate verification
without altering Git history. Omit `--require-clean` only for honest development verification.
See `docs/features/feature-schema-v1.md` and the Phase 08 gate for exact commands and limitations.

## Phase 09 evaluation tools

`eval_baselines.py` replays one verified session through A and the B CV/CA commit grid,
writing per-setting results, Parquet/JSONL events, a W sweep and a lead/FP plot.
`train_gbdt.py` trains LightGBM heads per Phase 08 fold from train only, selecting
binary hyperparameters on validation only. `gbdt_sample_diagnostics.py` reports
window-level validation diagnostics; these are not event-replay measurements.
`gbdt_fixture_replay.py` exercises both modes end to end on the Phase 08 in-memory
synthetic fixture. `eval_gbdt.py` applies a fold model in direct and trajectory modes through the same
replay harness and refuses held-out test evaluation without a validation operating
point and frozen W. `gbdt_latency.py` measures batch-one CPU inference for all heads.
`verify_phase09.py` runs the available self-test/developer verification and writes a
schema-valid experiment log. Participant evaluation remains gated on reviewed
`ds-v1.0` folds and Phase 08 normalization exports.

## Phase 10 temporal development tools

`train_temporal.py` accepts explicit model/training JSON and a Phase 08 fold.
`sweep_horizon.py` / `sweep_window.py` accept an explicit cell plan or the labelled
`--synthetic-fixture` mode. Each model/fold cell needs three seeds. Candidate models
are exported, parity checked, timed and replayed through unchanged geometry/commit.
`compare_temporal.py` exercises A/B/C-GBDT comparison on the synthetic fixed-grid
targets. Participant comparison/selection remains blocked by upstream evidence.

`eval_temporal.py` reloads a hashed export for validation-session replay or exact
validation-archive metric reproduction with a recorded tolerance. Test mode is
refused until the actual frozen participant protocol/ledger exists.
`latency_temporal.py`, `recorded_temporal_parity.py` and `failure_cases.py` write
diagnostic artifacts without modifying the models. `verify_phase10.py` runs full
regression, static/contracts/environment checks, frozen-source checks, candidate
artifact hashing and exported metric reproduction. Add `--require-clean` after
the owner commits; pass `--horizon-run`, `--window-run`, `--comparison-run` for the
recorded evidence directories. No script commits, tags, pushes or starts Phase 11.

## Phase 11 multi-task development tools

`train_mt.py` trains/exports one C-MT model from explicit `mt_config`/`training`/`loss` JSON.
`sweep_weighting.py` (Tasks 11.2–11.3) and `ablate_heads.py` (11.6) run labelled
`--synthetic-fixture` grids on `_p11_fixture.py` (scripted strokes, geometry-derived labels);
participant plans are refused until ds-v1.0 exists. Three seeds per cell, `--workers` for
parallel cells (grid timing is then contended). `ablate_heads.py --weighting-from-run` applies
the declared development rule (`experiments/phase-11/weighting-choice-rule.json`) and records
the choice; `compare_tti.py` compares direct/log/bins TTI heads the same way. `eval_mt.py` compares each head with geometry on its own trajectory and Baseline B
(11.4) or reproduces an export's validation metrics; `--partition test` is refused before any
file is read. `eval_consistency.py` sweeps the aux-head gates and scores commit-time intensity
sources (11.5, 11.7). `latency_mt.py` times MT versus single-task in interleaved blocks and
measures working sets in fresh subprocesses (11.8); run it alone. `verify_phase11.py` repeats
the gate checks and hashes/reproduces the recorded runs; add `--require-clean` after the owner
commit. No script commits, tags, pushes, runs a held-out evaluation or starts Phase 12/13.

## Phase 12 extension development tools

`eval_extension.py --extension {ref,e1,e2,e3,e4,e5} --synthetic-fixture` trains the declared
variants of one extension (Tasks 12.2–12.7; `_p12.py` holds the registry and constants of
`docs/experiments/phase-12-prereg.md`) on the SYNTHETIC `_p11_fixture.py` folds, exports and
parity-checks each model, and replays the fold's validation sessions over the declared τ/p grid
through the unchanged harness. Evaluation-only rules reuse trained cells: `e2-mix2-agg` (E2 rule
M2), `e4-ens3` and `e5-smooth` (both need `--reference-run`). E3 trains only with
`--feasibility-run` pointing at a FEASIBLE gate. Participant plans and `--partition test` are
refused before any file is read, and runs refuse to start if the archived pre-declaration changed.
`latency_extension.py --feasibility` is the E3 gate (random-initialised TorchScript models, run
before training); `--runs` times each variant's inference-to-candidate path on candidate windows
and probes working sets. Run both alone. `compare_extensions.py` applies the go/no-go rule
mechanically. On SYNTHETIC runs the output is a development verdict, never adoption.
`explore_posthoc_sigma.py` is an EXPLORATORY diagnostic (not pre-declared): a post-hoc Gaussian
variance head on frozen reference models, replayed like a declared variant but never a go/no-go
input. `verify_phase12.py` repeats the gate checks, audits frozen files, hashes the recorded runs and
reproduces one exported model per variant/family. Add `--require-clean` after the owner commit.
No script commits, tags, pushes, runs a held-out evaluation or starts Phase 13.

## Phase 16 performance tools

Run performance commands serially on HW-01. `profile_pipeline.py` profiles the
production experiment overlay and separates decode/capture wait from processing.
Use `--source replay --sessions <paths> --repeats 3` with
`configs/perf.developer.candidate.yaml`; live checks use
`--config configs/live.arm-C.candidate.yaml --source live --seconds 30 --repeats 1
--audio --dashboard`. `--display` enables windows; display-call time remains outside
the processing interval. Run
`--diagnostics` separately: cProfile/tracemalloc perturb timing. The candidate
soak is `--seconds 300`. Output goes under `--output experiments/phase-16`.

`regression_check.py --config configs/perf.developer.candidate.yaml --plan
configs/perf.regression-plan.json --val-samples <pinned samples.val.npz> --output
experiments/phase-16` freezes a reference; add `--reference <snapshot.json>` to
compare it and `--causal` for future perturbation. Never regenerate the reference
to make a failed candidate pass. `--candidate` selects a reversible half-detection,
IMAGE, perception-thread or shared-memory perception-process experiment; production
does not select these variants. The process worker permits one frame in flight.

`model_cost.py` compares original float, frozen graph and int8 with the same pinned
validation archive. `reconcile_delay.py --before-profile <dir> --after-profile <dir>
--config <config> --output <dir>` reruns same-model synthetic delay sensitivity;
it cannot set a representative live constant. `fps_end_to_end.py` accepts only
live non-perturbed profiles for delivery assessment; `--camera-blocked --target 60
--camera-evidence <profile>` records the conditional camera shortfall.

`verify_phase16.py --reference <frozen snapshot.json>` repeats full tests, static
checks, raw regression/causality/parity, faults and three-repeat final profiling.
Use `--require-clean` after the owner commits. Live soak, camera capability and
model-cost evidence are separate artifacts. Review the pending participant-fold,
shipped-model, live-delay and owner gates in `docs/gates/phase-16-gate.md`.

## Phase 17 (testing, hardening, failure handling)

All Phase 17 scripts record who runs them: pass `--executor-model "<model>" --executor-effort
"<effort>"` (never inferred). Outputs go under `experiments/phase-17/`.

`inject_faults.py --suite synthetic switch model capture-live audio devcapture fasthit guard` (or
`--suite all`, `--quick` for a reduced grid) runs the failure-injection campaign: SYNTHETIC
observation and capture faults placed during the approach / impact / idle, arm switches over the
Phase 18 threshold range, model load and mid-session faults, live-source timestamp faults, audio
device removal, developer-capture image faults through real perception, the SYNTHETIC fast-hit
sweep and the frame-drop guard threshold experiment. `invariant_replay.py` runs the invariants over
the full development replay set and the system-level TEST-CAUSAL-1. `degraded_experiment.py` is the
paired VALID vs VALID+DEGRADED commit experiment and `reacquisition_experiment.py [--workers N]` the
`g_max_frames` × `age_max_s` sweep (decision rules in their docstrings; the sweep also reports a
separately labelled post-hoc fake-out sensitivity). `soak_test.py --minutes 60` is the live soak
with SYNTHETIC scripted strokes (`--gain-scale` attenuates only played samples; writes
`soak-report.json`, `soak-samples.json`, `app-summary.json`). Never run the soak together with
another campaign.
`build_test_matrix.py [--check]` regenerates / checks `docs/testing/test-matrix.md`.
`verify_phase17.py [--require-clean]` repeats the executable gate checks (13 commands; the
live-mode assertion set, the soak and every person-dependent check are separate).
