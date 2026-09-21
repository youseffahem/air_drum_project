# Camera Profile — HW-01 Integrated Webcam (`hw01-integrated-webcam-v0`)

**Phase:** 02 — Task 02.10 · **Status:** MEASURED for the quantities marked MEASURED below (development hardware, 2026-09-21, developer lighting condition L0); PENDING for the quantities that need a person at the camera (§7, §8) or an external instrument (§6 bias). Nothing here is VALIDATED (no independent repeat session yet; reproducibility-policy §6 "live captures").
**Config fragment:** [`../configs/camera/hw01-integrated-webcam.candidate.yaml`](../configs/camera/hw01-integrated-webcam.candidate.yaml) (`profile_id: hw01-integrated-webcam-v0`, status *candidate*).
**Decisions:** [ADR-0013](decisions/ADR-0013-capture-backend-timestamp-policy.md). **Hardware:** [`hardware-inventory.md`](hardware-inventory.md) HW-01. **Protocols:** [`protocols/`](protocols/).
**Runs:** every number below names its `run_id` (`experiments/<run_id>/run.json`, git-ignored on HW-01; the gate record lists them). The Phase 02 development runs carry `git_sha 568eca92…` with a **dirty** tree (the Phase 02 code that measures is the code being added; see gate record §6); the baseline-mode FPS cells were **re-run on the committed tree** `13f0f3394fc699bb2e12eb10ae0f1da6c0ce2f61` with `git_dirty: false` (§3, runs `…-clean`). Python 3.11.9, OpenCV 5.0.0, `cv2` threads 8, clock `perf_counter` = `QueryPerformanceCounter()` (1e-7 s), laptop plugged in, Windows power scheme *Balanced*.

Labels: **MEASURED** (method + run id), **inspected** (read from the OS/driver), **advertised** (claimed by the driver, not verified), **candidate** (a choice, not a result), **PENDING** (not yet measured, reason given).

---

## 1. Device and backend

| Field | Value | Label |
|---|---|---|
| Device | "Integrated Webcam", USB `VID_0C45:PID_6717` (Sonix/Microdia controller), Dell Precision 3520 bezel camera | inspected (PnP) |
| Driver | Microsoft inbox UVC driver 10.0.22621.3672 | inspected (PnP) |
| Capture library | OpenCV 5.0.0.93 (`opencv-python`), Windows backends available: MSMF, DSHOW (also GSTREAMER, FFMPEG, UEYE, OBSENSOR listed, not applicable) | inspected (`20260921-0300-p02-enumerate-cameras`) |
| Device index | 0 on both backends; indices 1–3 open nothing | inspected (same run) |
| **Backend chosen for the Phase 03 baseline** | **DSHOW** (`timestamp_source: GRAB_RETURN`, stamp after the blocking `retrieve()`) — see §4 for the comparison; MSMF stays available for 1280×720 | candidate (ADR-0013 §5) |
| Clock (`clock_id`) | `perf_counter` → `QueryPerformanceCounter()`, monotonic, not adjustable, resolution 1e-7 s | inspected (`timing.clock_info()`) |

## 2. Modes negotiated (advertised by the driver — not delivered rates)

Run `20260921-0300-p02-enumerate-cameras` (Task 02.1), manual exposure −7 so the low-light frame-rate cap does not confound the short probe. "fps_prop" is the driver's `CAP_PROP_FPS` claim.

| Backend | Requested | Negotiated size | Format | fps_prop (advertised) | Short unique-frame probe (1.5 s; *not* a measurement) |
|---|---|---|---|---|---|
| MSMF | 640×480 @30 / @60 | 640×480 | MF subtype 22 (decoded internally) | 30 (also when 60 requested) | ~27.6 |
| MSMF | 848×480 @30 | 848×480 | idem | 30 | ~29.7 |
| MSMF | 960×540 @30 | 960×540 | idem | 30 | ~27.5 |
| MSMF | 1280×720 @30 / @60 | 1280×720 | idem | 30 | ~28.7–29.8 |
| MSMF | 1920×1080 @30 / @60 | **1280×720** (fallback) | idem | 30 | ~29–30 |
| DSHOW | 640×480 @30 / @60 | 640×480 | YUY2 | 30 / 60 (echoes the request) | ~30 |
| DSHOW | 848×480 @30, 960×540 @30 | 848×480, 960×540 | **MJPG** | 30 | ~30 |
| DSHOW | 1280×720 @30 / @60 | 1280×720 | YUY2 (a MJPG request is ignored) | 30 / 60 | **~10** |
| DSHOW | 1920×1080 @30 / @60 | **1280×720** (fallback) | unreported compressed format | 30 / 60 | ~30 |

