# Camera-Distance and Field-of-View Benchmark Protocol

**Phase:** 02 — Task 02.7 (protocol + visibility/pixel-size part) · **Phase 03 — Task 03.11** (tracking-quality part)
**Status:** protocol IMPLEMENTED; visibility table **MEASURED for 0.8, 1.0, 1.5 and 2.2 m** (owner, 2026-09-21, L2) — visibility *yes/yes* at all four; 1.2 m dropped, 1.8 m not captured; FOV (§6) **PENDING** (owner decision 2026-09-21: no further manual calibration before Phase 03); tracking-quality columns PENDING (Phase 03 Task 03.11). Caveats under §5. Tooling: `scripts/distance_benchmark.py` (IMPLEMENTED, self-tested).
**Source:** `project-discovery.md` Q25 ("distance … determined through camera and interaction benchmarking … enough field of view for both hands and the drumstick movement paths without excessive loss of tracking resolution"), Q24 (fixed camera), Q26 (both hands + surrounding space); REQ-024, REQ-025, REQ-026.

## 1. Question the benchmark answers

At which user–camera distance (for a given camera height and tilt) do **both hands and the full stick swing paths across all MVP zone positions stay inside the fixed ROI**, while the stick and hands remain **large enough in pixels** for the Phase 03 tracker? The first half (visibility, apparent size) needs no tracker and is this phase's part; the second half (tracking quality vs. apparent size) is Phase 03's.

## 2. Fixed factors

| Factor | Value | How recorded |
|---|---|---|
| Camera | HW-01 integrated webcam, mode of the camera profile (candidate 640×480 @ requested 30, manual exposure per lighting) | `capture.json` side-car (`negotiated`, `exposure`, `config_hash`) |
| Camera mount | Laptop on a stable table; lid angle fixed for the whole benchmark (REQ-024). Record the **camera height above the floor** (m, tape measure to the lens) and the **tilt** (degrees; 0 = lid vertical, positive = tilted up; use a phone inclinometer on the lid or "vertical by eye" with a note) | `--camera-height-m`, `--tilt-deg` |
| ROI | `roi.px` of the camera profile (candidate `[40, 20, 560, 440]`) | side-car |
| Lighting | one id from `lighting-checklist.md` | `--lighting` |
| Stick | ordinary drumstick; record length in cm (typical 5A ≈ 40.6 cm) and colour | `--note` |
| Pose | user stands facing the camera, both hands at "playing height" (elbows ~90°), stick tips pointing toward the camera-left/right zone positions | protocol §4 |

## 3. Distances (candidate set — choose per room, record what was used)

Mark distances from the lens on the floor with tape. Candidate set spanning "both hands + full swing visible" to "hands occupy a small fraction of the frame": **0.8, 1.0, 1.2, 1.5, 1.8, 2.2 m**. Add or drop values per room size; every value actually used is a row in §5.

## 4. Procedure per distance

1. Stand on the mark; hold the stick in the right hand, left hand empty at playing height (repeat with the left if hands differ in size).
2. `python scripts/distance_benchmark.py capture --label d<cm> --distance-m <m> --camera-height-m <m> --tilt-deg <deg> --lighting <id> --note "stick 40.6 cm hickory"` (5 s countdown, then one frame is saved with and without the guide overlay under `data/dev-captures/distance/d<cm>/`).
3. **Visibility check (operator, live)**: with `python scripts/show_guide.py --duration 30`, perform full swings toward each MVP zone position (hi-hat, snare, tom, crash — approximate positions from `configs/example.candidate.yaml`, drawn by Phase 04 later; use the band as reference now) and answer: *both hands inside the box at all times?* (yes / partial / no), *stick tip paths inside the box for all four zones?* (yes / partial / no) — note which zone leaves the box.
4. **Pixel sizes**: `python scripts/distance_benchmark.py measure --label d<cm> --interactive --hands-inside <a> --paths-inside <b> --note "<which zone left the box>"`; click stick butt → tip, then hand top → bottom (wrist crease to fingertip of the closed hand). The script prints the Markdown row and stores the points.
5. Paste the row into §5.

## 5. Results — visibility / pixel-size table (MEASURED when filled; PENDING now)

