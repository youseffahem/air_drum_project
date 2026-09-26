# Phase 11 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 11 — Multi-Task Prediction: Time-to-Impact, Zone & Intensity |
| Phase document | `phases/phase-11-multitask-prediction.md` |
| Submitter | Claude Opus 5.5 (Claude Code), acting for the project owner |
| Reviewer(s) | Project owner — PENDING |
| Review date | PENDING |
| Code state | start `bd0bcf8a99e0a0fe1fed13e9869892e5cec1dd81` clean; final verification `bd0bcf8a99e0a0fe1fed13e9869892e5cec1dd81` dirty: **yes** (Phase 11 uncommitted) |
| **Verdict** | **Proposed: FAIL for the full phase** — reviewer PENDING |

The multi-task machinery is implemented, tested and exercised end to end on a SYNTHETIC
kinematic fixture. Every research acceptance criterion needs participant evidence (ds-v1.0 CV
folds, the Phase 09/10 gates and owner budgets) that does not exist, and the single confirmatory
test run is deliberately not executed. Neither the submitter nor passing unit tests can pass
this gate.

## Execution environment

| Field | Recorded value |
|---|---|
| Model actually used | **Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code** — not the recommended Codex GPT-6 Astra |
| Reasoning effort actually used | Not exposed to the agent; not asserted (the recommended "Extra High" is a Codex picker setting) |
| Execution date/time | 2026-09-25, 08:40–10:46 (final verification; later edits documentation only) +03:00 (exact timestamps in each `run.json` / `execution.json`) |
| HEAD at start | `bd0bcf8a99e0a0fe1fed13e9869892e5cec1dd81` ("phase 10"), `git_dirty` **false** (verified 08:40 and by the Phase 10 verifier at 08:51) |
| HEAD at final verification | `bd0bcf8a99e0a0fe1fed13e9869892e5cec1dd81`; `git_dirty` **true** (no commit/tag/push performed) |
| Runtime / CPU | locked Windows Python 3.11 venv, PyTorch 2.14.0+cpu, HW-01 (Intel i7-7820HQ, 4 cores / 8 threads); hardware snapshots in every run manifest |

Every Phase 11 run's `execution.json` records `codex_model = "NOT CODEX: Claude Opus 5.5
(claude-opus-5-5) via Claude Code"` and reasoning effort "UNAVAILABLE to the agent; not asserted".

## Dependency verification (before any Phase 11 edit)

`scripts/verify_phase10.py --require-clean` on clean HEAD `bd0bcf8`:
`experiments/phase-10/20260925-0840-p10-gate-verification` — COMPLETED, all ten commands passed
(977 passed / 1 skipped; ruff; 7 import contracts; contracts; env smoke; `git diff --check`; four
exported-model metric reproductions), 8,007 input artifacts hash-verified, `git_dirty_final`
false. Recorded as an appendix in `docs/gates/phase-10-gate.md`. The Phase 10 gate itself remains
PENDING reviewer, proposed FAIL: Phase 11 therefore proceeds only with independent development
machinery, as its execution instructions require, and every participant-dependent item stays
PENDING.

## 1. Artefacts produced

