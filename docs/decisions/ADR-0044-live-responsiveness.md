# ADR-0044: Live responsiveness: loss diagnostics, one-slot capture queue, optional contrast-adaptive stick edges

**Status:**
- **Queue:** DECIDED on development evidence; the pre-declared rule passed.
- **Stick option:** IMPLEMENTED and **not enabled** (owner decision 2026-10-02: do not adopt).
- **Exposure:** **DECIDED: −6 kept.** R-EXPOSURE failed, and the owner live check of 2026-10-02 did not
  confirm the replay direction, so no deviation is adopted.
- **Not adopted (owner decision 2026-10-02):** axis carry-over, hand-presence threshold change,
  identity-matching change.

**Date:** 2026-10-02. **Phase:** none (post-T2 investigation). **Related:** README §8; ADR-0009, ADR-0016,
ADR-0039, ADR-0040, ADR-0041; `docs/perf/live-fps-t2.md`; record `docs/perf/live-responsiveness.md`.

## Context

While drumming in front of the camera the owner sees the live app "stop responding". T1 (mirror) and
T2 (display / FPS) are closed: the mirror changes no processing, and the display is not the limit.
Live runs re-acquire hands 60–80 times per minute even with no window.

`scripts/diagnose_responsiveness.py` replays and paces every existing developer recording. No new
recordings were made. The evidence is in `experiments/pre-participant/20261002-responsiveness/`, and the
decision rules were hashed before any candidate run (`predeclaration.md`, sha256 `36145abc…`).

Root causes, with numbers in the record:
1. **The hand landmarker loses a hand.** This causes 76–94 % of tracking losses at 30 FPS. At the live
   config's exposure −6 the room image is about half as bright as at −5, and both hands are detected in
   13 % of frames against 55 %.
2. **A lost hand makes every frame slower.** MediaPipe re-runs palm detection whenever fewer than two
   hands are tracked: p50 about 24–29 ms per frame with two hands tracked, 37–52 ms with fewer. That pushes the
   loop over the 33 ms budget and causes the frame drops.
3. **The stick axis is not found.** GEOM then caps tip confidence below `c_valid`, so the frame is
   DEGRADED. 45 % of observed zone entries in the owner sessions are discarded for track status, and
   70 % of those are stick-axis failures.
4. **The capture queue (two slots, FIFO) delivered a stale frame 93 % of the time.** A newer frame was
   already waiting, so decisions ran on frames 49 ms old (p50) when processing started.

## Decisions

1. **Diagnostics (no behaviour change).**
   - `spacedrums.app.loss_diagnosis` attributes a `LossCause` to every reset and re-acquisition, from
     the perception detail of the frames since the last VALID frame. `LossCause` is a diagnostic enum;
     `ResetReason` and every record are unchanged.
   - The app summary gains `counters.diagnostics`: resets by cause, frame freshness, and hand-model
     time by previously tracked hands. `SD-TRK-002` events gain `detail.loss_cause`.
   - `BoundedFrameQueue.last_depth_at_get` and `LiveFrameSource.queue_report()` expose the queue depth
     at each delivery.
   - A replay of the four owner sessions reproduces the recorded tracker states and the sounding
     arm's commits exactly.
2. **`configs/prototype.candidate.yaml` `camera_profile.queue.max_frames`: 2 → 1** (R-QUEUE passed). The
   schema already allowed 1. The consumer always takes the newest frame; timestamps and drop counting
   are unchanged.
   - Paced replay, 7 captures × 3 repeats: capture-to-processing-start age p50 48.9 → 15.3 ms;
     late deliveries 93 → 0 %; VALID 41.0 → 40.4 %; resets 64.4 → 64.7 /min; commits 139 → 144;
     drops 20.5 → 18.4 %.
   - `live.arm-C` and `perf.developer` are left unchanged as Phase 18/16 inputs (owner decision).
3. **Config schema 1.10: optional `stick.segment.contrast_target_range` / `contrast_max_gain`.**
   Contrast-adaptive Canny thresholds: when the region's p2–p98 grey span is below the target, both
   thresholds are divided by `min(max_gain, target / span)`. The keys default to absent, which keeps
   the byte-identical Phase 03 behaviour.
   - **Not enabled.** R-STICK (target 77, gain 2 or 3) failed criterion 5: commits in no-strike
     recordings rose from 59 to 64. It passed all other criteria: dark −6 axis-found 49 → 84 %, VALID
     17 → 30 %, owner-session discarded entries −1.6 points, median tip shift 0 px, 0 invariant
     violations.
   - The extra commits are mostly held sticks hovering at the tom1 boundary. That pre-existing source
     produces 53 commits in the baseline.
   - Enabling it would be an explicit engineering deviation from the pre-declared rule, which keeps
     fixed thresholds. Owner decision.
4. **Exposure stays −6.** R-EXPOSURE failed criterion 4 and criterion 6:
   - Criterion 4: hand-model p95 was 61.63 ms at −5 against 61.60 ms at −6, a 0.03 ms difference in
     uncontrolled replay timing.
   - Criterion 6: one queue drop in the 6 s −5 swing capture; the −6 swing capture has one too.
   - Every substantive criterion favours −5: both-hands presence 55 vs 13 %, VALID 53 vs 17 %, resets
     40 vs 116 /min, fast-stroke axis-found 90 vs 61 %.
   - A labelled post-hoc paced check also favours −5: hand model p50/p95 28.1/47.8 vs 38.6/54.0 ms;
     drops 18.0 vs 24.0 %.
   - **Proposed then:** −5 for the L2 lighting, as an explicit engineering deviation from the
     pre-declared rule, which kept −6.
   - **Owner live check (2026-10-02, 18:2x +03:00; protocol and criterion fixed and hashed before the
     runs, `live-check-addendum.md` sha256 `ab8ec0d9…`).** The owner made two 60 s runs at the real
     lighting, one at −6 and one at −5 via a temporary override, with the candidate config unchanged.
     The direction was **not confirmed**:
     - Both-hands presence fell from 0.58 to 0.51. The right hand went 0.70 → 0.54, and 14
       hand-left-ROI resets occurred in the −5 run only.
     - MediaPipe p50 was 28.12 vs 28.04 ms (not lower).
     - The no-strike-segment guard was breached: 24 vs 14 commits.
     - VALID (48 vs 35 %), re-acquisitions (42 vs 53 /min), axis-found (80 vs 66 %), drops (19.5 vs
       20.8 %) and unresponsive stretches (6 vs 25 over 0.5 s) favoured −5.
   - **Decision: keep −6.** The engineering deviation is not adopted. R-EXPOSURE stays recorded as
     failed, and the live check is recorded as not confirming. The live data are n = 1 per exposure,
     with a person-dependent workload and position; they do not show that −5 is worse, only that the
     evidence for a deviation is insufficient.
5. **Reported, not adopted:** an identity continuity gate scaled by elapsed frames; MediaPipe
   `min_hand_presence_confidence` 0.4 or 0.3; a VALID-anchored recovery across a non-VALID entry frame.
   That recovery would rescue 7 % of discarded entries. Numbers are in the record.

## Consequences

- The prototype config hash changes, and the P07 schema examples were regenerated
  (`scripts/_p07_examples.py`).
- No decision rule, threshold (`c_valid`, `g_max_frames`, `age_max_s`, commit gates) or coordinate
  convention changed. DEGRADED commits stay off (ADR-0039).
- The owner live check was done on 2026-10-02 (evidence in `live/`, comparison in
  `live-comparison.json`). The app summary now reports reset causes and frame freshness for any run.
- All figures are development evidence on an uncommitted tree; none is participant accuracy.
