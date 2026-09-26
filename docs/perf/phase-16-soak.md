# Phase 16 unattended soak and audio check

Status: **PENDING** clean reproduction and representative stroke/polyphony load.
The predeclared 300-second unattended camera soak completed on 2026-09-26
(+03:00), HW-01. These are dirty-tree development measurements.

Run: `experiments/phase-16/20260926-1337-soak/`. Settings:
`configs/live.arm-C.candidate.yaml`, native camera request 30 FPS, DSHOW 640×480
YUY2, manual exposure -6, OpenCV 1, Torch 1, MediaPipe CPU defaults, experiment
overlay, dashboard worker, real audio callback at 48 kHz / 128 samples. The
display/window driver is excluded; the actual overlay/dashboard render work runs.
No person was present and no sticks were played.

| Quantity | Development result |
|---|---:|
| Processed unique frames / capture span | 9,043 / 299.917 s |
| Delivered processing rate from capture timestamps | 30.148 frames/s |
| Capture diagnostic delivery rate | 30.176 frames/s |
| Capture queue drops / first-frame drops | 9 / 0 |
| Duplicate / clamped timestamps | 0 / 0 |
| Capture stall counter | 2 |
| Processing p50 / p95 / maximum | 24.327 / 36.861 / 84.631 ms |
| Frames exceeding 33.333 ms processing | 730 |
| Process CPU, one-core basis | 42.82% |
| Peak working set | 425.57 MiB |
| Median working set at 60–120 s / final 60 s | 414.04 / 423.26 MiB |
| Dashboard records / queue drops | 9,043 / 0 |
| Audio underruns / late events / clipped samples | 0 / 0 / 0 |
| Model prediction frames / scheduled audio strikes | 0 / 0 |
| Model fallbacks | 1: processing p95 exceeded existing budget; C → B |

The app exits normally and releases camera/audio resources. Resource sampling spans
306.108 seconds including startup and cleanup, with 282 observations. Windows
scheduling makes the nominal one-second sampling interval approximate. Working set
falls to 359.28 MiB after cleanup. The late-window median rises by 9.22 MiB; this
includes growing profiler frame dictionaries and application timing history. This
does not establish bounded steady-state heap behavior or diagnose a leak. A future
loaded soak should use a streaming/bounded profiler and compare retained heap.

The camera delivery figure is an idle/fallback result. It cannot demonstrate
sustained temporal-model prediction, polyphony, physical onset latency or lead
time. Full workload soak remains PENDING for Phase 17 and the owner/reviewer.

## Audio buffer screen

The 128-sample current idle check is
`experiments/phase-16/20260926-1324-optimized-live/`. The two 64-sample checks are
`experiments/phase-16/20260926-1332-audio64/`, using a copy of the same live config
with only `audio.buffer_frames` changed. Each run lasts 30 seconds.

| Buffer / run | Processing p95 ms | Delivered frames/s | Queue drops | CPU, one core | Audio underruns |
|---|---:|---:|---:|---:|---:|
| 128, current | 35.510 | 30.117 | 2 | 35.06% | 0 |
| 64, repeat 1 | 33.915 | 30.147 | 1 | 35.61% | 0 |
| 64, repeat 2 | 35.637 | 30.014 | 4 | 35.84% | 0 |

All three runs fall back to B and produce zero audio events. Peak working sets
for the 64-sample repeats are 404.34 and 415.64 MiB. The separate raw/harness
audio-config regression `20260926-1344-audio64-regression` passes; its command is
recorded in `final-command-ledger.json` beside the run.
**Keep 128 samples**: the smaller buffer has no demonstrated output-latency benefit
under loaded use. `buffer_frames / sample_rate` is only a nominal callback period;
it is not post-DAC latency. The Phase 04 Stereo Mix consistency/tap-point limitations
remain in force, and the accepted audio-output latency remains unset.

Audio uses the config's default output device on the HW-01 Realtek setup. The shared
run writer's hardware snapshot still labels audio as `n/a (Phase 04)` and does not
pin the resolved OS endpoint for these runs. Config/sample rate/buffer/device-enabled
counters are recorded; endpoint-specific latency/stability claims require fresh,
explicit endpoint provenance. No existing immutable run is rewritten to hide this.