Reading: the sensor tops out at 1280×720; on DSHOW the only 720p path that reaches ~30 FPS is the 1080p-request fallback with an unnamed compressed format (not a clean, reproducible request); on MSMF 720p decodes internally at ~30 FPS. 640×480 is delivered at ~30 FPS by both backends in uncompressed YUY2.

## 3. Native delivered FPS, jitter, drops, duplicates — MEASURED (Task 02.4)

Method: `scripts/measure_fps.py`; each cell 60 s (auto-exposure cells 30 s), repeated twice; delivered FPS = (N−1)/(t_last−t_first) over **delivered unique frames'** `t_capture`; gaps = intervals > 1.5× nominal, stalls > 2× nominal (nominal = requested rate); duplicates = byte-identical consecutive frames refused by capture; queue `max_frames 2`, drop-oldest. Exposure MANUAL −6 (15.6 ms) unless stated. Lighting L0 (§9). Runs: `20260921-0240-p02-fps-msmf-manual`, `20260921-0249-p02-fps-dshow-manual`, `20260921-0258-p02-fps-msmf-auto`, `20260921-0259-p02-fps-dshow-auto`.

| Backend | Requested | Repeat | **Delivered FPS** | Unique frames / 60 s | Interval mean / std / p1 / p50 / p99 / max (ms) | Gaps / stalls | Queue drops | **Duplicates refused** | Hand-over lag p50 / p95 (ms) | Capture-thread CPU |
|---|---|---|---|---|---|---|---|---|---|---|
| MSMF | 640×480 @30 | r1 | **29.08** | 1735 | 34.39 / 6.15 / 31.56 / 33.33 / 66.67 / 74.8 | 58 / 39 | 0 | 56 | 42.5 / 58.3 | 0.4 % |
| MSMF | 640×480 @30 | r2 | **29.08** | 1734 | 34.39 / 6.01 / 31.66 / 33.33 / 66.67 / 66.7 | 56 / 40 | 0 | 56 | 43.3 / 59.6 | 0.4 % |
| MSMF | 640×480 @60 | r1 | **29.08** | 1734 | 34.39 / 6.00 / 31.67 / 33.33 / 66.67 / 66.7 | 1732 / 602 ¹ | 0 | 56 | 43.0 / 60.2 | 0.3 % |
| MSMF | 640×480 @60 | r2 | **29.08** | 1734 | 34.39 / 6.05 / 31.68 / 33.33 / 66.67 / 66.7 | 1731 / 601 ¹ | 0 | 56 | 43.5 / 60.2 | 0.9 % |
| MSMF | 1280×720 @30 | r1 | **29.06** | 1733 | 34.41 / 6.05 / 31.69 / 33.33 / 66.67 / 66.7 | 57 / 41 | 0 | 57 | 50.0 / 66.8 | 2.0 % |
| MSMF | 1280×720 @30 | r2 | **29.10** | 1736 | 34.36 / 5.94 / 31.47 / 33.33 / 66.67 / 66.7 | 55 / 33 | 0 | 55 | 49.7 / 67.5 | 3.0 % |
| MSMF | 1280×720 @60 | r1 | **29.08** | 1734 | 34.39 / 6.04 / 31.66 / 33.33 / 66.67 / 80.1 | 1732 / 598 ¹ | 0 | 56 | 50.6 / 68.1 | 2.4 % |
| MSMF | 1280×720 @60 | r2 | **29.06** | 1734 | 34.41 / 6.06 / 31.61 / 33.33 / 66.67 / 68.2 | 1732 / 603 ¹ | 0 | 57 | 51.0 / 68.6 | 2.9 % |
| DSHOW | 640×480 @30 | r1 | **30.15** | 1802 | 33.16 / 4.59 / 28.29 / 32.01 / 48.57 / 59.6 | 8 / 0 | 0 | 0 | 0.2 / 0.4 | 0.6 % |
| DSHOW | 640×480 @30 | r2 | **30.18** | 1802 | 33.14 / 4.49 / 28.79 / 32.02 / 48.98 / 65.5 | 13 / 0 | 0 | 0 | 0.2 / 0.5 | 0.2 % |
| DSHOW | 640×480 @60 | r1 | **30.18** | 1802 | 33.14 / 4.47 / 29.29 / 32.02 / 49.24 / 62.0 | 1794 / 223 ¹ | 0 | 0 | 0.2 / 0.5 | 0.3 % |
| DSHOW | 640×480 @60 | r2 | **30.16** | 1800 | 33.16 / 4.57 / 28.22 / 32.02 / 49.25 / 77.5 | 1795 / 304 ¹ | 0 | 0 | 0.4 / 0.6 | 0.3 % |
| DSHOW | 1280×720 @30 | r1 | **10.06** | 594 | 99.42 / 7.70 / 85.90 / 96.39 / 119.25 / 121.3 | 593 / 593 | 0 | 0 | 0.5 / 1.1 | 0.9 % |
| DSHOW | 1280×720 @30 | r2 | **10.06** | 594 | 99.39 / 11.30 / 86.36 / 96.35 / 121.56 / 257.5 | 591 / 591 | 0 | 0 | 0.8 / 1.2 | 0.4 % |
| DSHOW | 1280×720 @60 | r1 | **10.06** | 594 | 99.40 / 7.60 / 85.58 / 96.47 / 117.78 / 121.9 | 593 / 593 | 0 | 0 | 0.6 / 1.1 | 0.5 % |
| DSHOW | 1280×720 @60 | r2 | **10.06** | 594 | 99.41 / 7.84 / 84.95 / 96.53 / 119.73 / 122.2 | 593 / 593 | 0 | 0 | 0.8 / 1.2 | 0.3 % |
| MSMF | 640×480 @30, **AUTO** exposure (30 s) | r1 | **10.09** | 298 | 99.10 / 14.23 / 66.67 / 100.00 / 133.33 / 133.3 | 296 / 290 | 0 | **591** | 105.1 / 130.0 | 1.0 % |
| DSHOW | 640×480 @30, **AUTO** exposure (30 s) | r1 | **10.05** | 293 | 99.46 / 6.66 / 92.74 / 96.23 / 113.68 / 115.4 | 292 / 292 | 0 | 0 | 0.4 / 0.5 | 0.3 % |

