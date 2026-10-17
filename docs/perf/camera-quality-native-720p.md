# Camera image quality: native 1280x720 capture (ADR-0047)

Date: 2026-10-16. Hardware: HW-01 Dell integrated webcam (USB 0C45:6717), OpenCV 5.0.0, Windows 11.
Development evidence: one camera, one room, no player in front of the camera, room light **not
stable** (see §4). Nothing here is participant evidence or a tracking-accuracy result. Raw evidence
(JSON + PNG, git-ignored): `experiments/camera-quality-20261016-modes/` and
`experiments/camera-quality-20261016-compare-{exp6,exp5,exp6-hands,exp5-redtips}/`.

## 1. Root cause: why SpaceDrums looked worse than Windows Camera

The causes compound. The first two are about resolution and blur, the third and fourth about darkness.

1. **The 640x480 mode is a cropped, downscaled picture.** ECC registration of 640x480 frames against
   1280x720 frames of the same static scene gives scale 1.500-1.501 and an x offset of
   158.8-159.0 px (y < 0.3 px), with correlation 0.99, on both DSHOW and MSMF. The 640x480 mode is the
   centre 960x720 window of the sensor image scaled by 2/3 in the camera. Windows Camera shows the full
   16:9 1280x720 field.
2. **SpaceDrums then enlarges that 640x480 image by 1.5x for the 960x720 window.** The full-kit
   stage uses a bilinear `cv2.resize`; the developer and product views are stretched by the
   `WINDOW_NORMAL` window. Every displayed pixel is 1.5 camera pixels, which reads as blur.
3. **Exposure is short on purpose.** The live profile is MANUAL -6 (2^-6 s = 15.6 ms, gain 1); the demo
   is -5 (31 ms). Under AUTO, as Windows Camera runs, this room drives every mode on both backends down
   to **~15 unique FPS** (about 64 ms frame interval), which is how it gets its brightness. At 30 FPS
   the exposure cannot exceed about 31 ms (-5).
4. **The views dim the camera image on purpose.** The stage multiplies it by 0.62 with a vignette
   (`ui/stage.py` `DIM`) and the product kit view by 0.60 (`ui/kit.py`). Both are design choices and
   are unchanged. Press `d` in the full-kit demo for the undimmed developer view.

Not causes: no lossy compression in the old path (640x480 is uncompressed YUY2); no extra
colour conversion. Focus and autofocus are not exposed by the driver (read-back -1: fixed focus), and
auto white balance is already on.

## 2. What the camera actually delivers (verified, not advertised)

`scripts/camera_modes.py modes` (4 s per cell after warm-up; every frame's size checked; unique =
not byte-identical to the previous frame; "delivered" = every frame has the requested size at >= 80 %
of 30 FPS). FOURCC=MJPG requests gave the same result as no FOURCC in every cell (not shown).

| Backend | Requested | Delivered size | FOURCC read-back | Unique FPS -6 / -5 / AUTO | Duplicates (MANUAL / AUTO) | Interval p50 / p95 / max at -5 (ms) | Verdict |
|---|---|---|---|---|---|---|---|
| DSHOW | 640x480 | 640x480 | YUY2 | 30.12 / 30.12 / 15.04 | 0 / 0 | 32.0 / 47.8 / 48.8 | delivered (AUTO: light-limited) |
| DSHOW | 1280x720 | 1280x720 | YUY2 | 10.04 / 10.04 / 10.01 | 0 / 0 | 96.5 / 112.5 / 113.9 | **too slow** (USB bandwidth) |
| DSHOW | 1920x1080 | **1280x720** | none reported (compressed) | 30.13 / 30.15 / 15.05 | 0 / 0 | 32.1 / 46.5 / 49.4 | **1280x720 at 30 FPS** (chosen) |
| MSMF | 640x480 | 640x480 | 0x16 (RGB24 after MF decode) | 28.62 / 28.75 / 15.07 | 0.04 / 0.49 | 32.1 / 53.6 / 65.0 | delivered, pads duplicates |
| MSMF | 1280x720 | 1280x720 | 0x16 | 28.73 / 28.73 / 15.05 | 0.04 / 0.49 | 32.3 / 54.0 / 65.2 | delivered, pads duplicates |
| MSMF | 1920x1080 | **1280x720** | 0x16 | 28.61 / 28.59 / 15.05 | 0.04 / 0.49 | 32.2 / 53.4 / 66.0 | 1280x720 |

