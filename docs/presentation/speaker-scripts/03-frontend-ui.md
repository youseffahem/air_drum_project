# Frontend and User Interface

Slide 8. Target: 75–85 seconds. Purpose: explain the actual desktop interface. Show `assets/hand-replay-window.jpg`, a genuine screenshot of current full-kit replay.

## Spoken script

“My role is to explain the user interface. SpaceDrums currently uses an OpenCV desktop window.

This screenshot shows the real seven-piece developer kit. It contains crash, ride, two toms, hi-hat, snare and floor tom. There is no kick-tracking feature. The camera preview is mirrored for the player, while the geometry keeps a consistent coordinate system.

The full-kit view shows the pads, accepted tip trails and committed-hit feedback. Pressing D opens diagnostics with tip states and stroke reasons. The layout-preview tool can move or scale pads and save a layout file.

The normal product has a separate standing and reach-calibration flow. The developer demo uses a fixed guide instead. We must not describe that guide as a successful calibration.

The screenshot was captured while the application processed recorded frames. Audio was disabled. Its counters are software events, and its frame-rate display is not a new live benchmark.

Display brightness adjustment is implemented separately from tracking input. This improves visibility without proving better detection. Our next work is clearer mode and failure messages, followed by a usability rehearsal with the team.

The core-processing presenter will explain how the components exchange information.”

## Likely questions

- **Is this a website or mobile interface?** No. The current interface is Python/OpenCV on the desktop.
- **Does the UI create hits for the animation?** It displays pipeline results; this demo has no keyboard or timer hit generator.
- **Does brighter preview improve tracking?** Default preview tone affects display only. `--tracking-tone auto` is a separate opt-in hand path.
- **Is the seven-piece kit calibrated?** The demo uses configured fixed geometry. Reachability and independent accuracy remain pending.

Evidence: `ui/stage.py:StageRenderer`, `ui/developer_demo.py:DemoOverlay`, `ui/layout_preview.py:LayoutPreview`, `ui/preview_tone.py:PreviewTone`. Dependencies: expose stable CV, strike, audio-health and calibration states. Acceptance: users can identify mode, readiness and failure without mistaking stream status for correctness.
