# Standing Space Drums candidate

**Developer candidate. Physical reachability, strike accuracy and 30 FPS acceptance
have not passed.** The detailed status is in `docs/reports/standing-product-v1.md`.
This entry point does not start participant collection or change Phase 18.

## Start

From the project folder:

```powershell
.venv\Scripts\python.exe scripts/fetch_pose_landmarker_model.py
.\play-spacedrums.ps1
```

The pose model downloads once and its hash is checked on every load. The existing
hand model and recorded sample bank must also be present. Normal play is offline.

Stand centered with your waist and both sticks visible. Hold both sticks apart
briefly. Follow each pad's prompt and alternate your hands for six relaxed strokes.
The app then fits all four pads together and asks for another set of strokes.
Nothing requires dragging a drum or adjusting individual coordinates.

The product uses the whole 640×480 camera image. Keep your waist and a little space
below it visible so the body reference and lower row can be established.

The display order is fixed:

| | Left | Right |
|---|---|---|
| Upper | Crash / Ride | Hi-Hat |
| Lower | Snare | Tom 1 |

R starts a fresh calibration. Esc or Q closes the window. A failed calibration
keeps sound disabled and tells you to retry. The camera profile stays at the
existing 640×480 / requested 30 FPS settings; actual delivered FPS is logged.

## Developer validation

```powershell
.\play-spacedrums.ps1 --developer --record-frames
```

This writes local developer evidence under `data/dev-product/<session>/`:
`report.json`, timestamped observations, and (with `--record-frames`) full PNG frames
and `frames.jsonl`. Without that flag, pixels are not saved. Logs still contain hand
landmarks and measured endpoints. These files stay in the git-ignored data directory.

Replay a recorded product session without the camera or speakers:

```powershell
.venv\Scripts\python.exe -m spacedrums.app.play --replay data/dev-product/<session> --recorded-roi --no-audio
```

Developer text appears only with `--developer` or the explicit `--demo` mode below.
The normal product view has no impact animation.
Two simultaneous hits keep separate event IDs and use the existing polyphonic mixer.

## Current blockers

The first guided developer capture exposed marginal waist visibility and intermittent
endpoint support. The revised second run passed standing calibration, but accepted
only one stroke before timing out on the first drum. It delivered 24.78 FPS overall.
Live strike recall, reachability and 30 FPS remain unaccepted. Calibration failure is
preserved in the report; the app never silently substitutes guessed tips, old
calibration files or undersized zones.

## Professor developer demo: explicit fixed guide

Software checks have passed; **the live physical demo is NOT YET VERIFIED**.
**Physical strike testing is paused for the camera/endpoint investigation.**
The launcher below is for resuming the developer demo after that investigation:

```powershell
.\demo-spacedrums.ps1
```

This is `app.play --demo`, using the real webcam, existing MediaPipe hands,
axis-following visible endpoints, production measured-stroke decision pipeline,
and existing audio scheduler/mixer. There are no keyboard, button or timer hits.
The separate synthetic audio harness is not involved.

Only this explicit mode loads `configs/demo.professor.candidate.yaml`. It freezes
the previous standing guide, bypasses the incomplete reach calibration, and labels
the screen **DEV DEMO | FIXED GUIDE**. It never marks a
calibration as passed. Endpoint, tracking, motion and commit thresholds are unchanged.
The normal launcher still uses automatic calibration. Pose inference is unnecessary
in fixed-guide mode and is not loaded. R is inactive; Esc/Q closes and saves the report.

The owner-approved developer-only exposure is **MANUAL -5** (2026-10-04).
Production/default remains **MANUAL -6**. DSHOW, 640x480, requested 30 FPS,
negotiated YUY2, perception thresholds and fixed 2x2 geometry are unchanged.

Keep the existing camera placement. In the mirrored screen, Crash/Ride is upper
left, Hi-Hat upper right, Snare lower left, and Tom 1 lower right.

1. Stand in frame holding both sticks apart. Look for the green measured tip dots.
2. For Snare, put one tip in the gap between the rows, just above Snare's yellow edge.
   Starting above Crash/Ride and sweeping through both rows hits Crash/Ride first.
3. Make a clear downward stroke **across the yellow top edge**. Expect one Snare sound,
   one counter increment and a brief green pad outline.
4. Hold the tip inside the pad briefly. Expect no continuing sounds or increments.
5. Lift fully above that edge, then strike again. Complete five strokes total and
   compare the sound count and Snare counter with your five movements.
6. Test Crash/Ride, then Hi-Hat, then Tom 1. Each stroke must start above that pad's
   yellow edge. Approach the lower pads from the row gap.
7. If singles work, try simultaneous Snare and Hi-Hat, one stick on each side.
8. Press Esc. Report heard sounds, counters, unwanted sounds, and missed strokes.

The steps above remain deferred; do not begin the five-hit check yet. The next
proposed physical check is only: hold both sticks still, raise both, move one
slowly, then make one slow downward stroke while observing measured endpoints.

Counters prove commits, not audibility. `AUDIO OK` means the stream is RUNNING.
A tip that disappears is not replaced with a guessed endpoint. Keep both tips
separated; identity through overlapping sticks has not passed physical validation.

The window keeps the camera at its full size and uses a top-left, translucent,
content-sized HUD with 14 px text. Three lines show mode, delivered FPS/perception
time/audio state, and L/R tip presence. A fourth line shows the latest committed
drum and its count. Measured tips, trails and four drum zones remain visible.
Detailed reasons and drop counts stay in the logs. Normal user mode has no
developer HUD. ASCII separators and `TIP OK` avoid unsupported OpenCV font glyphs.
`data/dev-product/<session>/report.json` records full-run FPS, shutdown queue drops,
latency distributions, per-drum commits, endpoint reasons and audio health.
`observations.jsonl` ties current endpoints to trajectories, candidates, commit
gates, timing and sample events. Physical action-to-sound latency remains unknown.
Raw images are not saved by default; synchronous `--record-frames` can lower FPS.

An asset check that does not open either device is available:

```powershell
.\demo-spacedrums.ps1 --check
```

See section 19 of `docs/reports/standing-product-v1.md` for evidence and limitations.

For an independent developer camera audit that never starts strikes or audio:

```powershell
.\.venv\Scripts\python.exe scripts/camera_quality_experiment.py --output experiments/camera-audit-new
```

This measures the unchanged baseline first. `--profiles baseline -5 -4 -3 auto baseline`
explicitly selects the limited exposure comparison; `--preview` displays diagnostic
hand landmarks, search polygons, fitted axes, accepted endpoints and rejection reasons.
Each output directory must be new. Raw/diagnostic representative PNGs,
`observations.jsonl` and `report.json` are saved locally. No profile is adopted
automatically. See [camera investigation](../reports/camera-quality-20261004.md).

The isolated short endpoint check uses the developer configuration and never
constructs a strike decision pipeline or audio output:

```powershell
.\.venv\Scripts\python.exe scripts/check_developer_endpoints.py --output experiments/endpoint-check-new
```

Focus the preview and press Space/Enter to start four six-second cues: hold both
sticks still, raise both, move one slowly, and make one slow downward stroke.
Esc/Q stops; it closes automatically after the last cue. Per-frame measurements
and raw review frames are buffered, then saved after the camera closes. Review
images are JPEG quality 95; compression is never fed into live perception.
The four drum guides remain visible and the compact HUD reports `AUDIO OFF`.
