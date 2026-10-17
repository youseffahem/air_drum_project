# Camera brightness: where it is lost and what fixes it (ADR-0048)

Date: 2026-10-16 (afternoon). Hardware: HW-01 integrated webcam, native 1280x720 path (ADR-0047),
OpenCV 5.0.0, DSHOW. Development evidence: one room, no player at the camera during the live
measurements. The hand-detection numbers come from **existing recordings** (`data/dev-captures`).
Evidence (git-ignored): `experiments/dark-20261016-*`.

## 1. Every stage that changes brightness

| Stage | Before | After (default `app.play`) |
|---|---|---|
| Sensor exposure | MANUAL -6 (15.6 ms) live, -5 (31 ms) demo | unchanged; `--exposure auto\|VALUE`; guarded (§3) |
| Another app changes the exposure | Windows Camera switches the shared device to **auto**: 30 -> 15 FPS, persists after it closes, read-back still says -5 | **guard re-applies** the exposure (§3) |
| Native vs standard capture tone | native ~10-16 % darker, lower black level (ADR-0047) | unchanged (tracking frames are not altered) |
| Crop + area downscale | mean-preserving (< 0.5 levels) | unchanged |
| Stage view (`--demo`, full kit) | x0.62 everywhere, vignette down to x0.28 in the corners | **off** (`--preview legacy` restores it) |
| Product kit view | x0.60 + 4 | **off** (`--preview legacy`) |
| Developer/diagnostic view | none (HUD patch only) | unchanged |
| Preview tone | none | **auto gamma toward mean 115**, display only (§4) |
| Window | none | none |

The image the stage showed at -6 had a mean luminance of **14-20**. The camera delivered 28-39, and
the view halved it again.

## 2. Exposure: auto vs fixed, same room, same path

`scripts/camera_modes.py exposure`, native path, guard off, 6 s settle (auto exposure and white balance
converge after every open), 8 s measured. Settings were run forward and then reverse
(`experiments/dark-20261016-exposure-native/`). Both values are listed where two runs exist.

| Setting | Exposure | Unique FPS | Interval p50 / p95 (ms) | Tracking-frame luminance | Temporal noise | Natural preview luminance (gamma) |
|---|---|---|---|---|---|---|
| AUTO | camera's choice (~64 ms period) | **15.04, 15.07** | 63.9 / 101.0, 95.3 | 115.3, 114.5 | 2.87, 2.94 | 115.4, 114.6 (1.00) |
| -7 | 7.8 ms | 30.19, 30.18 | 32.0 / 48.7 | 10.3, 12.8 | 1.87, 2.80 | 49.2, 54.7 (0.50) |
| -6 | 15.6 ms | 30.19, 30.18 | 32.0-32.1 / 48.2-48.5 | 28.1, 39.2 | 3.10, 4.48 | 81.4, 95.7 (0.50) |
| **-5** | **31.3 ms** | **30.19, 30.19** | 32.0 / 48.9-49.8 | **52.8, 72.6** | 2.41, 2.99 | **108.6, 110.3** (0.51-0.64) |
| -4.5 | truncated to -4 | 16.07, 16.06 | 63.9 / 66.2-66.4 | 157.7, 133.2 | 3.24, 2.80 | = camera |
| -4 | 62.5 ms | 16.06, 16.06 | 63.9-64.0 / 66.4 | 134.1, 105.9 | 2.82, 2.46 | = camera |
| -3 | clamped to -4 | 16.06, 16.06 | 64.0 / 66.2-66.3 | 127.5, 108.4 | 2.78, 2.48 | = camera |

- **-5 is the brightest fixed exposure that keeps ~30 FPS.** The next available step (-4; -4.5 and -3
  behave as -4) halves the rate to 16 FPS.
- AUTO gives the Windows Camera brightness (about 115) at **15 FPS** in this room. It has longer, more
  jittery intervals (p95 95-101 ms) and up to 64 ms of motion blur per frame. It is real-time only in
  brighter light.
