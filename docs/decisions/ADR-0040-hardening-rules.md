# ADR-0040 — Safety invariants, fault handling and hardening rules

Status: IMPLEMENTED (development evidence); every threshold below is a **candidate**; live,
person-dependent and participant confirmation PENDING.
Date: 2026-09-26. Phase: 17. Related: ADR-0006 (per-hand state), ADR-0013 (capture timestamps),
ADR-0016 (state machine), ADR-0018 (commit policy), ADR-0036 (live model arm, sticky fallback),
ADR-0039 (DEGRADED commits), ADR-0041 (re-acquisition thresholds: `g_max_frames` = 3 kept by owner
decision, a deviation from the declared sweep rule; D3 and D4 are tied to it).

## Context

Phase 17 added the runtime safety-invariant monitor (I1–I6) and a deterministic fault injector,
recorded a **pre-fix** campaign on the unmodified decision logic
(`experiments/phase-17/20260926-1542-prefix-inject-core/`,
`experiments/phase-17/20260926-1554-prefix-inject-devcapture/`) and found:

1. **Audible double strike across an arm switch / model fallback** (I3 + I4 on the audible
   stream): 14 of 540 switch runs over the Phase 18 threshold sweep range (`p_commit ≤ 0.3`,
   `tti_commit_s ≥ 0.10`). The arm that starts sounding had its own (shadow) refractory timers
   and episode flags, so a reactive commit replayed the strike the previous arm had just sounded.
2. **Frame intervals longer than the bridging allowance were not gaps.** A 300 ms camera stall
   never reset the tracker (one Kalman prediction over the whole gap), while the same time without
   *detections* resets after `g_max_frames` = 3. Stalls let the reactive arm commit 93–162 ms late
   from a crossing interpolated across the gap; a +0.2 s timestamp jump made the filter's
   extrapolation cross the snare surface one frame before the observed tip did.
3. **The live capture source could stop the application.** A `t_capture` that did not increase
   was clamped to an *equal* stamp, which `DecisionPipeline.step` rejects (`ValueError`): reproduced
   for driver-mapped stamps whose hand-over lag exceeds the frame interval and for a backward
   grab-clock step. TEST-CONFORM-7 only asserted non-decreasing stamps.
4. **Model faults other than `OSError`/`ValueError`/`RuntimeError` crashed the application**
   (`TypeError`, `IndexError`, `KeyError`, `FloatingPointError` at inference; a manifest with a
   wrongly typed field at load), and **non-finite model outputs were silent**: the active C arm
   went mute with no fallback. A NaN strike probability would also pass the `p_commit` gate
   (`nan < p_commit` is false).
5. **Audio device loss was silent**: callbacks stopped, nothing detected it, nothing retried, and
   voices queued forever; a re-attached device was never reopened.
6. A missing camera surfaced as a traceback; there were no user messages, no structured event log
   and no crash report.
7. Background people: the identity layer adopts any second detection when a user hand is lost.

## Decisions

**D1 Safety-invariant monitor.** `spacedrums.app.invariants.InvariantMonitor` audits every frame
result: I1 no commit outside the allowed statuses; I2 no record with `t_capture` after the current
frame (frames strictly increase; a reactive crossing time never after the frame; no commit decided
before its frame; tracker/model histories hold delivered frames only); I3 refractory per hand ×
zone and per hand, per arm stream and for the **audible** stream; I4 at most one commit per observed
entry episode, per arm and audible stream (an anticipatory commit belongs to the first entry seen
while `t_now ≤ t_impact_target + stale_prediction_tolerance_s`, mirroring the commit machine);
I5 no commit in a switch/fallback frame, none from a disabled model arm, `shadow` exactly for
non-active arms; I6 every audio event belongs to a non-shadow commit of the same frame and the
engine schedules nothing else. Modes: `raise` (test builds), `log` (application default,
`--invariants`), `collect` (campaigns). The I1/I3/I4 core (`commit.invariants.CommitAuditor`) also
audits Phase 09 harness output. The monitor is an auditor: it may wait for later frames to
attribute a commit and never feeds a decision.

**D2 Audible continuity across an arm switch.** On `ARM_SWITCH` a commit machine discards ARMED
progress only; its episode flags (tip inside, pending anticipated entry, committed-in-episode)
persist — geometry keeps its episodes on a switch, and the flags can only suppress. The arm that
starts sounding then **absorbs** the refractory timers (latest wins) and open-episode flags of the
arm that stops sounding (`PerHandCommitPolicy.absorb_suppression`). Only suppression moves between
arms; a decision in progress never does. Reset matrix (architecture.md §6.2) amended.

**D3 Time-gap tracking rule.** A frame interval above `(g_max_frames + 1.5) / requested_fps`
(150 ms at the candidate 30 FPS / `g_max_frames = 3`: more than `g_max` frames missing) is a gap:
the tracker resets with `GAP_EXCEEDED` before processing the frame and re-acquires from its
observation (no extrapolation across the gap; geometry and commit state for the hand reset as for
any tracking loss). Derived from existing parameters, so no new config key and no change to
`tracker_id`; no existing recording has a frame interval above 82 ms.

