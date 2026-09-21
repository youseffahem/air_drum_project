# spacedrums.timing

**Status:** clock IMPLEMENTED (Phase 02; tests in `tests/timing/`); `TimingRecord` collector, JSONL record streams and the README §5.3 decomposition IMPLEMENTED (Phase 05, Task 05.4). Layer L0: imports only `contracts`.

`now()` is the single `t_mono` accessor (ADR-0004); `CLOCK_ID = "perf_counter"` — confirmed on HW-01 as `QueryPerformanceCounter()` (resolution 1e-7 s, monotonic, not adjustable; ADR-0013). `thread_cpu_seconds()`, `process_cpu_seconds()`, `sleep_s()` and the wall-clock helpers for provenance fields live here so that `time`/`datetime` are imported in exactly one module; `tests/timing/test_clock.py` fails if any other module calls them.

Phase 05 modules: `records.TimingCollector` (FRAME / STRIKE records; `t_audio_out_est` copied only when the audio profile's output latency is MEASURED — contracts.md §3.10), `logger.RecordStreamWriter` / `read_record_stream` (header-first JSONL streams, `RecordStreamHeader`), `decomposition` (README §5.3 terms, `L_sys_est` with its term list, replay-aware N/A handling). Tests: `tests/timing/test_timing_records.py`.
