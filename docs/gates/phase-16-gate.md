# Phase 16 exit gate — performance optimization

**Status: PENDING owner/reviewer.** Date: 2026-09-26 (+03:00).
Submitter: Codex. Reviewer: project owner; signature **PENDING**.

The submitter recommends **FAIL for full-phase acceptance** until the missing
research inputs and clean reproduction are resolved. This is not a reviewer
verdict. Phase 17 has not started. Commit, tag and push remain owner-controlled.
The owner authorized independent Phase 16 work despite prior research/reviewer
conditions, and explicitly requested replay and unattended checks because no
person was available at the webcam.

## Execution provenance and dependencies

- Starting and final HEAD: `130c1fa4dfb9e65036d17aa9451a710c91cbc056`.
- Start tree clean. All Phase 16 implementation measurements use dirty source and
  are development diagnostics; clean post-owner-commit reproduction is PENDING.
- Initial provenance: `experiments/phase-16/execution-start.json`, recorded
  `2026-09-26T12:42:20.588402+03:00`. Dependency run began at 12:40 (+03:00).
  Every run has timezone-stamped start/finish and source hashes; final audit below.
- Actual exposed model: **GPT-6 family; exact deployed variant unavailable**.
  Actual picker reasoning setting: **unavailable to the agent**. The recommended
  Astra / Extra High settings are not asserted as actual execution settings.
- HW-01: i7-7820HQ, 4 physical / 8 logical cores, 15.9 GB RAM, CPU, Windows,
  AC power / Balanced plan. Exact environment and lock hashes are in run manifests.

Before production changes, `verify_phase13.py --require-clean` passed all ten
commands at current clean HEAD: **1,256 passed, 1 skipped**, static checks, seven
import contracts, schema/environment smoke, raw parity/causality, fault scenarios
and replay timing modes. Evidence:
`experiments/phase-16/dependencies/20260926-1240-p13-gate-verification/`.
Phase 15 clean five-repeat overlay reproduction first **failed** its 5 ms candidate
bound (5.363 ms incremental p95); the confirmation **passed** (2.454 ms).
Both runs are retained in `dependencies/phase15-clean*`, and both gate records are
updated. This closes executable checks while recording variability. Participant
data, model selection and reviewer conditions are still open.

## Acceptance criteria

| Criterion | Submitter assessment | Evidence / limitation |
|---|---|---|
| 1. Profiling and budget table complete | PARTIAL | Development baseline/final stage distributions, resource/allocation data and targets complete; representative live strokes and clean MEASURED evidence pending |
| 2. Before/after and regression for optimizations | PARTIAL | Retained changes pass developer/synthetic comparisons; rejected variants preserved. Reviewed participant fold and shipped-model regression unavailable |
| 3. Honest native 60 FPS report | MET as documented PENDING | Phase 02 camera capability fails the conditional preflight; no fabricated 60 FPS attempt |
| 4. Updated delay policy and material reruns | PARTIAL | Explicit unset live constant, materiality rule and same-model synthetic sensitivity; accepted live value and participant headline reruns pending |
| 5. Final causality/parity and soak | PARTIAL | Executable checks and five-minute unattended soak; person-dependent full workload and clean repeat pending |
| Definition of Done: reviewed PASS and integrity | NOT MET | Reviewer signature absent; I-11 remains NO |

## Artifacts

All reports are PENDING clean reproduction and gate acceptance:

| Artifact | Path |
|---|---|
| Profiling, resources and stage results | `docs/perf/phase-16-profiling.md` |
| Predeclared budget and achieved values | `docs/perf/phase-16-budget.md` |
| Incremental retain/reject log | `docs/perf/phase-16-perf-log.md` |
| Frozen regression protocol/results | `docs/perf/phase-16-regression.md` |
| Native 60 FPS shortfall | `docs/perf/phase-16-60fps.md` |
| Model export/quantization results | `docs/perf/phase-16-model-cost.md` |
| Delay policy and rerun manifest | `docs/perf/phase-16-delay.md`, `src/spacedrums/eval/constants.py` |
| Soak and audio buffer check | `docs/perf/phase-16-soak.md` |
| Executable tooling | `scripts/{profile_pipeline,fps_end_to_end,regression_check,model_cost,reconcile_delay,verify_phase16}.py`, `_p16*.py` |
| Pinned development roster/config | `configs/perf.regression-plan.json`, `configs/perf.developer.candidate.yaml` |

Production changes are OpenCV's explicit thread default, perception initialization
before capture, component-bound scans/lazy mask allocation, and a bounded arc-point
cache. The original float temporal package stays selected by the development
config. No record schema, causal algorithm, requirement or fallback threshold changed.

## Executable verification

Final retained-source run: `experiments/phase-16/20260926-1345-gate-verification/`.
`00.log` records **1,272 passed, 1 skipped, 107 warnings**, 489.58 seconds.
`01.log`–`05.log` record successful lint, seven import-layer contracts, schema
validation, environment smoke and whitespace checks. `06.log` records the frozen
raw/harness regression and future perturbation, with source hashes unchanged.
The remaining parity, fault and final-profile results and evidence audit are
recorded below. All new checks use dirty source at the
same HEAD; this does not satisfy clean reproducibility by itself.