¹ Against the *requested* 60 FPS nominal (16.7 ms), every ~33 ms interval counts as a gap and every ~66 ms one as a stall: this is the measured evidence that **the 60 FPS request is not delivered** (identical delivery to the 30 FPS request in every statistic).

**Clean-tree confirmation of the baseline cells (gate condition C-3, 2026-09-21 09:31–09:36, owner-instructed).** Same script, same arguments and therefore identical `config_hash` values as the corresponding development runs (`7538c06c…` DSHOW, `8cceef09…` MSMF); `git_sha 13f0f3394fc699bb2e12eb10ae0f1da6c0ce2f61`, **`git_dirty: false`**; 640×480 @30, MANUAL −6, 60 s × 2. These are the runs to cite for the baseline delivered rate.

| Backend | Run | Repeat | **Delivered FPS** | Unique frames / 60 s | Interval std / p1 / p50 / p99 / max (ms) | Gaps / stalls | Queue drops | **Duplicates refused** | Hand-over lag p50 (ms) | Capture-thread CPU |
|---|---|---|---|---|---|---|---|---|---|---|
| DSHOW | `20260921-0931-p02-fps-dshow-manual-clean` | r1 | **30.16** | 1801 | 5.32 / 21.84 / 32.04 / 49.97 / 64.9 | 18 / 0 | 0 | 0 | 0.2 | 0.4 % |
| DSHOW | same | r2 | **30.18** | 1802 | 4.72 / 25.29 / 32.02 / 50.24 / 59.7 | 21 / 0 | 0 | 0 | 0.2 | 0.3 % |
| MSMF | `20260921-0933-p02-fps-msmf-manual-clean` | r1 | **29.03** | 1732 | 6.23 / 31.48 / 33.33 / 66.67 / 79.5 | 60 / 34 | 0 | 59 | 43.3 | 0.4 % |
| MSMF | same | r2 | **29.06** | 1734 | 6.11 / 31.17 / 33.33 / 66.67 / — | 57 / 37 | 0 | 57 | 43.7 | 0.3 % |