- Room light drifted between the passes (for example -5: 52.8 then 72.6). Compare rows within one pass.
- With the hand model running every frame (`experiments/dark-20261016-exposure-native-hands/`):
  perception p50 15.1 / 14.9 ms (-5), 15.0 / 14.9 ms (-6) and 16.1 / 16.1 ms (AUTO), 0 drops. No player
  was present, so this is compute cost, not detection.

## 3. The exposure guard (measured, not read back)

The owner's 15:24 red-tip session (`data/dev-product/dev-product-20261016-152425-f8b7225e`) delivered
**20.3 FPS**. It ran at 29-30 FPS for 15 s and then at exactly **14.8-15.0 FPS** until the end. The camera
itself slowed: 20.5 raw reads/s, 0 late deliveries.

Reproduced on demand: opening Windows Camera while SpaceDrums streams gives 30.0 -> 14.8 FPS within
2.5 s, and it stays at 15 FPS after Windows Camera is closed (`dark-20261016-wincam-native`, whole run
17.0 FPS). Throughout, the driver read back `EXPOSURE -5` and `AUTO_EXPOSURE -1`, while the frames showed
auto exposure (luminance 73 -> 120). Each property read also costs 5-23 ms. A second OpenCV client
cannot take the camera (MSMF read error, DSHOW refuses to open), so the frame server path of Windows
Camera is the trigger. Re-applying the manual exposure restores 30 FPS within about 1 s.

`camera_profile.exposure.guard` (native fragment) measures the unique-frame rate in the capture thread:

| Scenario | Without guard | With guard |
|---|---|---|
| Windows Camera opened at 8 s, closed at 16 s, MANUAL -5 | 17.0 FPS; 15 FPS from 2.5 s to the end | **29.5 FPS**; one `REAPPLIED` (at 23.5 FPS, luminance 117); back to 29.5-30 within 4 s, also while Windows Camera stayed open |
| `--exposure auto` in this room | 15 FPS throughout | 15 FPS while converging, then one `AUTO_TO_MANUAL` -> -5 at 4 s (14.5 FPS, luminance 125); 27.5-30 FPS after |

The guard acts after the frame is queued, at most once per 2 s and at most 10 times. Every action is
listed in `report.json -> capture.capture_mode.exposure.guard.events`. `--camera standard` keeps the
previous unguarded capture.

## 4. Preview brightness (display only)

`product.preview` / `--preview natural|raw|legacy`. The default `natural` removes the views' artistic
darkening and applies an auto gamma (target mean 115, the Windows Camera level, gamma >= 0.5, smoothed
15 % per frame, never darkening). Black stays 0 and white stays 255.

| Exposure | Camera mean | Stage before | Kit view before | Diagnostic view before | **Natural after** (gamma) |
|---|---|---|---|---|---|
| -6 | 28.3 / 39.2 | 14.3 / 19.9 | 21.0 / 27.5 | 28.3 / 39.2 | **81.7 / 95.7** (0.50) |
| -5 | 52.7 / 72.5 | 26.8 / 37.0 | 35.6 / 47.5 | 52.7 / 72.5 | **108.4 / 110.0** (0.51 / 0.64) |
| AUTO (15 FPS) | 115.2 / 114.7 | 59.0 / 58.8 | 73.1 / 72.8 | 115.2 / 114.7 | 115.2 / 114.7 (1.00) |

The visual comparison is in `experiments/dark-20261016-exposure-native/before-after-panel.png`.

- At -5 the natural preview matches Windows Camera's mean brightness at twice its frame rate.
- At -6 it reaches 82-96, but gamma 0.5 makes the sensor noise visible: a gamma redistributes levels and
  cannot add light.
- Live cost (`dark-20261016-play-window-*`, red-tip demo, 14 s):
  - tone 1.85 ms p50 / 2.41 ms p95 per displayed frame, on the display path after the strike decision;
  - FPS 30.05 (natural) vs 29.74 (legacy);
  - capture-to-decision p50 7.1 vs 6.8 ms (noise).

The preview never reaches tracking. `--record-frames` saves the raw tracking frame (tested).

