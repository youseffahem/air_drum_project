# Phase 15 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 15 — Visualization / Debug Dashboard |
| Phase document | `phases/phase-15-debug-dashboard.md` |
| Submitter | Codex, acting for project owner |
| Reviewer / review date | Project owner — PENDING |
| Execution environment | GPT-5 Codex at start, then GPT-6 Codex after a runtime model switch; exact GPT-6 variant and reasoning effort **UNVERIFIED** (not exposed); recommended GPT-6 Sol/High not claimed |
| Start | 2026-09-26 11:01 +03:00; `f40e90b50e6766e9baf18e2e6a94c9d50c5187c7`, clean |
| Final verification | 2026-09-26 12:24 +03:00; `f40e90b50e6766e9baf18e2e6a94c9d50c5187c7`, dirty with Phase 15 work; full pytest, lint, seven import contracts and export reproduction passed |
| **Verdict** | **PENDING reviewer**; submitter cannot issue PASS |

## Dependency verification

Before Phase 15 edits, `scripts/verify_phase14.py --require-clean --executor-model "GPT-5 Codex"
--executor-effort "UNVERIFIED"` passed all 26 commands on clean owner commit `f40e90b...`.
Evidence: `experiments/phase-14/20260926-1102-p14-gate-verification/`. This closes Phase 14's
executable post-owner-commit condition only. Its live-person calibration/repeatability evidence
and owner signature remain PENDING; this Phase 15 authorization is recorded rather than treating
the Phase 14 research gate as passed.

## 1. Artefacts

| Artefact | Path | Status | Present? |
|---|---|---|---|
| Full toggleable overlay and theme | `src/spacedrums/ui/{overlay,theme}.py` | IMPLEMENTED development | yes |
| Non-blocking bus, timing/dashboard panel | `src/spacedrums/ui/dashboard.py` | IMPLEMENTED development | yes |
| Replay/GT viewer and clip export | `src/spacedrums/ui/replay_viewer.py`; labelled GT clip `experiments/phase-15/20260926-phase15-overhead/gt-replay.mp4` (1,131 frames, opens) | IMPLEMENTED development | yes |
| Frame/plot/table/summary exports | `src/spacedrums/ui/export.py` | IMPLEMENTED development | yes |
| Live integration and read-only gate traces | `src/spacedrums/app/{main,pipeline}.py` | IMPLEMENTED development | yes |
| User procedure | `docs/user/debug-overlay.md` | IMPLEMENTED | yes |
| Overhead report and run | `docs/reports/phase-15-overhead.md`, `experiments/phase-15/20260926-phase15-overhead/` | MEASURED development replay | yes |
| Framework decision | `docs/decisions/ADR-0038-dashboard-framework.md` | Accepted development decision; owner review PENDING | yes |
| Tests and measurement runner | `tests/ui/test_phase15_dashboard.py`, `scripts/measure_phase15.py` | IMPLEMENTED | yes |

## 2. Acceptance criteria

| # | Criterion | Evidence | Result |
|---|---|---|---|
| 1 | All listed overlay elements implemented and toggleable | `OverlayConfig`, scientific renderer, live `decision_traces`, overlay screenshot, toggle/bus/replay tests | MET live; replay search-region/rejection detail limited by existing recorded streams |
| 2 | Timing panel labels predicted vs estimated correctly | `timing_row`; `test_timing_labels_never_call_live_prediction_estimated`; dashboard screenshot | MET |
| 3 | Replay viewer with GT overlay works on dataset sessions | frame-ID index and Phase 09 matcher; synthetic recorded session test proves MATCHED and UNMATCHED; ds-v1.0 unavailable | PARTIAL: machinery MET, reviewed ds-v1.0 evidence PENDING |
| 4 | Export tools produce thesis-ready artefacts | annotated PNG, SVG/PNG plots, timing/FP CSV and summary JSON in cited run | MET as development exports; legacy replay has no valid processing-time series |
| 5 | Overhead measured; experiment mode within bound; dashboard ADR recorded | final incremental p95 2.782 ms <= 5.0 ms; three confirming optimized runs; ADR-0038 | MET on cited development replay; earlier pre-optimization failure retained |

## 3. Tests

Final stable-source verification on the dirty Phase 15 tree: `python -m pytest -q` passed
(exit 0, including causal tests); `ruff check src scripts tests`, `ruff format --check` for
changed Python files, seven import-linter contracts, and `git diff --check` passed. The
12 focused Phase 15 tests passed. Headless synthetic and recorded-replay application runs
with the dashboard enabled passed. The labelled GT clip opened with 1,131 frames;
annotated PNG, SVG/PNG plots, CSV tables and JSON summary were reproduced in the final
measurement run. These are development-tree results, not post-owner-commit verification.

