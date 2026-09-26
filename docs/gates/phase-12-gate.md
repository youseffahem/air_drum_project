# Phase 12 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 12 — Trajectory Prediction Extensions (optional) |
| Phase document | `phases/phase-12-trajectory-extensions.md` |
| Submitter | Claude Opus 5.5 (Claude Code), acting for the project owner |
| Reviewer(s) | Project owner — PENDING |
| Review date | PENDING |
| Code state | start `91351f555475b097a6450643fc83e8987e6a1ba1` clean; final verification `91351f555475b097a6450643fc83e8987e6a1ba1` dirty: **yes** (Phase 12 uncommitted) |
| **Verdict** | **Proposed: FAIL for the full phase** — reviewer PENDING (see "Verdict options") |

Phase 12 was attempted as a bounded development exercise. The entry decision and go/no-go rule were
declared and hashed before any extension existed; E1–E5 are implemented, causality-tested,
exported and exercised once each through the frozen harness on the SYNTHETIC Phase 11 fixture; the
E3 CPU feasibility gate passed before any Tiny Transformer training. **No extension is adopted**:
the rule needs participant CV folds and the confirmatory run needs held-out participants, and
neither exists. Neither the submitter nor passing unit tests can pass this gate.

## Execution environment

| Field | Recorded value |
|---|---|
| Model actually used | **Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code** — not the recommended Codex GPT-6 Astra |
| Reasoning effort actually used | Not exposed to the agent; not asserted (the recommended "Extra High" is a Codex picker setting) |
| Execution date/time | 2026-09-26, 04:45–06:50 +03:00 (exact timestamps in each `run.json` / `execution.json`) |
| HEAD at start | `91351f555475b097a6450643fc83e8987e6a1ba1` ("phase 11"), `git_dirty` **false** (verified by the Phase 11 verifier at 04:45) |
| HEAD at final verification | `91351f555475b097a6450643fc83e8987e6a1ba1`; `git_dirty` **true** (no commit/tag/push performed) |
| Runtime / CPU | locked Windows Python 3.11 venv, PyTorch 2.14.0+cpu, HW-01 (Intel i7-7820HQ, 4 cores / 8 threads); hardware snapshots in every run manifest |

Every Phase 12 run's `execution.json` records `codex_model = "NOT CODEX: Claude Opus 5.5
(claude-opus-5-5) via Claude Code"` and reasoning effort "UNAVAILABLE to the agent; not asserted".

## Dependency verification (before any Phase 12 edit)

`scripts/verify_phase11.py --require-clean` on clean HEAD `91351f5` passed all twelve commands
(condition C-11-5): `experiments/phase-11/20260926-0445-p11-gate-verification` — full regression
1038 passed / 1 skipped, ruff, 7 import contracts, contracts, env smoke, `git diff --check`, six
exported-model metric reproductions, 7,888 input artifacts hash-verified, `git_dirty_final` false.
Recorded as an appendix in `docs/gates/phase-11-gate.md`. Phase 10's post-commit condition was
already closed on `bd0bcf8`. The Phase 10 and 11 gates remain PENDING reviewer (proposed FAIL), so
Phase 12 proceeds only with independent development machinery, as its execution instructions
require, and every participant-dependent item stays PENDING.

## 1. Artefacts produced

| Artefact (phase document) | Path | Status label | Present? |
|---|---|---|---|
| Entry decision | `docs/experiments/phase-12-entry-decision.md` | submitter proposal; owner budget Open Question | yes |
| Pre-registration addendum (go/no-go rule) | `docs/experiments/phase-12-prereg.md` | PENDING draft (inherited owner fields); archived `experiments/phase-12/predeclaration/` 04:59:01 | yes |
| Extension modules | `src/spacedrums/models/temporal/ext/{config,representations,uncertainty,decoding,long_horizon,attention,tiny_transformer,model,train,adapter}.py` | IMPLEMENTED | yes |
| Probabilistic geometry (`intersect_prob`, gate) | `src/spacedrums/geometry/probabilistic.py` (additive; `intersect.py` unchanged) | IMPLEMENTED | yes |
| Evaluation helpers | `src/spacedrums/eval/probabilistic.py`; `MODEL:C-TT` arm label in `eval/replay.py` | IMPLEMENTED | yes |
| Scripts | `scripts/{eval_extension,compare_extensions}.py` + `latency_extension.py`, `verify_phase12.py`, `_p12.py`, `explore_posthoc_sigma.py` (EXPLORATORY) | IMPLEMENTED | yes |
| Per-extension reports | `docs/reports/phase-12-{e1-long-horizon,e2-representations,e3-tiny-transformer,e4-uncertainty,e5-decoding}.md` | SYNTHETIC development diagnostics; participant CV PENDING | yes |
| Summary ("none adopted") | `docs/reports/phase-12-summary.md` | SYNTHETIC development; no adoption possible | yes |
| ADRs | `docs/decisions/ADR-0031` … `ADR-0035` | IMPLEMENTED machinery / MEASURED E3 feasibility (dirty); adoption PENDING | yes |
| Experiments | `experiments/phase-12/…` (git-ignored, hashed per `run.json`) | development | yes |
| Updated model / reproducibility package | none: nothing adopted (Task 12.8 not triggered) | N/A | — |
| Gate record | this file | PENDING reviewer | yes |

