# Phase 18 — Final evaluation report

**Status: PENDING — the confirmatory evaluation has not been carried out.** The machinery for it is
complete: implemented, tested and rehearsed end to end on SYNTHETIC data. No hypothesis has a
participant result.

## Pre-registration (verified)

| Field | Value |
|---|---|
| Document | [`docs/experiments/phase-18-prereg.md`](../experiments/phase-18-prereg.md) |
| Archived version | 1 |
| SHA-256 (CRLF-normalised) | `sha256:e901f280efb4681d35607a072909d9409e9aeaf3ab1c128112769f8c25793ba0` |
| Archived at | 2026-09-27T08:44:07+03:00 (HEAD `6730b81…`, before any Phase 18 runner touched any data) |
| Hash record | [`docs/experiments/phase-18-prereg.hashes.json`](../experiments/phase-18-prereg.hashes.json) |
| Approval (owner / supervisor) | **PENDING** (`scripts/prereg_archive.py approve`) |
| Locks archived against it | none (the offline and live locks need upstream inputs that do not exist) |

`scripts/prereg_archive.py verify --cite docs/reports/phase-18-final-evaluation.md` checks two
things: that the document matches this digest, and that this report quotes it. The check runs in
`verify_phase18.py`.

## 1. Hypotheses: participant outcomes

Every hypothesis is **PENDING**. The table gives no decision because none exists. The decision
rules and failure readings are fixed in pre-registration §3 and §6.

| Hypothesis | Decides (pre-registration §3) | Participant outcome | Missing input | Decision path exercised on SYNTHETIC data |
|---|---|---|---|---|
| H1a | C's median `L_pred` > 0 at the FP budget | **PENDING** | `ds-v1.0` test participants; offline lock (W, `Δ_proc`, budgets, operating points, shipped model) | yes: `20260927-1237-offline-rehearsal` |
| H1b | C leads A, paired per participant | **PENDING** | as H1a | yes: same run |
| CB | C versus B at the same FP budget (two-sided, `δ_lead` materiality) | **PENDING** | as H1a | yes: same run |
| H2 | C's FP/min ≤ the budget | **PENDING** | as H1a | yes: same run (and S1) |
| H3 | C's `TE_pred` MAE ≤ `δ_TE` | **PENDING** | as H1a, plus the owner's `δ_audio` and, for the physical bound, the Phase 07 acoustic spread | yes: same run |
| H4 | externally measured action-to-sound latency C < A by more than the method uncertainty | **PENDING, no claim** | a GO external method (none: M1 NO_GO on the built-in microphone, M2 not piloted); ethics answer; live participants; live lock | yes: `20260927-1257-analyze-live` (one SYNTHETIC participant) |
| H4-B | as H4, for B | **PENDING, no claim** | as H4, plus the implemented ADR-0036 amendment (live B at its locked settings) | yes: same run |

The rehearsal outcomes stay in the experiment reports, where they are labelled SYNTHETIC. They
say nothing about participants, the models or the research question, and this report does not
repeat them.

## 2. What exists on 2026-09-27

- **Protocol.** Pre-registration version 1 (above); the live protocol, the questionnaire draft
  and the consent addendum draft CF-LIVE-v0.1; ADR-0042 (design decisions D1–D8).
- **Machinery.**
  - `spacedrums.live_eval`: statistics, hypotheses, pre-registration records and ledger,
    counterbalancing, the live protocol, `LiveSessionMetadata`, sync, M1 / M2 / M3, offline
    metrics and TEST-CAUSAL-1 on evaluated arms.
  - Schemas: `confirmatory-lock` and `live-session-metadata`.
  - Nine Phase 18 scripts and three helper modules (`scripts/README.md`, Phase 18 section).
  - Tests: `tests/live_eval/` and `tests/scripts/test_phase18_scripts.py`.
- **SYNTHETIC rehearsals** (machinery, never evidence):
  - the offline chain: rehearsal lock, confirmatory runner with its self-checks, and regeneration
    from stored results and from raw data (0 differences);
  - the live chain: session, Phase 07 labels, M1 sync and live analysis;
  - the method self-test.

  Each is described with its run ids in the experiment reports.
- **One developer measurement (no person).** M1 part (i), the known-separation click check,
  **failed** twice on HW-01's built-in microphone array (0 of 40 pairs). M1 is therefore NO_GO with
  that microphone (MEASURED developer pilot; `20260927-1228` / `-1230-methods-m1-clicks`,
  decision `20260927-1232-methods-decide`).
- **Cross-run determinism.** The final verification repeated the offline chain from scratch, with
  a new lock and retrained models. It reproduced every metric, interval and decision of the first
  chain exactly (offline report §2.1). This is machinery, not evidence.
