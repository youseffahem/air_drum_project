# ADR-0013 — Capture backend, timestamp policy, duplicate refusal, config schema 1.1

| Field | Value |
|---|---|
| Status | **Accepted** (Phase 02, Tasks 02.1–02.4, 02.8, 02.10) — the backend choice is a *candidate* pending Phase 03's tracking-quality benchmark (see Consequences) |
| Date | 2026-09-21 |
| Deciders | Project owner (via Phase 02 gate), recorded by Phase 02 |
| Related | ADR-0004 (clock), ADR-0009 (T1 threading), ADR-0010 (config), ADR-0012 (layout); `docs/camera-profile-hw01-integrated-webcam.md`; `docs/architecture/architecture.md` §5.2; `configs/schema/config.schema.json` (1.1); REQ-023 (I-5), REQ-101, REQ-102 |

## Context

Phase 02 measured the integrated webcam of HW-01 through OpenCV 5.0 on Windows 11 (camera profile §3–§6). Four findings shape how `FrameSample`s must be produced:

1. **Two backends, two behaviours.** `MSMF` exposes a per-frame driver timestamp (`CAP_PROP_POS_MSEC`) that lies on the same `QueryPerformanceCounter` base as `time.perf_counter` (fitted slope − 1 = 10⁻⁵…10⁻⁶ over 60 s), but hands frames over in bursts (hand-over lag ≈ 40 ms median, up to ~65 ms) and, whenever the sensor runs below its nominal rate, pads the stream with **byte-identical** frames that carry fresh, evenly spaced driver timestamps. `DSHOW` exposes no driver timestamp, blocks inside `retrieve()` (not `grab()`), delivers every sensor frame exactly once with a hand-over lag of ≈ 0.2 ms, but negotiates only uncompressed YUY2 on this device, so 1280×720 is delivered at ~10 FPS.
2. **The requested 60 FPS is not delivered** in any mode on either backend (delivered ≈ 29–30 FPS, identical to the 30 FPS request).
3. **Auto-exposure in dim light throttles the sensor to ~10 unique FPS**; manual exposure (log2 scale, e.g. −6 = 15.6 ms) restores ~30 FPS at the cost of a dark image. MSMF applies exposure settings only after the stream has started.
4. Two reproducibility fields were missing from config schema 1.0: the requested pixel format (it decides whether 720p is delivered at 10 or 30 FPS) and the measured grab-return bias that architecture.md §5.2 refers to.

## Decision

1. **Clock.** `clock_id = perf_counter` (ADR-0004 candidate) is confirmed for HW-01: `QueryPerformanceCounter()`, resolution 1e-7 s, monotonic, not adjustable. No change to ADR-0004.
2. **Timestamp policy per backend** (implemented in `spacedrums.capture`, labelled per frame in `FrameSample.timestamp_source`):
   - `DSHOW` → `GRAB_RETURN`, stamped **after the blocking call** (the backend probes at open time whether `grab()` or `retrieve()` waits and records `stamp_after`); `t_capture = t_grab_return − grab_return_bias_s`, bias 0 until measured with a method whose display term is bounded (protocol `capture-latency-flash-method.md` §2).
   - `MSMF` → `DRIVER_MAPPED` with the **identity map** when the driver clock is detected to share the `t_mono` base (all raw lags within `[−10 ms, 500 ms]` over the warm-up window), otherwise least-squares slope + minimum-lag offset once the window spans ≥ 5 s; warm-up frames are labelled `GRAB_RETURN`. A non-monotone driver clock disables the mapping.
   - Invariants `t_capture ≤ t_frame_available` and monotone `t_capture` are enforced by clamping **and counted** (`CaptureStats.clamped_timestamps`); a healthy run has 0 (the only clamp seen is the one-frame policy switch at warm-up on MSMF).
