# Phase 18 — Experiment 2: live end-to-end timing (Tasks 18.4, 18.5)

**Status: PENDING — no live session with a person exists.**

- The live experiment needs, first:
  - the ethics answer (`docs/ethics/ethics-approval-note.md`: Open Question since Phase 00);
  - signed live-session consent (draft addendum CF-LIVE-v0.1);
  - a practice pad and a microphone (not inventoried);
  - a shipped model (ADR-0030);
  - the developer pilot of the timing methods;
  - an archived live lock.
- Live participants: **0**. Developer live sessions under the Phase 18 protocol: **0**.
- Every number below comes from a **SYNTHETIC rehearsal**: generated observations and a generated
  microphone track. It exercises the runner and the analysis chain and is never evidence.

Protocol: [`../protocols/phase-18-live-protocol.md`](../protocols/phase-18-live-protocol.md).
Design: pre-registration §9 (Williams order, blinding, as-treated attribution).

## 1. Which quantities are external and which are software-stamped (Task 18.5)

| Quantity | Source | Label when it exists |
|---|---|---|
| Action-to-sound latency per strike (`L_sys` for A, physical `TE_audio` for B / C) | M1 microphone (pad onset → sound onset), or M2 video | **MEASURED (external)**: only after the method passes pre-registration §8 |
| Sound-before-impact fraction (B / C) | M1 / M2 | MEASURED (external) |
| README §5.3 decomposition (capture, tracking, features, inference, commit, audio scheduling, audio output) per arm | `timing.jsonl` | **SOFTWARE-STAMPED**; the audio-output term is empty until Phase 04 accepts an output latency |
| `t_out − t_impact_est` per strike | `AudioEvent.t_target_play` / `t_audio_out_est` against the reviewed label | **SOFTWARE ESTIMATE** (M3); never decides H4 |
| Live FP / FN on scripted negatives; live `L_pred` | frozen harness on the recorded session with reviewed Phase 07 labels | MEASURED (software-stamped commits against geometric labels) |
| Live inference latency per arm | `timing.jsonl` inference component | MEASURED (software-stamped) |

## 2. SYNTHETIC rehearsal of the live chain

### 2.1 Runs

| Step | Run | Result |
|---|---|---|
| Session | `experiments/phase-18/20260927-1253-live-rehearsal/` | `run_live_session.py --synthetic --participant-index 1 --pad-zone snare --synthetic-mic --duration-scale 0.3`, using the live config with the SYNTHETIC-trained development GRU. Williams sequence 0 (A, B, C). 3,798 frames; all 28 segments recorded; 7 arm switches (b0 A, b1 A, b2 B, b3 C, p1 A, p2 B, p3 C); no switch refused; participant view BLINDED. `metadata.json` (Phase 06) and `live-session.json` both validate, and `consistency_errors` is empty. |
| Labels | `…/labels/` (inside the session run) | The real Phase 07 pipeline (`build_labels.py`, dataset `ds-v0.0-selftest-p18-live`): 162 labels (128 POSITIVE, 3 AMBIGUOUS, 5 NEG_BETWEEN_ZONES, 6 NEG_FAKE_SWING, 12 NEG_NO_STRIKE_MOTION, 8 NEG_UPWARD_CROSSING); separation check passed. |
| M1 sync | `experiments/phase-18/20260927-1255-external-sync-m1/` | The SYNTHETIC microphone track holds pad transients at the truth crossings (+4 ms) and every played sample 50 ms after its scheduled play time. The system's own drum sounds are the sync events: 65 matched, residual RMS 2.9 µs; status OK written into `live-session.json`. |
| Analysis | `experiments/phase-18/20260927-1257-analyze-live/` | M3, the harness on the labelled session, M1, and H4 / H4-B. The first attempt (`…-1256-analyze-live`, kept with `FAILED.md`) stopped because live strike rows lacked `session_id`; fixed. |
| Repeat in the final verification | `experiments/phase-18/20260927-1258-p18-gate-verification/20260927-1323-live-rehearsal/`, `…-1324-external-sync-m1/`, `…-1324-analyze-live/` | Same command, session and chain; every step exited 0. 3,798 frames. The shadow C-GRU **fell back** at session time 140.2 s ("inference p95 exceeds configured budget"), so both switches to C (b3, p3) were **refused** and those blocks sounded with B (finding 4 below). Labels built. M1 sync: 50 sounds matched, residual RMS 1.7 µs. M1 paired 9 A pad strikes; B and C produced no pad-block sound to pair. H4 / H4-B INCONCLUSIVE. |

