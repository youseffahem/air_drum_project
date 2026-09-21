# Phase 02 — Camera Capture & Computer Vision Prototype

## Status

IMPLEMENTED + MEASURED (development hardware HW-01, 2026-09-21) — gate reviewed 2026-09-21: **PASS-WITH-CONDITIONS** (C-1 FOV, C-4/O-1 repository artefacts, C-5 frozen capture config at the Phase 03 gate), effective on the owner's signature. Gate record: [`../docs/gates/phase-02-gate.md`](../docs/gates/phase-02-gate.md). Capture module, L0 packages (contracts/timing/config), guide overlay and measurement scripts exist with 191 passing tests; native FPS, jitter, duplicates, timestamp mapping, exposure controls and a capture-latency upper bound are MEASURED ([`../docs/camera-profile-hw01-integrated-webcam.md`](../docs/camera-profile-hw01-integrated-webcam.md)); the 60 FPS attempt is measured as **not delivered** on HW-01. Owner-executed on 2026-09-21 under L2: distance-benchmark visibility table (0.8/1.0/1.5/2.2 m, all inside the ROI), stick-swing blur check (−5 selected), latency re-run with the screen at normal brightness. **PENDING:** FOV / visible playing area (owner deferred), tracking-quality vs. distance and the final working distance/ROI (Phase 03 Task 03.11 with the real tracker), grab-return bias (instrument), processing FPS (Phase 03/16). Nothing is VALIDATED.

## Purpose

Implement timestamped webcam capture with a fixed playing ROI and an on-screen "stand here" guide, measure the camera's **native** frame rate and timing behaviour, document a camera profile (resolution, FPS, exposure, field of view, placement, user distance, visible playing area), and establish the method for measuring camera capture latency. This phase is the first implementation phase and produces the `capture` module of Phase 01.

## Why This Phase Exists

Every downstream latency and timing claim starts at `t_capture`. If frame timestamps are wrong, jittery, or interpolated, the sub-frame impact estimation (Phase 04), the lead-time metric (Phase 09), and the end-to-end measurements (Phase 18) are all invalid. The project also commits to reporting *native* FPS only (Q23), which is impossible without measuring it. Finally, the playing area, camera distance, and field of view constrain what the stick tracker (Phase 03) can see; those must be benchmarked before tracking is tuned.

## Relationship to Research Contribution

The research contribution is measured in milliseconds of lead time. Frame period at 30 FPS is ~33 ms; a capture-timestamp error of even a fraction of a frame is comparable to the quantities being measured. This phase establishes the measurement foundation and the camera profile that will be reported with every result (Q22–Q26).

## Inputs

- Phase 01 contracts: `FrameSample`, clock model, config schema (`camera_profile`, `roi`).
- Phase 00 hardware inventory (advertised camera modes).
- Laptop webcam (initial); tripod/fixed mount if available.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-019, REQ-022, REQ-023, REQ-024, REQ-025, REQ-026, REQ-027, REQ-101, REQ-102; contributes to REQ-004.

## Expected Outputs

- `capture` module (implements `FrameSample` production, ROI crop, bounded queue with drop counting).
- Camera Profile document with **measured** native FPS, frame-interval statistics, drop rate, resolution, exposure setting, approximate field of view, placement, user distance, visible playing area.
- Playing-area guide overlay (fixed ROI rectangle + instruction text).
- Capture-latency measurement method and its first measured value on the development hardware.
- Camera-distance benchmark protocol (executed jointly with Phase 03 once tracking exists; protocol defined here).
- Lighting-variation checklist for later phases.

## Dependencies

- Phase 01 Exit Gate.

## System Components

- `src/spacedrums/capture/` — device open, mode selection, frame pull loop, timestamping, ROI crop, queue.
- `src/spacedrums/ui/guide.py` — playing-area guide overlay (prototype quality).
- `scripts/measure_fps.py`, `scripts/measure_capture_latency.py` — measurement scripts producing JSON per the experiment-log schema.
- `configs/camera/<device>.candidate.yaml` — camera profile config.

## Architecture

```
Camera device ──► capture thread: grab → t_capture (driver ts mapped to t_mono, or t_mono at grab if unavailable)
                                   → t_frame_available → ROI crop → bounded queue (drop-oldest, count)
                                   → FrameSample
```

