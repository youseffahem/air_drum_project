# Soak test (Phase 17, Task 17.8)

Status: **development evidence**, unattended. The person-played soak is PENDING.

Run context:
- **Machine:** HW-01 (i7-7820HQ, Windows 10.0.22621, AC power / Balanced plan).
- **Camera:** integrated webcam (DSHOW 640×480 YUY2, requested 30 FPS).
- **Audio:** Realtek default output.
- **Code state:** dirty tree on HEAD `8ad5393`, the same source as the final gate verification
  (`experiments/phase-17/20260927-0053-p17-gate-verification/`). The run's source audit confirmed the
  source was unchanged during the hour.
- **Executor:** Claude Opus 5.5 via Claude Code.
- **Run:** `experiments/phase-17/20260927-0150-soak-60min/`, 2026-09-27 01:50:20 → 02:50:20
  (+03:00).

## Method

`python scripts/soak_test.py --minutes 60 --executor-model … --executor-effort …` runs the real
application loop (`spacedrums.app.main.run`):
- live camera;
- real perception on every frame (MediaPipe hands + stick estimator);
- the configured development C-GRU arm with A and B shadowing
  (`configs/live.arm-C.candidate.yaml`);
- the real audio callback;
- the dashboard worker (no window);
- the invariant monitor in `log` mode, the health monitor and the structured event log.

No person was present.

**Scripted strokes.** Every 15 s a **SYNTHETIC scripted stroke** replaces the perception output of
one hand for about 1.2 s, through the test-build `observation_hook`. The strokes use `app.synthetic`
kinematics (0.15 s down-stroke) re-timed to the live frames, alternating hands and zones. This way
tracking, prediction, geometry, commit, audio scheduling and mixing run periodically for the whole
hour.

**Instrumentation.**
- **Gain:** played samples were attenuated to 10 % (`--gain-scale 0.1`) so the unattended laptop
  did not play full-volume drums. Mixing and callbacks are unchanged.
- **Process sampler:** a sampler thread recorded the process's private bytes, working set, handle
  count and Python thread count every 5 s.
- **Audio probe:** an observation-only probe on `AudioScheduler.schedule` recorded each audio
  event's lead: target play time minus scheduling time.

Nothing else ran on the machine.

## Results

| Quantity | Value |
|---|---|
| Duration | 60.1 min (3,607 s wall) |
| Crash | **none** (exit 0) |
| Frames | 108,638 delivered at **30.18 FPS** (camera timestamps); interval p50 32.0 ms, p99 48.5 ms |
| Capture drops / stalls / duplicates / clamped timestamps | **1** / 3 (interval > 2 × nominal) / 0 / 0; no camera stall reached the 0.5 s health threshold (no SD-CAM-002) |
| Scripted strokes | 240 windows, 8,680 injected frames (8 % of frames) |
| Commits | A 240 (shadow: every scripted stroke), B 147 (sounding), C-GRU 0 |
| Model fallback | 1: C-GRU → B at start-up (01:50:20), total processing p95 over the configured budget (SD-MDL-001; the Phase 16 finding on HW-01) |
| Audio | 147 events scheduled; **0 underruns**; 0 device outages / recoveries; 0 clipped samples; 1,350,170 callbacks |
| Audio events counted late by the mixer | 147 of 147 (see below) |
| Audio lead at scheduling (target − scheduling time) | median −4.0 ms, p5 −17.4 ms, p95 +12.6 ms, max +13.9 ms; 103 of 147 already past their target when scheduled |
| Safety invariants (`log` mode) | **0 violations**; checks I1 387, I2 451,041, I3 534, I4 534, I5 388, I6 108,932 |
| Health / event log | 482 transitions; SD-TRK-001 ×241 and SD-TRK-002 ×240 (the scripted hand appears and vanishes), SD-MDL-001 ×1; 0 write errors |
| Per-frame processing (perception + decision) | p50 16.6 ms, p95 34.0 ms, max 87.9 ms |
| Dashboard | 108,638 records published, 0 dropped |

### Memory and handles

The process sampler took 722 samples, one every 5 s.

| | Start | 1 min | 5 min | 30 min | 50 min | 59 min | First 10 min (median) | Last 10 min (median) | Change |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Private bytes (MiB) | 754.9 | 931.7 | 933.9 | 936.6 | 937.4 | 937.4 | 932.6 | 937.4 | **+4.8 (+0.5 %)** |
| Working set (MiB) | 265.0 | 398.1 | 403.2 | 393.7 | 394.9 | 395.4 | 394.4 | 395.3 | +0.9 |
| Handles | 495 | 998 | 1,103 | 1,103 | 1,103 | 1,105 | 1,105.5 | 1,105 | −0.5 |
| Python threads | 2 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 0 |

**Start-up allocations.** Models, camera and audio were allocated in the first minute. After that:
- **Private bytes** rose 3.5 MiB between minutes 5 and 50, then stayed flat over the last 10
  minutes. The linear trend after minute 5 is +5.6 MiB/h.
- **Handles** stayed between 1,103 and 1,109.
- **Python threads** stayed at 5 (`threading.active_count()`, so OS threads of native libraries are
  not included).

No leak is visible at this scale in one hour. A slow growth below a few MiB per hour cannot be
excluded by a one-hour run.

### Interpretation

- **Reliability.** The loop ran an hour with no crash, no invariant violation, no audio underrun and
  one queue drop, at the camera's 30 FPS. The health monitor and the event log tracked every
  transition.
- **Model arm not soaked.** The configured model arm never sounded: on HW-01 its total processing
  p95 exceeds the configured budget, so it falls back to B at start-up (sticky). The hour therefore
  covered the fallback transition and arms B (sounding) and A (shadow), not an hour of C-GRU
  inference.
- **Late audio.** All 147 audio events of arm B were counted late by the mixer. Even when
  scheduled, B's anticipation lead was at most +13.9 ms and was already negative for 103 events.
  With the output latency unmeasured (placeholder 0, Phase 04 criterion 6 PENDING), a target that
  close precedes the buffer being filled.
  - These are SYNTHETIC 0.15 s down-strokes, and the capture-to-decision path takes a frame or more.
  - The number says nothing about real strokes. It is a latency property to be measured in Phase 18
    (live-stroke delay PENDING since Phase 16), not a soak failure.

## Limitations and PENDING

- **Not a person playing.** The run was unattended. SYNTHETIC scripted strokes replaced one hand's
  perception about 8 % of the time; real perception ran on every frame. **Person-played soak:
  PENDING.**
- **Model arm.** The model arm fell back at start-up, so the development C-GRU's long-run inference
  was not soaked. That needs a model and hardware that meet the budget.
- **Gain.** Played samples were at 10 % gain.
- **Duration.** One hour: longer sessions (e.g. a Phase 18 study day) are not covered.
- **Clean reproduction.** Clean reproduction after the owner commit is PENDING
  (`scripts/soak_test.py --minutes 60` on the committed tree, nothing else running).

Evidence files in the run directory:
- `soak-report.json` (digest);
- `soak-samples.json` (process samples);
- `app-summary.json` (full application summary);
- `logs/…/events.jsonl` (structured event log);
- `audit.json` (`source_unchanged = true`).
