# AR view — first live checks (development evidence)

Date: 2026-10-24.

**Setup**
- Machine: this laptop (i7-13650HX, RTX 4050 Laptop GPU, on battery).
- Camera: DSHOW index 0.
- Command: `app.play --demo --fingers --no-audio`, 20 s per run.
- Nobody was in front of the camera, so these runs measure display cost and capture rate only. They
  say nothing about tracking, hits or sound.
- Native capture fell back to the standard 640x480 mode on this laptop: its camera reports 1920x1080,
  while the native profile expects HW-01's 1280x720. So the AR view composed 960x720 (4:3), not the
  16:9 canvas.

**Status**
- Reports are under the session scratch directory and are not committed.
- Still pending: the owner's played protocol (ADR-0049) and an AC-power repeat.

## Runs

| Run | View | Camera FPS | Dropped / delivered | render_ms p50 / p95 | frame_work_ms p50 / p95 | readback p50 | HUD p50 | CPU % (one core) | Exposure guard actions |
|---|---|---|---|---|---|---|---|---|---|
| classic-3 | classic | 29.7 | 0 / 347 | 0.8 / 0.9 | 19.7 / 22.1 | - | - | 46 | 0 |
| classic-4 | classic | 29.8 | 0 / 347 | 0.8 / 1.0 | 20.3 / 30.1 | - | - | 49 | 0 |
| ar-5 | ar | 29.5 | 3 / 313 | 10.1 / 11.1 | 30.4 / 38.1 | 6.7 | 1.7 | 68 | 0 |
| ar-6 | ar | 29.6 | 2 / 322 | 10.7 / 11.6 | 30.4 / 35.0 | 6.7 | 1.9 | 67 | 0 |
| ar-7 | ar | 29.6 | 2 / 281 | 9.3 / 10.1 | 21.3 / 30.0 | 6.6 | 1.3 | 48 | 0 |
| ar-8 | ar | 29.5 | 3 / 322 | 9.5 / 10.6 | 28.3 / 37.7 | 6.8 | 1.6 | 63 | 0 |
| ar-10 | ar | 29.6 | 2 / 321 | 9.8 / 10.8 | 25.8 / 30.8 | 6.7 | 1.6 | 61 | 0 |

## Findings

- **Camera rate holds.** The camera rate stays at about 29.5 FPS in the AR view (classic: 29.7-29.8).
  Drops rise from 0 to about 0.7-1.1 % of frames.
- **Two startup bugs, found and fixed in these runs:**
  - *Context on the iGPU.* MediaPipe loads OpenGL while it starts, before the first AR frame, so the
    renderer's Optimus preference came too late and the context landed on the Intel iGPU: readback
    9.8 ms. `ARView()` now sets the preference at construction, before any model starts.
  - *First-frame stall.* The first context and shader compile take about 2 s on the NVIDIA driver.
    On the first frame that starved the capture thread: about 1 delivered frame in the first second,
    and the exposure guard re-applied MANUAL once per run. `ARView.prewarm()` now builds the context,
    shaders and HUD text before the camera starts. The renderer resizes its targets instead of being
    recreated. Afterwards: 28-30 frames in the first second and no guard actions.
- **Readback dominates the render.** Readback is about 6.7 ms in the live loop, against 2.3-2.6 ms in
  an offline loop with the same frame size.
  - MSAA 0, 2 or 4 does not change it, nor does a 1 ms GIL switch interval or reading through a pixel
    buffer object.
  - Render p95 is 10-12 ms, above the 8 ms proposal in the plan. Frame work p95 reaches 35-40 ms in
    some runs, which explains the extra drops.
  - Next options:
    - repeat on AC power;
    - asynchronous double-buffered readback (one display frame of latency; never delays audio);
    - drawing the HUD on the GPU.
