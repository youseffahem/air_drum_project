# Phase 10 — Exit gate

Status: PENDING reviewer. **Proposed verdict: FAIL for the full phase.**
Submitter: Codex. Reviewer: project owner, not yet signed. Date: 2026-09-24.

The independent temporal-model implementation is available, with synthetic
development training/export/replay and developer-recording parity. Research
acceptance requires participant evidence that this repository does not contain.
Neither the submitter nor successful unit tests can pass this gate alone.

## Execution environment

| Field | Recorded value |
|---|---|
| Codex model actually used | GPT-6 Astra — confirmed by the owner in this task |
| Reasoning effort actually used | High — confirmed by the owner; differs from the recommended Extra High |
| Execution date/time | 2026-09-24, Africa/Cairo (+03:00); exact timestamps in each run.json |
| First logged dependency check | `20260924-1907-p09-development-verification` |
| HEAD at start | `35f288523b0b06733e93454325bcab3e86b122ff` |
| Dirty at start | false (git status and dependency run logs) |
| HEAD at final verification | recorded in the final verification summary; no Git history changes requested/performed |
| Dirty during Phase 10 development | true; source file hashes accompany runs |
| Runtime / CPU | locked Windows Python 3.11 environment; PyTorch 2.14.0+cpu; HW-01 snapshots in run manifests |

The owner confirmed "GPT-6 Astra, High" during execution. Early machine manifests
truthfully recorded that the exact picker values were unavailable to the agent;
`experiments/phase-10/execution-confirmation.json` supplements those immutable
records with the owner's confirmation. No claim of Extra High execution is made.

## Dependency verification

Before edits on the clean owner HEAD, Phase 08's `--require-clean` verifier passed
all 14 commands and Phase 09's verifier passed all 12 development checks. Their
records are `experiments/phase-08/20260924-1909-p08-gate-verification/run.json` and
`experiments/phase-09/20260924-1907-p09-development-verification/run.json`.
The corresponding gate appendices close only the executable post-commit checks.
Participant data, primary W, harness freeze and reviewer decisions remain pending.

## Artifacts and task coverage

| Tasks | Artifact / status |
|---|---|
| 10.1–10.4 | IMPLEMENTED: `src/spacedrums/models/temporal/` fold reader, GRU, TCN, head, masked losses; unit/leakage/causality tests |
| 10.5 | IMPLEMENTED development training: seeded fold isolation, macro-ADE early stopping, logs/checkpoints/manifests; participant training PENDING |
| 10.6 | IMPLEMENTED Anticipator/decode and MODEL-only replay wrapper; direct strikes prohibited for temporal arms; geometry/commit unchanged |
| 10.7 | IMPLEMENTED TorchScript export, all-validation-sample parity, raw CPU timing and recorded GRU parity; participant model latency PENDING |
| 10.8 | IMPLEMENTED synthetic horizon sweep; participant experiment PENDING; `phase-10-horizon-sweep.md` |
| 10.9 | IMPLEMENTED and executed synthetic history/auxiliary sweep; participant experiment PENDING; `phase-10-window-aux.md` |
| 10.10 | IMPLEMENTED neutral selector and diagnostic comparison machinery; full participant comparison/paired CIs and winner PENDING; `phase-10-model-comparison.md` |
| 10.11 | IMPLEMENTED control-grid replay; participant FP attribution and owner budget PENDING; `phase-10-fp-control.md`, ADR-0025 |
| 10.12 | IMPLEMENTED synthetic failure figures/index; participant catalogue PENDING; `phase-10-failure-cases.md` |
| 10.13 | PENDING prerequisites; no held-out test run; `phase-10-test-run.md` |
| 10.14 | IMPLEMENTED development export reload/metric reproduction; selected-model clean/independent reproduction PENDING |

Candidate checkpoints/exports/manifests/latency files are stored under their
immutable `experiments/phase-10/<run>/models/cell-*/` directories. There is no
selected participant `models/temporal/<model_id>/` package yet. Scripts expose
training, grid sweeps, validation replay, latency, failure extraction and final
verification. README and ADR-0026 explain fixed-grid target and bounded-GRU choices.
Requirements in the RTM have not been advanced.

## Acceptance criteria

| # | Criterion | Result |
|---|---|---|
| 1 | GRU/TCN causal tests, export parity and latency | PARTIAL: executable development evidence; clean participant-model evidence pending |
| 2 | Horizon/window CV experiments with full tables/curves | NOT MET for participant CV; synthetic diagnostics only |
| 3 | FP budget and all rules predeclared before test | PARTIAL: draft protocol and tested neutral rule; numeric owner/validation decisions pending |
| 4 | A/B/C-GBDT comparison, participant CIs, multi-criteria ADR | NOT MET for research comparison; diagnostic tooling and pending ADR exist |
| 5 | Single confirmatory test run | NOT MET; intentionally unexecuted |
| 6 | Failure-case catalogue | PARTIAL: synthetic examples; participant failure categories absent |
| 7 | Selected-model reproducibility package | PARTIAL: candidate reload tests; selected clean/independent reproduction absent |