- **Timestamp source policy:** prefer driver-provided timestamps if the backend exposes them and they are monotone; otherwise stamp at grab return and record `timestamp_source = "grab_return"` in the profile with the estimated bias/uncertainty from the capture-latency measurement.
- **FPS policy:** request a mode (e.g. 30 FPS baseline; 60 FPS attempt) and then *measure* delivered FPS from `t_capture` intervals. The delivered value, never the requested one, is written into the camera profile. No frame interpolation anywhere in the capture path.
- **ROI policy:** ROI is a fixed pixel rectangle in the config; the guide overlay draws the full-frame rectangle and the instruction "Stand so both hands and sticks stay inside the box". ROI size and placement are candidate values until the distance benchmark (Task 02.7).

## Detailed Tasks

### Task 02.1 — Device Enumeration and Mode Selection
- **What:** Enumerate available cameras and their advertised modes (resolution × FPS × pixel format) via the capture backend; select by config. Log the backend name and the negotiated mode.
- **Why:** Q22–23; reproducibility requires knowing exactly which mode was used.
- **Depends on:** Phase 01 config schema.
- **Evidence:** Log output of enumerated modes for the development webcam stored in the hardware inventory (labelled *inspected*).

### Task 02.2 — Monotonic Timestamping and Driver-Timestamp Mapping
- **What:** Implement `t_capture` and `t_frame_available`. If the backend exposes a driver timestamp, estimate its offset to `t_mono` by linear fit over a warm-up window and record the residual. If not, use grab-return time and document it.
- **Why:** README §5.1.
- **Depends on:** 02.1.
- **Evidence:** Timestamp-source field in the camera profile; residual statistics (MEASURED) or "not available" recorded.

### Task 02.3 — Bounded Queue and Drop Accounting
- **What:** Capture thread → bounded queue (size tunable, candidate 1–2 frames) with drop-oldest; each `FrameSample` carries `dropped_since_last`. Expose counters for delivered, dropped, and stalled (no frame for > 2× expected interval, tunable).
- **Why:** Latency must not accumulate when processing is slower than capture; drops must be visible in every experiment log.
- **Depends on:** 02.2.
- **Evidence:** Unit test with a slow consumer shows drop counts increase and queue latency stays bounded.

### Task 02.4 — Native FPS and Jitter Measurement
- **What:** Script that runs the capture for a fixed duration (tunable; candidate ≥ 60 s) per requested mode and reports: delivered FPS (count/duration), frame-interval mean/std/p1/p99, histogram, drop/stall counts, and CPU usage of the capture thread. Run for the 30 FPS baseline and the 60 FPS attempt at each candidate resolution.
- **Why:** Q23 — native FPS only; 60 FPS target must be verified, not assumed.
- **Depends on:** 02.3.
- **Evidence:** JSON results per mode following the experiment-log schema; table in the camera profile with MEASURED labels; explicit statement whether true 60 FPS is delivered on this hardware (or PENDING if not attempted).

### Task 02.5 — Exposure / Motion-Blur Setting Procedure
- **What:** Procedure to set exposure (manual if the backend allows; otherwise document auto-exposure behaviour) to limit motion blur of a moving stick under normal indoor lighting. Define a qualitative blur check (record a stick swing, inspect tip sharpness at the frame with maximum speed) and a quantitative proxy (edge-gradient magnitude along the stick at peak speed — candidate metric). Record the chosen setting per lighting condition.
- **Why:** Stick-tip localisation (Phase 03) degrades with blur; short exposure is a trade-off against noise in dim light (Q27).
- **Depends on:** 02.4.
- **Evidence:** Exposure settings and the blur-check results per lighting condition recorded as MEASURED; limitations noted where the webcam offers no manual control.

### Task 02.6 — Fixed Playing ROI and "Stand Here" Guide
- **What:** Config-driven ROI rectangle; overlay drawing the ROI, a horizontal reference band where hands are expected, and an instruction string. Prototype UI via OpenCV window. ROI-normalized coordinate helper (pixel ↔ normalized) implemented here and reused by all later modules.
- **Why:** Q4, Q19, Q26 — system defines where the user stands; no manual positioning.
- **Depends on:** 02.1.
- **Evidence:** Screenshot of the guide; unit tests for the coordinate helper (round-trip, corners, y-down orientation).

