# scripts/

One-off tools. Run from the repository root with the development venv (`.venv\Scripts\python.exe`).

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
