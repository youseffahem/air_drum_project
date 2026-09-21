# spacedrums.timing

**Status:** clock IMPLEMENTED (Phase 02; tests in `tests/timing/`). `TimingRecord` collector: Phase 05. Layer L0: imports only `contracts`.

`now()` is the single `t_mono` accessor (ADR-0004); `CLOCK_ID = "perf_counter"` — confirmed on HW-01 as `QueryPerformanceCounter()` (resolution 1e-7 s, monotonic, not adjustable; ADR-0013). `thread_cpu_seconds()`, `process_cpu_seconds()`, `sleep_s()` and the wall-clock helpers for provenance fields live here so that `time`/`datetime` are imported in exactly one module; `tests/timing/test_clock.py` fails if any other module calls them.