### Task 02.7 — Camera-Distance and Field-of-View Benchmark Protocol
- **What:** Define the protocol: place the camera at a fixed height (tripod or documented improvised mount); mark candidate user distances (e.g. a set of distances spanning "both hands + full stick swing visible" to "hands occupy a small fraction of the frame" — candidate values chosen per room and recorded, not fixed here); at each distance record (a) whether both hands and full stick paths across all MVP zone positions stay inside the ROI, (b) the apparent stick length in pixels, (c) the apparent hand size in pixels. Execution of the tracking-quality part of this benchmark is deferred to Phase 03 (Task 03.11) because it needs a tracker; this phase executes the visibility/geometry part.
- **Why:** Q25 — distance must be benchmarked.
- **Depends on:** 02.6.
- **Evidence:** Protocol document; visibility/pixel-size table per distance (MEASURED); the tracking-quality columns marked PENDING (Phase 03).

### Task 02.8 — Capture-Latency Measurement Method
- **What:** Define and execute a method for `t_frame_available − t_capture(true)`. Candidate method: display a high-contrast flash (or drive an LED) at a known `t_mono` and detect the first frame in which it appears; the difference between detection `t_frame_available` and the flash time, minus half a frame period on average, estimates capture latency (report the raw distribution, not only the corrected mean). Repeat ≥ 30 times (candidate); report median and p90.
- **Why:** README §5.3 — capture latency is one term of `L_sys` and cannot be obtained from software stamps alone.
- **Depends on:** 02.2.
- **Evidence:** Script; JSON results; MEASURED entry in the camera profile with method description and its known limitations (display latency of the flash itself must be accounted for or stated as a bound).

### Task 02.9 — Lighting-Variation Checklist
- **What:** Define the lighting conditions to be used in Phases 03, 06, 17: e.g. daylight from window, overhead room light, dim/evening, mixed, backlit (candidate list — final set decided with the recording location). For each: how to reproduce it and how to record it in session metadata.
- **Why:** Q27 — no laboratory-lighting assumption.
- **Depends on:** None.
- **Evidence:** Checklist document; referenced by Phase 06 metadata schema.