3. **Duplicate refusal.** A frame byte-identical to the previously delivered one is not delivered and is counted (`CaptureStats.duplicates`). Rationale: a real sensor frame differs by noise; identical frames are pipeline padding, and counting them would present padded frames as native FPS (integrity I-5). `frame_id` is assigned at delivery, so neither duplicates nor queue drops consume ids. Dedupe can be disabled only for diagnostics (`--no-dedupe`), never in a session config (no config key exists on purpose).
4. **Delivered FPS** is `(N − 1) / (t_last − t_first)` over delivered unique frames' `t_capture`, per run, and enters a config only as `native_fps_measured {value_fps, run_id, method}`.
5. **Baseline backend candidate for Phase 03:** `DSHOW`, 640×480, requested 30 FPS, manual exposure per lighting — chosen for the ≈ 0.2 ms hand-over lag and the absence of padded frames. `MSMF` remains the only path to 1280×720 at ~30 FPS on this device (at ≈ 40 ms hand-over lag); if Phase 03 shows that 640×480 gives insufficient stick-tip resolution, the trade-off is re-decided there with tracking evidence (Task 03.11) and this ADR is amended.
6. **Config schema 1.0 → 1.1** (minor, additive, nullable; `meta.schema_version` accepts both): `camera_profile.pixel_format: FOURCC | null` and `camera_profile.grab_return_bias_s: {value_s, run_id, method} | null`. A 1.0 document reads as both null. Loader cross-field checks added: exposure mode/value consistency, ROI inside resolution, bias only with a measured mode.
7. **Layout amendments** (`repo-layout.md`): `configs/camera/` (camera fragments), `docs/protocols/`, `docs/figures/phase-02/`, `docs/camera-profile-<device>.md`, `scripts/_runlog.py`, `.importlinter` at the root, `tests/{timing,config,capture,ui,architecture,scripts}/`; `pyproject.toml` gains the `[project]` table and setuptools backend; `requirements.in/.lock` gain `import-linter`. Config files may be **fragments** (`meta` + owned blocks) merged onto a base by the loader (ADR-0010 left assembly to the loader).
8. **Experiment logs of hardware runs** live in `experiments/<run_id>/` per `repo-layout.md` §3.3 (git-ignored); the phase document's `experiments/phase-02/*.json` wording is superseded by that rule. Whether `run.json`/`config.resolved.yaml` should be un-ignored for reviewability is an **Open Question** for the owner (gate record §7).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Use MSMF driver timestamps as the reference and ignore the hand-over lag | The sound cannot be scheduled before the frame arrives; a 40 ms hand-over lag is a direct `L_sys` term. The timestamp would be honest but the latency is real. |
| Deliver padded duplicates and let tracking cope | Presents a padded stream as native FPS; the tracker would see zero motion then a jump (velocity artefacts). |
| Least-squares offset (mean lag) for driver mapping | Pushes `t_capture` toward the hand-over time; grab returns can only be later than capture, so the offset must come from the earliest lag or the identity. |
| Put `dedupe` in the config schema | Would allow a session to present padded frames as delivered; the diagnostic flag on the script suffices. |
| Encode pixel format in `device.backend` string | Hides a first-class reproducibility parameter. |
| `pyav`/`imageio-ffmpeg` capture path (README §11 alternative) | Not needed: OpenCV's backends deliver what the device can; revisit only if an external camera (Q22) needs it. |

## Consequences

- `FrameSample.timestamp_source` is exact per frame; consumers must not assume a single source per session.
- Every FPS figure in the project reports `duplicates` and `dropped` beside it (camera profile §3 table format).
- Phase 03 receives a 640×480 baseline with a documented 720p alternative and decides with tracking evidence.
- Phase 16's 60 FPS attempt requires an external camera (HW-02, not inventoried); on HW-01 it is closed as *measured, not delivered*.
- The Task 02.8 flash method yields an upper bound only; `grab_return_bias_s` stays null (bias 0) until a method with a bounded display term exists (Open Question: LED/photodiode).
