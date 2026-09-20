# ADR-0004 — Single monotonic clock `t_mono` for every timestamp

| Field | Value |
|---|---|
| Status | **Accepted** (Phase 01, Task 01.3 / 01.10) |
| Date | 2026-09-20 |
| Deciders | Project owner (via roadmap README §5.1), recorded by Phase 01 |
| Related | `phases/README.md` §5; `docs/architecture/architecture.md` §5; `schemas/timing-record.schema.json`, `record-stream-header.schema.json`; REQ-005, REQ-045, REQ-060b |

## Context

The research quantities (`L_pred`, `L_sys`, `TE_pred`, `TE_audio`) are differences of timestamps produced by different subsystems: the camera driver, the application, the audio device, and (in Phase 18) external instruments. Frame periods are ~33 ms; a clock mismatch of a few milliseconds is the same order as the effect under study. Three clocks are involved by nature (camera, CPU, audio DAC) and Windows exposes several CPU clocks with different resolution and monotonicity guarantees.

## Decision

1. Every timestamp in every record is expressed in **seconds on one process-wide monotonic clock `t_mono`**, accessed only through `spacedrums.timing.now()`. The concrete function (candidate `time.perf_counter()`) is identified by `clock_id` in every `TimingRecord`, stream header, camera profile and audio profile.
2. Foreign clocks are **mapped onto `t_mono`, never the reverse**: camera driver timestamps by the capture module (Phase 02, linear map or grab-return minus measured bias; `FrameSample.timestamp_source` says which), audio device stream time by the audio engine (Phase 04, linear regression with drift). Each mapping's residual is a MEASURED quantity in the respective profile.
3. Wall-clock time is recorded once per session (`SessionMetadata.started_at` + `t_mono_at_start`) for alignment with external recordings; never used inside records.
4. Milliseconds never appear in variables, fields or config keys (`*_s` suffix convention; tested).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Use the camera driver's timestamps as the reference clock | Driver timestamps may be unavailable, non-monotone, or backend-dependent (`environment.md` OpenCV note); the audio side could not be mapped to them. |
| Wall clock (`time.time()`) | Not monotonic (NTP steps); resolution on Windows historically coarse. |
| Separate per-subsystem clocks with offsets stored per record | Every consumer would have to re-derive alignment; offline/online parity (`TEST-PARITY-1`) would become ambiguous. |
| Milliseconds as the unit | Readable but invites integer truncation and unit mix-ups; seconds as float64 keep sub-ms precision over sessions of hours. |

## Consequences

- One accessor to instrument; a grep for `time.` outside `spacedrums.timing` is a review check.
- Cross-process use (threading candidate T3) requires a benchmark that the chosen clock is consistent across processes (Phase 16) before adoption.
- Every latency figure carries `clock_id`, the mapping method and its residual, so numbers can be compared across sessions and hardware ids.
- If `perf_counter` proves unsuitable (Phase 02 measurement), a different function is chosen by amending this ADR; records remain valid because `clock_id` identifies the source.
