# Phase 18 live-session protocol (Experiment 2)

**Phase:** 18 — Task 18.4. **Status:** protocol IMPLEMENTED as machinery (`scripts/run_live_session.py`,
`spacedrums.live_eval.protocol`); protocol version `0.1-draft` until the developer pilot freezes it.
**No live session with a person has been run.**

Governing documents:

- design: pre-registration [§9](../experiments/phase-18-prereg.md);
- method acceptance: [§8](../experiments/phase-18-prereg.md);
- exclusions: [§7](../experiments/phase-18-prereg.md).

Person-dependent steps are marked **PERSON**.

## 1. Preconditions (all required before the first participant)

| # | Precondition | Where it is recorded | Status 2026-09-27 |
|---|---|---|---|
| 1 | Ethics question answered; consent form CF-v0.1 plus the live addendum approved | `docs/ethics/ethics-approval-note.md` | **Open Question** |
| 2 | Pre-registration approved by the owner and the supervisor (by hash) | `docs/experiments/phase-18-prereg.hashes.json` → `approvals` | PENDING |
| 3 | Shipped model and live config frozen; live model hash equals the offline lock's `C` | live lock `live.config_sha256`, `live.model` | PENDING (no shipped model; ADR-0030) |
| 4 | Developer pilot of M1 / M2 done; `methods.json` decides GO / NO-GO | `docs/reports/phase-18-external-methods.md` | M1 click part only (see report); pad and M2 PENDING |
| 5 | Live lock archived (config, model, arm mapping, Williams sequences, methods, questionnaire decision) | `confirmatory_lock.py archive` | PENDING |
| 6 | Calibration wizard (Phase 14) works live for the operator | `docs/user/calibration.md` | PENDING (Phase 14 live calibration) |
| 7 | Live B runs at the offline lock's `b_primary` (ADR-0036 amendment), and a model-fallback policy is declared | ADR-0036 amendment; live lock | PENDING (live report §3, findings 1 and 4) |

## 2. Equipment (record what is actually used in `LiveSessionMetadata.external_methods`)

