# spacedrums.ui

## Live mirror previews

Live camera windows mirror only the camera image, then draw every overlay on it in display space.
The live renderers take `mirror=True` (`draw_scientific_overlay`, `draw_guide`, `draw_wizard` and the
app's `render`): `preview.mirror_preview` makes an independent mirrored copy of the camera image (the
input, even an ROI slice of capture memory, is never changed), and a mirrored `canvas.Canvas` draws
the overlays from their camera coordinates onto that copy:

- scene overlays (ROI box, band, zones, cue highlights, hands, sticks, tracks, predictions,
  candidates) land on the mirrored pixels they describe;
- text is never reflected: a label keeps normal glyphs in the mirrored footprint of its camera-space
  box, and HUD content anchored to the ROI or the frame (status lines, badges, panels, progress and
  countdown bars) stays upright at the same place in its container.

Draw new live overlays and protocol cue hooks (`draw_hook` receives the ROI `Canvas`) through `Canvas`
methods, not raw `cv2` calls, so they follow the image. Never assign display pixels to a `FrameView`,
`ImageRef`, recorder, model input, or calibration/tracking record. ROI coordinates, zones and
handedness remain in the original camera coordinate system. Saved recordings, exported renderings,
screenshots, replay and annotation windows, and the camera-free dashboard retain their existing
orientation; `mirror=False` is the pixel-identical camera canvas. The developer exposure recorder
shows the mirror preview by default; `record --no-window` disables it. Synthetic exposure recordings
remain headless.

Per-frame window loops read keys with `cv2.pollKey()`, which does not wait. In the live app on HW-01
`cv2.waitKey(1)` took 2.0 ms per frame at the median against 0.4 ms for `pollKey` (T2 old/new
development runs, 2026-09-28); in a tight loop it waits up to a 15.6 ms Windows timer tick. The
one-shot `waitKey(1)` after destroying windows stays, and `scripts/measure_capture_latency.py` keeps
`waitKey(1)` because its measurement protocol defines it.

**Phase 14:** `wizard_views.py` IMPLEMENTED: `draw_wizard(frame, roi, WizardView)` draws the Calibration
Wizard screens (stand-here box and band, zones with the cued/selected zone highlighted, reach envelope,
step header, progress bar, key hints) from plain data built by `spacedrums.app.calibrate`; `ui` never
imports `calib` (independent L7 siblings). Tests: `tests/ui/test_ui_wizard_views.py`.

**Status:** `guide.py` IMPLEMENTED (Phase 02, prototype quality; tests in `tests/ui/`); `overlay.py` minimal debug overlay IMPLEMENTED (Phase 03, Task 03.15: landmarks, grip + prior, search region, candidates, axis, tip coloured by method with the MARKER fallback/benchmark tag, filtered tip + velocity, per-hand status; exercised by `scripts/benchmark_tip_methods.py`). Zone display (Phase 04) and the full dashboard (Phase 15) are PLANNED.

`draw_guide(frame, roi, band=(y0, y1), instruction, status_lines)` draws the fixed ROI box, the "hands here" band (ROI-normalized y, y down), the instruction "Stand so both hands and sticks stay inside the box" and a capture-stats line in which drops/duplicates/stalls are always visible. `scripts/show_guide.py` runs it live and saves a screenshot.
