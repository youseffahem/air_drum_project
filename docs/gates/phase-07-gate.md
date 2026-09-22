# Phase 07 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 07 — Dataset Creation & Labelling |
| Phase document | `phases/phase-07-dataset-labeling.md` |
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-22 |
| Reviewer(s) | Project owner — review pending |
| Review date | 2026-09-22 (submission) |
| Code state | **Working tree is DIRTY**: the entire Phase 07 tree is uncommitted. `HEAD` at the time of the final verification: **`f29588a6aad8b40d045507888ee7289bbaac2e2f`** (`[P06] Close C-06-6 clean-tree verification`). 51 paths changed/added (§9). No commit, tag, push or amend was performed by the submitter. Every run cited below was taken on this dirty tree and is therefore **development evidence, not citable as MEASURED on a clean tree** (`docs/reproducibility-policy.md` §4) — condition **C-07-7** carries the clean-tree reruns, exactly as C-06-6 did for Phase 06. |
| **Verdict** | **PROPOSED PASS-WITH-CONDITIONS — owner verdict pending.** All ten tasks (07.1–07.10) are IMPLEMENTED with tests (876 passed / 1 skipped project-wide; **344 new**), exercised end to end on a SYNTHETIC full-protocol session and on the existing DEV CAPTURE, and documented. **No participant recording exists** (Phase 06 C-06-1…C-06-4 are open), therefore: no review pass, no inter-annotator agreement, no acoustic validation against a physical reference, no frozen split, and no `ds-v1.0`. Acceptance criteria **1 and 2 are MET**; **3 is PENDING / NOT VALIDATED**; **4, 5, 6 and 7 are PARTIAL**. Whether that is a pass is the owner's call: the honest reading is the same as Phase 06's — **the machinery is complete and verified on non-participant input; the labelled dataset does not exist and cannot exist until people are recorded.** The *Definition of Done* ("gate record PASS; label validator clean") is satisfied for the validator and not for the dataset. The submitter proposes conditions C-07-1…C-07-7 and does **not** claim the phase is Done. |

**Dependency note.** Phase 06 proposes PASS-WITH-CONDITIONS with C-06-1…C-06-5 open (pilot, thresholds, pad+mic, campaign, owner decisions); Phase 05 proposes PASS-WITH-CONDITIONS with C-05-1…C-05-4 open; Phase 04 proposes FAIL (audio-output latency). **None of those conditions is reinterpreted here.** Phase 07 was executed on the owner's instruction, on the understanding that its inputs (`ds-raw-v1.0`, accepted participant sessions) do not exist. No Phase 06 condition is closed by this phase, and no Phase 08 work was started.

---

## 1. Artefacts produced

| Artefact (from the phase document) | Path | Status label | Present? |
|---|---|---|---|
| Labelling Rules document | `docs/dataset/labeling-rules-v1.0.md` (v1.0) + executable form `src/spacedrums/data/labels/rules.py` | IMPLEMENTED; **thresholds are candidates**, refinement after a real review pass PENDING (C-07-2) | yes |
| Offline label generator (re-track → non-causal smooth → geometry → candidate events) | `src/spacedrums/data/labels/{generate,smooth,rules,interp,schema}.py`, `scripts/build_labels.py` | IMPLEMENTED; deterministic (hash check) | yes |
| QC/review tool and review log | `tools/review_labels.py` (frame scrub + overlays + accept/reject/adjust/defer/note), `src/spacedrums/data/labels/review.py`, `schemas/label-review.schema.json`, `labels/<session>/review.jsonl` | IMPLEMENTED; **no human review performed** (C-07-3) | yes (tool) / **no** (review log of a real pass) |
| Inter-annotator agreement on a subset | `docs/reports/phase-07-agreement.md` | **PENDING / NOT VALIDATED** — no annotator, no second annotator (Open Question), no participant labels | yes (report stating PENDING) |
| `LabelRecord` files per session | `schemas/label-record.schema.json` (1.0), `data/labels/<session>/labels.jsonl` + `labels.meta.json` (`schemas/label-set.schema.json`) | IMPLEMENTED; written for 1 SYNTHETIC + 1 DEV CAPTURE session | yes |
| `ReferenceTrack` / causal track per session | `schemas/reference-track.schema.json` (1.0), `tracks_reference.jsonl` and `tracks_causal.jsonl` | IMPLEMENTED; separation verified structurally | yes |
| `ds-v1.0` manifest | `schemas/dataset-manifest.schema.json`, `src/spacedrums/data/labels/dataset.py`, `scripts/build_dataset_manifest.py` | IMPLEMENTED (builder); **`ds-v1.0` refused/absent by construction** — only `ds-v0.0-selftest-dev` exists (git-ignored) | yes (builder) / **no** (`ds-v1.0`) |
| Dataset card | `docs/dataset/dataset-card-ds-v1.0.md` (**PENDING template**, banner-marked "THIS DATASET DOES NOT EXIST YET"), `docs/dataset/dataset-card-ds-v0.0-selftest-dev.md` (self-test) | IMPLEMENTED (generator); the participant card is a template with every count PENDING | yes |
| Split files `splits/ds-v1.0/{test_participants,cv_folds}.json` | `src/spacedrums/data/splits.py`, `schemas/split-file.schema.json`, `scripts/build_splits.py`; ADR-0021 | IMPLEMENTED (rule + builder + leakage checks); **`data/splits/ds-v1.0/` does not exist and is refused at P = 0** | yes (builder) / **no** (frozen split) |
| Pad+mic validation report | `docs/reports/phase-07-acoustic-validation.md`, `src/spacedrums/data/labels/acoustic.py`, `scripts/acoustic_onset.py` | **PENDING** with the reason recorded (no pad, no microphone, no person) | yes (report stating PENDING) |
| Label statistics report (MEASURED counts) | `docs/reports/phase-07-label-stats.md`, `src/spacedrums/data/labels/stats.py`, `scripts/label_stats.py` | IMPLEMENTED; counts MEASURED **from SYNTHETIC and DEV CAPTURE labels only**, reported as separate tables | yes |
| Interpolation comparison + ADR | `docs/reports/phase-07-interpolation.md`, `docs/decisions/ADR-0020-subframe-interpolation.md`, `scripts/subframe_interpolation.py` | IMPLEMENTED; decision **QUADRATIC**, evidence SYNTHETIC only, physical-reference confirmation PENDING (C-07-4) | yes |
| Reference-smoother evidence (Task 07.2) | `docs/reports/phase-07-reference-smoother.md`, `scripts/reference_smoother_check.py` | IMPLEMENTED; SYNTHETIC; manual-annotation error near impacts PENDING (C-07-1) | yes |
| Split-design ADR | `docs/decisions/ADR-0021-split-design.md` (rule `P07-SPLIT-1`) | Accepted as a rule; **no split frozen** | yes |
| Label validator | `src/spacedrums/data/labels/validate.py`, `scripts/validate_labels.py` (30 violation codes) | IMPLEMENTED; clean on both labelled sessions; every failure mode has an injected negative case | yes |
| Gate record | `docs/gates/phase-07-gate.md` | IMPLEMENTED; reviewer decision PENDING | yes |

