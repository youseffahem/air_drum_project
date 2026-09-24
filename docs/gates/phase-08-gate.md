# Phase 08 — Exit Gate

Submitted 2026-09-22. Submitter: Codex. Reviewer: project owner, pending.
Proposed verdict: **FAIL for the full phase; implementation machinery is complete**.

The implementation acceptance criteria have executable evidence, but the required input
`ds-v1.0` and its reviewed, frozen participant splits do not exist. Therefore participant-fold
stats, counts, descriptive measurements and all-session parity cannot honestly be supplied.
The Definition of Done also requires a clean committed-tree rerun and reviewer PASS. Phase 09
has not started.

## Dependency and Phase 07 handoff

The latest owner commit is `1a8e790985bc97810eb28bd26ddc788136a16157` (`phase 7`). Phase 07
was reopened before this phase. Gate revision `docs/gates/phase-07-gate-r2.md` records the
clean-tree rerun and closes C-07-7. C-07-1 through C-07-6 remain pending because no manual
annotation, human review, physical reference or participant dataset exists. No other Phase 07
condition became executable. Phase 08 proceeded under the owner's explicit instruction, with
the unavailable dependency preserved as a gate condition rather than replaced with synthetic
evidence.

## Task status

| Task | Status | Evidence |
|---|---|---|
| 08.1 Feature schema v1 | IMPLEMENTED | descriptor/schema/doc; dimensions and group metadata recorded |
| 08.2 Causal core | IMPLEMENTED / VERIFIED | analytic, future-perturbation and bounded-history tests |
| 08.3 Masking and gaps | IMPLEMENTED / VERIFIED | invalid/stale reset, degradation, gap and safety-retention tests; diagnostic counts reported |
| 08.4 Normalization | IMPLEMENTED / VERIFIED on UNIT fixture; PARTICIPANT EVIDENCE PENDING | train-only fit, provenance and leakage rejection tests; no `ds-v1.0` |
| 08.5 Windows and targets | IMPLEMENTED / VERIFIED | shapes, time alignment, tails, ambiguity, quarantine and target-causality tests |
| 08.6 Reference exclusion | IMPLEMENTED / VERIFIED | source scan plus runtime filename/header/schema guard |
| 08.7 Target semantics | COMPLETE | `docs/features/feature-schema-v1.md`; Phase 10/18 references updated |
| 08.8 Streaming parity | IMPLEMENTED / VERIFIED | exact parity on UNIT, 2,262 SYNTHETIC and 342 DEV CAPTURE records; participant-fold parity PENDING |
| 08.9 Feature latency | DEVELOPMENT MEASUREMENT COMPLETE; CLEAN RERUN PENDING | HW-01 timing run below; C-08-3 |
| 08.10 Descriptive statistics | IMPLEMENTED; PARTICIPANT MEASUREMENT PENDING | test/generator/developer diagnostics clearly separated; C-08-1 |

## Acceptance criteria

| Criterion | Result |
|---|---|
| Schema documented with groups, units, derivations and masks | MET |
| Causal core; TEST-CAUSAL-1/2; streaming parity | MET for executable sources; participant all-session parity PENDING |
| Train-only per-fold normalization enforced | MET by implementation/tests; actual participant stats PENDING |
| Aligned samples and reported counts | MET for test/SYNTHETIC/DEV diagnostics; participant counts PENDING |
| Reference-track exclusion | MET |
| Feature latency measured | MET as dirty-tree development evidence; clean measurement PENDING |
| Definition of Done: stats files, measured report, gate PASS | NOT MET for participant data, clean rerun and reviewer decision |

## Verification

Primary run: `experiments/phase-08/20260922-2115-p08-gate-verification/run.json`.
It is schema-valid, records HW-01/environment/config/source hashes and contains hashed logs.
It ran on owner SHA `1a8e790985bc97810eb28bd26ddc788136a16157` with `git_dirty: true`,
because the Phase 08 changes are intentionally uncommitted.

