# Offline wooden-stick endpoint investigation — 4 October 2026

**Decision: continue offline development; do not enable physical strikes or audio.**

The current estimator confuses a connected edge-run endpoint with a physical stick tip. Its hand-directed search also excludes visible stick ends. A new offline prototype substantially improves the reviewed tip positions, including both reported errors, but simultaneous tracking remains brief and its CPU cost is too high for promotion. This report completes the offline investigation and gives an implementation recommendation; it does not claim that the production tracker has been fixed.

All new code is in developer scripts and tests. No production source, exposure setting, drum layout/size, strike threshold, scheduler, sample, calibration geometry, participant protocol, or Phase 18 file was changed. No camera, strike or audio session was started. No commit, push, tag, reset, checkout or clean was performed.

## Evidence and reproducibility

**Measured:** replayed all 608 saved processed frames from `experiments/developer-endpoint-check-20261004-01/`, using the recorded, current-frame hand landmarks and capture timestamps. This isolates endpoint perception; it does not rerun or improve the hand detector. There are 1,216 hand-frame slots, 939 detected hands and 277 missing-hand slots. All frames are 640 × 480, with full-frame ROI.

Inspected `report.json`, `observations.jsonl`, `visual-review.json`, both named error PNGs, all four original review sheets, raw JPEGs and new diagnostic renders. The original review images are mirrored; raw JPEGs and every new numeric label are **unmirrored**. A visible marker on the left of an original review image is therefore not a raw-image x coordinate or an anatomical hand label.

The original run used DSHOW, requested 30 FPS and developer exposure −5. Its 25.342 processed FPS and 34.929/52.857 ms perception p50/p95 are historical live measurements, not candidate performance.

**Replay limitation:** the original endpoints were computed before JPEG compression. Replaying the saved quality-95 JPEGs gives 261 acceptances, versus 275 in the live log; 66 hand-slots change acceptance (40 live-only, 26 JPEG-only), and 138 change rejection reason. Initial temporal state from the pre-capture settling interval is also unavailable. JPEG sensitivity is strongly suggested, but compression and initial-state effects cannot be fully separated. Compare candidates against the JPEG baseline on the same pixels, retaining the original live results as a separate reference.

Artifacts are in `experiments/developer-endpoint-offline-20261004-01/`:

- `review.html`: local diagnostic viewer with 22 sampled frame comparisons.
- `inventory.json`, `additional-audit.json`: logged failure counts and replay differences.
- `comparison.json`: full-capture acceptance and continuity, overall and by cue.
- `manual-labels.json`, `accuracy.json`: explicit tip labels, uncertainty, predictions and pixel errors.
- `support.jsonl`, `paired.jsonl`, `profile_single.jsonl`, `profile_temporal.jsonl`: per-frame decisions and diagnostic evidence.
- `benchmark.json`: three warmed serial runs per method, with per-frame CPU-stage timings.
- `continuity-visual-review.json`, `both-run-*.jpg`, `slow-run.jpg`: separately selected continuity examples.
- `provenance.json`: hashes of all 608 input images, source logs, labels and final code; base Git revision `94a53935293b512e7b5361a9d034ad0dd721dc0c`.
- `candidate-v1.py`, `candidate-v2.py` and corresponding versioned results: retained unsuccessful approaches, including the unsafe temporal variant.

The artifacts are local developer evidence under the repository's existing ignored `experiments/` directory. They are not participant evidence or a release benchmark.

## 1. Root cause analysis

**Measured from code and logs:**

