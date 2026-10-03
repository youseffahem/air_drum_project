# Live responsiveness on HW-01: tracking loss, frame drops and missed strikes

**Status: DIAGNOSED.**
- **One fix adopted:** a one-slot capture queue.
- **Owner decisions (2026-10-02):** contrast-adaptive stick edges not adopted; axis carry-over, presence
  threshold and identity changes not adopted.
- **Exposure:** kept at −6. R-EXPOSURE failed, and the owner live check (below) did not confirm −5.
- **Follow-up (2026-10-03):** missed and false strikes are characterised separately in
  `docs/perf/strike-reliability.md`; nothing was adopted there.

All values are development measurements on HW-01 (i7-7820HQ, CPU only), on an uncommitted tree: HEAD
`064cda5`, plus the uncommitted mirror fix and this work. Developer recordings only; no participant data;
not MEASURED gate or thesis evidence. Evidence (git-ignored, local):
`experiments/pre-participant/20261002-responsiveness/`. Decision: ADR-0044.

## Question and answer

When the owner drums, the live app often seems to stop responding. T1 and T2 showed that neither the
mirror nor the display is the cause. This record finds where responsiveness is lost.

1. **The hand landmarker loses a hand. This is the main cause.** At 30 FPS, 76–94 % of tracking losses
   start with the hand not detected (`HAND_NOT_DETECTED`). At the live config's exposure −6, the
   owner's room image is about half as bright as at −5: the ROI mean grey level is ≈ 40 against ≈ 78.
   Both hands are then detected in only 13 % of frames, and a hand track is VALID 17 % of the time.
2. **A lost hand also slows every frame.** MediaPipe re-runs palm detection whenever fewer than two
   hands are tracked. A frame takes p50 ≈ 24–29 ms after a frame with two tracked hands, and 37–52 ms
   after one with fewer. The budget is 33.3 ms. So tracking loss and frame drops share one cause.
3. **The stick axis is not found, so strikes are discarded.** Without an axis, GEOM caps the tip
   confidence at 0.4 × handedness, which is below `c_valid` 0.6, so the frame is DEGRADED and commits
   are refused (ADR-0039). In the owner sessions 45 % of observed zone entries were discarded this way
   (188/416), and 70 % of those discards were stick-axis failures. This is the "I hit and nothing
   sounds" symptom.
4. **The capture queue delivered stale frames.** With two slots and first-in-first-out delivery, a
   newer frame was already waiting at 93 % of deliveries. Processing then started on frames 49 ms old
   (p50; p95 65 ms). This adds latency; it does not by itself lose tracks.

No evidence implicates the mirror, the display (0.6 ms p50), rendering (2.2 ms), tracking, geometry,
commit or audio scheduling (each < 1 ms p50).

## Method

`scripts/diagnose_responsiveness.py` runs the real `app.main.run` loop under a probe. The probe writes
one row per delivered frame, with:
- stage times;
- queue depth and frame age;
- hands, identity, stick analysis and tracker state;
- the reset cause (`app.loss_diagnosis`, the same classifier the app now reports);
- candidates, commit gate decisions, commits and audio events.

The tool has two modes:

- **Replay** keeps the recorded timestamps, so decisions are deterministic. Replaying the four owner
  sessions reproduces the recorded tracker states (all 14,504 hand-frames) and the sounding arm's commit
  lists exactly. The shadow arm B differs, because its anticipation gates depend on `t_now`.
- **Paced** pushes the pre-decoded recorded frames through the live capture thread and queue
  (`LiveFrameSource`) at their recorded intervals, in real time. Compute, queue drops and `t_now` are
  real. Runs are repeated three times, serially, with nothing else running, and with headless render
  (the overlay and the mirror are drawn; the display call is stubbed). One extra run used a real
  window.

| Inputs | Frames | Condition |
|---|---:|---|
| `dist-d080-L2-exp-6`, `-exp-6-t2`, `swing-L2-exp-6` (D6) | 1,058 | 30 FPS, exposure −6 (live config), sticks held / swings |
| `dist-d080-L2-exp-5`, `-t2`, `-t3`, `swing-L2-exp-5` (B5) | 1,502 | 30 FPS, exposure −5 |
| 4 owner sessions of 2026-09-28 (S11) | 7,252 | owner playing scripted segments, ≈ 11 FPS record mode, exposure −5 |

