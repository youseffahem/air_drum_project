# User messages and error-reporting conventions (Phase 17, Task 17.9)

Status: IMPLEMENTED (`src/spacedrums/app/errors.py`, `src/spacedrums/app/health.py`,
`src/spacedrums/app/main.py`; tests `tests/app/test_app_health_errors.py`,
`tests/system/test_system_app.py`). Thresholds are candidates (ADR-0040). The wording of every
message is fixed in `errors.CATALOGUE`; `tests/app/test_app_health_errors.py` checks that each code
below exists there with a message and guidance.

## 1. Conventions

- **Codes.** `SD-<COMPONENT>-<NNN>`, stable once published; components: `CAM` camera, `CAP` capture,
  `TRK` tracking, `MDL` model, `AUD` audio, `INV` safety invariants, `APP` application.
- **Severity.** INFO (state change, no action), WARNING (degraded; the session goes on), ERROR (a
  function is lost; the session goes on), CRITICAL (the session cannot continue or its results must
  not be used).
- **Where a message appears.** The console prints a component's message once when it enters a
  non-OK state (`[SD-XXX-NNN] Title: message`). The overlay shows the non-OK messages of the camera,
  capture, tracking and audio components (the model line keeps the Phase 13 `MODEL DISABLED` text);
  the dashboard header shows `health: camera … | tracking … | model … | audio …`.
- **Structured event log.** One JSON object per line (`<log-dir>/<session_id>/events.jsonl`;
  `--log-dir`, default `data/logs` for live sessions, in memory for replay / SYNTHETIC runs):
  `ts_wall` (ISO, local offset), `t_mono`, `code`, `severity`, `component`, `message`, `detail`
  (machine-readable: measured FPS, drops in the window, valid fractions, fallback reason, …),
  `session_id`, `config_hash`. Health transitions, invariant violations (bounded to 20 per
  invariant in `log` mode), audio outages / recoveries and the missing-camera error are logged.
- **Crash reports.** Any unexpected exception writes `crash-<time>.json` (`SD-APP-001`) next to the
  event log before it propagates: exception type and message, traceback, Python / platform,
  `session_id`, `config_hash`, `calibration_hash`, `git_sha`, the model block (`path`, `hash`,
  `manifest_hash`, `family`), frames processed and the last logged events. No image or audio data
  is written.
- **Expected failures** (`errors.ReportedError`) print their message and exit with code 3 without
  a crash report (camera not found). Calibration refusals keep exit code 2 (Phase 14).
- **Honesty rules.** Messages state what was measured (delivered FPS from capture timestamps, never
  the requested mode), never promise timing or latency, and say explicitly that a lost-tracking
  strike is not guessed.

## 2. Message catalogue

| Code | Severity | Condition (detection) | Title / user message | Guidance |
|---|---|---|---|---|
| SD-CAM-001 | CRITICAL | camera backend fails to open (`LiveFrameSource.start`) | **Camera not found.** The camera could not be opened. | Check that the webcam is connected and not used by another program, then restart. The configured device index/backend is in the config's camera_profile block. |
| SD-CAM-002 | ERROR | no frame for `stall_s` (0.5 s candidate) while the live source waits | **Camera stopped delivering frames.** No camera frame has arrived for a while; drumming is paused (no sound can be triggered). | Check the cable / privacy shutter. If frames do not resume, restart the application. |
| SD-CAP-001 | WARNING | delivered FPS over the 2 s window < 0.8 × requested (candidates) | **Low frame rate.** The camera is delivering fewer frames per second than requested (measured from capture timestamps). | Add light (the camera lowers its frame rate in dim light), close other camera or video programs, and keep the laptop on mains power. |
| SD-CAP-002 | WARNING | ≥ 3 queue drops in the window (candidate) | **Frames are being dropped.** Processing is falling behind the camera; some frames were skipped and strikes right after a gap are not committed. | Close other programs; use the experiment overlay mode instead of the full overlay. |
| SD-CAP-003 | WARNING | a clamped or refused timestamp in the window | **Camera timestamps irregular.** Some camera timestamps went backwards or ahead of delivery and were refused or clamped. | Usually harmless if rare; if it persists, switch the capture backend or timestamp source (camera_profile.timestamp_source = GRAB_RETURN). |
| SD-TRK-001 | WARNING | the better hand VALID in < 50 % of the window's frames (candidate) | **Poor tracking.** Hands or sticks are not tracked reliably; strikes may be missed (the system never guesses a strike while tracking is lost). | Stand inside the marked area, keep both hands and the stick tips in view, improve the lighting (avoid a bright window behind you) and keep the background calm. |
| SD-TRK-002 | INFO | a hand re-acquired after a loss | **Hand re-acquired.** Tracking of a hand resumed after a loss; prediction restarts after a short warm-up. | No action needed. |
| SD-MDL-001 | WARNING | sticky model fallback (inference fault, budget, cadence) | **Model fallback active.** The temporal model was disabled; the baseline arm now produces the sounds. | The reason is in the session log. Restart after correcting it (the fallback is sticky by design). |
| SD-MDL-002 | ERROR | the model package fails verification or loading | **Model could not be loaded.** The configured model package failed verification or loading; the baseline arm sounds. | Check the model path and hashes in the config's anticipator.model block. |
| SD-AUD-001 | ERROR | audio stream down: no callback for 0.5 s or start failure (candidates) | **Audio device problem.** The audio output stopped (device removed or failed); strikes are still detected and logged but cannot be heard. Reconnection is retried automatically. | Reconnect the headphones/speakers or select another output device in the config's audio.device block. |
| SD-AUD-002 | WARNING | underruns increased within the window | **Audio underruns.** The audio device reported buffer underruns; some sounds may be late or crackle. | Close other audio programs; increase audio.buffer_frames if this persists. |
| SD-AUD-003 | INFO | the audio stream restarted | **Audio device recovered.** Audio output is running again. | No action needed. |
| SD-INV-001 | CRITICAL | an I1–I6 safety invariant failed (monitor in `log` mode) | **Safety invariant violated.** An internal safety check failed (see the session log). | Stop the session and report the log: results from this session must not be used. |
| SD-APP-001 | CRITICAL | unexpected exception (crash report written) | **Unexpected error.** The application stopped because of an unexpected error; a crash report was written. | Send the crash report file (it contains no images or audio) to the developer. |

## 3. What is PENDING

- Wording review with users (Phase 18 participants / Phase 22 demo): the messages are the
  developer's candidates; no participant has read them.
- The thresholds behind each condition are candidates chosen from the failure-injection campaign,
  not tuned on participant sessions.
