# Phase 18 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 18 — Evaluation & Experiments |
| Phase document | `phases/phase-18-evaluation-experiments.md` |
| Submitter | Claude Code agent acting for the project owner |
| Reviewer(s) | Project owner, and the supervisor (the gate procedure recommends supervisor sign-off for the Phase 18 pre-registration) — PENDING |
| Review date | PENDING |
| Code state | start `6730b81b261658784a33812b551acdf043a60be8`, clean; final verification on the same HEAD, **dirty** (Phase 18 changes uncommitted at the time). Owner commit `c2b6191d8683bfbd2ead5559f6735a40ebccc967` followed (2026-09-27 13:39:24 +03:00); its 499 source-audited files are byte-identical to the verified tree. The clean re-run on it is PENDING. |
| **Verdict** | **PENDING reviewer. Submitter proposes FAIL for the full phase.** Criterion 1 is MET: the pre-registration was declared and hashed before any Phase 18 runner touched data; owner / supervisor approval is PENDING. Criterion 2 is NOT MET: `ds-v1.0` does not exist, so the offline confirmatory run has not happened. Criteria 3 and 5 are PARTIAL: M1 is documented as failed on the built-in microphone; the pad and video pilots, every live session with a person, participant regeneration and the second-person check are PENDING. Criterion 4 is MET only in the PENDING form it allows: there is no effective-latency number. All machinery is implemented, tested and rehearsed end to end on SYNTHETIC data only; the final verification passed all 16 commands on the dirty tree. |

## Execution environment

| Item | Value |
|---|---|
| Model actually used | **Claude Opus 5.5** (`claude-opus-5-5`) via Claude Code (VS Code extension). The phase document's recommended GPT-6 Astra / Extra High was **not** used. |
| Reasoning effort actually used | "max", the session setting the harness reports to the agent. The Codex picker setting does not apply. |
| Execution start | 2026-09-27T06:45:22+03:00 (`experiments/phase-18/execution-start.json`) |
| Git HEAD at start | `6730b81b261658784a33812b551acdf043a60be8`, git_dirty = false |
| Final verification | `experiments/phase-18/20260927-1258-p18-gate-verification/`, 2026-09-27 12:58:35 → 13:25:04 +03:00, HEAD `6730b81…`, **dirty**. **All 16 commands exit 0**: pytest, ruff, import contracts, schemas, environment smoke, diff check, test-matrix freshness, pre-registration hash cited, method self-test, rehearsal lock, offline rehearsal, regeneration, live rehearsal, labels, M1 sync, live analysis. Untracked whitespace problems 0; `source_unchanged = true`. During the run the agent edited only documents outside the source audit (reports, this record, ADR-0042, `repo-layout.md`, RTM prose); the test-matrix freshness check was re-run afterwards and passed. |
| Executor record | Every Phase 18 run's `execution.json` carries the executor model and effort as command-line arguments, never inferred. `execution-start.json` supersedes any string hard-coded by `scripts/_p10.provenance()`. |
| Hardware | HW-01: i7-7820HQ (4 cores / 8 threads), 15.9 GB RAM, Windows 10.0.22621. Audio for the M1 pilot: "Microphone Array (Realtek Audio)" in, "Speakers / Headphones (Realtek Audio)" out, MME, 48 kHz. |

Wall-clock notes:

- Dependency verification: 06:45 → 08:43. Pre-registration archived: 08:44:07.
- The session was idle between about 08:44 and 12:24 (+03:00), waiting for the owner's "continue".
- The Phase 18 runs are from 12:27 onwards.
- Run timestamps are genuine.

## Dependency verification (before any dependent Phase 18 work)

- Phase 18 depends on the Phase 09, 10, 11, 12, 13, 14 and 17 gates.
- Each earlier executable post-owner-commit condition was closed in the phase that followed it, and
  is recorded in its gate record.
