# Phase 13 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 13 — Real-Time Inference Integration |
| Phase document | `phases/phase-13-realtime-inference.md` |
| Submitter | Codex, acting for project owner; actual model/effort UNVERIFIED |
| Reviewer / review date | Project owner — PENDING |
| Start | 2026-09-26 08:23:03 +03:00; `0714a75133608f47be430324d9f3154e844e411b`, clean |
| Final verification | 2026-09-26T09:38:58+03:00; same HEAD, dirty=true; 10/10 commands passed |
| Verdict | PENDING reviewer; submitter proposes FAIL for the full phase while required evidence is absent |

## Dependency verification

Before source edits, `scripts/verify_phase12.py --require-clean --runs <12 completed runs>`
passed all 27 commands on clean HEAD `0714a75133608f47be430324d9f3154e844e411b`.
Evidence: `experiments/phase-12/20260926-0824-p12-gate-verification/`.
Regression: 1,110 passed, 1 skipped; lint, seven import contracts, schema validation,
environment smoke and diff check passed. All 21 export reproductions and 10,683 input
artifacts passed. Source and clean state stayed unchanged. This closes C-12-5's
executable rerun only. Phase 05 C-05-5, Phase 10's and Phase 11 C-11-5's post-commit
checks were already recorded as closed; their person/participant/reviewer conditions remain.

The inherited Phase 12 verifier incorrectly hard-codes its earlier Claude executor
in `execution.json`. For **this rerun**, that executor field is superseded by
`experiments/phase-13/20260926-integration/execution-start.json`: actual model and
reasoning effort are UNVERIFIED. The user explicitly instructed against inferring
the recommended settings. Test outcomes and hashes from the verifier are unaffected.

## 1. Artifacts

| Artifact | Path | Status |
|---|---|---|
| Verified package checks; causal per-hand arm; budget and fallback | `src/spacedrums/prediction/{model_loader,model_arm,budget_monitor,fallback}.py` | IMPLEMENTED development |
| Model assembly / runtime switch / live pipeline | `src/spacedrums/app/{arms,pipeline,main}.py` | IMPLEMENTED development |
| Feature, prediction and timing streams; session metadata | app recorder, timing collector, Phase 06 recorder/schema | IMPLEMENTED development |
| Parity, raw causality, timing, faults and gate runners | `scripts/{parity_test,live_latency,phase13_faults,verify_phase13}.py`, `_p13.py` | IMPLEMENTED development |
| Tests | `tests/parity/`, schema test update | IMPLEMENTED |
| Config and running instructions | `configs/live.arm-C.candidate.yaml`, `configs/README.md`, app README | IMPLEMENTED candidate |
| Reports | `docs/reports/phase-13-{parity,live-timing}.md` | development diagnostics / required evidence PENDING |
| Architecture decision | `docs/decisions/ADR-0036-live-model-integration.md` | IMPLEMENTED development decision |
| Final evidence | `experiments/phase-13/20260926-0928-p13-gate-verification/` | IMPLEMENTED verification; all 10 commands passed |

## 2. Acceptance criteria

| # | Criterion | Evidence / remaining work | Result |
|---|---|---|---|
| 1 | Arm C runs live with verified model; per-hand state resets on tracking loss; causality tests pass in live mode | Verified GRU/TCN integration, synthetic safety tests and raw replay causality; shipped package and developer live strokes absent | PARTIAL |
| 2 | Arm switch and shadow mode work; active arm recorded per commit | Three-arm tests; suppressed transition frame; shadow audio test; metadata/commit streams | MET as tested development machinery |
| 3 | Fallback triggers on injected faults; no fabricated strikes during switches | Controlled fault traces, failure tests, runtime budget replay; sticky disable and warm baseline | MET as tested development machinery |
| 4 | TEST-PARITY-1 passes on designated sessions | Three raw developer sessions; participant fold unavailable | PARTIAL |
| 5 | Live inference/end-to-end software timing measured; delay constants reconciled with offline | Replay-only compute; per-frame parity delay; live timing and reconciliation absent | NOT MET |

## 3. Tests and execution record

Final stable-source verification completed: **1,138 passed, 1 skipped, 98 warnings**
in 492.71 s. All ten commands passed: full pytest, lint, seven import contracts,
schema validation, environment smoke, diff check, three-session raw parity/causality,
six injected faults and two replay timing runs. The warnings are retained in `00.log`.

Verification ran from `2026-09-26T09:28:21+03:00` to
`2026-09-26T09:38:58+03:00` on HEAD
`0714a75133608f47be430324d9f3154e844e411b`. The tree was dirty at both ends;
source hashes were unchanged. Actual model and effort are UNVERIFIED.

The interrupted
`20260926-0905-p13-gate-verification` is retained as FAILED/INTERRUPTED: a targeted check
found a fixture collection-order collision. The parity fixture now has a unique helper
module; targeted checks pass and both test collection orders work.