- **1920x1080 is not supported** on either backend. Every request returns 1280x720, the sensor maximum.
- An explicit 1280x720 + MJPG request on DSHOW negotiates YUY2 at 10 FPS: OpenCV's DSHOW wrapper drops
  the FOURCC. Only the 1920x1080 request reaches the compressed 720p mode.
- MSMF was not chosen: it pads about 4 % duplicate frames under manual exposure (49 % under AUTO), and
  the Phase 02 profile measured a 40-50 ms hand-over lag on MSMF against 0.2 ms on DSHOW
  (`docs/camera-profile-hw01-integrated-webcam.md` §3-4).
- The sweep's luminance and CPU columns are not comparable across rows: the room light changed during
  the 12-minute sweep, and the sweep computes image metrics on the full native frame. Use §3.

Device controls (DSHOW 720p, MANUAL -6, static scene):

| Control | Accepted | Effect |
|---|---|---|
| GAIN | 1-8 (setter fails above 8, read-back stays 8) | 8: luminance 36 -> 69 **and** temporal noise 3.95 -> 7.93 (same SNR) |
| BRIGHTNESS | 0-64 tested | +32 per 32 steps, noise unchanged: an offset that lifts blacks |
| FOCUS / AUTOFOCUS | read-back -1 | not exposed (fixed focus) |
| AUTO_WB / WB_TEMPERATURE | 1 / 4600 | auto white balance already on; not changed |

Neither gain nor brightness adds information, so neither is set by default
(`camera_profile.controls` stays empty; it exists for verified, restorable experiments).

## 3. Before / after: the app's capture path, A/B alternated

`scripts/camera_modes.py compare --repeats 2 --seconds 10`: standard and native arms alternated
(S N N S), 1 s settle, `cv2.setNumThreads(1)` as in `app.play`. "Hand model" runs the MediaPipe hand
landmarker on every frame and "red tips" the colour tracker. No player was present, so every hand-model
frame paid full palm detection.

| Condition | Arm | Delivered FPS | Drops | Interval p95 / max (ms) | Within 1.5x median | Hand-over lag p50 / p95 (ms) | Crop + downscale p50 / p95 (ms) | Process CPU (% of a core) | Display prep (ms) | Perception p50 / p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| -6 | standard | 30.20, 30.16 | 0, 0 | 48.0 / 52.1, 47.9 / 51.2 | 0.950, 0.960 | 0.1 / 0.4 | - | 24.3, 21.4 | 2.19, 2.10 | - |
| -6 | native | 30.15, 30.15 | 0, 0 | 48.5 / 72.0, 48.5 / 70.4 | 0.937, 0.930 | 3.7 / 6.5, 3.8 / 7.3 | 3.5 / 6.0, 3.6 / 6.9 | 18.9, 10.8 | 0.75, 0.78 | - |
| -5 | standard | 30.20, 30.19 | 0, 0 | 47.5 / 50.8, 47.8 / 52.3 | 0.954, 0.964 | 0.1 / 0.4 | - | 22.9, 21.8 | 2.13, 2.14 | - |
| -5 | native | 30.20, 30.15 | 0, 0 | 48.2 / 70.6, 48.8 / 71.9 | 0.940, 0.930 | 3.7 / 5.6, 3.9 / 6.9 | 3.5 / 5.3, 3.6 / 6.6 | 18.6, 12.8 | 0.77, 0.78 | - |
| -6, hand model | standard | 30.05, 30.10 | 2, 1 | 47.9 / 62.4, 48.0 / 50.4 | 0.963, 0.957 | 0.1 / 0.3 | - | 33.1, 41.7 | 1.76, 1.82 | 14.9 / 27.5, 15.4 / 32.0 |
| -6, hand model | native | 30.10, 30.14 | 1, 0 | 46.8 / 62.6, 46.8 / 58.4 | 0.990, 0.974 | 3.5 / 4.4, 3.6 / 5.1 | 3.3 / 4.2, 3.4 / 4.7 | 24.8, 22.7 | 0.77, 0.78 | 14.9 / 19.0, 14.9 / 19.0 |
| -5, red tips | standard | 30.15, 30.20 | 0, 0 | 48.0 / 53.2, 48.0 / 50.7 | 0.950, 0.947 | 0.1 / 0.4, 0.1 / 0.3 | - | 27.1, 24.3 | 1.90, 1.93 | 2.5 / 7.7, 2.4 / 4.7 |
| -5, red tips | native | 30.16, 30.15 | 0, 0 | 47.9 / 62.2, 47.7 / 58.8 | 0.953, 0.967 | 3.7 / 6.0, 3.6 / 4.6 | 3.5 / 5.6, 3.4 / 4.4 | 24.9, 18.6 | 0.76, 0.86 | 2.5 / 3.7, 2.2 / 3.0 |

