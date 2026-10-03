# Standing four-pad implementation and developer validation

Date: 2026-10-03. **Candidate implemented; V1 acceptance has not passed.**
All evidence below is synthetic or developer evidence. Phase 18 remains blocked.
No participant collection, commit, push, tag, reset, checkout or clean was performed.

Two guided runs are complete. The revised candidate passed standing calibration,
but moving-stick evidence was insufficient to fit the first drum. The second run
delivered 24.78 FPS overall and 24.25 FPS during the stroke prompt. Moving-tip
reliability and the 30 FPS target remain blockers.

## 1. What changed

`python -m spacedrums.app.play` and `play-spacedrums.ps1` start an integrated product
path: camera → hand and visible-stick perception → automatic calibration → four-pad
geometry → causal strike decisions → existing sample mixer. The older application,
research arms and historical configurations remain available.

New modules cover endpoint evidence, constrained reach fitting, automatic calibration,
body reference detection, measured-stroke geometry, and the clean kit renderer.
Configuration schema 1.11 and separate endpoint/calibration schemas are additive.
The product decision path requires current endpoint evidence; the old launcher refuses
product configuration so it cannot bypass calibration.

## 2. Why these changes were necessary

The historical GEOM estimator uses a length prior even when its axis is detected.
Its tip record cannot establish observed endpoint reachability. The new estimator
has no length fallback. It marks weak, missing, clipped and discontinuous evidence
separately. Calibration admits measured stroke trajectories, not resting positions
or a global bounding box. Rejected fits retain their evidence and reasons.

Developer recording exposed a second problem: the historical ROI removed the bottom
20 pixels, excluding an already marginal waist reference. The candidate now uses the
whole 640×480 capture. Standing measurements expire after 3.5 seconds, preventing
old body positions from accumulating through long pose dropouts.

## 3. Coordinates

**No physically accepted coordinates exist yet.** The first live run did not reach
the fitting step. A fixture used in tests and `SYNTHETIC-layout-preview.png` must not
be adopted as the owner's calibrated layout.

Coordinates remain camera-space ROI units. Let `xL < xR` be fitted column centres,
and `yU < yD` fitted top strike heights. In the mirrored player display:

| Drum | Camera-space centre x | Top strike y | Display position |
|---|---:|---:|---|
| Crash / Ride | xR | yU | Upper left |
| Hi-Hat | xL | yU | Upper right |
| Snare | xR | yD | Lower left |
| Tom 1 | xL | yD | Lower right |

Column centres are medians of demonstrated endpoints on each side. Row heights are
the median demonstrated stroke bottoms minus a 10-pixel traversed margin. The fitter
checks ordering, centring, torso exclusion, navel band, local approach support,
image bounds and gaps. The display mirror does not alter decision coordinates.

## 4. Dimensions and geometry

**Design decision, awaiting physical validation:** four equal rounded polygon pads,
with horizontal top strike segments. Width is the greater of 72 pixels and the
largest per-target 10th–90th percentile endpoint spread plus 20 pixels. Height is
42 pixels. Horizontal and vertical edge gaps must each be at least 32 pixels.
The torso exclusion margin is 10 pixels. These floors are never reduced to force a fit.

The test fixture uses columns 0.20/0.80, top rows 0.30/0.65, width 0.15 and height
0.10. These values are synthetic, not the final user coordinates or dimensions.

## 5. Camera and ROI

Owner-reported placement: lens approximately 1.50 m high, chest approximately 1.20 m
away. These distances were not independently measured. The first live run negotiated
DSHOW, 640×480, YUY2 and a requested 30 FPS, with exposure property −6.
Capture timestamps are host `GRAB_RETURN` timestamps, not sensor exposure times.

The first recording used ROI `[40,20,560,440]`. The revised candidate uses
`[0,0,640,480]`. Calibration measures a usable reach envelope inside that image;
it does not infer depth or metres from monocular pixels. Both hips and the stroke
area must remain visible. No farther camera distance or new hardware is required.

## 6. Automatic calibration