## 5. Tracking-side correction: opt-in, not default

An offline test ran the app's hand model in VIDEO mode, as live, on existing recordings. Each recording
was run with its original frames and with the same auto gamma applied to the tracking frame
(`experiments/dark-20261016-tracking-tone/result.json`). Presence is the share of hand slots detected.

| Recording | Exposure, mean | Hand presence | Both hands | Stick found | Same presence decision |
|---|---|---|---|---|---|
| swing-L2-exp-5 | -5, 76 | 0.798 -> 0.839 | 0.602 -> 0.684 | 0.462 -> 0.629 | 0.88 |
| dist-d080-L2-exp-5 | -5, 81 | 0.495 -> 0.616 | 0.050 -> 0.261 | 0.001 -> 0.151 | 0.80 |
| dist-d080-L2-exp-5-t2 | -5, 79 | 0.907 -> 0.958 | 0.815 -> 0.916 | 0.757 -> 0.779 | 0.92 |
| swing-L2-exp-6 | -6, 40 | **0.421 -> 0.333** | **0.187 -> 0.129** | 0.047 -> 0.181 | 0.69 |
| dist-d080-L2-exp-6 | -6, 43 | 0.306 -> 0.482 | 0.034 -> 0.149 | 0.052 -> 0.213 | 0.75 |
| dist-d080-L2-exp-6-t2 | -6, 43 | 0.492 -> 0.827 | 0.200 -> 0.676 | 0.137 -> 0.495 | 0.51 |
| swing-L2-exp-7 | -7, 18 | 0.000 -> 0.009 | 0 -> 0 | 0 -> 0 | 0.99 |

Presence rose in 6 of 7 recordings and fell in one fast-swing recording at -6. Presence is not accuracy:
no ground truth exists, and up to half of the per-frame decisions changed. A correction is therefore
available as **`--tracking-tone auto` (opt-in, HAND/fingertip/visible-stick only)**:

- It is refused with `--red-tips`: gamma shifts the saturation the red-tip floors use, and no
  painted-tip recording exists to validate it.
- The recorded frame stays raw, so a replay with the flag reproduces the run.
- It is not live-validated. Run §6 before relying on it.

The more reliable route to brighter tracking frames is more light on the sensor: -5 instead of -6,
or more room light.

## 6. Owner live checks

```powershell
# What you see now (natural preview, guarded native capture). Compare with Windows Camera side by side;
# the guard keeps SpaceDrums at 30 FPS when Windows Camera opens.
.\demo-sticks-spacedrums.ps1
.\demo-spacedrums.ps1 --preview raw          # camera pixels, no tone
.\demo-spacedrums.ps1 --preview legacy       # the previous dimmed look

# Brightest real-time exposure vs the live default, fingers, 60 s each, same position
.\play-spacedrums.ps1 --exposure -5
.\play-spacedrums.ps1 --exposure -6
.\play-spacedrums.ps1 --exposure auto        # bright in good light; falls back to -5 if < 24 FPS

# Exposure sweep with you in view (hands per frame, tracking cost), about 6 min
.\.venv\Scripts\python.exe scripts\camera_modes.py exposure --exposure auto --exposure -6 --exposure -5 --perception hands

# Tracking-side gamma A/B, fingers, same 16 snare hits each, then compare
.\demo-spacedrums.ps1 --kit four
.\demo-spacedrums.ps1 --kit four --tracking-tone auto
.\.venv\Scripts\python.exe scripts\compare_play_sessions.py --run raw data\dev-product\<first> snare=16 --run toned data\dev-product\<second> snare=16
```

## 7. Limitations

- One room, one afternoon; the light drifted between passes.
- No player was present in the live runs. Hand numbers come from older recordings at 640x480 YUY2
  (the standard path), not native frames.
- The guard's trigger is measured with Windows Camera only. Other camera apps were not tested.
- Gamma cannot recover the SNR of a short exposure. The -6 preview is bright but noisy.
- Not a claim of matching Windows Camera at -6: Windows Camera's brightness comes from a 4x longer
  exposure at half the frame rate.
