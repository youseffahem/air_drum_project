# Strike reliability on HW-01: missed strikes and false strikes

**Status: CHARACTERISED. Nothing adopted.**
- **Missed strikes (A):** characterised. The four pre-declared perception candidates all failed.
- **False strikes (B):** characterised. The 31 pre-declared decision-only candidates all failed.
- **No production code or config changed.** Owner decisions are listed at the end.
- **Phase 18 remains BLOCKED.**

All values are development measurements on HW-01 (i7-7820HQ, CPU only), on an uncommitted tree: HEAD
`064cda5` plus the uncommitted mirror fix and the 2026-10-02 responsiveness work. The evidence is developer
replay evidence, paced replay evidence and the rows of the 2026-10-02 owner live check. It contains no
participant data, no ground truth and no accuracy claim.

Evidence (git-ignored, local): `experiments/pre-participant/20261002-strike-reliability/`. The
pre-declaration is `predeclaration.md`, sha256 `2672b58a…`, hashed 2026-10-03 00:23 +03:00, after Stages
0–3 and before any candidate run. Follows `docs/perf/live-responsiveness.md` (ADR-0044).

## 1. Conclusions

**What causes missed strikes.**
- **The rejecting gate is the commit status gate (C1).** It rejected every discarded zone entry: 188/188 in
  the four owner sessions (S11) and 10/10 in the live −6 check. Commit logic, timing and geometry rejected
  none; the only exceptions are 4 refractory rejections at −5.
- **The entry frame's stick tip was below `c_valid`:**
  - 48 % had no stick axis, so the tip was placed at the prior length along the grip direction;
  - 33 % had an axis but low confidence;
  - 19 % were bridged predictions while the hand was not detected.
- **The perception causes, as shares of S11 discarded entries:** stick components rejected for
  elongation 22 % and orientation 20 %, hand not detected 16 %, tip or axis low confidence 22 %, identity
  14 %, axis fit 6 %.
- **Upstream, tracks are lost mainly through the hand landmarker:** HAND_NOT_DETECTED is 49 % of S11
  resets, 96 % of D6 resets and 49 % of live −6 resets.
- **GRIP_DEGENERATE (knuckle row edge-on, no direction prior) appears only in the live −6 run:** 33 % of
  its resets, but only 10 of 12,700 replayable hand-frames.
- **Frame age and ROI clipping are not material:**
  - frame age at processing start is p50 13–16 ms, with queue depth always 1;
  - the search region is clipped in 20 of 386 S11 entries;
  - HAND_LEFT_ROI is 0 % of live −6 resets.

**What causes false strikes.**
- **Tom 1 is 93 % of them:** 55 of the 59 no-strike commits (RIGHT 41, LEFT 14); snare 3, crash 1.
- **The mechanism is the stick-tip estimate jumping across tom1's boundary, not hover or jitter.**
  - The tip enters from the side of the upper arc (LATERAL_ENTRY 81 %).
  - The wrist moves a median of 3 px while the tip moves 53 px.
  - In 38 of 43 measurable cases (88 %) the tip angle jumps by about 27° and reverts on the next frame.
    This is offline diagnosis using the next frame.
  - 26 of 59 (44 %) cross from a previous point that was not a VALID observation: no-axis prior 14,
    bridged 10, DEGRADED axis 2.
  - Hover and jitter are rare: SHALLOW_HOVER 3, JITTER_REENTRY 6.
- **Tom1's default position (y 0.30–0.46) is where held sticks rest:** up to 42 % of the live hand-frames
  of a held-stick capture are inside tom1. It is also directly above the snare in the stroke path.
- **The 14 live −6 no-strike commits are different:**
  - 12 of 14 are continuing motion, not flicker;
  - 5 look like deliberate, deep strokes;
  - they are spread over LEFT:tom1 5, RIGHT:snare 4, LEFT:hihat 3, LEFT:snare 2.
  - They are fake swings that physically entered the virtual zones, which is a layout and feedback problem.

**What remains unresolved.**
- **No decision-only rule separates false commits from real-looking ones.** Every rule that removes at
  least 50 % of the no-strike commits also removes at least 15 % of the real-looking strike commits.
- **Every perception change that finds more sticks raises the no-strike commits.**
  - The four A candidates here: 59 → 67–73.
  - The contrast option on 2026-10-02: 59 → 64.
  - Missed and false strikes are coupled through the stick-tip estimate.
- **Zone assignment is poor in the existing evidence:**
  - 29 of 94 (31 %) instructed-segment commits hit the instructed zone in the playability session;
  - 0 of 22 did in the live −6 strike segments, against 32 of 41 at −5;
  - live sessions run on the uncalibrated default layout.

## 2. Method

1. **Stage 0:** snapshot taken; the 2026-10-02 evidence verified against its manifest (525/525).
2. **Stage 1:** fresh deterministic replays of all 12 inputs on the current tree (`replay/baseline2`).
   - They are identical to the 2026-10-02 baseline on every decision field.
   - The probe gained two diagnostic row fields, `region_clip` and `grip_baseline` (`scripts/_resp.py`).
   - Paced replay, 7 captures × 3 repeats (`paced/baseline-current`).
3. **Stage 2:** characterisation scripts `harness/analyse_a.py`, `analyse_b.py` and `bbox_check.py`.
   - The B mechanism labels were defined in the script before it ran.
4. **Stage 3:** `harness/resim.py` re-runs arm A's geometry and commit policy from the rows with the
   production classes. It reproduces 100 % of the recorded arm-A candidates, decisions and commits:
   - on all 12 replay inputs (481 / 481 / 283);
   - on both live-check runs (138 / 138 / 101);
   - with the production `GeometryEngine` and with the null-rule wrapper.
   It is prefix-invariant. This lets decision-only candidates be tested on identical inputs, including the
   live rows, which have no frames.
5. **Stage 4:** the pre-declaration was hashed. The B grids were fixed in `harness/rule_b.py` before
   Stage 2 ran.
6. **Stage 5:**
   - `harness/rule_b.py` evaluated 31 decision-only candidates, plus next-frame confirmation as a diagnostic.
   - `harness/rule_a.py` evaluated 4 perception candidates by full replay.

Evaluation sets:

| Set | Contents |
|---|---|
| **NS (no strike)** | 5 held-stick distance captures, playability `move_between_zones`, `fake_swings`, `stop_before_impact` |
| **RS (real-looking strikes)** | 13 playability strike segments, swing −5/−6, induced-loss, diag-record, calib-run1 |
| **ZC** | instructed-zone RS segments |
| **SYN** | Phase 11 SYNTHETIC kinematic fixture |
| **LIVE** | owner live check rows; report-only |

## 3. Missed strikes (A)

### 3.1 Complete discarded-entry table (aggregated; the 235 entries are in `analysis/discarded-entry-table.csv`)

| A1 class (entry frame) | S11 | D6 | B5 | LIVE6 | LIVE5 |
|---|---|---|---|---|---|
| component rejected: elongation | 41 (22 %) | 1 (25 %) | – | – | 8 (30 %) |
| component rejected: orientation | 37 (20 %) | 1 (25 %) | 1 (17 %) | 1 (10 %) | 3 (11 %) |
| hand not detected (bridged position) | 30 (16 %) | 1 (25 %) | 2 (33 %) | 2 (20 %) | 3 (11 %) |
| tip low confidence | 26 (14 %) | – | – | 2 (20 %) | 1 (4 %) |
| axis low confidence | 15 (8 %) | – | – | 4 (40 %) | 7 (26 %) |
| axis fit rejected | 11 (6 %) | 1 (25 %) | – | 1 (10 %) | – |
| identity: low handedness label | 12 (6 %) | – | – | – | – |
| identity: low wrist continuity | 9 (5 %) | – | – | – | 1 (4 %) |
| identity ambiguity | 5 (3 %) | – | – | – | 1 (4 %) |
| decision logic: REJECT_REFRACTORY_ZONE | – | – | 2 (33 %) | – | 2 (7 %) |
| component rejected: size | 1 (1 %) | – | 1 (17 %) | – | – |
| no edges | 1 (1 %) | – | – | – | – |
| hand left ROI (bridged position) | – | – | – | – | 1 (4 %) |
| **discarded / entries** | 188 / 416 (45.2 %) | 4 / 22 (18.2 %) | 6 / 43 (14.0 %) | 10 / 46 (21.7 %) | 27 / 92 (29.3 %) |
| rejecting gate | status (perception) 188 | status (perception) 4 | status (perception) 4, decision logic (REJECT_REFRACTORY_ZONE) 2 | status (perception) 10 | status (perception) 25, decision logic (REJECT_REFRACTORY_ZONE) 2 |
| entry-frame tip source | DEGRADED_PRIOR 90, DEGRADED_AXIS 62, BRIDGED 36 | DEGRADED_PRIOR 3, BRIDGED 1 | VALID_AXIS 2, DEGRADED_PRIOR 2, BRIDGED 2 | DEGRADED_AXIS 6, DEGRADED_PRIOR 2, BRIDGED 2 | DEGRADED_PRIOR 11, DEGRADED_AXIS 10, BRIDGED 4, VALID_AXIS 2 |
| observed (axis) / needs invented state | 62 / 126 | 0 / 4 | 2 / 4 | 6 / 4 | 12 / 15 |