| Artefact (phase document) | Path | Status label | Present? |
|---|---|---|---|
| Heads (extended), multi-task losses | `src/spacedrums/models/temporal/{heads,losses}.py` | IMPLEMENTED | yes |
| Multi-task training | `src/spacedrums/models/temporal/mt_train.py` (+ `config.py` `MultiTaskConfig`, `gru.py`/`tcn.py` `MultiTask*`, `export.load_mt_model`) | IMPLEMENTED | yes |
| MT adapter | `src/spacedrums/models/temporal/mt_adapter.py` | IMPLEMENTED | yes |
| Consistency flags and gates | `src/spacedrums/models/temporal/consistency.py` | IMPLEMENTED | yes |
| Scripts | `scripts/{train_mt, eval_mt, ablate_heads, eval_consistency}.py` + `sweep_weighting.py`, `compare_tti.py`, `latency_mt.py`, `verify_phase11.py`, `_p11*.py` | IMPLEMENTED | yes |
| Pre-registration addendum | `docs/experiments/phase-11-prereg.md` | PENDING (draft; owner fields open) | yes |
| Weighting / conflicts / per-task / gating / head-ablation reports | `docs/reports/phase-11-{weighting,conflicts,per-task,gating,head-ablation}.md` | SYNTHETIC development diagnostics; participant results PENDING | yes |
| Test-run report | `docs/reports/phase-11-test-run.md` | PENDING (no held-out run) | yes |
| Latency report (added) | `docs/reports/phase-11-latency.md` | development CPU compute | yes |
| ADRs | `docs/decisions/ADR-0028-aux-schema-bump.md` (IMPLEMENTED contract), `ADR-0029-intensity-source.md` (PENDING), `ADR-0030-ship-model.md` (PENDING) | as stated | yes |
| Models | per-cell exports under `experiments/phase-11/<run>/models/cell-*/`; no `models/temporal/<mt_model_id>/` ship package | development only | partial |
| Experiments | `experiments/phase-11/…` (git-ignored, hashed per `run.json`) | development | yes |
| Gate record | this file | PENDING reviewer | yes |

## 2. Acceptance criteria

| # | Criterion (phase document) | Evidence | Result |
|---|---|---|---|
| 1 | MT model implemented with masked losses and configurable weighting; causal tests pass | `test_mt_heads_losses.py`, `test_mt_causal.py`, `test_mt_training.py`; full regression 1038 passed, 1 skipped (371.95 s) | **MET** for implementation (dirty tree; clean rerun pending) |
| 2 | Weighting, conflicts, per-task, gating, head ablations executed on CV folds | synthetic runs listed in §4 | **NOT MET** for participant CV folds; executed on SYNTHETIC folds only |
| 3 | Intensity source ADR recorded | ADR-0029 | **PARTIAL**: rule, metric and development default recorded; participant decision PENDING |
| 4 | Single confirmatory test run; ship ADR with all criteria | `phase-11-test-run.md`, ADR-0030 | **NOT MET**: intentionally unexecuted; ship rule pre-declared, nothing selected |
| 5 | Latency/memory measured; reproducibility package updated | `phase-11-latency.md`; `verify_phase11.py` | **PARTIAL**: development CPU compute measured on HW-01; no selected/shipped model, no clean or independent reproduction |

## 3. Tests

| Test id / file | What it checks | Result | Where run |
|---|---|---|---|
| `tests/temporal/test_mt_heads_losses.py` | head shapes, zeroed disabled heads, TorchScript parity; masked losses (no-impact sample feeds only trajectory + strike-negative); TTI direct/log/bins; weighting schemes | pass | HW-01, 2026-09-25 |
| `tests/temporal/test_mt_causal.py` | TEST-CAUSAL-1/2 on every head (future perturbation, N truncation, masked NaN payload, negative control); bounded GRU state parity | pass | HW-01 |
| `tests/temporal/test_mt_training.py` | trajectory-only C-MT **bit-identical** to Phase 10 `train_fold` (GRU, TCN); determinism, export parity and tamper refusal per weighting; conflict sampling read-only; label contracts (zone ids, H_max, exported H); held-out file never opened; train-only intensity scaling | pass | HW-01 |
| `tests/temporal/test_mt_consistency.py` | flag semantics; default gate strips head probability; p_aux/agreement/intensity gates; config 1.5 validation and version gate; TrajectoryPrediction 1.1 round trip and 1.0 migration | pass | HW-01 |
| `tests/temporal/test_mt_invariant.py` | **invariant**: heads cannot create strikes; every C-MT commit is GEOMETRY from a geometry-engine candidate; p_aux only removes; C-MT requires its gate; unflagged direct candidates refused; flagged diagnostic labelled and not an Anticipator; application refuses C-MT and never references the diagnostic | pass | HW-01 |
| `tests/temporal/test_mt_protocol.py` | test partition refused before file access; participant plans refused without a run dir; fixture determinism/labels on the impact surface; replay cache input check; mechanical weighting rule | pass | HW-01 |
| Full regression | all suites incl. Phase 00–10 | 1038 passed, 1 skipped (371.95 s) | `20260925-1039-p11-gate-verification`, HW-01 |
| Static/contracts | ruff; 7 import-linter contracts (incl. `no-peek`); contract validation; env smoke; `git diff --check` | pass | `20260925-1039-p11-gate-verification`, HW-01 |

