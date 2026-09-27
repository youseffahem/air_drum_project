# Space Drums — Causality, Parity and Conformance Test Specifications

**Phase:** 01 — Tasks 01.6 (causality contract), 01.9 (parity), 01.5 (conformance) · **Status:** specifications are IMPLEMENTED as documents; the tests themselves are PLANNED and are executed by the phases named in each section. `TEST-SCHEMA-1` (contracts.md §5) ran first; Phase 03 executed `TEST-CAUSAL-1/2` for the tracker, Phase 05 for the rule-based `Anticipator` (`tests/prediction/test_causal_anticipator.py`) and the `CommitPolicy` (`tests/commit/test_causal_commit.py`, declared time-bounded `N_eff`; open episodes stated as a limitation) — results in `docs/gates/phase-05-gate.md` §4; the informal replay-determinism check of Task 05.5 is `tests/app/test_app_recorder_summary.py`.
**Cited by:** Phase 03 (tracker), 05 (rule-based anticipator, commit policy), 08 (features), 09 (simulator, GBDT), 10–12 (models), 13 (live replay + parity), 16–20 (re-runs after threading / integration changes); integrity checklist item I-3.

---

## 1. The causality contract

> Any component labelled *causal* consumes only observations with timestamp ≤ the current frame's `t_capture`. Offline *label generation* (Phase 07) may use the full recording and is therefore non-causal by design; this is documented and is the only place future information is permitted.  — `phases/README.md` §13

Structural guarantees already in the architecture: no interface has a look-ahead argument (`architecture.md` §11); the `Tracker.history` property exposes only states with `t_capture ≤` current; replay feeds frames in `frame_id` order; workers only see delivered frames (§7). The two tests below turn the guarantee from *asserted* into *verified*.

### 1.1 Non-causal artefacts — where they may exist (made explicit at the gate review, 2026-09-21)

> **Phase 07 status (2026-09-22):** the artefacts below now exist and the rules are enforced rather than asserted. `ReferenceTrack` is `schemas/reference-track.schema.json` with `causal: false` and `kind: ReferenceTrack` as schema `const`s, written only to `data/labels/<session>/tracks_reference.jsonl`; `LabelRecord` is `schemas/label-record.schema.json`, also `causal: false` by `const`. Enforcement: `RecordStreamHeader.record_type` has no value naming a label artefact (`TEST-SCHEMA-1`); the `.importlinter` contract **`labels-are-offline`** forbids `capture`, `hands`, `stick`, `tracking`, `geometry`, `prediction`, `commit`, `audio` and `app` from importing `spacedrums.data.labels` or `spacedrums.data.splits`; and `TEST-LABEL-10` (`tests/labels/test_label_leakage.py`) scans the source of every causal package — plus `features/`, `models/` and `eval/`, which pass vacuously until Phase 08 creates them — for imports of the label machinery and for reads of `tracks_reference`. `LabelRecord` additionally carries a `runtime_reference` block holding what the *causal* pipeline saw, banner-labelled *REAL-TIME AVAILABLE SIGNALS (not ground truth)*; the label validator raises `RUNTIME_TIME_COPIED` if a label's `t_impact_est` was taken from it.


Future-aware quantities exist in exactly one place: **Phase 07 label construction.** Concretely:

| Artefact | Causal? | Allowed home | Forbidden |
|---|---|---|---|
| `ReferenceTrack` — offline-smoothed / bidirectionally-filtered tip trajectory (`contracts.md` §6) | **no** | `labels/` of a dataset version, `causal: false` const | never written under `records/`; never as a `TrackState`, `KinematicFeatures` or `TrajectoryPrediction` stream; never passed to any `Tracker`, `Anticipator`, `DirectAnticipator`, feature, `Geometry` or `CommitPolicy` call; never a model input or training *feature* |
| `LabelRecord.t_impact_est` (offline, computed from the full recording) | **no** | `labels/` | never visible to any arm at evaluation time (README §13; Phase 18 rule); used only for matching and as training **targets** |
| Regenerated derived records (`producer = REGENERATED`) | **yes** | `records/` | produced only by running the causal pipeline through `ReplayFrameSource` |

Rules: (i) every runtime/online input to `Tracker`, features, `Anticipator`/`DirectAnticipator`, `Geometry` and `CommitPolicy` is a record produced causally from frames with `t_capture ≤` the current frame — `RecordStreamHeader.record_type` cannot name a label artefact (schema enum), so a label file cannot even be opened as a record stream; (ii) training may use non-causal labels as **targets** and causal records as **inputs** — Phase 08's reference-track exclusion test verifies that no feature is computed from a `ReferenceTrack`; (iii) at inference time, in the harness or live, the pipeline has no access to `labels/` (the harness loads labels only in the event-matching stage after all arms have run); (iv) `TEST-CAUSAL-1` on the harness itself (Phase 09) is what proves (iii).