What each discarded entry passed on its entry frame:

| discarded entries: check passed on the entry frame | S11 | D6 | B5 | LIVE6 | LIVE5 |
|---|---|---|---|---|---|
| hand_present | 158 | 3 | 4 | 8 | 23 |
| handedness_ge_c_valid | 132 | 3 | 4 | 8 | 21 |
| stick_record | 158 | 3 | 4 | 8 | 23 |
| axis_found | 62 | 0 | 2 | 6 | 12 |
| tip_conf_ge_c_valid | 0 | 0 | 2 | 0 | 2 |
| geometry_inside_zone | 188 | 4 | 6 | 10 | 27 |
| candidate | 188 | 4 | 6 | 10 | 27 |

**Reading the trace.**
- Every discarded entry was geometrically inside the zone and had a candidate.
- None had a VALID-level tip confidence, except refractory cases.
- The rejection is perception (status), never commit logic.
- Of the 41 S11 AXIS_LOW_CONFIDENCE entries:
  - 26 would reach `c_valid` with a handedness of 1.0. The fused identity score (owner-closed) is the joint
    limit;
  - 15 have `axis_conf` below 0.2.

### 3.2 Can the missed entries be recovered causally? (A2)

- **Axis observed on the entry frame:** 62 of 188 S11 discarded entries (33 %); live −6: 6 of 10. The
  crossing was observed but below `c_valid`. Committing these would relax the status gate (ADR-0039), so
  they are quantified only, never proposed.
- **Would need an invented state:** 126 of 188 (67 %): a no-axis prior tip or a bridged prediction. Not
  recoverable without invention.
- **VALID-to-VALID crossing around the discarded frame** (≤ 3 frames each side, no reset; the 2026-10-02
  rule, re-run): 14 of 188 S11 (7.4 %); live −6 3 of 10; live −5 9 of 25. It commits at a later frame
  across an unobserved entry frame, so it stays report-only.
- **Non-VALID episodes, S11:**
  - 1,460 episodes, median 3 frames, p90 12 frames (1.2 s);
  - 649 had a stick axis observed inside the gap;
  - 179 contained a discarded candidate;
  - recovery comes a median of 1 frame after the last axis-observed frame, so it is not late;
  - 574 were longer than `g_max_frames`.

### 3.3 Correlates

- **Wrist speed:** discard rates rise mildly with speed: S11 slow 35 %, normal 38 %, fast 39 %.
- **Brightness:** S11 (−5, ROI grey ≥ 60) shows no trend; live −6 (grey 45–60) discards 19 %.
- **Hand:** S11 LEFT 50 % vs RIGHT 43 %; live −6 RIGHT 8 of 13 vs LEFT 2 of 33.
- **Previous point:** entries whose previous point was bridged are discarded most (S11 72 %).

| wrist_speed_tercile: discarded / entries | S11 | LIVE6 | LIVE5 |
|---|---|---|---|
| fast | 44/113 (39 %) | 3/15 (20 %) | 9/27 (33 %) |
| normal | 42/112 (38 %) | 2/14 (14 %) | 7/26 (27 %) |
| slow | 39/113 (35 %) | 3/15 (20 %) | 5/27 (19 %) |
| unknown | 63/78 (81 %) | 2/2 (100 %) | 6/12 (50 %) |

| roi_mean_brightness: discarded / entries | S11 | LIVE6 | LIVE5 |
|---|---|---|---|
| 45-60 | – | 8/42 (19 %) | – |
| 60-75 | 19/49 (39 %) | 2/4 (50 %) | – |
| >=75 | 169/367 (46 %) | – | 27/92 (29 %) |

| hand: discarded / entries | S11 | LIVE6 | LIVE5 |
|---|---|---|---|
| LEFT | 67/133 (50 %) | 2/33 (6 %) | 10/33 (30 %) |
| RIGHT | 121/283 (43 %) | 8/13 (62 %) | 17/59 (29 %) |

| zone: discarded / entries | S11 | LIVE6 | LIVE5 |
|---|---|---|---|
| crash_ride | 18/43 (42 %) | – | 4/7 (57 %) |
| hihat | 16/24 (67 %) | 0/6 (0 %) | 3/10 (30 %) |
| snare | 83/138 (60 %) | 8/25 (32 %) | 10/48 (21 %) |
| tom1 | 71/211 (34 %) | 2/15 (13 %) | 10/27 (37 %) |

| previous_frame_tip_source: discarded / entries | S11 | LIVE6 | LIVE5 |
|---|---|---|---|
| BRIDGED | 55/76 (72 %) | 1/2 (50 %) | 5/13 (38 %) |
| DEGRADED_AXIS | 23/42 (55 %) | 0/3 (0 %) | 7/17 (41 %) |
| DEGRADED_PRIOR | 51/125 (41 %) | 1/4 (25 %) | 4/18 (22 %) |
| VALID_AXIS | 59/173 (34 %) | 8/37 (22 %) | 11/44 (25 %) |

| frame_age_ms: discarded / entries | S11 | LIVE6 | LIVE5 |
|---|---|---|---|
| 15-30 | – | 7/27 (26 %) | 14/36 (39 %) |
| <15 | – | 3/16 (19 %) | 11/49 (22 %) |
| >=30 | – | 0/3 (0 %) | 2/7 (29 %) |
| unknown | 188/416 (45 %) | – | – |

### 3.4 Complete reset-cause table

| reset reason / loss cause | S11 | D6 | B5 | PACED | LIVE6 | LIVE5 |
|---|---|---|---|---|---|---|
| GAP_EXCEEDED / HAND_NOT_DETECTED | 89 (16 %) | 40 (59 %) | 20 (61 %) | 130 (49 %) | 24 (35 %) | 23 (43 %) |
| STALE / HAND_NOT_DETECTED | 155 (28 %) | 24 (35 %) | 6 (18 %) | 73 (27 %) | 9 (13 %) | 8 (15 %) |
| STALE / STICK_REJECTED_ORIENTATION | 69 (13 %) | 2 (3 %) | – | 6 (2 %) | 3 (4 %) | – |
| GAP_EXCEEDED / FRAME_GAP_DROPS | 51 (9 %) | – | – | 12 (4 %) | – | – |
| STALE / IDENTITY_LOW_LABEL | 43 (8 %) | – | 3 (9 %) | 14 (5 %) | – | 1 (2 %) |
| STALE / STICK_REJECTED_ELONGATION | 38 (7 %) | – | – | 2 (1 %) | 5 (7 %) | 2 (4 %) |
| STALE / AXIS_FIT_REJECTED | 23 (4 %) | 1 (1 %) | 3 (9 %) | 13 (5 %) | – | – |
| LOW_CONFIDENCE / HAND_NOT_DETECTED | 22 (4 %) | 1 (1 %) | 1 (3 %) | 7 (3 %) | 1 (1 %) | 2 (4 %) |
| GAP_EXCEEDED / HAND_LEFT_ROI | 10 (2 %) | – | – | 1 (0 %) | – | 10 (19 %) |
| STALE / HAND_LEFT_ROI | 11 (2 %) | – | – | 1 (0 %) | – | 4 (8 %) |
| STALE / IDENTITY_AMBIGUOUS | 11 (2 %) | – | – | 2 (1 %) | 1 (1 %) | 1 (2 %) |
| LOW_CONFIDENCE / IDENTITY_LOW_LABEL | 7 (1 %) | – | – | 2 (1 %) | 2 (3 %) | – |
| STALE / GRIP_DEGENERATE | – | – | – | – | 11 (16 %) | – |
| STALE / AXIS_LOW_CONFIDENCE | 10 (2 %) | – | – | – | 1 (1 %) | – |
| GAP_EXCEEDED / GRIP_DEGENERATE | – | – | – | – | 10 (14 %) | – |
| GAP_EXCEEDED / STICK_REJECTED_ORIENTATION | 1 (0 %) | – | – | 3 (1 %) | – | – |
| LOW_CONFIDENCE / IDENTITY_AMBIGUOUS | 2 (0 %) | – | – | 1 (0 %) | – | – |
| GAP_EXCEEDED / IDENTITY_LOW_LABEL | – | – | – | – | – | 2 (4 %) |
| LOW_CONFIDENCE / GRIP_DEGENERATE | – | – | – | – | 2 (3 %) | – |
| STALE / STICK_NO_EDGES | 2 (0 %) | – | – | – | – | – |
| **total** | 544 | 68 | 33 | 267 | 69 | 53 |