## 4. Measurements produced in this phase

All are **SYNTHETIC DEVELOPMENT** diagnostics on `scripts/_p11_fixture.py`, dirty tree, candidate
settings; not Measured thesis quantities (integrity I-1).

| Quantity | Label | Value (summary) | run_id | Method | Hardware |
|---|---|---|---|---|---|
| Weighting comparison, conflicts | development | every MT scheme degraded ADE/FDE beyond seed variance (both families); zone-head gradients mostly oppose the trajectory | `20260925-0913-synthetic-weighting` | `sweep_weighting.py` | HW-01 |
| Per-task (head vs geometry vs B) | development | see `phase-11-per-task.md` | `20260925-1002-synthetic-per-task` | `eval_mt.py --run` | HW-01 |
| Gating and commit-time intensity | development | p_aux gates trade FP for FN along the curve; agreement gates suppressed most valid strikes (FN 0.79–1.0); commit-time intensity: B extrapolation ρ 0.62–0.70 > geometry 0.31–0.33 ≈ head 0.21–0.32 (τ 0.05) | `20260925-1007-synthetic-gating` | `eval_consistency.py` | HW-01 |
| Head ablation incl. no-trajectory diagnostic | development | only +TTI within seed variance for both families; zone costs most; no-trajectory diagnostic matched about half as many impacts as trajectory-first at equal τ, with higher FP/min and timing error (labelled diagnostic) | `20260925-0949-synthetic-ablation` | `ablate_heads.py --weighting-from-run` | HW-01 |
| TTI parameterisation (direct/log/bins) | development | log best near impact (≈24 ms vs 48–65 ms) but biased early; bins costliest for ADE | `20260925-1029-synthetic-tti` | `compare_tti.py` | HW-01 |
| Latency / parameters / memory | development CPU compute | +153 parameters (+2.3–2.4 %), p50 +0.04–0.05 ms, p95/p99 within spread, identical working set (~207 MB incl. runtime) | `20260925-1028-mt-latency-memory` | `latency_mt.py` | HW-01 |

## Final developer verification

`experiments/phase-11/20260925-1039-p11-gate-verification/run.json` — COMPLETED 2026-09-25
10:46:30 +03:00, `RESULT PASS` for a dirty tree. All 12 commands passed:

- Full regression **1038 passed, 1 skipped, 44 warnings** (371.95 s). It was 977/1 at the Phase 10
  verification; the 61 added tests are Phase 11's.
- Ruff; import-linter 7 contracts kept (incl. `no-peek`: models never import geometry); contract
  validation; environment smoke; `git diff --check` (and, separately, all 33 new files free of CR
  and trailing whitespace).
- Six subprocess reproductions of exported-model validation metrics (atol 1e-6, rtol 1e-5): GRU/TCN
  from the weighting run, and `all` and `no-traj` for both families from the ablation run.
- 7,888 artifacts of the six input runs matched their recorded hashes.
- Frozen geometry/commit/matching/metrics/report/selection/constants unchanged versus HEAD; the only
  changed harness file is the additive `src/spacedrums/eval/replay.py`. Source unchanged during
  verification; `git_sha_final` `bd0bcf8`, `git_dirty_final` **true**.

