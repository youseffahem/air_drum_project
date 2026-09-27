# Phase 18 — Experiment 1: offline confirmatory evaluation (Tasks 18.2, 18.7)

**Status: PENDING — the confirmatory run has not happened.**

- It needs:
  - the reviewed, frozen `ds-v1.0` held-out participants (Phase 07; absent);
  - the frozen `W` (`W_PRIMARY_S` is `None`);
  - the accepted live `Δ_proc` (`DELTA_PROC_LIVE_S` is `None`);
  - the owner budgets (ADR-0025);
  - the validation operating points (ADR-0024);
  - the shipped model (ADR-0030);
  - an owner / supervisor approval of the pre-registration.
- None of these exists on 2026-09-27, so the offline lock cannot be archived, and
  `run_offline_confirmatory.py` refuses to run without one.
- **No participant number appears in this report.** Every number below comes from a **SYNTHETIC
  rehearsal** on the Phase 11 kinematic fixture: it checks the machinery and is never evidence.

Pre-registration: [`../experiments/phase-18-prereg.md`](../experiments/phase-18-prereg.md), version
1, `sha256:e901f280efb4681d35607a072909d9409e9aeaf3ab1c128112769f8c25793ba0`, archived
2026-09-27T08:44:07+03:00.

## 1. What is ready for the confirmatory run

| Step (pre-registration section) | Implementation | Tested by |
|---|---|---|
| Lock validation, archive precedence, approval, execute-once ledger (§0, §11) | `live_eval.prereg`, `scripts/confirmatory_lock.py`, `scripts/prereg_archive.py` | `tests/live_eval/test_live_eval_prereg.py`; runner refusals in `tests/scripts/test_phase18_scripts.py` |
| Frozen-source check (§4.4.3) | `run_offline_confirmatory.frozen_source_mismatches` | rehearsal |
| Harness self-checks: `pytest tests/eval tests/live_eval` and TEST-CAUSAL-1 on every locked arm (§4.4) | `live_eval.causality.causal_check` in `causality_checks` | `test_live_eval_offline.py` (pass on A / B; a leaky arm fails); rehearsal |
| Held-out sessions through `load_dataset` (participant) or the regenerated fixture (rehearsal), checked against the locked roster and digests | `load_test_sessions` | rehearsal |
| Every arm at primary `Δ_proc` (+ S1) and at `Δ_proc = 0`; declared curve sweep (§4, §10 F1) | `confirmatory` | rehearsal |
| Per-participant / pooled metrics, strata, trajectory ADE / FDE, intensity ρ (§5, Task 18.7) | `live_eval.offline` | `test_live_eval_offline.py` |
| Hypotheses H1a, H1b, CB, H2, H3 and S1 sensitivity; paired differences (§3, §6) | `live_eval.hypotheses`, `live_eval.stats` | `test_live_eval_stats.py` |
| Tables T1–T9 and figures F1–F6 from `results.json` alone; regeneration (§10, Task 18.9) | `scripts/_p18_report.py`, `scripts/regenerate_phase18.py` | `test_phase18_scripts.py`; rehearsal regeneration |

## 2. SYNTHETIC rehearsal (machinery only)

### 2.1 Chain and inputs

| Step | Run | What happened |
|---|---|---|
| Rehearsal lock | `experiments/phase-18/20260927-1234-rehearsal-lock/` | The kinematic fixture had 12 SYNTHETIC identities: 3 held out (`SYNTHETIC-K0`, `-K1`, `-K7`) and 5 folds. A fold-0 GRU (N 8, K 4, hidden 16, 8 epochs) and a fold-0 GBDT were trained with the unchanged Phase 10 / 09 code. Every arm's point was picked on the fold-0 validation identities with `select_point` (development budget FP 30/min, FN 0.6, `Δ_proc` 30 ms, W 50 ms). The lock `sha256:f63d4a95…c23a` was archived at 12:37:02 in a run-local copy of the hash record, after pre-registration v1. The first attempt (`20260927-1233-rehearsal-lock`, kept with `FAILED.md`) stopped on a directory-creation bug, since fixed. |
| Offline runner | `experiments/phase-18/20260927-1237-offline-rehearsal/` | Lock verified, frozen sources unchanged, ledger RESERVED at 12:37:20 and COMPLETED at 12:46:58. Self-checks: `tests/eval` 7 passed, `tests/live_eval` 52 passed. TEST-CAUSAL-1 passed for all six locked arms: 40 cuts × 3 kinds × 2 fixture sessions each, maximum deviation 0 (learned arms bit-identical as well), and 36–40 of 40 perturbations per kind changed an output after the cut, so no pass is vacuous. All arms ran at `Δ_proc` 30 ms (with S1) and 0 ms, then the curve sweep; tables T1–T9 and figures F1–F6 are in `report/`. |
| Regeneration (Task 18.9) | `experiments/phase-18/20260927-1251-regenerate/` | **Passed.** From stored `results.json`: all 9 table digests and 6 figure-data digests equal. From raw data (the regenerated fixture, the locked models rebuilt): the whole computation reproduced with **0 differences** at absolute tolerance 1e-9. PNG bytes differ for F1 / F2 only, after a styling fix to the figure code (markers only, fewer direct labels), which leaves the plotted data unchanged. The earlier run `20260927-1248-regenerate` is kept with a `NOTE.md`: its comparator flagged the run-specific keys as differences, a bug now fixed and tested. The **second-person check** (another person or machine running `regenerate_phase18.py`) is PENDING. |