## 4. Measurements

| Quantity | Label | Value | run id | Method / hardware |
|---|---|---:|---|---|
| experiment overlay incremental p95 | MEASURED development replay | 2.782 ms (bound 5.0 ms, PASS) | `20260926-phase15-overhead/final` | identical 171-frame Phase 05 developer replay, five repeats; local Windows workstation (replay records marked HW-01) |
| full overlay incremental p95 | MEASURED development replay | 2.589 ms | same | same |
| bounded OpenCV queue publisher p95 | MEASURED development stress | 0.0017 ms | same | 5,000 immediate publishes; 4,998 UI drops; local Windows workstation |
| local JSON socket publisher p95 | MEASURED development prototype | 0.0277 ms | same | 5,000 immediate sends; browser rendering excluded |

All are software wall-time diagnostics. No physical, acoustic, live-camera, participant, or latency-
reduction claim is made.

## 5. Integrity checklist — submitter assessment; reviewer must verify

| Item | Assessment | Evidence / limitation |
|---|---|---|
| I-1 numbers labelled | YES | report labels development replay/stress measurements and target bound |
| I-2 implementation tested | YES development; clean commit PENDING | full pytest, focused tests, lint/import contracts and exports passed on dirty Phase 15 tree |
| I-3 causality | YES | UI reads post-decision immutable records; no decision input or future-frame access added |
| I-4 no fabricated evidence | YES | cited replay is explicitly a Phase 05 developer capture; no participant evidence claimed |
| I-5 native FPS only | YES | 30 fps appears only as target frame-period basis, not measured camera FPS |
| I-6 no latency reduction claim | YES | report explicitly excludes physical/acoustic/end-to-end claims |
| I-7 marker labels | YES | existing overlay retains `FALLBACK/BENCHMARK` marker tag |
| I-8 participant split | N/A | no training/model result |
| I-9 scope | YES | scientific OpenCV UI only; no realistic kit visuals |
| I-10 status vocabulary | YES | phase PENDING gate; RTM not advanced by submitter |
| I-11 clean reproducibility | NO pending owner commit | development evidence is from dirty Phase 15 tree; clean rerun required |
| I-12 limitations | YES | user guide/report/ADR and this record state limitations |

## 6. Deviations

- The selected dashboard is an OpenCV secondary window, not Qt/Tk. It reuses the fixed project
  dependency and won the measured framework comparison.
- A browser candidate was prototyped at the non-blocking local JSON transport boundary only;
  DOM rendering was excluded and is recorded as such.
- No reviewed `ds-v1.0` exists. Replay/GT integration is verified on the repository's labelled
  SYNTHETIC session and must be repeated on `ds-v1.0` when available.
- The cited overhead run uses a Phase 05 developer replay, distinct from the labelled SYNTHETIC
  session used for the GT integration test. One pre-optimization overhead run exceeded the
  provisional bound (6.277 ms); the failure and subsequent results are preserved in the report.
- Live gate-rejection traces are read-only `FrameResult` diagnostics and are not added to the
  causal record schemas. Recorded replay therefore shows persisted candidates/commits but not
  historical rejection reasons.
- The open Baseline-B-shadow question is resolved: hidden with all trajectories in experiment
  mode, visible alongside Arm C in full mode.

## 7. Required exit-gate actions

1. Owner reviews element coverage, screenshots, label wording, measurements and integrity items.
2. After owner commit, rerun the Phase 15 tests/measurement reproduction on a clean HEAD.
3. When available, open a reviewed `ds-v1.0` session and record matched/unmatched viewer evidence.
4. Owner controls commit, tag and push. Do not start Phase 16 before authorization.

Reviewer signature: **PENDING**.

## Post-owner-commit verification during authorized Phase 16

2026-09-26, clean HEAD `130c1fa4dfb9e65036d17aa9451a710c91cbc056`:
the full 1,256-test suite, lint/import/schema/smoke checks passed in
`experiments/phase-16/dependencies/20260926-1240-p13-gate-verification/`.
The Phase 15 reproduction used all 171 developer-replay frames, five repeats:

| Clean reproduction | Experiment incremental p95 | 5 ms bound |
|---|---:|---|
| `experiments/phase-16/dependencies/phase15-clean/` | 5.363 ms | FAIL |
| `experiments/phase-16/dependencies/phase15-clean-repeat/` | 2.454 ms | PASS |

Both results are preserved. They establish executable reproduction and material
wall-time variability, not a robust PASS for the overhead bound. Export artifacts
were reproduced in both runs. Environment/clean-state records are
`phase15-verification.json` and `phase15-repeat-verification.json` beside these runs.
Owner review and reviewed participant replay evidence remain PENDING. The owner
separately authorized Phase 16 performance work; this record does not sign its gate.