This is same-environment development verification, not a clean or independent reproduction and
not a research PASS. TorchScript deprecation warnings remain visible in the logs.

## 5. Integrity checklist (submitter assessment; reviewer must verify)

| # | Item | Assessment | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled | YES | reports label every value SYNTHETIC DEVELOPMENT with run ids; candidates marked; no Measured participant claim |
| I-2 | No implementation claim without tests | YES (dirty tree) | §3; clean rerun after the owner commit is condition C-11-5 |
| I-3 | No causal component consumes future frames | YES | TEST-CAUSAL-1/2 on every head; replay future-perturbation invariance for C-MT commits |
| I-4 | No fabricated data | YES | fixture named/labelled SYNTHETIC in ids, notes and every report; no participant, consent or label invented |
| I-5 | FPS native only | YES / N/A | the fixture's 30 Hz grid is a scripted candidate, never reported as FPS |
| I-6 | No "latency reduced" claim | YES | lead is offline commit-to-label time; inference compute only; no sound/latency claim |
| I-7 | Marker condition labelled | N/A | no markers; synthetic tracks |
| I-8 | Participant-level split | YES for development; participant PENDING | fixture split by `P07-SPLIT-1`, held-out identity never opened, train-only normalisation and intensity scaling (tested) |
| I-9 | Scope respected | YES | no attention/Transformer/uncertainty, no live integration, no head-only live path, no test re-tuning |
| I-10 | Status vocabulary correct | YES | phase PENDING; RTM rows stay PLANNED with evidence pointers; no self-issued PASS |
| I-11 | Reproducibility fields complete | **NO** | runs are `git_dirty: true`; clean rerun and independent reproduction pending (C-11-5) |
| I-12 | Limitations stated | YES | every report ends with limitations |

## 6. Deviations from the phase document

| What | Why | Impact on dependents |
|---|---|---|
| Executed on a new SYNTHETIC kinematic fixture, not ds-v1.0 | ds-v1.0 does not exist; the Phase 08 unit fixture never enters a zone, so gates and intensity could not be exercised | none of the numbers may enter Phase 18/19 or the thesis as results |
| `eval/replay.py` extended (C-MT arm, post-geometry gate, flagged diagnostic mode) | the frozen commit policy must stay unchanged; the gate sits between geometry and commit | harness hashes changed; frozen matching/metrics/report/selection/constants and geometry/commit unchanged (audited); defaults preserve every earlier arm (full regression) |
| Head probability removed from `commit.p_commit` for C-MT | "gates default off" must hold for the shared threshold | Phase 10's optional aux logit keeps its original route |
| Additive changes to Phase 10 modules (`head_factory`, `_prepare/_infer/_decode`, `decode(aux=…)`, `read_samples` anchor/aux records) | reuse without duplication | Phase 10 behaviour bit-identical (tests; verified equivalence) |
| Config 1.5 bump; one contract test's "unknown version" moved to 1.6 | adding a version makes 1.5 known | none |
| Development weighting chosen by a rule declared mid-run (74/144 cells, before any summary) | the ablation needs one scheme; the rule is mechanical and recorded | development only |
| Grid latency measured with three parallel workers | wall-clock budget | marked contended; Task 11.8 uses a separate isolated run |
| Added `compare_tti.py` and `phase-11-latency.md` | answer the TTI open question at development level; give Task 11.8 its own evidence | additive |
| Scripts gained additive helpers after some runs started (`_p11.load_grid_run`, `choose_weighting`, TTI kind, configurable latency pair) | orchestration grew with the phase | each run's `source-hashes.json` records the code it ran. Against the final tree, the weighting run differs in `src/` only by `config/loader.py` (the config-1.5 version gate, not exercised by any run); the ablation run differs only in scripts (`_p11_grid.py` later gained the additive TTI kind; `compare_tti.py`, `latency_mt.py` it did not use); the TTI run matches exactly. Cross-run checkpoints are bit-identical (48/48) |
| Model/effort not the recommended Codex profile | the phase was executed by Claude Opus 5.5 | recorded truthfully above |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase |
|---|---|---|
| Participant CV weighting/conflicts/per-task/gating/ablation | To Be Experimentally Determined | Phase 11 (after Phase 09/10 gates, ds-v1.0) |
| TTI direct vs log vs bins | To Be Experimentally Determined (synthetic comparison `20260925-1029-synthetic-tti`: log best near impact but biased early; bins costliest) | Phase 11 CV |
| Intensity source (ADR-0029) | To Be Experimentally Determined | Phase 11 CV + test |
| Gate thresholds/tolerances | To Be Experimentally Determined | Phase 11 CV |
| Ship decision (ADR-0030), δ thresholds, memory budget | Open Question (owner) | Phase 11 test run |
| Intensity at commit vs updated at predicted impact | Open Question (commit adopted; alternative recorded) | Phase 13/18 |
| No-trajectory diagnostic in the thesis | Open Question (recommended yes, labelled) | Phase 19/21 |