1. Stand in the visible frame with waist, both hands and both sticks visible.
2. Collect at least ten stable, recent shoulder/hip references over at least 1.5 s.
   Require current measured endpoints for both hands. Navel height is an explicit
   anatomical approximation: shoulder height plus 0.78 of the shoulder–hip interval.
3. Follow each provisional pad cue with six relaxed strokes, including at least two
   with each hand. A recorded stroke needs measured downward travel and a rebound.
   A short missing interval can retain an already measured downward approach;
   no predicted samples fill the gap. Idle or expired motion cannot bridge it.
4. Fit all four pads together from those trajectories. Reject insufficient local
   evidence, overlap, small gaps, body intrusion or inadequate approach margins.
5. Verify another six strokes per pad. Require at least 90% commit matching, no
   wrong/unmatched commits and at least 80% measured endpoint coverage per target.

The verification is a consistency check between perception and decisions, **not
independent physical hit truth**. Sound begins during verification after a fit passes.
Failed calibration disables sound. R starts a fresh attempt; Esc/Q closes the app.

## 7. Tracking architecture

MediaPipe Hand Landmarker detects both hands. Existing causal identity association
and Kalman state are retained. The product's VALID position is the current accepted
endpoint to avoid position-filter delay at impact. Predicted positions remain
DEGRADED and cannot trigger a product strike or calibrate a pad.

Hand landmarks anchor a connected-pixel line fit. A current supported endpoint must
lie inside the search region. If a reliable line is cut by that region, the revised
candidate turns and extends the search along the **current image's fitted axis**,
up to 14 hand spans. It still requires visible endpoint support and rejects image-edge
clipping. Temporal angle, length and relative displacement checks reject isolated
jumps; a subsequent consistent observation can reacquire.

Either hand may hit any pad. Stable identity through physical crossings and occlusion
has not yet passed live validation.

## 8. Strike detection and audio

Independent per-hand measured trajectories require downward approach, minimum travel,
velocity and crossing of a pad's top surface. Complete between-frame crossings work.
One continuous downstroke produces at most one pad hit. A measured rebound re-arms it.
A bounded gap can retain history; crossing a gap requires measured downward approach
before the gap. Prediction does not create a crossing. Reacquisition inside a pad,
resting tips, lateral entry, upward motion and rejected teleports do not seed hits.

Existing candidate, commit, timing and polyphonic audio contracts are reused.
Per-hand and per-zone refractory intervals are 25 and 35 ms. Simultaneous hands keep
separate event IDs. Samples are the existing recorded TR-505 crash, closed hi-hat,
snare and high tom. No new impact animation or audio processing is added.

## 9. Models and candidate comparisons

The existing pinned MediaPipe Hand Landmarker remains the hand model. Pose Landmarker
Full is added only for the standing step, at most 5 Hz. Its SHA-256 is
`5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1`.
Assets are hash-verified on load. See the official
[Pose Landmarker documentation](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker).

Measured comparisons on the current recording's 643-frame interval:

| Candidate | Accepted endpoint observations / 1,286 | Endpoint compute p50 / p95 |
|---|---:|---:|
| Paired line edges | 70 | 18.64 / 36.37 ms |
| Fixed connected-support search | 741 | 12.44 / 25.58 ms |
| Axis-following search | 875 | 12.99 / 23.17 ms |

These are saved-current-hand replay results, from one sequential benchmark. They
measure coverage and cost, not labelled endpoint accuracy. The axis-following search
recovers 134 observations; temporal outlier rejections also rise from 9 to 15.
Plain forward extension alone recovered none and was superseded. Paired edges are
retained only as an experimental comparison. Full-frame hand input and full-frame ROI
did not materially improve endpoint coverage in the fixed-search comparison.

On the older 325-frame recording, widening the initial support search improved
coverage from 104 to 170 of 650 hand observations. Historical GEOM's higher presence
count is not comparable measured-tip accuracy. No labelled training corpus exists
for a stick-tip network or temporal strike model. No GRU/TCN/Transformer was promoted
on untrained weights or synthetic-only accuracy. A stronger model remains eligible
if it demonstrates better physical recall and acceptable cost.

## 10–12. CPU, GPU, FPS and latency