| Check | Actual result | Evidence class |
|---|---|---|
| Focused Phase 08 suite | 307 passed, 3 deprecation warnings | UNIT / CONTRACT TEST |
| Full regression | 941 passed, 1 opt-in webcam test skipped, 3 warnings | UNIT / PROPERTY / CONTRACT TEST |
| Ruff; import-linter | PASS; 7 contracts kept, 0 broken | STATIC CHECK |
| Contract/schema validator | PASS | CONTRACT TEST |
| Environment, pinned model, seven drum samples | PASS | STATIC CHECK |
| `git diff --check` | PASS | STATIC CHECK |
| Synthetic fold feature/stats exports | PASS, three folds; disjoint assignments and train-only stats | UNIT TEST |
| Existing SYNTHETIC session | 2,262 exact parity records; 2,248 windows | SYNTHETIC |
| Existing DEV CAPTURE | 342 exact parity records; 328 windows | DEV CAPTURE |
| Feature latency | default p50 0.97715 ms, p95 1.263505 ms; 2,000 timed calls | HARDWARE MEASUREMENT (development) |

The detailed statistics and scope limits are in
`docs/reports/phase-08-feature-stats.md`. The earlier failed development attempt
`20260922-2109-p08-gate-verification` is retained as historical evidence; it was superseded by
the passing run and is not cited as the gate result.

## Integrity checklist

| Item | Result |
|---|---|
| Every number labelled by evidence type | YES |
| No participant recording or empirical evidence fabricated | YES |
| Synthetic identities never represented as participants | YES |
| Reference tracks excluded from model inputs | YES |
| Future data excluded from X | YES |
| Split/hash/fold/session provenance checked; no split creation side effect | YES |
| Invalid/stale values zeroed and masked; derivative state reset | YES |
| Safety-only windows retained separately | YES |
| Raw values and timing samples retained with run provenance | YES |
| No model training or feature selection performed | YES |
| No Git history operation performed | YES |

## Conditions

| Condition | Status / classification | Closure evidence required |
|---|---|---|
| **C-08-1** Execute Phase 08 on the reviewed `ds-v1.0` frozen participant folds; export samples/safety sets and normalization stats per fold; report exact counts, drop reasons, train-only descriptive statistics and all-session batch/streaming parity. | PENDING — HUMAN/PARTICIPANT dependency; blocks Phase 09 | Phase 07 C-07-6 closed; schema-valid participant feature/stats runs with hashes and the report updated. Synthetic or DEV data cannot close it. |
| **C-08-2** Review the final schema/target semantics and C-08-1 evidence; record the owner/reviewer gate verdict. | PENDING — OWNER DECISION, after C-08-1 | Signed gate verdict and date. |
| **C-08-3** After the owner commits Phase 08, rerun `scripts/verify_phase08.py --require-clean`; update this gate/report to the clean run and close only if every command passes without modifying the tree. | PENDING — OWNER GIT ACTION | Schema-valid run on the Phase 08 owner SHA with `git_dirty: false`, passing command logs and clean post-command state. |

No condition currently executable without the absent participant dependency, owner commit or
reviewer decision remains open. A passing dirty-tree development run cannot close C-08-3.

## Gate decision and handoff

**Final proposed gate: FAIL.** This verdict concerns the full Phase 08 Definition of Done, not
the completeness of the implementation. C-08-1 blocks data-dependent Phase 09 work because
the next phase requires actual participant folds and their normalization statistics. C-08-2
and C-08-3 are owner-dependent. Phase 09 — Classical ML Baselines is the next phase and was
not started.

Signed: **PENDING — project owner**, 2026-09-22.

## Post-owner-commit verification — 2026-09-24

Phase 10 authorization triggered the outstanding C-08-3 check before edits.
`scripts/verify_phase08.py --require-clean` passed all 14 commands on HEAD
`35f288523b0b06733e93454325bcab3e86b122ff`, with initial and post-command
`git_dirty: false`. Evidence:
`experiments/phase-08/20260924-1909-p08-gate-verification/run.json`,
`verification.json`, and `source-hashes.json` in that directory.

C-08-3's executable post-commit condition is now satisfied on the current owner
HEAD. C-08-1 participant data and C-08-2 reviewer decision remain PENDING;
the full gate has not passed and no requirement status is advanced.