### 3.5 Hand detection and MediaPipe cost (A3)

| run | prev 0 hands: n: p50/p95 | prev 1 hand | prev 2 hands | hand-count dropouts 1/2/longer frames | extra ms after 1-frame dropout p50 | over-budget after <2 hands / all over-budget | GAP_EXCEEDED with hand back <= 3 frames / all | presence L / R / both |
|---|---|---|---|---|---|---|---|---|
| dist-d080-L2-exp-5-r0 | 17: 50.9 / 88.3 | 207: 51.1 / 70.9 | 18: 31.4 / 46.0 | 1 / 3 / 11 | 16.9 | 223 / 236 | 0 / 1 | 0.08 / 0.93 / 0.07 |
| dist-d080-L2-exp-5-t2-r0 | – | 44: 47.8 / 95.9 | 263: 30.1 / 46.4 | 20 / 3 / 2 | 13.7 | 44 / 240 | 2 / 3 | 0.86 / 1.00 / 0.86 |
| dist-d080-L2-exp-5-t3-r0 | 3: 39.3 / 41.1 | 81: 41.6 / 61.0 | 262: 26.1 / 38.3 | 25 / 8 / 7 | 15.1 | 82 / 199 | 6 / 7 | 0.90 / 0.84 / 0.76 |
| dist-d080-L2-exp-6-r0 | 109: 48.5 / 68.7 | 142: 47.3 / 70.1 | 18: 30.9 / 57.5 | 1 / 1 / 7 | 14.7 | 248 / 260 | 3 / 8 | 0.13 / 0.53 / 0.07 |
| dist-d080-L2-exp-6-t2-r0 | 69: 37.2 / 54.9 | 167: 43.7 / 64.7 | 67: 29.3 / 47.7 | 3 / 1 / 13 | 18.5 | 208 / 251 | 10 / 22 | 0.41 / 0.58 / 0.22 |
| swing-L2-exp-5-r0 | 1: 37.3 / 37.3 | 43: 39.6 / 51.0 | 95: 24.5 / 34.5 | 9 / 3 / 6 | 14.6 | 44 / 72 | 5 / 5 | 0.70 / 0.98 / 0.69 |
| swing-L2-exp-6-r0 | 37: 44.9 / 78.2 | 58: 43.9 / 67.2 | 13: 29.6 / 39.2 | 2 / 2 / 3 | 18.8 | 90 / 95 | 1 / 2 | 0.20 / 0.58 / 0.12 |
| live/minus6 | 295: 19.2 / 43.0 | 309: 42.4 / 57.1 | 823: 27.4 / 38.4 | 77 / 16 / 31 | 16.5 | 348 / 766 | 20 / 34 | 0.67 / 0.70 / 0.58 |
| live/minus5 | 136: 20.6 / 40.3 | 574: 34.9 / 48.8 | 740: 25.6 / 34.9 | 60 / 11 / 40 | 16.8 | 399 / 702 | 22 / 35 | 0.87 / 0.54 / 0.51 |
| dist-d080-L2-exp-5 (replay) | 26: 50.1 / 70.1 | 395: 51.8 / 76.3 | 22: 33.4 / 49.1 | 0 / 2 / 18 | – | 420 / 438 | 1 / 4 | 0.07 / 0.93 / 0.05 |
| dist-d080-L2-exp-5-t2 (replay) | – | 82: 53.5 / 71.3 | 360: 31.8 / 44.0 | 29 / 8 / 4 | 21.3 | 82 / 424 | 1 / 2 | 0.81 / 1.00 / 0.81 |
| dist-d080-L2-exp-5-t3 (replay) | 1: 47.6 / 47.6 | 108: 49.2 / 80.3 | 334: 32.2 / 47.8 | 23 / 5 / 12 | 16.5 | 109 / 412 | 6 / 8 | 0.93 / 0.82 / 0.75 |
| dist-d080-L2-exp-6 (replay) | 186: 48.8 / 69.3 | 241: 50.8 / 72.5 | 15: 32.9 / 39.0 | 2 / 0 / 11 | 12.9 | 419 / 431 | 5 / 14 | 0.10 / 0.51 / 0.03 |
| dist-d080-L2-exp-6-t2 (replay) | 96: 52.8 / 77.6 | 259: 59.4 / 100.1 | 88: 43.0 / 75.2 | 4 / 3 / 17 | 19.2 | 349 / 435 | 12 / 24 | 0.35 / 0.64 / 0.20 |
| swing-L2-exp-5 (replay) | 1: 32.2 / 32.2 | 67: 50.6 / 72.8 | 102: 30.4 / 48.6 | 9 / 6 / 7 | 18.2 | 67 / 154 | 2 / 6 | 0.64 / 0.96 / 0.60 |
| swing-L2-exp-6 (replay) | 59: 51.5 / 70.6 | 80: 50.6 / 69.1 | 31: 29.1 / 42.0 | 2 / 1 / 7 | 13.9 | 135 / 155 | 1 / 2 | 0.27 / 0.57 / 0.19 |

- **One tracked hand is the expensive state.**
  - In the live −6 run, MediaPipe takes p50 19.2 / 42.4 / 27.4 ms after 0 / 1 / 2 tracked hands. With
    fewer than two hands the graph re-runs palm detection (inferred from timing).
  - Live −6 had 77 one-frame hand dropouts (2 → 1 → 2), 16 two-frame and 31 longer.
  - Each one-frame dropout costs p50 16.5 ms extra on the next frame.
  - 348 of the 766 over-budget frames (45 %) follow a frame with fewer than two hands.
  - 319 over-budget frames are followed by a queue drop.
- **Not addressable here:** MediaPipe Tasks exposes no control over the palm-detection rerun, and
  hand-presence and model changes are owner-closed. No model experiment was run.
- **GAP_EXCEEDED resets:**
  - 20 of 34 live −6 GAP_EXCEEDED resets had the hand back within 3 frames.
  - `g_max_frames` 3 is an ADR-0041 owner decision and was not reopened.

### 3.6 ROI and camera coverage (A4)

- **HAND_LEFT_ROI resets:**
  - live −6: 0;
  - live −5: 14 of 53, after the owner's position drifted;
  - S11: 21 of 544 (3.9 %).
- **Search-region clipping:**
  - present in 0.3–13 % of stick frames in the owner sessions;
  - present in 20 of 386 S11 entries;
  - not a material cause.
- **Zones near the ROI edge:** crash_ride is 0.041 from the right edge and hi-hat 0.07; tom1 and snare are
  0.22–0.30 away. No boundary fix is proposed.
- **Stale `_last_bbox` check:** expiring the last-seen bbox after 0.5 s relabels 902 hand-absent frames but
  changes **0 of 767** reset and loss causes (`analysis/a4-stale-bbox.json`). The attribution does not
  change, so **no fix** was made.

### 3.7 Frame age (A5)

| Run | Age at processing start p50 / p90 / p95 / p99 (ms) | Queue depth | Newer frame waiting | Capture interval p50 | Age at commit frames p50 | `t_now − t_capture` at commit p50 |
|---|---|---|---|---|---|---|
| Paced, current tree | 16.4 / 29.8 / 31.7 / 41.4 | always 1 | 0 % | 37.5 ms | 16.4 ms | 59.0 ms |
| Owner live check −6 | 13.3 / 28.7 / 30.6 / 36.5 | always 1 | 0 % | 32.5 ms | 20 ms | 55.1 ms |

- **Commit latency is processing, not queue staleness.** The candidate-frame age (p50 17.0–20.2 ms) is no
  different from all frames, so frame age does not contribute to missed strikes.
- **The queue policy was not changed.**

## 4. False strikes (B)

### 4.1 Zone distribution (complete; Tom 1 is not assumed)

| hand:zone | NS | RS | LIVE-NS:minus6 | LIVE-RS:minus6 | LIVE-NS:minus5 | LIVE-RS:minus5 |
|---|---|---|---|---|---|---|
| LEFT:crash_ride | 1 | 9 | – | – | – | 3 |
| LEFT:hihat | – | 6 | 3 | 3 | 4 | – |
| LEFT:snare | – | 20 | 2 | 10 | – | 7 |
| LEFT:tom1 | 14 | 31 | 5 | 8 | 9 | – |
| RIGHT:crash_ride | – | 15 | – | – | – | – |
| RIGHT:hihat | – | 2 | – | – | – | 3 |
| RIGHT:snare | 3 | 34 | 4 | 1 | 8 | 23 |
| RIGHT:tom1 | 41 | 107 | – | – | 3 | 5 |
| **total** | 59 | 224 | 14 | 22 | 24 | 41 |

