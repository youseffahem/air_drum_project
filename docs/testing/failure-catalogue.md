# Failure catalogue and limitations (Phase 17, Task 17.10)

Status: development evidence (SYNTHETIC sequences, the three developer swing captures, a
synthetic-trained development model, HW-01). Every threshold is a candidate (ADR-0040). Numbers
cite `failure-injection-report.md` (FIR) and `soak-report.md`; person-dependent and participant
confirmations are PENDING and listed in §3. Feeds the Phase 21 limitations section.

Legend — **Detection**: how the system notices; **Behaviour**: what it does (safety first: no
strike is ever committed on a track that is not VALID, README §8); **Message**: catalogue code
(`user-messages.md`); **Residual risk**: what can still go wrong after Phase 17.

## 1. Failure modes

| # | Failure mode | Detection | Behaviour | Message | Residual risk |
|---|---|---|---|---|---|
| F1 | Short tracking loss / occlusion (≤ `g_max` = 3 frames ≈ 100 ms) | no usable observation (absent or confidence < `c_min`) | DEGRADED bridge (existing state only, confidence decays); **no commit** while DEGRADED (ADR-0039); geometry keeps following the bridge | SD-TRK-001 if persistent | a strike inside the gap is committed **late** at re-acquisition (crossing between the last bridged point and the new observation) or lost: FP + FN in the metrics, never an invented strike (FIR §4.1; `g_max` 3 / `age_max` 0.5 kept by owner decision, `g_max` 3 an explicit deviation from the declared sweep rule's 6: ADR-0041, FIR §4.3) |
| F2 | Longer tracking loss (> `g_max`), incl. the ~100–300 ms Q35 case | gap counter > `g_max` | INVALID + reset (`GAP_EXCEEDED`: filter, history, features, model window, commit FSM, geometry episode); STALE after `age_max` = 0.5 s; zero commits; re-acquisition needs `conf ≥ c_valid`; prediction warm-up (rule 2 frames, model N frames) | SD-TRK-001 if persistent | strikes during the loss are lost (FN); re-acquisition time MEASURED in FIR §4.1 (SYNTHETIC: VALID on the first clean frame) and §4.2 (real perception: median 49 ms, max 259 ms on exp-5) |
| F3 | Hand leaves the ROI | the detector (ROI input) sees no hand | as F1/F2 | SD-TRK-001 | as F1/F2 |
| F4 | Lighting change (dim / bright / step) | detection and stick segmentation confidence drop; the camera may lower its frame rate | VALID fraction falls (dim gain 0.35: 0 % VALID on the developer capture) → no commits; frames and timestamps stay valid | SD-TRK-001, SD-CAP-001 | **dark sticks in dim light are unsupported**; no strike is invented but the kit goes silent; strong over-exposure (gain 1.8) added two unverifiable arm-A commits on one developer capture (FIR §4.2) |
| F5 | Identity swap (LEFT/RIGHT exchanged) | Phase 03 identity events (`IDENTITY_JUMP`, `AMBIGUOUS` caps confidence) | tracks follow the observations they are given | — (logged identity events) | **open**: arm A can sound a strike for the wrong hand, arms B/C can invent strikes from the teleported track; swaps between nearby hands are kinematically indistinguishable from real motion, so only the identity layer can prevent them (FIR §4.1) |
| F6 | Second person / background hands | box-size single-user rule (ADR-0040 D9, config 1.8, **off by default**) | with the rule on, a much smaller detection is never assigned (`BACKGROUND_REJECTED`); with it off, a background hand can take over a lost user hand | — | the live two-person test is PENDING; rule off until it sets the threshold |
| F7 | Background objects / distractors | none needed | no strike from a moving distractor on the developer capture with arms A/B | — | the development C-GRU reacts to small input changes (FIR §4.2) |
| F8 | Camera stall (no frames) | live source waits; health `stall_s` = 0.5 s | nothing is processed; the next frame after a gap > 150 ms resets the tracker (ADR-0040 D3) instead of extrapolating across it | SD-CAM-002 | strikes during the stall are lost |
| F9 | Frame-drop bursts (processing behind the camera) | queue drops counted per delivered frame | commit guard: no commit on a frame with more than `max_dropped_since_last` = 3 missing frames (queue drops **or** stall-inferred, D4; = `g_max_frames`); more than 3 missing frames reset the tracker anyway (D3) | SD-CAP-002 | a strike right after 2–3 missing frames is committed from a crossing interpolated across the gap and can be **late** (mistimed, FIR §5.2–5.3) |
| F10 | Non-monotone / jumping timestamps | live: a stamp that does not increase is refused; replay: the recording is refused at load; forward jump > 150 ms = gap | no crash; the frame is not delivered / the tracker resets | SD-CAP-003 | a persistent forward driver-clock jump degrades stamps to hand-over time (clamped, counted) until the mapper refits |
| F11 | FPS change mid-session (e.g. dim light, auto-exposure ~10 FPS measured in Phase 02) | delivered FPS from `t_capture`; model cadence guard (15-frame median, ±25 %) | model arm falls back (sticky) on a sustained mismatch; baselines keep committing (at 15 FPS one missing frame per frame, at 10 FPS two: both within the guard) | SD-CAP-001, SD-MDL-001 | at ~10 FPS most reactive commits are late (SYNTHETIC: 5 matched, 14 mistimed of 19; FIR §5.3) |
| F12 | Model fault (exception of any type, non-finite output, slow, corrupt / wrong-schema package) | exception / finite check / p95 budgets / load verification | sticky fallback to B (else A); no commit in the fallback frame; no commit from the model afterwards; the new sounding arm inherits suppression (no double sound) | SD-MDL-001 / SD-MDL-002 | a corrupt export that loads and returns finite garbage is not detectable (it behaves like a bad model) |
| F13 | Arm switch (user key or fallback) | transition counter | no commit in the switch frame; ARMED progress dropped; refractory + open-episode suppression carried to the sounding arm (D2) | — | none known after the fix (FIR §6.2) |
| F14 | Audio device removed / failing | no callback for 0.5 s or start failure | DOWN: strikes still scheduled and logged, not queued; retry every 1 s; mixer cleared on recovery | SD-AUD-001 / SD-AUD-003 | physical removal / re-attach on HW-01 not exercised (fake PortAudio only) |
| F15 | Audio underrun burst | PortAudio `output_underflow` | late events played late and counted (Phase 04 policy) | SD-AUD-002 | a long burst can make sounds late |
| F16 | Camera not found | backend open fails | message and exit code 3, no traceback | SD-CAM-001 | — |
| F17 | Unexpected exception | any uncaught exception | crash report with config / model / calibration hashes, then exit | SD-APP-001 | — |
| F18 | Safety-invariant violation (defect) | runtime monitor I1–I6 | logged (application) / raised (tests) | SD-INV-001 | measured zero on the development replay set and in the live-mode assertion set (FIR §3); participant replay PENDING |
| F19 | Re-acquisition during a stroke that stops short (arm B) | none (a normal re-acquisition) | after a reset arm B anticipates from a fresh two-frame history and can commit a strike the stick never makes | — | SYNTHETIC occluded fake-outs: 10–13 added B commits in 336 placements at every `g_max` (FIR §4.3, F-10); a post-re-acquisition warm-up for B is proposed for Phase 18 (ADR-0041) |

## 2. Unresolved limitations (to be stated in Phase 21)

1. **Fast hits beyond the measured rate.** The SYNTHETIC sweep (FIR §4.4) separates every pattern
   down to an inter-onset interval of 0.3 s (arm A) / 0.2 s (arm B). Below that, frame sampling
   of short strokes decides, not the commit logic (`r_zone` = 0.10 s only limits same-hand
   same-zone hits). The real maximum separable rate with sticks is a developer-played
   measurement, PENDING.
2. **Dark sticks in dim light**: tracking fails before anything else does (F4); no low-light
   adaptation exists.
3. **Layouts far from recorded ones**: model behaviour on calibrated layouts that depart from the
   training layout is untested (ADR-0037); the geometry and commit safety paths are layout-agnostic.
4. **Identity swaps** (F5) and **background hands** (F6) remain dependent on the identity layer.
5. **The development C-GRU** (synthetic-trained, no participant data) commits strikes under
   out-of-distribution inputs where arms A and B do not; a shipped model must pass the Phase 17
   injection suites before Phase 18 relies on it.
6. **Strikes inside tracking gaps** are lost or committed late; DEGRADED commits stay off
   (ADR-0039).
7. **Physical fault tests** (occluding hand, lighting change, second person, unplugging audio)
   and a person-played soak have not been run.
8. **Anticipation lead in live runs.** In the unattended live runs (SYNTHETIC 0.15 s strokes),
   every audio event of arm B was counted late by the mixer. The lead at scheduling was at most
   +14 ms (median −4 ms, `soak-report.md`). Output latency and live-stroke delay are unmeasured
   (Phase 04 criterion 6, Phase 16), so any claim of sound before impact waits for Phase 18.

## 3. PENDING (person / participant dependent)

- Live physical occlusion and lighting-change injection (Task 17.3 live part).
- Live background-person test with a second person (Task 17.6) and the single-user threshold.
- Physical audio-device removal / re-attach on HW-01 (Task 17.5 live part).
- Person-played soak (Task 17.8) and the full participant replay set (Task 17.2) once ds-v1.0 exists.
- Developer-played fast-hit measurement with real sticks (Open Question).
- Participant confirmation of the re-acquisition thresholds (ADR-0041: `g_max` 3 kept by owner
  decision, an explicit deviation from the declared sweep rule, which selected 6).