The actual host reports **Quadro M620, 2 GB**, not the RTX 3050 named in the directive.
The installed MediaPipe GPU delegate fails explicitly because GPU processing is
disabled in its build. PyTorch is CPU-only; ONNX Runtime exposes CPU/Azure providers.
No GPU acceleration is claimed. The final live GPU snapshot was 0% / 0 MiB; it is
a snapshot, not a utilization trace.

First guided run (`live-guided-01`):

| Measurement | Result and interpretation |
|---|---|
| Raw capture reads | 4,238 / 140.43 s ≈ 30.18 reads/s; includes warm-up |
| Delivered unique frames | 2,169; 15.49 FPS over their timestamp span |
| Frames with any hand | 585; 10.26 FPS across their first/last timestamp span |
| Queue drops | 2,055 attributed to delivered samples; 2,057 total at shutdown |
| Duplicate/stalled frames | 0 / 0 reported |
| Process CPU | 82.75 CPU s / 147.42 wall s = 56.13% of one core |
| Hand inference p50 / p95 | 25.77 / 45.13 ms |
| Pose inference p50 / p95 | 25.94 / 43.36 ms |
| Queue age p50 / p95 | 16.31 / 31.03 ms |
| Capture-return to decision-stage end p50 / p95 | 74.82 / 126.41 ms |
| Whole frame work p50 / p95 | 58.20 / 108.64 ms |

This run saved PNGs synchronously. Its `perception_ms` field also includes PNG
writing because the timer began too early. That field must not be presented as pure
perception inference. The launcher now records image-writing time separately.
The tiny recorded decision-stage duration occurred while the sounding pipeline was
disabled; it is not the latency of an actual strike decision.

Compute-only replay of fixed-search perception measured 36.85 / 60.25 ms p50/p95,
with 25.54 frames/s throughput. Reframing the same images measured 34.71 / 47.59 ms
and 28.21 frames/s. These exclude capture, pose, rendering, recording and audio;
they are not live FPS and do not establish 30 FPS feasibility.

**Action-to-sound, DAC output latency and live audio scheduling latency remain
unmeasured.** No sounding stage was reached. Host capture-return time cannot stand
in for the physical start of a gesture. The report keeps unavailable metrics null.

### Second guided run: revised candidate, no PNG recording

`live-guided-02` used the full camera ROI and axis-following endpoint search. The
owner confirmed readiness after the request for a slight downward camera tilt.
Standing calibration passed; the first reach prompt timed out after 30 seconds.

| Measurement | Result |
|---|---|
| Raw capture reads/s | 30.18, including warm-up |
| Effective unique FPS | 24.78 overall; STAND 22.50; REACH 24.25; RETRY 26.47 |
| Frames and drops | 2,809 delivered; 611 attributed drops; 612 total at shutdown |
| Duplicate/stall reports | 0 / 1 |
| Process CPU | 44.125 CPU s / 120.46 wall s = 36.63% of one core |
| Hand inference p50 / p95 | 25.28 / 42.79 ms |
| Perception p50 / p95 | 33.71 / 50.17 ms, excluding pose and image writing |
| Pose inference p50 / p95 | 23.89 / 38.65 ms |
| Queue age p50 / p95 | 14.29 / 30.47 ms |
| Capture-return to decision-stage end p50 / p95 | 51.24 / 75.91 ms |
| Whole frame work p50 / p95 | 36.95 / 58.75 ms |

These runs differ in framing, code and recording mode; their difference is not a
controlled estimate of recording overhead. Neither contains a READY/play interval.
The decision stage again had no sounding pipeline. No audio-latency claim follows
from those timing values. Stage summaries count the state entering a frame, while
observation logs record the state after update, causing one-frame boundary differences.

## 13–16. False hits, misses, rapid and simultaneous hits

`synthetic-validation.json` runs the actual product decision pipeline and audio
scheduler against rendered observation fixtures sampled at 30 Hz:

| Scenario | Expected | Matched | Missed | Extra hits |
|---|---:|---:|---:|---:|
| Either hand on every pad | 8 | 8 | 0 | 0 |
| Simultaneous two-hand strokes | 20 | 20 | 0 | 0 |
| Alternating roll | 20 | 20 | 0 | 0 |
| Same-hand 7.5 Hz repetitions | 10 | 10 | 0 | 0 |
| Hover, lateral, upward, stop-short, rest jitter | 0 | 0 | 0 | 0 |