| Item | Needed for | Inventoried? |
|---|---|---|
| HW-01 laptop, integrated webcam, speakers | every session | yes (HW-01) |
| Two ordinary drumsticks | every session | Open Question (hardware inventory) |
| Practice pad | M1 PAD blocks | **no** (Open Question) |
| Microphone near pad and speaker (the built-in array only if the click check passes at the position used) | M1 | built-in array only; external mic **no** |
| Phone with high-frame-rate video (≥ 200 FPS) and an LED or flash reference | M2 | **no** |
| Metronome cue (the protocol's on-screen tempo) | TEMPO segments | software |

## 3. Session flow (operator script)

1. **Consent** (**PERSON**). Consent is taken per session: CF-v0.1 plus the live addendum
   ([`consent-form-live-addendum.md`](../ethics/consent-form-live-addendum.md)). Record:
   - the consent record id;
   - whether the participant is also a dataset participant (`--overlap-with-dataset`).
2. **Participant index.** The next unused 1-based index for this study. It fixes the Williams arm
   order: sequence `(index − 1) mod 6`. Never re-draw an order: a repeated session keeps its index.
3. **Calibration** (**PERSON**): `python -m spacedrums.app.calibrate --user-tag <pseudonym>`.
   - With M1, place the pad first and fit the pad zone so that its impact surface coincides with
     the pad surface in the image.
   - Check with five test strikes before continuing.
   - Keep the calibration file; its hash goes into both metadata documents.
4. **Start the session** (**PERSON**):

   ```powershell
   .venv/Scripts/python.exe scripts/run_live_session.py --live --kind PARTICIPANT --participant P01 `
       --participant-index 1 --consent-status SIGNED --consent-record-id <id> `
       --calibration configs/calibration/<file>.calib.yaml --pad-zone snare --mic-device <mic> `
       --overlap-with-dataset NO --executor-model "<who runs it>" --executor-effort "n/a"
   ```

5. **Blocks.** The participant sees zones and cues only (blinded). The console prints each block's
   arm for the operator.
   - Keys: `n` next segment, `r` re-take, `k` skip, `m` clap marker, `f` fallback note, `q` quit.
   - Do **not** tell the participant which arm is sounding.
   - If a model fallback message appears, note the time: it is logged, and the block continues
     as-treated (pre-registration §7.2, item 4).
   - A fallback disables the model **for the rest of the session**, even when it happens while C
     only runs in shadow. The live config has `automatic_recovery: false`, so every later switch to
     C is refused ("model unavailable; restart after correcting the recorded fault"). The C blocks
     then sound with the previous arm, and C gets no data. What the operator does then is an Open
     Question for the owner (§6).
6. **PAD blocks** (M1). Single hits on the pad, about one per second, one block per arm in the
   same order.
7. **Questionnaire** (only if the owner decided to include it, pre-registration §1):
   [`phase-18-questionnaire.md`](phase-18-questionnaire.md). Record answers under the session's
   pseudonym only.
8. **After the session:**
   - `python scripts/external_sync.py --session <dir> --method M1 --recording <dir>/audio_track.wav`;
   - Phase 07 labels for the session (`scripts/build_labels.py --session <dir> ...`, then review);
   - `python scripts/analyze_live.py --session <dir> ... --lock-live <archived live lock>`.

## 4. Block content (candidate durations × `--duration-scale`)

| Block | Segments (Phase 06 types) | Candidate duration |
|---|---|---|
| b0 familiarisation (arm A; not analysed) | SINGLE_HITS on any zone | 30 s |
| b1–b3 AIR, one per arm | SINGLE_HITS per zone (10 s each), ALTERNATING_ONE_ZONE (15 s), TEMPO medium 100 bpm (15 s), FAKE_SWING (15 s), STOP_BEFORE_IMPACT (15 s) | ≈ 100 s with four zones |
| p1–p3 PAD, one per arm (M1 only) | PAD_MIC on the pad zone | 30 s each |

Total, excluding calibration and questionnaire: 420 s (7 minutes) of cued playing at scale 1.0
with four zones. That is 30 + 3 × 100 + 3 × 30 s: an arithmetic candidate, never a measured session
length.

## 5. What the session records

| Document | Content |
|---|---|
| `metadata.json` | Phase 06 `SessionMetadata`, unchanged schema; segments and takes; consent; calibration |
| `live-session.json` | `LiveSessionMetadata`: arm order and Williams index, blocks with spans and switches, commits per arm (sounding / shadow), fallbacks, external methods with recording hashes and sync, blinding, questionnaire, dataset overlap, pre-registration version and hash |
| record streams, `timing.jsonl`, `session.json` | as every Phase 05 / 13 recording; shadow commits are logged, never scheduled |
| `audio_track.wav` | the M1 microphone track (only with PAD blocks and `--mic-device`) |

## 6. Stop rules

- The participant asks to stop: stop immediately. Completed blocks are kept (§7.2 of the
  pre-registration).
- Camera, tracking or audio health FAIL (the application's messages): pause, fix, then re-take the
  segment. Takes are kept and flagged, never deleted.
- A model fallback: continue. The fallback arm sounds for the **rest of the session**, not only the
  block: later switches to C are refused. This is reported.
  - The SYNTHETIC rehearsal inside the final verification showed it:
    `experiments/phase-18/20260927-1258-p18-gate-verification/20260927-1323-live-rehearsal/`.
    The shadow C-GRU's inference p95 exceeded the 10 ms budget over 30 frames at session time
    140.2 s, while B was sounding, and both later C blocks were refused.
  - **Open Question (owner, before the live lock).** Choose between:
    - a model warm-up with a health check before each C block;
    - restarting the application and re-running the missing C blocks (a protocol amendment);
    - a recovery policy in the live config;
    - accepting the loss (the participant then leaves the paired C analysis, pre-registration
      §7.2, item 5).