**Independent repeat (final verification).** The whole chain was repeated inside
`experiments/phase-18/20260927-1258-p18-gate-verification/`, and every step exited 0:

- a new rehearsal lock (`…-1308-rehearsal-lock`), with the models retrained from scratch:
  - the GRU checkpoint is bit-identical to the first chain's;
  - the TorchScript export bytes, the wall-clock latency file and the manifest that records them
    differ, as known for exports;
- the offline runner (`…-1310-offline-rehearsal`);
- regeneration (`…-1321-regenerate`): stored results, 9 / 9 tables and 6 / 6 figure data sets equal
  and the PNGs byte-identical; raw data, 0 differences.

Compared with the first chain, `results.json` has **no difference** at the 1e-9 tolerance
(regeneration comparator), apart from two kinds of run-specific value:

- the selection-file paths;
- the development GRU's wall-clock inference latency, which the lock measures anew.

Every metric, interval and decision is the same. The nine tables differ only in their provenance
line (lock digest and run id).

### 2.2 What the rehearsal shows (SYNTHETIC; no reading about the research question)

- **Every decision path runs.** H1a INCONCLUSIVE, H1b SUPPORTED, CB C_LONGER, H2 INCONCLUSIVE,
  H3 SUPPORTED, and H4 / H4-B PENDING (a live question).
- **P = 3.** Every interval is flagged `degenerate` (it spans the three participant values), as §6
  declares.
- **Infeasible arms.** `C-GBDT-direct` had no budget-feasible validation point. It is evaluated at
  its diagnostic point, flagged infeasible in T9, and a hypothesis naming such an arm would be
  NOT TESTABLE.
- **S1 changes H2 (INCONCLUSIVE → SUPPORTED)** on the fixture: matching by predicted impact time
  turns early anticipatory commits from FP + FN into matches. This is finding 1 below, seen on
  data.
- **Trajectory error (T6).** It is computed only for arms that emit trajectories, against the
  future causal track; the direct GBDT has none.
- None of these numbers says anything about participants, the models or the research question.
  The fixture's scripted strokes and a fold-0 development GRU trained for eight epochs are not a
  shipped model.

## 3. Findings from building Experiment 1 (carried to the owner)

1. **Matching reference (pre-registration §4.1; ADR-0042 D2).**
   - The frozen harness pairs a strike with an impact by `t_commit`, not by `t_impact_pred` as
     README §10.1 describes.
   - Every matched `L_pred` therefore lies in [−W, +W], and an anticipatory commit made more than
     `W` early counts as one FP plus one FN. This also bounds every Phase 10–12 development lead.
   - S1 (§10.1 reference time) is pre-declared as a sensitivity. The owner decided on 2026-09-27
     to keep ADR-0023 primary (decision A1).
2. **Held-out participant count (§6).** Rule P07-SPLIT-1 holds out 2–3 participants at the planned
   10–12. The participant-bootstrap interval then equals [min, max] of the participant values, so
   offline decisions read "every held-out participant meets the criterion".
3. **Frozen geometry edge case.**
   - A tip sample lying exactly on a zone's impact surface (within `1e-9` in the ellipse's
     normalised radius) is counted as inside by `GeometryEngine.observe`, while `first_impact`
     requires the sample to be strictly inside.
   - The entry episode then starts with no candidate, and the strike is never detected.
   - On continuously filtered positions this is practically impossible, but on grid-aligned
     SYNTHETIC tracks it is deterministic: the Phase 18 test swing had to start at y = 0.401
     instead of 0.40.
   - Not changed (frozen Phase 04 geometry); reported for the owner.

## 4. What the confirmatory run will report

The pre-registration's tables T1–T9 and figures F1–F6, every hypothesis with its decision and
reading, the S1 sensitivity and the zero-delay appendix, all regenerated from `results.json` by
`regenerate_phase18.py`.