Duplicates refused: 0 in every arm. Native open probe: 20/20 frames 1280x720, 30.5 unique FPS. The open
takes 4.7-5.0 s against 4.1-4.3 s for standard.

Field of view, registering each standard tracking frame against the native tracking frame (ECC
affine, 640x480 px): scale 0.9998-1.0003, offset dx -0.15 to -0.29 px, dy -0.10 to -0.20 px, correlation
0.989-0.996 in all four runs. **Tracking keeps the same field of view to within 0.3 px.**

Reading:

- **Real-time behaviour is preserved.** Delivered FPS, drops and perception cost are unchanged within
  run-to-run noise. The worst interval rises from about 50-53 ms to 58-72 ms: an occasional late frame,
  not a lost one.
- **CPU: native costs more.** The compare's CPU column above is dominated by the diagnostic's own
  metric work and is not a fair cost measure. In the real app (table below) native uses about 7 more
  points of one core, consistent with the mode sweep (compressed 720p 16-26 % against 1-3.5 % for 640x480
  YUY2). That is decode and conversion, mostly outside the capture thread, on a multi-core CPU.

`app.play --demo --red-tips --no-audio --no-window --max-seconds 12`, live, run once per mode back to
back (`experiments/camera-quality-20261016-play-{native,standard}/report.json`):

| Mode | Capture mode | Unique FPS | Drops | Frames | Capture -> decision p50 (ms) | Red-tip p50 (ms) | Process CPU, whole run (% of one core) |
|---|---|---|---|---|---|---|---|
| `--camera native` | NATIVE_CROP | 30.20 | 0 | 203 | 7.0 | 2.4 | 11.5 |
| `--camera standard` | STANDARD | 30.18 | 0 | 225 | 5.4 | 4.6 | 4.4 |

(Frames differ because the native open probe takes longer within the same 12 s.)
- **Latency cost: about +3.6 ms per frame** (p95 up to about +7 ms) between capture and hand-over. That
  is the single-threaded area downscale. A bilinear resize would cost about 1.2 ms but aliases; a
  separable implementation saved nothing (3.55 against 3.75 ms). Any extra latency of the camera's
  compressed mode **before** the frame reaches the PC is not measured here (§6).
- **Display:** 960x720 native pixels shown 1:1 instead of 640x480 upscaled; display preparation
  0.77 ms against 2.1 ms. Luminance-normalised display detail (gradient energy / luminance^2) is
  1.8-3.3x higher. That includes sensor noise at native scale, so check the saved images
  `display-standard-vs-native.png` in each compare folder.

## 4. The tracking frame is not pixel-identical: tone and noise

Tracking frames from the two modes differ in tone. Back-to-back captures at -5 (4 cycles, 6 s settle for
auto white balance, last 3 s measured) agree in direction in all 4 pairs although the room changed between
cycles (standard luminance 63-107):

| Pair | Mean luminance standard / native | 1st percentile (black level) | Mean HSV saturation |
|---|---|---|---|
| 1 | 81.9 / 74.5 | 24 / 14 | 85.8 / 117.9 |
| 2 | 79.0 / 56.2 | 20 / 8 | 84.3 / 119.2 |
| 3 | 63.5 / 50.0 | 15 / 7 | 113.7 / 60.3 |
| 4 | 107.0 / 96.4 | 33 / 20 | 54.0 / 80.3 |

- At the same exposure the native tracking frame is **~10-16 % darker in mean**, mostly in the shadows:
  its black level is lower in 4/4 pairs. A plausible explanation, **not verified**, is a limited-range
  YUY2 conversion lifting blacks in the old mode while the compressed mode uses full range.
- Saturation is higher in 3/4 pairs.
- Relative temporal noise (noise / luminance) is 1.3-1.7x higher in native tracking frames (-5: 0.044-0.049
  against 0.029-0.035); absolute noise is similar.
- The tracking-frame detail ratio (1.2-2.7x) also includes this noise.

Consequence: the hand model and the red-tip HSV floors (`s_min` 170) now see darker, more saturated,
deeper-black frames. Earlier evidence showed hand detection is strongly brightness-dependent
(ADR-0044, `camera-quality-20261004.md`). **The effect on hand presence, red-tip acceptance and strikes
is not measured** (no player was present). Run §6 before relying on it. `--camera standard` restores the
old frames exactly.

