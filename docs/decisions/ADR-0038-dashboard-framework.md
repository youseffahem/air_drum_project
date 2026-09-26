# ADR-0038: Bounded OpenCV dashboard worker

- **Status:** Accepted for Phase 15 development implementation; owner review pending
- **Date:** 2026-09-26
- **Decision owners:** Phase 15 submitter; project-owner gate review pending

## Context

The dashboard must consume all diagnostic records without blocking capture/decisions. The phase
asked for a measured choice between a lightweight native window and a browser panel fed over a
local socket. The scientific element set is fixed; realistic kit visuals remain out of scope.

## Prototypes and measured result

`scripts/measure_phase15.py` stressed 5,000 producer publishes on the local Windows workstation.
The bounded Python queue feeding an OpenCV worker measured **0.0017 ms p95** producer cost.
The local JSON stream-socket transport prototype measured **0.0277 ms p95**, excluding browser
DOM/plot rendering. Under deliberate queue saturation, the OpenCV candidate dropped 4,998 UI
records while the publisher continued; these are UI drops, not capture drops. Full method and
limits are in `docs/reports/phase-15-overhead.md`.

## Decision

Use an in-process dashboard consumer thread with one bounded queue per subscriber and
drop-if-full semantics. Render the secondary panel with OpenCV. Keep plotting/export offline
with Matplotlib's headless backend. The producer API is a frozen `DashboardRecord` envelope plus
`RecordBus.publish()`; consumers may drain to the newest record.

The queue capacity defaults to two. No UI consumer may call a blocking producer operation.
Drop counts are mandatory dashboard/session diagnostics.

Experiment mode does not show Baseline B's shadow trajectory by default; full mode shows all
available B/C trajectories together. This keeps timed protocols on the measured minimal renderer
while retaining the comparison for analysis and demonstrations.

## Consequences

- The production loop gains only bounded, non-blocking fan-out; a slow UI cannot create
  decision back-pressure.
- The selected renderer reuses existing dependencies and works for screenshot evidence.
- OpenCV GUI display still requires a desktop session. Headless runs retain export and tests.
- A future browser panel may subscribe to the same record abstraction, but adopting it requires
  a fresh measurement including browser rendering and lifecycle complexity.

## Alternatives rejected

- **Browser/local socket now:** higher measured transport cost, additional process/socket and
  browser-rendering failure modes, with no requirement benefit for the fixed Phase 15 element set.
- **Synchronous side panel in the processing loop:** violates the non-blocking requirement.
