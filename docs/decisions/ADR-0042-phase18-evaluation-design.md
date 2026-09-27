# ADR-0042 — Phase 18 evaluation design: two-stage pre-registration, live protocol and timing methods

Status: **IMPLEMENTED development machinery; owner review PENDING.** Decisions D2 (matching reference)
and D7 (M1 thresholds) carry Open Questions for the owner. No participant result exists.
Date: 2026-09-27. Phase: 18 (Tasks 18.1–18.9). Related: ADR-0007, ADR-0012, ADR-0023, ADR-0024,
ADR-0025, ADR-0027, ADR-0030, ADR-0036, ADR-0037; `docs/experiments/phase-18-prereg.md`.

## Context

Phase 18 must run one pre-registered confirmatory comparison of A, B and C: offline on held-out
participants, and live with external timing. Its upstream inputs are all PENDING on 2026-09-27:

- `ds-v1.0`;
- `W_PRIMARY_S` and `DELTA_PROC_LIVE_S` (both `None` in `eval/constants.py`);
- the owner budgets (ADR-0025);
- the operating points (ADR-0024);
- the shipped model (ADR-0030);
- the Phase 04 output latency;
- the Phase 07 acoustic validation;
- the ethics answer.

The design must let the protocol be fixed now, before any data exists, while the numbers are
fixed later. It must also keep the Phase 09 harness frozen.

## Decisions

**D1. Two-stage pre-registration.**

- `phase-18-prereg.md` fixes rules and symbols. Its CRLF-normalised SHA-256 is appended to the
  tracked, append-only `phase-18-prereg.hashes.json` (`scripts/prereg_archive.py`).
- Upstream values go into frozen-inputs **locks**: an offline lock before Experiment 1 and a live
  lock before the first live participant (schema `confirmatory-lock`, validated by
  `live_eval.prereg.lock_errors`). A lock with any `PENDING` placeholder, an inconsistent arm or
  budget, or a stale pre-registration version cannot be archived.
- The offline runner refuses to start unless all of the following hold:
  - the lock is archived after the latest pre-registration version;
  - every locked pipeline source digest is unchanged;
  - a participant lock runs on a clean tree;
  - the ledger has no earlier execution of this lock, unless a reviewed retry reason is recorded.
- The ledger (`phase-18-confirmatory-ledger.jsonl`) reserves the run before test data is read.

**D2. Matching stays ADR-0023; README §10.1 becomes a pre-declared sensitivity (S1).**

- The frozen harness pairs on `t_commit`, not on `t_impact_pred` as README §10.1 describes.
  Phase 18 found that this discrepancy was not recorded anywhere.
- Consequences under ADR-0023: every matched `L_pred` lies in [−W, +W], and a commit made more than
  `W` early counts as FP + FN.
- The primary analysis follows the frozen rule. S1 re-pairs on `t_ref` through the unchanged
  `evaluate_session` and recomputes leads from `t_commit`.
- **Open Question (owner, before the offline lock):** keep ADR-0023 as primary, or amend ADR-0023
  and the pre-registration to make §10.1 primary.

**D3. Decision rules on participant-bootstrap intervals.**

- Participant-bootstrap intervals only: 10,000 resamples, seed 18, percentile 95 %.
- Every hypothesis has a failure reading, and C-vs-B is two-sided with a `δ_lead` materiality
  qualifier.
- For P ≤ 3 the interval equals [min, max] of the participant values. Rule P07-SPLIT-1 gives
  P_test = 2–3 at the planned 10–12 participants, so the pre-registration states that the offline
  decisions then read "every held-out participant meets the criterion".

**D4. `spacedrums.live_eval` package** (top layer, a sibling of `spacedrums.app` in `.importlinter`).

- It contains the analysis layer over the frozen harness, TEST-CAUSAL-1 for evaluated arms, the
  live protocol, `LiveSessionMetadata`, sync and the M1 / M2 / M3 methods.
- `spacedrums.eval` is untouched. Adding a file there would change the harness hash set.

**D5. `LiveSessionMetadata` by composition.**

- `live-session.json` sits next to the unchanged Phase 06 `metadata.json`, references it by
  SHA-256, and repeats its identity fields; `consistency_errors` checks them.
- The closed Phase 06 schema (`additionalProperties: false`) rules out adding fields to it
  without a Phase 06 schema bump that every dataset tool would inherit.

**D6. Live design.**

- Arms A / B / C are blocked within participant, in a Williams order (six sequences), with index
  `(participant − 1) mod 6`.
- Content per block: single hits per zone, alternating, medium tempo, fake swing,
  stop-before-impact. PAD blocks follow for M1.
- The participant view is blinded with `--overlay-mode off` and the runner's own hooks (zones and
  cues; no arm name), with **no change to `app` or `ui`**.
- Attribution is as-treated, by the commit record's `arm`.

**D7. M1 measurement method** (pad + microphone; pre-registration §8).

- Speaker onsets come from normalised cross-correlation with the played bank sample, refined to
  sub-sample precision.
- Pad onsets come from the Phase 06/07 detector on the residual after subtracting the fitted
  sounds.
- Latency is the within-recording difference, so the microphone path cancels.
- Sync to `t_mono`: the recorded sounds are aligned with the software `AudioEvent.t_target_play`
  train. The system's own drum sounds are the sync events, and they give per-strike `strike_id`
  attribution.
- GO thresholds (candidates; the owner may amend them before the live lock): click
  |bias| ≤ 1 ms and e95 ≤ 2 ms over ≥ 30 pairs; pad pairing ≥ 90 % of ≥ 30 strikes;
  `U_M1 = sqrt(e95² + r_pad²) ≤ 5 ms`.

**D8. TEST-CAUSAL-1 on the exact evaluated arms** (GARBAGE / REMOVED / SHIFTED).

- Runs on two SYNTHETIC fixture sessions, never test data.
- Cuts: every 10th frame plus candidate and reset frames, capped at 40 evenly spaced cuts per
  session (CPU).
- Tolerance: `1e-6` for learned arms; `t_inference_done` (wall clock) excluded.
- Each perturbation kind reports whether it was effective, so a vacuous pass is visible.

## Consequences

- The confirmatory run can happen once the upstream inputs exist, without re-deciding any rule.
  Any later change of a rule is a new pre-registered run, reported beside the original.
- The SYNTHETIC rehearsals exercise every runner end to end, but they are machinery, never
  evidence.
- The W-cap finding (D2) affects how Phase 10–12 leads are interpreted. It is reported in the
  limitations and carried to the owner.
- **Live B needs its own operating point (open; owner).** The live rehearsal showed that
  `DecisionPipeline` builds arm B from the model config's `anticipator` block (ADR-0036: "the same
  configured K/step applies to B"). With the development model (K = 1), live B looks only 33 ms
  ahead instead of its locked K. The live lock may not be archived until the live configuration runs
  B at the offline lock's `b_primary` settings; that needs an ADR-0036 amendment.
- **M1 on the built-in microphone is NO_GO** (click-pair check failed twice). An external
  microphone is a precondition of the M1 pad pilot.
- **Live fallback policy (open; owner).** The live config's model fallback (`automatic_recovery:
  false`) also fires while C runs in shadow. It disables C for the rest of the session, so later C
  blocks are refused. This happened in one of two SYNTHETIC live rehearsals. The live lock needs a
  declared policy first: warm-up and health check, restart and re-run, a recovery setting, or
  accepting the loss.
- No threshold, model or harness change is made in Phase 18.
