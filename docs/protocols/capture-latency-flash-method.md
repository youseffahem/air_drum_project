# Capture-Latency Measurement Method (screen flash)

**Phase:** 02 — Task 02.8 · **Status:** IMPLEMENTED (`scripts/measure_capture_latency.py`, self-tested on a synthetic camera); executed on HW-01 — results and labels in the camera profile §6.
**Definition measured:** `t_frame_available − t_capture(true)` (README §5.3 "camera capture latency"), which software stamps alone cannot give because `t_capture(true)` (the exposure instant) is not observable from software.

## 1. Principle

Create an optical event at a known `t_mono` instant and find the first frame that shows it. The event is the laptop's own screen switching from black to white (full-screen OpenCV window); the webcam sees the scene lit by the screen (works in a dim room, or with a mirror/white wall facing the screen). Per trial:

```
t_flash            = now() immediately after cv2.waitKey(1) returns (frame handed to the display pipeline)
detect frame       = first delivered FrameSample whose patch luminance > mu + max(k·sigma, min_delta)
raw                = t_frame_available(detect) − t_flash
t_capture variant  = t_capture(detect) − t_flash
corrected (mean)   = raw − period / 2
```

`mu`, `sigma` come from a baseline of ≥ 3 s of frames with the screen black; `k = 6`, `min_delta = 3` grey levels are **candidate** thresholds; the detection contrast of every trial is reported in σ units so a marginal detection is visible.

## 2. What the numbers mean (and do not mean)

| Quantity | Meaning | Label |
|---|---|---|
| `raw` distribution (median, p10, p90, min, max) | **Upper bound** of capture latency + display latency: it contains (a) the display pipeline from `waitKey` return to photons (compositor, panel response — unknown on HW-01, typically ≥ 1 refresh ≈ 16.7 ms at 60 Hz), (b) the wait until the next exposure starts (uniform in `[0, period]`), (c) exposure + readout + USB transfer + driver + backend delivery, (d) the hand-over into the queue. | MEASURED (upper bound) |
| `raw − period/2` | mean-corrected for (b) only; reported beside `raw`, never instead of it | derived |
| `min(raw)` | tightest bound on (a)+(c)+(d) seen in the run | derived |
| `t_capture − t_flash` | how much of `raw` the stamped `t_capture` recovers: for `GRAB_RETURN` with `bias = 0` it equals `raw` minus the hand-over lag; for `DRIVER_MAPPED` it shows whether the driver timestamp lies before the hand-over | MEASURED |
| `grab_return_bias_s` (config) | the value to subtract from the grab-return stamp so that `t_capture` approximates the exposure instant. **Candidate rule:** `bias = median(raw) − period/2 − display_latency_assumed`; because `display_latency_assumed` is unknown on HW-01, Phase 02 records the bias as **PENDING** and leaves `grab_return_bias_s = null` (bias 0), stating the measured upper bound in the profile instead. A later run with an LED + photodiode or a known-latency external display can close it. | PENDING |

## 3. Limitations (must accompany every use of the numbers)

1. Display latency of the internal panel is unknown and included → all values are upper bounds.
2. Exposure phase: the flash lands uniformly inside a frame period; the half-period correction is a mean correction, the per-trial values scatter by ± half a period by construction.
3. Manual exposure is mandatory (auto-exposure would react to the flash and the sensor rate would change); the luminance change must exceed the noise (`contrast_sigma_min` is reported; trials with contrast < 6 σ are suspicious).
4. The screen lights the scene indirectly; if the room is bright the contrast can be too low → trial "NOT DETECTED" (counted, never silently dropped).
5. Backend delivery behaviour (MSMF bursts vs DSHOW blocking read) is part of the measured path and differs per backend; the profile reports both.

## 4. Procedure

1. Dim the room (or aim the camera at a white wall/mirror lit by the screen); close other camera users.
2. `python scripts/measure_capture_latency.py --backend DSHOW --timestamp-source GRAB_RETURN --exposure MANUAL:-6 --trials 30`
3. Repeat for `--backend MSMF --timestamp-source DRIVER_MAPPED`.
4. Copy the summary (median, p10, p90, min, max, n detected / n trials, contrast_sigma_min, frame period) into the camera profile with the run ids; keep `latency_trials.json` in the run directory.
5. Do **not** write `grab_return_bias_s` into the config from this method unless the display latency term has been measured or bounded by a documented method (README §5.1: mapping residual must be recorded; here the residual is the unknown display term).

## 5. Alternatives considered

- **LED driven by the audio output or a GPIO** with a photodiode: removes the display term; needs hardware not in the inventory (Open Question, `hardware-inventory.md`).
- **Cross-camera / phone slow-motion**: films the screen and the webcam preview together; gives relative, not absolute, latency.
- **Manufacturer latency claims**: none available for the integrated webcam; not usable as a bound.
