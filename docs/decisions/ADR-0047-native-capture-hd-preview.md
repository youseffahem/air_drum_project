# ADR-0047 — Native 1280x720 capture with an unchanged 640x480 tracking frame

Date: 2026-10-16. Status: implemented candidate, default in `app.play`; the effect on live tracking
(hand presence, red-tip acceptance, strikes) and the camera-to-photon latency of the compressed mode
are not yet measured with a player.

The owner reported that the SpaceDrums camera image looks much worse than the same webcam in the
Windows Camera app (darker, blurrier, noisier, lower resolution). Evidence:
[`../perf/camera-quality-native-720p.md`](../perf/camera-quality-native-720p.md).

## Findings that drive the decision (development evidence, HW-01, one room)

- **The 640x480 mode is a crop.** ECC registration of 640x480 against 1280x720 frames of a static
  scene gives scale 1.500-1.501 and an x offset of 158.8-159.0 native pixels (y < 0.3 px) on DSHOW and
  on MSMF. The 640x480 picture is the centre 960x720 window of the sensor image, scaled by 2/3 inside
  the camera. Windows Camera shows the whole 16:9 field at 1280x720.
- **The display then enlarges it.** The full-kit stage upscales 640x480 to 960x720 (bilinear), and the
  other views are stretched by the 960x720 window. Every displayed pixel is 1.5 camera pixels.
- **Darkness is mostly exposure, plus intentional dimming.** The live profile uses MANUAL -6
  (15.6 ms); the demo uses -5 (31 ms). Under AUTO, this room runs the sensor at about 62 ms, so every
  mode drops to about 15 unique FPS (Windows Camera's condition). The stage multiplies the camera
  image by 0.62 with a vignette, and the product kit view by 0.60. Both are design choices and are kept.
- **Only one 720p path reaches 30 FPS on the low-latency backend.** A DSHOW 1920x1080 request
  negotiates 1280x720 in a compressed format at about 30 unique FPS with no duplicates. A 1280x720
  request negotiates YUY2 at 10 FPS, and a FOURCC=MJPG request is not honoured through OpenCV's DSHOW
  wrapper. MSMF delivers 720p at about 29 FPS but pads with duplicates and hands frames over about
  40-50 ms late (camera profile §3-4).
- **Gain and brightness do not add information.** Gain accepts 1-8 (the setter reports failure
  above 8). Gain 8 roughly doubles both luminance and temporal noise. Brightness is an offset.
  Focus/autofocus are not exposed (-1). Auto white balance is already on.

## Decisions

- **Capture native, track unchanged.** `camera_profile.native_capture` (optional, additive schema
  1.11) requests 1920x1080, expects 1280x720, crops `[159, 0, 960, 720]` and area-downscales it to
  `resolution_px` [640, 480] in the capture thread before `t_frame_available`. Tracking, the ROI, zones,
  calibration, red-tip HSV/area/gate thresholds and the decision pipeline see a 640x480 frame with
  the same field of view as before. The conversion cost (about 1.5 ms p50) is inside the measured
  hand-over.
- **Verify, never trust properties.** The open reads `probe_frames` frames. Every frame must be 1280x720.
  Under MANUAL exposure the unique-frame rate must reach `min_fps` (25). Otherwise the standard
  640x480 mode is reopened and the reason is recorded
  (`report.json -> capture.capture_mode.mode == "STANDARD_FALLBACK"`). `fallback: FAIL` refuses to start.
- **Display the native window.** `LiveFrameSource.preview_image(sample)` returns the 960x720 window of
  the delivered frame. The stage uses it instead of its 1.5x upscale (its pad geometry is unchanged).
  The developer and product views draw on it with the ROI scaled by 1.5, and red-tip ROI-pixel
  markers are scaled once. The preview never reaches perception, calibration or a recorder:
  `--record-frames` still saves the tracking frame.
- **Default in `app.play`, reversible per launch.** `--camera native` is the default and
  `--camera standard` gives the previous capture with a byte-identical configuration. Research entry
  points (`app.main`, the wizard, Phase 02-19 scripts) never load the fragment.
- **Exposure stays a profile decision.** The live profile keeps -6 (ADR-0044 owner decision) and the
  demo keeps -5. `--exposure auto|VALUE` overrides it for one launch, for example to compare with
  Windows Camera. -5 (31 ms) is the longest exposure that keeps 30 FPS on this camera; AUTO trades
  frame rate and motion blur for brightness.
- **Device controls are opt-in and verified.** `camera_profile.controls` (GAIN, BRIGHTNESS, ...) is
  empty by default. A requested control is set once the stream runs, counted as verified only when
  the read-back equals the request, and restored on close.

## Consequences

- The preview shows 2.25x more pixels for the same field of view, and the window shows them 1:1.
- Measured A/B (evidence §3): delivered FPS (30.1-30.2), drops, duplicates and perception cost are
  unchanged. The field of view matches to within 0.3 px. Display preparation is cheaper (0.77 vs 2.1 ms).
  The single-threaded area downscale adds about 3.6 ms p50 (p95 up to about 7 ms) to every frame's hand-over.
  Process CPU in the real app rises by about 7 points of one core (11.5 % vs 4.4 %, red-tip demo).
- The tracking frame is not pixel-identical (evidence §4). At the same exposure, native tracking frames
  are about 10-16 % darker in mean, have a lower black level (4/4 pairs) and are more saturated (3/4).
  Their relative temporal noise is 1.3-1.7x higher. Hand detection and the red-tip HSV floors were tuned
  on the old frames, and the effect on them is **not measured with a player**. `--camera standard`
  restores the old frames exactly; the owner's A/B protocol is in evidence §6.
- The camera's compressed 720p mode may add delay before the frame reaches the PC. The screen-flash
  A/B in evidence §6 measures it. Until then, latency equivalence is not claimed.
- Not a claim that SpaceDrums now matches Windows Camera. At 30 FPS the exposure is at most 31 ms,
  while Windows Camera uses about 62 ms (15 FPS) in this room.