The clean runs agree with the development runs within 0.05 FPS in every cell and reproduce the qualitative pattern: DSHOW delivers every sensor frame once (0 duplicates, sub-millisecond hand-over); MSMF pads ~57–59 byte-identical frames per minute, which capture refuses and counts, and hands frames over ~43 ms late (identity clock map, slope − 1 = −3.1e-6 in r1). No timestamp clamp occurred in the clean cells (the single policy-switch clamp of the development MSMF cells did not recur). Lighting: L2 (room light on, 09:31), not L0 — as expected under manual exposure the FPS/duplicate figures are unchanged.

Findings (all MEASURED, this hardware, this lighting):

- **Baseline mode, 640×480 requested 30 FPS:** DSHOW delivers **30.15–30.18 FPS** with no duplicates and a 32.0 ms median interval (p99 ≈ 49 ms, i.e. ~1 in 100 intervals is a skipped sensor frame); MSMF delivers **29.06–29.10 FPS** on a strict 33.33 ms driver cadence with ~56 padded (byte-identical) frames per minute refused, so ~1 interval per second is 66.7 ms. Repeats agree within 0.05 FPS.
- **60 FPS target (Q23):** not delivered in any mode on either backend → on HW-01 the 60 FPS attempt is **measured as not achievable**; it remains a Target for an external camera (Phase 16, HW-02 not inventoried).
- **1280×720:** ~29.1 FPS on MSMF (with the padding above, 2–3 % capture-thread CPU), **10.06 FPS on DSHOW** (uncompressed YUY2 over USB).
- **Auto-exposure in this dim condition:** both backends drop to **~10 unique FPS** (sensor exposure ≈ 100 ms); MSMF additionally pads to a nominal 30 FPS with **591 duplicates in 30 s** (2 of every 3 frames) and its hand-over lag grows to ~105 ms. This is why the profile uses MANUAL exposure (§5).
- Queue drops: 0 in every cell (the consumer kept up with a trivial workload); drop counters are nevertheless reported everywhere. `clamped_timestamps`: 0 on DSHOW; **1 per MSMF cell** — the single frame at which the per-frame policy switches from `GRAB_RETURN` (mapper warm-up) to `DRIVER_MAPPED` and the driver stamp precedes the last grab stamp (documented, expected; it produces one 0 ms interval that is visible as `min_s = 0` in those cells and does not affect p1/p50/p99).
- Capture-thread CPU: ≤ 1 % at 640×480, 2–3 % at 720p on MSMF (decode), HW-01.

**Config field:** `native_fps_measured` stays `null` in the candidate fragment because candidate files may not carry cited measurements (ADR-0010 §3). When the fragment is frozen (`capture.hw01.v1.yaml`, `meta.status: frozen`) it is filled from the clean run: `{value_fps: 30.16, run_id: "20260921-0931-p02-fps-dshow-manual-clean", method: "measure_fps.py cell 640x480@30-MANUAL-r1, unique-frame (N-1)/span, git_dirty false"}`. **Freezing is deferred (2026-09-21):** a frozen file would also pin the ROI and backend (Phase 03 Task 03.11 decides them) and `exposure.value` (−6 in the fragment and in the clean runs, while the owner selected −5 for L2 in §5.1); freezing before those are settled would force an immediate v2. The clean runs remain citable from this profile in the meantime.

## 4. Timestamp source and mapping residual — MEASURED (Task 02.2)