`swing-L2-exp-7` (exposure −7) is reported only: no hand is detected at all. Every candidate rule was
written and hashed (`predeclaration.md`, sha256 `36145abc…`) before its first run.

## Results

### Part 1: what the user experiences (frame categories, % of hand-frames)

A = no hand · B = hand, no stick · C = stick, but track not VALID · D = VALID, no zone entry ·
E = zone entry not committed · F = committed.

| Group | A | B | C | D | E | F |
|---|---:|---:|---:|---:|---:|---:|
| D6 replay (−6) | 59.7 | 0.0 | 22.9 | 16.4 | 0.2 | 0.9 |
| B5 replay (−5) | 23.6 | 0.0 | 23.2 | 51.8 | 0.2 | 1.2 |
| S11 replay (owner playing) | 33.9 | 0.1 | 31.7 | 31.5 | 1.3 | 1.6 |

The perceived "stopping" is mostly categories A (no hand) and C (no usable stick). Category E in the
owner sessions is half of all observed entries: 188 of 416 discarded, almost all for track status.

### Part 2: stage times

Paced live path, 21 runs, 6,106 frames, before the fix. Times in ms.

| Stage | p50 | p90 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|
| capture: wait for the next frame | 0.03 | 0.05 | 0.06 | 0.08 | 384 (start-up) |
| hands pre/post-processing (BGR→RGB, coordinates, records) | 0.37 | 0.50 | 0.58 | 0.75 | 2.3 |
| **MediaPipe hand landmarker call** | **37.3** | **44.8** | **50.8** | **63.2** | **91.6** |
| identity / handedness assignment | 0.07 | 0.12 | 0.14 | 0.21 | 0.5 |
| grip reference (hands + stick) | 0.10 | 0.18 | 0.23 | 0.35 | 1.3 |
| stick search region | 0.21 | 0.36 | 0.43 | 0.58 | 1.2 |
| stick segmentation (blur, Canny, closing, components) | 0.97 | 1.76 | 2.03 | 2.66 | 4.0 |
| stick axis fit (RANSAC) | 1.34 | 3.52 | 4.04 | 5.90 | 9.6 |
| stick tip estimation | 0.04 | 0.08 | 0.10 | 0.14 | 0.3 |
| tracker (trajectory update) | 0.17 | 0.28 | 0.35 | 0.50 | 0.9 |
| geometry / strike detection | 0.09 | 0.18 | 0.22 | 0.33 | 1.0 |
| rule anticipator (arm B, shadow) | 0.05 | 0.09 | 0.11 | 0.16 | 0.4 |
| decision logic (commit policy) | 0.04 | 0.06 | 0.09 | 0.13 | 0.3 |
| audio scheduling | 0.00 | 0.00 | 0.00 | 0.01 | 0.04 |
| rendering (overlay + mirror) | 2.26 | 3.12 | 3.58 | 4.92 | 65 |
| display (`imshow` + `pollKey`, one real-window run) | 0.57 | 0.84 | 1.01 | 1.75 | 16.7 |
| **processing (perception → decision)** | **39.7** | **48.9** | **54.6** | **67.9** | **95.5** |
| **loop interval** | **42.9** | **52.6** | **58.5** | **72.8** | **161** |

Against the 33.33 ms budget, processing exceeded 33.33 ms in 62.7 % of frames, 40 ms in 48.7 % and
50 ms in 8.7 %. MediaPipe is 94 % of the processing time.

### Part 3: why tracks are lost

`LossCause` is attributed to the frames since the last VALID frame. The per-episode table counts the
first reset of each loss.

| Group | Losses | Hand not detected | Stick (no axis or low axis confidence) | Identity (label / ambiguous / continuity) | Frame gap (drops) | Hand left ROI |
|---|---:|---:|---:|---:|---:|---:|
| D6 replay (−6) | 46 | **93.5 %** | 6.5 % | 0 | 0 | 0 |
| B5 replay (−5) | 27 | **77.8 %** | 11.1 % | 11.1 % | 0 | 0 |
| Paced, before | 200 | **80.5 %** | 11.5 % | 7.0 % | 0 | 1.0 % |
| S11 replay (≈ 11 FPS) | 444 | **43.7 %** | 31.3 % | 10.8 % | 11.5 % | 2.7 % |