The live −6 strike segments committed no instructed zone (0 of 22):
- `fast_snare` → LEFT:tom1 8, LEFT:hihat 3;
- `across_zones` → LEFT:snare 10, RIGHT:snare 1.

Live −5 hit the instructed zone 32 of 41 times. The playability session's instructed segments hit it 29 of
94 times (31 %): in `single_crash_L`, for example, 8 RIGHT:tom1 commits. All of these sessions used the
uncalibrated default layout.

### 4.2 Mechanism labels (multi-label / primary)

| label (multi / primary) | NS | RS | LIVE-NS:minus6 | LIVE-NS:minus5 | LIVE-RS:minus6 |
|---|---|---|---|---|---|
| FLICKER_JUMP | 26 / 26 | 110 / 110 | 2 / 2 | 12 / 12 | 5 / 5 |
| REACQ_ENTRY | 3 / 2 | 9 / 6 | 1 / 1 | 0 / 0 | 0 / 0 |
| JITTER_REENTRY | 6 / 3 | 9 / 6 | 0 / 0 | 1 / 0 | 0 / 0 |
| SHALLOW_HOVER | 3 / 1 | 4 / 3 | 2 / 2 | 0 / 0 | 0 / 0 |
| LATERAL_ENTRY | 48 / 24 | 50 / 26 | 2 / 0 | 1 / 0 | 3 / 1 |
| STROKE_THROUGH | 18 / 1 | 22 / 7 | 2 / 0 | 2 / 2 | 0 / 0 |
| DELIBERATE_LOOKING | 28 / 1 | 112 / 26 | 6 / 5 | 21 / 9 | 15 / 12 |
| UNLABELLED | 0 / 1 | 0 / 40 | 0 / 4 | 0 / 1 | 0 / 4 |
| commits | 59 | 224 | 14 | 24 | 22 |

### 4.3 Tom 1 questions (B2)

| # | Question | Answer (evidence) |
|---:|---|---|
| 1 | Tips actually crossing? | Yes, by the filtered tip: depth p50 0.045 ROI (≈ 20 px) below the arc, future max depth p50 0.064 |
| 2 | Merely hovering? | Rarely: SHALLOW_HOVER 3 of 59 |
| 3 | Coordinate noise, repeated crossings? | Noise yes, but of a different kind: an estimate **jump** of p50 53 px, with 88 % reverting next frame; small-jitter re-entry (JITTER_REENTRY) only 6 of 59 |
| 4 | Boundary near a common trajectory? | Yes. Held sticks rest at tom1's top: in `dist-…-exp-6-t2`, 237 of 564 live hand-frames are inside tom1 and 181 within 0.02 of its boundary |
| 5 | Direction or velocity test too permissive? | The test (`v_min` 0.15 ROI/s on a fixed normal) passes jumps easily, but tightening it (B2, B12) cuts real-looking strikes faster than false ones |
| 6 | Insufficient hysteresis? | Hysteresis (B4) removes only 3–25 %; re-entry is not the main mechanism |
| 7 | Same trajectory triggering several zones? | STROKE_THROUGH 18 of 59 multi-label (tom1 → snare) |
| 8 | Geometry sensitive to tip jitter? | It is sensitive to tip **jumps**, which come from perception |
| 9 | Calibration causing the overlap? | Live and replay used the uncalibrated default layout. Under the three owner calibrations, 51–58 of 59 NS tips fall in no zone (diagnostic only; those files do not bind to the current config) |
| 10 | One hand? | RIGHT 44, LEFT 15 in NS; live −6 LEFT 10, RIGHT 4 |

### 4.4 VALID-anchored crossing (B11, asked specifically)

**Previous point not VALID before a VALID crossing:** 26 of 59 NS commits (no-axis prior 14, bridged 10,
DEGRADED axis 2), 2 of 14 live −6 and 12 of 24 live −5 no-strike commits.

**Applying B11 removes exactly those 26.** It also removes 110 of 224 real-looking commits (49 %) and 14 of
29 zone-correct ones. Real-looking strikes have the same structure, because the stick axis is often lost in
the frame before an observed impact.

### 4.5 Complete false-commit table

The table is in the appendix (97 rows: NS, live −6, live −5). It is also in
`analysis/false-commit-table.csv`, and with every field in `analysis/b-false-commit-table.json`.

## 5. Performance (Part F)

| run | FPS | drops % | age p50/p95/p99 ms | MediaPipe p50/p95/p99 ms | processing p50/p95/p99 ms | > 33.3 ms % | > 40 ms % | > 50 ms % |
|---|---|---|---|---|---|---|---|---|
| paced/baseline-current | 20.5 | 31.8 | 16.4 / 31.7 / 41.4 | 39.6 / 61.8 / 79.9 | 43.4 / 67.0 / 86.5 | 79.3 | 62.6 | 27.4 |
| 2026-10-02 paced/queue-1 (uncontended) | 24.6 | 18.4 | 14.6 / 31.1 / 37.2 | 35.2 / 50.4 / 64.8 | 37.5 / 54.6 / 69.4 | 60.2 | 35.2 | 8.6 |
| 2026-10-02 paced/baseline queue-2 (uncontended) | 23.9 | 20.5 | 48.6 / 64.6 / 75.5 | 37.3 / 50.8 / 63.2 | 39.7 / 54.6 / 67.9 | 62.7 | 48.7 | 8.7 |
| owner live check minus6 | 23.9 | 20.8 | 13.3 / 30.6 / 36.5 | 28.0 / 46.1 / 58.8 | 33.9 / 52.8 / 65.4 | 53.6 | 30.6 | 7.8 |
| owner live check minus5 | 24.3 | 19.5 | 14.1 / 30.7 / 36.2 | 28.1 / 44.4 / 52.9 | 33.2 / 51.1 / 62.2 | 48.4 | 26.1 | 6.0 |

- **Current tree, paced:** 20.5 FPS, 31.8 % drops, processing p50 43.4 ms.
- **Load during these runs:** the paced runs ran with the owner's desktop apps open (Discord, Edge WebView2,
  Chrome; about half a core, about 3 GB RAM free).
- **Why it is slower than on 2026-10-02:** MediaPipe rose from p50 35.2 to 39.6 ms and p95 from 50.4 to
  61.8 ms against the uncontended queue-1 runs on the same code. Frame age did not change (p50 14.6 →
  16.4 ms).
- **No before/after:** nothing was adopted, so there is no "after" run. The current numbers are the
  baseline for the next change.

| stage (p50 / p95 / p99 ms) | paced/baseline-current | owner live check minus6 |
|---|---|---|
| 1 perception: MediaPipe | 39.58 / 61.79 / 79.94 | 28.04 / 46.10 / 58.80 |
| 1 perception: other (hands pre/post, identity, grip, stick) | 3.79 / 9.37 / 12.31 | 3.96 / 9.32 / 13.30 |
| 1 perception: stick total | 3.20 / 8.46 / 11.42 | 3.34 / 8.43 / 12.52 |
| 2 queue staleness (frame age at start) | 16.45 / 31.66 / 41.44 | 13.27 / 30.65 / 36.52 |
| 3 rendering (overlay + mirror) | 2.55 / 4.52 / 5.94 | 2.39 / 5.45 / 7.90 |
| 3 display | – | 0.58 / 1.25 / 3.62 |
| 4 tracking | 0.19 / 0.43 / 0.62 | 0.17 / 0.32 / 0.43 |
| 5 geometry | 0.08 / 0.26 / 0.41 | 0.11 / 0.27 / 0.42 |
| 5 decision logic (commit policy) | 0.04 / 0.10 / 0.15 | 0.04 / 0.08 / 0.12 |
| 6 audio scheduling | 0.01 / 0.03 / 0.05 | 0.01 / 0.04 / 0.04 |

| Bucket | Finding |
|---|---|
| 1. Perception | MediaPipe is 83–91 % of processing (ratio of p50s, live −6 to paced); stick + other perception 3–4 ms |
| 2. Queue staleness | p50 13–16 ms; queue depth always 1 |
| 3. Rendering | 2.4–2.6 ms p50; display 0.6 ms |
| 4. Tracking | 0.2 ms |
| 5. Geometry and commit | 0.1 ms |
| 6. Audio scheduling | 0.01 ms |

Nothing contradicts the 2026-10-02 finding, so rendering was not touched.

## 6. Candidate fixes

### 6.1 B: decision-only (re-simulated, identical inputs)

Criteria C-B1..C-B7 are in `predeclaration.md`: NS −50 %, RS ≥ 95 % kept, identical timing, ZC and zone
shares, safety, causal prefix invariance, SYN.