### 2.2 What the chain showed (SYNTHETIC)

- **M1 recovers the known answers.** All 9 sounded pad strikes are paired. Their measured
  latencies match the known `scheduled + 50 ms − (crossing + 4 ms)` to within **0.034 ms**, bounded
  by the 1 ms onset frames. The 17 unpaired pad strikes are exactly those where B or C did not sound.
- **H4 / H4-B are INCONCLUSIVE, as declared:** one SYNTHETIC participant gives no interval, and B /
  C produced no pad-block sound to pair.
- **M3 rejects every SYNTHETIC timing record as mixed-clock.** Generated `t_capture` sits beside
  wall-clock processing stamps, so the decomposition applies to live camera sessions only. Per-strike
  M3 estimates carry "DAC path EXCLUDED".
- **Harness on the live session, arm's own blocks:**
  - A: 30 / 30 matched, 0 FP.
  - C (development GRU): 4 matched, 19 FP, 26 FN; it was trained on another fixture.
  - B: 2 matched, 28 FN (next section).
- **EXPLORATORY motion summary.** Identical ground-truth inward speed in every arm's blocks: the
  correct null for scripted strokes.

## 3. Findings for the live experiment (carried to the owner)

1. **Live arm B inherits the model's horizon.**
   - `DecisionPipeline` builds B from the config's `anticipator` block with only `type` switched to
     `rule` (`src/spacedrums/app/pipeline.py:203–204`; ADR-0036: "the same configured K/step
     applies to B").
   - With the development model (K = 1), live B extrapolates only 33 ms ahead, while the Phase 05
     prototype B uses K = 6.
   - In the rehearsal, B committed on 2 of 30 strikes.
   - A live comparison would pit C against a handicapped B. Before any live lock, the live
     configuration must run B at its locked operating point (motion model, K, τ, p): an ADR-0036
     amendment and an owner decision. Nothing was changed in Phase 18.
2. **One-frame switch lag.** A block's first frame is decided by the previous arm; the switch takes
   effect on the next frame. One A sound fell inside PAD block p2. As-treated attribution (by the
   commit's `arm`) counts it correctly, and the switch frame is recorded per block.
3. **M1 on HW-01's built-in microphone is NO_GO**
   ([`phase-18-external-methods.md`](phase-18-external-methods.md)). The live PAD blocks need an
   external microphone.
4. **One model fallback removes C from the rest of the session.**
   - The live config's fallback rule (`anticipator.fallback`: inference p95 budget 10 ms over
     30 frames, `automatic_recovery: false`) applies while C runs in shadow too.
   - Once it fires, the model stays disabled and the runner refuses every later switch to C.
   - The repeat rehearsal in the final verification hit this after 40 s of session time; the first
     rehearsal did not. It depends on wall-clock timing on HW-01, not on the data.
   - For a participant this would leave no C data: as-treated attribution stays correct, but the
     participant leaves the paired C analysis (pre-registration §7.2, item 5).
   - The policy for live sessions (warm-up and health check, restart and re-run, a recovery setting,
     or accepting the loss) is an owner decision before the live lock. Nothing was changed in
     Phase 18.

## 4. Behaviour to watch in real sessions (declared, exploratory)

- **Motion under anticipatory sound.** `analyze_live.py` reports the ground-truth inward speed at
  impact per sounding arm. A difference between arms would be a genuine system effect (the player
  hears the sound before the stroke ends). It is observed and reported, never hidden, and never
  tested (EXPLORATORY).
- **Fallback during a C block, or in shadow.** A cold or slow model call can switch C to B
  (ADR-0036). The block continues as-treated and the switch is listed per block. C then stays
  disabled for the rest of the session (finding 4).
