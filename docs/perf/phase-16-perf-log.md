# Phase 16 optimization log

Status: **PENDING** reviewer and clean reproduction. All new values below are
development measurements on dirty source, 2026-09-26, HW-01 i7-7820HQ, CPU only.
They are not MEASURED gate/thesis evidence under the reproducibility policy.
Run paths below are relative to `experiments/phase-16/`. No model was retrained.

## Retention decisions

| Change (isolated screen) | Before → after loop p95 ms | After CPU % of one core | Regression | Decision |
|---|---:|---:|---|---|
| Half-resolution hand detection, full-resolution stick | 58.429 → 62.061 | 51.21 | FAIL; first capture commits 11 → 4 | Reject |
| Synchronous perception thread | 58.429 → 58.693 | 46.37 | PASS; subsequent future-perturbation check recorded in regression report | Reject; no tail gain |
| IMAGE instead of VIDEO landmark mode | 58.429 → 59.865 | 55.78 | FAIL | Retain VIDEO |
| OpenCV 8 → 1 threads | 58.429 → 57.731 | 50.39 | PASS | Retain explicit default 1; `--opencv-threads 8` restores historical setting |
| Shared-memory perception process (OpenCV parent 8, child library default) | 58.429 → 52.184 | 44.60 aggregate | PASS and causal | Keep only as optional experiment; no production worker |
| Component bounding-box scans and lazy empty mask, after OpenCV 1 | 57.731 → 63.358 | 50.42 | PASS | Retain allocation reduction; whole-loop speedup not established by this pair |
| Bounded arc-coordinate cache, after preceding retained changes | 63.358 → 49.834 | 53.14 | PASS and causal | Retain; pixel-identical paired microbenchmark supports local gain |
| Initialize perception before camera | Idle 35.510 after vs 34.247 baseline | 35.06 | Initialization order/failure cleanup test and final raw regression | Retain; startup drops 23 → 0 in these sessions |

Baseline CPU was 53.60% of one core. CPU includes startup, replay decode and cleanup;
wall-time p95 covers perception through experiment overlay. These different scopes
must not be divided to infer CPU efficiency. Independent serial runs can vary with
thermal state and OS scheduling. Final reproduction and per-run ranges are in the
[profiling report](phase-16-profiling.md); intermediate gains are not additive.

The independent final retained-source run
`20260926-1345-gate-verification/profile/20260926-1356-profile` has p50/p95
37.073/56.302 ms, compared with baseline 39.636/58.429 ms. Final CPU is 51.46%
of one core and sampled peak working set is 396.46 MiB. This smaller 3.64% p95
improvement supersedes any suggestion that the intermediate 49.834 ms result is
a reliably achieved bound. The 33.333 ms frame period is still missed in 967 of
1,542 replay frames. All final frozen records and harness metrics pass.

Baseline and retained screens use three repeats of each of three developer captures
(1,542 frames). Half/thread/IMAGE/process screens use two (1,028 frames). Replay drop
counts are historical input metadata: six for three repeats, four for two. They do
not measure new queue drops or demonstrate that a replay sustains camera delivery.
Live idle baseline/current drops were 24/2 over separate 30-second sessions.

## Evidence map

| Candidate | Timing run | Reference comparison |
|---|---|---|
| Baseline | `20260926-1255-baseline` | `20260926-1301-reference-fixed` |
| Half resolution | `20260926-1302-half-screen` | `20260926-1303-half-regression` |
| Thread | `20260926-1303-worker-screen` | `20260926-1304-worker-regression` |
| IMAGE | `20260926-1305-image-screen` | `20260926-1306-image-regression` |
| OpenCV 1 | `20260926-1307-cv1-screen` | `20260926-1308-cv1-regression` |
| Process | `20260926-1311-process-screen` | `20260926-1313-process-regression` |
| Component bounds | `20260926-1316-segment-bounds` | `20260926-1318-segment-regression` |
| Arc cache | `20260926-1320-cached-zones` | `20260926-1322-zones-regression` |
| Live initialization | `20260926-1257-baseline-live`, `20260926-1324-optimized-live` | Final verifier plus startup cleanup test |

`screen-commands.json` and `remaining-screens.json` retain commands and exit codes.
The initial `20260926-1300-reference` failed because the script omitted the model
clock argument; its failed log is preserved. Optimization started after the fixed
reference and the tolerance protocol were recorded.

## Allocation and copy changes

`segment-microbench.json` compares the old function loaded from starting Git HEAD
against the changed function on four real-frame search regions. Candidate pixels,
masks, edge counts and component records are exact. Three paired batches of 300
calls gave old p50 0.513/0.442/0.442 ms versus new 0.443/0.419/0.417 ms. Separate
tracemalloc runs show about 246.9 kB less peak Python allocation per selected region
(old 534,019–572,171 bytes; new 287,130–325,282 bytes). This is a local allocation
result; the full-loop component-only run was slower and is retained above.

`zones-microbench.json` compares exact rendered pixels at three image dimensions
and randomized backgrounds, three paired 300-call batches. Old p50 was
1.883/1.852/1.872 ms; cached p50 1.410/1.622/1.448 ms. The cache holds at most 128
immutable geometry/dimension keys, and read-only coordinate arrays. Changing
calibration or dimensions selects a new key. Existing image copies needed to
preserve source ownership remain in place.

## Concurrency and estimator scope

Capture already has a bounded drop-oldest queue. The experimental perception
process shares one full BGR frame and waits for that frame's result before reuse;
it validates the returned frame id. There is no prefetch or future-frame access.
Its modest tail improvement still misses the 33.333 ms target and adds a second
process, memory and startup cost. Production keeps inline perception/inference.
Its parent peak working set was 300.36 MiB, with worker final working sets of
357.72–369.07 MiB; those snapshots are not a simultaneous aggregate peak.
The thread experiment similarly waits synchronously; it does not claim overlap.
Inference cost is small compared with landmark detection, so no additional
production inference worker was adopted.

The installed MediaPipe task CPU API does not expose the legacy `model_complexity`
or a supported thread-count control through BaseOptions. VIDEO/IMAGE, input scale
and OpenCV's available thread control were screened. No alternative hand model
was silently substituted. Developer data lacks reviewed tip ground truth; changed
presence/track/commit records reject lossy variants without invented tip errors.

## Model, audio and delay decisions

See [model cost](phase-16-model-cost.md), [soak/audio](phase-16-soak.md) and
[delay reconciliation](phase-16-delay.md). Dynamic int8 is rejected. Model graph
freezing remains experimental. The original float package remains pinned; there
is still no owner-selected shipped model. The 128-sample audio buffer remains the
candidate default because unattended callback checks do not establish post-DAC
latency or loaded polyphony stability. No audio-latency constant is invented.

No causal record contract changed. Fixed-delay regression remains independent of
measured wall-clock speed. Performance budgets and regression tolerances were not
relaxed to conceal overload or behavioral changes.
