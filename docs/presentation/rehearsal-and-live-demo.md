# Rehearsal and live-demo plan

Use the 15-slide English deck and the audit dated 17 October 2026. Member names, institution, supervisor and instructor-specific timing remain unprovided. Assign actual names before submission. The leader is one of the six members, ideally the core-processing presenter.

## Speaker order and timing

| Order | Presenter responsibility | Slides | Planned time |
|---|---|---|---|
| 1 | Team leader opening, problem, objectives, architecture and stack | 1–5 | 90 s |
| 2 | AI and Computer Vision | 6 | 85 s |
| 3 | Strike Detection and Motion Analysis | 7 | 85 s |
| 4 | Frontend and User Interface | 8 | 80 s |
| 5 | Backend and Core Processing | 9 | 85 s |
| 6 | Audio and Music Engine | 10 | 85 s |
| 7 | Mobile Application Development | 11 | 80 s |
| 8 | Team leader results, limitations, roadmap and closing | 12–15 | 70 s |

Spoken allocation: 660 seconds (11 minutes). Allow about 20 seconds total for handoffs and pointing, giving **11 minutes 20 seconds**. Q&A is separate. A 30-second optional demonstration brings the total to about 11 minutes 50 seconds. Do not add a long demo on top of this schedule. If the instructor requires 10 minutes, trim 10 seconds from each role and 20 seconds from the opening. Timing is a rehearsal estimate, not a recorded delivery result. Script notes and Q&A are not all spoken.

The frontend presenter advances slides and opens prepared images. The core presenter operates the application and owns the fallback. The audio presenter checks sound if a live demo is chosen. These are proposed operating responsibilities, not historical contributions.

Handoffs follow the spoken last sentence in each script: leader → CV → strike → frontend → core → audio → mobile → leader. Keep slide order unchanged. The AI presenter points to the fingertip evidence; strike points to the crossing and commit stages; frontend shows the kit; core follows the record chain; audio follows the scheduler/mixer; mobile clearly says “proposed.”

## Launch and preflight commands

Run from the repository root in PowerShell. Use the existing `.venv`, model assets and sample banks. No dependency installation or download is needed for the audit machine's verified demo preflight.

```powershell
# No camera or speaker is opened by these checks.
.\demo-spacedrums.ps1 --check
.\demo-sticks-spacedrums.ps1 --check

# Current HAND developer demo: full kit is the parser default.
.\demo-spacedrums.ps1

# Painted red-tip developer demo. Default dark_paint is false.
.\demo-sticks-spacedrums.ps1

# Explicit four-pad developer guide, if this is the rehearsed layout.
.\demo-spacedrums.ps1 --kit four

# Normal visible-stick product with standing/reach calibration.
.\play-spacedrums.ps1
```

These commands are grounded in the root launchers and `app/play.py:main`. `--demo` bypasses automatic reach calibration and uses a fixed guide. It enables 33 ms edge look-ahead. D toggles full-kit diagnostics; Esc or Q exits and writes the report. R retries normal-product calibration; it is inactive in developer mode. Do not switch modes, exposure, thresholds or kit layout during the talk to chase a successful hit.

The normal path also needs the pose model. The documented one-time fetch command is `.venv\Scripts\python.exe scripts/fetch_pose_landmarker_model.py`; do setup before the event, not during it. Demo `--check` verifies hand/sample assets but does not exercise the normal pose/calibration path.

The default camera mode is native, with standard fallback. `--camera standard` selects the older capture path if it was rehearsed. `--preview raw` disables display brightening. `--tracking-tone auto` is an opt-in, unvalidated hand-input change and should not be introduced as a presentation fix.

## Recommended fallback: genuine recorded-frame replay

The saved 572-frame session exists locally with `frames.jsonl` and lossless tracking frames. Unlike several earlier sessions, it actually supports replay. Use the following commands without `--recorded-roi`; that flag is incompatible with fixed demo geometry.

```powershell
.\.venv\Scripts\python.exe -m spacedrums.app.play --demo --fingers --replay data/dev-product/dev-product-20261017-005812-ccdb76de --no-audio
.\.venv\Scripts\python.exe -m spacedrums.app.play --demo --red-tips --replay data/dev-product/dev-product-20261017-005812-ccdb76de --no-audio
```

Say: “This is the current application processing recorded developer frames. Audio is disabled. We are showing behavior, not a new live benchmark.” The source recording contains painted sticks; HAND replay applies fingertip processing to that footage. It is not a separate bare-hand validation trial. Replay can run faster or slower than the original capture, and the on-screen FPS uses recorded timestamps. Its frame-rate display must not be quoted as a fresh camera measurement.

