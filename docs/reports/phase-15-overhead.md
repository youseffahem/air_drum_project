# Phase 15 overlay and dashboard overhead

## Result

The final run on 2026-09-26 used the repository's developer replay
`dev-p05-swing-L2-exp-5` (producer `REPLAY`, from a Phase 05 development capture). Each mode
rendered the same 171 frames five times (855 frame
renders per mode) after a cache warm-up. Values are **MEASURED development replay wall time**
on the local Windows workstation (the replay records carry `hardware_id=HW-01`); they are not
camera, physical, audio-output, or acoustic latency.

| Mode | p50 total ms | p95 total ms | p95 incremental vs off ms | Recorded capture drops |
|---|---:|---:|---:|---:|
| off | 8.618 | 10.707 | 0.000 | 1 |
| experiment | 10.858 | 13.488 | **2.782** | 1 |
| full | 11.330 | 13.296 | 2.589 | 1 |

The experimentally defined experiment-mode bound is incremental p95 <= **5.0 ms** versus
off, corresponding to 15% of a 30 fps frame period rounded. The final observed 2.782 ms
passes. Three earlier runs after removing redundant overlay image copies measured 2.476,
2.901 and 2.246 ms. Before that change, one run measured 6.277 ms (failed) and a repeat 4.453 ms
(passed); the failed run remains preserved in the evidence directory. This variation is a
reason to re-measure on the eventual live protocol, not a claim of a hard real-time guarantee.
The capture-drop column is the replay's recorded input and is intentionally identical across
modes; UI drops are a different counter.
The final full-mode p95 happened to be slightly below experiment-mode p95 despite rendering
more elements; these are independently sampled wall-time distributions, not a per-frame
monotonic cost claim.

## Framework comparison

The producer published 5,000 records as fast as possible to stress both minimal prototypes.
The test measures producer-side calls only, which is the loop-impact quantity. Rendering runs
outside that path.

| Candidate | producer p50 ms | producer p95 ms | max ms | overload behavior |
|---|---:|---:|---:|---|
| bounded queue + OpenCV worker | 0.0017 | **0.0017** | 0.0340 | 4,998 UI records dropped; producer did not block |
| local JSON stream socket for browser panel | 0.0093 | 0.0277 | 0.2852 | 0 transport drops in this run; browser rendering excluded |

The bounded OpenCV worker is selected in ADR-0038 because it is already sufficient for the
fixed scientific UI, has lower measured producer impact, adds no browser runtime/socket
lifecycle, and directly reuses the project's OpenCV rendering. Saturation deliberately caused
UI drops and did not produce pipeline/capture drops.

## Evidence

- Machine-readable results: `experiments/phase-15/20260926-phase15-overhead/final/overhead.json`
- Flat table: `experiments/phase-15/20260926-phase15-overhead/final/overhead.csv`
- Dashboard screenshot: `experiments/phase-15/20260926-phase15-overhead/final/dashboard.png`
- Annotated frame and PNG/SVG/CSV/JSON exports:
  `experiments/phase-15/20260926-phase15-overhead/final/exports/`
- Earlier and optimization-confirmation runs: root `overhead.json`, `repeat/`, `optimized/`,
  and `optimized-repeat/` under the same evidence directory.
- Reproduction command: `scripts/measure_phase15.py` (also documented in the user guide)

## Limitations

The replay is development evidence, not a participant or live-camera trial. Windows
scheduling, display drivers, resolution and concurrent load can change UI cost. The browser
candidate covers transport only, not DOM plotting. The 5 ms target is a Phase 15 experiment
budget, not evidence that end-to-end or effective latency was reduced. Phase 18 must re-measure
the selected experiment mode in live protocols.
