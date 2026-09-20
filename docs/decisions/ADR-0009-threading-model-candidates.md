# ADR-0009 — Threading / process model: baseline T1 adopted, T2/T3 as benchmarked escape hatches

| Field | Value |
|---|---|
| Status | **Accepted for T1 as the baseline; T2/T3 are `Pending Architecture Decision` (Phase 16)** (Phase 01, Task 01.10) |
| Date | 2026-09-20 |
| Deciders | Project owner, recorded by Phase 01 |
| Related | `docs/architecture/architecture.md` §7; `docs/decisions/ADR-0001-python-first-stack.md` (GIL risk); `configs/schema/config.schema.json` (`camera_profile.queue`); REQ-304, REQ-023, REQ-060b |

## Context

Python-first (ADR-0001) means the GIL bounds parallelism across pure-Python stages, while the heavy stages (landmark inference, classical CV, model inference, audio callback) run in native code that releases the GIL to varying degrees. No measurement exists yet (Phase 02/03/16). The contracts must not depend on the eventual choice, and causality must survive concurrency: a worker that could see a frame before the main loop has processed the previous one is a future-frame leak.

## Decision

1. **T1 baseline (adopted now, used from Phase 02/05):** a *capture thread* stamps `t_capture`/`t_frame_available` and pushes into a **bounded queue with drop-oldest** (size `camera_profile.queue.max_frames`, tunable; drops counted in `FrameSample.dropped_since_last`); a single *processing loop* runs hands → stick → tracking → features → prediction → geometry → commit for both hands per frame in `frame_id` order; the *audio callback thread* (owned by the audio library) consumes a lock-free queue of `AudioEvent`s.
2. **T2 (inference worker) and T3 (perception process)** are permitted only on measured need (Phase 13/16), with these invariants: timestamps for frames are created only in the capture thread/process (ADR-0004); a worker sees only frames already delivered to the loop; results are tagged with the `frame_id` they saw and discarded (logged as late) if stale; `TEST-CAUSAL-1` is re-run in live mode after any threading change.
3. **Drop, never buffer:** the queue policy is fixed to `DROP_OLDEST` by schema so latency cannot accumulate; the effect of drops on effective frame rate is a Pending Benchmark (Phase 02/16) and is always reported with FPS figures (integrity I-5).
4. All records are serialisable (no object references), so T3 can move them across a process boundary without contract change.

## Alternatives considered

| Alternative | Why not (now) |
|---|---|
| Fully asynchronous pipeline (each stage its own thread with queues) | Maximum overlap but each queue adds latency and ordering hazards; without measurements it is premature (Phase 16 decides). |
| Multiprocessing from the start | Extra complexity and IPC cost; clock consistency across processes not yet verified. |
| Native (C++) hot path | ADR-0001 escape hatch; needs profiling evidence first. |
| Blocking queue (back-pressure) | Would let latency grow unboundedly when processing is slower than capture; contradicts real-time behaviour (REQ-304). |

## Consequences

- Phase 02 implements the capture thread + queue and measures drop/stall rates; Phase 03/16 profile per-stage costs into the named latency slots.
- Any adoption of T2/T3 is a new ADR that supersedes the *Pending* part of this one and cites the benchmark run ids.
- Per-frame latency figures must state the threading candidate and thread counts.
