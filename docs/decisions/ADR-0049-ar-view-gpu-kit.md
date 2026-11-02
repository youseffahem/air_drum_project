# ADR-0049 — AR view: a GPU-rendered 3D kit over the live camera

Date: 2026-10-24. Status: implementation candidate behind `app.play --view ar`; the classic views stay
the default until the owner signs off a live A/B (FPS, drops, capture-to-schedule latency, commits per
hit against `--view classic`).

The owner supplied a reference screen ("SpaceDrums — AI Air Drumming"):
- the full-screen webcam with a realistic, neon-lit four-piece kit drawn into it, AR style;
- a brand card, a status card (FPS, latency, sticks, hands) and a "Stick Tracking" panel;
- piece callouts and a bottom control bar (Settings, Camera View, Sensitivity, Volume).

The camera must stay live, and stick-tip detection, hit detection and the audio engine must not change.

## Findings that drive the decision

- **No OpenGL in OpenCV.** The OpenCV build reports `GUI: WIN32UI` with no OpenGL and no FreeType, and
  no 3D or GUI toolkit was installed. ADR-0038 kept realistic kit visuals out of scope.
- **The offscreen context costs little.** A standalone moderngl context on this laptop opens in about
  180 ms. Upload, draw and RGBA readback of a 1280x720 frame plus `cvtColor` cost about 2.5 ms.
- **The default GPU is the iGPU.** The context lands on the Intel iGPU by default. Setting
  `SHIM_MCCOMPAT=0x800000001` in the process before the first context moves it to the RTX 4050.
- **Measured view cost (SYNTHETIC frames, this laptop):**

  | Setup | Cost |
  |---|---|
  | Full AR frame (kit, bloom, overlay), RTX 4050 | 3.4 ms p50 / 3.7 ms p95 |
  | Same frame, Intel iGPU | about 13 ms |
  | HUD on the CPU (premultiplied uint8 sprites) | 1.3 ms p50 |

- **Audio comes first.** Audio is scheduled inside `DecisionPipeline.step` before any rendering, so the
  view can delay only the next frame, never the current hit.

## Decisions

- **Renderer: moderngl offscreen (OpenGL 3.3) on the main thread.** The window stays HighGUI.
  - Per frame, the renderer uploads the unmirrored camera frame and renders the kit (PBR-style lacquer,
    chrome, coated heads, lathed brass, emissive neon) and the additive glow overlay into a 4x MSAA
    premultiplied colour target and an emission target.
  - It then runs a dual-Kawase bloom, composites over the mirrored camera and reads RGBA back.
  - Outside the kit and its glow, the camera pixel is passed through byte for byte (tested).
  - The new dependency is `moderngl` (+ `glcontext`). Pillow becomes a direct dependency for HUD text
    (Segoe UI and Segoe Fluent Icons, with a Hershey fallback).
- **The hit zones drive the drawing.** Each zone's impact segment, mapped through the one
  `DisplayMap`, is the horizontal major axis of the drawn head or cymbal ellipse.
  - A solver places each piece in 3D (centre, radius, roll; depth from its screen row) so the rim's
    extremes land on the segment endpoints. The error is ≤ 1.5 px, measured at 0.000 px for every
    viewpoint, ROI and capture mode.
  - The renderer never moves a zone.
- **16:9 display, unchanged tracking.** In native capture the AR view shows the whole 1280x720 frame
  (`LiveFrameSource.preview_full`, display only). The tracked 960x720 window sits inside it with 161 px
  of mirrored margin.
  - The hit zones must stay inside the tracked window, so the cymbals cannot reach the screen edges as
    in the reference.
  - Standard capture shows the tracking frame at 1.5x (960x720).
- **Reference four-piece kit.** `--kit reference` (`geometry/reference_kit.py`,
  `configs/demo.reference.candidate.yaml`) is the AR demo default.
  - It uses the four-pad ids, names and TR-505 samples. Cymbals sit outside and high; Tom (inner left)
    and Snare (inner right) sit low.
  - Every product floor holds. Because of the 32 px vertical-gap floor, the hi-hat sits about
    0.1 frame-height higher than in the reference.
- **Status shows measurements only.**
  - FPS is the rolling capture rate.
  - Latency is the rolling p50 of the logged capture-to-audio-schedule time plus the opened output
    stream latency. It is a software figure, not an acoustic measurement, and shows "—" when unknown.
  - Stick and hand states come from current `EndpointEvidence`.
  - The classic product view (`render_kit`) keeps its no-diagnostics rule; the AR view shows the
    panels in all modes (owner decision), and `H` hides them.
- **Controls.**
  - **Volume** maps to `AudioOutput.output_scale` (applied before enqueueing; the callback is
    untouched).
  - **Sensitivity** maps to `pipeline.geometry.v_min` (`v_min · 2^((0.7 − s)/0.3)`, clamped
    0.05-0.60).
  - The reference defaults (sensitivity 0.7, volume 0.8) give exactly today's `v_min` and
    `output_scale` 1.0.
  - **Camera View** offers virtual viewpoints (Front, High Angle, Low Angle; the alignment is
    re-solved) and capture devices (restart capture, reset tracking, and rebuild decisions or restart
    calibration).
  - Every change goes into `report.json` `ar_view.controls.changes`.
- **Fallback.** Without moderngl or an OpenGL 3.3 context, `--view ar` prints one JSON line, records
  `ar_view.fallback` and continues in the classic view.

## Consequences and limits

- Hands and sticks that dip below a head line go behind the drum, because the kit is drawn over the
  camera image. Tip markers are always drawn on top. Occlusion from the measured hand landmarks is a
  possible follow-up.
- The neon stick bands follow the estimated stick segment. In `--red-tips` mode without
  `--hand-assist` there is no segment, so only the tip disc and trail are drawn.
- Not measured yet:
  - live A/B against the classic view;
  - the 20-minute soak;
  - camera-switch behaviour on real hardware;
  - the iGPU cost inside the full loop.
