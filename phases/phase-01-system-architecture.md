# Phase 01 — System Architecture & Contracts

## Status

Planned

## Purpose

Define the module boundaries, the per-hand pipeline structure, the data contracts exchanged between modules, the timing/clock model, the causality contract and how it is tested, the configuration schema, and the zone-registry extensibility rules. This phase produces an architecture specification that all implementation phases (02–17) conform to. No functional code is written.

## Why This Phase Exists

The pipeline (README §1) has eleven stages and three distinct sources of strike candidates (reactive, rule-based, learned). If each phase invents its own record types, timestamps, or coordinate frames, the offline evaluation (Phase 09) and the online system (Phase 13) will diverge and the research comparison becomes invalid. Fixing the contracts first makes the tip-estimation methods (Phase 03), the baselines (Phase 05), and the models (Phase 10–12) interchangeable behind the same interfaces, which is exactly what the benchmark design needs.

## Relationship to Research Contribution

- The **causality contract** and its test (Task 01.6) are the technical guarantee behind "never use future frames".
- The **`TrajectoryPrediction` → geometry → `StrikeCandidate`** contract chain encodes trajectory-first: the model's primary output is a future trajectory; the strike is derived by a separate deterministic component.
- The **`TimingRecord`** contract carries every timestamp in README §5 so that `L_sys`, `L_pred`, and the end-to-end decomposition can be computed identically offline and online.
- Per-hand independence (Q33) is a structural property of the architecture, not a runtime option.

## Inputs

- Phase 00 artefacts (RTM, repo layout, reproducibility policy, ADRs).
- README §5–§10 canonical definitions.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-001, REQ-021, REQ-033, REQ-051, REQ-052, REQ-055, REQ-060b, REQ-207, REQ-302; contributes to REQ-004.

## Expected Outputs

- Architecture Specification (module map, per-hand pipeline, threading model, latency-budget slots).
- Data Contract Specification (schemas for every record type below, with units and coordinate frames).
- Causality Contract + test specification.
- Configuration Schema (camera profile, ROI, zones, thresholds, model descriptor).
- Zone-Registry extensibility rules (future kick / non-hand trigger types).
- Interface definitions for pluggable components: `TipEstimator`, `Tracker`, `Anticipator` (rule-based or model), `CommitPolicy`, `AudioScheduler`.
- ADRs for each non-obvious choice.

## Dependencies

- Phase 00 Exit Gate passed.

## System Components

Specified (not implemented) in this phase:

| Module | Responsibility | Producer of | Consumer of |
|--------|----------------|-------------|-------------|
| `capture` | Timestamped frames from the webcam; ROI crop | `FrameSample` | camera device |
| `hands` | Hand landmark estimation, L/R identity | `HandObservation` | `FrameSample` |
| `stick` | Stick detection/segmentation, axis, tip (pluggable `TipEstimator`) | `StickObservation` | `FrameSample`, `HandObservation` |
| `tracking` | Per-hand causal filter, state machine | `TrackState` | `HandObservation`, `StickObservation` |
| `features` | Per-hand causal kinematic features | `KinematicFeatures` | `TrackState`, zone geometry |
| `prediction` | Pluggable `Anticipator`: rule-based extrapolator or learned model | `TrajectoryPrediction` (+ auxiliary outputs) | `KinematicFeatures` / `TrackState` history |
| `geometry` | Zone registry, impact surfaces, trajectory–zone intersection, sub-frame crossing time | `StrikeCandidate` | `TrajectoryPrediction` (predicted) or `TrackState` history (observed) |
| `commit` | Per-hand commit state machine, refractory, duplicate suppression, safety checks | `CommittedStrike` | `StrikeCandidate`, `TrackState` |
| `audio` | Sample bank, scheduling, mixer, device clock mapping | `AudioEvent`, `t_audio_out` estimate | `CommittedStrike` |
| `timing` | Collects all timestamps into `TimingRecord` | `TimingRecord` | all modules |
| `ui` | Playing-area guide, zone display, debug overlay (Phase 15) | — | all records |
| `eval` | Offline replay, metrics (Phase 09) | reports | recorded records + labels |
| `data` | Recording, dataset manifests, labels (Phases 06–07) | files | records |

## Architecture

### Per-hand pipeline

