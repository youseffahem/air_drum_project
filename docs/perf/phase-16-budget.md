# Phase 16 latency budget

Targets declared 2026-09-26 (+03:00) after baseline profiling and before optimization.
Hardware: HW-01 i7-7820HQ, CPU only. Baseline OpenCV 8 threads, Torch 1 thread,
MediaPipe task defaults. Three repeats of 514 developer frames, startup included.
Run: `experiments/phase-16/20260926-1255-baseline/`.

| Stage | Baseline p95 ms (development measurement) | Target 30 FPS ms | Target 60 FPS ms | Achieved p95 ms (development measurement) |
|---|---:|---:|---:|---:|
| Hands | 48.152 | 20.000 | 10.000 | 49.024 |
| Stick | 7.149 | 2.000 | 1.000 | 5.333 |
| Tracking | 0.371 | 0.300 | 0.150 | 0.298 |
| Features and window | 1.898 | 1.000 | 0.500 | 1.789 |
| Model inference | 3.210 | 2.000 | 1.000 | 2.844 |
| Rule prediction | 0.093 | 0.150 | 0.075 | 0.090 |
| Geometry | 0.188 | 0.250 | 0.125 | 0.177 |
| Commit | 0.102 | 0.150 | 0.075 | 0.093 |
| Audio scheduling | 0.000 | 0.100 | 0.050 | 0.000 |
| Experiment overlay | 5.274 | 2.000 | 1.000 | 3.052 |
| Other loop work | 0.406 | 0.750 | 0.375 | 0.391 |
| Target sum | — | 28.800 | 14.400 | — |
| Frame period | — | 33.333 | 16.667 | — |
| Target headroom | — | 4.533 | 2.267 | — |

The measured full-loop p50/p95 is 39.636/58.429 ms. Per-stage p95 values must not
be added and called the measured loop p95: percentiles do not add. Targets are
planning allocations, not evidence of feasibility. The 60 FPS column is contingent
on a camera that delivers native 60 FPS and an eligible model input cadence.

Audio scheduling p95 is zero because few frames commit; this is not evidence of
zero audio device latency. Capture wait, replay PNG decode, display driver costs
and acoustic output are outside this processing budget and are reported separately.
The unattended live baseline is workload-limited and does not replace the stroke
replays when assessing computational capacity.

## Achieved interpretation

Final development run: `experiments/phase-16/20260926-1345-gate-verification/profile/20260926-1356-profile`. Achieved values use
OpenCV 1, Torch 1, the original float package and retained allocation/cache changes.
Full-loop p50/p95 is 37.073/56.302 ms. These exceed the 30 FPS
frame period at p95; no sustained model-processing target is declared achieved.
The predeclared targets and headroom have not been relaxed.
