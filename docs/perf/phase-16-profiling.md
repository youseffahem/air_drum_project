# Phase 16 profiling

Status: **PENDING** clean reproduction and representative live-stroke evidence.
All Phase 16 timing values here are development measurements on dirty source,
2026-09-26 (+03:00), HW-01 i7-7820HQ CPU. They cannot be cited as MEASURED in a
gate or thesis until clean reproduction. The dependency checks are separately
identified in the gate record.

## Method and scope

`profile_pipeline.py` instruments the actual `app.run` path with the experiment
overlay. Each frame records disjoint stage wall times, full processing time,
capture timestamp/id, original drops, active arm, fallback, predictions and commits.
Replay PNG decoding and live capture wait are outside the processing interval.
The actual overlay is rendered; window/display calls are suppressed unless
`--display` is specified. The JSON flag `display_included` records whether windows
were enabled; display-call time stays outside the processing interval even then,
as specified by `processing_scope`. Audio device and dashboard are enabled only in live
checks. Audio scheduling remains exercised for replay commits.

The fixed roster comprises 514 developer frames, replayed three times for the
baseline and retained configuration. Timing distributions include the first
processed frame and model warm-up; initialization before that frame is excluded
from frame timings but included in resource sampling. The baseline uses OpenCV 8
threads, retained settings 1; Torch uses 1 and MediaPipe task CPU defaults throughout.
Fallback is disabled explicitly in the replay comparison and remains enabled live.
Per-frame stage samples include zeros when a stage has no work; model-only costs
are separately measured on nonempty windows in the model-cost report.

All runs execute serially, without a concurrent training/test benchmark. The
reference and later profiles hash raw images and frame streams. The initial
baseline profiler predates per-image hash output; it names the same unchanged
developer roster but lacks its own image-hash artifact. That provenance limitation
must be resolved in the clean reproduction. Config CLI overrides and thread counts
are recorded separately from the immutable base configuration snapshot.

## CPU, memory, allocation and contention method

Native Windows thread user+kernel CPU and process working sets are sampled every
second; process CPU uses `process_time`. Percentages are normalized to one logical
core, so 100% means one fully occupied core. Resource intervals include application
startup, decoding and teardown. Short-lived threads may escape sampling; thread
ids include creation time to distinguish reuse. Working-set values are resident
process memory, not retained heap or a leak diagnosis. The profiler itself stores
per-frame dictionaries, which makes its long-run memory grow with frame count.

Allocation/cProfile run `experiments/phase-16/20260926-1258-allocation-baseline`
contains 60 developer frames. Its Python peak/retained allocation is
38,947,675/34,632,576 bytes; much of the retained allocation comes from imports.
Native allocations are excluded. Its timing is deliberately perturbed and is
excluded from the before/after timing comparison. `profile.pstats` and
`hotspots.txt` show repeated overlay arc construction and synchronous MediaPipe
dispatch waits. About 2.27 seconds in lock acquisition is a wait observation,
not proof of GIL contention. MediaPipe releases work to native threads, and
wall time includes scheduling waits. Thread CPU and the paired worker experiments
do not directly measure GIL hold/wait time.

For example, baseline sample 1's busiest sampled thread used 27.52% of one core;
the next sampled threads were about 1.84–2.37% each. Full per-thread counters are
in every `sample-*.json`, with explicit sampling coverage limitations. Paired local
allocation/pixel benchmarks are documented in the optimization log.

## Interpretation

Landmark detection dominates the replay frame budget. Smaller inputs and IMAGE
mode change behavior, so their timings do not justify adoption. A shared-memory
process remains experimental. Local allocation and draw-cache improvements can
be retained with exact output checks, but do not establish native camera capacity
or effective acoustic latency. The budget table's targets remain unmet where
measured stage p95 exceeds the declared target.

The final measurements below include an independent replay reproduction after
all retained source changes. Intermediate per-run variance is retained in the
JSON evidence and the optimization log; no confidence interval or significance
claim is inferred from three repeats.

## Final retained configuration vs baseline

Final run: `experiments/phase-16/20260926-1345-gate-verification/profile/20260926-1356-profile`. Baseline: `experiments/phase-16/20260926-1255-baseline`.

| Stage | Baseline p50 / p95 ms | Final p50 / p95 ms |
|---|---:|---:|
| Hands | 29.987 / 48.152 | 29.295 / 49.024 |
| Stick | 1.282 / 7.149 | 0.749 / 5.333 |
| Tracking | 0.089 / 0.371 | 0.079 / 0.298 |
| Features and window | 0.175 / 1.898 | 0.169 / 1.789 |
| Model inference | 0.061 / 3.210 | 0.057 / 2.844 |
| Rule prediction | 0.017 / 0.093 | 0.017 / 0.090 |
| Geometry | 0.030 / 0.188 | 0.029 / 0.177 |
| Commit | 0.027 / 0.102 | 0.027 / 0.093 |
| Audio scheduling | 0.000 / 0.000 | 0.000 / 0.000 |
| Experiment overlay | 2.692 / 5.274 | 1.813 / 3.052 |
| Other loop work | 0.245 / 0.406 | 0.231 / 0.391 |
| Full processing interval | 39.636 / 58.429 | 37.073 / 56.302 |

The final observed p95 differs by -3.64% from baseline. This is a
development wall-time comparison; it does not establish causal attribution to one change,
native sustained Arm C delivery, statistical significance or effective acoustic latency.

| Quantity | Baseline | Final |
|---|---:|---:|
| Frames / session runs | 1542 / 9 | 1542 / 9 |
| Mean processing ms | 39.299 | 37.093 |
| Replay compute capacity, frames/s (not camera FPS) | 25.446 | 26.959 |
| Frames over 30 FPS target period | 1095 | 967 |
| Historical input drops, summed over repeats | 6 | 6 |
| Process CPU, % of one core | 53.60 | 51.46 |
| Peak sampled working set, MiB | 403.15 | 396.46 |

Per-run p95 ms in repeat/session order (5, 6, 7):

- Baseline: 64.244, 57.308, 54.078, 61.259, 64.717, 41.584, 52.885, 54.219, 56.129.
- Final: 55.630, 59.371, 52.617, 59.483, 52.630, 44.896, 55.631, 61.711, 41.750.

Each sample retains per-thread CPU, raw per-frame timings, decode distributions and
predictions/commits/fallback counts. Stage percentiles must not be summed as loop percentiles.