```
FrameSample ──► hands ──► HandObservation(LEFT), HandObservation(RIGHT)
                 │
                 └──► stick ──► StickObservation(LEFT), StickObservation(RIGHT)

For each hand h ∈ {LEFT, RIGHT} (independent state, no cross-hand coupling in V1):
  tracking[h] ──► TrackState[h]
  features[h] ──► KinematicFeatures[h]
  prediction[h] ──► TrajectoryPrediction[h] (+ aux)
  geometry ──► StrikeCandidate[h]* (0..n per frame)
  commit[h] ──► CommittedStrike[h]* (0..1 per frame per zone)
audio ◄── CommittedStrike[*] (both hands; polyphonic)
timing ◄── every stage
```

Cross-hand interaction is limited to: (a) the hand-identity assignment step inside `hands`, (b) the audio mixer. Any future cross-hand feature (e.g. suppressing a duplicate when both tips enter the same zone) is a Phase 05 `CommitPolicy` decision, not an architectural coupling.

### Threading / process model (Pending Architecture Decision — candidates)

- **Capture thread:** pulls frames, stamps `t_capture` / `t_frame_available`, pushes to a bounded queue (drop-oldest policy so that latency never accumulates; drops are counted).
- **Processing loop (main thread or worker):** hands → stick → tracking → features → prediction → geometry → commit, per frame, both hands.
- **Audio callback thread:** owned by the audio library; consumes a lock-free queue of `AudioEvent`s with target times.
- **Optional inference worker (Phase 13):** only if model inference cannot fit inside the frame budget on the main loop; must preserve causality (it only ever sees frames already delivered).

Python GIL implications are a Pending Benchmark (Phase 16). The architecture must allow moving `hands`/`stick` to a separate process if needed without changing contracts.

### Latency-budget slots

Per-frame budget at 30 FPS is ~33.3 ms and at 60 FPS ~16.7 ms (arithmetic, not a measurement). The architecture assigns named slots — `capture`, `hands`, `stick`, `tracking`, `features`, `prediction`, `geometry+commit`, `audio_dispatch` — whose measured costs are filled in from Phase 02 onward. Target values per slot are **To Be Experimentally Determined** in Phase 16.

### Source-of-candidate abstraction

`geometry` accepts either an *observed* trajectory (from `TrackState` history) or a *predicted* trajectory (from `TrajectoryPrediction`) and produces `StrikeCandidate`s with `source ∈ {REACTIVE, RULE, MODEL}`. This is the single mechanism by which Baselines A, B, and C are compared under identical commit logic.

## Detailed Tasks

### Task 01.1 — Module Map and Responsibility Boundaries
- **What:** Write the module table above into the architecture spec with allowed dependencies (a module may import only from modules to its left in the pipeline plus `timing`, `config`, `geometry` types). Produce a dependency diagram.
- **Why:** Prevents e.g. `commit` reaching into `hands` internals, which would make offline replay diverge from online behaviour.
- **Depends on:** Phase 00 repo layout.
- **Evidence:** Spec section; an import-linting rule description to be enforced from Phase 02 onward.

### Task 01.2 — Data Contract Specification
- **What:** Define every record type with fields, types, units, frame, nullability. See *Interfaces / Contracts* below for the field lists. Include a schema-version field on every record.
- **Why:** Offline datasets (Phase 06/07) store these records; the harness (Phase 09) and live system (Phase 13) must read the same schema.
- **Depends on:** README §5–§7.
- **Evidence:** `docs/architecture/contracts.md` + machine-readable schema files (JSON Schema or dataclass stubs used only as schema, not logic).

### Task 01.3 — Clock and Timestamp Model
- **What:** Specify `t_mono` as the single reference; specify how camera driver timestamps are mapped (Phase 02 implements), how audio device time is mapped (Phase 04 implements), and the fields of `TimingRecord`. Specify that every record carries the `t_capture` of the frame it derives from.
- **Why:** README §5 is only meaningful if every module stamps consistently.
- **Depends on:** README §5.
- **Evidence:** Spec section; `TimingRecord` schema.