**Not built, by the phase document's "What Must NOT Be Done Yet":** no feature statistics, no model training, no baseline performance, no dataset release. Phase 08 was not started.

## 2. Task-by-task status

| Task | What it required | Status | Evidence |
|---|---|---|---|
| **07.1** Labelling Rules v1.0 | Rules for positives, GT intensity proxy, six negative classes, ambiguous, excluded; non-causality statement; every rule unit-tested on synthetic trajectories | **IMPLEMENTED** (thresholds = candidates) | `docs/dataset/labeling-rules-v1.0.md`; `rules.py` (R1–R11, hashed); `TEST-LABEL-1` (32 tests) |
| **07.2** Offline re-tracking + reference smoother | Causal track stored; non-causal smoother (RTS / centred SavGol); gap bound → `NEG_TRACKING_LOSS`; **manual-annotation error near impacts (MEASURED, subset)** | **IMPLEMENTED**; manual-annotation error **PENDING** (person-dependent) | `smooth.py` (RTS over the Phase 03 Kalman model + centred SavGol); both track files per session; `TEST-LABEL-2` (23 tests); `docs/reports/phase-07-reference-smoother.md` (SYNTHETIC) |
| **07.3** Label generator | Phase 04 geometry on the reference trajectory + rules → `LabelRecord`s with full provenance; **re-running reproduces identical labels (hash check)** | **IMPLEMENTED** | `generate.py`; `--check-determinism` → IDENTICAL on both sessions (§3.2); `TEST-LABEL-4` (22 tests) |
| **07.4** Sub-frame interpolation comparison | Linear vs quadratic, bias and spread vs the best reference; decision rule recorded **before** looking at results; ADR | **PARTIAL** — comparison run and ADR written; evidence is SYNTHETIC, physical/manual reference PENDING | `interp.py`; `docs/reports/phase-07-interpolation.md`; ADR-0020; `TEST-LABEL-3` (17 tests) |
| **07.5** Review tool + QC protocol | Frame scrub with overlays, accept/reject/adjust (original retained), notes; QC sampling rates recorded; second annotator; κ and \|Δt\| | **IMPLEMENTED (tool + protocol)**; **review pass NOT PERFORMED** | `tools/review_labels.py`; `review.py`; QC protocol `P07-QC-1`; `TEST-LABEL-6` (25 tests); `docs/reports/phase-07-agreement.md` = PENDING |
| **07.6** Acoustic onset GT (pad+mic) | Onset detection → `t_impact_phys`, pairing, residual distribution, microphone-path latency bound | **PARTIAL** — machinery implemented and self-tested; **validation PENDING with the reason recorded** (the branch the phase document's evidence line permits) | `acoustic.py`; `scripts/acoustic_onset.py`; `TEST-LABEL-7` (10 tests); `docs/reports/phase-07-acoustic-validation.md` |
| **07.7** Label schema + validator | `LabelRecord` schema (reserved fields + `dataset_version`, `labels_version`, `review_status`, `reviewer_id`, `adjusted`); referential integrity, monotone times, one positive per episode, no positives in quarantined segments | **IMPLEMENTED** | `schemas/label-record.schema.json`; `validate.py` (30 codes); validator **CLEAN** on both sessions; `TEST-LABEL-5` (29 tests) + `tests/contracts/test_label_schemas.py` (62 tests) |
| **07.8** Participant-level splits | Frozen held-out test participants; participant-grouped K-fold; leakage checks; per-fold train-only normalisation rule; same files mandatory for 09–19 | **PARTIAL** — rule, builder, leakage checks and tests complete; **nothing frozen (P = 0)** | `splits.py`; ADR-0021; `schemas/split-file.schema.json`; `TEST-LABEL-8` (36 tests); `data/splits/ds-v1.0/` **does not exist** |
| **07.9** Label statistics report | Counts per class / zone / hand / segment / participant; `intensity_proxy_gt` distribution; tracking validity around positives; ambiguous fraction; review adjustments; strata sizes | **IMPLEMENTED**; counts are SYNTHETIC + DEV CAPTURE, never participant | `stats.py`; `docs/reports/phase-07-label-stats.md`; `TEST-LABEL-9` (27 tests) |
| **07.10** Manifest, versioning, dataset card | `ds-v1.0` manifest with hashes; dataset card; versioning rule (machinery → new `labels_version`; sessions → new `ds` minor) | **PARTIAL** — builder, card generator, versioning rule and hash reproducibility complete; **`ds-v1.0` refused (empty)** | `dataset.py`; `schemas/dataset-manifest.schema.json`; `data/manifests/ds-v0.0-selftest-dev.json` (self-test, git-ignored); `docs/dataset/dataset-card-ds-v1.0.md` (PENDING template) |

## 3. Tests and verification

All commands ran on HW-01, 2026-09-22, `.venv` Python 3.11.9, **dirty tree on `f29588a6…`**.

### 3.1 Commands and results

| Command | What it checks | Result |
|---|---|---|
| `.venv\Scripts\python.exe -m pytest tests/labels tests/contracts tests/scripts/test_phase07_scripts.py -o addopts="" -q --strict-markers` | Phase 07 focused suite: `TEST-LABEL-1…10`, the six label schemas (`TEST-SCHEMA-1` extension), `TEST-SCRIPTS-4` | **PASS — 489 passed** in 55 s |
| `.venv\Scripts\python.exe -m pytest -o addopts="" --strict-markers -q` | Project-wide regression | **PASS — 876 passed, 1 skipped** in 287 s (skip = opt-in webcam hardware test; 532 at the Phase 06 gate, so **+344**) |
| `.venv\Scripts\ruff.exe check .` | Lint | **PASS — All checks passed** |
| `.venv\Scripts\lint-imports.exe --config .importlinter` | Layer contracts incl. the new `labels-are-offline` forbidden contract | **PASS — 7 kept, 0 broken** (6 at the Phase 06 gate) |
| `.venv\Scripts\python.exe scripts\validate_contracts.py` | Record + dataset + **label** schemas; non-causality and kind-gating conditionals | **PASS — `RESULT: PASS`, 465 checks** (204 at the Phase 01 gate) |
| `.venv\Scripts\python.exe scripts\validate_labels.py --selftest` | Validator on a clean SYNTHETIC set, then **13 injected failure modes** | **PASS** — clean set CLEAN; all 13 CAUGHT, 0 MISSED, 0 SKIPPED |
| `.venv\Scripts\python.exe scripts\build_labels.py --session … --check-determinism --validate` (×2 sessions) | Generation, determinism, track separation, validation | **PASS** — both sessions: determinism IDENTICAL, separation ok, validator CLEAN |
| `.venv\Scripts\python.exe scripts\build_splits.py --selftest` | Leakage checks, determinism, three refusals | **PASS** — `all_passed: true`, IDENTICAL, 3 REFUSED, 0 NOT REFUSED |
| `.venv\Scripts\python.exe scripts\build_dataset_manifest.py selftest` | Manifest hashing, file re-hash, determinism, kind gating, empty-participant refusal, card render | **PASS** |
| `.venv\Scripts\python.exe scripts\acoustic_onset.py --selftest` | Onset detector + pairing on a SYNTHETIC click track with an injected offset | **PASS** — 4/4 onsets, recovered offset = injected offset |
| `.venv\Scripts\python.exe tools\review_labels.py --selftest` | Review round-trip: queue, two scripted passes, correction history, append-only log, κ, disagreement | **PASS** |
| `.venv\Scripts\python.exe scripts\reference_smoother_check.py` | Smoother behaviour near impacts | **PASS** (the default smoother keeps every synthetic entry) |
| `.venv\Scripts\python.exe scripts\subframe_interpolation.py` | Linear vs quadratic under the pre-declared rule | **PASS** — decision QUADRATIC on both tables |
| `.venv\Scripts\python.exe scripts\env_smoke.py` | Environment + experiment-log schema | **PASS** |
| `.venv\Scripts\python.exe scripts\fetch_hand_landmarker_model.py --verify` | Model asset hash | **PASS** — `sha256:fbc2a300…07cde1`, 7,819,105 bytes |
| `.venv\Scripts\python.exe scripts\fetch_drum_samples.py --verify` | Seven sample hashes | **PASS** — 7/7 OK |
| `git add -N . && git diff --check` (then `git reset`) | Whitespace / CRLF in tracked and untracked changes | **PASS — exit 0** (all new files LF; no CRLF-in-HEAD file received a CRLF edit) |

### 3.2 Causality and leakage verification

| Check | How | Result |
|---|---|---|
| The reference trajectory really is non-causal | `TEST-LABEL-2`: perturbing measurement `i+2` changes the smoothed sample at `i`, and the influence reaches further back than one sample | **PASS** — this is the property that makes the reference a label source and forbids it as a model input |
| A label artefact cannot be opened as a record stream | `RecordStreamHeader.record_type` enum has no label value; `validate_contracts.py` rejects `record_type: LabelRecord` / `ReferenceTrack` | **PASS** |
| `causal: false` is a schema `const` on labels and reference tracks | `TEST-SCHEMA-1` extension; validator code `CAUSAL_FLAG` | **PASS** |
| No causal package imports the label machinery | `.importlinter` contract `labels-are-offline` (capture, hands, stick, tracking, geometry, prediction, commit, audio, app) **and** `TEST-LABEL-10` AST scan (adds `features`, `models`, `eval` — vacuous until Phase 08 creates them, by design) | **PASS** |
| No causal package reads `tracks_reference` / `labels.jsonl` | `TEST-LABEL-10` source scan | **PASS** |
| The label machinery does not import the decision pipeline | `TEST-LABEL-10` (no `spacedrums.{app,commit,prediction}` import) — a label must never be a by-product of the arm under evaluation | **PASS** |
| Ground truth is not copied from the runtime candidate | Validator code `RUNTIME_TIME_COPIED`; `TEST-LABEL-5` | **PASS** |
| No label describes an instant the recording does not contain | Validator codes `TIME_OUT_OF_SESSION` / `FUTURE_LEAKAGE`; `TEST-LABEL-5` | **PASS** |
| Participant / session leakage across splits | `TEST-LABEL-8` (participant disjointness, session integrity, no session in two folds, test not in any fold, every session assigned; injected-overlap detection) | **PASS** (on SYNTHETIC rosters; a frozen participant split is PENDING) |
| `TEST-CAUSAL-1/2` (tracker, anticipator, commit policy) | Unchanged from Phases 03/05, re-run in the full suite | **PASS** |

### 3.3 Sessions labelled

| Session | Kind | Labels | Classes | `set_hash` | Validator |
|---|---|---:|---|---|---|
| `synthetic-p07-labels` | **SYNTHETIC** (full 25-segment protocol, generated) | 65 | POSITIVE 32, NEG_NO_STRIKE_MOTION 11, NEG_UPWARD_CROSSING 7, NEG_STOP_BEFORE_IMPACT 4, NEG_BETWEEN_ZONES 4, NEG_FAKE_SWING 3, NEG_TRACKING_LOSS 3, AMBIGUOUS 1 | `sha256:63071ea9…` | CLEAN |
| `dev-p06-ingest-exp-5` | **DEV CAPTURE** (Phase 02 developer capture, one hand, poor tracking) | 21 | EXCLUDED 10, AMBIGUOUS 8, POSITIVE 1, NEG_TRACKING_LOSS 1, NEG_UPWARD_CROSSING 1 | `sha256:663e23ab…` | CLEAN |

The SYNTHETIC protocol session exercises **all nine label classes**. The DEV CAPTURE is dominated by `EXCLUDED` (its nine quarantined low-validity takes, Phase 06) and `AMBIGUOUS` (degraded reference tracking) — which is the correct behaviour on a one-hand capture with poor tracking, and is itself evidence that R6b and R11 fire on real frames.

## 4. Measurements produced in this phase

Every row states its evidence class. **No row is participant evidence.**

| Quantity | Evidence class | Value | Source |
|---|---|---|---|
| Reference-smoother entry survival near impacts, per candidate | **SYNTHETIC** | `rts-kalman-cv-v1 q=5` (the Phase 03 causal value): **17/24** at noise 0, 16/24 at noise 0.003, crossing bias ≈ **+11 ms**. `q=200`: **24/24**, bias **−0.66 ms**. `rts-kalman-ca-v1 q=200`: **0/24**. `savgol window 9`: **0/24**; `window 3`: 24/24 | `scripts/reference_smoother_check.py`, `docs/reports/phase-07-reference-smoother.md` |
| Sub-frame estimator error vs the analytic crossing (estimator isolated) | **SYNTHETIC** | LINEAR bias −0.734 ms, IQR 2.047 ms, max 3.821 ms · QUADRATIC bias 0.000 ms, IQR 1.067 ms, max 1.832 ms (n = 24) | `scripts/subframe_interpolation.py`, ADR-0020 |
| Label time vs the analytic crossing of the SYNTHETIC strokes | **SYNTHETIC** | every POSITIVE within one frame (33 ms) of the analytic crossing; on the unit-test session the two positives land 2.0 ms and 3.1 ms early | `TEST-LABEL-4::test_positive_labels_match_the_synthetic_analytic_crossings` |
| Label counts per class / zone / hand / segment type | **SYNTHETIC** (65) and **DEV CAPTURE** (21), reported as two tables, never summed | §3.3; `docs/reports/phase-07-label-stats.md` |
| Ambiguous fraction; excluded fraction | **SYNTHETIC** 0.0154 / 0.0000 · **DEV CAPTURE** 0.3810 / 0.4762 | `docs/reports/phase-07-label-stats.md` |
| Generator determinism | **UNIT / INTEGRATION TEST** | `labels.jsonl` byte-identical and `set_hash` identical on re-run, both sessions | `scripts/build_labels.py --check-determinism` |
| Manifest / split hash determinism | **UNIT TEST** | identical across runs; `generated_at` excluded from the hash | `TEST-LABEL-9`, `TEST-LABEL-8` |
| Acoustic detector offset recovery | **SYNTHETIC** | 4/4 onsets; recovered offset = **injected** offset (5 ms quantisation of a 6 ms injection) | `scripts/acoustic_onset.py --selftest` |
| Acoustic pairing on the SYNTHETIC click track | **SYNTHETIC** | 3 pad positives, 1 paired, residual 48.3 ms — **a property of the click generator, not a physical offset** | `docs/reports/phase-07-acoustic-validation.md` §3.2 |
| Cohen's κ, \|Δt\|, review coverage, adjustment rate on real annotations | **PENDING / NOT VALIDATED** | none | needs a review pass on participant labels |
| `t_impact_phys − t_impact_est` on a real pad + microphone | **PENDING / NOT VALIDATED** | none | needs C-06-3 |
| Reference-trajectory error near impacts vs **manual** annotation | **PENDING / NOT VALIDATED** | none | person-dependent |
| Participant count `P`, frozen `n_test` / `K`, per-participant label counts | **PENDING / NOT VALIDATED** | none | needs C-06-4 |

## 5. Acceptance criteria

| # | Criterion (verbatim) | Evidence | Status |
|---|---|---|---|
| 1 | Labelling rules v1.0 documented, tested, and applied; label provenance stored. | `docs/dataset/labeling-rules-v1.0.md` (R1–R11, thresholds, QC protocol, non-causality statement); `TEST-LABEL-1` (every rule on synthetic evidence); applied to 2 sessions producing all nine classes (§3.3); every label carries the full `provenance` block incl. `labels_hash` (`TEST-LABEL-4`) | **MET** — with the evidence class stated: *applied to SYNTHETIC and DEV CAPTURE material*; application to participant recordings is PENDING and thresholds remain candidates (C-07-2) |
| 2 | Reference and causal tracks stored separately; leakage test in place. | Two files per session with distinct names and distinct schemas; `tracks_reference.jsonl` is provably **not** a record stream and `tracks_causal.jsonl` **is** one (`leakage_report`, `TEST-LABEL-4`); `causal: false` as a schema `const`; `RecordStreamHeader` cannot name a label artefact; `.importlinter` `labels-are-offline`; `TEST-LABEL-10` AST + text scan incl. the future `features/` and `models/` | **MET** |
| 3 | Review completed per QC protocol; agreement reported. | Tool, protocol `P07-QC-1`, queue, correction history, second-pass disagreement rule and κ/\|Δt\| all implemented and tested (`TEST-LABEL-6`, 25 tests). **No human has reviewed any label; no second annotator exists (Open Question unresolved).** | **PENDING / NOT VALIDATED** (C-07-3) |
| 4 | Acoustic validation reported (or PENDING with reason). | `docs/reports/phase-07-acoustic-validation.md` reports **PENDING** with the reason: no pad and no microphone are inventoried, no person recorded (C-06-3/C-06-4). Machinery implemented and self-tested on a SYNTHETIC click track. | **PARTIAL** — the criterion admits a PENDING branch and that branch is taken with a recorded reason; the submitter grades it PARTIAL rather than MET because the reason is *"Phase 06 never ran"*, not the pilot-informed drop the task anticipated (C-07-5) |
| 5 | Interpolation choice recorded (ADR). | ADR-0020: decision **QUADRATIC** for offline labels (live geometry unchanged), under a decision rule declared before the run; comparison table in `docs/reports/phase-07-interpolation.md` | **PARTIAL** — the ADR exists and the choice is recorded; the task's evidence line asks for a MEASURED comparison and the only available reference was a SYNTHETIC analytic crossing, so the ADR is marked *provisional* (C-07-4) |
| 6 | Participant-level splits frozen; leakage tests pass. | Leakage tests pass (`TEST-LABEL-8`, 36 tests); rule `P07-SPLIT-1` fixed in code before any participant exists (ADR-0021); builder refuses to freeze or to write an empty participant split. **No split is frozen: P = 0.** | **PARTIAL** — second half MET, first half NOT MET / PENDING (C-07-6) |
| 7 | `ds-v1.0` manifest, label statistics, and dataset card complete. | Manifest builder + schema + versioning rule + file re-hash (`TEST-LABEL-9`); statistics report generated with MEASURED counts (SYNTHETIC / DEV CAPTURE); dataset card generator, and `docs/dataset/dataset-card-ds-v1.0.md` rendered as an explicitly-banner-marked PENDING template. **`ds-v1.0` itself is refused by construction (no participant label set).** | **PARTIAL** (C-07-6) |

## 6. Evidence classification — separated, never combined

| Class | What is in it | Where |
|---|---|---|
| **PARTICIPANT** | **Nothing. No participant recording, label, count, agreement or split exists.** | — |
| **PILOT** | **Nothing.** | — |
| **DEV CAPTURE** | 21 labels from `dev-p06-ingest-exp-5` (a Phase 02 developer capture of the developer's own hand, replayed): class counts, ambiguous/excluded fractions, validator-clean result, determinism | §3.3, `docs/reports/phase-07-label-stats.md` (its own table) |
| **SYNTHETIC** | 65 labels from the generated full-protocol session; the smoother comparison; the interpolation comparison; the acoustic click-track pairing; the split self-test roster; the review self-test | §4, the four reports, the script self-tests |
| **UNIT / PROPERTY TEST** | 344 new tests: rules, smoother, interpolation, generator, validator (13 injected failure modes), review, acoustic, statistics, splits, leakage, schemas, scripts | §3.1 |
| **STATIC / CONTRACT CHECK** | 465 contract-validator checks; ruff; 7 import-linter contracts incl. `labels-are-offline`; the `TEST-LABEL-10` source scans; `git diff --check` | §3.1, §3.2 |

The code enforces this separation rather than relying on the report: `schema.evidence_label` **raises** on a mixed set of source kinds, `stats.aggregate` groups by `source_kind` and produces no cross-kind total, `roster_from_label_sets` refuses a mixed roster, and a `ds` manifest that spans kinds (only possible for a self-test version) labels its totals *"INVENTORY across N source kinds … a file count, NOT one evidence class"* with a `by_source_kind` breakdown.

## 7. Integrity checklist

| # | Item | Result | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled | YES | every number in this record, the four reports, the two ADRs and the two cards carries SYNTHETIC / DEV CAPTURE / candidate / TEST / PENDING |
| I-2 | No implementation claim without tests | YES | §3.1; every Phase 07 module, script and tool has tests (344 new) |
| I-3 | No causal component consumes future frames | YES | §3.2; no causal component was touched; the one non-causal component is schema-, linter- and test-fenced |
| I-4 | No fabricated data | YES | no recording made; no participant label, count, κ or split exists; SYNTHETIC sessions carry `session_kind = SYNTHETIC` / `participant_id = SYNTHETIC`; schemas refuse a participant `dataset_version` or `t_impact_phys` on SYNTHETIC / DEV CAPTURE material; split pseudonyms are `SYNTHETIC-P**` and cannot be frozen |
| I-5 | FPS reported as native only | N/A | no FPS measured in this phase |
| I-6 | No "latency reduced" claim | YES | none. ADR-0020 explicitly declines to change the live estimator |
| I-7 | Marker condition labelled | N/A / YES | both labelled sessions are `MARKERLESS`; `tip_method` travels in the causal track |
| I-8 | Participant-level split | YES (as a rule) | ADR-0021; leakage tests; **no split frozen**, stated everywhere |
| I-9 | Scope respected | YES | no features, no training, no baseline performance, no release; Phase 08 not started; `OOS-REF` unchanged |
| I-10 | Status vocabulary | YES | phase document `## Status` = IMPLEMENTED (machinery) / PENDING (participant-dependent evidence) |
| I-11 | Reproducibility fields complete | **NO — dirty tree** | every cited run was taken on the uncommitted Phase 07 tree at `HEAD = f29588a6…`. Artefacts carry the real `git_sha`/`git_dirty`; none may be cited as clean-tree MEASURED until **C-07-7** |
| I-12 | Limitations stated | YES | dataset card §9; agreement report §1; acoustic report §1/§4; ADR-0020 *provisional*; ADR-0021 small-`P` caveat; rules document §5 |

## 8. Deviations from the phase document

| What | Why | Impact on dependents |
|---|---|---|
| Tasks 07.5 (review pass), 07.6 (validation) and 07.8 (freeze) not *performed* | No participant recording exists; no annotator; no pad or microphone | Criteria 3, 4, 6, 7 open; conditions C-07-3…C-07-6 |
| The reference smoother uses a **different process noise** from the Phase 03 tracker (`q = 200` vs `q = 5`) | Measured (SYNTHETIC): the tracker's `q` over-smooths the reversal at impact and loses the surface entry on 7 of 24 strokes, silently turning positives into stop-shorts | The reference is *not* "the tracker run backwards"; `smoother_id` + params are in every label's provenance. Re-tuning is a `labels_version` bump |
| Two scripts beyond the phase document's list: `subframe_interpolation.py` (07.4) and `reference_smoother_check.py` (07.2) | Those two tasks need an evidence-producing entry point and the listed scripts do not cover them | Additive; both are `--synthetic`-only and tested |
| `EXCLUDED` overrides the observed class; the pre-exclusion class is kept in `notes` | The phase document lists EXCLUDED as a *class*, but the observed classification is still useful | Statistics count EXCLUDED separately; `metric_eligible` excludes it |
| `NEG_UPWARD_CROSSING` excludes the recovery stroke of an already-labelled entry | Labelling every exit would emit one negative per strike and flood the dataset | Documented in rules R5 and tested |
| `labels_hash` covers zone layout and `v_min` as well as rules/thresholds/smoother/tracker | Labels built on different layouts are not comparable within one dataset | A layout change needs a new `labels_version`; the manifest refuses to mix (demonstrated live during this phase) |
| `tracker_hash` identifies the tracker only, not the session's recording commit | A session recorded on a different commit with the identical tracker must still be admissible | Recording commit stays in `SessionMetadata` and the raw manifest |
| `pyproject.toml` adds `tests/data` to `pythonpath` | The label tests reuse the Phase 06 SYNTHETIC session builder instead of duplicating it | Test-only |
| `.gitignore`: split files **tracked**, self-test manifests and splits ignored | Phases 09–19 must use the same folds, so frozen splits belong in the repository | Additive |

## 9. Files added / modified

**Added (36).**
`schemas/{label-record,reference-track,label-set,label-review,split-file,dataset-manifest}.schema.json`;
`schemas/examples/{label-record,reference-track,label-set,label-review,split-file,dataset-manifest}.valid.example.json`;
`src/spacedrums/data/labels/{__init__,schema,rules,smooth,interp,generate,validate,review,acoustic,stats,dataset}.py`;
`src/spacedrums/data/splits.py`;
`scripts/{_p07,_p07_examples,build_labels,validate_labels,label_stats,build_splits,build_dataset_manifest,acoustic_onset,subframe_interpolation,reference_smoother_check}.py`;
`tools/review_labels.py`;
`tests/labels/{conftest,label_helpers,test_label_rules,test_reference_smoother,test_subframe_interp,test_label_generator,test_label_validator,test_label_review,test_label_acoustic,test_dataset_splits,test_label_stats_manifest,test_label_leakage}.py`;
`tests/contracts/test_label_schemas.py`; `tests/scripts/test_phase07_scripts.py`;
`docs/dataset/{labeling-rules-v1.0,dataset-card-ds-v1.0,dataset-card-ds-v0.0-selftest-dev}.md`;
`docs/decisions/{ADR-0020-subframe-interpolation,ADR-0021-split-design}.md`;
`docs/reports/phase-07-{label-stats,agreement,acoustic-validation,interpolation,reference-smoother}.md`;
`docs/gates/phase-07-gate.md`.

**Modified (15).**
`.gitignore` (tracked split files; ignored self-test manifests/splits) · `.importlinter` (`labels-are-offline`) · `pyproject.toml` (`pythonpath`) · `scripts/validate_contracts.py` (label schemas + non-causality/kind-gating checks) · `scripts/README.md` · `src/spacedrums/data/__init__.py` · `tests/contracts/conftest.py` (`LABEL_SCHEMAS`) · `tests/README.md` · `docs/architecture/contracts.md` (§6 `LabelRecord`/`ReferenceTrack` now DEFINED) · `docs/architecture/causality-tests.md` (§1.1 Phase 07 status) · `docs/decisions/README.md` (ADR-0020/0021) · `docs/repo-layout.md` (Phase 07 amendment) · `docs/requirements/rtm.md` (REQ-014/038/048/049) · `data/manifests/README.md` · `phases/phase-07-dataset-labeling.md` (Status).

**Git-ignored artefacts produced** (not part of the commit): `data/raw/SYNTHETIC/synthetic-p07-labels/` (generated session), `data/labels/{synthetic-p07-labels,dev-p06-ingest-exp-5}/`, `data/manifests/ds-v0.0-selftest-dev.json`, `data/splits/ds-v0.0-selftest-dev/`, `experiments/20260922-16*-p06-record-synthetic/`.

## 10. Conditions (proposed PASS-WITH-CONDITIONS)

| Condition | Owner | Must be closed by |
|---|---|---|
| **C-07-1** Reference-smoother validation against **manual tip annotations near impacts** on a stratified subset of real recordings (`tools/annotate_tip.py`), per Task 07.2's evidence line; report the reference-trajectory error with the subset size; confirm or replace the `rts-kalman-cv-v1, q = 200` default. Person-dependent. | Project owner (annotation) + submitter (report) | before labels of a real dataset are frozen |
| **C-07-2** Refine the negative-rule thresholds (`rules.Thresholds`) after the first review pass on real recordings; record the new values and the resulting `labels_version` bump in `labeling-rules-v1.0.md` §5 and §9. | Submitter | with C-07-3 |
| **C-07-3** Perform the review pass under `P07-QC-1`: 100 % of positives and ambiguous, sampled negatives at the recorded rate; a **second annotator** on the stratified subset (or the documented self-re-review fallback, labelled `SELF_REREVIEW`); fill `docs/reports/phase-07-agreement.md` with κ and the \|Δt\| distribution. Resolves the Open Question *"Who is the second annotator?"*. | Project owner (annotators) + submitter (tooling, report) | before any Phase 09 result |
| **C-07-4** Re-run the interpolation comparison against a **physical** reference (`t_impact_phys`) and/or manual frame annotations; confirm or reverse ADR-0020 and lift its *provisional* status (a reversal is a `labels_version` bump). | Submitter | with C-07-5 |
| **C-07-5** Acoustic validation: after Phase 06 **C-06-3**, measure and record the microphone-path latency bound, run `scripts/acoustic_onset.py --all` over the campaign, and report bias, spread, fraction paired and the number of strikes covered — or record the drop with its evidence, leaving `t_impact_phys` null and the card's "geometric only" statement in force. | Project owner (equipment) + submitter (report) | before Phase 18 |
| **C-07-6** Build the real dataset after Phase 06 **C-06-4**: label every accepted participant session, run the validator clean, freeze `data/splits/ds-v1.0/{test_participants,cv_folds}.json` under `P07-SPLIT-1` with the actual `P`, write `data/manifests/ds-v1.0.json`, and regenerate `docs/dataset/dataset-card-ds-v1.0.md` and `docs/reports/phase-07-label-stats.md` with MEASURED participant counts. | Submitter (after the campaign) | before Phase 08 feature statistics |
| **C-07-7** Clean-tree reruns of every command in §3.1 after the owner commits the Phase 07 tree; update the code-state row and the run references here with the committed SHA and `git_dirty: false` (the Phase 07 analogue of C-06-6). | Submitter | at the owner's commit |

## 11. Explicit statements

1. **No participant recordings were created.** No person was at a camera during this phase. The only new recording-shaped artefact is a *generated* SYNTHETIC session (blank frames, generated observations) produced by `scripts/record_session.py --synthetic`.
2. **No participant data was fabricated.** There is no participant label, no participant count, no participant-derived statistic and no participant dataset anywhere in this phase. The schemas make fabrication structurally hard: a `SYNTHETIC` or `DEV_CAPTURE` artefact cannot carry a participant `dataset_version` or `t_impact_phys`, and a self-test roster cannot produce or freeze a participant split.
3. **No empirical participant annotation agreement was claimed.** No human reviewed any label. The κ printed by `tools/review_labels.py --selftest` is computed over **scripted machine decisions on generated labels** and is labelled as such in the tool output, in the agreement report and here.
4. **Synthetic and dev evidence was not presented as participant evidence.** Every table states its evidence class; the statistics group by `source_kind` and the library raises rather than sum across kinds; the DEV CAPTURE is labelled a developer recording of the developer's own hand, never a participant session.
5. **The 48 ms acoustic residual is not a physical measurement.** It is the offset between where the SYNTHETIC click generator placed its clicks and where the geometry placed the crossing, reported only to show the pairing path runs.
6. **The interpolation and smoother decisions rest on SYNTHETIC evidence.** They were taken under rules declared before the runs, and both are marked provisional/candidate pending a real reference.

## 12. Git

| Field | Value |
|---|---|
| **HEAD at final verification** | **`f29588a6aad8b40d045507888ee7289bbaac2e2f`** |
| **`git_dirty`** | **true** — 15 modified + 36 added paths (51 total, §9); none committed |
| Commit / tag / push / amend by the submitter | **none.** No `git commit`, `git tag`, `git push` or `git commit --amend` was executed. The working tree is left for the owner to inspect and commit. |
| `git diff --check` | exit 0 (no whitespace or line-ending problems in tracked or untracked changes) |
| Line endings | all new files LF; no CRLF-in-HEAD file received a CRLF edit |

## 13. Reviewer statement

Submitter evidence assembly is complete. The project owner has not reviewed or signed this record, and the submitter does not claim authority to pass it.

**What the submitter ran and inspected:** every command in §3.1; the generation, validation, statistics, manifest, split, acoustic, interpolation and smoother runs on the two labelled sessions; the 13 injected validator failure modes; the review round-trip; the generated schema examples against their schemas; both dataset cards; every report.

**What was NOT done:** any session with a person; any pilot; any participant; any microphone or pad; any human review of any label; any inter-annotator agreement; any frozen participant split; any `ds-v1.0`; any measurement of label quality, annotation agreement, class balance in a real dataset, or the offset between the geometric and physical impact. **There is no participant data, and there is no labelled dataset.**

**The honest proposed verdict** is **PASS-WITH-CONDITIONS for the labelling infrastructure (criteria 1 and 2 MET, 4–7 PARTIAL) with criterion 3 PENDING under C-07-1…C-07-7**, *if* the owner accepts a gate that passes machinery without the dataset — the same shape as the Phase 06 gate, and for the same reason. Otherwise the verdict is **FAIL**, because the *Definition of Done* names a completed dataset (`ds-v1.0`, frozen splits, agreement reported) that cannot exist without recording people.

No Phase 08 work was started.

Signed: **PENDING — project owner**, 2026-09-22