1. `segment_stick()` gates connected components by angle to the knuckle-row prior, elongation and size, then keeps at most four. This happens before fitting an axis. A real stick excluded here cannot be recovered by RANSAC.
2. `VisibleEndpointEstimator` uses an oriented rectangle of width 2.4 hand spans and initial forward reach 7 spans. The broad patch's pixels are only searched by the experimental paired-edge branch. The normal branch is not an orientation-independent search.
3. Search expansion occurs only after an axis passes strength/length checks and its support endpoint touches the rectangle boundary. A stick outside the initial rectangle, a failed axis or zero connected support prevents the recovery step from running.
4. `_contiguous_extent()` starts at the projected grip and stops at the first forward gap larger than half a hand span. It measures continuity of retained edge pixels, including the grip-to-shaft gap; it does not measure visibility of the physical rod. Of 248 weak/short rejections, 174 have exactly zero forward support despite having a fitted axis.
5. An accepted `support_far_px` has no independent physical-cap test. Fragmented shaft edges, an edge disappearing into low contrast, a sleeve or a body contour can end inside the search region and pass. Confidence is an axis/hand score, not a calibrated probability that the physical tip is correct.
6. The old temporal check rejects large jumps. It does not use a previous reliable axis to recover current-image shaft evidence. It can stabilize an incorrect component, and a two-frame repeat can allow reacquisition of that incorrect component.

**Manually reviewed:** frame 342 RIGHT follows a sleeve/body edge toward the face; its true stick tip is outside the final logged search polygon by 47.5 px. Its grip-to-tip direction differs from the search direction by 36.1°. Frame 640 RIGHT follows the correct shaft direction but stops partway along it; the physical tip lies inside the search polygon (6.0 px margin). These are distinct failures requiring both better search and explicit terminal evidence.

**Inferred:** hand occlusion near the grip, segmentation fragmentation, low contrast and imperfect hand direction jointly explain much of the drop-out behavior. The evidence does not support attributing every missed frame to a unique physical cause.

## 2. Failure-mode counts

Counts below are **hand-frames**, unless stated otherwise. Rows A–K overlap and must not be summed.

| Mode | Evidence-supported count | Interpretation / limits |
|---|---:|---|
| A. No stick axis | 387/939 detected-hand slots | 272 had no retained candidate pixels; 115 had pixels but axis fitting failed. Only 1 of the 272 had no Canny edges at all. |
| B. Insufficient connected support | 215 of 248 weak/short cases | 148 weak + short; 67 short only; 33 weak only. 174/248 have zero extent; 201/248 are below 18 px. The other short cases fail the span-scaled minimum. |
| C. Wrong component/edge | At least 1 confirmed accepted case in sampled live results | Frame 342 RIGHT, 97.0 px tip error. No exhaustive 608-frame wrong-component count. |
| D. Shaft mistaken for endpoint | At least 1 confirmed accepted case in sampled live results | Frame 640 RIGHT, 110.9 px error. The existing paired-edge alternative also produces large fragment-end errors in the diagnostic set. |
| E. Hand/stick association | 277 missing-hand slots; 62 present hands below 0.65 identity confidence | These are upstream availability/confidence indicators, not 339 proven association errors. Frame 613 shows a suspect identity discontinuity during blurred motion; a complete anatomical swap count is unavailable. |
| F. Endpoint search-region failure | 17/30 scorable reviewed tips outside the logged search polygon | This is subset geometry, not a dataset-wide miss rate. Includes frame 342 and the otherwise visible slow-moving stick in frame 466. |
| G. Occlusion | Unquantified causal count | Grip occlusion is visible; 3 sampled frames (365, 389, 593) show crossing shafts. Crossing is not equivalent to an occluded physical tip. No full-capture occlusion annotation exists. |
| H. Motion blur | 7/37 labelled tips excluded from precise scoring | A further blurred tip (466 LEFT, ±5 px) remains in the scored set and is borderline. Frame 613 is excluded at frame level. These are review counts, not a camera blur rate. |
| I. Background/body interference | At least 1 confirmed live false endpoint | Frame 342 selects body/sleeve evidence. Many component pixels are unrelated, but their complete causal contribution is unlabelled. |
| J. Stick orientation | Orientation-rejected components occur in 262/272 empty-candidate cases | Component rejection categories overlap: 244 also contain not-elongated rejections and 181 too-small rejections. Only 4/30 reviewed true axes differ from the logged prior by more than 0.7 rad (modulo π); even smaller errors can exclude a long tip laterally. |
| K. Leaving usable search region | 0 logged `CLIPPED_ENDPOINT`; 17/30 tips outside search as in F | Zero clipped rejections does not establish zero clipping: earlier gates can fail first. No full-image boundary exit is present in the 30 visible, scorable labels. Camera-ROI exits remain unvalidated. |

