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

Every measurement script has a `--synthetic` self-test mode used by `tests/scripts/`; real runs write `experiments/<YYYYMMDD>-<HHMM>-<slug>/` (git-ignored) and their numbers are quoted with the run id in the camera profile.