| Backend | Policy | Evidence (runs of §3) | Label |
|---|---|---|---|
| MSMF | `DRIVER_MAPPED`, mapper mode **IDENTITY_SAME_CLOCK**: `CAP_PROP_POS_MSEC` lies on the `QueryPerformanceCounter` base. Least-squares slope − 1 over 60 s: **+2.5e-5, +3.3e-6, −1.0e-5, +1.3e-5** (640×480 cells), **+4.8e-5, +3.2e-5, +7.3e-6, +2.2e-5** (720p cells) → drift ≤ 3 ms per minute, within the fit noise; the identity map is used. Raw hand-over lag `t_grab − t_drv`: **p50 38–39 ms, p95 54–58 ms** at 640×480 (the *residual* of the identity assumption is the spread of that lag: LS residual std ≈ **10.7–11.1 ms**, p95 |resid| ≈ 17–19 ms — it is the burst delivery of MSMF, not clock noise). First 59 frames of every cell are labelled `GRAB_RETURN` (mapper warm-up). | MEASURED |
| DSHOW | `GRAB_RETURN`, no driver timestamp (`CAP_PROP_POS_MSEC = −1`); the blocking wait is in `retrieve()` (probe: grab median 0.01 ms, retrieve median 32 ms at 640×480 / 96 ms at 720p) so the stamp is taken after `retrieve()`; hand-over lag `t_frame_available − t_capture` **p50 0.2–0.8 ms, p95 0.4–1.2 ms**. `grab_return_bias_s` = **0 (null)** — the flash method (§6) yields only an upper bound including display latency, so no bias is written (protocol §2). | MEASURED (bias PENDING) |

Consequence for `L_sys` (README §5.3): on MSMF the `capture` slot (`t_frame_available − t_capture`) is ≈ 40 ms median even though `t_capture` is accurate; on DSHOW it is ≈ 0.2 ms but `t_capture` is the hand-over instant, i.e. true exposure time + the unknown bias bounded in §6.

## 5. Exposure controls and the low-light frame-rate cap — MEASURED (Task 02.5, machine part)

Run `20260921-0309-p02-exposure-inspect` (640×480, lighting L0, 45-frame probes per setting); procedure `protocols/exposure-blur-procedure.md`.

| Backend | Setting | Accepted (set / read-back) | Unique FPS (short probe) | Mean luminance (grey levels) | Temporal-noise std |
|---|---|---|---|---|---|
| DSHOW | AUTO | yes / read-back −1 (uninformative) | **10.0** | 13 | 2.3 |
| DSHOW | MANUAL −4 (62 ms) | yes / −4 | 16.0 | 12 | 2.1 |
| DSHOW | MANUAL −5 (31 ms) | yes / −5 | 29.7 | 11 | 1.7 |
| DSHOW | MANUAL −6 (15.6 ms) | yes / −6 | 29.4 | 12 | 2.8 |
| DSHOW | MANUAL −7 (7.8 ms) | yes / −7 | 30.1 | 5 | 2.7 |
| DSHOW | MANUAL −8 (3.9 ms) | yes / −8 | 30.1 | 5 | 2.7 |
| MSMF | AUTO | yes / read-back 0 | **10.5** | 11 | 2.2 |
| MSMF | MANUAL −4 … −8 | yes / read-back stuck at −6 (effect real: luminance and FPS change) | 15.8 / 30.1 / 28.8 / 27.7 / 30.1 | 10 / 10 / 11 / 5 / 5 | 1.8–2.8 |

Findings: manual exposure is available on both backends (MSMF only after the stream has started; read-back unreliable on MSMF); the sensor runs at ~30 FPS for exposures ≤ 31 ms (−5 and shorter), ~16 FPS at 62 ms (−4), ~10 FPS under auto-exposure in this dim condition. The luminance values here are very low because of the lighting condition (§9), not because of the settings alone.

### 5.1 Per-lighting exposure setting and blur check — MEASURED for L2 (Task 02.5, owner, 2026-09-21)

Inspect run `20260921-0904-p02-exposure-inspect` (DSHOW 640×480, lighting **L2**): AUTO → 15.0 FPS, luminance 120; −4 → 16.0 FPS, 115; **−5 → 30.1 FPS, 68, noise 5.81**; **−6 → 29.7 FPS, 36, noise 5.34**; **−7 → 29.6 FPS, 13, noise 4.70**; −8 → 29.6 FPS, 7. Swing recordings (`scripts/exposure_blur_check.py record/analyze`, 6 s, 4–6 strokes, `data/dev-captures/swing-L2-exp-<v>/`, git-ignored):