The mutually exclusive original reasons are: `HAND_MISSING` 277, `NO_VISIBLE_AXIS` 387, `WEAK_OR_SHORT_SUPPORT` 248, `LOW_CONFIDENCE` 15, `TEMPORAL_OUTLIER` 14 and accepted `CONNECTED_AXIS_ENDPOINT` 275. They sum to 1,216.

## 3. Candidate algorithms

**Existing support baseline:** unchanged connected Canny components → RANSAC → connected-run end, including its existing temporal gate. No threshold was relaxed.

**Existing paired edges:** unchanged experimental LSD-pair branch from `visible.py`. Its paired fragment ends are still not reliable physical caps. It is both slower and poorer on this capture; do not adopt it.

**New image-profile prototype, single frame:**

1. Detect line segments once per image at an internal 0.5 scale. Vector-filter short proposals, then form plausible narrow, parallel edge pairs close to each grip. Choose distal direction from grip proximity rather than hard-gating on the knuckle-row angle. This proposes an axis; it does not emit a tip.
2. Sample a narrow strip in the current full-resolution image. Compare shaft-centre appearance with both adjacent flanks using local BGR contrast and agreement. There is no fixed wood colour, coloured marker or stick-specific template.
3. Require substantial observed shaft support, plausible width and continuity. Small holes are grouped for run discovery, but the diagnostic support points retain the actual observed evidence. Reject a run ending before farther current edge evidence.
4. Require a distal appearance transition and absence of continuing shaft evidence. Search a two-dimensional neighbourhood beyond the candidate so that a slightly wrong axis cannot simply walk off the shaft and call that a cap. Reject ambiguous distal runs and image/search boundaries.
5. Reject support directed back toward the wrist. Enforce the existing 0.65 hand-identity floor. Reject ambiguous shaft choices and joint ownership of the same shaft/tip by both hands.

**New causal variant:** adds short-lived, per-hand axis hypotheses when fresh edge pairs fail. Search local angle/offset variations, but run the complete current-image shaft/cap check for every one. The prior influences ranking and jump rejection; it never supplies the returned endpoint. Last measurement age and last edge-pair axis age expire at 120 ms. Renewed profile-only evidence cannot keep an old edge-pair axis alive indefinitely. `prior_tip` is explicitly diagnostic `PRIOR_ONLY`, never a measured output. Missing image evidence yields a null tip. Input frame IDs/timestamps must match, and processing timestamps must increase.

No position smoothing or velocity extrapolation is used. The endpoint is the farthest qualifying supported run found on a proposed axis; the prototype **abstains** on long unsupported gaps. It does not yet provide a complete multi-component shaft graph capable of confidently crossing all occlusions.

All image-profile constants are provisional developer algorithm parameters. They are not validity-threshold reductions to the production estimator, participant thresholds or calibrated probabilities.

**Rejected temporal design:** the intermediate v2 prototype refreshed its prior from profile-only measurements without separately expiring the underlying edge-pair axis. On the 30-tip set it accepted 24 points but had 4 errors over 10 px, including a 274.2 px forearm endpoint at crossing frame 389. This is why higher acceptance or longer runs cannot justify a design. The final version adds distal neighbourhood checks, wrist direction and separate axis expiry; it abstains on that crossing.

**Model choice:** no new learned model was downloaded or adopted. The comparison uses existing OpenCV/NumPy dependencies on CPU. There is no new model licence or GPU cost to justify. A pretrained-model proposal would require a separate licence, quality and latency comparison.

## 4–6. Offline accuracy and manually reviewed examples

