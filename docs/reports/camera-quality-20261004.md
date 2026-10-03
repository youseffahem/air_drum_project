# Developer camera investigation and compact HUD — 2026-10-04

Follow-up: the owner subsequently approved **developer-only manual -5**.
Production remains -6. The [short endpoint check](developer-endpoint-check-20261004.md)
has now run and failed continuity/position stability. The adoption-pending notes
below describe the earlier investigation state.

Physical strike testing stayed stopped. No decision pipeline or audio stream was
started for these measurements. This is developer evidence on the integrated
webcam, not participant evidence or validation of audible strikes. Production
configuration, perception code, thresholds and 2x2 geometry were not changed.

## A. Why the image is dark

The developer demo requests DSHOW manual exposure **-6**. In this room, changing
only the exposure request to **-5** raised mean ROI luminance from **36.61 to
62.29/255**, with raw capture still about **30.19 reads/s**. Returning to -6
made the image dark again (33.07). This establishes exposure as a material
contributor under the observed lighting, though posture and scene were not
perfectly controlled between profiles.

The existing normal product renderer also applies `alpha=0.60, beta=4` to its
display image; the developer demo does **not** use that renderer. That dimming
cannot explain the current developer-demo darkness. It was not changed here.
Perception receives the original pixels in both paths.

The supplied attachment contained text only, not the referenced Windows Camera
and SpaceDrums screenshots. Windows Camera settings/backend were not inspected.
Its exact advantage therefore remains unverified; longer/automatic exposure,
gain, other device controls and processing are plausible differences, not findings.

