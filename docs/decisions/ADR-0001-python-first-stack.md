# ADR-0001 — Python-first technology stack

| Field | Value |
|---|---|
| Status | **Accepted** (owner decision recorded during roadmap definition; formalised in Phase 00, Task 00.9) |
| Date | 2026-09-20 (recorded) |
| Deciders | Project owner |
| Related | `phases/README.md` §11; `docs/environment.md`; REQ-044 (select on CPU inference cost), REQ-052/209 (fully local), REQ-304 (real-time) |

## Context

Space Drums combines webcam capture, hand-landmark inference, classical CV for the stick, a causal temporal model, GBDT baselines, deterministic geometry, an audio engine, and an offline evaluation harness. The project is a single-developer graduation project with a research-first goal (README §1) and a hard real-time component (REQ-304) on a CPU-only laptop (`hardware-inventory.md` HW-01). The candidate libraries for every stage (OpenCV, MediaPipe, PyTorch, ONNX Runtime, LightGBM, PortAudio) all expose mature Python bindings with Windows CPU wheels.

## Decision

The project is implemented **Python-first**: all pipeline stages, tooling, evaluation, and the live application are written in Python (CPython 3.11.x, `environment.md`), using the candidate libraries in README §11. Performance-critical work is delegated to those libraries' native cores rather than to project-written native code.

## Alternatives considered

| Alternative | Why not (now) |
|---|---|
| C++ end-to-end (OpenCV/MediaPipe C++ APIs, libtorch, PortAudio) | Lowest latency ceiling, but development speed for a research project with many experiments would be far lower; build complexity on Windows; the research question is answered offline first (Phase 09–12), where Python is standard. |
| Rust / Go application with Python for research only | Two code bases → offline/online parity (Phase 13 `TEST-PARITY-1`) becomes much harder to guarantee. |
| Python for research, C++ "hot path" from the start | Premature: no measurement yet shows Python is the bottleneck. Kept as the **escape hatch**: Phase 16 profiling may motivate a native module for one stage, recorded by a new ADR. |
| Unity/C# or a game engine for the front end | Attractive visuals, but visual polish is explicitly subordinate to measurable behaviour (REQ-310); would split the pipeline. |

## Consequences

- **Positive:** fast iteration; one code path for offline harness and live inference (parity); the whole community tooling for the ML side; easy reproducibility via `requirements.lock`.
- **Negative / risks:** GIL and interpreter overhead in the live loop; per-frame latency depends on library internals and threading (Phase 16 must measure; latency budgets are `Pending Benchmark`). Windows wheel availability constrains the Python minor version (3.11 chosen; `environment.md` OQ-ENV-1).
- **Obligations:** thread counts and hardware ids recorded with every latency figure; any native-code addition needs an ADR and must pass the parity test.