| candidate | NS commits | RS kept | RS timing changed | ZC % | SYN recall / unmatched | LIVE −6 NS / RS (report) | zone-correct RS kept (post hoc) | C-B1..C-B7 | verdict |
|---|---|---|---|---|---|---|---|---|---|
| B1=0.005 | 59→55 (7 %) | 95.5 % | 0 | 31.1 | 0.883 / 2 | 10 / 21 | 97 % | ✗ ✓ ✓ ✓ ✓ ✓ ✗ | FAIL |
| B1=0.01 | 59→51 (14 %) | 90.2 % | 0 | 30.7 | 0.799 / 1 | 9 / 21 | 93 % | ✗ ✗ ✓ ✓ ✓ ✓ ✗ | FAIL |
| B1=0.02 | 59→46 (22 %) | 79.9 % | 0 | 33.3 | 0.651 / 1 | 6 / 17 | 90 % | ✗ ✗ ✓ ✗ ✓ ✓ ✗ | FAIL |
| B2=0.3 | 59→51 (14 %) | 88.8 % | 0 | 32.1 | 0.937 / 10 | 12 / 21 | 93 % | ✗ ✗ ✓ ✓ ✓ ✓ ✓ | FAIL |
| B2=0.5 | 59→40 (32 %) | 79.0 % | 0 | 34.6 | 0.937 / 10 | 9 / 20 | 93 % | ✗ ✗ ✓ ✓ ✓ ✓ ✓ | FAIL |
| B2=1 | 59→32 (46 %) | 57.6 % | 0 | 36.4 | 0.934 / 10 | 6 / 15 | 69 % | ✗ ✗ ✓ ✓ ✓ ✓ ✗ | FAIL |
| B3=1 | 59→25 (58 %) | 45.5 % | 0 | 19.5 | 0.937 / 10 | 12 / 15 | 28 % | ✓ ✗ ✓ ✗ ✓ ✓ ✓ | FAIL |
| B3=2 | 59→13 (78 %) | 12.9 % | 0 | 16.7 | 0.913 / 10 | 7 / 8 | 7 % | ✓ ✗ ✓ ✗ ✓ ✓ ✗ | FAIL |
| B3=3 | 59→7 (88 %) | 4.0 % | 0 | 0.0 | 0.867 / 10 | 3 / 5 | 0 % | ✓ ✗ ✓ ✗ ✓ ✓ ✗ | FAIL |
| B4=0.005 | 59→57 (3 %) | 97.3 % | 0 | 30.9 | 0.937 / 10 | 14 / 22 | 100 % | ✗ ✓ ✓ ✓ ✓ ✓ ✓ | FAIL |
| B4=0.01 | 59→53 (10 %) | 96.0 % | 0 | 31.2 | 0.937 / 10 | 14 / 22 | 100 % | ✗ ✓ ✓ ✓ ✓ ✓ ✓ | FAIL |
| B4=0.02 | 59→44 (25 %) | 92.0 % | 0 | 32.2 | 0.937 / 10 | 13 / 20 | 97 % | ✗ ✗ ✓ ✓ ✓ ✓ ✓ | FAIL |
| B5=0.15 | 59→54 (8 %) | 100.0 % | 0 | 30.9 | 0.937 / 10 | 14 / 22 | 100 % | ✗ ✓ ✓ ✓ ✓ ✓ ✓ | FAIL |
| B5=0.2 | 59→51 (14 %) | 97.8 % | 0 | 31.5 | 0.937 / 10 | 14 / 21 | 100 % | ✗ ✓ ✓ ✓ ✓ ✓ ✓ | FAIL |
| B5=0.3 | 59→47 (20 %) | 92.4 % | 0 | 31.8 | 0.909 / 9 | 14 / 20 | 97 % | ✗ ✗ ✓ ✓ ✓ ✓ ✗ | FAIL |
| B6=0.005 | 59→30 (49 %) | 86.2 % | 0 | 29.6 | 0.909 / 8 | 12 / 16 | 83 % | ✗ ✗ ✓ ✓ ✓ ✓ ✗ | FAIL |
| B6=0.01 | 59→27 (54 %) | 84.8 % | 0 | 29.6 | 0.906 / 8 | 12 / 16 | 83 % | ✓ ✗ ✓ ✓ ✓ ✓ ✗ | FAIL |
| B6=0.02 | 59→21 (64 %) | 79.9 % | 0 | 30.3 | 0.906 / 8 | 12 / 13 | 79 % | ✓ ✗ ✓ ✓ ✓ ✓ ✗ | FAIL |
| B7=2 | 59→27 (54 %) | 36.2 % | 0 | 33.3 | 0.937 / 10 | 10 / 17 | 38 % | ✓ ✗ ✓ ✗ ✓ ✓ ✓ | FAIL |
| B7=3 | 59→23 (61 %) | 26.8 % | 0 | 28.0 | 0.930 / 10 | 8 / 17 | 24 % | ✓ ✗ ✓ ✗ ✓ ✓ ✗ | FAIL |
| B7=5 | 59→20 (66 %) | 22.3 % | 0 | 14.3 | 0.918 / 10 | 8 / 15 | 10 % | ✓ ✗ ✓ ✗ ✓ ✓ ✗ | FAIL |
| B8=0.65 | 59→58 (2 %) | 95.5 % | 0 | 29.2 | 0.937 / 10 | 12 / 20 | 90 % | ✗ ✓ ✓ ✓ ✓ ✓ ✓ | FAIL |
| B8=0.7 | 59→55 (7 %) | 85.7 % | 0 | 29.5 | 0.937 / 10 | 11 / 18 | 79 % | ✗ ✗ ✓ ✓ ✓ ✓ ✓ | FAIL |
| B8=0.8 | 59→27 (54 %) | 48.7 % | 0 | 28.0 | 0.937 / 10 | 5 / 12 | 48 % | ✓ ✗ ✓ ✗ ✓ ✓ ✓ | FAIL |
| B9=0.005 | 59→54 (8 %) | 92.0 % | 206 | 32.2 | 0.948 / 1 | 11 / 24 | 93 % | ✗ ✗ ✗ ✓ ✓ ✓ ✓ | FAIL |
| B9=0.01 | 59→54 (8 %) | 80.4 % | 180 | 32.5 | 0.939 / 0 | 11 / 25 | 86 % | ✗ ✗ ✗ ✓ ✓ ✓ ✓ | FAIL |
| B9=0.02 | 59→52 (12 %) | 64.7 % | 145 | 32.4 | 0.909 / 0 | 8 / 22 | 72 % | ✗ ✗ ✗ ✓ ✓ ✓ ✗ | FAIL |
| B11=1 | 59→33 (44 %) | 50.9 % | 0 | 32.6 | 0.937 / 10 | 12 / 17 | 52 % | ✗ ✗ ✓ ✓ ✓ ✓ ✓ | FAIL |
| B12=0.15 | 59→46 (22 %) | 63.4 % | 0 | 24.2 | 0.892 / 10 | 12 / 19 | 52 % | ✗ ✗ ✓ ✗ ✓ ✓ ✗ | FAIL |
| B12=0.5 | 59→41 (31 %) | 41.5 % | 0 | 23.3 | 0.881 / 10 | 6 / 17 | 34 % | ✗ ✗ ✓ ✗ ✓ ✓ ✗ | FAIL |
| B12=1 | 59→39 (34 %) | 24.1 % | 0 | 22.2 | 0.862 / 9 | 4 / 12 | 21 % | ✗ ✗ ✓ ✗ ✓ ✓ ✗ | FAIL |

- **No candidate passes.** Every rule that reaches the NS bar drops RS below 95 %: B3, B6 (0.01 / 0.02),
  B7, B8 (0.8).
- **B6 = 0.01 is the closest:**
  - NS −54 %, RS 84.8 %, 83 % of zone-correct commits kept;
  - it also fails SYN (recall 0.906 against 0.937).
- **B9 also changes commit timing**, so it fails C-B3.
- **B10, next-frame confirmation (diagnostic, ineligible):** it would keep 31 of 59 NS and 112 of 224 RS
  commits.
- **Combination:** none evaluated, since no single candidate passed.
- **Report-only contrast run:** not run; the pre-declaration runs it only with a selected B fix.
- **The zone-correct column is post hoc and report-only** (`analysis/posthoc-zc-retention.json`).

### 6.2 A: perception (full replay)

