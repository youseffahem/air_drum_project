# Calibrating Space Drums

The Calibration Wizard fits the virtual drum zones to your camera placement and your reach, and
measures how long each of your sticks looks to the camera. With the default settings the measurement
windows add up to about one minute for the four-zone layout; reading the instructions and any repeats
come on top. You need the camera in its usual place, both sticks, and space to swing.

The wizard writes one calibration file. The app uses it when you start playing and records its
fingerprint (hash) with every session, so each session shows the calibration it used.

## 1. Start the wizard

From the repository root:

```powershell
# your own calibration (use a nickname, never your real name)
.venv/Scripts/python.exe -m spacedrums.app.calibrate --user-tag dev-jo

# a shared calibration for a desk / room set-up
.venv/Scripts/python.exe -m spacedrums.app.calibrate --scope SETUP --setup-tag hw01-desk

# the seven-zone layout instead of the four-zone one
.venv/Scripts/python.exe -m spacedrums.app.calibrate --user-tag dev-jo --layout v1-7
```

The file is written to `configs/calibration/user-<tag>-hw-01.calib.yaml` (or
`setup-<tag>.calib.yaml`). **Participant calibrations** (Phase 18) use `--participant` and are
written under `data/calibration/`, which is never committed.

A calibration file that is still valid is not overwritten by accident. To replace it on purpose, add
`--recalibrate`.

## 2. The six steps

Every step shows what to do. Press **SPACE** to start its measurement. Hold the pose for the short
countdown and until the bar is full. The wizard then shows a result:

| Key | Meaning |
|---|---|
| SPACE | start the step's measurement |
| ENTER | accept the result and go on |
| r | redo this step |
| f | use the default for this step (only where a default exists) |
| q | quit; your progress is kept, continue later with `--resume` |

1. **Camera check.** Stand still. The wizard confirms that the camera and its settings match the
   configuration and gives a lighting hint. *If it reports a profile mismatch, the configuration is
   wrong; fix it, then start again.*
2. **Playing area.** Stand so that both hands and both sticks stay inside the green box. Move both
   hands slowly left and right through the yellow band. If the wizard says **MOVE CLOSER** or
   **MOVE FARTHER**, step accordingly and press **r**.
3. **Stick length.** Hold both sticks **still**, pointing up and away from you, fully visible, until
   the bar is full. If a stick could not be measured, the wizard uses the default length and says
   so. Press **r** to try again (better light helps), or **f** to use the default for both sticks.
4. **Zone placement.** Slowly sweep both stick tips over everything you can comfortably reach: far
   left to far right, high to low. The drum zones are then fitted to that area (cyan box). Before
   you accept, you may adjust:
   - **n** selects the next zone, **i / j / k / l** move it up / left / down / right, a little at a
     time and only a short distance;
   - **s** changes the sound of the selected zone.
   Zones may not overlap. If two overlap, **ENTER** is blocked until you move them apart. **f**
   keeps the original fixed layout instead of the fitted one.
5. **Test strikes.** When a zone lights up, hit it once. Each zone is cued five times, and either
   hand may play. The result shows how many strikes were detected per zone. If some zones were
   missed or triggered their neighbour, press **p** to redo the placement or **r** to strike again.
   **v** skips the test, but a calibration without test strikes is marked as such.
6. **Save.** Check the summary and press **ENTER**.

## 3. Play with your calibration

```powershell
.venv/Scripts/python.exe -m spacedrums.app.main --calibration configs/calibration/user-dev-jo-hw-01.calib.yaml
```

Or put `calibration_path: configs/calibration/user-dev-jo-hw-01.calib.yaml` in your configuration
file. The app prints `calibration: CALIBRATED <id> (<hash>)`. The recording tool accepts the same
`--calibration` option.

Without a calibration, the app prints `calibration: UNCALIBRATED`, uses the built-in layout, and
records that in the session.

## 4. When you must calibrate again

The app refuses a calibration that no longer matches, and tells you why:

| Message | Cause |
|---|---|
| `CAMERA_PROFILE_CHANGED` | the camera or any camera setting (exposure, resolution, ...) changed |
| `ROI_CHANGED` | the playing box on the screen changed |
| `GEOMETRY_VERSION_CHANGED` | the app's drum-zone rules changed in a newer version |
| `TEMPLATE_CHANGED` | the built-in layout your calibration started from was edited |

Also calibrate again when you move the camera, stand elsewhere, or use different sticks. To check a
file without starting the app:

```powershell
.venv/Scripts/python.exe -m spacedrums.app.calibrate --check configs/calibration/user-dev-jo-hw-01.calib.yaml
```

Do not edit a calibration file by hand. The app rebuilds the layout from the recorded steps and
refuses a file whose zones were changed.

## 5. If it does not work

- **Hands not tracked / "both hands VALID 20 %".** Improve the light (see the lighting checklist) and
  stay inside the box.
- **"only N still frames".** Hold the sticks still for the whole bar, fully visible against a plain
  background.
- **Layout clamped / shifted.** Your sweep was very small or went outside the box. Redo the sweep
  more slowly, or step closer or farther.
- **You cannot finish.** Press **q**. No calibration is written and the app keeps using the
  built-in layout. Run the wizard again with `--resume` to continue where you stopped.