- **Reset rules (S11):** STALE 362, GAP_EXCEEDED 151, LOW_CONFIDENCE 31.
- **The STALE resets:** sticks seen for more than 0.5 s with tip confidence in [0.3, 0.6). That is a
  stick-axis problem, not a hand problem.
- **No "unknown" bucket was needed.** Blur, fast movement and occlusion cannot be separated without
  ground truth, so they are not causes here; Part 5 stratifies by speed instead.

### Part 4: MediaPipe

- **One call, whole pipeline blocked:** a single synchronous `detect_for_video` per frame on the ROI
  (VIDEO mode, two hands, float16 model) blocks the loop for 94 % of the processing time.
- **Cost depends on hands tracked in the previous frame:**

  | Group | 0 hands: n, p50, p95 | 1 hand: n, p50, p95 | 2 hands: n, p50, p95 |
  |---|---|---|---|
  | D6 replay | 341, 41.8, 62.1 | 580, 44.4, 64.2 | 134, 28.6, 39.4 |
  | B5 replay | 28, 52.4, 68.7 | 652, 46.5, 72.2 | 818, 27.2, 40.1 |
  | Paced, before | 834, 39.0, 55.8 | 2,708, 39.1, 54.0 | 2,543, 24.2, 35.4 |

  With fewer than two hands, the graph runs palm detection every frame. This is inferred from the
  timing signature, which matches the documented MediaPipe behaviour.
- **The call is latency-bound, not CPU-saturated:** the process used ≈ 35–48 % of one core during
  paced runs (≈ 38 % in a pure landmarker loop).
- **Timer quantisation was checked and excluded:** the system timer resolution was already 1.0 ms, and
  forcing it changed nothing (p50 23.8 vs 23.8 ms).
- **Model configuration:** VIDEO mode and both-hand tracking are appropriate, and Phase 16 already
  rejected IMAGE mode and half-resolution input. Presence threshold variants 0.4 and 0.3 were tested
  (report-only, below); they did not help.

### Part 5: stick tracking

Axis found, as % of frames with a stick, by wrist-speed tercile:

| Group | slow | normal | fast | Dominant failure |
|---|---:|---:|---:|---|
| B5 (−5) | 89.1 | 85.0 | 63.3 | axis fit rejected (fast), elongation / orientation |
| D6 (−6) | 50.9 | 52.6 | 44.3 | components rejected (elongation, orientation): low contrast |
| S11 (owner playing, −5) | 66.8 | 63.9 | 59.9 | components rejected for orientation |

- **The detector itself fails, not the frame rate.** The axis rate falls with speed at −5 (motion
  blur) and is low at every speed at −6 (darkness).
- **Contrast is the measurable mechanism in the dark:** the search region's grey span is median 51 at
  −6 against 77 at −5.
- **Contrast-adaptive Canny thresholds** raised −6 axis-found from 49 to 84 % (R-STICK, below).

### Part 6: capture queue

- **Settings:** queue `max_frames` 2, drop-oldest when full; the consumer took the oldest queued frame.
- **Measured before the fix (paced):** a newer frame was already waiting at 92.8 % of deliveries.
  Frame age at processing start was p50 48.6 ms, p95 64.6 ms.
- **The fix:** `max_frames` 1, a value the schema already allows. The consumer always takes the newest
  frame. Drops are counted as before, and every delivered frame keeps its own capture timestamp.

### Part 7: recovery

- Thresholds were not changed: `c_valid` 0.6, `c_min` 0.3, `g_max_frames` 3, `age_max_s` 0.5,
  re-acquisition at VALID level only (ADR-0041).
- **Loss mechanics:**
  - A hand missed for four or more frames ends the track (GAP_EXCEEDED).
  - A stick seen only at DEGRADED confidence for more than 0.5 s ends it (STALE). It then cannot be
    re-acquired until one frame reaches VALID.
  - Unresponsive stretches longer than 0.5 s with the hand visible: 9.9 /min (paced), and up to 3.5 s.
- **What would reduce resets:** better observations, not looser thresholds. Hand presence explains
  most losses.

### Part 8: strikes around short gaps

