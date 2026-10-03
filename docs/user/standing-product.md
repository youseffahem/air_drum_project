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

Developer text appears only with `--developer`. No impact animation is added.
Two simultaneous hits keep separate event IDs and use the existing polyphonic mixer.

## Current blockers

The first guided developer capture exposed marginal waist visibility and intermittent
endpoint support. The revised second run passed standing calibration, but accepted
only one stroke before timing out on the first drum. It delivered 24.78 FPS overall.
Live strike recall, reachability and 30 FPS remain unaccepted. Calibration failure is
preserved in the report; the app never silently substitutes guessed tips, old
calibration files or undersized zones.
