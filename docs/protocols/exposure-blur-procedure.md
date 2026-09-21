# Exposure / Motion-Blur Setting Procedure

**Phase:** 02 — Task 02.5 · **Status:** procedure IMPLEMENTED; exposure-control *capability* MEASURED on HW-01 (camera profile §5); blur check **MEASURED for L2** (owner, 2026-09-21; §4) — other lighting conditions PENDING (Phase 03 / 06).
**Source:** `project-discovery.md` Q27; Phase 03 needs sharp stick tips (blur degrades tip localisation); README §11 stack.

## 1. Controls available on HW-01 (inspected + measured, 2026-09-21)

| Control | DSHOW | MSMF | Notes |
|---|---|---|---|
| `CAP_PROP_AUTO_EXPOSURE` | 0.75 = auto, 0.25 = manual; set returns True; read-back returns −1 (uninformative) | 1 = auto, 0 = manual; set returns True; read-back 0 in both states | OpenCV's own convention per backend |
| `CAP_PROP_EXPOSURE` (manual) | accepted, **read-back reflects the value** (−5, −6, −7 verified) | accepted, read-back stuck at −6, but the **effect is real** (luminance drops with each step) | value = log2(seconds): −5 = 31 ms, −6 = 15.6 ms, −7 = 7.8 ms, −8 = 3.9 ms (DirectShow scale, UVC driver) |
| Order of operations | any | **must be applied after the stream has started** (before the first frame it is ignored) | implemented in `LiveFrameSource` (re-applied after warm-up) |
| Effect on frame rate | manual −5…−8 → ~30 unique FPS; auto in dim light → ~10 unique FPS | same | camera profile §3, §5 |
| Gain / brightness | properties readable (gain 1, brightness 0) — not yet exercised | same | Open item |

## 2. Why the setting matters here

Motion blur length ≈ tip speed × exposure time. A stick tip moving 2 m/s at 1.5 m from a 640-px-wide camera with ~60° FOV covers roughly 0.8 px/ms; at 15.6 ms exposure the blur streak is ~12 px, at 7.8 ms ~6 px, at 31 ms ~25 px (arithmetic on candidate values, not a measurement). Shorter exposure trades blur for noise and a darker image, and under auto-exposure the sensor may extend the exposure beyond a frame period and *halve or third the frame rate* (measured). The procedure therefore chooses the **shortest manual exposure that keeps the image usable** for each lighting condition.

## 3. Procedure per lighting condition (`lighting-checklist.md` ids)

1. **Inspect** (machine): `python scripts/exposure_blur_check.py inspect --backends <profile backend> --values -4,-5,-6,-7,-8 --lighting <id>` → table of unique FPS, mean luminance and temporal-noise std per setting. Discard settings whose unique FPS < 28 (the sensor is being throttled) or whose mean luminance is below the usability floor (**To Be Experimentally Determined** in Phase 03; placeholder ~25 grey levels).
2. **Record a swing** (person): `... record --name swing-<id>-exp<value> --exposure MANUAL:<value> --lighting <id> --seconds 6`, performing 4–6 full-speed strokes through the box. Repeat for the two or three candidate values that survived step 1.
3. **Analyze**: `... analyze --name swing-<id>-exp<value>` → per-frame motion proxy and blur proxy; the peak-motion ROI crop is written for the qualitative check.
4. **Qualitative check**: open the peak-motion crop; grade the tip as *sharp* (edge ≤ 2–3 px), *streaked* (visible streak, tip still identifiable) or *smeared* (tip not identifiable). Record the grade.
5. **Quantitative proxy (candidate)**: the reported `gradient_mag_in_moving_region` at the peak-motion frame; higher = sharper edges in the moving region. Until Phase 03 localises the stick axis, the proxy is computed over all moving pixels in the ROI (hands included) and is comparative only (same scene, same lighting, different exposure) — never an absolute blur measure.
6. **Choose** the shortest exposure with grade *sharp* or *streaked* and acceptable luminance/noise; write it into the camera profile's per-lighting table with the run/capture ids and the grade.

## 4. Results so far

| Lighting id | Setting chosen | Unique FPS | Mean luminance | Blur grade (peak-motion frame) | Proxy | Evidence |
|---|---|---|---|---|---|---|
| L0 (developer, night, 2026-09-21) | **candidate** MANUAL −6 (15.6 ms) — chosen for the Phase 02 runs because it keeps ~30 unique FPS; luminance ≈ 15–21 grey levels (dark) | ~30 (measured, §1) | ≈ 15–21 (measured) | **PENDING** (no stick swing recorded — no person present) | PENDING | `exposure_inspect` run in camera profile §5 |
| **L2** (overhead room light, 2026-09-21 09:04–09:07, owner) | **MANUAL −5 (31 ms) — owner's selection.** §3.6 literal reading: −6 (15.6 ms) is the shorter exposure and was also graded *sharp*, so it is the rule's pick unless its luminance (36) is judged below the usability floor (To Be Experimentally Determined, Phase 03); −6 stays the alternative. | −5: 30.1 · −6: 29.7 · −7: 29.6 (unique, short probe) | −5: 68 · −6: 36 · −7: 13 (noise std 5.81 / 5.34 / 4.70) | −5: **sharp** · −6: **sharp** · −7: **streaked** (owner, peak-motion ROI crops) | `gradient_mag_in_moving_region` at the peak-motion frame: −5: 46.6 (frame 120) · −6: 38.8 (frame 79) · −7: 32.9 (frame 89) — comparative only, and correlated with luminance here | inspect run `20260921-0904-p02-exposure-inspect`; captures `data/dev-captures/swing-L2-exp-5` (171 frames, 29.93 FPS, 1 drop), `swing-L2-exp-6` (171, 29.95 FPS, 1 drop), `swing-L2-exp-7` (172, 30.13 FPS, 0 drops); DSHOW 640×480; 6 s each |
| L1, L3–L5 | PENDING | | | | | Phase 03 / Phase 06 |

Limitations: the proxy is not along the stick axis (Phase 03); no manual gain control has been exercised; DSHOW reports the exposure read-back correctly while MSMF does not, so on MSMF the *applied* value is trusted only through its effect (luminance), which is recorded per run.