### Task 01.4 — Per-Hand State Ownership
- **What:** Specify that `tracking`, `features`, `prediction`, and `commit` instantiate one state object per hand, keyed by `hand_id ∈ {LEFT, RIGHT}`, with an explicit `reset(reason)` method and a `status` per README §8. Specify what resets on `INVALID`/`STALE` (filter state, feature history, model hidden state, commit `ARMED` candidates) and what persists (refractory timers — persist, so a re-acquired hand cannot immediately re-trigger the same zone).
- **Why:** Q33–35.
- **Depends on:** README §8.
- **Evidence:** State-ownership table in the spec; reset matrix (state × trigger → action).

### Task 01.5 — Pluggable Interfaces
- **What:** Define abstract interfaces:
  - `TipEstimator.estimate(frame_roi, hand_obs) -> StickObservation` with `method_id`.
  - `Tracker.update(hand_obs, stick_obs, t_capture) -> TrackState` (causal; no lookahead argument exists).
  - `Anticipator.predict(track_history[h], features[h]) -> TrajectoryPrediction | None` (rule-based and learned implementations share this).
  - `Geometry.intersect(trajectory, source) -> list[StrikeCandidate]`.
  - `CommitPolicy.step(candidates[h], track_state[h], t_now) -> list[CommittedStrike]`.
  - `AudioScheduler.schedule(committed) -> AudioEvent`.
- **Why:** Enables the method benchmarks (Phase 03), baseline comparison (Phase 05/09/18), and model swapping (Phase 13) without touching other modules.
- **Depends on:** 01.2.
- **Evidence:** Interface definitions in the spec; each later phase's implementation must cite the interface it implements.

### Task 01.6 — Causality Contract and Its Test
- **What:** State the contract (README §13). Define the **future-perturbation invariance test**: given a recorded sequence, run the causal pipeline up to frame `i`, then run it again with frames `> i` replaced by random/garbage data (or removed); all outputs up to and including frame `i` must be bit-identical (or within a documented floating-point tolerance for non-deterministic ops). Define a second test: **history-truncation monotonicity** — outputs at frame `i` depend only on frames within the declared window `N`. Specify that the test harness (Phase 09) must run these on every `Tracker`, `Anticipator`, and feature implementation.
- **Why:** This is the only way "causal" becomes verifiable rather than asserted.
- **Depends on:** 01.5.
- **Evidence:** Test specification document; later phases reference it as `TEST-CAUSAL-1` and `TEST-CAUSAL-2`.

### Task 01.7 — Configuration Schema
- **What:** Define the top-level config: `camera_profile` (device, resolution, requested FPS, exposure mode, measured native FPS reference), `roi` (pixel rectangle), `zones[]` (id, name, shape, impact surface, trigger type, sample id), `tracking` (thresholds `c_valid`, `c_min`, `g_max`, `age_max`, filter type/params), `anticipator` (`type: rule | model`, horizon, model path/hash), `commit` (TTI commit threshold, refractory, duplicate-suppression rules, degraded-commit flag), `audio` (device, buffer size, sample bank), `debug` (overlay flags). All values tunable; schema validation mandatory at load.
- **Why:** Every experiment must be reproducible from a config snapshot (Phase 00 policy).
- **Depends on:** 01.2, Phase 00 Task 00.5.
- **Evidence:** `configs/schema/config.schema.json` (or equivalent) + one example config with all values marked `# candidate` in comments.

### Task 01.8 — Zone-Registry Extensibility Rules
- **What:** Specify `Zone.trigger_type ∈ {HAND_TIP}` for V1 with the enum declared open (e.g. `FOOT` reserved, not implemented). Specify that `geometry.intersect` is generic over "a trajectory of a tracked point" so a future foot point could reuse it. Specify that zones are hand-agnostic (Q11) with an optional `allowed_hands` field defaulting to both, reserved for future experiments.
- **Why:** Q17/Q55 — kick outside V1 but must not be made impossible.
- **Depends on:** 01.2.
- **Evidence:** Spec section + ADR.

### Task 01.9 — Recording/Replay Symmetry Requirement
- **What:** Specify that the live pipeline can be run in *record mode* (persisting `FrameSample` video + every record type per frame) and that the same module code can be driven by a *replay source* that feeds recorded frames/records with their original timestamps. Specify what is recorded raw (video, `t_capture`) versus derived (all records), and that derived records can be regenerated from raw video by re-running the causal pipeline with a given config/version.
- **Why:** Phases 06, 09, 13 depend on offline/online parity; Phase 13's parity test needs this design.
- **Depends on:** 01.2, 01.3.
- **Evidence:** Spec section; parity test defined as `TEST-PARITY-1` (Phase 13 executes it).

