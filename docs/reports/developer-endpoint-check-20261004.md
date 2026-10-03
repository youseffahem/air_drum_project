# Developer endpoint check at manual exposure -5 — 2026-10-04

**Result: endpoint continuity and position stability did not pass.** The owner
approved exposure -5 for the developer demo only. This is now set in
`configs/demo.professor.candidate.yaml`; production/default remains manual -6.
No perception thresholds, measured-tip rules, length fallback or 2x2 geometry
were changed. No participant protocols or Phase 18 work were started.

## Configuration and procedure

The previous camera process was already closed. A fresh DSHOW connection was
opened at 640x480, requested 30 FPS. The driver negotiated **YUY2** and read back
**exposure -5** at the start and end. Both exposure setter calls succeeded.
Other device readbacks remained gain 1, brightness 0, contrast 0, saturation 64,
sharpness 2, gamma 100, backlight 3 and white-balance temperature 4600.

`scripts/check_developer_endpoints.py` ran the existing `Perception` path and
rendered the unchanged four drum guides plus measured markers/trails. It never
constructed a strike decision pipeline or audio output. The user pressed Space
to begin four six-second cues: hold both still, raise both, move one slowly,
and make one slow downward stroke. The check ended automatically after 24 s.
The camera and window were closed cleanly. No subsequent live check was started.

All 608 processed frames were buffered in memory during the check, then saved
as JPEG quality 95 after camera shutdown. Compression was not fed to perception.
The report and observations retain real capture timestamps and current evidence.
The first/last recorded capture stamps span 23.952 s.

## Measurements

| Metric | Observed |
|---|---:|
| Actual processed FPS | **25.34** |
| Processed frames | 608 |
| Capture-queue drops within measured span | 116 |
| Hand presence, individual hand/frame opportunities | **77.22%**, 939 / 1216 |
| Both hands detected in a frame | 57.07%, 347 / 608 |
| Accepted measured endpoint given detected hand | **29.29%**, 275 / 939 |
| Accepted endpoint over all hand/frame opportunities | 22.62%, 275 / 1216 |
| Both endpoints accepted in a frame | **9.38%**, 57 / 608 |
| Longest continuous both-tip run | **0.639 s**, 17 frames |
| Both-tip runs / observed losses | 17 / 17 |
| Perception p50 / p95 / max | 34.93 / 52.86 / 72.73 ms |

Continuity requires acceptance on consecutive processed frames, with no capture
timestamp gap greater than 0.115 s (the existing display trail gap). These are
acceptance measurements, not ground-truth physical-end accuracy.

| Cue interval | FPS | Hand presence | Accepted given hand | Both-tip frames |
|---|---:|---:|---:|---:|
| Hold both still | 25.71 | 82.47% | 36.61% | 21 / 154 (13.64%) |
| Raise both | 24.49 | 89.04% | 37.69% | 25 / 146 (17.12%) |
| Move one slowly | 26.14 | 50.32% | 17.72% | 0 / 157 |
| One slow downward stroke | 25.13 | 88.41% | 20.97% | 11 / 151 (7.28%) |

These are cue-window labels. Saved frames show transitions between gestures
within some intervals, so they are not perfectly isolated conditions. During
the one-stick movement interval the other hand was lowered; its absence partly
explains zero both-tip coverage. The detected moving-hand endpoint was still
accepted only 28 times among 158 detected-hand observations in that interval.

## Physical-end accuracy and operator observation

The owner reported: **“They disappeared, but visible dots stayed at the ends.”**
That observation is preserved separately from the sampled saved-frame review.
The review confirms disappearance even while the wooden stick is visibly in
frame, and catches brief positional failures:

- **Frame 342, 9.49 s:** the accepted RIGHT endpoint is near the face/neck,
  off the corresponding wooden stick. LEFT is near its physical end.
- **Frame 640, 21.50 s:** the accepted RIGHT green dot is partway along the
  stick on the right of the mirrored preview; the physical tip extends well
  above it. LEFT is near its physical end.
- **Frame 318, 8.50 s:** both accepted markers are near their physical ends,
  demonstrating intermittent correct placement rather than consistent accuracy.

Thus the dots do **not** consistently appear, remain at the physical ends, or
survive slow movement. The saved examples do not establish an exhaustive
percentage of wrongly positioned endpoints. No manual labels were fed back to
the estimator and no endpoints were invented or filled in.

## Exact remaining blocker

The measured endpoint stage is unreliable before strike detection would run.
Across 1216 hand/frame opportunities, the reasons were:

| Outcome/rejection | Count |
|---|---:|
| Accepted connected-axis endpoint | 275 |
| No visible axis | **387** |
| Weak or short support | **248** |
| Hand missing | 277 |
| Low confidence | 15 |
| Temporal outlier | 14 |

Of the 248 weak/short cases, **215 failed connected support length** (67 length
only, 148 length and confidence); 33 failed confidence only. The two saved
positional examples also show that an accepted fitted-support endpoint can
belong to a shaft segment or unrelated image edge rather than the physical tip.
Brightness improvement alone has not resolved support extraction and association
with the true stick. Hand visibility is an additional limitation. Noise, motion
blur, background texture and orientation are not independently isolated by this
short check, so no single underlying cause is claimed beyond those measured
failure stages.

## Evidence and checks

Evidence directory: `experiments/developer-endpoint-check-20261004-01/`.

- `report.json`: actual camera properties, overall and per-cue metrics.
- `observations.jsonl`: all 608 frames' hands, endpoints and analysis stages.
- `frames/`: 608 recorded review images.
- `visual-review.json`: operator observation, sampled findings and support breakdown.
- `step-1-review.jpg` through `step-4-review.jpg`: evenly spaced visual samples.
- `endpoint-error-frame-342.png`, `endpoint-error-frame-640.png`: logged green
  endpoints drawn on the corresponding captured frames for review.

Five existing developer-demo tests passed. Configuration comparison confirmed
that only exposure differs between developer and production camera settings;
endpoint/stroke/reach thresholds match. Ruff and `git diff --check` passed.

Stopped after this check. No five-hit demo, audio output, P1/P2/P0R,
commit, push, tag, reset, checkout or clean was performed.