### Task 02.10 — Camera Profile Document
- **What:** Consolidate: device, backend, negotiated mode, measured native FPS/jitter/drops per mode, timestamp source and residual, exposure settings, approximate FOV (from a known-size object at a known distance, or from the manufacturer's spec labelled *advertised*), placement (height, tilt), user distance candidates, visible playing area in metres (approximate, method stated), processing FPS placeholder (PENDING until Phase 03/16).
- **Why:** Q22–Q26 require this documentation; every later result cites it.
- **Depends on:** 02.1–02.9.
- **Evidence:** `docs/camera-profile-<device>.md` with every value labelled MEASURED / advertised / PENDING.

## Data Requirements

- Short developer-only test captures (a few minutes) for FPS/latency/blur measurement. These are **not** dataset recordings, must be stored under `data/dev-captures/`, and must never be counted toward the participant dataset.

## Algorithms / Technical Approach

- Frame-interval statistics: from consecutive `t_capture` differences; drops flagged when interval > 1.5× nominal (tunable).
- Driver-timestamp mapping: least-squares offset (and optionally drift) between driver time and `t_mono` over a warm-up window; residual std reported.
- Capture latency: flash-detection method (Task 02.8); detection by thresholding mean luminance in a fixed patch.
- ROI crop: pure array slicing, no resampling, to avoid adding latency or blur.

## Interfaces / Contracts

- Produces `FrameSample` per Phase 01.
- Exposes `CaptureStats { delivered, dropped, stalled, fps_measured, interval_p50, interval_p99 }` to the debug overlay (Phase 15) and to session metadata (Phase 06).
- Coordinate helper: `px_to_norm(x_px, y_px, roi) -> (x, y)` and inverse; y-down.

## Tests

- **Unit:** coordinate helper round-trip and orientation; queue drop-oldest behaviour; interval statistics on synthetic timestamp arrays; stall detection.
- **Integration:** capture runs for N seconds without exceptions; `FrameSample` fields populated and schema-valid; `dropped_since_last` sums to total drops.
- **Hardware measurement scripts** produce schema-valid JSON.

## Measurements

| Quantity | Method | Label |
|----------|--------|-------|
| Native delivered FPS per mode | Task 02.4 | MEASURED after execution |
| Frame-interval jitter (std, p1, p99) | Task 02.4 | MEASURED |
| Drop/stall rate | Task 02.4 | MEASURED |
| Timestamp mapping residual | Task 02.2 | MEASURED or N/A |
| Capture latency (median, p90) | Task 02.8 | MEASURED |
| Exposure setting per lighting condition + blur proxy | Task 02.5 | MEASURED |
| Apparent stick length / hand size vs. distance | Task 02.7 | MEASURED |
| Approximate FOV and visible playing area | Task 02.10 | MEASURED (method stated) or advertised |

No values are written into this document. They are written into the camera profile after measurement.

## Experimental Design

- **FPS benchmark:** factors = requested mode (30 vs. 60 FPS) × resolution candidates; response = delivered FPS, jitter, drops; ≥ 60 s per cell (candidate); repeated at least twice to check stability.
- **Capture latency:** ≥ 30 flash trials (candidate) per mode; report distribution.
- **Distance benchmark (visibility part):** candidate distances × one camera height; response = visibility of hands/stick paths and pixel sizes.

## Acceptance Criteria

1. Capture module produces schema-valid `FrameSample`s with monotone `t_capture` and drop accounting.
2. Native FPS measured and documented for the 30 FPS baseline; the 60 FPS attempt is either measured or explicitly PENDING with the reason.
3. Capture-latency method executed at least once; results and limitations documented.
4. ROI guide overlay works; coordinate helper tests pass.
5. Camera profile document complete with labels on every value.
6. Distance protocol written; visibility table filled.

## Definition of Done

- Implementation + unit/integration tests passing.
- All measurements in the table above executed on the development hardware (or marked PENDING with reason) and stored as experiment-log JSON.
- Camera profile reviewed; gate record PASS; integrity checklist applied (no requested FPS presented as delivered FPS).

## Risks

- Laptop webcam may not deliver a stable 30 FPS at usable resolution under indoor lighting (auto-exposure lowers FPS in dim light) → documented as a measured limitation; external camera upgrade path recorded (Q22).
- Backend exposes no driver timestamps → grab-return stamping with measured bias.
- Windows camera backends differ in latency (Pending Benchmark: compare available backends).

## Failure Modes

- Auto-exposure changes mid-session → frame-rate and blur change; mitigation: lock exposure where possible; log exposure if the backend reports it.
- Queue policy hides a systematically slow consumer → drop counters must be surfaced in every session log.

## Fallback Strategy

- If 60 FPS is not achievable, the project proceeds at the 30 FPS baseline; 60 FPS remains a Target and a Phase 16 attempt with an external camera.
- If capture latency cannot be measured with the flash method, report it as PENDING and bound it using the manufacturer/backend documentation, clearly labelled.

## Artifacts Produced

- `src/spacedrums/capture/`, `src/spacedrums/ui/guide.py`
- `scripts/measure_fps.py`, `scripts/measure_capture_latency.py`
- `docs/camera-profile-<device>.md`
- `docs/protocols/camera-distance-benchmark.md`
- `docs/protocols/lighting-checklist.md`
- `experiments/phase-02/*.json`
- `docs/gates/phase-02-gate.md`

## Exit Gate

Reviewer verifies the camera profile is fully labelled and the FPS/latency measurements exist. PASS → Phase 03 may start.

Gate record: [`../docs/gates/phase-02-gate.md`](../docs/gates/phase-02-gate.md) — submitted and reviewed 2026-09-21, verdict **PASS-WITH-CONDITIONS** (effective on owner signature; conditions C-1 FOV, C-4/O-1, C-5).

## What Must NOT Be Done Yet

- No hand or stick tracking.
- No frame interpolation, optical-flow upsampling, or any "60 FPS" derived from 30 FPS.
- No participant recordings.
- No claims about tracking quality vs. distance (those are Phase 03).

## Open Questions

- Which Windows capture backend gives the lowest and most stable latency on the development laptop? (Pending Benchmark)
- Is manual exposure available on the laptop webcam? (inspect)
- Will an external camera be acquired, and when? (affects Phase 16 60 FPS attempt)

## Decisions That Must Be Experimentally Validated

- Resolution/FPS mode for the project baseline (Task 02.4).
- ROI size and placement (Task 02.7 + Phase 03 Task 03.11).
- Exposure setting per lighting condition (Task 02.5).
- Queue size and stall threshold (Task 02.3, revisited in Phase 16).