| Exposure | Capture id | Frames / delivered FPS / drops | Peak-motion frame | Blur proxy `gradient_mag_in_moving_region` (comparative only) | Qualitative grade (owner, peak-motion ROI crop) |
|---|---|---|---|---|---|
| MANUAL −5 (31 ms) | `swing-L2-exp-5` (09:06:23) | 171 / 29.93 / 1 | 120 | 46.6 | **sharp** |
| MANUAL −6 (15.6 ms) | `swing-L2-exp-6` (09:06:35) | 171 / 29.95 / 1 | 79 | 38.8 | **sharp** |
| MANUAL −7 (7.8 ms) | `swing-L2-exp-7` (09:06:49) | 172 / 30.13 / 0 | 89 | 32.9 | **streaked** |

**Selected for L2: MANUAL −5 — owner's decision (2026-09-21).** Note for the record: −6 is the *shorter* exposure and was also graded *sharp*, so the literal §3.6 rule of `protocols/exposure-blur-procedure.md` ("shortest exposure graded sharp/streaked with acceptable luminance/noise") picks −6 unless its luminance (36 grey levels) is judged below the usability floor, which is To Be Experimentally Determined in Phase 03; −6 remains the alternative and is the value the Phase 02 FPS/latency runs used. The blur proxy increases with luminance in this data set and therefore cannot separate sharpness from brightness; the grades are the evidence. The config fragment keeps `exposure.value: -6` (candidate) until the owner moves it — changing it changes `config_hash` for later runs. Other lighting conditions: PENDING.

## 6. Capture latency — MEASURED upper bound (Task 02.8)

Method: `protocols/capture-latency-flash-method.md` (screen flash, rolling baseline, k = 6, min-delta 0.3 grey levels, 30 trials per run). Condition: room lit only by the laptop screen at **0 % brightness** (§9) — the flash contrast was too small at exposure −6 (4.8 σ, runs `…-0305-…`, `…-0306-…`, `…-0310-…` ABORTED, not citable), so the measurement uses **−4** (robust, 62 ms exposure, ~16 FPS) and **−5** (31 ms, ~30 FPS); the exposure term is therefore larger than in the baseline mode and the values are upper bounds in two ways (display latency + exposure).

| Backend / policy | Exposure | Frame period (ms) | raw = t_frame_available − t_flash: median / p10 / p90 / min / max (ms) | t_capture − t_flash median (ms) | raw − period/2 (ms) | detected / trials | min contrast (σ) | run_id |
|---|---|---|---|---|---|---|---|---|
| DSHOW / GRAB_RETURN | −4 (62 ms) | 63.95 | **118.2** / 101.8 / 124.7 / 99.6 / 126.7 | 117.7 | 86.2 | 30 / 30 | 17 | `20260921-0314-p02-latency-dshow-exp4` |
| MSMF / DRIVER_MAPPED | −4 (62 ms) | 66.67 | **116.7** / 101.7 / 124.4 / 94.5 / 161.5 | **45.9** | 83.3 | 29 / 30 | 11 | `20260921-0315-p02-latency-msmf-exp4` |
| DSHOW / GRAB_RETURN | −5 (31 ms) | 31.97 | **115.8** / 92.8 / 125.3 / 84.4 / 133.2 | 115.3 | 99.8 | 30 / 30 | 7 | `20260921-0317-p02-latency-dshow-exp5` |
| MSMF / DRIVER_MAPPED | −5 (31 ms) | 33.33 | **116.9** / 91.1 / 137.1 / 82.4 / 895.0 ¹ | **70.3** | 100.2 | 29 / 30 | 6 | `20260921-0318-p02-latency-msmf-exp5` |

| DSHOW / GRAB_RETURN, **L2 lighting, screen at normal brightness** (owner, 09:13) | −5 (31 ms) | 32.04 | **137.7** / 117.1 / 159.6 / 105.4 / 553.1 ² | 137.4 | 121.7 | **27 / 30** ³ | 6.7 | `20260921-0913-p02-latency-dshow` |