**Manually reviewed diagnostic set:** nearest saved frame to each half-second-plus-integer timestamp, 24 frames total. Reviewed grids and enlarged raw tip crops before inspecting profile-candidate results; annotated 37 tips on 22 frames. Thirty tips are scorable, with 3–5 px annotation uncertainty; 7 blurred tips are excluded from precise errors. The remaining opportunities include the lowered/absent second hand and frames 116/613 with ambiguous ownership or severe blur.

Labels were visually placed and reviewed by Codex, not an independent human annotator. They mark the apparent physical cap centre. This is neither exhaustive ground truth nor a held-out accuracy test: algorithm development subsequently used these results.

After inspecting cap size, annotation uncertainty and the baseline error distribution, **10 px** was selected as a developer comparison tolerance. It separates several-pixel localisation differences from the 97–122 px fragment/object errors. The raw errors and uncertainty classifications remain available so this cutoff cannot hide borderline points.

| Method | Accepted / 30 visible labelled tips | Within 10 px / accepted | Correct coverage / 30 | Accepted error p50 / p95 / max, px |
|---|---:|---:|---:|---:|
| Recorded live baseline | 10 | 8/10 (80.0%) | 26.7% | 4.93 / 104.63 / 110.86 |
| Same baseline on JPEGs | 11 | 9/11 (81.8%) | 30.0% | 4.61 / 104.44 / 111.17 |
| Existing paired edges | 5 | 3/5 (60.0%) | 10.0% | 8.80 / 121.39 / 122.05 |
| New profile, single frame | 18 | 17/18 (94.4%) | 56.7% | 2.92 / 5.98 / 10.84 |
| New profile, causal prior | 20 | 19/20 (95.0%) | 63.3% | 2.92 / 5.41 / 10.84 |

Errors are conditional on acceptance. Missing predictions are counted separately, not assigned zero error. For the final candidate, 19 accepted points remain inside 10 px even after adding their annotation uncertainty. The remaining point is 10.84 px from its label with ±5 px uncertainty: nominally incorrect, but visually borderline rather than a demonstrated shaft-segment error. There are zero confirmed gross shaft/background endpoints among these 20 candidate acceptances. This small, development-used subset cannot establish the error rate for all 564 candidate acceptances.

| Example | Original live result | Final candidate result |
|---|---|---|
| 342 RIGHT: sleeve/body selected | 97.02 px error | 2.02 px, current shaft and physical cap |
| 640 RIGHT: shaft fragment end | 110.86 px error | 2.53 px, physical cap beyond the old connected run |
| 466 LEFT: search misses visible stick | No axis; true tip 96.1 px outside search | Accepted, 10.84 px error; blurred/borderline |
| 389: crossing sticks | Both rejected | Both rejected; unsafe intermediate forearm acceptance removed |
| 593: crossing sticks | Both rejected | Both rejected; unresolved crossing support/association |
| 520 LEFT: low-contrast/sleeve boundary | Weak/short support | Rejects internal support break; no fabricated cap |

Use `comparison-frame-342.jpg`, `comparison-frame-640.jpg` and `review.html` to inspect the raw image, baseline search/component evidence and candidate support together. Each panel shows hand landmarks, fitted axis, shaft support, candidate/accepted/rejected locations, prior-only state where applicable, and rejection reason. The baseline cyan pixels are retained components; the candidate cyan pixels are observed profile samples. These meanings are distinguished in the viewer.

## 7. Continuity

**Measured acceptance continuity**, with no interpolation: consecutive saved frames, broken by rejection or capture gap over 115 ms, matching the original report's run convention. Durations use capture time, not frame-count/30.