- The only outstanding condition was **Phase 17's**. It was run on the owner commit `6730b81…`, on
  a clean tree, before any Phase 18 file existed in the repository, and recorded in
  [`phase-17-gate.md`](phase-17-gate.md), "Post-owner-commit verification — 2026-09-27":

1. **Gate verifier.** Command: `scripts/verify_phase17.py --require-clean --output
   experiments/phase-18/dependencies`. Time: 06:45:33 → 07:42:22.
   - **All 13 commands passed**, including pytest with **1,441 passed, 1 skipped**.
   - Untracked whitespace problems 0; `source_unchanged = true`; `git_dirty_final = false`.
   - Evidence: `experiments/phase-18/dependencies/20260927-0645-p17-gate-verification/`.
2. **Live soak.** Command: `scripts/soak_test.py --minutes 60`. Time: 07:42 → 08:43:04.
   - 60.1 min; **no crash; 0 invariant violations**.
   - 303 capture drops, 19 stalls and 20 underruns, against 1 / 3 / 0 in the dirty-tree soak. This
     is disclosed as run-to-run variability; the cause is not identified.
   - Evidence: `experiments/phase-18/dependencies/20260927-0742-soak-60min/`.

What this does and does not close:

- It closes Phase 17's executable condition only.
- Phase 17's person-dependent tests and reviewer signature remain PENDING, and Phase 17 has no PASS.
- The owner authorised Phase 18 with the Phase 17 gate unsigned, as in earlier phases. This is
  recorded, not assumed.

## Findings carried to the owner

1. **Matching reference.** The frozen harness pairs on `t_commit` (ADR-0023), which caps every
   matched lead at `W` and turns a commit more than `W` early into FP + FN. README §10.1 describes
   pairing on `t_impact_pred`. S1 is pre-declared as a sensitivity. **Decided A1:** ADR-0023 stays
   primary. (Offline report §3; ADR-0042 D2; T2.)
2. **Held-out participant count.** P_test = 2–3 makes every participant interval [min, max] of the
   participant values. **Decided D1:** the rule and the planned count are kept. (T1.)
3. **Frozen geometry.** A sample exactly on a zone boundary opens an entry episode without a
   candidate. (T20.)
4. **Live B inherits the model's horizon** (K = 1: 33 ms). Also, every live arm shares the one
   `commit` block (`tti_commit_s`, `p_commit`, `n_confirm_frames`): `app/pipeline.py` builds one
   `CommitSettings` for all arms. Live B and C therefore cannot each run at their own locked commit
   settings, and a changed `n_confirm_frames` would also delay A. **Decided B:** ADR-0036 amended
   (live B at the offline-locked settings, per-arm commit settings); implementation PENDING before
   the live lock. (Live report §3; T18.)
5. **One-frame arm-switch lag**, handled as-treated. (T19.)
6. **M1 is NO_GO on the built-in microphone.** An external microphone is needed. **Decided E1:** M1
   stays primary; M2 only if M1 fails its pilot. (External-methods report; T11.)
7. **One model fallback removes C from the rest of the session** (ADR-0036 sticky fallback). It is
   triggered by any of:
   - model inference p95 (both hands summed per frame) above `budget_s` = 10 ms over the last 30
     model frames;
   - total processing p95 above `processing_budget_s` = 33.3 ms over the same window;
   - a capture-cadence mismatch with the model's `dt_step`;
   - a model load or inference exception.

   It also fires while C runs in shadow. No recovery mode exists (the config schema fixes
   `automatic_recovery` to `false`), so the runner refuses every later switch to C. Seen in the
   verification's live rehearsal and not in the first one. **Decided C1:** the fallback is kept and
   the loss of C data accepted. (Live report §3; T21; live protocol §6.)

## Owner decisions — 2026-09-27

Recorded as documentation only. The pre-registration text is unchanged (version 1,
`sha256:e901f280…793ba0`); none of these decisions needs a new version; version 1 is **not**
approved yet.