¹ one late detection (895 ms) at the marginal contrast of this run (6 σ); it is kept in the distribution and visible in p90/max; the median is unaffected.
² one late detection (553.1 ms) kept in the distribution (visible in p90/max); the median is unaffected.
³ trials 8, 11 and 24 were NOT DETECTED within the 1.0 s timeout (default detection floor `min_delta` 3.0 grey levels, k = 6; baseline luminance ≈ 76 under L2). They are counted, not dropped. Same command as the L0 runs except the lighting/screen condition (`--backend DSHOW --timestamp-source GRAB_RETURN --exposure MANUAL:-5 --trials 30`); negotiated 640×480 YUY2, driver fps property 30.00003 (advertised), `stamp_after = RETRIEVE`, no driver timestamps.

Findings (MEASURED, upper bounds — every value includes the unknown display latency; none of them is `L_sys` or any README §5 latency term):

- **L2 re-run (C-2), DSHOW, −5, screen at normal brightness:** raw hand-over after the flash command **137.7 ms median** (p10 117.1, p90 159.6, min 105.4, max 553.1 ms), `t_capture − t_flash` median 137.4 ms, half-period-corrected median 121.7 ms, 27 of 30 trials detected. Compared with the L0 run at the same exposure (`…-0317-…`: median 115.8 ms, 30/30), the L2 values are ~22 ms higher and three trials went undetected; the run is recorded as is — the profile does not attribute the difference (screen content, brightness, exposure settling and detection margin all changed between the two conditions and were not separated).

- **Flash → frame hand-over is ≈ 115–120 ms median on both backends and at both exposures**, with a floor of **82–100 ms** (minimum over 30 trials). Because the value barely changes when the exposure and the frame period are halved (−4 → −5), the bound is dominated by a fixed term — display pipeline latency (unknown, included) plus camera readout/USB/driver delivery — rather than by exposure phase. The two backends agree on `t_frame_available` within 1 ms at the median even though DSHOW blocks per frame and MSMF delivers in bursts (the bursts average out over 30 trials).
- **MSMF driver timestamps place the capture instant ≈ 46 ms (−4) / ≈ 70 ms (−5) after the flash command**, i.e. 47–71 ms *before* the frame is handed over — consistent with the §4 hand-over lag of MSMF (≈ 40–70 ms). If the driver stamp marks the true exposure instant, the display-plus-exposure term is ≤ 46 ms at −4; the 24 ms difference between the two exposures is within the ± half-period scatter of the method and is not interpreted further.
- **Grab-return bias:** for DSHOW the stamped `t_capture` (= hand-over) is ~115 ms after the flash command, and the MSMF driver stamp suggests the true capture instant lies ~45–70 ms earlier. A bias of that order would be the honest correction, **but it cannot be separated from the unknown display latency with this method**, so `grab_return_bias_s` stays **null (0)** and every DSHOW `t_capture` is documented as *hand-over time, true exposure earlier by an unmeasured 45–115 ms bound* (PENDING: LED/photodiode or known-latency display). Phase 05/09 use `t_capture` consistently across arms, so the bias cancels in `L_pred` and `TE_pred` (both arms see the same stamps); it does **not** cancel in `L_sys`, which is why it is recorded as a bounded unknown.
- Frame-period figures confirm §5: −4 runs the sensor at ~15.6 FPS (64–67 ms), −5 at ~30 FPS.

Interpretation rules: `raw` bounds capture latency + display latency from above; `raw − period/2` is the mean exposure-phase correction; the difference between the `t_capture` variant and `raw` is the hand-over lag of §4. The **display term is unknown** (internal panel; typically ≥ one 60 Hz refresh = 16.7 ms plus panel response) so no `grab_return_bias_s` is derived (PENDING until an LED/photodiode or a display of known latency is available — Open Question in the hardware inventory).

## 7. Placement, distance, field of view

