# spacedrums.capture

**Status:** IMPLEMENTED (Phase 02). Tests: `tests/capture/` (unit + opt-in hardware integration). Layer L1: imports only `contracts`, `timing`, `config`.

| Module | What it does |
|---|---|
| `roi.py` | `Roi` + the single px <-> ROI-normalized mapping (`px_to_norm`, `norm_to_px`, ADR-0005) and `crop_roi` (pure slicing) |
| `backend.py` | `CameraBackend` Protocol; `OpenCvCamera` (cv2.VideoCapture, MSMF/DSHOW, exposure controls, blocking-probe for the stamp point); `SyntheticCamera` (tests) |
| `timestamps.py` | `DriverTimestampMapper` (driver clock -> `t_mono`: identity when the clock base is shared, least-squares + min-lag otherwise) and `GrabReturnStamper` |
| `frame_queue.py` | `BoundedFrameQueue`: drop-oldest with exact drop accounting |
| `stats.py` | `interval_stats` (delivered FPS, jitter, gaps, stalls, histogram), `StallDetector`, `CaptureStats` |
| `source.py` | `LiveFrameSource` (`FrameSource`): capture thread -> t_capture policy -> duplicate refusal -> queue -> `FrameSample` |
| `device.py` | enumeration / mode probing through the backend (Task 02.1); values are *advertised*, never measured |
| `exposure.py` | `ExposureGuard` / `ExposureWatch` (`camera_profile.exposure.guard`, ADR-0048): measured unique-FPS guard that re-applies a MANUAL exposure or replaces a too-slow AUTO with a fallback; read-back is unreliable on HW-01 |
| `native.py` | `NativeCapture` (`camera_profile.native_capture`, ADR-0047): native-mode request, verification and fallback; `tracking_frame` = crop + area downscale to `resolution_px` (upscaling and aspect changes refused) |

Policies (docs/camera-profile-hw01-integrated-webcam.md, ADR-0013): delivered FPS is measured from `t_capture` of unique frames only; byte-identical consecutive frames are refused and counted (`CaptureStats.duplicates`); `frame_id` is assigned at delivery so neither drops nor duplicates consume ids; `t_capture <= t_frame_available` and monotone `t_capture` are enforced and any clamp is counted. No temporal interpolation and no upsampling anywhere; the only spatial resampling is the opt-in native-capture area downscale (ADR-0047).

**Phase 05:** `replay.ReplayFrameSource` — the basic replay `FrameSource` (architecture.md §12): reads a recorded session or a Phase 02/03 dev capture (`frames.jsonl` + PNG frames), reproduces `t_capture` / `t_frame_available` / `dropped_since_last` exactly and sets `timestamp_source = REPLAY` (`tests/capture/test_replay_source.py`). Promoted from the Phase 03 script helper `scripts/_devcapture.py`, which stays for the Phase 03 scripts.

**ADR-0047 (2026-10-16):** optional native capture. `LiveFrameSource` opens `native_capture.request_px`, verifies the delivered frames (size on every probe frame, unique FPS >= `min_fps` under MANUAL exposure) and otherwise reopens `resolution_px` (`capture_report()["mode"] == "STANDARD_FALLBACK"`, with the reason). Delivered native frames are cut to `crop_px` and area-downscaled to `resolution_px` before `t_frame_available`; `FrameSample`s, ROI and every downstream coordinate keep the tracking size. `preview_image(sample)` returns the native-resolution window for display only. Optional `camera_profile.controls` (GAIN, BRIGHTNESS, ...) are set after the stream starts, verified by read-back (`OpenCvCamera.controls_report`) and restored on close. Diagnostics: `scripts/camera_modes.py`; evidence: `docs/perf/camera-quality-native-720p.md`.
