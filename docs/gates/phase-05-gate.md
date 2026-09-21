# Phase 05 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 05 — Rule-Based Baseline & First Playable Prototype |
| Phase document | `phases/phase-05-rule-based-baseline.md` |
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-21 |
| Reviewer(s) | Project owner — review pending |
| Review date | 2026-09-21 (submission) |
| Code state | base `36f2d4eb5623b1c9bf2ffa8e72d5c0b9c80580b0` / dirty: **yes** (owner required no commit; every run cited below carries `git_dirty: true`) |
| **Verdict** | **PROPOSED PASS-WITH-CONDITIONS — owner verdict pending.** The machine-executable scope of Tasks 05.1–05.5 and the machinery of 05.6–05.10 is IMPLEMENTED with tests (485 passed); causality tests pass; the synthetic safety test shows zero commits on non-VALID frames. Acceptance criteria **3** and **5** are **NOT MET** as measurements (playability with sticks; a software-stamped `L_sys_est` decomposition) and criterion 6 is met only as a *candidate* file, because every measurement they need is person-dependent (no new recording was made, on the owner's instruction) or depends on the Phase 04 audio-output latency that is still PENDING. Whether "PASS-WITH-CONDITIONS" or "FAIL" is the right reading is the owner's call; the submitter proposes conditions C-05-1…C-05-5 below and notes that the phase document's *Definition of Done* (playability report with counts, safety-test log, timing decomposition) is **not** satisfied by this submission. |

**Dependency note.** Phase 04's gate record proposes **FAIL** (criterion 6: physical audio output latency PENDING) and states "Phase 05 and later work must not start". Phase 05 was executed on the owner's explicit instruction. This record does not reinterpret Phase 04's evidence: the audio-output term stays PENDING everywhere below, and `t_audio_out_est` is withheld from every timing record (ADR-0018 §7).

## 1. Artefacts produced

| Artefact (from phase document) | Path | Status label | Present? |
|---|---|---|---|
| `prediction/rule_based.py` — Baseline B (`Anticipator`, `source = RULE`, CV and CA) | `src/spacedrums/prediction/{base,rule_based}.py` | IMPLEMENTED | yes |
| Reactive path wiring — Baseline A (`source = REACTIVE`) | `src/spacedrums/app/pipeline.py` (+ Phase 04 `GeometryEngine.observe`) | IMPLEMENTED | yes |
| `commit/` — state machine, refractory, duplicate suppression, safety gates; `CommitPolicy` | `src/spacedrums/commit/{state_machine,refractory,policy}.py` | IMPLEMENTED | yes |
| `timing/` — `TimingRecord` collection, per-session logs, decomposition | `src/spacedrums/timing/{records,logger,decomposition}.py`; `contracts.records.TimingRecord`; `Anticipator`/`CommitPolicy` Protocols | IMPLEMENTED | yes |
| `app/` — playable prototype with A/B switch and record mode; basic replay source | `src/spacedrums/app/{main,pipeline,audio_out,recorder,session_summary,synthetic}.py`; `src/spacedrums/capture/replay.py` | IMPLEMENTED (live run with a person: PENDING) | yes |
| `scripts/playability_session.py`, `scripts/induced_loss_test.py` | `scripts/` (+ `timing_summary.py`, `shadow_compare.py`, `rule_baseline_sensitivity.py`, `render_session_frames.py`, `_p05.py`) | IMPLEMENTED; live modes PENDING | yes |
| Playability report | `docs/reports/phase-05-playability.md` | IMPLEMENTED (structure, synthetic + dev-capture evidence); per-hit-type counts, safety log, `L_sys_est` **PENDING** | yes |
| Frozen candidate thresholds | `configs/prototype.candidate.yaml` (schema 1.3, ADR-0018) | IMPLEMENTED; **candidate, not tuned** | yes |
| `data/dev-sessions/` (developer only) | `data/dev-sessions/dev-p05-swing-L2-exp-{5,6,7}` — replays of the existing Phase 02 captures, git-ignored | DEV CAPTURE replays; no new recording | yes |
| Gate record | `docs/gates/phase-05-gate.md` | IMPLEMENTED; reviewer decision PENDING | yes |
| Decision record | `docs/decisions/ADR-0018-rule-baseline-commit-policy.md` | Proposed | yes |

## 2. Acceptance criteria

| # | Criterion (verbatim from phase document) | Evidence (file / test id / run id) | Status |
|---|---|---|---|
| 1 | Baseline A and Baseline B run under the shared commit policy; runtime switch and shadow logging work. | `tests/app/test_app_pipeline.py` (`test_hit_types_reactive_arm_matches_synthetic_truth`, `test_rule_arm_anticipates_on_synthetic_strikes`, `test_shadow_commits_never_reach_audio`, `test_runtime_arm_switch`); dev-capture runs (§4) with A active + B shadow | **MET** (VERIFIED on SYNTHETIC input and on replayed DEV CAPTURES; live run with a person PENDING) |
| 2 | All commit-policy and safety tests pass; zero commits during `INVALID` in the induced-loss test. | `tests/commit/` (27 tests incl. the TEST-CONFORM-5 property test), `tests/commit/test_causal_commit.py`; induced-loss: `tests/app/test_app_pipeline.py::test_induced_tracking_loss_zero_commits_while_not_valid` and run `20260921-1918-p05-induced-loss-synthetic` (24/24 cases, 0 commits on non-VALID frames); dev-capture sessions: 0 commits on non-VALID frames | **MET for the tests and the SYNTHETIC induced-loss test; the live induced-loss test (real occlusions) is PENDING** (C-05-2) |
| 3 | Playable with ordinary sticks on the MVP layout: single, alternating, repeated, rapid, and near-simultaneous hits each demonstrated and logged in the playability report with counts. | Protocol implemented (`scripts/playability_session.py --live`); SYNTHETIC self-test run `20260921-1917-p05-playability-synthetic` exercises every hit type through the pipeline | **NOT MET** — no person, no sticks, no live session (C-05-1) |
| 4 | Record mode persists raw video + all records + config snapshot; replay reproduces the committed-strike list. | `tests/app/test_app_recorder_summary.py` (every stream schema-valid with headers; replay reproduces the committed-strike list bit-for-bit); `ReplayFrameSource` (`tests/capture/test_replay_source.py`) | **MET** (VERIFIED on SYNTHETIC sessions and on the replayed dev captures; PNG-sequence "video") |
| 5 | `TimingRecord` populated; software-stamped `L_sys` decomposition reported with its term list. | `TimingRecord` populated on every path (VERIFIED); decomposition implemented with its term list (`spacedrums.timing.decomposition`, `scripts/timing_summary.py`, runs `20260921-1919-p05-timing-summary-synthetic`, `20260921-1924-p05-timing-summary`); **no `L_sys_est` value**: needs a live session and the MEASURED audio output latency (Phase 04 criterion 6 PENDING) | **PARTIAL** — instrumentation MET; the decomposition *report* is PENDING (C-05-3, depends on Phase 04) |
| 6 | Candidate prototype config frozen and labelled as candidate. | `configs/prototype.candidate.yaml` (`meta.status: candidate`, every value commented as candidate/provisional; `config_hash sha256:fd7d0926…`) | **MET as a labelled candidate file; the developer tuning session (Task 05.6) that was to inform it is PENDING** (C-05-4) |

## 3. Tests

All commands ran on HW-01, 2026-09-21, `.venv` Python 3.11.9, dirty tree on `36f2d4e…`.

| Test id / command | What it checks | Result |
|---|---|---|
| `.venv\Scripts\python.exe -m pytest tests/prediction tests/commit tests/app tests/timing tests/capture/test_replay_source.py tests/scripts/test_phase05_scripts.py -q` | Phase 05 focused suite (TEST-PRED-1…3, TEST-CONFORM-3/5, TEST-COMMIT-1/2, TEST-CAUSAL-1/2 anticipator + commit policy, TEST-APP-1…10, TEST-TIMING-2, TEST-CONFORM-7 replay, TEST-SCRIPTS-2) | PASS — 87 passed in 50.9 s |
| `.venv\Scripts\python.exe -m pytest -q` (`-o addopts="" -q --strict-markers`) | Project-wide regression suite | PASS — **485 passed, 1 skipped** in 144 s (skip = opt-in webcam hardware test) |
| `.venv\Scripts\ruff.exe check .` | Lint | PASS — All checks passed |
| `.venv\Scripts\lint-imports.exe --config .importlinter` | Layer contract + the two new forbidden-import contracts | PASS — 68 files, 163 dependencies, 6 contracts kept, 0 broken |
| `.venv\Scripts\python.exe scripts\validate_contracts.py` | JSON schemas (incl. config schema 1.3) | PASS — `RESULT: PASS` |
| `.venv\Scripts\python.exe scripts\env_smoke.py` | Environment + experiment-log schema | PASS — `RESULT: PASS` |
| `.venv\Scripts\python.exe scripts\fetch_hand_landmarker_model.py --verify` | Model asset hash | PASS — `sha256:fbc2a300…07cde1`, 7,819,105 bytes |
| `.venv\Scripts\python.exe scripts\fetch_drum_samples.py --verify` | Seven sample hashes | PASS — 7/7 OK |
| `git add -N . && git diff --check` (then `git reset`) | Whitespace / CRLF in tracked and untracked changes | PASS — exit 0 |
| `tests/prediction/test_causal_anticipator.py`, `tests/commit/test_causal_commit.py` | TEST-CAUSAL-1/2 (see §4 lines) | PASS |
| `tests/app/test_app_pipeline.py::test_deterministic_replay_reproduces_every_decision`, `tests/app/test_app_recorder_summary.py` | Deterministic replay | PASS |

Known test-layout note: the `from conftest import …` pattern of `tests/tracking` (Phase 03) makes some *explicit multi-directory* invocations order-fragile (e.g. `pytest tests/tracking/test_filters.py tests/contracts/test_config_schema.py` fails at HEAD too); the canonical `pytest` run and per-directory runs pass. Phase 05 keeps its helpers in uniquely named modules (`app_helpers.py`, `commit_helpers.py`, `synthetic_histories.py`).

Line endings: three tracked files that are CRLF in HEAD (`configs/schema/config.schema.json`, `src/spacedrums/config/loader.py`, `tests/contracts/test_config_schema.py`) received LF-only additions, as in the Phase 04 gate, so `git diff --check` stays clean and the diffs are minimal (3 / 13 / 16 lines).

## 4. Measurements produced in this phase

Every run is a dirty-tree run (`git_dirty: true`); none is promotable to VALIDATED (I-11).

| Quantity | Label | Value | run_id / test | Method | Hardware id |
|---|---|---|---|---|---|
| TEST-CAUSAL-1 rule-based anticipator (CV, CA) | VERIFIED on SYNTHETIC | PASS, 0 differing tuples (\|I\| = 11 / 12; GARBAGE, REMOVED, SHIFTED) | `tests/prediction/test_causal_anticipator.py` | causality-tests.md §2 | HW-01 |
| TEST-CAUSAL-2 rule-based anticipator | VERIFIED on SYNTHETIC | PASS; N = 3, N_min = 2, \|I\| = 23; negative control differs 23/23 | idem | §3 | HW-01 |
| TEST-CAUSAL-1 / -2 commit policy | VERIFIED on SYNTHETIC | PASS (\|I\| = 57; 38 commits) / PASS (N_eff = 7 frames, \|I\| = 73; negative control differs 2/73) | `tests/commit/test_causal_commit.py` | §2–3 | HW-01 |
| Predicted-crossing error vs analytic parabola | SYNTHETIC | CA −3.6e-4 s, CV +1.06e-2 s (dt_step 1/30 s, linear sub-step interpolation) | `tests/prediction/test_rule_based.py` | analytic | HW-01 |
| Commits on non-VALID frames (synthetic induced loss, 24 cases) | SYNTHETIC | **0**; all cases OK | `20260921-1918-p05-induced-loss-synthetic` | occlusion injection | HW-01 |
| Hit-type table (synthetic scenarios, A + B shadow) | SYNTHETIC | report §5.1 | `20260921-1917-p05-playability-synthetic` | analytic truth matching, W = 0.10 s | HW-01 |
| Rule-arm sensitivity grid (16 configs) | SYNTHETIC | report §5.4 | `20260921-1920-p05-rule-sensitivity-synthetic` | synthetic sweep | HW-01 |
| Dev-capture pipeline runs (3 captures; A active, B shadow) | DEV CAPTURE (replay of existing captures) | exp-5: 2 A commits (1 visibly plausible, 1 spurious from a mis-estimated tip), 0 B commits, 0 non-VALID commits; exp-6/7: 0 commits | `data/dev-sessions/dev-p05-swing-L2-exp-*`, `20260921-1924-p05-timing-summary`, `20260921-1924-p05-shadow-compare` | `app.main --source devcapture --record` | HW-01 |
| Per-frame processing (perception + decision, PNG decode excluded) | MEASURED development only (software-stamped) | exp-5 p50 31.2 / p95 47.4 ms; exp-6 36.9 / 46.0; exp-7 25.5 / 37.3 | dev-session summaries | wall-clock deltas | HW-01 |
| Per-hit-type counts (live), max hit rate, induced-loss log (live), `L_sys_est` decomposition, tuning log | **PENDING** | none | — | need a person / Phase 04 audio latency | HW-01 |

## 5. Integrity checklist

| # | Item | Result | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled | YES | report §5 and this record label SYNTHETIC / DEV CAPTURE / software-stamped / PENDING per row; config values commented as candidate |
| I-2 | No implementation claim without tests | YES | §3: 485 passed; every Phase 05 module has tests |
| I-3 | No causal component consumes future frames | YES | TEST-CAUSAL-1/2 on the anticipator and the commit policy (§4); no look-ahead argument in any interface |
| I-4 | No fabricated data | YES | no recording made; synthetic sequences carry `synthetic` in ids, file names and labels; the spurious dev-capture commit is reported as such |
| I-5 | FPS reported as native only | N/A | no FPS figure is claimed (per-frame processing time is labelled development-only) |
| I-6 | No "latency reduced" claim | YES | `L_pred` sign convention stated; synthetic lead times explicitly non-transferable; `L_sys_est` PENDING; report §9 |
| I-7 | Marker condition labelled | N/A | `GEOM` only |
| I-8 | Participant-level split | N/A | no ML, no dataset |
| I-9 | Scope respected | YES | no learned model, no participant recording, no calibration wizard, no cancellation of commits, no Phase 06 work; `OOS-REF` unchanged |
| I-10 | Status vocabulary | YES | phase document `## Status` = IMPLEMENTED with PENDING measurements; RTM rows keep PLANNED with evidence pointers until signature |
| I-11 | Reproducibility fields complete | **NO** | every cited run has `git_dirty: true` (owner prohibited a commit); clean-tree reruns are condition C-05-5 |
| I-12 | Limitations stated | YES | report §9 |

## 6. Deviations from the phase document

| What | Why | Impact on dependents |
|---|---|---|
| Phase 05 started while the Phase 04 gate proposes FAIL | Owner instruction | The audio-output term of every timing quantity stays PENDING; `t_audio_out_est` withheld (ADR-0018 §7) |
| Tasks 05.6–05.10 delivered as machinery + SYNTHETIC self-tests + dev-capture replays, not as developer measurements | No person at the camera; no new recording permitted | Criteria 3/5 not met as measurements; conditions C-05-1…C-05-4 |
| Config schema minor bump 1.2 → 1.3 (optional `geometry.v_min`) | `v_min` was a constructor argument only; Task 05.6 must freeze it in config | Additive; older documents valid; ADR-0018 |
| `CommitPolicy.step` gains a keyword-only `dropped_since_last` argument | Frame-drop guard needs the current frame's drop count; no look-ahead | Additive to the Phase 01 signature; documented in the Protocol docstring and ADR-0018 §3 |
| Record mode writes a lossless PNG sequence rather than a video container | Exact regeneration; matches the Phase 02/03 dev-capture format the replay source already reads; Phase 06 decides the codec | None for Phase 05; Phase 06 may switch containers |
| `intensity_proxy` for the rule arm is Phase 04's crossing-speed magnitude (not "speed along the inward normal") | Keep one definition across arms | Phase 07/11 define the proxy on data |
| `session.json` is a Phase 05 developer-provenance file, not the Phase 06 `SessionMetadata` | Phase 06 owns that schema | None |
| `ReplayFrameSource` added to `spacedrums.capture` now (the Phase 03 helper announced a Phase 09/13 promotion) | Task 05.5 requires a basic replay source | The script helper stays for the Phase 03 scripts |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase / owner |
|---|---|---|
| CV vs CA as the default rule arm | To Be Experimentally Determined | Phase 09 (both implemented; synthetic TE favours CA, commit frame identical) |
| `τ_commit`, `p_commit`, `n_confirm`, `r_zone`, `r_hand`, `v_min`, `K`, `dt_step`, `v_min_predict`, `a_max`, speed-gate bounds | To Be Experimentally Determined | Phases 09/18 on participant data; Phase 05 tuning session PENDING (C-05-4) |
| `Δ_proc` for replayed commit decisions (Phase 05 uses `t_frame_available + 0.0`) | Pending Architecture Decision | Phase 09 (define), 13 (validate) |
| Whether `DEGRADED` commits are ever allowed | To Be Experimentally Determined | Phase 17 |
| 7th V1 zone before/after data collection | Open Question | Owner before the Phase 06 freeze |
| Tip-estimation errors after acquisition (spurious commit on exp-5 frame 8) | PENDING (Phase 03 C-03-1 annotated benchmark) | Phase 03 condition; affects the reactive reference |
| Audio output latency / buffer choice | PENDING (Phase 04 criterion 6) | Phase 04 rerun; blocks `L_sys_est` |

## 8. Conditions (proposed PASS-WITH-CONDITIONS)

| Condition | Owner | Must be closed by |
|---|---|---|
| **C-05-1** Run `scripts/playability_session.py --live` with two ordinary sticks on the MVP layout; review the recording (`scripts/render_session_frames.py`), fill the per-hit-type counts (committed / missed / extra) and the maximum separable hit rate in report §5.1. Person-dependent. | Project owner (session) + submitter (tables) | before Phase 06 records any participant |
| **C-05-2** Run `scripts/induced_loss_test.py --live` (cover the camera / occlude a hand for ~100–300 ms and longer, during and outside swings); the script's non-VALID commit count must be 0; paste the trace into report §5.2. | Project owner + submitter | with C-05-1 |
| **C-05-3** After Phase 04 criterion 6 is closed (accepted post-DAC output latency with run id), run a live session with `--audio-output-latency-s <value> --audio-latency-run-id <run>` and `scripts/timing_summary.py --session-dir …`; fill the `L_sys_est` table (§5.3) with its term list. | Submitter | before Phase 09 cites any timing figure |
| **C-05-4** Developer tuning session (Task 05.6): try configurations for playability, log each (config, qualitative outcome) pair in report §6, freeze the Phase 06 candidate config (`configs/prototype.candidate.yaml` or a successor). | Project owner + submitter | before the Phase 06 freeze |
| **C-05-5** Clean-tree reruns of the cited runs (`p05-playability-synthetic`, `p05-induced-loss-synthetic`, `p05-rule-sensitivity-synthetic`, `p05-timing-summary`, `p05-shadow-compare`) after the owner commits the Phase 05 tree; update run ids in the report. | Submitter | at signature |

## 9. Reviewer statement

Submitter evidence assembly is complete. The project owner has not yet reviewed or signed this record, and the submitter does not claim authority to pass it. What was inspected/run by the submitter: the full test suite and every validation command in §3; the five SYNTHETIC/dev-capture runs in §4; the exp-5 commit frames rendered from the git-ignored dev session (one plausible entry, one spurious commit from a mis-estimated tip; the renderings contain the developer's image and are not kept in the repository — regenerable with `scripts/render_session_frames.py`; `docs/figures/phase-05/` holds only a SYNTHETIC illustration of the overlay). What was **not** done: any session with a person and sticks, any audible check, any measurement of playability, lead time or latency on real strokes. The honest proposed verdict is **PASS-WITH-CONDITIONS if the owner accepts that criteria 3 and 5 are closed by C-05-1…C-05-4 before Phase 06 recording; otherwise FAIL** (criterion 3 is a measurement the phase document requires and it does not exist). No Phase 06 work was started.

Signed: **PENDING — project owner**, 2026-09-21