### Task 01.10 — Architecture Decision Records
- **What:** ADRs for: single monotonic clock; ROI-normalized y-down coordinates; per-hand independence; geometry as a separate deterministic stage after prediction (trajectory-first); candidate-source abstraction; threading candidates; config schema.
- **Why:** Traceability.
- **Depends on:** All above.
- **Evidence:** ADR files in `docs/decisions/`.

## Data Requirements

None recorded. Contract examples may use synthetic hand-written records for schema validation only, clearly named `example_*`.

## Algorithms / Technical Approach

No algorithms are implemented. The phase fixes *where* algorithms live:

- Filtering/tracking algorithms → Phase 03.
- Impact-surface crossing and sub-frame interpolation → Phase 04.
- Extrapolation (rule-based) → Phase 05.
- Learned prediction → Phases 09–12.

## Interfaces / Contracts

Field lists (units: seconds on `t_mono`; positions ROI-normalized unless suffixed `_px`; `schema_version` on all):

**`FrameSample`**: `frame_id:int`, `t_capture:float`, `t_frame_available:float`, `roi_px:(x,y,w,h)`, `image_ref` (in-memory or file offset), `camera_profile_id:str`, `dropped_since_last:int`.

**`HandObservation`**: `frame_id`, `t_capture`, `hand_id:{LEFT,RIGHT}`, `landmarks:[21×(x,y)]`, `landmark_visibility:[21]` (if provided by the estimator), `handedness_score:float`, `bbox:(x,y,w,h)`, `detector_id:str`, `present:bool`.

**`StickObservation`**: `frame_id`, `t_capture`, `hand_id`, `axis_origin:(x,y)`, `axis_dir:(ux,uy)` (unit), `tip:(x,y)`, `tip_confidence:float∈[0,1]`, `axis_confidence:float`, `method_id:{GEOM, AXIS_REFINED, MARKER}`, `stick_length_est:float|null`, `present:bool`.

**`TrackState`**: `frame_id`, `t_capture`, `hand_id`, `status:{VALID,DEGRADED,INVALID,STALE}`, `tip_filtered:(x,y)`, `tip_velocity:(vx,vy)` (units: normalized/s), `tip_acceleration:(ax,ay)`, `axis_angle:float` (rad), `axis_angular_velocity:float`, `confidence:float`, `frames_since_valid:int`, `last_valid_t:float`, `history_ref` (window of past `TrackState`s, causal).

**`KinematicFeatures`**: `frame_id`, `t_capture`, `hand_id`, `feature_schema_id:str`, `values:[F]` (float vector per Phase 08 schema), `mask:[F]` (validity), `dt:float`.

**`TrajectoryPrediction`**: `frame_id`, `t_capture` (reference time), `hand_id`, `K:int`, `dt_step:float`, `positions:[K×(x,y)]`, `velocities:[K×(vx,vy)]|null`, `uncertainty:[K×…]|null`, `aux:{strike_prob_within_H:float|null, tti:float|null, zone_logits:[Z]|null, impact_pos:(x,y)|null, intensity_proxy:float|null}`, `anticipator_id:str`, `model_hash:str|null`, `t_inference_done`.

**`StrikeCandidate`**: `candidate_id`, `frame_id`, `t_capture`, `hand_id`, `zone_id`, `source:{REACTIVE,RULE,MODEL}`, `t_impact_pred:float|null` (null for REACTIVE), `t_impact_est:float|null` (set for REACTIVE from sub-frame interpolation), `tti:float|null`, `impact_position:(x,y)`, `crossing_velocity:(vx,vy)`, `strike_probability:float|null`, `intensity_proxy:float`, `t_candidate`.

**`CommittedStrike`**: `strike_id`, `candidate_id`, `hand_id`, `zone_id`, `source`, `t_commit`, `t_impact_target:float` (the time the sound is intended to sound: `t_impact_pred` for anticipatory, `now` for reactive), `intensity_proxy`, `gain:float`, `refractory_until:float`, `episode_id`.

**`AudioEvent`**: `strike_id`, `sample_id`, `t_audio_scheduled`, `t_target_play`, `t_audio_out_est:float` (from measured output latency), `gain`.