**D4 Missing-frame commit guard.** `commit.frames_missing = max(dropped_since_last,
round(dt / nominal_dt) − 1)`: a camera stall leaves the same sparse trajectory as queue drops, so
the guard `commit.max_dropped_since_last` applies to both. The live pipeline and the Phase 09
harness (`replay(..., nominal_dt_s=...)`, used by the Phase 13 parity path) compute it identically.
**Threshold (Task 17.4):** rule declared before the run — choose the value minimising FP + FN
(Phase 09 matcher, W = 50 ms candidate) summed over arms A and B on stalls / drop bursts of 1–3
frames around each crossing plus sustained 15 and 10 FPS; ties to the stricter value; zero
fabricated FP required. Run `experiments/phase-17/20260926-2248-guard-experiment/` (SYNTHETIC,
212 injected cases per arm and threshold): FP + FN = 790 / 747 / 740 / **724** / 724 for thresholds
0 / 1 / 2 / **3** / none, zero fabricated FP at every threshold. For arm A, 1 → 3 recovers 81
strikes (matched 483 → 564) at the cost of 58 **late** commits outside W (FP 10 → 68; mistimed real
strikes, none invented); arm B is unaffected above 1. **Candidate value changed from 1 to 3
(= `g_max_frames`)** in `configs/prototype.candidate.yaml` and `configs/live.arm-C.candidate.yaml`.
It matches the tracker's bridging allowance: after ≤ 3 missing frames the track is bridged and a
commit may follow; ≥ 4 missing frames (> 150 ms) already reset the tracker (D3). The
Phase 16-pinned `configs/perf.developer.candidate.yaml` keeps 1 (its frozen regression compares
`commit_policy_id`, which contains the value); `example.candidate.yaml` is the schema example.
At a sustained ~10 FPS (Phase 02: auto-exposure in a dark room) arm A then commits, mostly late
(5 matched, 14 mistimed of 19); the health monitor reports the low frame rate (SD-CAP-001).

**D5 Capture timestamps.** The live source never delivers a non-increasing `t_capture`: such a
frame is refused and counted (`CaptureStats.clamped_timestamps`, detail
`timestamp_report()["refused_non_monotone"]`; the session-metadata schema is unchanged). The replay
source refuses a recording whose `t_capture` does not strictly increase at load instead of the
pipeline stopping mid-run.

**D6 Model faults are fallbacks.** Any exception while loading or running the model triggers the
sticky fallback (ADR-0036), never a crash. A prediction with a non-finite position, probability,
TTI or intensity is a model fault. Defence in depth: the commit policy rejects a candidate whose
reference time is not finite (`REJECT_STALE`) or whose probability is not `>= p_commit`
(`REJECT_PROBABILITY`, which also rejects NaN).

**D7 Audio supervision.** `AudioOutput.check_health` (once per frame): no callback for
`STALL_S = 0.5 s` or a failed start → `DOWN`; restart attempts every `RETRY_S = 1.0 s` (both
candidates). While `DOWN` a commit is still scheduled and logged (`AudioEvent`) but not queued
(`dropped_while_down`); a restart clears the mixer so a recovered device never plays a backlog.
Underrun bursts keep the Phase 04 late-event policy (played late, counted).

**D8 Health, messages, logs, crash reports.** `app.health.HealthMonitor` exposes
`HealthStatus {camera, tracking, model, audio}` (OK / WARN / FAIL / OFF, candidate thresholds in
`HealthSettings`) to the overlay and the dashboard. `app.errors` holds the message catalogue
(`docs/testing/user-messages.md`), the structured JSONL event log (`--log-dir`; `data/logs` for
live sessions) and crash reports with config / model / calibration hashes. A missing camera is
message `SD-CAM-001` and exit code 3.

**D9 Single-user identity rule (Task 17.6 Open Question).** Rule chosen: the user is the person
closest to the camera, so a detection whose box area is below `user_min_relative_area` × the user's
hand size (the larger of the largest detection in the frame and the running size of assigned
hands) is a background hand and is never assigned; temporal continuity (Phase 03) stays the primary
identity cue. Config schema **1.8** adds the optional `hands.identity.user_min_relative_area`;
**default 0 (off)**, candidate 0.35, until the live two-person test (PENDING) sets the value. The
ROI stand-here band was not used: a background person can stand anywhere behind the user.

**D10 Fault injection is test-build only.** `spacedrums.app.faults` refuses unless
`SPACEDRUMS_FAULT_INJECTION=1` (set by the test suites and the Phase 17 scripts); the application
CLI never reaches it (`run(observation_hook=...)` checks the same guard).

## Consequences

- No model changed; no retraining; no record schema or DEGRADED default changed (ADR-0039). The only
  commit threshold changed is the frame-drop guard (D4, 1 → 3, by the pre-declared rule). Config
  schema 1.8 is a minor, optional bump. The four Phase 07 SYNTHETIC schema examples
  (`schemas/examples/{label-record,label-set,reference-track,dataset-manifest}.valid.example.json`)
  embed the prototype config's hash and were regenerated with `scripts/_p07_examples.py` (only the
  embedded hashes changed).
- Decision-identical on the frozen Phase 16 regression inputs (no switches, no interval above the
  gap threshold, no missing frame above the guard); the re-run is recorded in the Phase 17 gate.
- Residual risks (failure catalogue): identity swaps can make arm A sound a strike for the wrong
  hand and arms B/C invent strikes from the teleported track — only the identity layer can
  prevent this; the synthetic-trained development C-GRU commits strikes under out-of-distribution
  inputs (swaps, background hands, lateral exits) where A and B do not; physical occlusion,
  lighting, two-person and device-removal tests need a person and remain PENDING.