## 2. Acceptance criteria

| # | Criterion (phase document) | Evidence | Result |
|---|---|---|---|
| 1 | Entry decision recorded (attempt list or skip with justification) | `phase-12-entry-decision.md`, hash archived before any extension code; priority order justified from the SYNTHETIC failure evidence, participant re-ordering rule stated | **MET** as a submitter proposal (the compute/time budget is the owner's Open Question) |
| 2 | Go/no-go rule pre-declared | `phase-12-prereg.md` archived 04:59:01; unchanged documents enforced by every grid run (`eval_extension.py` refuses otherwise), recorded by the comparison and exploratory runs and re-checked by `verify_phase12.py`; rule implemented and unit-tested (`test_ext_protocol.py`) | **MET** as a procedure; inherited numeric fields (FP budget, FN ceiling, W, δ_TE, δ_lead, CPU budget) PENDING |
| 3 | Each attempted extension has a results report and an ADR | five reports + ADR-0031…0035 | **PARTIAL**: results are SYNTHETIC development runs, not the required participant CV-fold results |
| 4 | If adopted: confirmatory run and updated packages; if none adopted: a summary stating so | `phase-12-summary.md` | **PARTIAL**: none adopted because participant evidence is absent, not because the rule rejected every extension on CV folds |

## 3. Tests

| Test file | What it checks | Result | Where run |
|---|---|---|---|
| `tests/temporal/test_ext_causal.py` | TEST-CAUSAL-1/2 (future perturbation, N truncation, masked NaN payload, negative control) for every extension × GRU/TCN and the TT; attention masks every future position; TT encoder causal at every window position; E5 base reads the current frame only | pass | HW-01, 2026-09-26 |
| `tests/temporal/test_ext_representations.py` | config (one extension per model, hashes); increment/polynomial round trips; mixture head and relaxed WTA loss; detached-mean Gaussian NLL; bounded acceleration and train-only bound; layout rows through probabilistic geometry; decoding of offsets/velocities/layouts; every extension (incl. C-TT) commits only through geometry, future frames cannot change earlier commits; gate relabelling gated by the unchanged `p_commit`; ensemble adapter; calibration metrics | pass | HW-01 |
| `tests/temporal/test_ext_training.py` | no extension = Phase 10 training **bit for bit** (GRU, TCN); determinism, TorchScript parity, eager reload and tamper refusal per extension; held-out file never opened; two-rate targets = dense-grid columns; E5 base = Baseline B's CV extrapolation; refusals | pass | HW-01 |
| `tests/temporal/test_ext_protocol.py` | test partition / participant plan / missing reference / missing or INFEASIBLE E3 gate refused before any run directory; declared registry = pre-registration; go/no-go rule cases (GO, band, timing, CPU, feasibility, insufficient evidence, ensemble pairing) | pass | HW-01 |
| `tests/geometry/test_geometry_probabilistic.py` | certain prediction = deterministic candidate; shared Gaussian = analytic 1 − Φ(d/σ); independent draws; members 2/3, mixture 0.3 exact; two-rate offsets; gate never creates, only relabels; zone-specific probability | pass | HW-01 |
| Full regression | all suites incl. Phase 00–11 | see "Final developer verification" | HW-01 |

## 4. Measurements produced in this phase

All are development values on a dirty tree; the training/replay values are SYNTHETIC diagnostics on
`scripts/_p11_fixture.py`, never thesis results (integrity I-1).

| Quantity | Label | Value (summary) | run_id | Method | Hardware |
|---|---|---|---|---|---|
| E3 feasibility (random-init TorchScript, batch 1) | MEASURED development compute (dirty) | p95 GRU 3.358, TCN 3.211, TT 3.762 ms; budget 10.074 ms → FEASIBLE | `20260926-0519-tt-feasibility` | `latency_extension.py --feasibility` | HW-01 |
| Path latency / working set, 27 entries | development compute (isolated) | reference path p95 GRU 1.535, TCN 1.008 ms; TT 0.75 ×; E4 Gaussian 2.93/3.55 ×; ensemble 2.55/2.70 ×; working set ≈ 241 MB (runtime), +4–7 MB per model | `20260926-0624-ext-latency-memory` | `latency_extension.py --runs` | HW-01 |
| Reference and E1–E5 development grids | SYNTHETIC development | see the reports and `phase-12-summary.md` | `20260926-0528/-0533/-0541/-0550/-0611/-0621-…` | `eval_extension.py` | HW-01 |
| Go/no-go (development verdicts) | SYNTHETIC development | every variant NO-GO (TCN) or insufficient evidence (GRU) | `20260926-0629-synthetic-go-no-go` | `compare_extensions.py` | HW-01 |
| E4 calibration (reliability, ECE, Brier, AUC) | SYNTHETIC development | e.g. TCN AUC: reference 0.762, ensemble 0.828, exploratory post-hoc 0.924 | E4, exploratory runs | offline crossing probability vs `strike_within_H` | HW-01 |
| Post-hoc variance head | **EXPLORATORY** (not pre-declared) | GRU feasible 5/12 with the gate vs 2/12 without; mean bit-identical to the reference | `20260926-0547-exploratory-e4-posthoc` | `explore_posthoc_sigma.py` | HW-01 |

## Final developer verification

`experiments/phase-12/20260926-0634-p12-gate-verification/run.json` — COMPLETED 2026-09-26
06:45:03 +03:00, `RESULT PASS` for a dirty tree. All 27 commands passed:

- Full regression **1110 passed, 1 skipped, 58 warnings** (478.11 s). It was 1038/1 at the Phase 11
  clean verification; the 72 added tests are Phase 12's.
- Ruff; import-linter 7 contracts kept (incl. `no-peek`: models never import geometry); contract
  validation; environment smoke; `git diff --check`.
- 21 subprocess reproductions of exported-model validation metrics (atol 1e-6, rtol 1e-5), one per
  variant and family of every grid and the exploratory run.
- 10,620 artifacts of the ten input runs matched their recorded hashes.
- Frozen Phase 04 geometry files, the Phase 05 commit package, the Phase 09 matching/metrics/
  report/selection/constants, `eval/temporal.py` and every Phase 10/11 model module unchanged versus
  HEAD; the only changed harness file is the additive `eval/replay.py`. The archived
  pre-declaration still matches both documents. Source unchanged during verification;
  `git_sha_final` `91351f5`, `git_dirty_final` **true**.

This is same-environment development verification, not a clean or independent reproduction and not
a research PASS. TorchScript deprecation warnings remain visible in the logs. After this run only
documentation changed (this record, `scripts/README.md`); `git diff --check` was re-run on them.

## 5. Integrity checklist (submitter assessment; reviewer must verify)

| # | Item | Assessment | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled | YES | every report labels values SYNTHETIC DEVELOPMENT with run ids; the exploratory run is labelled EXPLORATORY; candidates marked |
| I-2 | No implementation claim without tests | YES (dirty tree) | §3; clean rerun after the owner commit is condition C-12-5 |
| I-3 | No causal component consumes future frames | YES | TEST-CAUSAL-1/2 on every new encoder/head/decoder; attention mask tests; replay future invariance for extension commits |
| I-4 | No fabricated data | YES | fixture named and labelled SYNTHETIC in ids, plans and reports; no participant, consent or label invented |
| I-5 | FPS native only | YES / N/A | the fixture's 30 Hz grid is a scripted candidate, never reported as FPS |
| I-6 | No "latency reduced" claim | YES | lead is offline commit-to-label time; latency is inference compute only |
| I-7 | Marker condition labelled | N/A | no markers; synthetic tracks |
| I-8 | Participant-level split | YES for development; participant PENDING | fixture split by `P07-SPLIT-1`, held-out identity never opened (tested); E5 statistics, E5(b) bound and exploratory fits use training folds only |
| I-9 | Scope respected | YES | no live integration, no bidirectional or future-attending layer, no adoption, no schema bump, frozen Phase 04/05/09 files and Phase 10/11 model code unchanged |
| I-10 | Status vocabulary correct | YES | phase PENDING; RTM rows stay PLANNED with evidence pointers; no self-issued PASS |
| I-11 | Reproducibility fields complete | **NO** | runs are `git_dirty: true`; clean rerun and independent reproduction pending (C-12-5) |
| I-12 | Limitations stated | YES | every report ends with limitations |

## 6. Deviations from the phase document

| What | Why | Impact on dependents |
|---|---|---|
| Executed on the SYNTHETIC Phase 11 kinematic fixture, not ds-v1.0 CV folds | ds-v1.0 does not exist | no number may enter Phase 18/19 or the thesis as a result |
| `intersect_prob` lives in a new module `geometry/probabilistic.py` instead of a method in `intersect.py` | keeps every existing geometry file byte-identical ("deterministic path unchanged" by construction) | none; `verify_phase12.py` audits the frozen files |
| `eval/replay.py` gained the `MODEL:C-TT` arm label | `Arm.C_TT` existed in the contracts, the replay did not accept it | additive; every other arm unchanged (full regression) |
| The crossing gate reads the current tip from `eval/probabilistic.AnchorRecorder` | the replay's post-geometry hook receives only (prediction, candidate) | a live pipeline passes the track's tip; recorded in ADR-0034 |
| EXPLORATORY post-hoc variance head run (not pre-declared) | the declared E4(a) confounded the gate with a degraded mean | outside the rule; only informs a proposed E4(a′) declaration (owner) |
| Declared E4(a) design flaw found in development | NLL through the shared encoder from σ ≈ 1 degraded the mean | recorded; `e4-gauss` kept as declared, not modified post hoc |
| Comparison run executed twice (`…-0627-…` superseded by `…-0629-…`) | a clipped figure title | identical verdicts and gate-effect analysis (checked) |
| Development operating points picked per fold on its single validation identity | the fixture has one validation identity per fold | participant-macro aggregation across validation participants must be implemented with the participant plan |
| Grid latencies measured with three parallel workers; the exploratory run shared the CPU with the E2/E1 grids | wall-clock budget | marked contended; the CPU criterion uses the isolated latency run only |
| `_p12.py` gained the `EXPLORATORY_PROBABILISTIC` constant during the E1 run | the latency script had to time the exploratory gate | each run's `source-hashes.json` records the code it ran; the constant is unused by the grid runner |
| Model/effort not the recommended Codex profile | executed by Claude Opus 5.5 | recorded truthfully above |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase |
|---|---|---|
| Compute/time budget for participant CV; accept, reduce or defer the attempt | Open Question (owner) | Phase 12 re-gate |
| Declare the post-hoc variance head as E4(a′) before participant CV | Open Question (owner) | before any participant run |
| Participant CV go/no-go for every declared variant | To Be Experimentally Determined | Phase 12 re-gate (after Phase 09/10/11 gates, ds-v1.0) |
| Whether the crossing probability should replace τ_commit gating | Open Question (phase document) | participant CV |
| Participant-macro aggregation of operating points in the extension runner | Pending Architecture Decision | participant plan implementation |
| `modes` contract field if rule M2 is ever adopted | Pending Architecture Decision | on adoption (ADR-0032) |
| TT on the target CPU budget | Pending Benchmark | Phase 13/16 |
| Per-step uncertainty in V1 (architecture Open Question) | Open Question | Phase 12 re-gate / Phase 13 |

## 8. Conditions (if the reviewer chooses PASS-WITH-CONDITIONS)

| Condition | Owner | Must be closed by |
|---|---|---|
| C-12-1 Phase 09/10/11 gates, reviewed ds-v1.0 participant folds and the inherited owner budgets | owner / Phases 07–11 | before any Phase 12 participant run |
| C-12-2 Owner decision on the participant budget/priorities and on E4(a′); archive the amended pre-registration | owner | before any Phase 12 participant run |
| C-12-3 Participant CV runs of the declared variants with participant-macro aggregation; ADR-0031…0035 decisions | submitter | Phase 12 re-gate |
| C-12-4 Task 12.8 confirmatory run for any GO variant, or a participant-based "none adopted" summary | submitter + reviewer | Phase 12 re-gate |
| C-12-5 After the owner commit: `scripts/verify_phase12.py --require-clean --runs <recorded runs>` | submitter | next phase start |

## Verdict options

The submitter proposes **FAIL for the full phase**, consistent with the Phase 10 and 11 records:
criteria 3 and 4 require participant CV results that do not exist, and I-11 is NO. Phase 12 is
optional, however, and no later phase depends on its outputs (Phase 13 lists it as optional). The
reviewer may therefore instead (a) record **PASS-WITH-CONDITIONS** scoped to the entry decision, the
declared rule and the machinery, with C-12-1…5, or (b) convert the entry decision into a documented
**deferral/skip**, which the phase document allows.

## 9. Reviewer statement

PENDING. The reviewer should open the entry decision, pre-registration and archived hashes, the
five reports and the summary, the `run.json` files, and rerun `scripts/verify_phase12.py` on the
committed tree. Signed: —
