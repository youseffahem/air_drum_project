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

Keys act in the space the window shows: the calibration wizard's `j` / `l` move the selected zone
left / right on screen in the mirrored live window too (`handle_key(..., mirror=True)` reverses the
camera x step); the stored nudges stay in camera coordinates.

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

## Full-kit stage view (`stage.py`)

`app.play --demo` (default `--kit full`) renders `StageRenderer`: the mirrored, dimmed camera upscaled to
960x720 with seven pads (crash, tom 1, tom 2, ride, hi-hat, snare, floor tom; no kick). Hits flash the pad in
its accent colour, spring the drum heads, wobble the cymbals, emit ripples and sparks, and feed a hit/combo
readout; fingertips leave a glowing trail and the strike edge brightens as one approaches. Everything is
display-only: `StageRenderer.to_display` is the one place that maps ROI-normalised camera coordinates to
display pixels, and it reads only committed strikes and endpoint evidence from the shared pipeline.
`D` switches to the diagnostic `DemoOverlay`; `--kit four` keeps the 2x2 guide. The renderer costs about
4 ms per frame (`latency_ms.render_ms` in the run report).

The seven pads are arranged like a drum kit seen from the player's seat (`configs/demo.fullkit.candidate.yaml`,
profile `full-kit-v2`): crash high left, ride high right, hi-hat left in front of the snare, snare low
centre-left, tom 1 above it, tom 2 right of and a little higher than tom 1, floor tom low right and largest.
Cymbals are wide and shallow, drums deeper; every pad is the polygon the strike geometry uses, so what is drawn
is what is hit. `--kit four` and the 2x2 guide are unchanged.

### Layout preview (`layout_preview.py`)

Stand where you normally play and check the kit before accepting it:

```
python -m spacedrums.app.play --demo --fingers --layout-preview
```

It draws each pad's display coordinates and pixel size with its hit count, each hand's measured fingertip
reach (p5-p95 box and recent points; a pad's text turns red when no measured fingertip has been seen both
above its top edge and inside it) and a message line. Keys: `i`/`k` move the whole kit up/down, `j`/`l`
left/right (as displayed), `[` / `]` scale it, `s` saves `kit-layout.yaml` into the session directory. A nudge
is applied only if it stays inside the ROI, keeps pads from overlapping and keeps the product floors
(72 x 42 px pads, 32 px gaps, checked pairwise); otherwise the reason is shown and the kit stays as it was.
Reuse a saved layout with `--demo --kit full --kit-layout PATH`. Only zones, registry and decision state are
rebuilt on a nudge; the audio stream keeps running. No fingertip or stick threshold is involved.

`python scripts/preview_kit_layout.py --session DIR --output OUT` renders the same view offline from a
developer session's `observations.jsonl` and prints a per-pad reach verdict and clearance table.
