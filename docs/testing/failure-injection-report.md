# Failure-injection and safety-invariant report (Phase 17, Tasks 17.2–17.7)

Status: **development evidence**. All of it comes from:
- SYNTHETIC sequences (`app.synthetic`, labelled analytic truth);
- the three developer swing captures, through real perception;
- the SYNTHETIC P07 labelled session;
- the synthetic-trained development C-GRU (`configs/live.arm-C.candidate.yaml`; not a shipped model).

Run context:
- **Machine:** HW-01 (i7-7820HQ, Windows 10.0.22621, CPU), 2026-09-26/27 (+03:00).
- **Code state:** dirty tree on HEAD `8ad5393ece768ff27bbd067c1de5f46ba7425d55`.
- **Executor:** Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code; reasoning effort not exposed
  to the agent.
- **Matching:** the Phase 09 matcher with the candidate W = 50 ms (no primary W is frozen).

**No participant data exists.** The participant replay set, every person-dependent physical test
and a clean post-owner-commit re-run are PENDING (§9).

## 1. Method

- **Monitor.** `app.invariants.InvariantMonitor` audits every frame (I1–I6 are defined in
  ADR-0040 D1).
  - Campaigns run it in `collect` mode and count violations (MEASURED; 0 required).
  - They also count the checks made, so a zero is not vacuous.
  - `tests/invariants/test_inv_monitor.py` (TEST-INV-1) shows that each invariant fires on a
    constructed violation.
- **Injection.** `app.faults` (test builds only) injects deterministic faults in replay:
  - **observation faults:** occlusion, hand out of the ROI, identity swap, low confidence 0.45,
    a background hand reported as the user's;
  - **capture faults:** stall, drop burst, forward timestamp jump, FPS dip;
  - **image faults on developer captures:** an occlusion mask around a hand, the hand's half of
    the ROI blanked, lighting gain/gamma steps and session-wide changes, a moving distractor;
  - **model faults:** at load and mid-session;
  - **live-source timestamp faults** behind a fake camera;
  - **audio device loss and underruns** behind a fake PortAudio stream.
- **Placement and set-ups.**
  - **Where:** SYNTHETIC faults are placed during the **approach** (ending one frame before the
    crossing), at the **impact** (covering it) and during **idle** (≥ 0.3 s from any crossing).
  - **Durations:** 100 / 200 / 300 / 500 / 1000 ms.
  - **Strikes and sequences:** the first two strikes of six sequences: single, repeated,
    alternating two zones, near-simultaneous, rapid, noisy repeated.
  - **Set-ups:** **rule** (A sounds, B shadows; `configs/prototype.candidate.yaml`) and **model**
    (C-GRU sounds, A and B shadow).
- **Attribution.** FP and FN are counted in a window from 0.1 s before the fault to 0.3 s after it.
  They are compared with the unperturbed run of the same sequence (delta).
  - An FP is **fabricated** when no strike of the same hand lies within 0.3 s (nothing happened).
  - Otherwise it is **mistimed**: a real strike committed outside W, which also produces an FN.
- **Pre-fix / post-fix.** The campaign was first recorded on the unmodified decision logic, with
  instrumentation only:
  - `experiments/phase-17/20260926-1542-prefix-inject-core/`;
  - `experiments/phase-17/20260926-1554-prefix-inject-devcapture/`.

  The ADR-0040 fixes followed. The same campaign was then re-run inside the final gate verification
  (§10).

## 2. Findings and fixes