**`TimingRecord`**: `strike_id|frame_id`, and every timestamp of README §5.2 that applies, plus `hardware_id`, `config_hash`.

**`SessionMetadata`** and **`LabelRecord`**: defined in Phases 06 and 07 respectively; this phase reserves their names and requires `dataset_version` and `schema_version` fields.

## Tests

- **Schema tests:** every contract has a JSON Schema (or equivalent) that accepts a valid example and rejects examples missing required fields, with wrong units flags, or with `t_capture` absent.
- **Interface conformance tests (specified now, implemented in later phases):** each `TipEstimator`, `Tracker`, `Anticipator`, `CommitPolicy` implementation must pass a shared conformance suite (returns correct record types, respects `hand_id`, never raises on `INVALID` input).
- **`TEST-CAUSAL-1` / `TEST-CAUSAL-2`:** specified in Task 01.6; executed by Phase 03 (tracker), Phase 05 (rule-based anticipator), Phase 08 (features), Phase 10+ (models).
- **`TEST-PARITY-1`:** specified in Task 01.9; executed in Phase 13.

## Measurements

None. Latency-budget slots are named but left empty (Pending Benchmark).

## Experimental Design

Not applicable.

## Acceptance Criteria

1. Architecture spec contains the module map, allowed-dependency rules, per-hand pipeline, threading candidates, and named latency slots.
2. Every record type in *Interfaces / Contracts* has a machine-readable schema that validates.
3. Causality tests `TEST-CAUSAL-1/2` and parity test `TEST-PARITY-1` are fully specified (inputs, procedure, pass criteria).
4. Config schema exists and validates the example config.
5. Zone-registry extensibility (open trigger-type enum, hand-agnostic zones) is specified.
6. ADRs written for all decisions in Task 01.10.
7. Reviewer confirms the spec does not contradict `project-discovery.md` (trajectory-first, markerless primary, no out-of-scope hardware, per-hand independence, causal).

## Definition of Done

- All acceptance criteria met; gate record PASS.
- Integrity checklist applied (no implementation claimed; no numbers as results).
- RTM updated with REQ → Phase 01 references for architectural requirements.

## Risks

- Over-engineering contracts before real data exists → mitigation: `schema_version` on every record; contracts may evolve via ADR, with migration notes.
- Python threading model may not meet the frame budget → contracts must survive a move to multiprocessing (they do if records are serialisable — required).
- Coordinate convention chosen now may conflict with a chosen hand-landmark library's convention → mitigation: `hands` module converts to ROI-normalized at its boundary; documented in Task 01.2.

## Failure Modes

- Contracts silently diverge between offline and online paths → `TEST-PARITY-1` exists to catch it.
- A module reads future frames via a shared buffer → `TEST-CAUSAL-1` exists to catch it.

## Fallback Strategy

- If a later phase needs a field not in the contract, it adds it with a schema-version bump and an ADR; it never repurposes an existing field.

## Artifacts Produced

- `docs/architecture/architecture.md`
- `docs/architecture/contracts.md` + `schemas/*.schema.json`
- `docs/architecture/causality-tests.md` (`TEST-CAUSAL-1/2`, `TEST-PARITY-1`)
- `configs/schema/config.schema.json` + `configs/example.candidate.yaml`
- `docs/decisions/ADR-0004..` (architecture decisions)
- `docs/gates/phase-01-gate.md`

## Exit Gate

Reviewer confirms acceptance criteria; PASS recorded. Phases 02 and 04 may start (in parallel); Phase 03 after 02.

## What Must NOT Be Done Yet

- No functional implementation of any module.
- No benchmark of libraries beyond the Phase 00 smoke import.
- No choice of filter, tip-estimation method, model family, or thresholds — only the interfaces they must implement.

## Open Questions

- Threading vs. multiprocessing for `hands`/`stick` on the target laptop (Pending Benchmark, Phase 16).
- Whether `DEGRADED` commits should ever be allowed (Phase 05/17 experiment).
- Whether `TrajectoryPrediction` should carry per-step uncertainty in V1 or only in Phase 12 (the field is reserved as nullable).

## Decisions That Must Be Experimentally Validated

- Latency-budget slot targets (Phase 16).
- Bounded-queue drop policy's effect on effective frame rate (Phase 02/16).
- Whether the one-step causal bridge in `DEGRADED` is safe (Phase 03/05/17).