The replay run writes a new developer output directory automatically. These original raw sessions are git-ignored and will not accompany a plain Git checkout. The delivered screenshots are embedded in the PPTX, so the presentation itself does not depend on those recordings being available on the presentation computer.

## Optional live demonstration and stop rule

Use live mode only after a successful rehearsal on the actual camera, room lighting and audio device. The audit did not conduct a new physical trial, and historical instructions pause formal physical strike testing pending endpoint investigation. The presentation should default to the recorded evidence unless the team deliberately resumes and checks live operation beforehand.

1. Before the audience arrives, confirm the correct kit, input mode and actual sample audibility. Keep volume comfortable. For STICK, illuminate both painted tips at playing distance. Do not interpret a bright preview as good raw color evidence.
2. The frontend presenter shows the full kit. The core presenter exposes diagnostics and points to actual measured/missing states.
3. If both measurements are stable, perform only the previously rehearsed single-pad example. Count physical strokes and listen; a counter alone is insufficient.
4. If a tip is lost, the selected drum is unexpected, sound is absent, or setup takes more than 10 seconds, stop the live example. Press Esc/Q and use slide 8 or 13. Do not manufacture hits or claim the failed example succeeded.

Safe images: `assets/hand-replay-window.jpg` (kit), `hand-diagnostics-window.jpg` (one measured fingertip), `stick-diagnostics-window.jpg` (tracking loss), `recorded-four-pad-preview.png` (older recorded preview), and the two red-tip contact sheets. Diagrams explain audio without a hardware-dependent playback demo. No recorded audio or video clip is supplied as proof of successful play.

## Presentation-file and speaker checklist

- Open `SpaceDrums-Team-Presentation.pptx` on the final presentation computer and start slideshow mode. Check all 15 slides, fonts, image proportions and diagram arrows on the projector.
- Confirm embedded images work with the repository disconnected. Review slide notes and source citations. Keep `previews/` available as PNG fallback.
- Insert verified names/institution/supervisor only if required. Unknown details were intentionally omitted from the title.
- Verify that all six roles appear and that mobile is labeled unimplemented with unresolved scope.
- Each speaker rehearses once with the corresponding script and once from slide cues only. Time the spoken passage, excluding Q&A notes.
- Pronounce “MediaPipe,” “OpenCV,” “per-hand,” “measured point,” and “commit” consistently. Explain a commit as a software event, not a guaranteed correct heard hit.
- Each speaker states one limitation and one next step. Use “will” or “propose” for future work, never past tense.
- Leader reads the exact fresh test summary on slide 12. Do not substitute an old report's passing count.
- Run one complete team rehearsal with transitions and the fallback stop rule. Cut content if it exceeds 12 minutes.

## Technical questions

| Question | Evidence-based answer |
|---|---|
| Is STICK mode markerless? | Red-tip mode requires painted caps and is logged as MARKER. A separate visible-stick path exists but has unresolved reliability limits. |
| What does the AI predict in the current demo? | MediaPipe predicts hand landmarks in HAND mode. Current product strikes use Arm A. Learned temporal anticipation is a separate research path without accepted participant results. |
| Why did the wrong drum sound? | The earliest eligible edge can win a continuous downstroke; tracking/association can also be wrong. Independent intended-hit labels are needed to distinguish causes. |
| Is the calibration complete? | The developer demo has a fixed guide. Normal code fits and verifies reach, but independent live acceptance remains pending. |
| How fast is it? | Developer capture trials reached about 30 FPS under specified conditions. Recording can reduce this. Physical action-to-sound latency is not established. |
| Does a 128-frame buffer mean 2.7 ms total latency? | No. It is only buffer duration at 48 kHz. Camera exposure, delivery, processing, scheduling and audio hardware also matter. |
| Why not show a mobile mockup? | It would not prove implementation. Mobile scope and interface must first be agreed. |
| Why do tests pass while tracking fails? | Many tests exercise synthetic/contracts/replay conditions. Real color, blur, occlusion and intent need separate validation. Any fresh suite failure is disclosed too. |
| Can others reproduce the demo? | The source and configs are available, but ignored model/sample/recording assets and environment setup must also be present. A clean portable release has not been accepted. |

Claims to avoid: validated real-world accuracy from test counts; zero/guaranteed latency; markerless red tips; an implemented mobile app; passed calibration from fixed geometry; 1080p or 60 FPS delivery; all commits correct/audible; participant success; personal authorship inferred from Git. See `project-audit.md` for the full claim register.
