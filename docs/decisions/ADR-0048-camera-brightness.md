# ADR-0048 — Camera brightness: natural preview, measured exposure guard, opt-in tracking tone

Date: 2026-10-16. Status: implemented candidate. The preview and the guard are default in `app.play`.
The tracking tone is opt-in. Live tracking effects were not measured with a player.
Evidence: [`../perf/camera-brightness.md`](../perf/camera-brightness.md).

## Context

The owner reported that the SpaceDrums image is much darker than Windows Camera in the same room.
Tracing showed three separate causes:

- **Short exposure.** -6 (15.6 ms) live and -5 (31 ms) demo, against Windows Camera's auto exposure
  (about 64 ms frame period, 15 FPS in this room).
- **Artistic darkening.** The stage multiplies the camera by 0.62 with a vignette down to 0.28 in the
  corners, and the kit view by 0.60 + 4. At -6 the stage showed a mean luminance of 14-20.
- **Exposure taken over by another app.** Opening Windows Camera switches the shared device to auto
  exposure. SpaceDrums falls to 15 FPS and stays there after Windows Camera closes, while the driver
  still reads back the requested value. This explains the owner's 20 FPS session.

## Decisions

- **Display brightness is a display decision.** `product.preview` (`--preview natural|raw|legacy`) is
  applied to a copy of the display image only. `natural` (default) removes the dim and the vignette and
  applies an auto gamma toward a mean of 115, the Windows Camera level (gamma 0.5-1, smoothed, never
  darkening). `raw` shows the camera pixels; `legacy` restores the previous look. The renderer defaults
  are unchanged, so other callers keep the old look.
- **Exposure is verified by measurement.** Read-back is unreliable on HW-01 and costs 5-23 ms per
  property. `camera_profile.exposure.guard` (native fragment) therefore watches the unique-frame rate
  in the capture thread.
  - MANUAL below `min_fps` (24): the exposure is re-applied (`REAPPLIED`).
  - AUTO below `min_fps` after `settle_s` (4 s): it switches once to `fallback_value` -5
    (`AUTO_TO_MANUAL`). -5 is the brightest fixed exposure measured at about 30 FPS (-4 gives 16).
  - Actions run after the hand-over, at most one per 2 s window and at most 10 in total, and are
    listed in the report.
  - `--camera standard` stays the unguarded previous path.
- **Exposure defaults are unchanged.** The live profile stays -6 (ADR-0044 owner decision) and the demo
  stays -5. `--exposure auto|VALUE` selects per launch. Recommendation: -5, or auto in good light.
- **Tracking correction is a separate, opt-in path.** `--tracking-tone auto` gives the hand model the
  same auto gamma. On 7 real recordings, hand presence rose in 6 and fell in 1. It is refused for red
  tips (no painted-tip recording; gamma moves saturation), and recordings stay raw.

## Consequences

- Preview brightness at -5 is about 108-110 (Windows Camera 115) at 30 FPS. At -6 it is 82-96, with
  visible noise. The tone costs about 1.9 ms p50 per displayed frame after the decision; capture,
  tracking and audio timing are unchanged.
- A camera app opened during play no longer leaves SpaceDrums at 15 FPS. The rate recovers within about
  4 s (measured: whole run 29.5 vs 17.0 FPS).
- `--exposure auto` runs at the camera's rate while converging. In a dim room that means 15 FPS for the
  first ~4 s.