| run | S11 discarded % | D6 VALID % | NS commits | S11 identity jumps | resets/min | median tip shift px | S11 axis-found % | criteria 1..8 | verdict |
|---|---|---|---|---|---|---|---|---|---|
| baseline2 | 45.2 | 17.2 | 59 | 85 | 51.6 | – | 62.7 | – | – |
| a1-min-elongation-1.75 | 42.0 | 21.2 | 68 | 85 | 51.2 | 0.00 | 65.2 | ✓ ✗ ✓ ✓ ✓ ✓ ✓ NOT RUN | FAIL |
| a1-min-elongation-1.5 | 40.6 | 24.3 | 67 | 85 | 49.9 | 0.00 | 67.4 | ✓ ✗ ✗ ✓ ✓ ✓ ✓ NOT RUN | FAIL |
| a2-angle-tol-0.85 | 41.6 | 17.8 | 67 | 85 | 51.6 | 0.00 | 67.2 | ✓ ✗ ✓ ✓ ✓ ✗ ✓ NOT RUN | FAIL |
| a2-angle-tol-1.0 | 38.9 | 18.1 | 73 | 85 | 49.8 | 0.00 | 71.7 | ✓ ✗ ✗ ✓ ✓ ✓ ✓ NOT RUN | FAIL |

- **All four reduce missed strikes:**
  - S11 discarded share 45.2 → 38.9–42.0 %;
  - D6 VALID 17.2 → up to 24.3 %;
  - axis-found up to +9 points.
- **All four raise NS commits (59 → 67–73)**, so they fail criterion 2. Some also fail zone shares (3) or
  resets/min (6).
- **Not affected:** the median tip shift is 0 px and invariant violations are 0.
- **Criterion 8 (paced):** not run, because no candidate passed criteria 1–7.

### 6.3 Adopted

None.

### 6.4 Rejected

All 31 B candidates and all 4 A candidates.

Also not done:
- the `_last_bbox` fix: attribution unchanged;
- a GRIP_DEGENERATE fix: no replayable evidence;
- MediaPipe changes: owner-closed, no experiment.

## 7. Production changes

None in `src/`, in `configs/` or in the schema.

Harness-only:
- `scripts/_resp.py`: probe row fields `region_clip` and `grip_baseline`;
- `tests/scripts/test_diagnose_responsiveness.py`: two tests for them;
- `scripts/README.md`: documentation.

The determinism check confirms that the probe change leaves every decision unchanged.

## 8. Causality and safety

- **Sounding commits checked:** all 384 in the evidence (283 replay, 101 live).
  - On a VALID frame: 384 of 384 (**0 on DEGRADED frames**).
  - With an observed stick axis: 384 of 384 (**0 on missing-stick frames**).
  - Above the frame-drop guard: 0.
- **Invariant violations:** 0 in every app summary.
- **Future-frame leakage:** none at runtime, because no runtime code changed. Every candidate rule passed
  causal prefix invariance (C-B6). Future frames were used only in the labelled offline diagnoses (B2
  labels, angle reversion, B10).
- **The closed decisions are unchanged:** queue 1, exposure −6, contrast OFF, no axis carry-over, presence,
  identity, mirror, pollKey, DEGRADED commits OFF.

## 9. Owner decisions

1. **False strikes: no pre-declared rule passed.** Options:
   - (a) keep the current behaviour;
   - (b) adopt B6 = 0.01 (one-shot re-arm) as an explicit engineering deviation. It failed C-B2 (RS 84.8 %)
     and C-B7 (SYN recall 0.906). **Not recommended:** it also removes 17 % of zone-correct strikes;
   - (c) address the cause instead: the stick-tip estimate flicker, and tom1's position at the held-stick
     rest height and above the snare.
2. **Layout and calibration.**
   - The three owner calibrations (exposure −5, queue 2) are refused by the current config
     (`CAMERA_PROFILE_CHANGED`). Exposure −6 alone already breaks the binding.
   - Live sessions therefore run uncalibrated.
   - Should the owner re-run the calibration wizard at the current camera profile? That is an owner live
     action, and it changes where tom1 sits relative to the held-stick position.
3. **Missed strikes.**
   - The A candidates (`min_elongation` 1.5–1.75, `angle_tol_rad` 0.85–1.0) cut discarded entries by 3–6
     points but add 8–14 no-strike commits.
   - They could be reconsidered only together with a false-strike fix, in a new pre-declared experiment.
4. **GRIP_DEGENERATE at −6.** It causes 33 % of live −6 resets, but no replayable recording contains it.
   Any fix would need a short owner developer capture at −6 (not participant data).
5. **Evidence quality.** The RS set is mostly wrong-zone (31 % zone-correct) and recorded at about 11 FPS.
   A labelled 30 FPS owner playing capture would be needed to evaluate any false-strike rule fairly against
   real strikes.

## 10. Live checks

None required: nothing was adopted.

## 11. Scope limits

- **No ground truth:** "real-looking" strikes are commits in instructed strike segments.
- **The LIVE rows have no frames:** decision-only candidates were re-simulated on them, but perception
  candidates could not be.
- **Paced timings were contended**; replay decisions are not affected.
- **Speed terciles use wrist speed;** tip speed is dominated by estimate jumps.

## 12. Phase 18

Phase 18 remains BLOCKED. Nothing here is participant validation.

## 13. Verification (2026-10-03, this tree)

| Check | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **1,643 passed, 1 skipped, 0 failed** (exit 0; 00:44–00:58 +03:00) |
| `.venv\Scripts\ruff.exe check .` | All checks passed |
| `git diff --check` | clean |
| Untracked files | no CR, no trailing whitespace |
| `python scripts/verify_phase19.py --skip-full` | 11/11 checks as expected (exit 0) |
| Causality tests | inside the full suite, green: `tests/commit/test_causal_commit.py`, `tests/tracking/test_causal.py`, `tests/app/test_gap_strike_causality.py`, `tests/invariants`, `tests/failure_injection` |

**Notes on the counts.**
- The pass count is that of the full suite's progress output; `-q` together with `addopts = -q` suppresses
  the summary line.
- `pytest --collect-only` collects 1,643 tests.
- The skipped test is the opt-in hardware capture test, which skips at module level during collection.
- The 2 tests beyond the stated 1,641 baseline are this investigation's probe-field tests.

## Appendix: complete false-commit table (NS, live −6, live −5)

- **Arc angle:** where the entry-frame tip lies around the zone centre (0° = the top of the arc).
- **Prev point:** how the crossing's previous point was observed.
- **Primary:** the first label in the declared precedence.