## 8. Conditions (if the reviewer chooses PASS-WITH-CONDITIONS for the machinery)

| Condition | Owner | Must be closed by |
|---|---|---|
| C-11-1 Phase 09/10 gates and reviewed ds-v1.0 participant folds with auxiliary targets | owner / Phases 07–10 | before any Phase 11 research claim |
| C-11-2 Participant CV runs of Tasks 11.2–11.8 with the pre-registered rules | submitter | Phase 11 re-gate |
| C-11-3 Owner fields of `phase-11-prereg.md`, archived before held-out access | owner | before Task 11.9 |
| C-11-4 Single confirmatory run, ADR-0029/0030 decisions, shipped-model reproducibility package | submitter + reviewer | Phase 11 re-gate |
| C-11-5 After the owner commit: `scripts/verify_phase11.py --require-clean --runs <recorded runs>` | submitter | next phase start |

## 9. Reviewer statement

PENDING. The reviewer should open the reports and `run.json` files, rerun `scripts/verify_phase11.py`
on the committed tree, and inspect `tests/temporal/test_mt_invariant.py` for the trajectory-first
invariant. Signed: —

## Post-owner-commit verification — 2026-09-26 (condition C-11-5)

Before any Phase 12 edit, `scripts/verify_phase11.py --require-clean` passed all twelve commands on
clean HEAD `91351f555475b097a6450643fc83e8987e6a1ba1` (owner commit "phase 11"), with the six recorded
Phase 11 runs as inputs. Evidence: `experiments/phase-11/20260926-0445-p11-gate-verification/run.json`,
`verification.json` and `summary.json` (COMPLETED 2026-09-26 04:55:25 +03:00).

- Full regression: **1038 passed, 1 skipped, 44 warnings** in 492.36 s (same counts as the dirty-tree
  verification of 2026-09-25).
- Ruff, all seven import-boundary contracts, contract validation, environment smoke check and
  `git diff --check` passed.
- Six exported-model subprocess evaluations (GRU/TCN from the weighting run; `all` and `no-traj` for
  both families from the ablation run) reproduced their archived validation metrics within
  atol=1e-6/rtol=1e-5.
- 2,632 + 3,904 + 4 + 8 + 4 + 1,336 = 7,888 input-run artifacts matched their recorded hashes.
- Frozen geometry/commit/matching/metrics/report/selection/constants and the extended
  `eval/replay.py` unchanged versus HEAD; source unchanged during verification; `git_dirty_final`
  **false**.

This closes the executable clean-tree rerun of C-11-5 only. C-11-1 to C-11-4 (participant folds,
participant CV runs, owner pre-registration fields, confirmatory run and ship decision) remain open;
the verdict remains PENDING reviewer, proposed FAIL. Phase 12 proceeds only with independent
development machinery under its explicit instruction to continue executable work while participant
evidence and owner decisions stay PENDING.