**Components that must pass `TEST-CAUSAL-1` and `TEST-CAUSAL-2` before any result derived from them is reported:**

| Component | Interface | First executed in |
|---|---|---|
| Every `Tracker` implementation | `Tracker.update` | Phase 03 |
| Every `TipEstimator` (per-frame, trivially causal — `TEST-CAUSAL-1` only, as a regression guard) | `TipEstimator.estimate` | Phase 03 |
| Every feature implementation | `features` | Phase 08 |
| Every `Anticipator` (rule-based B; C-GBDT; C-GRU/TCN/MT/TT; every Phase 12/19 variant) | `Anticipator.predict` | 05, 09, 10, 11, 12, 19 |
| Every `DirectAnticipator` and the harness's direct-head adapter (diagnostic modes) | `DirectAnticipator.predict_direct` | 09 (GBDT direct), 19 (AB-NOTRAJ) |
| `CommitPolicy` | `CommitPolicy.step` | Phase 05 |
| The causal replay simulator itself | `eval` | Phase 09 |
| The live loop in replay-from-file mode (all arms) | `app` | Phase 13, re-run 16/17/20 |

---

## 2. `TEST-CAUSAL-1` — future-perturbation invariance

**Claim tested.** For a component `C` and a recorded sequence, the outputs of `C` up to and including frame `i` do not depend on any frame `> i`.

**Inputs.**
- A recorded session (raw video + `frames.jsonl`, `architecture.md` §12.2) or, for unit-level runs, a synthetic sequence of input records (Phase 03/05/08 synthetic tracks are acceptable and must be labelled synthetic).
- The component under test, instantiated from a config snapshot (`config_hash` recorded).
- A set of cut indices `I = {i_1, …, i_m}` — candidate: every 10th frame plus every frame at which a `StrikeCandidate` or reset occurred in the reference run (*candidate rule; Phase 09 freezes it*).
- A perturbation kind per run: `GARBAGE` (frames `> i` replaced by uniform-random pixels / random records with valid schema but random values), `REMOVED` (sequence truncated at `i`), `SHIFTED` (frames `> i` replaced by frames from a different session). All three are run.

**Procedure.**
1. **Reference run:** feed frames `0..n` through `C` causally; log every output record (`TrackState`, `KinematicFeatures`, `TrajectoryPrediction`, `StrikeCandidate`, `CommittedStrike` as applicable) keyed by `(frame_id, hand_id)`.
2. For each cut index `i ∈ I` and each perturbation kind: **reset `C`** (`reset(SESSION_START)`), build the perturbed sequence, feed it through `C`, log outputs.
3. Compare the perturbed log to the reference log **for all frames `≤ i`**.
4. Additionally (live-mode variant, Phase 13): assert that no `FrameSample` with `t_capture` greater than the frame currently being processed is ever visible to the component (instrumented `FrameSource`).

**Pass criteria.**
- For every `i`, every kind, every hand, every record type: the outputs for frames `≤ i` are **bit-identical** to the reference (JSON-serialised, canonical form) — for deterministic code paths (tracker, features, geometry, rule-based anticipator, commit policy, simulator).
- For learned models whose runtime is non-deterministic at floating-point level (multi-threaded inference): numeric fields agree within a **pre-declared tolerance** stated in the phase document before the run (candidate: absolute `1e-6` in ROI-normalized units on positions, `1e-6` s on times — *candidate values*, fixed in Phase 10); every non-numeric field (ids, status, zone, source, counts of records) is identical. Tolerance runs are reported with the tolerance and the maximum observed deviation.
- Any difference at a frame `≤ i` is a **failure**; the failing `(component, i, kind, frame, field)` tuples are listed in the test report.

**Evidence.** Test id `TEST-CAUSAL-1`, component id, `config_hash`, `git_sha`, session/synthetic id, `|I|`, kinds run, result, max deviation (if tolerance mode). Recorded in the phase's gate record.

---

## 3. `TEST-CAUSAL-2` — history-truncation monotonicity

**Claim tested.** The output of `C` at frame `i` depends only on frames within its **declared history window** `N` (config `tracking.history_n`, model `N`, feature window) — i.e. `C` has no hidden long memory beyond what it declares. (This is what makes `N` a meaningful ablation variable in Phase 19 and bounds the state that must be reset on `INVALID`.)

**Inputs.** As `TEST-CAUSAL-1`, plus the declared `N` of the component and a warm-up length `N_min` (declared by the component; the number of VALID frames it needs before producing an output).