| Id | Decision | What it means | Still pending |
|---|---|---|---|
| A1 | ADR-0023 commit-time matching stays the primary confirmatory rule; README §10.1 stays sensitivity S1 | no rule change; ADR-0023 records the difference (clarification); leads stay bounded by `W` | the offline lock (`W` and the other upstream values) |
| B | ADR-0036 amended: live arm B uses the offline-locked B settings (`b_primary`), with per-arm commit settings in the live pipeline; the shared-setting deviation was not chosen | no pre-registration change; the values come from the offline lock after `ds-v1.0` | implementation, tests, a live-lock consistency check, Phase 17 and 18 re-verification, all before the live lock |
| C1 | The sticky fallback is kept; a participant or session may lose its C data after a fallback | no recovery mode, no budget change; pre-registration §7.2 items 4–5 apply | nothing to implement; losses are reported per session |
| D1 | P07-SPLIT-1 and the planned 10–12 participants are kept | 2–3 held out; the per-participant reading of §6 applies | `ds-v1.0` (recruitment needs the ethics answer) |
| E1 | M1 (pad + external microphone) is equipped and evaluated as the primary timing method; M2 only if M1 fails its declared pilot; §8 thresholds and the estimator unchanged | no pre-registration change | external microphone without processing and practice pad; M1 part (i) re-run; developer pad pilot; GO / NO-GO |

## 1. Artefacts produced

| Artefact (from phase document) | Path | Status label | Present? |
|---|---|---|---|
| Pre-registration (+ hash record) | `docs/experiments/phase-18-prereg.md`, `docs/experiments/phase-18-prereg.hashes.json` (byte copies in `experiments/phase-18/preregistration/`) | DECLARED, version 1, `sha256:e901f280…793ba0`; approval PENDING; no lock archived | yes |
| Offline confirmatory report | `docs/reports/phase-18-offline-confirmatory.md` | PENDING; SYNTHETIC rehearsal and three findings | yes |
| External-methods report | `docs/reports/phase-18-external-methods.md` | M1 **NO_GO** on the built-in microphone (MEASURED developer pilot); M1 with an external microphone and M2 PENDING; M3 estimate only | yes |
| Live results | `docs/reports/phase-18-live-results.md` | PENDING (0 live sessions with a person); SYNTHETIC rehearsal and four findings | yes |
| Effective-latency analysis | `docs/reports/phase-18-effective-latency.md` | PENDING, no claim | yes |
| Limitations | `docs/reports/phase-18-limitations.md` | complete for the design (T1–T21); result-dependent entries PENDING | yes |
| Final evaluation report | `docs/reports/phase-18-final-evaluation.md` | PENDING; quotes the pre-registration hash (checked by `prereg_archive.py verify --cite`) | yes |
| `src/spacedrums/live_eval/`, scripts | the package (13 modules); `scripts/{run_offline_confirmatory, run_live_session, analyze_live, external_sync, confirmatory_lock, prereg_archive, regenerate_phase18, external_methods_pilot, verify_phase18}.py` and the helpers `_p18`, `_p18_live`, `_p18_report` | IMPLEMENTED (development); tests in §3 | yes |
| `experiments/phase-18/…`, external recordings with sync metadata | rehearsal and pilot runs (§4); click excerpts `click-excerpts.npz` | SYNTHETIC rehearsals plus the M1 click pilot; **no participant or live-person recording exists** | partial |
| Gate record | `docs/gates/phase-18-gate.md` | PENDING reviewer | yes |

Added beyond the list:

- ADR-0042, the design decisions D1–D8.
- Schemas `confirmatory-lock` and `live-session-metadata`, with SYNTHETIC examples and
  `validate_contracts.py` checks.
- The live protocol and the questionnaire draft (`docs/protocols/`).
- The consent addendum draft CF-LIVE-v0.1 (`docs/ethics/`).
- The `live_eval` import layer (`.importlinter`, the AST layer test, `architecture.md`).
- RTM evidence pointers (statuses unchanged) and the regenerated test matrix.
- The Phase 18 sections of the package, schema and script READMEs.

Interfaces (phase document "Interfaces / Contracts"):

