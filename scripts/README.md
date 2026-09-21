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

`tools/annotate_tip.py` (Task 03.10) is the manual tip-annotation tool (person-dependent; `--synthetic` writes a labelled SYNTHETIC self-test file the benchmark refuses by default). Every measurement script has a `--synthetic` self-test mode used by `tests/scripts/`; real runs write `experiments/<YYYYMMDD>-<HHMM>-<slug>/` (git-ignored) and their numbers are quoted with the run id in the camera profile.