| Method | Accepted hand-slots / 939 detected | Both accepted frames / 608 | Longest both run | Longest LEFT slow-cue run |
|---|---:|---:|---:|---:|
| Recorded live | 275 (29.3%) | 57 (9.38%) | 0.639 s | 4 frames / 0.144 s |
| JPEG baseline | 261 (27.8%) | 55 (9.05%) | 0.609 s | 4 frames / 0.144 s |
| Existing paired edges | 221 (23.5%) | 4 (0.66%) | Single frames only | 7 / 0.256 s |
| New profile single | 520 (55.4%) | 126 (20.72%) | 20 / 0.720 s | 7 / 0.304 s |
| New profile causal | 564 (60.1%) | 151 (24.84%) | 20 / 0.720 s | 22 / 0.800 s |

The causal candidate has 96 acceptances in the slow cue versus 22 for the JPEG baseline. Its longest overall LEFT run is 53 frames / 1.953 s. In cue 3, the recorded RIGHT hand is absent in 156/157 frames; no endpoint-only algorithm can honestly produce a sustained two-hand run there from these inputs.

**Separately manually reviewed:** all 20 frames of the longest candidate both-run (616–635) and all 22 slow-run endpoint crops (522–543). The rings follow the rod ends rather than showing the old large shaft jumps. Both cap positions are clearly resolved in 16 frames (617–632, 0.560 s); 4 frames have motion uncertainty. The slow-run crops have several-pixel offsets and some sleeve/blur ambiguity. These runs were selected because they were the candidate's longest and have no precise per-frame tip labels; do not pool them into the 30-tip accuracy estimate or call 0.720 s independently verified accurate continuity.

There is useful slow-motion improvement. There is **not yet evidence of reliable multi-second simultaneous tracking**.

## 8. Performance

**Measured:** three warmed, serial 608-frame runs per method, rotating method order, same saved images/hands, OpenCV 5.0.0, NumPy 2.4.6, OpenCV thread count 1, CPU execution. Decode, JSON serialization, annotation and rendering are outside the timed region. Both hand slots are timed together. Process CPU seconds and per-frame wall times are retained. The desktop was not exclusively reserved; occasional scheduling outliers are retained, not discarded.

| Endpoint stage | Pooled p50 | Pooled p95 | Mean | Observed max |
|---|---:|---:|---:|---:|
| JPEG support baseline | 8.02 ms | 17.92 ms | 8.86 ms | 33.69 ms |
| Existing paired edges | 23.69 ms | 39.13 ms | 23.47 ms | 98.82 ms |
| New profile single | 13.62 ms | 19.41 ms | 14.07 ms | 66.50 ms |
| New profile causal | 15.03 ms | 28.93 ms | 17.27 ms | 177.24 ms |

The initial full-scale proposal implementation cost approximately 26 ms median in its exploratory run. Reduced-scale proposals plus full-resolution confirmation cut that substantially, but the final causal version still adds about 8.4 ms **mean** endpoint compute over the baseline. The extreme maximum is a desktop timing observation, not attributed solely to algorithm cost.

**Inferred, not measured live:** substituting per-frame median replay stage costs into the recorded perception time (`old perception − replay baseline stage + candidate stage`) gives candidate perception p50 about 43.93 ms and p95 60.45 ms; single-frame profile gives 40.61/56.43 ms. These are counterfactual budget estimates from different runs, not FPS measurements. They exclude app overhead and cannot validate capture/display throughput.

The original pipeline already exceeds a 33.33 ms perception budget at the median. The candidate cannot currently be claimed to preserve the 30 FPS target or the observed 25.34 processed FPS. Performance is a promotion blocker.

## 9. Recommended endpoint strategy and evidence gates

Retain the **current-image physical-cap validation** approach, with conservative temporal search and explicit expiry. Continue it as an offline experiment. Do not copy either the existing paired-edge estimator or the unsafe v2 temporal variant into production.

Next algorithm work should fit/trace current shaft centre and width across multiple collinear fragments, then validate the farthest supported terminal cap. Use hand/wrist and a prior as proposal/association evidence, not a hard search direction or a length-derived endpoint. A bounded shaft graph or current-image strip trace is preferable to accepting the first edge break. At crossings, shared-support ownership must either resolve uniquely or abstain. It should never copy one candidate to both hands.