- `LiveSessionMetadata` carries `arm_blocks[]`, `external_methods[]`, sync markers and the
  calibration hash, by composition with the Phase 06 `SessionMetadata` (ADR-0042 D5).
- Results: every run's `run.json` validates against the Phase 09 `experiment-log` schema
  (`_runlog.RunLog`, as in Phases 09–12). The offline `results.json` holds the Phase 18 aggregates
  that T1–T9 and F1–F6 are rendered from.

## 2. Acceptance criteria

| # | Criterion (verbatim from phase document) | Evidence (file / test id / run id) | Submitter assessment |
|---|---|---|---|
| 1 | Pre-registration archived with hash before runs. | Hash record version 1, archived 2026-09-27T08:44:07+03:00 (HEAD `6730b81…`, dirty tree). The first Phase 18 runner started at 12:27. `test_the_tracked_preregistration_matches_its_archived_hash_and_names_every_rule`; `prereg_archive.py verify --cite` in the final verification. Runners refuse a document that differs from its latest archived version, a lock archived before that version, and a participant lock without approval. | **MET** as a declaration. Owner / supervisor approval PENDING. Any amendment before a lock is a new archived version. |
| 2 | Offline confirmatory results complete for all arms with per-participant CIs and the primary figure. | `docs/reports/phase-18-offline-confirmatory.md`. The runner, tables T1–T9 and figures F1–F6 are exercised on the SYNTHETIC rehearsal `20260927-1237-offline-rehearsal`. | **NOT MET**. `ds-v1.0`, W, `Δ_proc`, the budgets, the operating points and the shipped model do not exist, so the offline lock cannot be archived. No participant result. |
| 3 | External-measurement methods validated (or documented as failed) and live results reported with uncertainties. | M1 part (i) failed twice on the built-in microphone (`20260927-1228` / `-1230-methods-m1-clicks`), decision `20260927-1232-methods-decide`. M2 not piloted. M3 estimate only. Live chain on SYNTHETIC data: `20260927-1253` → `-1257`, repeated in the final verification (`…-1323` → `…-1324`). | **PARTIAL**. M1 is documented as failed on the built-in microphone. M1 with an external microphone, the pad pilot and M2 are PENDING. Live sessions with a person: 0 (ethics Open Question). |
| 4 | Effective-latency analysis based solely on external measurements (or PENDING). | `docs/reports/phase-18-effective-latency.md` | **MET in its PENDING form.** No number; the analysis and its interpretation rules are declared. |
| 5 | Limitations section complete; reproducibility package regenerates all outputs. | `phase-18-limitations.md` (T1–T21). Regeneration `20260927-1251-regenerate` and, in the final verification, `…-1321-regenerate`: from stored results and from raw data, 0 differences. An independent repeat of the whole offline chain reproduced every metric, interval and decision. | **PARTIAL**. Limitations are complete for the design. Regeneration succeeded on the SYNTHETIC rehearsal only; participant outputs and the second-person check are PENDING. |
| DoD | All acceptance criteria; final evaluation report; gate record PASS; integrity checklist applied (every number labelled; hypotheses reported as supported / not supported / inconclusive). | this record; `phase-18-final-evaluation.md` (every hypothesis PENDING) | **NOT MET**: criteria 2, 3 and 5; I-11 NO; reviewer signature absent |

## 3. Tests

Final verification pytest run: **1,499 passed, 1 skipped** (557 s). Phase 17 ended at 1,441 passed and
1 skipped; the 58 new tests are the Phase 18 suites below. The Phase 18 suites:

| Test id | What it checks | Result | Where run |
|---|---|---|---|
| `tests/live_eval/test_live_eval_stats.py` (TEST-P18-STATS, TEST-P18-HYP) | participant bootstrap: seeded, order-independent, `degenerate` flag for small P, no interval for one participant; paired differences; pooled FP/min ratio; decision rules (greater / at most / reduction beyond `U`; two-sided C-vs-B); failure readings and preconditions on every hypothesis; the `δ_TE` rule | pass | HW-01, 2026-09-27 |
| `tests/live_eval/test_live_eval_prereg.py` (TEST-P18-PREREG) | the tracked document matches its archived hash and names every rule; the record is append-only; a version after a lock needs a reason; lock validation refuses placeholders and inconsistent arms; archive precedence; participant use needs a recorded approval; the ledger refuses a repeat participant execution | pass | HW-01, 2026-09-27 |
| `tests/live_eval/test_live_eval_methods.py` (TEST-P18-SYNC, TEST-P18-M1 / M2 / M3) | event-train sync (offset, drift, spurious events, explicit failure); flash detection; envelope lag; M1 known latencies, including early sound and ambiguous strikes; click-pair validation; M1 and M2 decision rules; M3 single-clock rule and DAC labelling | pass | HW-01, 2026-09-27 |
| `tests/live_eval/test_live_eval_protocol.py` (TEST-P18-LIVE) | Williams balance; six orders; blocks use Phase 06 segments only; the arm switcher switches once per block and blinds the participant; `live-session-metadata` example and conditionals; consistency with the Phase 06 document | pass | HW-01, 2026-09-27 |
| `tests/live_eval/test_live_eval_offline.py` (TEST-P18-OFFLINE) | participant and pooled metrics regroup the harness events; strata; S1 pairs an early accurate commit that ADR-0023 counts twice; trajectory error against the future causal track; TEST-CAUSAL-1 passes the frozen arms with effective perturbations and **catches an arm that reads the future** | pass | HW-01, 2026-09-27 |
| `tests/scripts/test_phase18_scripts.py` (TEST-P18-SCRIPTS) | lock templates cannot be archived; runners refuse before reading data; report rendering is deterministic; the regeneration comparator tolerates only float noise and run-specific keys; the exploratory click diagnostic; the verifier chains steps by evidence lines | pass | HW-01, 2026-09-27 |
| `tests/architecture/test_import_layers.py` | `live_eval` in the top layer; no lower layer imports it | pass | HW-01, 2026-09-27 |
| Runner self-checks (pre-registration §4.4) | `pytest tests/eval tests/live_eval` and TEST-CAUSAL-1 on all six locked arms: 40 cuts × 3 kinds × 2 fixture sessions, maximum deviation 0; perturbations effective 36–40 of 40 per kind | pass | `20260927-1237-offline-rehearsal/self-checks.json` and the final verification |

## 4. Measurements produced in this phase

The only measurement of the physical system is the M1 click pilot. It involved no person. Its
recordings stayed in memory, except ±15 ms excerpts around located clicks: one click, in the second
run; no pair was detected.

| Quantity | Label | Value | run_id | Method | Hardware id |
|---|---|---|---|---|---|
| M1 part (i): click pairs detected on the built-in microphone array (40 pairs, separations 20–200 ms) | MEASURED (developer pilot, no person) | **0 / 40** (0 clicks located), reproduced 0 / 40 (1 located) → **FAIL** against the declared rule (≥ 30 pairs, \|bias\| ≤ 1 ms, e95 ≤ 2 ms) | `20260927-1228-methods-m1-clicks`, `20260927-1230-methods-m1-clicks` | `external_methods_pilot.py --m1-clicks --allow-audio-device`; pre-registration §8 | HW-01 |
| Method decisions | derived from the above and from the inventory | M1 **NO_GO** (built-in microphone); M2 PENDING; M3 ESTIMATE_ONLY | `20260927-1232-methods-decide` | `--decide` | HW-01 |
| Whole-stimulus alignment of the click recording | EXPLORATORY (post hoc) | no click train found: peak 0.023, delay −0.75 s (impossible), so the diagnostic reports nothing further | `20260927-1230-methods-m1-clicks` (`NOTE.md`) | envelope cross-correlation | HW-01 |

SYNTHETIC machinery checks, which are not measurements of the system:

| Check | Result | run_id |
|---|---|---|
| Method self-test (click pairs, M1 pairing, sync, flashes) | all known answers recovered (external-methods report §1) | `20260927-1228-methods-selftest` |
| TEST-CAUSAL-1 on the six rehearsal arms | maximum deviation 0 | `20260927-1237-offline-rehearsal` |
| Regeneration from stored results and from raw data | 0 differences (tolerance 1e-9) | `20260927-1251-regenerate` |
| Live chain: M1 recovery of known latencies; sync residual | within 0.034 ms; RMS 2.9 µs (65 matched sounds) | `20260927-1255-external-sync-m1`, `20260927-1257-analyze-live` |
| Final verification, offline chain repeated from scratch (new lock, retrained models) | every step exit 0; regeneration from stored results and raw data 0 differences; against the first chain, **no difference** in any metric, interval or decision (only run-specific paths and the wall-clock inference latency differ); GRU checkpoint bit-identical | `…-1308-rehearsal-lock`, `…-1310-offline-rehearsal`, `…-1321-regenerate` |
| Final verification, live chain repeated | every step exit 0; sync 50 matched, RMS 1.7 µs; 9 A pad strikes paired. **The shadow C-GRU fell back** at session time 140.2 s (inference p95 over the 10 ms budget), so both C blocks were refused and sounded with B: finding 7 | `…-1323-live-rehearsal`, `…-1324-external-sync-m1`, `…-1324-analyze-live` |

The Phase 17 dependency re-run measurements are recorded in `phase-17-gate.md`.

## 5. Integrity checklist

| # | Item | YES / NO / N/A | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled Target / Measured / Historical / Pending | YES | Every number is one of: a declared rule; a candidate; SYNTHETIC with a run id; MEASURED developer pilot with a run id; or PENDING. No participant number appears anywhere. |
| I-2 | No implementation claim without tests | YES (development) | §3; clean-commit reproduction PENDING |
| I-3 | No causal component consumes future frames | YES (development) | TEST-CAUSAL-1 on all six locked rehearsal arms (0 deviation, effective perturbations); a leaky arm is caught (TEST-P18-OFFLINE). The live runner uses the unchanged Phase 13–17 loop. Labels are the only non-causal input, and only the analysis sees them. |
| I-4 | No fabricated data | YES | No participant, session or result was invented. SYNTHETIC inputs are labelled in names and documents (`SYNTHETIC-K*` identities, `p18-synthetic-*` session, `ds-v0.0-selftest-p18-live`, schema examples). Failed runs are kept with `FAILED.md`, `SUPERSEDED.md` or `NOTE.md`. |
| I-5 | FPS reported as native only | YES | No FPS figure is claimed. M2's ≥ 200 FPS is a requirement, not a measurement. |
| I-6 | No "latency reduced" claim before Phase 18 | YES | Phase 18 makes none: the effective-latency report is PENDING and says no claim; REQ-060c is quoted in the limitations and the effective-latency report. |
| I-7 | Marker condition clearly labelled | N/A | no marker condition (limitation T16) |
| I-8 | Participant-level split confirmed for ML results | N/A for participants | No participant ML result exists. The rehearsal used the P07 participant-level split on SYNTHETIC identities (3 held out, 5 folds). |
| I-9 | Scope respected (out-of-scope register) | YES | no ablation (Phase 19); no model, threshold, harness, `app` or `ui` change; Phase 19 not started |
| I-10 | Status vocabulary correct | YES | Phase document and gate PENDING; RTM statuses unchanged (evidence pointers only); hypotheses PENDING |
| I-11 | Reproducibility fields complete | **NO** | Provenance, source audits and executor fields are complete, but every Phase 18 run used a dirty tree. The owner commit exists (`c2b6191`); `verify_phase18.py --require-clean` on it is still required. |
| I-12 | Limitations stated | YES | `phase-18-limitations.md`; every report lists what was not shown |

## 6. Deviations from the phase document