| Field | Value | Label |
|---|---|---|
| Mount | laptop on a desk, lid at its usual working angle; no tripod (REQ-024 satisfied by "fixed position" for now; tripod Open Question) | inspected |
| Lens height above floor, tilt | **0.75 m, 0°** (lid vertical) — entered by the owner with the distance-benchmark captures of 2026-09-21 (`data/dev-captures/distance/*/capture.json`) | MEASURED (tape measure, owner) |
| User distance candidates | 0.8 / 1.0 / 1.2 / 1.5 / 1.8 / 2.2 m (candidate set, protocol §3) | candidate |
| Visibility / apparent stick & hand size per distance | 0.8 m: hands yes / paths yes, stick 134.1 px (0.305 ROI-norm), hand 90 px; 1.0 m: yes / yes, 120.0 px (0.273), 122 px; 1.5 m: yes / yes, 135.6 px (0.307), 105.5 px; 2.2 m: yes / yes, 64.0 px (0.122), 53.7 px; 1.2 m dropped (unmeasured), 1.8 m not captured. Visibility is *yes* over the whole 0.8–2.2 m span at this height → the working distance is not visibility-limited; pixel columns indicative only (occlusion / click variance — caveats in `protocols/camera-distance-benchmark.md` §5). | MEASURED (visibility, L2, owner) / indicative (pixel sizes) |
| Horizontal field of view | **PENDING** — not measured (owner decision 2026-09-21: no further manual calibration before Phase 03). The stick lengths are partly occluded and unusable as the §6 known-size object; the two-marks capture was not done. No manufacturer FOV spec available (*advertised: unknown*). No number is given. | PENDING |
| Visible playing area (m) at the baseline distance | PENDING (follows from FOV + distance; FOV pending) | PENDING |
| Playing ROI (`roi.px`) | `[40, 20, 560, 440]` in the 640×480 frame (frame minus a 40/20 px margin); contains both hands and all four zone paths at every measured distance 0.8–2.2 m (L2) | candidate — **the final working distance / ROI and the practical tracking limits are decided in Phase 03 (Task 03.11) with the real hand + stick tracker on these captures**; Phase 02 shows only that visibility does not limit them |

## 8. Processing FPS

PENDING — placeholder until Phase 03 (hands + stick per frame) and Phase 16 (optimisation). Capture alone costs ≤ 1 % of one core at 640×480 (§3).

## 9. Lighting condition of every Phase 02 measurement — L0 (developer, unspecified)

All runs: 2026-09-21, 02:40–03:20 local time, night; room lighting not set or described by a person; the laptop display's brightness was **0 %** (`WmiMonitorBrightness.CurrentBrightness = 0`, inspected 03:09), i.e. the room was nearly dark; mean frame luminance under auto exposure ≈ 12–13 grey levels during the runs (an earlier probe at ~00:30 saw ≈ 65 under auto exposure — the difference is consistent with the screen being dimmed in between). Consequences: (a) the luminance columns of §5 are not representative of L1–L2 conditions; (b) the flash method needed a longer exposure than the baseline mode (§6); (c) the FPS/jitter/duplicate results of §3 are **not** expected to depend on lighting *given manual exposure* (they did not change between −6 in §3 and −7 in §2), while the auto-exposure results are lighting-specific by nature. Every table above carries this condition; `protocols/lighting-checklist.md` §4 records it.

## 10. Limitations and what this profile does not claim

- Single hardware (HW-01), single lighting condition (L0, dark), single session; no VALIDATED value (an independent repeat session under a described lighting condition is required for that).
- No tracking-quality claim of any kind (Phase 03); no processing FPS (Phase 03/16); no effective-latency claim (Phase 18).
- Capture latency is bounded, not determined: the display term and the exposure phase are inside the bound.
- The 1280×720 modes were measured but not chosen; the 848×480 / 960×540 MJPG modes on DSHOW were only probed (§2), not measured for 60 s — a Phase 03 option if 640×480 proves too coarse.
- Exposure values are backend-specific integers on a log2 scale; the profile does not claim absolute exposure times beyond the DirectShow convention (2^value s).
- The development runs were taken on a dirty git tree (the code under test). The baseline-mode FPS cells (640×480 @30, both backends) were re-run on the committed tree with `git_dirty: false` (§3, C-3) and are the citable ones; the 60 FPS attempt, the 720p cells, the auto-exposure cells, the exposure inspection and the flash-latency runs were **not** re-run on the clean tree and remain dirty-tree MEASURED evidence for this phase's engineering decisions (integrity I-11; re-run before any thesis citation).