Reduce compute by limiting proposal detection to the union of hand-reachable regions, using bounded search along recently measured axes, sharing image preprocessing and suppressing expensive diagnostic serialization in the live path. Benchmark each change on the same pixels; these optimizations are recommendations, not measured savings.

The following **post-review developer gates** are proposed now, after seeing the baseline/candidates. They are not Phase 18 thresholds:

- At least 95% of accepted, clearly reviewed points within 10 px, p95 error at most 10 px, and zero obvious shaft/body/cross-hand endpoints over 20 px in an expanded independently reviewed set. Include rejected frames and both named counterexamples; report uncertainty and coverage. The current 20 acceptances are too few and were used during development.
- At least 80% correct coverage on clear, hand-visible labelled opportunities, preventing an all-abstain precision result. Current correct coverage is only 63.3%.
- At least one manually verified 2 s simultaneous-tip run and 2 s slow-motion run without fabricated or carried-forward measurements. Current accepted maxima are only 0.720 s simultaneous and 0.800 s in the slow cue.
- Endpoint-stage cost at or below the measured baseline envelope (roughly 8 ms p50 / 18 ms p95) before claiming no throughput regression. Separately validate full-loop throughput against the 30 FPS target; current candidate fails the endpoint budget.
- Blank/occluded/exit cases yield no measured tip, prior expires, prefixes are causal, and shared-shaft assignments are rejected. Synthetic tests cover parts of this; real occlusion/exit/identity behavior still needs evidence.

Passing one subset percentage does not pass these gates. **Promotion status: FAIL / NOT YET VALIDATED.**

## 10. Exact code changes

Implemented only for offline investigation:

| Added file | Purpose |
|---|---|
| `scripts/review_developer_endpoints.py` | Read the 608-frame capture and saved hands; replay unchanged baselines and experimental candidates in time order; write detailed decisions, acceptance and continuity; prepare raw annotation sheets. |
| `scripts/_endpoint_candidate.py` | `ProfileEndpointCandidate`: image-wide shared proposals, local shaft/cap evidence, distal continuation rejection, wrist check, joint ownership, causal axis hypotheses and measurement/axis expiry. No app integration. |
| `scripts/score_endpoint_review.py` | Score explicit reviewed labels with uncertainty, count search-region mismatch, draw evidence panels and generate a local HTML viewer. |
| `scripts/benchmark_endpoint_review.py` | Warmed repeated endpoint-only CPU comparison on cached identical inputs. |
| `tests/scripts/test_endpoint_review.py` | Synthetic checks for both caps, no output on blank images, stale-state expiry, image clipping, shared-shaft rejection, hand-order independence, causal prefix behavior, nonmonotonic/future input rejection and timestamp-aware run segmentation. |
| This report | Findings, evidence limits, integration plan and next test. |

**Required before production integration, not performed:**

1. Optimize and validate the experimental core above. Do not alter production minimum-confidence/support values to conceal missing evidence.
2. Introduce a production endpoint implementation under `src/spacedrums/stick/` with a **frame-level two-hand call**. Adapt `Perception.__call__` in `src/spacedrums/app/main.py` to share preprocessing and resolve ownership before emitting either observation. The present per-hand `estimate()` loop cannot resolve both candidates jointly after emission.
3. Convert only fresh, validated caps to the existing `StickObservation`/`EndpointEvidence` measured representation. Preserve normalized ROI coordinates and hand-confidence bounds; absent/uncertain states must carry no measured tip. Keep predicted/prior-only state out of strike-eligible evidence.
4. Add a separate diagnostic record for frame/hand, landmarks/grip, search bounds, edge proposals, axis, observed support/gaps, candidate, cap scores, rejection reason, measurement age and axis age. Reset per-hand diagnostics on every call to prevent stale debug objects. Avoid changing downstream strike/audio contracts simply to expose debug data.
5. Port the evidence renderer into the developer endpoint view (`src/spacedrums/ui/developer_demo.py` or a dedicated endpoint-review overlay) and extend `scripts/check_developer_endpoints.py` to save those diagnostics with lossless buffered frames. Keep the endpoint check disconnected from strike/audio execution.
6. Add real recorded regression cases for 342/640, crossing ambiguity, hand-ID discontinuity, partial occlusion and exiting the frame. Re-run cost and quality checks before choosing a default. The existing production estimator remains the default today.