The `20260926-0907-p13-gate-verification` attempt is also retained as
FAILED/INTERRUPTED. Review found that relative float tolerance could conceal timestamp
drift at large capture epochs. Timestamp comparison now uses absolute tolerance only,
and a negative control verifies rejection of a 10 ms change at a 125,000 s epoch.
The fixture producer regenerated two example hashes affected by the added timing
stamp; the stable-source run includes those generated updates.

The completed `20260926-0916-p13-gate-verification` run is retained as FAILED:
1,137 tests passed, one skipped and one failed because the C-MT refusal test still
expected the former A/B-only error message. C-MT was correctly refused. The assertion
now matches the unsupported C-MT label; all eight tests in that file pass. Its other
nine verification commands passed, with unchanged source hashes. The full verifier
was rerun successfully after this test-only correction.

The final verifier ran full regression, lint, import boundaries, contract validation,
environment smoke, diff check, raw parity/causality, injected faults, and two replay
timing modes. It records start/final source hashes, SHA, dirty state, timestamps,
hardware and config. Model/effort remain UNVERIFIED in every Phase 13 evidence record.

Final artifact audit: the run record validates against `experiment-log`; all
392 listed artifact hashes match. Current source matches the verified start snapshot.
Audit record: `experiments/phase-13/20260926-integration/final-audit.json`.

## 4. Measurements

See the two reports for development tables and exact run paths. These dirty-tree
runs are diagnostics, not MEASURED gate evidence under the reproducibility policy;
a clean post-owner-commit rerun remains required. Controlled fault durations are
SYNTHETIC. In-loop replay compute is distinct from live camera timing. No effective-latency or acoustic result is claimed.
Live inference percentiles, full live strike decomposition and live drop comparison
are PENDING. The model in all development runs is SYNTHETIC-trained, not shipped.

## 5. Integrity checklist — submitter assessment, reviewer must verify

| Item | Assessment | Evidence / limitation |
|---|---|---|
| I-1 numbers labelled | YES | reports separate candidates, development diagnostics, synthetic faults and pending measurements |
| I-2 implementation tested | YES for development; clean commit pending | parity/safety tests and executable verifier; no clean Phase 13 claim |
| I-3 causality | YES | delivered-frame assertions; future observation refusal; raw and synthetic perturbation tests |
| I-4 no fabricated evidence | YES | existing DEV recordings, explicitly SYNTHETIC weights/tests; no participant data invented |
| I-5 native FPS only | YES | requested rate and candidate guards are labelled; no new native-FPS claim |
| I-6 no latency reduction claim | YES | only software processing reported; acoustic/physical times absent |
| I-7 marker labels | YES | configured GEOM markerless path retained; no new marker benchmark |
| I-8 participant split | N/A for new model fitting; participant evidence PENDING | no training/selection in this phase; pinned prior synthetic fold stats |
| I-9 scope | YES | no optimization, calibration, participant experiments, audio cancellation or next phase |
| I-10 status vocabulary | YES | full phase PENDING; RTM statuses unchanged; no submitter-issued PASS |
| I-11 clean reproducibility | NO | Phase 13 changes uncommitted; clean rerun and owner review pending |
| I-12 limitations | YES | reports, ADR and acceptance table |

## 6. Deviations

- No shipped model or ds-v1.0 exists. Independent development integrates a pinned
  Phase 10 fixture, without making the Phase 10/11 ship decision or adopting Phase 12.
- The user confirmed no developer with sticks is available: live strike timing stays PENDING.
- Existing nested model config and seconds units are extended rather than duplicated
  by flat paths/hashes or milliseconds. Record arm names remain C-GRU/C-TCN.
- Windowed in-loop inference is implemented. Worker inference and automatic recovery
  remain optional and disabled; no worker-delay claim is needed.
- Raw images are the repository's lossless PNG video sequence format. Phase 09
  receives live causal tracks, with separate model/feature/geometry/commit state.
- Early exploratory replay outputs under `20260926-integration/` are superseded by
  the final stable-source run. Some code changed during exploratory work; those
  initial outputs are not cited as final source reproduction.

## 7. Required exit-gate actions

1. Owner/reviewer resolves dependency research gates and the actual ship ADR; pin
   that model's manifest/export/statistics in the deployment config.
2. Supply reviewed ds-v1.0 and run every session of the designated fold plus developer
   sessions through the roster-validated parity plan. Preserve failed cases and fixes.
3. Run developer live strokes, A active/B+C shadow then C active/A+B shadow; record
   in-loop inference, per-strike software terms and real frame drops. Review fallback
   and reconcile delay policy; rerun offline comparisons if material.
4. Review candidate budgets/rate guard and recovery decision at Phase 16 when authorized.
5. Owner controls commit/tag/push. After the owner commit, automatically run
   `scripts/verify_phase13.py --require-clean --parity-config <recorded config> --plan <recorded plan>`
   on that HEAD. The reviewer must evaluate every criterion and sign the gate.

Reviewer signature: **PENDING**. No Phase 14/15/16 work or Git publication is authorized
by this record. Stop at this Exit Gate.