## Tests and development evidence

`tests/temporal/` covers future perturbation, N truncation and negative controls,
TCN receptive field, bounded-stateful GRU parity, masked payload/target behavior,
loss weights/velocity, fixed-grid gaps/tails, fold/test/normalization isolation,
deterministic seeds, both families' optional-head exports, artifact tampering,
Anticipator schemas, per-hand loss/reset, injected Phase 08 feature parity,
geometry-only strikes, a simpler arm winning selection, and refusal of held-out mode.
Phase 08 leakage and reference-read scans are also part of full regression.

`experiments/phase-10/recorded-parity.json`: DEV_CAPTURE diagnostic with
synthetic-trained GRU; 261 predictions compared, max absolute coordinate difference
2.0265579e-6 at atol=1e-6/rtol=1e-5 (combined tolerance passed). No accuracy claim.

The horizon run `20260924-1926-synthetic-horizon` completed 54 models/648 points.
Raw timing, parity, input hashes, manifests, per-step support and event records
accompany every model; source hashes are recorded per run. All numbers are DEVELOPMENT
diagnostics while dirty, not MEASURED thesis results. Supplementary execution
records below identify completed later checks and runs.

The first verifier `20260924-1940-p10-gate-verification` is a retained FAILED
development attempt: pytest collection found a duplicate test-module basename;
the new file was renamed. Its other checks passed. It is not the final test result.

The second verifier `20260924-1943-p10-gate-verification` is also retained FAILED:
976 tests passed, one skipped, and the shared-clock architecture test found a
direct `time` import in the new latency benchmark. The benchmark now uses
`spacedrums.timing.now`; all 38 targeted temporal/timing tests passed after the
fix. Historical timing artifacts retain their original timer description.
The final full regression record below supersedes this failed attempt.

Completed later development runs:

- `20260924-1936-synthetic-window`: 72 models, 1,296 replay evaluations, 4,807
  artifacts; all 72 export parity and metric-reload checks passed. The supplemental
  history/auxiliary figure separates N and probability thresholds; all p_aux=.7
  evaluations had no matches and are not presented as useful FP-control points.
- `20260924-2001-synthetic-comparison`: 363 evaluations and 529 artifacts, including
  nine GBDT fits. It reuses 216 N8/K4 temporal evaluations from the horizon run.
  A/B/C-GBDT trajectory had no matched events in the scripted fixture; the comparison
  report records this limitation and selects no winner.

The two sweeps together produced 126 temporal models with passing export checks.
These runs used earlier development source hashes; the window run predates the
clock-only fix, and the horizon run also predates later validation/adapter/loss
test refinements. Final source and subprocess reload evidence are archived
separately. The final source archive is not asserted to be each historical run's
exact source, and none of this evidence meets clean independent reproduction.

## Final developer verification

`experiments/phase-10/20260924-2006-p10-gate-verification/run.json` completed
successfully. All eight commands passed:

- Full regression: **977 passed, 1 skipped, 11 warnings**, 1000.12 seconds.
- Ruff, all seven import-boundary contracts, contract validation, environment
  smoke check and `git diff --check` passed.
- GRU and TCN exported-model subprocess evaluations reproduced the archived
  validation metrics within atol=1e-6/rtol=1e-5.
- All 2,671 horizon and 529 comparison artifacts matched their recorded hashes.

The verification summary confirms unchanged source throughout the run and no
changes to frozen geometry, commit, matching, metrics, reporting, selection or
evaluation constants. Final HEAD is
`35f288523b0b06733e93454325bcab3e86b122ff`; final git_dirty is **true**.
This is a successful development check, not a clean-environment reproduction or
a Phase 10 research PASS. TorchScript deprecation warnings remain visible in logs.

The completed supplement
`experiments/phase-10/20260924-2025-p10-evidence-bundle/run.json` verifies all
**8,021 artifacts** across the horizon, window, comparison and final-verification
records, and hashes those input run manifests. Four additional subprocess checks
reproduce the window run's GRU/TCN pure and auxiliary model metrics. It includes
the owner-confirmed GPT-6 Astra / High execution record, DEV recording parity,
failure figures, the separated history/auxiliary figure, source hashes and
`source.zip` containing the final development source/config/test files and lock.
Its assembly script is retained. Source stayed unchanged during assembly;
HEAD stayed the same and git_dirty remained true. This supplement is DEVELOPMENT
evidence and does not create a selected participant model or independent validation.

## Integrity checklist (submitter assessment; reviewer must verify)