Reproduce from `C:\Users\jo\Desktop\air_drum_project` with the existing `.venv`:

```powershell
.venv/Scripts/python.exe scripts/review_developer_endpoints.py --prepare
.venv/Scripts/python.exe scripts/review_developer_endpoints.py
.venv/Scripts/python.exe scripts/score_endpoint_review.py
.venv/Scripts/python.exe scripts/benchmark_endpoint_review.py --repeats 3
.venv/Scripts/python.exe -m pytest tests/scripts/test_endpoint_review.py tests/stick/test_visible_endpoint.py -q
```

The scorer requires the supplied `manual-labels.json` in the output directory; it does not generate human/visual truth from predictions. The scripts use the existing experiment paths by default and expose `--source`/`--output` for another developer capture.

**Validation:** 16 tests passed, including the existing visible-endpoint tests; Ruff check passed for all added Python files. Replayed final decisions after the final causal input guard/diagnostic additions. Benchmarking preceded those negligible guard/formatting changes, explicitly recorded in provenance. No hardware tests ran.

## 11. Exact next physical test — proposed only

After the offline gates and endpoint budget pass, run one **24-second endpoint-only developer check**, DSHOW, 640 × 480, requested 30 FPS, developer exposure −5. Ordinary wooden sticks, no markers. Keep the existing layout/calibration and disable all strike decisions and audio. Save processed full frames losslessly after camera shutdown, plus timestamps, dropped-frame counts, hand identities, detailed endpoint evidence and stage timings.

Six four-second cues:

1. 0–4 s: hold both sticks upright and still, with visible tips.
2. 4–8 s: slowly rotate both through diagonal toward horizontal, keeping hands separated.
3. 8–12 s: slowly move LEFT while holding RIGHT still.
4. 12–16 s: slowly move RIGHT while holding LEFT still.
5. 16–20 s: slowly cross and uncross the shafts once with both hands visible.
6. 20–24 s: briefly occlude one distal tip, then move that tip out of the frame and back; hold the other stick still.

There are no strikes in these cues. Stop on an accepted sleeve/background/shaft-fragment point, swapped/shared ownership, or a measured tip persisting through disappearance. Review actual endpoint correctness, not green-dot count, before scheduling any five-hit/audio demonstration. **This test has not run and is not yet recommended for immediate execution.**

## 12. Remaining uncertainty

- Only one person, room, lighting setup, camera profile and pair of sticks are represented. Different stick finishes, backgrounds, distances and foreshortening are untested.
- Most accepted outputs in the full 608-frame comparison are unlabelled. The 30-tip subset is small, correlated and used during development; enlarged crops improve annotation but do not make it independent ground truth.
- Longest acceptance runs are not equivalent to longest accurately measured runs. Multi-second simultaneous accuracy remains unproved.
- Crossing and occlusion handling remains conservative and incomplete. The wrist-direction gate can reject legitimate grips; a hand-ID swap can survive an endpoint estimator that trusts the saved label. The prototype guards shared shafts but does not solve anatomical identity tracking.
- A contrast transition can still be caused by sleeve/background texture or a change in appearance. The new cap tests reduce the observed errors; they do not establish universal physical-tip correctness.
- JPEG replay differs from the original pixels and loses the pre-recording temporal prefix. No full pipeline latency, display responsiveness, new live FPS, strike detection or audio success was measured.

**Recommended disposition:** keep the improved cap evidence and diagnostic harness; continue offline work on coverage, crossing association and compute. The evidence supports an implementation direction, not a live-strike readiness claim.