**Procedure.**
1. **Reference run** as in `TEST-CAUSAL-1`.
2. For each cut index `i ∈ I` with `i ≥ N + N_min`: reset `C`; feed **only** frames `i − N + 1 .. i` (the window) — for stateful components this means starting cold at frame `i − N + 1`; log the output at frame `i`.
3. Compare the output at frame `i` with the reference output at frame `i`.
4. **Negative control** (must fail, proving the test can detect memory): repeat step 2 with window `N − 1` for a component whose output demonstrably depends on the full window (e.g. a finite-difference feature over `N` samples); the comparison must differ.

**Pass criteria.**
- Output at frame `i` from the truncated run equals the reference output (bit-identical / declared tolerance as in `TEST-CAUSAL-1`) for every `i` in `I`.
- If the component's declared `N` is "unbounded" (e.g. a stateful GRU), the component must declare an **effective** `N_eff` with the justification, and the test runs with `N_eff`; a difference greater than the tolerance means the declaration is wrong and the test fails. Models with unbounded memory that cannot declare `N_eff` cannot be ablated on history length and this is stated as a limitation.
- The negative control differs.

**Evidence.** Test id `TEST-CAUSAL-2`, `N` (or `N_eff`), `N_min`, `|I|`, result, negative-control result.

---

## 4. `TEST-PARITY-1` — offline/online parity (Task 01.9; executed in Phase 13)

**Claim tested.** The live application driven by a `ReplayFrameSource` produces the same decisions as the Phase 09 harness on the same recorded session, model and config — so results measured offline transfer to the live system.

**Inputs.**
- Recorded sessions: all sessions of one held-out fold plus the developer sessions (Phase 13 designates them; ids recorded).
- The same `config_hash`, `model_hash`, `git_sha` for both paths.
- `Δ_proc` policy: the harness's simulated processing delay set to the live measured per-frame processing time distribution's chosen statistic (candidate: p50; *Phase 09/13 define and label it*).

**Procedure.**
1. **Offline path:** Phase 09 harness regenerates all derived records from raw video (`producer = REGENERATED`).
2. **Online path:** the live app in replay-from-file mode processes the same raw video with original timestamps (`timestamp_source = REPLAY`, `producer = REPLAY`), all arms in shadow so every arm's records are logged.
3. Join records by `(record_type, frame_id, hand_id)` (and `candidate_id`/`strike_id` order for candidates/commits) and compare field by field.

**Pass criteria.**

| Record | Criterion |
|---|---|
| `TrackState`, `KinematicFeatures` | bit-identical (deterministic code path) — any difference is a bug. |
| `TrajectoryPrediction` | within the export-parity tolerance of the shipped model (declared in the Phase 10 ship ADR; candidate absolute `1e-5` ROI-norm); rule-based: bit-identical. |
| `StrikeCandidate` | identical set of `(hand_id, zone_id, source, frame_id)`; `t_impact_pred`/`t_impact_est`/`impact_position` within the same tolerance. |
| `CommittedStrike` | identical set of `(hand_id, zone_id, arm, episode_id)`; `t_commit` may differ by the documented `Δ_proc` only; any commit present in one path and absent in the other is a failure unless explained by a `t_now`-dependent gate at the tolerance boundary, in which case it is counted and reported (the count must be stated with the parity result; there is no silent tolerance on commit sets). |
| `TimingRecord` | not compared (live stamps are historical by nature); processing-latency statistics are reported separately. |

**Evidence.** Test id `TEST-PARITY-1`, session ids, `config_hash`, `model_hash`, `git_sha`, per-record-type match counts, max deviations, list of explained commit differences.

---

## 5. Interface conformance suite — `TEST-CONFORM-1…7` (Task 01.5; implemented in Phase 03, extended per interface by its first implementer)

A shared pytest suite parametrised over every implementation of an interface. An implementation that does not pass cannot be benchmarked or shipped. Ids follow `repo-layout.md` §3.5 (`TEST-<AREA>-<N>`); the mnemonic in parentheses is informal.