All **10 commands passed**; `verification-summary.json` records the result.
`07.log` covers raw live/offline parity and future perturbation for all three
developer captures; `08.log` covers all six injected fault cases; `09.log` covers
the final nine session runs (three repeats per capture). Source hashes were
unchanged throughout verification, which finished at
`2026-09-26T13:57:27+03:00`; final SHA is the starting SHA above, dirty **true**.

| Final development observation | Result | Evidence |
|---|---|---|
| Replay processing p50/p95, baseline → retained | 39.636/58.429 → 37.073/56.302 ms | Profiling report and final `profile/20260926-1356-profile` |
| Frozen raw/harness comparison | PASS, no changed retained records/metrics | `regression/` and regression report |
| Five-minute unattended soak | 9,043 frames, 9 drops, 0 audio underruns, 1 overload fallback | `20260926-1337-soak` and soak report |
| Native 60 FPS | PENDING camera capability | `native-60fps.json` and 60 FPS report |
| Delay proxy change | -0.3821 ms; below 1 ms candidate rule | `20260926-1357-delay-reconciliation` |
| Synthetic delay sensitivity reruns | All nine A/B/C/version evaluations completed; no informative lead median | Same rerun manifest; participant headlines still pending |
| Evidence audit | 37 run manifests validate; 717 listed artifact hashes match; no source-change audit failures | `experiments/phase-16/final-audit.json` |

The final audit also passes lint, formatting for new Python files, tracked diff
whitespace and untracked-file trailing-whitespace checks. One failed initial
reference-script run and rejected candidate outcomes remain preserved. The audit
timestamp, final dirty state, source hashes and tracked-diff hash are recorded in
that file. All processes launched for these checks have finished.

## Integrity checklist — submitter assessment

| Item | Answer | Evidence / limitation |
|---|---|---|
| I-1 labels | YES | Dirty results identified as development; targets separate; reports name runs, HW-01 and date |
| I-2 tested implementation | YES development | Final executable report below; clean-commit status pending |
| I-3 causality | YES development | Raw future perturbation for retained inline, thread and process experiments; frozen record comparisons |
| I-4 no fabrication | YES | Existing DEV captures and explicitly SYNTHETIC validation only; no participant substitute |
| I-5 native FPS | YES | Camera timestamps for live delivery; replay capacity separate; native 60 FPS PENDING |
| I-6 effective latency claims | YES | Software timings only; no physical/acoustic anticipation or guaranteed sound-before-impact claim |
| I-7 marker condition | N/A | GEOM estimator; no marker experiment introduced |
| I-8 split | YES for engineering screen | Same pinned SYNTHETIC validation archive and split; no training/test partition access. Participant fold PENDING |
| I-9 scope | YES | CPU performance work only; no participant study, retraining or next phase |
| I-10 status | YES | Phase and gate PENDING; RTM statuses unchanged |
| I-11 reproducibility | NO | Source audits/manifests retained, but new measurements use dirty source; owner commit and clean rerun required |
| I-12 limitations | YES | Idle soak, fallback, camera limit, timing variance, missing shipped model/participant fold and live delay explicitly recorded |

## Deviations and outstanding inputs

1. Reviewed `ds-v1.0` fold unavailable. Repeat the fixed regression on the entire
   selected fold plus developer sessions once available; preserve the predeclared
   tolerances and actual reviewed provenance.
2. No owner-selected shipped model. Synthetic-trained GRU profiling is development
   evidence only. Graph freezing was screened through the existing TorchScript
   runtime; ONNX migration/stateful inference were not implemented or claimed.
3. No person available: idle camera/audio/dashboard checks and replay were run.
   Representative strokes, polyphony and accepted live `Δ_proc` remain PENDING.
   Repeat Phase 09/10 participant headlines with the same frozen models if material.
4. Webcam cannot deliver native 60 FPS. Owner acquisition decision remains open;
   repeat Phase 02 capability checks before any 60 FPS pipeline attempt.
5. No direct GIL-wait measurement. Thread CPU and synchronous native-call waits
   are documented without claiming Python lock contention caused the bottleneck.
6. Clean Phase 15 bound varied across runs; robustness is not established by the
   passing confirmation. UI target and full pipeline frame budget remain separate.
   The retained dirty-source repeat (`experiments/phase-16/phase15-retained`, all
   171 frames, five repeats) passes at 0.713 ms incremental p95. It does not replace
   the two preserved clean dependency results.

## Exit actions

Owner/reviewer reviews the evidence and resolves the conditions above under
[the gate procedure](gate-procedure.md). After the owner commits, run
`verify_phase16.py --require-clean --reference <preserved snapshot.json>` and
repeat the live/soak/model timing checks under the documented conditions. A commit
alone does not satisfy the gate. When a next phase is authorized, outstanding
post-owner-commit verification must run before dependent work.

Reviewer verdict/signature/date: **PENDING**.