- **Seven findings for the owner:**
  1. ADR-0023 pairs on `t_commit`, which caps every matched lead at `W`. S1 is the pre-declared
     sensitivity; the owner kept ADR-0023 primary (A1).
  2. P_test = 2–3 makes every participant interval equal to [min, max] of the participant values;
     the owner kept the rule and the planned count (D1).
  3. The frozen geometry has a boundary edge case (limitation T20).
  4. Live B inherits the model's horizon, and all live arms share one `commit` block. The owner
     amended ADR-0036 (live B at the offline-locked settings, per-arm commit settings); the
     implementation is PENDING before the live lock.
  5. The arm switch lags by one frame; attribution is as-treated.
  6. M1 is NO_GO on the built-in microphone; M1 with an external microphone stays primary (E1).
  7. One model fallback, even in shadow, removes C from the rest of a live session (limitation
     T21). The owner kept the fallback and accepted the loss (C1).

  The offline report §3 covers finding 1, the live report §3 findings 4 and 7, and the
  limitations the rest; the gate record numbers them the same way.

## 3. What does not exist

- No `ds-v1.0`, so **no offline confirmatory run**: the offline lock cannot be archived, and the
  runner refuses without it.
- **No live session with a person.** Live participants: 0. Developer live sessions under the
  Phase 18 protocol: 0. The ethics answer is an Open Question since Phase 00.
- **No validated external timing method.** M1 is NO_GO on the built-in microphone and PENDING with
  an external one; M2 is PENDING (no ≥ 200 FPS camera or LED reference); M3 is an estimate by
  definition.
- **No effective-latency number.** Following README §5.4 and REQ-060c, the thesis may not claim a
  latency reduction, or sound before the physical impact.
- No questionnaire data. Including Experiment 3 is an Open Question.
- No second-person regeneration check.

## 4. Integrity

- **Pre-registration precedence.**
  - The document was archived at 08:44:07. The first Phase 18 runner started at 12:27
    (`20260927-1227-methods-selftest`), and no Phase 18 runner has touched participant data.
  - The rehearsal lock was archived in a run-local copy of the hash record. The tracked record
    holds one version, no lock and no approval.
- **Labels.** Every number in the Phase 18 reports is one of: a declared rule; a candidate; a
  SYNTHETIC rehearsal value with its run id; a MEASURED developer pilot value with its run id; or
  PENDING. None is a participant result.
- **Code state.** All Phase 18 runs used a **dirty** tree (Phase 18 uncommitted), so they are
  development evidence. The clean re-run (`verify_phase18.py --require-clean`) waits for the owner
  commit.
- **Executor.** Claude Opus 5.5 via Claude Code, recorded in each run's `execution.json` and in
  `experiments/phase-18/execution-start.json`. The recommended GPT-6 Astra was not used.
- **Frozen code.** The Phase 09 harness (`spacedrums.eval`), the models, the thresholds, `app` and
  `ui` are unchanged. Phase 18 added a package, schemas, scripts, tests and documents.

## 5. Path to a result (owner actions, in order)

1. Decisions A1, B, C1, D1 and E1 were recorded on 2026-09-27 (gate record, "Owner decisions");
   none changes the pre-registration text. Approve version 1 with `prereg_archive.py approve`,
   with the answers in the note. The questionnaire can stay open until the first live session.
2. **Experiment 1** (after `ds-v1.0`, W, `Δ_proc`, the budgets, the operating points and the
   shipped model exist):
   1. `confirmatory_lock.py template`, then `validate`, then `archive`, on a clean tree;
   2. `run_offline_confirmatory.py --lock …`, run **once**;
   3. `regenerate_phase18.py`, then a second person repeats it.
3. **Experiment 2** (after the ethics answer, signed consent, an external microphone and a practice
   pad, the implemented and re-verified ADR-0036 amendment, and the live lock):
   1. M1 part (i) with the external microphone;
   2. the developer pad pilot and the M1 decision;
   3. live sessions with `run_live_session.py`;
   4. `external_sync.py`, then `analyze_live.py`.
4. This report is then rewritten from the experiment reports, keeping the pre-registration hash
   above.

## 6. Reports

| Report | Task | Status |
|---|---|---|
| [`phase-18-offline-confirmatory.md`](phase-18-offline-confirmatory.md) | 18.2, 18.7 | PENDING; SYNTHETIC rehearsal and findings |
| [`phase-18-external-methods.md`](phase-18-external-methods.md) | 18.3 | M1 NO_GO (built-in microphone); M2 PENDING; M3 estimate only |
| [`phase-18-live-results.md`](phase-18-live-results.md) | 18.4, 18.5 | PENDING; SYNTHETIC rehearsal and findings |
| [`phase-18-effective-latency.md`](phase-18-effective-latency.md) | 18.6 | PENDING, no claim |
| [`phase-18-limitations.md`](phase-18-limitations.md) | 18.8 | threats register complete for the design |
| Reproducibility: `scripts/regenerate_phase18.py`, `scripts/verify_phase18.py` | 18.9 | regeneration passed on the rehearsal; second-person check PENDING |
| Gate record: [`../gates/phase-18-gate.md`](../gates/phase-18-gate.md) | — | PENDING reviewer |