| Id | Interface | Checks |
|---|---|---|
| `TEST-CONFORM-1` (tip) | `TipEstimator` | Returns a schema-valid `StickObservation`; `method_id` matches the class attribute; `hand_id`, `frame_id`, `t_capture` equal the input's; `present=False` (not an exception) for an absent hand (`HandObservation.present=False`); output independent of call order across hands. |
| `TEST-CONFORM-2` (track) | `Tracker` | One schema-valid `TrackState` per call, `t_capture` monotone; status transitions obey README §8 for constructed confidence/gap sequences (VALID→DEGRADED→INVALID→STALE; re-acquisition); `INVALID`/`STALE` states carry null positions; `reset(reason)` clears history and sets `reset_reason`; `history` never contains a state with `t_capture >` current; never raises on `present=False` inputs. |
| `TEST-CONFORM-3` (anticipator) | `Anticipator` / `DirectAnticipator` | Returns `None` or a schema-valid `TrajectoryPrediction` with `t_capture` = latest history `t_capture`, `len(positions) == K`, `dt_step` = config; returns `None` (never raises) when history is shorter than `N_min` or status is `INVALID`/`STALE`; `anticipator_id`/`model_hash` populated; `reset` clears hidden state (prediction after reset equals prediction of a fresh instance on the same window); when `t_offsets_s` is set it is strictly increasing with `len == K`. *Live arms* (anything Phase 13 loads) must implement `Anticipator`; a `DirectAnticipator`-only model is refused by the loader. `DirectPrediction` outputs carry a non-null `model_hash` and a sanctioned `diagnostic_mode`. |
| `TEST-CONFORM-4` (geometry) | `Geometry` | Same routine accepts `OBSERVED` and `PREDICTED` trajectories; candidates are schema-valid with `source` set as requested; `REACTIVE` candidates have `t_impact_est`, others `t_impact_pred`+`tti`; upward crossing produces no candidate; entering through a non-impact boundary produces no candidate; at most one candidate per episode; every candidate has `derivation = GEOMETRY`; a sparse trajectory (`t_offsets_s`) is intersected as given; analytic crossing time reproduced within `1e-9` s on a synthetic linear segment (Phase 04 unit tests extend this). |
| `TEST-CONFORM-5` (commit) | `CommitPolicy` | Never emits a `CommittedStrike` when `track_state.status ∉ allowed set` (property test over random candidate streams); refractory honoured per (hand, zone); one commit per `episode_id`; `reset` discards `ARMED` candidates but not refractory timers; per-hand instances do not share state (two hands, same candidates → independent decisions). |
| `TEST-CONFORM-6` (audio) | `AudioScheduler` | Returns a schema-valid `AudioEvent` with `t_target_play = t_impact_target`, `audio_late_s ≥ 0`, `t_audio_out_est ≥ t_audio_scheduled`; never called with a shadow commit (app test). |
| `TEST-CONFORM-7` (source) | `FrameSource` | Yields schema-valid `FrameSample`s in strictly increasing `frame_id` and non-decreasing `t_capture`; replay source reproduces recorded `t_capture` exactly and sets `timestamp_source = REPLAY`. |

Common to all: outputs are serialisable and validate against their schema (`TEST-SCHEMA-1` validators are reused); no interface call reads `time.*` directly (only `spacedrums.timing.now()`; static check).

---

## 6. `TEST-SCHEMA-1` — contract schemas (implemented now)

Specified and executed in `contracts.md` §5 (`tests/contracts/`, `scripts/validate_contracts.py`). Re-run by any phase that adds or bumps a schema.

---

## 7. Reporting rules

- A test result is cited with its id, `git_sha`, `config_hash`, hardware id (for timing-sensitive runs), date, and the session/synthetic data id. Synthetic inputs are named `synthetic_*`/`example_*` and never presented as recordings (integrity I-4).
- A component is called **causal** in any document only after `TEST-CAUSAL-1` and `TEST-CAUSAL-2` have passed on the exact `git_sha` cited.
- Tolerances are declared **before** the run in the phase document; a run that needs a looser tolerance than declared fails and the discrepancy is recorded.

## Phase 17 hardened-build evidence

`TEST-CAUSAL-1/2` were re-run on the hardened build (Task 17.2): every component suite in the
full pytest run, the Phase 13 raw live/offline parity + future-blackout check
(`scripts/parity_test.py`), and a system-level `TEST-CAUSAL-1` over the live loop in replay mode
with GARBAGE / REMOVED / SHIFTED suffixes for every developer capture and arm set-up
(`scripts/invariant_replay.py`). The runtime monitor's invariant **I2** checks the causality
contract on every processed frame in replay and live mode (no record with `t_capture` after the
current frame; delivered frames strictly increase; histories hold delivered frames only).
`TEST-CONFORM-7` is strengthened: the live source now delivers **strictly increasing** `t_capture`
(a non-increasing stamp is refused and counted), and the replay source refuses such recordings at
load (ADR-0040 D5). In live mode, prefix invariance under a perturbed future cannot be
constructed (the future is the camera's), so the live-mode assertion set runs the monitor in
`raise` mode instead (I2: 37,587 checks, 0 violations; unattended, development evidence; a session
with a person is PENDING). Results and run ids: `docs/gates/phase-17-gate.md`.

## Phase 08 implementation evidence

`tests/features/test_causality.py` implements TEST-CAUSAL-1 (REMOVED/GARBAGE/SHIFTED,
both hands, default and jerk schemas) and TEST-CAUSAL-2 (N_core=2/3 with N-1 negative
control). `test_io.py` checks reference-file exclusion in features/models/loaders and guards
renamed non-causal input at runtime. `test_windows_normalize.py` proves labels/future targets
cannot change X and checks shared window assembly. Full participant-fold parity is PENDING;
existing DEV/SYNTHETIC sessions have separate replay evidence in the Phase 08 gate.