| distance (m) | height (m) / tilt (°) | resolution | both hands inside ROI | stick paths inside ROI (all 4 zones) | apparent stick length px (ROI-norm) | apparent hand height px | tracking quality | note |
|---|---|---|---|---|---|---|---|---|
| 0.8 | 0.75 / 0.0 | 640x480 | yes | yes | 134.1 (0.305 ROI-norm) | 90.0 | PENDING (03.11) | all four MVP zone paths inside ROI; stick 40.6 cm hickory |
| 1.0 | 0.75 / 0.0 | 640x480 | yes | yes | 120.0 (0.273 ROI-norm) | 122.0 | PENDING (03.11) | all four MVP zone paths inside ROI; stick 40.6 cm hickory |
| 1.2 | 0.75 / 0.0 | 640x480 | not recorded | not recorded | not measured | not measured | — | **dropped** (owner decision 2026-09-21): captured 08:52 but `frame.png` was not overwritten (file locked; stale first attempt), so no pixel measurement exists; bracketed by the 1.0 m and 1.5 m rows |
| 1.5 | 0.75 / 0.0 | 640x480 | yes | yes | 135.6 (0.307 ROI-norm) | 105.5 | PENDING (03.11) | all hands and stick paths remained inside ROI; stick 40.6 cm hickory |
| 2.2 | 0.75 / 0.0 | 640x480 | yes | yes | 64.0 (0.122 ROI-norm) | 53.7 | PENDING (03.11) | all hands and stick paths remained inside ROI; stick 40.6 cm hickory |

Rows measured by the project owner on 2026-09-21, 08:43–09:25 local, lighting **L2** (overhead room light), exposure MANUAL −6, DSHOW 640×480, `roi.px [40, 20, 560, 440]`; side-cars in `data/dev-captures/distance/d<cm>/capture.json` (git-ignored, HW-01). Caveats on these rows: (a) the hand height *increases* from 0.8 m to 1.0 m, which the geometry forbids, so the two hand values reflect different click points (wrist crease / fingertip) rather than a size change — treat hand-height values as ±30 px until Phase 03 replaces them with landmark-based sizes; (b) the stick shrinks by 0.895× where 0.8× is expected, consistent with the hand occluding part of the stick, so the stick values are the *visible* length, not the full 40.6 cm — they therefore cannot serve as the known-size object of §6. (c) the stick reads 135.6 px at 1.5 m, *larger* than at 0.8 m (134.1) and 1.0 m (120.0), while 1.5 → 2.2 m shrinks by 0.47× where 0.68× is expected: the click precision actually achieved is therefore worse than the ±5 px assumed below and the stick/hand pixel columns are indicative only — Phase 03 Task 03.11 re-derives apparent sizes from landmarks/stick detections on the same captures. Distance 1.8 m was not captured, 1.2 m was dropped (candidate set §3 allows both). **Visibility outcome:** both answers are *yes* at every measured distance from 0.8 to 2.2 m — the fixed ROI `[40, 20, 560, 440]` contains both hands and all four MVP zone paths over the whole candidate span at this camera height; a *partial/no* boundary was not reached and would lie closer than 0.8 m (not searched). The working distance is therefore **not limited by visibility** within 0.8–2.2 m; it will be limited by tracking resolution, which only the Phase 03 tracker can measure (§7).

Rules for the table: pixel sizes are read from a single frame and are ±5 px (click precision) — state this; `tracking quality` stays PENDING until Phase 03 fills it from the same captures; no row may be added without its `capture.json` side-car.

## 6. Field-of-view estimate (feeds camera profile §7) — PENDING

**Not measured (owner decision, 2026-09-21).** No FOV value exists for HW-01's webcam: the stick lengths above are partly occluded and unusable as the known-size object, and the two-marks capture was not performed. Any later FOV figure must come from the procedure below and be labelled MEASURED with `s`, `p`, `d`; until then every document carries *PENDING*.

From any row: horizontal FOV ≈ `2·atan(W_scene / (2·d))` where `W_scene` is the real width covered by the full frame at distance `d` (place a tape measure or two marks of known separation `s` in the frame, measure their separation `p` px, then `W_scene = s · W_frame / p`). Record `s`, `p`, `d` and the resulting FOV as **MEASURED (method stated)**; until then the profile carries *advertised* (unknown for this device) / PENDING.

## 7. Decision rule (to be applied in Phase 03, not here)

The baseline distance is the **largest** distance at which both visibility answers are *yes* **and** the Phase 03 tracking-quality columns meet their acceptance thresholds; the ROI size/placement (`roi.px`) is then frozen with the camera profile version bump. Until then `roi.px` is a candidate.