| input | segment | frame | hand | zone | status | tip conf | prev point | inward v (ROI/s) | depth | arc angle ° | tip jump px | live frames before | primary | labels |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1442-playability | fake_swings | 3220 | RIGHT | tom1 | VALID | 0.84 | DEGRADED_AXIS | 1.13 | 0.045 | 64 | 184 | 2 | FLICKER_JUMP | FLICKER_JUMP+REACQ_ENTRY+LATERAL_ENTRY+DELIBERATE_LOOKING |
| 1442-playability | fake_swings | 3257 | RIGHT | tom1 | VALID | 0.83 | BRIDGED | 2.90 | 0.151 | 168 | 149 | 3 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| 1442-playability | fake_swings | 3269 | LEFT | crash_ride | VALID | 0.69 | VALID_AXIS | 0.87 | 0.032 | -60 | 71 | 20 | LATERAL_ENTRY | LATERAL_ENTRY |
| 1442-playability | fake_swings | 3363 | RIGHT | tom1 | VALID | 0.79 | DEGRADED_PRIOR | 1.71 | 0.124 | -147 | 79 | 5 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| 1442-playability | stop_before_impact | 3487 | RIGHT | snare | VALID | 0.90 | VALID_AXIS | 3.60 | 0.083 | 13 | 101 | 1 | REACQ_ENTRY | REACQ_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| 1442-playability | stop_before_impact | 3546 | RIGHT | snare | VALID | 0.91 | DEGRADED_PRIOR | 1.98 | 0.027 | 15 | 94 | 10 | FLICKER_JUMP | FLICKER_JUMP |
| dist-exp-5-t2 | – | 88 | LEFT | tom1 | VALID | 0.73 | VALID_AXIS | 0.26 | 0.021 | 85 | 20 | 88 | LATERAL_ENTRY | LATERAL_ENTRY |
| dist-exp-5-t2 | – | 111 | RIGHT | tom1 | VALID | 0.74 | VALID_AXIS | 0.77 | 0.057 | -87 | 38 | 111 | LATERAL_ENTRY | LATERAL_ENTRY |
| dist-exp-5-t2 | – | 374 | RIGHT | tom1 | VALID | 0.85 | VALID_AXIS | 0.16 | 0.006 | -76 | 6 | 374 | LATERAL_ENTRY | LATERAL_ENTRY+SHALLOW_HOVER |
| dist-exp-5-t2 | – | 396 | RIGHT | tom1 | VALID | 0.90 | VALID_AXIS | 0.72 | 0.069 | -97 | 34 | 396 | LATERAL_ENTRY | LATERAL_ENTRY |
| dist-exp-5-t2 | – | 399 | RIGHT | tom1 | VALID | 0.90 | VALID_AXIS | 0.43 | 0.041 | -82 | 18 | 399 | JITTER_REENTRY | JITTER_REENTRY+LATERAL_ENTRY |
| dist-exp-5-t2 | – | 421 | RIGHT | tom1 | VALID | 0.91 | VALID_AXIS | 0.58 | 0.041 | -85 | 22 | 421 | LATERAL_ENTRY | LATERAL_ENTRY |
| dist-exp-5-t2 | – | 428 | RIGHT | tom1 | VALID | 0.86 | VALID_AXIS | 0.57 | 0.055 | -88 | 25 | 428 | JITTER_REENTRY | JITTER_REENTRY+LATERAL_ENTRY |
| dist-exp-5-t2 | – | 441 | RIGHT | tom1 | VALID | 0.80 | VALID_AXIS | 0.18 | 0.000 | -71 | 3 | 441 | SHALLOW_HOVER | SHALLOW_HOVER |
| dist-exp-5-t3 | – | 44 | RIGHT | tom1 | VALID | 0.78 | VALID_AXIS | 1.97 | 0.057 | -74 | 52 | 44 | LATERAL_ENTRY | LATERAL_ENTRY+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 50 | RIGHT | tom1 | VALID | 0.81 | VALID_AXIS | 1.52 | 0.042 | -64 | 45 | 50 | LATERAL_ENTRY | LATERAL_ENTRY+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 54 | RIGHT | tom1 | VALID | 0.73 | VALID_AXIS | 2.36 | 0.076 | -96 | 62 | 54 | LATERAL_ENTRY | LATERAL_ENTRY+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 70 | RIGHT | tom1 | VALID | 0.75 | VALID_AXIS | 2.26 | 0.070 | -88 | 57 | 70 | LATERAL_ENTRY | LATERAL_ENTRY+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 74 | RIGHT | tom1 | VALID | 0.78 | VALID_AXIS | 1.77 | 0.078 | -98 | 65 | 74 | LATERAL_ENTRY | LATERAL_ENTRY+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 79 | RIGHT | tom1 | VALID | 0.75 | VALID_AXIS | 3.12 | 0.099 | -131 | 72 | 79 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 88 | RIGHT | tom1 | VALID | 0.89 | VALID_AXIS | 1.49 | 0.075 | -94 | 59 | 88 | LATERAL_ENTRY | LATERAL_ENTRY+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 103 | RIGHT | tom1 | VALID | 0.82 | VALID_AXIS | 1.10 | 0.041 | -73 | 37 | 103 | LATERAL_ENTRY | LATERAL_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 177 | LEFT | tom1 | VALID | 0.70 | BRIDGED | 6.19 | 0.081 | 113 | 119 | 7 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 191 | RIGHT | snare | VALID | 0.81 | DEGRADED_AXIS | 5.51 | 0.168 | -171 | 91 | 191 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 214 | LEFT | tom1 | VALID | 0.61 | DEGRADED_PRIOR | 2.57 | 0.121 | 150 | 64 | 28 | FLICKER_JUMP | FLICKER_JUMP+STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 244 | LEFT | tom1 | VALID | 0.67 | VALID_AXIS | 0.32 | 0.010 | 69 | 36 | 58 | LATERAL_ENTRY | LATERAL_ENTRY+STROKE_THROUGH |
| dist-exp-5-t3 | – | 280 | RIGHT | tom1 | VALID | 0.85 | DEGRADED_PRIOR | 0.35 | 0.019 | 74 | 46 | 51 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY |
| dist-exp-5-t3 | – | 292 | RIGHT | tom1 | VALID | 0.73 | DEGRADED_PRIOR | 1.10 | 0.040 | 71 | 53 | 63 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 322 | LEFT | tom1 | VALID | 0.83 | VALID_AXIS | 5.02 | 0.150 | 162 | 106 | 27 | STROKE_THROUGH | STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 322 | RIGHT | tom1 | VALID | 0.67 | BRIDGED | 1.89 | 0.069 | -61 | 66 | 93 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 328 | LEFT | tom1 | VALID | 0.82 | VALID_AXIS | 2.77 | 0.038 | 50 | 62 | 33 | LATERAL_ENTRY | LATERAL_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 333 | LEFT | tom1 | VALID | 0.80 | VALID_AXIS | 3.15 | 0.060 | 68 | 73 | 38 | LATERAL_ENTRY | LATERAL_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 341 | LEFT | tom1 | VALID | 0.86 | VALID_AXIS | 1.35 | 0.014 | 48 | 73 | 46 | LATERAL_ENTRY | LATERAL_ENTRY+STROKE_THROUGH |
| dist-exp-5-t3 | – | 362 | RIGHT | tom1 | VALID | 0.74 | BRIDGED | 2.09 | 0.057 | -57 | 65 | 15 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 373 | LEFT | tom1 | VALID | 0.82 | VALID_AXIS | 2.23 | 0.046 | 66 | 64 | 78 | LATERAL_ENTRY | LATERAL_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 379 | LEFT | tom1 | VALID | 0.81 | VALID_AXIS | 3.82 | 0.096 | 125 | 90 | 84 | LATERAL_ENTRY | LATERAL_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 380 | RIGHT | tom1 | VALID | 0.80 | BRIDGED | 1.48 | 0.056 | -59 | 48 | 33 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 391 | LEFT | tom1 | VALID | 0.84 | DEGRADED_PRIOR | 3.18 | 0.083 | 109 | 100 | 96 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 410 | LEFT | tom1 | VALID | 0.80 | DEGRADED_PRIOR | 4.31 | 0.109 | 136 | 118 | 115 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-5-t3 | – | 418 | LEFT | tom1 | VALID | 0.83 | VALID_AXIS | 1.57 | 0.007 | 57 | 52 | 123 | LATERAL_ENTRY | LATERAL_ENTRY+STROKE_THROUGH |
| dist-exp-5-t3 | – | 434 | LEFT | tom1 | VALID | 0.82 | VALID_AXIS | 1.43 | 0.014 | 57 | 49 | 139 | LATERAL_ENTRY | LATERAL_ENTRY+STROKE_THROUGH |
| dist-exp-6-t2 | – | 4 | RIGHT | tom1 | VALID | 0.81 | VALID_AXIS | 0.57 | 0.045 | -69 | 22 | 2 | REACQ_ENTRY | REACQ_ENTRY+JITTER_REENTRY+LATERAL_ENTRY |
| dist-exp-6-t2 | – | 16 | RIGHT | tom1 | VALID | 0.79 | DEGRADED_PRIOR | 0.53 | 0.029 | -64 | 38 | 14 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY |
| dist-exp-6-t2 | – | 28 | RIGHT | tom1 | VALID | 0.79 | BRIDGED | 0.23 | 0.047 | -62 | 69 | 26 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY |
| dist-exp-6-t2 | – | 116 | RIGHT | tom1 | VALID | 0.74 | VALID_AXIS | 2.37 | 0.148 | 172 | 91 | 10 | LATERAL_ENTRY | LATERAL_ENTRY+STROKE_THROUGH+DELIBERATE_LOOKING |
| dist-exp-6-t2 | – | 120 | RIGHT | tom1 | VALID | 0.78 | VALID_AXIS | 0.34 | 0.003 | -53 | 57 | 14 | LATERAL_ENTRY | LATERAL_ENTRY |
| dist-exp-6-t2 | – | 125 | RIGHT | tom1 | VALID | 0.74 | DEGRADED_PRIOR | 3.89 | 0.137 | 172 | 96 | 19 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+DELIBERATE_LOOKING |
| dist-exp-6-t2 | – | 132 | RIGHT | tom1 | VALID | 0.78 | DEGRADED_PRIOR | 0.32 | 0.009 | -59 | 5 | 26 | FLICKER_JUMP | FLICKER_JUMP+JITTER_REENTRY |
| dist-exp-6-t2 | – | 172 | RIGHT | tom1 | VALID | 0.78 | DEGRADED_PRIOR | 0.21 | 0.046 | -82 | 21 | 66 | FLICKER_JUMP | FLICKER_JUMP+JITTER_REENTRY+LATERAL_ENTRY |
| dist-exp-6-t2 | – | 228 | RIGHT | tom1 | VALID | 0.74 | VALID_AXIS | 0.39 | 0.035 | -79 | 18 | 15 | JITTER_REENTRY | JITTER_REENTRY+LATERAL_ENTRY |
| dist-exp-6-t2 | – | 240 | RIGHT | tom1 | VALID | 0.77 | DEGRADED_PRIOR | 0.45 | 0.037 | -71 | 24 | 27 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY |
| dist-exp-6-t2 | – | 330 | RIGHT | tom1 | VALID | 0.72 | BRIDGED | 0.44 | 0.044 | -65 | 43 | 17 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY |
| dist-exp-6-t2 | – | 353 | RIGHT | tom1 | VALID | 0.86 | VALID_AXIS | 0.25 | 0.005 | -51 | 5 | 40 | UNLABELLED |  |
| dist-exp-6-t2 | – | 356 | RIGHT | tom1 | VALID | 0.76 | DEGRADED_PRIOR | 0.26 | 0.011 | -64 | 12 | 43 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY |
| dist-exp-6-t2 | – | 378 | RIGHT | tom1 | VALID | 0.77 | VALID_AXIS | 0.32 | 0.040 | -69 | 22 | 65 | LATERAL_ENTRY | LATERAL_ENTRY |
| dist-exp-6-t2 | – | 389 | RIGHT | tom1 | VALID | 0.77 | BRIDGED | 0.33 | 0.041 | -72 | 29 | 76 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY |
| dist-exp-6-t2 | – | 394 | RIGHT | tom1 | VALID | 0.77 | BRIDGED | 0.17 | 0.023 | -65 | 34 | 81 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY |
| dist-exp-6-t2 | – | 421 | RIGHT | tom1 | VALID | 0.78 | BRIDGED | 0.98 | 0.007 | -64 | 61 | 5 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+STROKE_THROUGH |
| dist-exp-6-t2 | – | 440 | RIGHT | tom1 | VALID | 0.73 | DEGRADED_PRIOR | 0.34 | 0.001 | -70 | 12 | 24 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+SHALLOW_HOVER |
| live/minus6 | hold_still | 169 | RIGHT | snare | VALID | 0.76 | VALID_AXIS | 0.33 | 0.013 | 16 | 36 | 1 | REACQ_ENTRY | REACQ_ENTRY+LATERAL_ENTRY |
| live/minus6 | hold_still | 177 | RIGHT | snare | VALID | 0.63 | DEGRADED_AXIS | 0.76 | 0.004 | 20 | 36 | 9 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY |
| live/minus6 | fake_swings | 1169 | LEFT | hihat | VALID | 0.93 | VALID_AXIS | 0.79 | 0.061 | 109 | 23 | 304 | UNLABELLED |  |
| live/minus6 | fake_swings | 1178 | LEFT | hihat | VALID | 0.91 | VALID_AXIS | 2.09 | 0.054 | 103 | 38 | 313 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus6 | fake_swings | 1186 | LEFT | hihat | VALID | 0.91 | VALID_AXIS | 1.24 | 0.055 | 102 | 21 | 321 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus6 | fake_swings | 1202 | LEFT | tom1 | VALID | 0.80 | VALID_AXIS | 0.71 | 0.014 | -22 | 12 | 337 | UNLABELLED |  |
| live/minus6 | fake_swings | 1211 | LEFT | tom1 | VALID | 0.73 | VALID_AXIS | 1.83 | 0.050 | -10 | 60 | 346 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus6 | fake_swings | 1221 | LEFT | tom1 | VALID | 0.77 | VALID_AXIS | 1.18 | 0.031 | -5 | 40 | 356 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus6 | fake_swings | 1230 | LEFT | tom1 | VALID | 0.80 | VALID_AXIS | 1.25 | 0.001 | 3 | 22 | 365 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus6 | fake_swings | 1253 | LEFT | tom1 | VALID | 0.63 | VALID_AXIS | 0.39 | 0.004 | 55 | 11 | 388 | SHALLOW_HOVER | SHALLOW_HOVER+STROKE_THROUGH |
| live/minus6 | fake_swings | 1305 | RIGHT | snare | VALID | 0.81 | DEGRADED_PRIOR | 2.12 | 0.032 | 25 | 72 | 12 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| live/minus6 | fake_swings | 1316 | RIGHT | snare | VALID | 0.76 | VALID_AXIS | 0.20 | 0.005 | 10 | 7 | 23 | SHALLOW_HOVER | SHALLOW_HOVER+STROKE_THROUGH |
| live/minus6 | fake_swings | 1332 | LEFT | snare | VALID | 0.68 | VALID_AXIS | 0.18 | 0.009 | 41 | 5 | 467 | UNLABELLED |  |
| live/minus6 | fake_swings | 1345 | LEFT | snare | VALID | 0.73 | VALID_AXIS | 0.32 | 0.014 | 40 | 13 | 480 | UNLABELLED |  |
| live/minus5 | hold_still | 161 | RIGHT | snare | VALID | 0.85 | DEGRADED_PRIOR | 1.68 | 0.106 | 123 | 48 | 6 | FLICKER_JUMP | FLICKER_JUMP+JITTER_REENTRY+DELIBERATE_LOOKING |
| live/minus5 | hold_still | 165 | RIGHT | snare | VALID | 0.77 | DEGRADED_PRIOR | 2.04 | 0.122 | 157 | 58 | 10 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| live/minus5 | hold_still | 174 | RIGHT | snare | VALID | 0.79 | DEGRADED_PRIOR | 4.69 | 0.119 | 141 | 67 | 19 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| live/minus5 | hold_still | 178 | RIGHT | snare | VALID | 0.83 | VALID_AXIS | 2.75 | 0.100 | 94 | 74 | 23 | STROKE_THROUGH | STROKE_THROUGH+DELIBERATE_LOOKING |
| live/minus5 | hold_still | 182 | RIGHT | snare | VALID | 0.79 | BRIDGED | 13.19 | 0.154 | 151 | 232 | 27 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| live/minus5 | hold_still | 187 | RIGHT | snare | VALID | 0.79 | DEGRADED_AXIS | 1.71 | 0.095 | 54 | 168 | 32 | FLICKER_JUMP | FLICKER_JUMP+LATERAL_ENTRY+DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1170 | RIGHT | snare | VALID | 0.80 | DEGRADED_PRIOR | 2.80 | 0.069 | 6 | 39 | 110 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1190 | LEFT | tom1 | VALID | 0.84 | VALID_AXIS | 0.86 | 0.056 | 92 | 20 | 243 | UNLABELLED |  |
| live/minus5 | fake_swings | 1199 | LEFT | tom1 | VALID | 0.82 | VALID_AXIS | 1.29 | 0.085 | 116 | 41 | 252 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1207 | LEFT | tom1 | VALID | 0.75 | VALID_AXIS | 3.97 | 0.112 | 134 | 62 | 260 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1216 | LEFT | tom1 | VALID | 0.75 | VALID_AXIS | 3.89 | 0.111 | 135 | 61 | 269 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1225 | LEFT | tom1 | VALID | 0.78 | VALID_AXIS | 1.20 | 0.048 | 65 | 39 | 278 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1234 | RIGHT | snare | VALID | 0.82 | VALID_AXIS | 1.20 | 0.018 | -27 | 26 | 174 | STROKE_THROUGH | STROKE_THROUGH |
| live/minus5 | fake_swings | 1239 | RIGHT | tom1 | VALID | 0.72 | DEGRADED_AXIS | 1.24 | 0.029 | -29 | 17 | 179 | FLICKER_JUMP | FLICKER_JUMP |
| live/minus5 | fake_swings | 1245 | RIGHT | tom1 | VALID | 0.72 | DEGRADED_AXIS | 2.81 | 0.107 | -136 | 84 | 185 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1251 | LEFT | tom1 | VALID | 0.77 | VALID_AXIS | 1.79 | 0.042 | 56 | 58 | 304 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1266 | LEFT | tom1 | VALID | 0.77 | VALID_AXIS | 1.56 | 0.005 | 35 | 25 | 319 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1274 | RIGHT | tom1 | VALID | 0.72 | VALID_AXIS | 1.36 | 0.053 | -46 | 34 | 214 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1276 | LEFT | tom1 | VALID | 0.70 | VALID_AXIS | 2.32 | 0.001 | 33 | 36 | 329 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1286 | LEFT | tom1 | VALID | 0.77 | VALID_AXIS | 1.60 | 0.055 | 59 | 24 | 339 | DELIBERATE_LOOKING | DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1329 | LEFT | hihat | VALID | 0.87 | DEGRADED_PRIOR | 2.86 | 0.044 | 94 | 49 | 382 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1340 | LEFT | hihat | VALID | 0.82 | DEGRADED_PRIOR | 2.48 | 0.117 | 150 | 85 | 393 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1347 | LEFT | hihat | VALID | 0.81 | DEGRADED_PRIOR | 1.22 | 0.029 | 67 | 43 | 400 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
| live/minus5 | fake_swings | 1394 | LEFT | hihat | VALID | 0.96 | DEGRADED_PRIOR | 3.82 | 0.058 | 92 | 90 | 447 | FLICKER_JUMP | FLICKER_JUMP+DELIBERATE_LOOKING |