| # | Finding (pre-fix evidence) | Invariant / effect | Fix (ADR-0040) | Post-fix |
|---|---|---|---|---|
| F-1 | Switching B → A (or a model fallback) one frame after an anticipatory commit made A sound the **same strike again** 66.7 ms later: 14 of 540 switch runs, only at `p_commit ≤ 0.3` with `tti_commit_s ≥ 0.10` (inside Phase 18's sweep) | I3 + I4 on the audible stream | D2: ARM_SWITCH keeps episode suppression; the newly sounding arm absorbs the previous arm's refractory timers and open-episode flags | 0 violations in all 540 switch runs (§6.2); TEST-FI-SW-1, TEST-INV-1 |
| F-2 | A camera stall up to 300 ms never reset the tracker (one Kalman prediction over the gap); A committed 93–162 ms late from a crossing interpolated across 4–6 missing frames; a +0.2 s clock jump made the filter's extrapolation cross the snare surface one frame before the observed tip | timing / premature reactive strike | D3 time-gap reset (> 150 ms); D4 stalls count as missing frames | frame intervals > 150 ms reset the tracker (TEST-FI-CAP-4); the development model's stall / drop / jump fabrications 11 / 15 / 6 → 1 / 1 / 3 (§5.2) |
| F-3 | `LiveFrameSource` clamped a non-increasing `t_capture` to an **equal** stamp, which `DecisionPipeline.step` rejects: **crash** after 9 frames (driver stamps whose hand-over lag exceeds the frame interval) and after 57 frames (backward grab-clock step) | crash | D5: such frames are refused and counted; replay refuses such recordings at load | 193 / 192 frames delivered, 4 / 5 refused and counted, 0 violations (§5.1); TEST-FI-CAP-1, TEST-FI-CAP-2 |
| F-4 | Model exceptions other than `OSError`/`ValueError`/`RuntimeError` **crashed** the application (`TypeError`, `IndexError`, `KeyError`, `FloatingPointError` at inference; a wrongly typed manifest field at load: 5 of 15 model cases) | crash | D6: any exception is a sticky fallback | 0 crashes in 15 model cases, 14 fallbacks (§6.1); TEST-FI-MDL-1..5 |
| F-5 | NaN / Inf model outputs were **silent**: the active C arm went mute with no fallback (3 cases); a NaN probability would pass `p_commit` | silent failure | D6: finite check → fallback; the commit policy rejects non-finite time / probability | fallback "model produced a non-finite prediction" in all 3 cases (§6.1) |
| F-6 | Audio device removal was **silent**: callbacks stopped, nothing detected or retried it, and a re-attached device was never reopened (callbacks 306 → 102) | silent failure | D7: supervision, retries, no backlog burst | DOWN after 0.5 s, recovered on the first retry after re-attach, mixer cleared (§6.3); TEST-FI-AUD-1..3 |
| F-7 | Missing camera = traceback; no user messages, structured log or crash report | usability | D8 | message SD-CAM-001 and exit code 3; event log and crash reports with hashes (TEST-SYS-1..5, TEST-APP-11..14) |
| F-8 | Identity **swaps** make arm A commit a strike for the wrong hand and arms B / C invent strikes from the teleported track (rule set-up: A 53, B 68 fabricated over 152 swap runs); nearby hands' swaps are indistinguishable from real motion | residual risk (not an invariant violation) | none possible below the identity layer; single-user rule D9 for background hands; documented | unchanged (by design) |
| F-9 | The **development C-GRU** commits strikes under out-of-distribution inputs where A and B do not (pre-fix, fabricated over 152 runs each: background hand 48, swaps 116, lateral exit 12, drops / stalls / FPS dips 36) | residual risk (model) | none in Phase 17 (no model changes); a shipped model must pass this campaign | background hand, swaps and lateral exit unchanged; drops / stalls / FPS dips 36 → 12 after the time-gap reset (§5.2) |
| F-10 | After a reset, **arm B anticipates from a fresh two-frame history**: an occlusion that ends while a fake-out stroke is still moving adds a B commit (10–13 of 336 post-hoc placements, at every `g_max`) | residual risk (arm B) | none in Phase 17; a post-re-acquisition warm-up for B is proposed for Phase 18 (ADR-0041) | measured in §4.3 |

Apart from F-1 (found by the 540-run switch suite), no pre-fix run violated an invariant: not the
2,736 SYNTHETIC injection runs, and not the 88 developer-capture runs. Every crash and silent
failure is listed above. F-10 was found by the re-acquisition sweep (§4.3), after the fixes.

## 3. Safety invariants (Task 17.2)

### 3.1 Replay set

Run `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0105-invariant-replay` (`scripts/invariant_replay.py`, final source tree) covered every recording and
labelled SYNTHETIC session in the repository. Each ran in three arm set-ups: A, B or the
development C-GRU sounding, the others shadowing.

| Source | Set-up | Replays | Frames | Commits audited | Violations |
|---|---|---:|---:|---:|---:|
| Developer recordings with raw frames (3 swing captures, 3 P05 dev sessions, the P06 DEV ingest) through real perception | A / B / C-GRU | 7 / 7 / 7 | 1,199 each | 6 / 6 / 33 | **0** |
| SYNTHETIC P07 session (recorded observations, 37.7 s) | A / B / C-GRU | 1 / 1 / 1 | 1,131 each | 37 / 37 / 60 | **0** |
| Every SYNTHETIC scenario of `app.synthetic`, two noise levels | A / B / C-GRU | 24 / 24 / 24 | 1,536 each | 59 / 59 / 80 | **0** |
| **Total** | | **96** | **11,598** | **377** | **0** |

- **Checks made** (so the zero is not vacuous): I1 377, I2 389,834, I3 560, I4 400, I5 377,
  I6 11,964.
- **Phase 09 harness.** The harness replay of the SYNTHETIC P07 causal tracks under
  `CommitAuditor` gave arm A 33 commits and arm B 4, with 42 observed entry episodes and **0**
  violations.
- **Constructed violations.** `TEST-INV-1` shows every invariant firing on one, including the
  audible I3/I4 break of F-1 and a future-stamped commit for I2.

**TEST-CAUSAL-1 on the hardened live loop (system level, replay mode).** For each developer swing
capture and set-up, the frames after the midpoint were perturbed in three ways:
- **GARBAGE:** replaced by uniform noise;
- **REMOVED:** dropped;
- **SHIFTED:** taken from another capture.

All **27** runs kept every record at frames up to the cut bit-identical (maximum deviation 0,
including model predictions).

Non-vacuity: 21 of the 27 runs changed or removed post-cut track records.
- **exp-5:** all 170 records changed in every run.
- **exp-6:** GARBAGE 22, REMOVED 170, **SHIFTED 0**. The donor capture for SHIFTED is exp-6
  itself, so that perturbation was a no-op there. This is a flaw of the check, recorded here.
- **exp-7** (an absence case): GARBAGE 0, REMOVED 170, SHIFTED 24.

The component-level TEST-CAUSAL-1/2 suites passed in the same verification's pytest run. The
Phase 13 raw parity and future-blackout check passed on all three captures.

### 3.2 Live mode (assertion set)

Run `experiments/phase-17/20260927-0026-live-assertions/` ran the invariants in **`raise`** mode
(a violation stops the session with a crash report). It was unattended: the camera was on (DSHOW
640×480, 30 FPS requested) and no one was playing. The camera-only part detected no hand; in the
scripted part, real perception briefly reported a right hand in the first second, before any
scripted stroke. Config: `configs/live.arm-C.candidate.yaml` (C-GRU sounding, A and B shadowing).

| Part | Frames (FPS) | Commits | Audio events | Checks: I1 / I2 / I3 / I4 / I5 / I6 | Violations |
|---|---|---|---:|---|---:|
| Camera only: the product CLI `python -m spacedrums.app.main --source live --no-window --invariants raise --max-seconds 120`, fault injection disabled | 3,623 (30.19) | 0 (no hand in view) | 0 | 0 / 10,987 / 0 / 0 / 1 / 3,623 | **0** |
| Camera + SYNTHETIC scripted strokes every 4 s (`soak_test.py` `ScriptedStrokes` through the test-build observation hook; 31 windows, 1,086 injected frames; played samples at 10 % gain) | 3,620 (30.18) | A 30 (shadow), B 24 (sounding) | 24 | 54 / 26,600 / 78 / 78 / 55 / 3,668 | **0** |

In both parts the development C-GRU fell back to B at start-up: its total processing p95 was over
the configured budget on HW-01 (the Phase 16 finding). SD-MDL-001 was logged and I5 checked the
fallback frame.
- **Capture.** Camera-only: 0 drops, 1 stall counted. Scripted: 1 drop, 0 stalls.
- **Per-frame processing.** p95 38.6 / 38.4 ms.
- **Health and event log.** The health monitor and the event log recorded every transition:
  scripted part 60 transitions (SD-TRK-001 ×30 and SD-TRK-002 ×30 as the scripted hand appeared
  and vanished), camera-only part 2.
- **Late audio.** All 24 audio events were counted **late** by the mixer: the target time had
  already passed when the buffer was filled, so they were played at once (Phase 04 policy). The
  run did not record how late; the soak records the per-event lead (see `soak-report.md`).

**Reproduction.** Part 1 is the product CLI shown in the table. Part 2 ran through a small wrapper
around `run()`, archived with the evidence as `live_assertions.py` (not in the repository). The
nearest repository command is `python scripts/soak_test.py --minutes 2 --stroke-every-s 4`; it runs
the monitor in `log` mode, so it counts violations instead of stopping on the first one.

**Causality in live mode:** TEST-CAUSAL-1 (prefix invariance under a perturbed future) is a
replay-mode test by construction. In live mode the causality rule is enforced by I2 in `raise`
mode: 37,587 checks, 0 violations. A live session with a person at the camera is PENDING (§9).

**Participant replay set: PENDING.** No participant dataset (ds-v1.0) exists; the same script runs
on it unchanged once it does.

## 4. Tracking and vision faults (Task 17.3)

### 4.1 SYNTHETIC injection grid

Source: `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0111-inject-all/injection-synthetic.json`.

2,736 runs (152 per set-up and fault kind): **0 crashes, 0 invariant violations** (pre-fix: 0 / 0).
The table sums audible deltas against the unperturbed run over positions and durations
(fabricated = no same-hand strike within 0.3 s; mistimed = a real strike committed outside W):

| Set-up | Fault | Fabricated (+) | Mistimed (+) | FN (+) | Fabricated by arm (A / B / C-GRU) |
|---|---|---:|---:|---:|---|
| rule (A sounds) | OCCLUSION | 0 | 6 | 83 | 0 / 0 / – |
| | OUT_OF_ROI | 0 | 1 | 80 | 0 / 0 / – |
| | LOW_CONF (0.45) | 0 | 0 | 82 | 0 / 0 / – |
| | BACKGROUND_HAND | 0 | 0 | 57 | 0 / 0 / – |
| | SWAP | 53 | 1 | 101 | **53 / 68** / – |
| model (C-GRU sounds) | OCCLUSION | 0 | 5 | 0 | 0 / 0 / 0 |
| | OUT_OF_ROI | 12 | 17 | 0 | 0 / 0 / **12** |
| | LOW_CONF | 2 | 0 | 0 | 0 / 0 / 2 |
| | BACKGROUND_HAND | 48 | 69 | 0 | 0 / 0 / **48** |
| | SWAP | 116 | 47 | 0 | 53 / 54 / **116** |

- **Model set-up FN column.** It is 0 because the unperturbed reference already misses every
  strike. The development C-GRU matches 0 of the analytic strikes on these sequences; this is a
  property of that model, not of the faults.
- **Rule set-up by position.** Every loss-type fault fabricated **nothing** at the approach, the
  impact or idle.
  - FNs concentrate at the impact (occlusion 67, out-of-ROI 64, low confidence 67).
  - They also occur when a loss ends just before the crossing (16): the re-acquired track has no
    previous observed point from which to detect the entry.
- **The 6 mistimed occlusion commits.** These strikes were committed on the first frame after a
  ≤ 100 ms bridge, from a crossing between the last bridged point and the new observation. They
  are late by more than W (failure catalogue F1).

**State transitions** (OCCLUSION, hand VALID before the fault): the README §8 sequence held in
**152 / 152** occlusion runs per set-up:
- DEGRADED for `g_max` = 3 frames;
- then INVALID with `GAP_EXCEEDED`;
- STALE once the last valid time is older than `age_max` = 0.5 s.

The occluded hand made zero commits while it was not VALID (monitor I1; zero violations).

**Re-acquisition (MEASURED, SYNTHETIC input).**
- The first frame with a clean observation (confidence 0.9 ≥ `c_valid`) is VALID immediately
  (0 ms) for every duration.
- For losses ≥ 200 ms, the rule arm predicts again 33.3 ms later (`n_min_frames` = 2) and the
  development model 233.3 ms later (its N = 8 frame window refills). A 100 ms loss is bridged, so
  nothing is reset.
- Three 1000 ms losses that end at the sequence end have no re-acquisition frame.

### 4.2 Developer captures through real perception

Each developer swing capture was replayed through real perception (MediaPipe hands + stick
estimator) with image and capture faults, in both set-ups: 200 runs in
`experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0111-inject-all/injection-devcapture.json`; the pre-fix campaign covered exp-5 only, 88 runs. These
captures have **no ground truth**, so an outcome is the change against the unperturbed replay of
the same capture: audible commits added or removed within frames [start − 3, end + 15] (hand, zone
and arm agree within ±2 frames).

Faults: an occluder mask around one hand's reference position for 3 / 6 / 9 / 30 frames, at two
anchors (one and two thirds through the hand's live frames); the same hand's half of the ROI blanked
(out of ROI) for the same spans; lighting steps (30 frames mid-capture) and session-wide changes
(gain 0.35; gain 0.2 with gamma 1.6; gain 1.8 with gamma 0.7); a dark bar sweeping the upper
background for the whole capture (distractor); a 3- and a 9-frame stall, a 3-frame drop burst, a
6-frame timestamp jump and a 30-frame FPS dip, all mid-capture.

| Capture (unperturbed tracking) | Unperturbed audible commits, rule / model set-up | Runs | Crashes | Invariant violations | Rule set-up: added / removed | Model set-up: added / removed |
|---|---|---:|---:|---:|---|---|
| exp-5 (VALID in 68 % of hand-frames; unperturbed strikes: left snare, right tom1) | 2 (A) / 9 (C-GRU) | 88 | 0 | 0 | 2 / 8 | 20 / 88 |
| exp-6 (VALID in 5 % of hand-frames, STALE in 53 %) | 0 / 0 | 88 | 0 | 0 | 0 / 0 | 1 / 0 |
| exp-7 (absence case: no hand) | 0 / 0 | 24 | 0 | 0 | 0 / 0 | 0 / 0 |

- **Rule set-up (A sounding): faults removed strikes and never added one, except one lighting
  case.** The 30-frame occluder and the 30-frame out-of-ROI mask covering exp-5's tom1 strike
  removed it; the 3–9-frame masks at the anchors changed nothing. Session-wide dimming (gain 0.35,
  and 0.2 with gamma 1.6) removed both strikes. The distractor removed the left snare strike. The
  session-wide **bright** change (gain 1.8, gamma 0.7) removed the tom1 strike and **added two left
  snare commits** (frames 13 and 24, 0.17 s and 0.53 s after the unperturbed strike at frame 8).
  With no truth they cannot be classified; they are the only additions in the rule set-up and are
  recorded as a limitation (failure catalogue: strong over-exposure).
- **Model set-up (development C-GRU sounding):** its own nine unperturbed strikes on exp-5 are
  unverified. Faults removed 88 of them and added 20 commits: occluder 4, out-of-ROI 4, the bright
  session change 6, the distractor 6. On exp-6 the bright session change added one commit.
- **exp-7:** no commit in any run, including every lighting change and the distractor. The moving
  bar was never taken for a stick.
- **Capture faults** at mid-capture changed nothing in the rule set-up. In the model set-up the
  FPS dip removed three C-GRU commits.
- **Pre-fix vs post-fix:** exp-5's 88 runs gave identical outcomes before and after the fixes
  (added 22 / removed 96 in both campaigns).

**Re-acquisition through real perception (MEASURED, developer captures).** This is the time from the
first frame after an occluder / out-of-ROI mask to the hand's first VALID frame, and to the next
prediction.
- **exp-5 (32 runs):**
  - VALID: median 48.9 ms, p90 159.7 ms, max 258.6 ms;
  - the rule arm predicts again: median 127.7 ms, p90 223.7 ms, max 463.4 ms (31 runs);
  - the development model predicts again: median 280.5 ms, p90 633.2 ms, max 767.3 ms;
  - status on the first frame after the mask: INVALID 18, VALID 6, DEGRADED 5, STALE 3.
- **exp-6:** median 2,856 ms, p90 3,434 ms, max 3,488 ms. exp-6's hands are rarely VALID even
  without a fault, so this is the time to that capture's next VALID frame, not a recovery property.
- **Summary:** re-acquisition through real perception takes one to several frames longer than the
  SYNTHETIC 0 ms (the detector needs a confident frame again). The pooled figure in the campaign
  JSON (`reacquisition_valid`: median 112 ms, p90 3,344 ms over 64 runs) mixes the two captures and
  should not be quoted alone.

### 4.3 Re-acquisition thresholds `g_max_frames` / `age_max_s` (decision, ADR-0041)

`scripts/reacquisition_experiment.py` swept `g_max_frames` ∈ {1, 2, 3, 4, 6} ×
`age_max_s` ∈ {0.25, 0.5, 1.0} s. Arms A and B, rule set-up.
- **Evidence run:** `experiments/phase-17/20260927-0047-reacquisition-experiment/` (clean audit;
  repeated in `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0145-reacquisition-experiment`).
- **Faults:** 643 SYNTHETIC injection cases per point: losses of 1–15 frames; confidence 0.45 for
  3–36 frames, clean or with position jitter; stalls of 2–6 frames.
- **Also run:** the P07 session, the developer captures, and occluded fake-outs (216 declared
  placements plus 336 post-hoc placements).
- **Result:** 0 violations and 0 crashes at every point.

| `g_max_frames` (`age_max_s` 0.5) | FP + FN, A + B | A FP (mistimed) / FN | B FN | Fabricated: injection / fake-outs (declared) / fake-outs (post-hoc) |
|---:|---:|---|---:|---|
| 1 | 587 | 0 / 351 | 236 | 0 / 4 / 13 |
| 2 | 571 | 2 / 333 | 236 | 0 / 4 / 12 |
| 3 (candidate) | 585 | 15 / 332 | 238 | 0 / 4 / 12 |
| 4 | 586 | 15 / 332 | 239 | 0 / 4 / 11 |
| 6 | 593 | 15 / 332 | 246 | 0 / 3 / 10 |

- **`age_max_s`: 0.5 s is best at every `g_max`.** FP + FN at 0.25 / 0.5 / 1.0 s is
  591 / 585 / 586 at 3. It has no effect on fabrication, P07 or any developer-capture commit.
- **`g_max` 2 vs 3.** At 3, a 3-frame loss or stall is bridged, and arm A commits the strike inside
  it late (13 mistimed). At 2, the strike is lost.
- **`g_max` 6 vs 3.** At 6, losses and stalls of 4–6 frames are bridged, and B misses 8 more
  strikes.
- **Fabricated strikes.** They come only from arm B's post-reset anticipation on fake-outs (F-10).
  Longer bridges avoid a few of these resets, but losses longer than `g_max` fabricate equally at
  every point.
- **P07 and developer captures.** P07 scores are identical at every point, and no developer-capture
  commit changes.

The **declared rule selects `g_max_frames = 6`, `age_max_s = 0.5`** (only the g6 points have the
fewest fabricated strikes). The post-hoc sensitivity selects the same.

**Owner decision (2026-09-27): `g_max_frames = 3` is kept** and `age_max_s = 0.5` confirmed.
Keeping 3 is an **explicit engineering deviation from the pre-declared sweep rule**. The reasons
are in ADR-0041:
- the deciding difference is 1–2 B commits in several hundred placements;
- the choice sits at the grid's edge;
- D3 / D4 are tied to 3.

By the owner's instruction, the campaign was not re-run at 6. Every other number in this report
was measured at 3.

### 4.4 Fast hits: maximum separable hit rate (Open Question; SYNTHETIC)

Source: `inject_faults.py --suite fasthit` (`experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0111-inject-all/injection-fasthit.json`).
- **Strokes:** eight noise-free SYNTHETIC strokes at a fixed inter-onset interval (IOI) per
  pattern. The down-stroke scales with the IOI (`t_down = 0.4 × IOI`, at most 0.2 s).
- **Scoring:** both set-ups; Phase 09 matcher, W = 50 ms.
- **Table:** matched strikes of 8 in the rule set-up (A and B FP 0 throughout). In the model
  set-up A is identical, and B differs only at 0.12 and 0.08 s (±1).

| Pattern | Arm | 0.4 s | 0.3 s | 0.2 s | 0.15 s | 0.12 s | 0.1 s | 0.08 s |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| one hand, one zone | A | 8 | 8 | 0 | 4 | 2 | 0 | 2 |
| | B | 8 | 8 | 8 | 0 | 1 | 1 | 0 |
| alternating hands, one zone | A | 8 | 8 | 0 | 4 | 3 | 0 | 2 |
| | B | 8 | 8 | 8 | 4 | 5 | 8 | 1 |
| alternating hands, two zones | A | 8 | 8 | 0 | 4 | 3 | 0 | 2 |
| | B | 8 | 8 | 8 | 4 | 5 | 8 | 1 |

- **Monotone bound.** Every pattern is fully separated down to an IOI of **0.3 s** by A
  (3.3 hits/s) and **0.2 s** by B (5 hits/s).
- **Below that the outcome is not monotone in the IOI.** Two examples: A scores 0/8 at 0.2 s but
  4/8 at 0.15 s; B alternating scores 4/8 at 0.15 s but 8/8 at 0.1 s.
- **Likely cause: frame sampling, not the commit logic.**
  - Results are all-or-nothing at IOIs that are whole multiples of the 33.3 ms frame period
    (0.4, 0.3, 0.2 and 0.1 s; every stroke then has the same frame phase), and partial in between.
  - The one exception sits at the refractory boundary: one hand on one zone at 0.1 s, where
    `r_zone` = 0.10 s applies (B 1/8).
  - That fits frame sampling of down-strokes of 80 ms or less.
  - The commit logic cannot explain the pattern: `r_zone` only limits same-hand, same-zone hits
    0.1 s apart or closer.
- **Misleading JSON field.** The campaign JSON's `smallest_separable_ioi_s` (the smallest IOI with
  ≥ 95 % matched and 0 FP) reports 0.1 s for B on alternating patterns because of this
  non-monotonicity. The bounds above are the monotone ones.
- **Development C-GRU:** matches at most 6/8 at any IOI, with FPs.
- **Violations:** 105 runs, 0.
- **Real sticks:** the maximum separable rate with real sticks is a developer-played measurement,
  PENDING.

### 4.5 Live physical tests — PENDING

**Tests:** a person occludes a hand with the other hand or an object, for ~100–300 ms and longer,
during the approach, at the impact and while idle; and switches or dims the room light while
playing.

**Procedure:**
- `scripts/induced_loss_test.py --live` (Phase 05);
- `python -m spacedrums.app.main --source live --record --invariants raise --log-dir <dir>`.

The monitor must report zero violations, and the event log records every health transition.

Not executed: no person was at the camera.

## 5. Capture and timing faults (Task 17.4)

### 5.1 Live source (fake camera behind `LiveFrameSource`)

Source: `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0111-inject-all/injection-capture-live.json`.

| Case | Pre-fix | Post-fix |
|---|---|---|
| Driver timestamps whose hand-over lag (50 ms) exceeds the frame interval (10 ms), DRIVER_MAPPED | **crash** after 9 frames (equal stamps) | 193 frames delivered, 4 refused and counted, 0 violations |
| Driver clock jumps back 5 s | 197 frames, mapper disabled → GRAB_RETURN | unchanged |
| Driver clock jumps ahead 2 s | 197 frames, 140 stamps clamped to hand-over time | unchanged (failure catalogue F10) |
| Grab clock steps back 50 ms | **crash** after 57 frames | 192 delivered, 5 refused, 0 violations |
| 300 ms camera stall | no crash, 1 stall counted | no crash; the next frame resets the tracker (D3) |
| Disconnect (40 reads) and re-attach | no crash | no crash; stall counted; frames resume |

The replay source now refuses a recording whose `t_capture` does not strictly increase
(TEST-FI-CAP-2). No existing recording is affected (maximum frame interval 82 ms).

These cases run a real capture thread, so their frame counts depend on thread timing. The
disconnect case delivered 197 frames with 0 queue drops in one run, and 186 with 11 in the final
verification. Every other count above was identical in both runs.

### 5.2 SYNTHETIC stalls, drop bursts, clock jumps and FPS dips (same grid as §4.1)

| Set-up | Fault | Fabricated pre → post | Mistimed pre → post | FN pre → post |
|---|---|---|---|---|
| rule | STALL | 0 → 0 | 7 → 7 | 98 → 102 |
| | DROP_BURST | 0 → 0 | 0 → 7 | 103 → 102 |
| | TIMESTAMP_JUMP (forward) | 0 → 0 | 0 → 0 | 0 → 0 |
| | FPS_CHANGE (15 FPS dips) | 0 → 0 | 5 → 5 | 22 → 22 |
| model | STALL | 11 → **1** | 17 → 9 | 0 → 0 |
| | DROP_BURST | 15 → **1** | 16 → 11 | 0 → 0 |
| | TIMESTAMP_JUMP | 6 → **3** | 26 → 16 | 13 → 13 |
| | FPS_CHANGE | 10 → 10 | 39 → 39 | 0 → 0 |

- **Development model.** The time-gap reset (D3) removed most of its stall and drop fabrications:
  its input window no longer spans the gap.
- **Rule set-up.**
  - The guard change (D4, 1 → 3) lets up to three missing frames through: +7 mistimed commits
    after drop bursts, balanced by −1 FN.
  - Stalls longer than 150 ms now reset the tracker (+4 FN): strikes inside a long stall are lost
    instead of committed late.

**Drop accounting and `dt` handling.**
- **Accounting:** queue drops are counted per delivered frame. A stall's missing frames are
  inferred from `dt` (`frames_missing`, D4). Both feed the commit guard.
- **Tracker:** it predicts with the measured `dt`. An interval above `(g_max + 1.5)` frame periods
  resets it, together with its history and the model window.
- **Model arm:** it checks the frame cadence (15-frame median, ±25 %) and falls back on a
  sustained mismatch.
- **Rule arm:** it uses the measured `dt`.

TEST-FI-CAP-3..6 cover drop accounting, the gap reset, the stall-inferred guard, and FPS dips
with forward clock jumps.

### 5.3 Frame-drop guard threshold (decision, ADR-0040 D4)

**Rule declared before the run** (`inject_faults.py`, `GUARD_RULE`):
- choose `commit.max_dropped_since_last` to minimise FP + FN (Phase 09 matcher, W = 50 ms) summed
  over arms A and B;
- the test set: stalls and drop bursts of 1–3 frames placed around each crossing, plus sustained
  15 and 10 FPS;
- ties go to the stricter guard;
- zero fabricated FP is required.

212 SYNTHETIC cases per arm and threshold. Decision run:
`experiments/phase-17/20260926-2248-guard-experiment/`, reproduced exactly in `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0111-inject-all`.

| Threshold | A: matched / FP / FN | B: matched / FP / FN | FP + FN (A + B) | Fabricated |
|---:|---|---|---:|---:|
| 0 | 438 / 0 / 230 | 108 / 0 / 560 | 790 | 0 |
| 1 (previous candidate) | 483 / 10 / 185 | 116 / 0 / 552 | 747 | 0 |
| 2 | 526 / 46 / 142 | 116 / 0 / 552 | 740 | 0 |
| **3 (chosen)** | **564 / 68 / 104** | 116 / 0 / 552 | **724** | 0 |
| no guard | 564 / 68 / 104 | 116 / 0 / 552 | 724 | 0 |

- **Guard 1 → 3.** It recovers 81 strikes for arm A at the cost of 58 late commits outside W: real
  strikes committed late, none invented. B is unaffected above 1.
- **15 FPS:** A 13 matched / 4 FP / 6 FN of 19 at guards 1–3.
- **10 FPS:** at guard ≥ 2, A 5 / 14 / 14 (mostly late); at guards 0–1, A commits nothing.
- **B at low frame rates:** at 10 FPS B commits nothing at any guard; at 15 FPS it gets 2 of 19.
- **Candidates changed:** the prototype and `live.arm-C` candidates went from 1 to 3 (=
  `g_max_frames`).
- **Pinned config unchanged:** `configs/perf.developer.candidate.yaml`, pinned by the Phase 16
  frozen regression, keeps 1.

## 6. Model and audio faults, arm switches (Task 17.5)

### 6.1 Model faults (C-GRU sounding, A and B shadow; SYNTHETIC alternating strokes)

Source: `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0111-inject-all/injection-model.json`.

| Fault | Pre-fix | Post-fix |
|---|---|---|
| Package missing / wrong export hash / malformed manifest JSON / wrong feature dimension | fallback to B at load | unchanged |
| Manifest with a wrongly typed field (`dt_step: "fast"`) | **crash** at construction (`TypeError`) | fallback to B at load |
| Export corrupted (64 zeroed bytes) *and re-hashed into the config* | loads; identical commits to the reference | unchanged: the corruption hit non-semantic bytes; the SHA-256 pin is the protection (a re-hashed file is by construction a different, owner-accepted package) |
| Slow inference (+50 ms per call) | fallback: inference p95 budget | unchanged |
| `RuntimeError` mid-session | fallback | unchanged |
| `TypeError` / `IndexError` / `KeyError` / `FloatingPointError` mid-session | **crash** | fallback to B |
| NaN / Inf trajectories (after 20 calls, or from the start) | **silent**: C mute, no fallback | fallback: "model produced a non-finite prediction" |

In every fallback:
- no commit is made in the fallback frame (I5);
- the model makes no commit afterwards;
- the sounding arm becomes B (A when B is not configured).

Unit tests TEST-FI-MDL-1..5 use the analytic TorchScript fixture. They also cover
`ZeroDivisionError`, `AttributeError` and a missing export file.

### 6.2 Runtime arm switch / fallback (Phase 18 commit-threshold range)

Source: `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0111-inject-all/injection-switch.json`.

540 runs covered `p_commit` ∈ {0.5, 0.3, 0.1} × `tti_commit_s` ∈ {0.05, 0.10, 0.15} × six
SYNTHETIC sequences × {B → A, A → B}, with the switch 1–5 frames after the sounding arm's first
commit.

| `p_commit` | `tti_commit_s` | Runs with audible I3 + I4 violations, pre-fix | Post-fix |
|---:|---:|---:|---:|
| 0.1 | 0.10 / 0.15 | 3 / 5 | 0 / 0 |
| 0.3 | 0.10 / 0.15 | 3 / 3 | 0 / 0 |
| every other cell | | 0 | 0 |

Before the fix, every violation had the same mechanism:
1. B sounded a strike 1–2 frames before its crossing.
2. The switch skipped one frame.
3. A's reactive crossing sounded the same strike again 66.7 ms later.

### 6.3 Audio device (fake PortAudio stream; SYNTHETIC strokes)

Source: `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0111-inject-all/injection-audio.json`.

| Case | Pre-fix | Post-fix |
|---|---|---|
| Device removed mid-session | callbacks stop (306 → 102); nothing detected; voices queue | DOWN after 0.5 s without callbacks; strikes still scheduled and logged, 2 not queued (`dropped_while_down`); a retry fails while absent |
| Removed then re-attached | never reopened; silent for the rest of the session | reopened on the first retry after re-attach (1 recovery); mixer cleared (no backlog burst); later strikes sound |
| Start with no device | exception at `audio.start()` → application stops | DOWN, retried every 1 s, recovers when the device appears (TEST-FI-AUD-2) |
| 10 underruns in a burst | counted | counted; state stays RUNNING; late events played late and counted (Phase 04 policy) |

**Physical device removal / re-attach on HW-01: PENDING.** The internal Realtek output cannot be
unplugged; a USB or Bluetooth output and a person are needed.

## 7. Background people and objects (Task 17.6)

- **Background hand reported as the user's** (observation level, §4.1): arms A and B produced
  **0** fabricated strikes; the development C-GRU produced 48. Rule set-up FN +57: the substituted
  hand hides the real strokes.
- **Moving distractor** in the upper background of the developer captures (§4.2): the rule
  set-up added no strike. On exp-5 it removed one A strike. On exp-7 (no hand) no commit appeared.
- **Single-user identity rule** (ADR-0040 D9, config 1.8, off by default), tested by
  TEST-FI-ID-1..4:
  - a much smaller detection that appears while a user hand is lost is rejected
    (`BACKGROUND_REJECTED`) with the rule on, and adopted with it off;
  - two similarly sized user hands are never rejected.
- **Live second-person test: PENDING** (needs two people).
  - **Setup:** a second person moves and air-drums behind the player at 1–3 m, for two minutes
    each with the rule off and with it at 0.35.
  - **Count:** identity events, audible strikes during the player's idle periods (target 0), and
    invariant violations.

## 8. DEGRADED commits (Task 17.7; ADR-0039)

`scripts/degraded_experiment.py` compared P0 (commits in VALID only, the default) with P1 (VALID +
DEGRADED) on paired runs. Its decision rule was declared before the first P1 run.
- **Decision run:** `experiments/phase-17/20260926-2250-degraded-experiment/`.
- **Repeat:** identical in `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0142-degraded-experiment` (0 differences in the full JSON).

| Evidence | Arm | P0 | P1 |
|---|---|---|---|
| Phase 09 harness, SYNTHETIC P07 session (32 positives; 9 DEGRADED frames) | A / B | 32 / 4 matched | identical |
| SYNTHETIC injected occlusion (2, 3, 6 frames) and low confidence (3, 9 frames), approach / impact / idle, 375 strikes per arm | A | 347 matched, 28 FN, 0 fabricated | **361 matched, 14 FN**, 0 fabricated |
| | B | 78 matched, 297 FN | identical |
| | C-GRU | 81 fabricated | **84 fabricated** |
| SYNTHETIC fake-outs (a stroke stopping 2–20 mm above the surface, occluded around the stop), 432 placements | A | **0** commits | **45 fabricated strikes** |
| | B | 139 | 139 |
| Developer capture exp-5 (81 DEGRADED frames; no truth) | A | 2 commits | 4 (+2, unverifiable) |

- **Violations:** 0 in every run of both policies.
- **Where the gain comes from:** all of A's FN reduction comes from low-confidence frames observed
  at the impact.
- **Where the fabrications come from:** all of them come from **bridged** frames, where the filter's
  extrapolation crosses a surface the real stick never reached.
- **Decision: DEGRADED commits stay off.** P1 fails the declared rule because A fabricates 45
  strikes on occluded fake-outs.

## 9. Limitations of this evidence and PENDING

- **What the evidence is.** Everything above is development evidence: SYNTHETIC kinematics,
  three short developer captures (one without hands, one with hands rarely VALID), a
  synthetic-trained model and a fake audio backend.
- **What the zeros mean.** The zero-violation and zero-fabrication results hold for these inputs
  only.
- **What a shipped model must do.** It must repeat §4.1, §5.2 and §6.1 before Phase 18 relies on
  it.
- **PENDING:**
  - the participant replay set (Task 17.2; ds-v1.0 does not exist);
  - physical occlusion and lighting tests (§4.5);
  - the second-person test (§7);
  - physical audio-device removal (§6.3);
  - the developer-played fast-hit measurement (§4.4);
  - a person-played soak (`soak-report.md`);
  - participant confirmation of the re-acquisition thresholds (ADR-0041; `g_max_frames` 3 kept by
    owner decision against the declared rule's 6);
  - the clean post-owner-commit re-run of `scripts/verify_phase17.py --require-clean`.

## 10. Runs

| Run | Content |
|---|---|
| `experiments/phase-17/dependencies/20260926-1459-gate-verification/` | Phase 16 post-owner-commit verification (clean tree) |
| `experiments/phase-17/20260926-1542-prefix-inject-core/`, `20260926-1554-prefix-inject-devcapture/` | pre-fix campaign |
| `experiments/phase-17/20260926-2248-guard-experiment/` | frame-drop guard decision run |
| `experiments/phase-17/20260926-2250-degraded-experiment/` | DEGRADED decision run |
| `experiments/phase-17/20260926-2300-p17-gate-verification/`, `20260926-2312-…` | **aborted** verifications (`ABORTED.md`: tracked schema examples rewritten by a test mid-run; soak sampler defects found by a dry run) |
| `experiments/phase-17/20260926-2327-p17-gate-verification/` | full verification before the re-acquisition sweep existed (12 commands passed) |
| `experiments/phase-17/20260927-0026-live-assertions/` | live-mode assertion set (§3.2; wrapper archived as `live_assertions.py`) |
| `experiments/phase-17/20260927-0038-reacquisition-experiment/` | **aborted** preview (`ABORTED.md`: scripts edited during the run) |
| `experiments/phase-17/20260927-0047-reacquisition-experiment/` | re-acquisition threshold sweep (§4.3) |
| `experiments/phase-17/20260927-0053-p17-gate-verification/` | **final gate verification** (13 commands) with `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0105-invariant-replay`, `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0111-inject-all`, `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0142-degraded-experiment`, `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0145-reacquisition-experiment` |
| `experiments/phase-17/20260927-0150-soak-60min/` | 60-minute soak (`soak-report.md`) |