- **Current behaviour, now covered by tests (`tests/app/test_gap_strike_causality.py`):**
  - a VALID crossing after up to three dropped frames commits;
  - nothing commits on bridged or DEGRADED frames;
  - an entry seen only on a DEGRADED frame is not committed later.
- **Offline check of a VALID-anchored rule:** would a crossing between the last VALID position before
  the discarded entry and the next VALID position after it (each ≤ 3 frames away, no reset between)
  rescue the strike? Only 14 of 188 discarded owner-session entries (7 %) qualify. Not proposed.

### Part 9: scheduling

- The loop is sequential: capture thread → queue → perception → decision → render → display.
- Only MediaPipe is expensive, and its cost depends on how many hands are tracked.
- **Not done:**
  - running two frames through MediaPipe at once (it would break VIDEO-mode tracking);
  - threading (excluded by the T2 owner rule after the no-window test failed);
  - throttling hand detection (it would lose causal per-frame observations).
- **Smaller stages:** none exceeded 2 ms p95 except the RANSAC axis fit (4.0 ms). Its cost is
  data-dependent, and output-identical savings would be small. Not changed.

## Pre-declared rules and outcomes

| Rule | Outcome | Key numbers |
|---|---|---|
| **R-QUEUE:** `max_frames` 2 → 1 | **PASS → adopted** in `configs/prototype.candidate.yaml` | Age p50 48.9 → 15.3 ms; late deliveries 93 → 0 %; VALID 41.0 → 40.4 %; resets 64.4 → 64.7 /min; commits 139 → 144 |
| **R-STICK:** contrast-adaptive Canny (target 77, gain 2 or 3) | **FAIL** on criterion 5 only → **not enabled** (option implemented, default off) | −6 axis-found 49 → 84 %; −6 VALID 17 → 30 %; S11 discarded 45.2 → 43.6 %; tip shift median 0 px; **no-strike commits 59 → 64** |
| **R-EXPOSURE:** −6 → −5 | **FAIL** on criteria 4 (+0.03 ms p95) and 6 (one queue drop in a 6 s capture) → **kept at −6** | Both-hands presence 55 vs 13 %; VALID 53 vs 17 %; resets 40 vs 116 /min; fast-stroke axis 90 vs 61 % |

R-STICK's extra commits are mostly held sticks hovering at the tom1 boundary in the distance captures.
That source already gives 53 commits in the baseline with no strike instructed, and it exists
independently of this change.

The R-EXPOSURE failures are artefacts of the criteria's wording. A labelled post-hoc check on the
controlled paced runs gives, at −5 against −6:
- hand model p50 28.1 vs 38.6 ms and p95 47.8 vs 54.0 ms;
- drops 18.0 vs 24.0 %.

The −6 swing capture also has one queue drop.

**Proposed to the owner:** exposure −5 for the L2 lighting, and the stick option at (77, 2). Each would
be an explicit engineering deviation from its pre-declared rule.

## Before and after (adopted change only)

Paced live path, the same 7 captures × 3 repeats; only `queue.max_frames` differs.

| Measure | Before (2) | After (1) |
|---|---:|---:|
| Delivered FPS (pooled) | 24.0 | 24.6 |
| Dropped / offered frames | 20.5 % | 18.4 % |
| Frame age at processing start, p50 / p95 | 48.6 / 64.6 ms | 14.6 / 31.1 ms |
| Processing p50 / p95 | 39.7 / 54.6 ms | 37.5 / 54.7 ms |
| Re-acquisitions per minute | 51.9 | 50.8 |
| VALID hand-frames | 41.0 % | 40.4 % |
| Zone entries / discarded | 175 / 36 | 184 / 40 |
| Commits (sounding arm) | 139 | 144 |
| Invariant violations | 0 | 0 |

Replay decisions are unchanged by construction: the stick option is off and the exposure is a
capture-time property. The paced reproduction is harsher than the T2 live runs (20 % against 4.5–9 %
drops), because it uses recorded content with fewer tracked hands. Its absolute numbers are therefore
not live numbers.

## Report-only candidates (not adopted)