Microsoft defines the exposure control in log2 seconds: -6 is approximately
15.625 ms, -5 is 31.25 ms, and -4 is 62.5 ms. This explains why longer exposures
can sacrifice a 30 FPS cadence. [Microsoft CameraControlProperty](https://learn.microsoft.com/en-us/windows/win32/api/strmif/ne-strmif-cameracontrolproperty).

## B. Current camera audit

Baseline hardware readbacks, repeated throughout the sweep:

| Property | Requested / observed |
|---|---|
| Device | Integrated Webcam, index 0 |
| Backend | DSHOW |
| Resolution | 640x480 requested and delivered |
| FPS property | 30 requested; driver reports 30.00003 |
| Raw capture / processed FPS | 30.19 / 25.72 in the comparison baseline |
| Exposure | MANUAL -6; setter accepted, value reads -6 |
| Auto-exposure readback | -1, uninformative; setter reports success |
| Gain / brightness / contrast | 1 / 0 / 0 |
| Saturation / sharpness / hue | 64 / 2 / 0 |
| Gamma / backlight | 100 / 3 |
| White-balance temperature / auto WB | 4600 / 1 |
| Focus / autofocus | -1 / -1, unavailable via this backend |
| FOURCC | YUY2, raw code 844715353 |
| Decoded image | uint8 BGR, CONVERT_RGB = 1 |
| Separate blue/red WB, zoom, pan, tilt, iris | -1, unavailable |
| FORMAT, MODE, buffer size, codec pixel-format property | -1, unavailable |
| Timestamps | GRAB_RETURN after RETRIEVE; no driver timestamps |

The project forces device/backend, width/height, FPS and manual exposure; it
reapplies exposure after warm-up. `pixel_format` is null, so YUY2 is negotiated,
not explicitly forced. Gain, brightness, contrast, saturation, sharpness,
white balance and focus are not set by the project. No gain/brightness adjustment
was tested because OpenCV does not expose reliable ranges here. A readback alone
does not establish that a control can be changed reliably.

OpenCV 5.0.0 is installed. Its unsupported-property sentinel is -1; do not mistake
unavailable focus/auto-exposure state for a meaningful setting. A successful
setter also does not guarantee the requested value: **-3 returned success but
read back -4 twice**, and behaved like -4.
[OpenCV property documentation](https://docs.opencv.org/5.0/main_modules/videoio_flags_base.html),
[OpenCV 4-to-5 migration](https://github.com/opencv/opencv/wiki/OpenCV-4-to-5-migration).

## C–F. Limited profile comparison

Runner: `scripts/camera_quality_experiment.py`. A separate unchanged baseline
audit preceded the sweep. Each sweep profile used three seconds of settling,
then ten seconds of the same hand/endpoint architecture, one capture thread and
drop-oldest queue. No cosmetic image adjustment was applied. Preview was off;
representative PNGs were written after each sample. JSON logging is included in
the measured consumer workload. Actual samples lasted about ten seconds.

| Request | Readback | ROI/lower luminance | Raw reads/s | Processed FPS | Queue drops | Hands present | Accepted given hand | Both tips / frames |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline -6 | -6 | 36.61 / 21.35 | 30.19 | 25.72 | 45 | 41.70% | 10.65% | 1 / 259 |
| **-5** | **-5** | **62.29 / 36.31** | **30.19** | **27.79** | **24** | **98.74%** | **41.17%** | **33 / 278** |
| -4 | -4 | 108.05 / 69.79 | 16.07 | 16.07 | 0 | 99.69% | 90.40% | 133 / 162 |
| -3 | -4 (clamped) | 107.37 / 69.44 | 16.07 | 16.07 | 0 | 100% | 90.43% | 132 / 162 |
| Auto request | -4; auto flag unavailable | 113.68 / 74.10 | 15.08 | 15.07 | 0 | 100% | 86.75% | 111 / 151 |
| Baseline repeat -6 | -6 | 33.07 / 19.06 | 30.19 | 22.96 | 72 | 52.16% | 0.83% | 0 / 231 |

Hands present means detected hand observations / (2 x processed frames).
Accepted given hand means accepted measured endpoints / detected hand observations.
Endpoint coverage over **all** hand/frame opportunities rose from **4.44% to
40.65%** for the first baseline versus -5. These are algorithm acceptance rates,
not ground-truth endpoint accuracy. The repeat baseline shows scene/landmark
dependence; this short sequential experiment is not a controlled efficacy trial.

| Request | Luminance std | Mean absolute frame brightness delta | Highlights >=250 | Perception p50/p95 ms |
|---|---:|---:|---:|---:|
| -6 | 1.088 | 0.094 | 0% | 33.71 / 50.15 |
| -5 | 0.161 | 0.079 | 0.0000082% | 31.93 / 45.93 |
| -4 | 0.495 | 0.117 | 0.02119% | 36.76 / 53.20 |
| -3 request | 0.233 | 0.119 | 0.01730% | 33.47 / 58.26 |
| Auto request | 0.208 | 0.124 | 0.02572% | 34.27 / 50.27 |
| -6 repeat | 0.083 | 0.060 | 0% | 40.48 / 57.08 |

No duplicate frames were reported in the sweep. Raw-read rates include settling;
perception metrics and table drops exclude it. These queue drops are not claimed
as sensor frame losses. The driver continues advertising 30 even at the slower
exposures; advertised FPS is not delivered FPS.

**Best tested 30-FPS-capable candidate: DSHOW, index 0, 640x480, request 30,
YUY2 negotiated, MANUAL -5**, other readbacks as above. This improves visibility
without software brightening. It remains visibly noisy and does not fully meet
the endpoint-reliability or near-30 processed-FPS goal.

## G–H. Green tips and remaining blocker

Green measured endpoints appeared intermittently. The -5 representative contains
both; only **33/278 frames (11.87%)** had both accepted. Representative images
are the first frame with the highest tip/hand-presence score, not typical-frame
accuracy evidence. At -6 and -4, visual inspection also found accepted markers
partway down a shaft: current-image support can end before the physical tip.

At -5, among 556 hand/frame opportunities: 226 accepted, **296 weak/short
support**, 13 no visible axis, 7 missing hands, 5 low confidence and 9 temporal
outliers. Of the 296 weak/short cases, **285 fail minimum connected support
length** (221 length only, 64 length and confidence); 11 fail confidence only.
Their median connected support length is zero, despite median axis inlier ratio
0.723. Retained edges therefore often fail to provide continuous outward shaft
support from the grip. This is the immediate measured blocker, not a strike gate.

The underlying conditions are only partly separable with this evidence:

| Candidate explanation | Evidence / limit |
|---|---|
| Illumination / contrast | Exposure increase greatly improves hand detection and acceptance; low visibility contributes. No lux or stick/background contrast ground truth. |
| Connected support | 285 short-support failures at -5; direct measurable bottleneck. |
| Hand quality | Hand presence is 98.74% at -5; missing hands no longer dominate. Landmark accuracy itself was not ground-truthed. |
| Orientation / background texture | Weak frames contain 408 orientation-rejected, 222 non-elongated and 167 small components; 457 retained. These are component counts, not independent causal frame labels. |
| Search placement / clipping | Saved search regions are visible; no CLIPPED_ENDPOINT failures at -5. A misplaced region can still fail earlier, so placement is not ruled out. |
| Motion blur / exposure time | Longer-exposure cadence penalty measured; dynamic blur not isolated because no prescribed movement/strike test was run. |
| Thickness / resolution | Fixed at 640x480; shaft width not systematically measured. Resolution effects not isolated. |
| Focus | Not exposed by this backend; cannot attribute failures to autofocus. |
| Leaving search region | No controlled entering/leaving test; unresolved. |

No endpoint was fabricated, no length fallback reintroduced, and no validity
threshold lowered. The diagnostic view shows current hand landmarks, search
region, fitted axis, rejection reason, exposure and FPS; only accepted MEASURED
evidence produces a green dot. Early-rejection debug references are cleared in
the experiment to avoid showing another hand's or frame's stale analysis.

## I–J. Adoption and next physical check

**Do not adopt a production default yet.** -5 merits a developer-only trial:
it retains 30-capable capture and improves visibility, but accepted-tip accuracy,
two-tip continuity and moving-stick clarity remain insufficiently validated.
The production/developer YAML still requests -6. The camera was closed after
the sweep; its existing close routine restores automatic exposure for other apps.

Per the supplied instruction to ask before adoption, the pending choice is
whether to use -5 for developer testing only. After that choice, the next check
should remain short and without the five-hit/audio demo: hold both sticks still,
raise both, move one slowly, then perform one slow downward stroke while
checking whether the green dots stay on the **physical ends**. Stop on missing
or misplaced endpoints. This check has not been started here.

## HUD correction and verification

The demo uses three compact lines, plus a fourth for the latest committed hit,
at the top-left with 14 px glyph height and 20 px line spacing. The background
blends 55% dark colour only behind the text. The representative four-line HUD
measures **218 x 90 px** at (6,6), about **6.4%** of 640x480; three lines use less.
Drum counts moved out of the zones into the HUD. Drum names remain labels.
Tips/trails/outlines are drawn after the HUD so their markers remain visible.
No full-width panel, crop, camera resize or global display adjustment is applied.
Normal user mode never constructs this demo overlay.

Verification: **42 product tests passed**; Ruff passes for both new/modified
Python files. Offline pixel checks confirmed unchanged input pixels and output
dimensions, translucency, and no HUD changes beyond its small top-left bounds.
Live audit reports have no runtime errors. No audible-strike claim is made.

## Local evidence

- Baseline audit: `experiments/camera-quality-20261004-baseline/00-baseline/`.
- Comparison: `experiments/camera-quality-20261004-comparison/`; each profile has
  `report.json`, `observations.jsonl`, `raw.png` and `diagnostic.png`.
- Detailed -5 failure breakdown: `01--5/failure-analysis.json` in that comparison.
- Updated camera/drum/HUD preview: `experiments/developer-demo-software/compact-hud-preview.png`.
- Earlier live observations remain in `data/dev-product/dev-product-20261003-235503-7548897c/`.

No commit, push, tag, reset, checkout, clean, participant work or Phase 18 work
was performed.