| What | Why | Impact on dependents |
|---|---|---|
| Recommended model (GPT-6 Astra / Extra High) not used; Claude Opus 5.5 executed the phase | the executing agent is Claude Code | none on evidence; recorded in every `execution.json` |
| Two-stage pre-registration: rules and symbols now, values in frozen-inputs locks later (ADR-0042 D1) | W, `Δ_proc`, the budgets, the operating points, the shipped model and `ds-v1.0` are all PENDING; declaring rules now keeps them ahead of any data | every lock must be archived after the latest approved version; the runners enforce this |
| Primary matching stays ADR-0023 (`t_commit`); README §10.1 (`t_impact_pred`) is the pre-declared sensitivity S1 (ADR-0042 D2) | the frozen harness implements ADR-0023, and the discrepancy was unrecorded | decided A1 (owner, 2026-09-27): ADR-0023 stays primary; this also bounds the Phase 10–12 leads (T2) |
| `LiveSessionMetadata` extends `SessionMetadata` by composition (`live-session.json` references `metadata.json` by SHA-256) rather than by new fields (ADR-0042 D5) | the Phase 06 schema is closed (`additionalProperties: false`) | none on the Phase 06 tools |
| External sync uses the system's own drum sounds against the software audio-event train (M1) and flashes (M2), not a separate clap (ADR-0042 D7) | the sounds are already in every recording and identify each strike | none |
| New import layer `spacedrums.live_eval` beside `app` (ADR-0042 D4) | analysis and live protocol above the frozen harness; `spacedrums.eval` stays unchanged | architecture contracts updated and tested |
| EXPLORATORY post-hoc click diagnostic after the declared M1 check failed | to tell "no click train recorded" apart from "the estimator missed it" | labelled exploratory; the declared outcome is unchanged; an estimator change would need a new pre-registration version |
| Runs kept with notes: `20260927-1227-methods-selftest` (`SUPERSEDED.md`), `-1233-rehearsal-lock` (`FAILED.md`), `-1248-regenerate` (`NOTE.md`), `-1256-analyze-live` (`FAILED.md`), `-1230-methods-m1-clicks` (`NOTE.md`) | script defects found by the runs, fixed and re-run | superseded by the later runs and by the final verification |
| No participant evidence; the rehearsals are SYNTHETIC | inputs, equipment and ethics are PENDING | the experiments themselves remain to be run |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase |
|---|---|---|
| Owner / supervisor approval of pre-registration version 1. Decisions A1, B, C1, D1 and E1 need no new version; their answers go in the approval note | Pending | 18 re-gate |
| Matching reference (ADR-0042 D2): decided A1, ADR-0023 primary and README §10.1 as S1 | Decided 2026-09-27 | — |
| `ds-v1.0` held-out participants; participant count and held-out size. P07-SPLIT-1 (ADR-0021): P = 8–11 → 2 held out, 12–19 → 3, ≥ 20 → round(0.2 P). With ≤ 3 held out, every interval is [min, max] of the participant values (pre-registration §6). Rule and planned 10–12 kept (decision D1) | Pending (`ds-v1.0`) | 06–07, then 18 |
| `W_PRIMARY_S`, `DELTA_PROC_LIVE_S` (live-stroke delay) | Pending Benchmark | 16 / 18 |
| Owner FP budget (ADR-0025), operating points (ADR-0024), shipped model (ADR-0030) | Pending Architecture Decision | 18, before the offline lock |
| `δ_audio`, `δ_lead`; Phase 07 acoustic spread `s_phys` | Open Question / Pending Benchmark | owner; 07 |
| Phase 04 output latency (M3's DAC term) | Pending Benchmark | 04 / 18 |
| Ethics answer; signed live consent (CF-LIVE-v0.1 draft) | Open Question | 00 / 18, before any live session |
| M1 as the primary timing method (decision E1): external microphone without processing and practice pad; M1 part (i) re-run; developer pad pilot (≥ 30 strikes); thresholds and estimator kept as declared | Pending Benchmark | 18 |
| M2 (≥ 200 FPS camera, LED reference): only if M1 fails its declared pilot (decision E1) | Pending Benchmark (conditional) | 18 |
| Live B at the offline-locked `b_primary` settings with per-arm commit settings (ADR-0036 amendment, decided 2026-09-27): implementation, tests, live-lock consistency check, Phase 17 and 18 re-verification (finding 4; T18) | Pending (implementation) | 18, before the live lock |
| Live model-fallback policy (finding 7; T21): decided C1, the sticky fallback is kept and a loss of C data accepted (pre-registration §7.2, items 4–5); no recovery mode, no budget change | Decided 2026-09-27 | — |
| Include the questionnaire (Experiment 3); number of live participants and overlap with dataset participants | Open Question | 18, before the first live session |
| Frozen-geometry boundary edge case (T20) | Open Question | owner; a later phase |
| Whether anticipatory sound changes user motion | To Be Experimentally Determined | 18 (live) |
| Second-person regeneration check | Pending | 18 re-gate |
| Participant replay set for the invariants (from Phase 17) | Pending | after `ds-v1.0` |
| From Phase 17: `g_max_frames` 3 / `age_max_s` 0.5 confirmation on participant data (ADR-0041, owner-decided deviation) | To Be Experimentally Determined | 18 re-gate, after `ds-v1.0` |
| From Phase 17: DEGRADED commits on participant data (ADR-0039, kept off) | Pending | 18 re-gate, after `ds-v1.0` |
| From Phase 17: arm B post-re-acquisition warm-up (F-10, F19) | To Be Experimentally Determined | 18 re-gate, after `ds-v1.0` |
| From Phase 17: developer-played maximum separable hit rate (REQ-013) | Pending | 17 re-gate / 18 |

## 8. Conditions

None proposed: the submitter proposes FAIL, not PASS-WITH-CONDITIONS. The confirmatory
experiments are this phase's purpose, and Phases 19 and 20 depend on their results.

## 9. Reviewer statement

PENDING — to be written by the reviewer: what was inspected, run or opened, and anything not
verified.

Signed: PENDING

## Exit actions (owner)

1. **Review.** The pre-registration, ADR-0042, the six reports, the live protocol, the
   questionnaire and the consent addendum.
2. **Decisions.** A1, B, C1, D1 and E1 were recorded on 2026-09-27 ("Owner decisions" above). None
   changes the pre-registration text, so no new version is needed. Still open: the questionnaire
   and the live participant count (both before the first live session). Approve version 1 when
   ready, with the answers in the note:
   `python scripts/prereg_archive.py approve --by "<name>" --date YYYY-MM-DD --note "<answers>"`
   (the approver runs this, never the agent).
3. **Commit** the Phase 18 changes: done by the owner (`c2b6191`, 2026-09-27 13:39:24 +03:00). Commit,
   tag and push stay owner-controlled; the agent made none.
4. **Clean re-run.** On the committed tree, run
   `python scripts/verify_phase18.py --require-clean --executor-model "<actual>" --executor-effort "<actual>"`
   (26.5 min on the dirty tree on HW-01).
5. **Equipment and person steps** (external-methods report §3):
   1. an external microphone without processing, then M1 part (i);
   2. the developer pad pilot, then `--decide`;
   3. M2 only if M1 fails its declared pilot (decision E1);
   4. the Phase 04 output-latency loopback.
6. **Experiment 1**, once `ds-v1.0` and the upstream decisions exist:
   `confirmatory_lock.py template`, then `validate`, then `archive`, on a clean tree; then
   `run_offline_confirmatory.py --lock …` **once**; then `regenerate_phase18.py`, and a second person
   repeats it.
7. **Experiment 2**, after the ethics answer, consent, the implemented and re-verified ADR-0036
   amendment, the M1 equipment and pilot, and the live lock:
   `run_live_session.py`, then `external_sync.py`, then `analyze_live.py`, per participant.
8. **Next phase.** Per the phase document, a PASS leads to Phases 19 and 20. The agent has not
   started either.