| Candidate | Owner sessions: discarded / commits | No-strike commits | Identity jumps (S11) | Verdict |
|---|---|---:|---:|---|
| Baseline | 45.2 % / 228 | 59 | 85 | — |
| Identity gate scaled by elapsed frames | 41.5 % / 257 | 57 | **97** | Mixed: more strikes, more possible swaps |
| `min_hand_presence_confidence` 0.4 | 46.2 % / 232 | 64 | 84 | More hands, more identity events, more resets at −6 |
| `min_hand_presence_confidence` 0.3 | 48.3 % / 229 | 68 | 82 | Worse |

## Scope limits

- **No 30 FPS recording of the owner drumming exists.** The 30 FPS evidence is distance and swing
  captures; the playing evidence is ≈ 11 FPS record-mode sessions. No ground truth exists, so no
  claim of accuracy or of a false-positive rate.
- **Lighting:** the lighting of the T2 runs was not recorded, so the exposure finding is scoped to the
  L2 captures.
- **Paced capture:** the paced camera does no colour conversion in the capture thread.
- **Owner live check:** n = 1 run per exposure (below).

## Owner live check, −6 vs −5 (2026-10-02)

- **Setup:** two 60 s runs by the owner at the real lighting, one directly after the other, with the
  same position, sticks and on-screen protocol (`harness/live_check.py`). Segments: hold still,
  snare singles, across zones, fast snare, fake swings.
- **App:** the unchanged live app (queue 1, stick option off, uncalibrated, window with mirror,
  audio on). No frames were recorded.
- **Exposure:** −5 came from a temporary override; `configs/prototype.candidate.yaml` stayed at −6.
- **Criterion:** fixed and hashed before the runs (`live-check-addendum.md`, sha256 `ab8ec0d9…`).
- **Results:** `live/minus6/`, `live/minus5/` and `live-comparison.json`.

| # | Measure | −6 | −5 |
|---|---|---:|---:|
| 1 | Hand presence, both / L / R | 0.58 / 0.67 / 0.70 | 0.51 / 0.87 / 0.54 |
| 2 | Reliable tracking (VALID or DEGRADED, % hand-frames) | 64.3 | 74.3 |
| 3 | Re-acquisitions / min | 53.3 | 42.2 |
| 4 | MediaPipe p50 / p95 (ms) | 28.04 / 46.10 | 28.12 / 44.41 |
| 5 | FPS delivered | 23.90 | 24.28 |
| 6 | Dropped frames | 20.8 % | 19.5 % |
| 7 | Stick axis found | 65.8 % | 80.1 % |
| 8 | VALID (% hand-frames) | 34.6 | 48.3 |
| 9 | Discarded zone entries (n / entries) | 10 / 46 (21.7 %) | 27 / 92 (29.4 %) |
| 10 | Committed strikes | 36 | 65 |
| 11 | No-strike-segment commits (hold still + fake swings) | 14 | 24 |
| 12 | Stretches > 0.5 s with hand visible (n; longest) | 25; 3.5 s | 6; 1.8 s |
| | ROI grey p50 (lighting) / exposure read back | 55 / −6 | 103 / −5 |
| | Processing p50 / p95 (ms) | 33.9 / 52.8 | 33.2 / 51.1 |
| | Frame age at processing start p50 (ms) | 13.3 | 14.1 |
| | Invariant violations | 0 | 0 |

**Direction not confirmed → −6 kept.**

- **Primary criteria (all five needed):**
  - both-hands presence was lower at −5 (0.51 vs 0.58);
  - MediaPipe p50 was not lower (28.12 vs 28.04 ms);
  - VALID, re-acquisitions and drops favoured −5.
- **Guards:**
  - axis-found passed;
  - no-strike commits rose by 10 (24 vs 14), beyond the +2 guard.

**Interpretation:**
- At the owner's real lighting the −6 image was brighter than in the 2026-09-28 captures (ROI grey 55
  vs ≈ 41). The hand-model cost was already about 28 ms at −6, so the replay's palm-detection gap did
  not appear live.
- The −5 run tracked sticks better and produced more commits in every segment, including the
  no-strike ones. More false positives at −5 is a real risk this check cannot rule out.
- The right hand's lower presence at −5 came with 14 hand-left-ROI resets that the −6 run did not
  have, which suggests a difference in position or playing between the runs. With n = 1 per exposure
  this check cannot separate exposure from that drift.
- **No deviation is adopted.** R-EXPOSURE stays recorded as failed.