| Item | Assessment | Evidence / limitation |
|---|---|---|
| I-1 labels/provenance | YES | development/synthetic labels, per-run manifests; no participant numbers invented |
| I-2 tested implementation | YES subject to final verification record | named tests and executable CLIs; research outcomes remain pending |
| I-3 causality | YES | future/truncation tests, masks, reference import/read guards |
| I-4 no fabricated evidence | YES | original explicitly synthetic fixture retained as such; DEV used for parity only |
| I-5 native FPS only | YES | candidate 1/30 grid is not reported as a new FPS measurement |
| I-6 no latency-reduction claim | YES | inference compute is separate from Phase 18 sound measurement |
| I-7 marker conditions | N/A for model fixtures | DEV parity is tip-only replay, not a markerless accuracy benchmark |
| I-8 ML split isolation | YES for development checks; participant PENDING | disjoint synthetic grouping keys and train-only normalization; no participant claim |
| I-9 scope | YES | one optional logit only; no next phase/live integration/Transformer |
| I-10 status vocabulary | YES | phase PENDING; RTM unchanged; no self-issued PASS |
| I-11 clean reproducibility | NO | Phase 10 uncommitted, generic parent run envelopes plus detailed model/plan artifacts; independent selected-model reproduction absent |
| I-12 limitations | YES | each report and pending ADR states missing evidence |

## Deviations and unresolved evidence

- Dependency gates are not passed. Only independent engineering/diagnostic work
  proceeded, as expressly directed in the phase execution instructions. Synthetic
  training does not substitute for the mandated ds-v1.0 CV/test experiments.
- Stateful GRU uses bounded start-state lanes, rebuilding for window-relative
  features. Indefinite O(1) state carry would contradict N-truncation parity.
- Targets are resampled on a fixed grid; input resampling/live parity is Phase 13.
- Fixed-grid FDE support is explicit. No unobserved endpoint is scored as present.
- The history sweep's K=4 is a development candidate, not a selected horizon.
- TorchScript is tested; ONNX is not claimed. Deprecation warnings are retained.
- Development timing ran alongside other repository checks; it is not a controlled
  deployment-performance comparison. Parameter bytes are not peak process RSS.
- Participant paired comparisons, complete baseline trajectory/latency resource
  tables and all failure subtypes remain PENDING. The protocol-specific single-run
  test ledger/runner remains pending the actual frozen protocol. It is not replaced
  by a generic unsafe test sweep.
- Parent RunLog envelopes use the existing prototype config and no-participant
  dataset marker; exact model/training/grid/fixture versions, rosters and hashes
  reside in hashed plan/model artifacts. This development envelope is not promoted
  to participant reproducibility evidence.

## Required exit-gate actions

1. Close participant-dependent Phase 07/08/09 conditions with real reviewed
   ds-v1.0 data, fold samples/stats, Baseline A/B/C results, primary W and harness freeze.
2. Run the participant CV horizon/history/aux/control experiments, complete all
   comparator/paired-CI/resource tables, and decide FP/FN/timing/CPU budgets with the owner.
3. Freeze H/N/family/final-fit recipe/operating points and archive the completed
   pre-registration before implementing/validating the protocol-specific one-run
   ledger and performing the single held-out evaluation. Never retune on its results.
4. Complete participant failure catalogue and selected export reproduction in a
   clean environment or by a second person; only then consider VALIDATED status.
5. Owner controls commit/tag/push. After an owner commit, automatically rerun
   `scripts/verify_phase10.py --require-clean` with the recorded run directories;
   reviewer evaluates all criteria and signs. Do not start Phase 11 on this record.

Reviewer signature: **PENDING**. No PASS, tag, commit, push, or next phase performed.

## Post-owner-commit verification — 2026-09-25

Before any Phase 11 edit, `scripts/verify_phase10.py --require-clean` passed all ten
commands on clean HEAD `bd0bcf8a99e0a0fe1fed13e9869892e5cec1dd81` (owner commit
"phase 10"), with the horizon, window and comparison runs as inputs. Evidence:
`experiments/phase-10/20260925-0840-p10-gate-verification/run.json`,
`verification.json` and `summary.json` (COMPLETED 2026-09-25 08:51:32 +03:00).

- Full regression: **977 passed, 1 skipped, 11 warnings** in 592.53 s.
- Ruff, all seven import-boundary contracts, contract validation, environment smoke
  check and `git diff --check` passed.
- Four exported-model subprocess evaluations (GRU/TCN from the horizon run, GRU/TCN
  auxiliary cells from the window run) reproduced their archived validation metrics
  within atol=1e-6/rtol=1e-5.
- 2,671 + 4,807 + 529 = 8,007 input-run artifacts matched their recorded hashes.
- Frozen geometry/commit/matching/metrics/report/selection/constants unchanged;
  source unchanged during verification; `git_dirty_final` **false**.

This closes the executable clean-tree rerun of required action 5 only. The
participant, budget, selection, held-out and independent-reproduction actions 1–4
remain open; the verdict remains PENDING reviewer, proposed FAIL. Phase 11 proceeds
only with independent development machinery under its explicit instruction to
continue executable work while participant evidence and owner decisions stay PENDING.