All 58 expected events also reached the audio scheduler. Ten frames produced two
independent simultaneous events. Tests also cover short gaps, uncertain/missing
evidence, tip discontinuity, prefix causality and minimum geometry constraints.
These fixtures bypass camera perception. **Physical false-hit and missed-hit rates
are unknown.** Zero live commits during failed calibration is not a zero false-hit rate.

## 17. Known limitations and acceptance status

The first guided run remained in STAND. Of 585 frames containing any detected hand,
565 contained both hands, but only 245 contained both accepted tips. Pose replay
frequently missed the hips; median accepted hip y was 1.026 in the old ROI, outside
its lower boundary. The recording is noisy and the waist is at the image edge.

The revised candidate fixes crop loss and some search clipping, but physical
reachability, moving-tip accuracy, cross-hand identity, rapid live strokes, rolls,
simultaneous audio and 30 FPS have not passed. No final pad placement is certified.
Calibration dimensions and thresholds remain design choices, not measured ergonomic
limits. Low coverage cannot be accepted merely because it prevents false hits.

During the second run's 728 logged REACH frames, both hands were detected in 445,
but both tips were accepted together in only 8. Of 1,456 hand-tip observations,
164 were accepted (11.26%); 409 had no visible axis, 377 had weak/short support,
343 lacked the hand, 150 had low confidence, 10 were temporal outliers and 3 had
uncertain grip direction. Only one completed calibration stroke was admitted.
The raw video was deliberately not recorded in this timing run, so these motion
failures cannot be re-evaluated with another image model from this run alone.

A final offline check replayed its saved endpoint/body observations. Preserving a
bounded measured approach through brief missing samples raised admitted calibration
strokes from one to two. The fit still failed for insufficient evidence. This is
a developer replay improvement, not a second live pass or a physical miss-rate estimate.
Further relaxing acceptance thresholds would not establish reliable tip measurements.

The full suite before final revisions completed with 1,677 passed, one skipped and
two failures. Both failures were corrected: an obsolete unknown-schema fixture and
direct clock calls in the new launcher. The final focused run passed **592 tests,
with one hardware test skipped**, covering architecture, contracts, geometry, hands,
sticks, tracking, timing, UI, product flow, commit, audio and capture. The original
full-run result is retained, not rewritten as an all-green run.
After the final calibration gap change, all 37 product tests passed, including
new one/two-frame gap, long-gap and idle-reacquisition cases. Ruff and `git diff
--check` passed. Explicitly listing several test directories initially exposed
existing `from conftest import ...` import collisions; running from the tests root
with exclusions produced the successful 592-test result.

## 18. Remaining owner actions and evidence

The requested second developer run is finished. No further zone-placement exercise
is justified by these results. The next perception investigation needs a short raw
developer motion capture with visible endpoints through strokes, plus independently
checked endpoint/stroke labels. Those are needed to compare a stronger endpoint or
temporal image model against actual accuracy, rather than admission counts. The owner
would need to perform that capture; software analysis and model evaluation follow.
No participant collection or hardware purchase is requested.

The execution host's GPU differs from the directive. If RTX 3050 benchmarking is
intended, its availability on the execution machine must first be established.
Physical strike validation and independent action/audio timing remain required
before owner acceptance. The stopping condition is the demonstrated perception
and performance blocker, not successful V1 completion.

Evidence is retained locally under
`experiments/pre-participant/20261003-product-v1/`: reach audits, perception comparisons,
synthetic validation, test logs/XML, illustrative preview, and `live-guided-01/`
with frames, observations, report and diagnosis; `live-guided-02/` contains observations,
report and diagnosis without raw pixels. Before/after gap replay reports preserve
the final calibration experiment. These directories are git-ignored;
the report and source changes are reviewable in the working tree.

The user guide is [standing-product.md](../user/standing-product.md), with startup
and replay commands. This candidate does not authorize participant collection.