## 5. Recommended settings

| Goal | Command / setting |
|---|---|
| Default play (sharper view, same tracking geometry) | `.\play-spacedrums.ps1` (native is the default) |
| Previous camera path, byte-identical config | add `--camera standard` |
| Brightest image that keeps 30 FPS | add `--exposure -5` (31 ms; the demo launchers already use -5) |
| Like-for-like with Windows Camera | `--exposure auto`: about 15 FPS and longer motion blur in a dim room; for comparison, not for drumming |
| Gain / brightness | leave unset: measured to add noise or offset, not information |

The live product profile keeps MANUAL -6 (owner decision, ADR-0044); this change does not move it.

### Troubleshooting

- **The console prints `native mode not delivered; using the standard mode`.** The open probe did not
  see 1280x720 frames at 25 FPS or more. `report.json -> capture.capture_mode.rejected` says why
  (size, frame count or rate).
  - Close other camera apps (Windows Camera, Teams, browser tabs).
  - Check that no exposure override slower than 25 FPS is set.
  - Run `scripts/camera_modes.py modes --backends DSHOW` to see what the driver delivers now.
- **Strikes feel later or tracking seems worse.** Run with `--camera standard` and compare (§6). Native
  adds about 3.6 ms per frame and gives darker, noisier tracking frames at the same exposure.
- **The image is still dark.** In a dim room only more light or a longer exposure helps. -5 is the
  longest exposure that keeps 30 FPS, and the stage view dims the camera by design (`d` shows it
  undimmed). Gain 8 doubles brightness and noise alike.
- **Other cameras.** The fragment's `expect_px`/`crop_px` are measured for HW-01. On another camera
  the probe falls back to the standard mode. Measure with `camera_modes.py modes`, then register the
  standard frame against the native one (`compare` prints the FOV registration) before writing a new
  window.

## 6. Commands to verify with the webcam (owner)

```powershell
# 1. Modes the driver really delivers (no tracking, about 12 min, room frames saved locally)
.\.venv\Scripts\python.exe scripts\camera_modes.py modes --exposure profile --exposure -5 --exposure auto

# 2. A/B of the capture paths with the hand model under load (stand in view, keep still, about 2 min)
.\.venv\Scripts\python.exe scripts\camera_modes.py compare --repeats 2 --seconds 15 --perception hands
.\.venv\Scripts\python.exe scripts\camera_modes.py compare --repeats 2 --seconds 15 --exposure -5 --perception red-tips

# 3. Play both ways, then compare strikes with the existing block protocol
.\demo-sticks-spacedrums.ps1 --camera native
.\demo-sticks-spacedrums.ps1 --camera standard
.\.venv\Scripts\python.exe scripts\compare_play_sessions.py --run native data\dev-product\<native-session> snare=16 --run standard data\dev-product\<standard-session> snare=16

# 4. Capture latency A/B, screen-flash method (dark room, screen at normal brightness; the screen
#    flashes white). The display term cancels in the difference of the two medians.
.\.venv\Scripts\python.exe scripts\measure_capture_latency.py --base-config configs\prototype.candidate.yaml --camera-config configs\prototype.candidate.yaml --trials 30 --slug latency-standard
.\.venv\Scripts\python.exe scripts\measure_capture_latency.py --base-config configs\prototype.candidate.yaml --camera-config configs\camera\hw01-native-720p.candidate.yaml --trials 30 --slug latency-native
```

In (2), compare `hands_present_per_frame` and `perception_ms` between arms; tone and FOV are reported
too. In (3), use the same hits and the same position in both blocks.

## 7. Limitations

- One camera, one room, one afternoon. The light changed during the runs, so luminance and detail are
  compared only within alternated pairs.
- The detail metric (gradient energy) also rises with noise. Read it with the noise column and the
  saved images.
- No player: hand presence, endpoint acceptance, red-tip continuity and strike accuracy on native
  frames are unmeasured.
- Hand-over lag is `t_frame_available - t_capture` with the DSHOW grab-return stamp. Camera-side encoding
  and USB delay are not in it; §6 (4) measures them.
- **This is not a claim that SpaceDrums now matches Windows Camera.** It now shows the camera's
  highest delivered resolution at 1:1, but at 30 FPS its exposure is at most half of what Windows
  Camera uses in this room.
