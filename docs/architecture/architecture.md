# Space Drums — Architecture Specification

**Phase:** 01 — System Architecture & Contracts · **Status:** IMPLEMENTED as a specification (no module code exists; every module below is PLANNED). Awaiting Phase 01 Exit Gate.
**Inputs:** [`../../phases/README.md`](../../phases/README.md) §1, §5–§10, §13; [`../../phases/phase-01-system-architecture.md`](../../phases/phase-01-system-architecture.md); Phase 00 artefacts ([`../repo-layout.md`](../repo-layout.md), [`../reproducibility-policy.md`](../reproducibility-policy.md), ADR-0001…0003).
**Companions:** [`contracts.md`](contracts.md) (record types, schemas), [`causality-tests.md`](causality-tests.md) (`TEST-CAUSAL-1/2`, `TEST-PARITY-1`, conformance suite), [`../../configs/schema/config.schema.json`](../../configs/schema/config.schema.json), ADR-0004…0012 in [`../decisions/`](../decisions/).
**Requirements owned (RTM):** REQ-001, REQ-021, REQ-033, REQ-051, REQ-052, REQ-055, REQ-060b, REQ-207, REQ-302; contributes to REQ-004. Traceability table in §16.

> Every implementation phase (02–17) conforms to this document. A later phase that needs something this document does not allow adds it by **ADR + schema-version bump**; it never repurposes an existing field, module boundary, or timestamp (Phase 01 *Fallback Strategy*).
>
> **Causality rule (README §13):** any component labelled *causal* consumes only observations with timestamp ≤ the current frame's `t_capture`. Offline label generation (Phase 07) may use the full recording and is therefore non-causal by design; this is documented and is the only place future information is permitted.

---

## 1. Pipeline overview

The system is the eleven-stage pipeline of `project-discovery.md` ("Confirmed Core Architecture"), mapped onto thirteen modules plus three type-only packages. The research contribution is *trajectory-first*:

```
Past Motion → Causal Temporal Model → Future Stick Trajectory → Virtual Drum Geometry
→ Predicted Intersection → Predicted Strike → Time-to-Impact → Audio Scheduling
```

Structural consequences fixed here:

1. The anticipator's primary output is a **`TrajectoryPrediction`** (future positions). It is never a bare strike classifier (ADR-0007).
2. **`geometry`** is a separate, deterministic stage that turns *any* trajectory — observed or predicted — into `StrikeCandidate`s (ADR-0008). Baselines A, B and every learned arm C therefore share one geometry implementation and one commit policy.
3. Each hand owns independent tracking, feature, prediction and commit state (ADR-0006, Q33).
4. One monotonic clock stamps everything (ADR-0004); every record carries the `t_capture` of the frame it derives from.
5. Coordinates are ROI-normalized, y-down, 2-D (ADR-0005, Q21).

---

## 2. Module map and responsibility boundaries (Task 01.1)

### 2.1 Modules

| Module (`src/spacedrums/<pkg>/`) | Responsibility | Produces | Consumes | Owning phase |
|---|---|---|---|---|
| `contracts` *(type-only)* | Record types (§3 of `contracts.md`), enums, interface definitions (§11). No logic beyond construction/validation. | — | — | 01 (spec), 02 (first code) |
| `timing` *(type-only + clock)* | The single `t_mono` clock accessor; `TimingRecord` collector | `TimingRecord` | every stage's stamps | 01 (spec), 02 (clock), 05 (full records) |
| `config` | Schema-validated config loading, resolution, `config_hash` | resolved config | YAML files | 01 (schema), 02 (loader) |
| `capture` | Timestamped frames from the webcam; fixed ROI crop; bounded queue with drop counting; px↔normalized helper | `FrameSample` | camera device / replay file | 02 |
| `hands` | Hand landmark estimation; LEFT/RIGHT identity; conversion to ROI-normalized coordinates | `HandObservation` ×2 | `FrameSample` | 03 |
| `stick` | Stick detection / segmentation, axis, tip — pluggable `TipEstimator` (`GEOM`, `AXIS_REFINED`, `MARKER`) | `StickObservation` ×2 | `FrameSample`, `HandObservation` | 03 |
| `tracking` | Per-hand causal filter and README §8 state machine — pluggable `Tracker` | `TrackState` ×2 | `HandObservation`, `StickObservation` | 03 |
| `features` | Per-hand causal kinematic features (offline = online code path) | `KinematicFeatures` ×2 | `TrackState` history, zone geometry (read-only) | 08 |
| `prediction` | Pluggable `Anticipator`: rule-based extrapolator (B) or learned model (C-*) | `TrajectoryPrediction` ×2 | `KinematicFeatures` / `TrackState` history | 05, 09–13 |
| `geometry` | Zone registry, impact surfaces, trajectory–zone intersection, sub-frame crossing time, entry episodes | `StrikeCandidate` × 0..n per hand | a *trajectory* (observed from `TrackState` history, or predicted) | 04 |
| `commit` | Per-hand commit state machine, refractory, duplicate suppression, safety gates — pluggable `CommitPolicy` | `CommittedStrike` × 0..1 per hand per zone per frame | `StrikeCandidate`, `TrackState` | 05 |
| `audio` | Sample bank, time-targeted scheduler, callback mixer, device-clock mapping, gain mapping | `AudioEvent` (+ `t_audio_out_est`) | `CommittedStrike` | 04 |
| `ui` | Stand-here guide, zone display, debug overlay/dashboard | rendering only | every record (read-only) | 02, 15 |
| `eval` | Causal replay simulator, event matching, canonical metrics, experiment-log writer | reports, `run.json` | recorded records + labels | 09 |
| `data` | Recording tool, session metadata, dataset manifests, labelling/QC, splits | files | records | 06, 07 |
| `calib` | Calibration wizard, calibration file I/O | config fragments | `capture`, `geometry`, `ui` | 14 |
| `app` *(composition root)* | Wires modules into the live loop, arm switch, record/replay mode | — | everything | 05, 13 |

Amendment to `repo-layout.md` §1/§2: the three type-only packages `contracts/`, `timing/`, `config/` and the composition root `app/` are added by this phase (ADR-0012). README stubs exist; no code.

### 2.2 Allowed-dependency rule

Modules are ordered in **layers**. A module may import from its own layer's *lower* rows and from any layer below it — never sideways into a peer's internals and never upward.

| Layer | Packages | May import from |
|---|---|---|
| L0 — types | `contracts` | nothing in `spacedrums` |
| L0 — types | `timing`, `config` | `contracts` |
| L1 — capture | `capture` | L0 |
| L2 — perception | `hands` | L0, `capture` (px↔normalized helper only) |
| L2 — perception | `stick` | L0, `capture`, `hands` |
| L3 — tracking | `tracking` | L0 |
| L4 — features | `features` | L0, `tracking`, `geometry` (**zone geometry read-only**: zone registry and distances; no candidate generation) |
| L4 — geometry | `geometry` | L0 |
| L5 — prediction | `prediction` | L0, `features`, `tracking` |
| L6 — decision | `commit` | L0, `geometry`, `tracking` |
| L6 — output | `audio` | L0 |
| L7 — tooling | `ui`, `eval`, `data`, `calib` | any lower layer (read-only use of records; `eval` may *drive* L1–L6 through the interfaces in §11) |
| L8 — root | `app` | everything |

Rules that follow:

- `commit` never reaches into `hands`/`stick`/`prediction`; it sees only `StrikeCandidate` + `TrackState` (the phase document's example). This is what keeps offline replay (Phase 09) and the live loop (Phase 13) identical.
- `geometry` does not know whether a trajectory is observed or predicted beyond the `source` tag (ADR-0008).
- `prediction` never imports `geometry`: a model cannot "peek" at zones except through features that Phase 08 defines and tests for leakage.
- `audio` and `capture` know nothing about hands or zones.
- Anything in `eval`/`data` that reproduces pipeline behaviour must call the *same* module code via the §11 interfaces (record/replay symmetry, §12) — never a re-implementation.

### 2.3 Dependency diagram

```
                       ┌──────────── L0 types ────────────┐
                       │  contracts ◄── timing ◄── config │
                       └───────────────▲──────────────────┘
                                       │ (all modules)
  L1  capture ──────────────┐
                            ▼
  L2  hands ──────► stick   │
        │             │     │
        ▼             ▼     │
  L3  tracking ◄────────────┘
        │  ├────────────────────────┐
        ▼  ▼                        │
  L4  features ──(read-only zones)──► geometry
        │                             ▲    │
        ▼                             │    │
  L5  prediction ── TrajectoryPrediction ──┘ (predicted trajectory)
                    TrackState history ────┘ (observed trajectory)
                                           │ StrikeCandidate
                                           ▼
  L6  commit ◄── TrackState              audio ◄── CommittedStrike
  L7  ui · eval · data · calib   (read records / drive interfaces)
  L8  app                        (composition root)
```

### 2.4 Import-linting rule (enforced from Phase 02)

The layer table is enforced mechanically with the `import-linter` tool (dev dependency added in Phase 02 to `requirements.in`; recorded there). Candidate contract, to be committed as `.importlinter` when the first module lands:

```ini
[importlinter]
root_package = spacedrums

[importlinter:contract:layers]
name = Space Drums pipeline layers
type = layers
layers =
    spacedrums.app
    spacedrums.ui | spacedrums.eval | spacedrums.data | spacedrums.calib
    spacedrums.commit | spacedrums.audio
    spacedrums.prediction
    spacedrums.features | spacedrums.geometry
    spacedrums.tracking
    spacedrums.stick
    spacedrums.hands
    spacedrums.capture
    spacedrums.timing | spacedrums.config
    spacedrums.contracts

[importlinter:contract:no-peek]
name = prediction must not import geometry; commit must not import perception
type = forbidden
source_modules = spacedrums.prediction
forbidden_modules = spacedrums.geometry

[importlinter:contract:commit-blind]
type = forbidden
source_modules = spacedrums.commit
forbidden_modules = spacedrums.hands, spacedrums.stick, spacedrums.prediction, spacedrums.features
```

`features → geometry` (read-only zone access) is the one intentional exception to strict layering and is expressed above by placing `features` and `geometry` in the same layer; the "read-only" part is a code-review rule (features may call zone-distance helpers, never `intersect`). The linter runs in the test suite of every phase from 02 onward; a violation fails the gate (integrity item I-2 evidence).

---

## 3. Per-hand pipeline

```
FrameSample ──► hands ──► HandObservation(LEFT), HandObservation(RIGHT)
                 │
                 └──► stick ──► StickObservation(LEFT), StickObservation(RIGHT)

For each hand h ∈ {LEFT, RIGHT}   (independent state; no cross-hand coupling in V1)
  tracking[h].update(...)           ──► TrackState[h]            (exactly one per frame, any status)
  features[h].compute(...)          ──► KinematicFeatures[h]     (only when status ∈ {VALID, DEGRADED})
  anticipator[h].predict(...)       ──► TrajectoryPrediction[h] | None
  geometry.intersect(observed[h], REACTIVE)  ──► StrikeCandidate[h]*   (Baseline A path)
  geometry.intersect(predicted[h], RULE|MODEL) ──► StrikeCandidate[h]* (B / C path)
  commit[h].step(candidates[h], TrackState[h], t_now) ──► CommittedStrike[h]*
audio.schedule(CommittedStrike[*])  (both hands; polyphonic)
timing.collect(...)                 (every stage stamps; §7)
```

Cross-hand interaction is limited to (a) the LEFT/RIGHT identity assignment inside `hands` and (b) the audio mixer. Any future cross-hand rule (e.g. suppressing a duplicate when both tips enter one zone) is a `CommitPolicy` decision (Phase 05), not an architectural coupling (ADR-0006).

Both hands are processed for every frame, in a fixed order (LEFT then RIGHT) so that logs are deterministic; the order carries no semantic meaning.

---

## 4. Source-of-candidate abstraction (ADR-0008)

`geometry.intersect(trajectory, source)` accepts one **trajectory** — a time-ordered list of `(t, p)` samples of a tracked point — and returns `StrikeCandidate`s tagged `source ∈ {REACTIVE, RULE, MODEL}`:

| Source | Trajectory fed to geometry | `t_impact_est` | `t_impact_pred` / `tti` | Produced by |
|---|---|---|---|---|
| `REACTIVE` (Baseline A) | the last two *observed* `TrackState.tip_filtered` samples `(t_{i-1}, p_{i-1}), (t_i, p_i)` | sub-frame interpolated crossing (Phase 04, Task 04.3) | null | Phase 05, Task 05.1 |
| `RULE` (Baseline B) | `TrajectoryPrediction.positions` from a causal CV/CA extrapolator, prefixed by the current observed tip | null | first valid predicted crossing; `tti = t_impact_pred − t_capture` | Phase 05, Task 05.2 |
| `MODEL` (Arm C) | `TrajectoryPrediction.positions` from a learned model, same prefix rule | null | as RULE | Phases 09–13 |

Every candidate above carries `derivation = GEOMETRY`. **Diagnostic exception (gate review, 2026-09-21):** Phase 09 Task 09.8 evaluates C-GBDT additionally in a *direct* mode (probability + TTI → candidate, no geometry) and Phase 19 AB-NOTRAJ ablates the trajectory stage. These are the **only** paths that bypass geometry; they produce `StrikeCandidate(source = MODEL, derivation = DIRECT_HEAD)` from a `DirectPrediction` (`contracts.md` §3.11) inside the harness, through the same commit policy, and every result from them is labelled *direct / no-trajectory (diagnostic)*. The live application never runs them (Phase 13's loader refuses a direct-only model); `derivation` is schema-enforced so the two paths cannot be confused in any table.

Consequences:

- The impact definition (first valid downward/inward entry per episode, Q36–Q37), the sub-frame interpolation (Q39), and the impact-position/zone retention (Q38) are implemented **once** in `geometry` and are identical for all arms.
- The commit policy is **source-agnostic**: it reads `strike_probability`, `tti`, `t_impact_pred`/`t_impact_est`, zone and hand — never the arm or the derivation. The arm is recorded (`CommittedStrike.arm`, schema-bound to `source`: A↔REACTIVE, B↔RULE, C-*↔MODEL) for analysis only.
- Phase 18's design can let any of A, B, C win on any metric because nothing in the decision path privileges one source.
- Arms may run **simultaneously**: one *active* (sounds), others *shadow* (`CommittedStrike.shadow = true`, logged, not scheduled). Metrics treat shadow commits exactly like sounding ones.

---

## 5. Clock and timestamp model (Task 01.3; ADR-0004)

### 5.1 The clock

- **`t_mono`** is the single reference clock for every timestamp in the system, in **seconds** as `float`. Candidate implementation: `time.perf_counter()` (monotonic, sub-microsecond resolution on Windows via QPC). The identity of the function actually used is recorded as `clock_id` in `TimingRecord`, the camera profile, the audio profile and every `RecordStreamHeader`.
- Exactly one accessor exists: `spacedrums.timing.now() -> float`. No module calls `time.*` directly for timestamps (code-review rule; grep-able).
- `t_mono` has no defined epoch. Wall-clock (`started_at`) is recorded once per session in `SessionMetadata` together with the `t_mono` value at that instant, so records can be aligned to real time when needed (ethics/retention, cross-device audio alignment).
- **Cross-process rule:** if `hands`/`stick` move to a worker process (§8, candidate T3), the worker never *creates* frame timestamps; `t_capture`/`t_frame_available` are stamped in the capture process and travel with the frame. Processing-done stamps made in the worker use the same clock function; whether the OS clock is consistent across processes is a **Pending Benchmark** (Phase 16) and is measured before T3 is adopted.

### 5.2 Camera driver timestamps → `t_mono` (Phase 02 implements, Task 02.2)

- `timestamp_source = DRIVER_MAPPED`: driver timestamps `t_drv` are mapped by a linear model `t_capture = a + b·t_drv` fitted over a warm-up window and re-estimated slowly (drift). The residual distribution (p50/p95, max) is a **MEASURED** quantity in the camera profile.
- `timestamp_source = GRAB_RETURN`: `t_capture = now() − bias_est` at grab return, where `bias_est` is the capture-latency estimate of the camera profile (Phase 02, Task 02.9) and its uncertainty is stated. Until measured, `bias_est = 0` and the profile says so.
- Either way, `t_frame_available = now()` when the `FrameSample` is enqueued, and `t_capture ≤ t_frame_available` is asserted.
- Delivered FPS is **never** taken from the requested mode: it is measured from `t_capture` differences (integrity item I-5). The config schema forbids a native-FPS number without a `run_id`.

### 5.3 Audio device time → `t_mono` (Phase 04 implements, Task 04.7)

- The callback's device stream time (`t_dev`, seconds on the audio device clock) is mapped by `t_mono = a + b·t_dev`, estimated by linear regression over callback samples; the residual is a **MEASURED** quantity in the audio profile.
- `t_audio_out_est = t_placement + L_out`, where `t_placement` is the sample-exact placement instant on `t_mono` and `L_out` is the **MEASURED** output latency of the audio profile (Phase 04, Task 04.8). It is an estimate; the measured `t_audio_out` field of `TimingRecord` stays null until Phase 18 measures externally.

### 5.4 Per-event timestamps and `TimingRecord`

The README §5.2 symbols are the field names (all on `t_mono`, seconds):

| Field | Stamped by | Kind |
|---|---|---|
| `t_capture`, `t_frame_available` | `capture` | FRAME |
| `t_tracking_done` | `app` loop after both hands' `Tracker.update` | FRAME |
| `t_features_done` | `app` loop after both hands' features | FRAME (null for arms without features) |
| `t_inference_done` | `Anticipator.predict` (inside the record it returns) | FRAME (null for A) |
| `t_candidate` | `geometry.intersect` | STRIKE |
| `t_commit` | `CommitPolicy.step` | STRIKE |
| `t_audio_scheduled` | `AudioScheduler.schedule` | STRIKE |
| `t_audio_out_est` | `audio` (§5.3) | STRIKE |
| `t_audio_out`, `t_acoustic_onset` | **external measurement only** (Phase 18) | STRIKE, null otherwise |
| `t_impact_est` | `geometry` (observed crossing) | STRIKE (may be filled after the commit, for anticipatory commits, once the crossing is observed) |
| `t_impact_pred` | `geometry` (predicted crossing) | STRIKE |
| `t_impact_phys` | Phase 07 labelling from the optional pad + microphone condition (ADR-0002) | STRIKE, null otherwise |

One `TimingRecord(kind=FRAME)` per processed frame and one `TimingRecord(kind=STRIKE)` per `CommittedStrike` (shadow included). Latency components (README §5.3) and `L_sys`, `L_pred`, `TE_*` (README §5.4) are **derived** by `eval` from these fields and are never stored; no sum is reported without its term list.

**Estimated vs measured (gate review, 2026-09-21).** README §5.2's single symbol `t_audio_out` admits two provenances; this architecture keeps them in two fields. `t_audio_out_est` (software placement instant + the MEASURED `L_out` of the audio profile) may only feed quantities named with the `_est` suffix and labelled *software-estimated* (`L_sys_est`, `TE_audio_est`); `L_sys` and `TE_audio` without suffix require the externally measured `t_audio_out` or `t_acoustic_onset` (Phase 18). `L_pred` uses no audio timestamp. `L_eff` stays conceptual and is never computed from `_est` values. Full rule table: `contracts.md` §3.10.

**Rule:** every record carries the `t_capture` of the frame it derives from (schema-enforced), so any record can be joined to its frame and to `TimingRecord` without ambiguity.

---

## 6. Per-hand state ownership (Task 01.4; ADR-0006)

### 6.1 Ownership table

Each of `tracking`, `features`, `prediction`, `commit` instantiates **one state object per hand**, keyed by `hand_id ∈ {LEFT, RIGHT}`, created at session start and living for the session. Every state object exposes `reset(reason: ResetReason)` and `status` (README §8).

| Module | Per-hand state object | Contents | `status` source |
|---|---|---|---|
| `tracking` | `TrackerState[h]` | filter state (position/velocity/acceleration estimates, covariance or equivalent), causal history window of the last `N` `TrackState`s, `frames_since_valid`, `last_valid_t` | computed here (README §8 thresholds `c_valid`, `c_min`, `g_max`, `age_max` from config) |
| `features` | `FeatureState[h]` | rolling buffers needed for causal features (previous values for finite differences, window statistics) | mirrors `TrackState.status` |
| `prediction` | `AnticipatorState[h]` | rule-based: none beyond the history it reads; learned: model hidden state (GRU) or input window (TCN/GBDT), normalisation stats id | mirrors `TrackState.status` |
| `commit` | `CommitState[h]` | commit FSM state (IDLE/ARMED/COMMITTED/REFRACTORY per zone), pending `ARMED` candidates, per-(hand, zone) `refractory_until`, per-hand last-commit time, current episode ids per zone | reads `TrackState.status` as a safety gate |

`geometry` is stateless except for **entry-episode bookkeeping**, which is keyed by `(hand_id, zone_id)` and owned by `geometry` (Phase 04, Task 04.4); it is listed in the reset matrix because episodes end on tracking loss.

### 6.2 Reset matrix (state × trigger → action)

Triggers (`ResetReason`): `GAP_EXCEEDED` (→ INVALID), `LOW_CONFIDENCE` (→ INVALID), `STALE`, `MANUAL`, `ARM_SWITCH`, `CONFIG_RELOAD`, `SESSION_START`. Re-acquisition (`INVALID/STALE → VALID`) is not a reset; it is listed for completeness.

| State element | → `INVALID` (`GAP_EXCEEDED`, `LOW_CONFIDENCE`) | → `STALE` | `MANUAL` / `SESSION_START` | `ARM_SWITCH` | `CONFIG_RELOAD` | Re-acquired (`→ VALID`) |
|---|---|---|---|---|---|---|
| Tracker filter state | **reset** (re-initialised from the next VALID observation) | reset | reset | keep | reset | initialise from observation |
| Tracker history window | **cleared** | cleared | cleared | keep | cleared | starts refilling |
| `frames_since_valid` | counts up | counts up | 0 | keep | 0 | 0 |
| `last_valid_t` | keep (used for STALE decision) | keep | null | keep | null | updated |
| Feature buffers | **cleared** | cleared | cleared | keep | cleared | refill; `mask=false` until full |
| Model hidden state / input window | **reset** | reset | reset | reset (new arm) | reset | warm-up from scratch; predictions withheld until the window has ≥ `N_min` VALID frames (tunable) |
| Commit FSM (IDLE/ARMED/…) | → **IDLE**; pending `ARMED` candidates **discarded** | → IDLE, discarded | → IDLE | → IDLE (no cross-arm carry-over) | → IDLE | stays IDLE until a new candidate |
| Per-(hand, zone) `refractory_until` | **persists** | persists | cleared on `SESSION_START`; **persists** on `MANUAL` | **persists** | persists | persists — a re-acquired hand cannot immediately re-trigger the same zone |
| Per-hand last-commit time | persists | persists | cleared on `SESSION_START` | persists | persists | persists |
| Geometry entry episodes for hand `h` | **closed** (episode ends on loss, Phase 04) | closed | closed | keep | closed | new episode on next valid entry |
| Ids (candidate/strike/episode counters) | persist | persist | persist within session | persist | persist | persist |

Rules encoded by the matrix (Q34–Q35):

- No history, filter or model state survives a transition to `INVALID`/`STALE`, so nothing can be extrapolated across a loss period: **the system never fabricates a strike during tracking loss** — `CommitPolicy` refuses every candidate while `status ∉ {VALID}` (or `{VALID, DEGRADED}` only when `allow_degraded_commits` is true, an explicit experiment).
- Refractory timers are the only state that persists across resets, and only in the safe direction (they can suppress, never create, a commit).
- `DEGRADED` bridging uses existing state only, for at most `g_max` frames (config), and never future frames — the causal one-step bridge is itself subject to `TEST-CAUSAL-1`.
- `reset_reason` is written into the `TrackState` of the frame where the reset happened, so a replay can prove where resets occurred.

---

## 7. Threading / process model — candidates (Pending Architecture Decision, Phase 16)

The contracts must survive any of the candidates below; this is guaranteed by requiring every record to be **serialisable** (JSON-representable; `image_ref` instead of arrays) and every interface to be **message-shaped** (§11).

| Candidate | Description | When chosen |
|---|---|---|
| **T1 — baseline** | *Capture thread*: pulls frames, stamps `t_capture`/`t_frame_available`, pushes into a bounded queue (`max_frames` tunable, **drop-oldest**, drops counted in `dropped_since_last`). *Processing loop* (main thread): hands → stick → tracking → features → prediction → geometry → commit for both hands, per frame. *Audio callback thread*: owned by the audio library; consumes a lock-free queue of `AudioEvent`s with target times. | Default from Phase 02/05. |
| **T2 — inference worker** | T1 + a worker thread for `Anticipator.predict` **only if** inference does not fit the frame budget on the main loop. The worker receives an immutable snapshot of the per-hand history (frames already delivered) and returns a `TrajectoryPrediction` tagged with the `frame_id` it saw; the main loop uses it only if that `frame_id` is the latest processed one, otherwise it is logged as late. | Phase 13/16, on measured need. |
| **T3 — perception process** | `hands`/`stick` in a separate process (shared-memory frames; records over a pipe) to escape the GIL. Timestamps are created only in the capture process (§5.1). | Phase 16, on measured need; requires the cross-process clock benchmark. |

Invariants for all candidates: (i) latency never accumulates — the queue drops rather than buffers; (ii) causality: a worker only ever sees frames already delivered to the main loop, and `TEST-CAUSAL-1` is re-run in live mode after any threading change (Phase 13, Task 13.6; Phase 16); (iii) `t_capture` ordering: the processing loop processes frames in `frame_id` order and never reorders.

Python GIL implications, per-stage costs and the drop policy's effect on effective frame rate are **Pending Benchmark** (Phases 02/16).

---

## 8. Latency-budget slots (Pending Benchmark)

Named slots whose costs are measured from Phase 02 onward and whose targets are **To Be Experimentally Determined** in Phase 16. Frame period at a *requested* 30 FPS is ≈ 33.3 ms and at 60 FPS ≈ 16.7 ms — **arithmetic, not a measurement**.

| Slot | Timestamp span | Measured in | Target |
|---|---|---|---|
| `capture` | `t_frame_available − t_capture` | Phase 02 | Pending Benchmark |
| `hands` | part of `t_tracking_done − t_frame_available` (per-stage stamps in Phase 03 profiling) | Phase 03 | Pending Benchmark |
| `stick` | idem | Phase 03 | Pending Benchmark |
| `tracking` | idem | Phase 03 | Pending Benchmark |
| `features` | `t_features_done − t_tracking_done` | Phase 08/13 | Pending Benchmark |
| `prediction` | `t_inference_done − t_features_done` | Phase 05 (rule), 10/13 (model) | Pending Benchmark |
| `geometry+commit` | `t_commit − t_inference_done` | Phase 05 | Pending Benchmark |
| `audio_dispatch` | `t_audio_scheduled − t_commit` | Phase 05 | Pending Benchmark |
| `audio_out` | `t_audio_out − t_audio_scheduled` (measured `L_out`) | Phase 04 | Pending Benchmark |

No sum of slots is called "total latency" unless the term list is printed next to it (README §5.3).

---

## 9. Coordinate convention (ADR-0005)

- Image plane only; no depth in V1 (Q21; REQ-206). Positions are `[x, y]` with exactly two components in schema 1.x.
- ROI-normalized: `(x, y) = ((x_px − roi.x) / roi.w, (y_px − roi.y) / roi.h)`, origin top-left, **y increases downward**. "Downward/inward" for a drum-like zone therefore means increasing `y`; the zone's `inward_normal` makes this explicit per zone so nothing hard-codes "down" (Phase 04).
- Velocities are ROI-normalized units per second; the ROI aspect ratio is recorded (`roi_px`) so pixel-space or metric-space reporting can be derived. Angles are radians from `+x` towards `+y`.
- `hands` converts the landmark library's native coordinates to ROI-normalized at its boundary (Phase 01 risk mitigation); no other module sees library coordinates.
- Every pixel-space figure in a report states the ROI size and the camera profile.

---

## 10. Zone-registry extensibility (Task 01.8; ADR-0011)

- `Zone.trigger_type ∈ {HAND_TIP}` in schema 1.0. The enum is declared **open**: `FOOT` is reserved (`OOS-REF:REQ-207`) and would be added by a schema-version bump + ADR + scope expansion per `out-of-scope.md` §2 — never by editing the enum in place.
- `geometry.intersect` is generic over "a trajectory of a tracked point": its input is `Trajectory{point_id, samples[(t, p)], kind}`; `point_id` is `LEFT`/`RIGHT` in V1, with `LEFT_FOOT`/`RIGHT_FOOT` reserved names. Nothing in geometry assumes the point is a stick tip.
- Zones are **hand-agnostic** (Q11): `allowed_hands` is optional, defaults to `[LEFT, RIGHT]`, and is reserved for Phase 18 experiments; restricting it in V1 requires an ADR.
- Zone ids are stable strings (ADR-0003); a future `kick` id is reserved in the registry design (Phase 04) without a layout entry, a sample, or a trigger.
- `SessionMetadata` and `LabelRecord` (Phases 06/07) inherit the same `trigger_type`/`point_id` vocabularies so a dataset could later carry foot labels without a format change beyond the enum bump.

---

## 11. Pluggable interfaces (Task 01.5)

Interfaces are written as Python `Protocol`s in `spacedrums.contracts.interfaces` (first code in Phase 02/03). The signatures below are normative; names, argument order and return types may not change without an ADR. All arguments are records from `contracts.md`; **no interface has a look-ahead argument** — there is no way to pass future frames.

```python
class TipEstimator(Protocol):
    method_id: TipMethod                                    # GEOM | AXIS_REFINED | MARKER
    def estimate(self, frame_roi: FrameView, hand_obs: HandObservation) -> StickObservation: ...
    # Pure per-frame function of (frame, hand observation). Must return a StickObservation
    # with present=False rather than raise when the hand is absent.

class Tracker(Protocol):
    tracker_id: str
    def update(self, hand_obs: HandObservation, stick_obs: StickObservation,
               t_capture: float) -> TrackState: ...        # causal; one call per frame per hand
    def reset(self, reason: ResetReason) -> None: ...
    @property
    def history(self) -> Sequence[TrackState]: ...         # last ≤ N states, oldest first, all t_capture ≤ current

class Anticipator(Protocol):
    anticipator_id: str
    model_hash: str | None
    def predict(self, track_history: Sequence[TrackState],
                features: KinematicFeatures | None) -> TrajectoryPrediction | None: ...
    # Rule-based (B) and learned (C-*) implementations share this. Returns None when it
    # declines to predict (insufficient history, status not VALID/DEGRADED, warm-up).
    def reset(self, reason: ResetReason) -> None: ...

class DirectAnticipator(Protocol):                         # DIAGNOSTIC ONLY (gate review 2026-09-21)
    anticipator_id: str
    model_hash: str                                        # never None: learned models only
    def predict_direct(self, track_history: Sequence[TrackState],
                       features: KinematicFeatures | None) -> DirectPrediction | None: ...
    # Implemented only by models evaluated in Phase 09 direct mode / Phase 19 AB-NOTRAJ.
    # Called only by the harness's direct-head adapter, which emits
    # StrikeCandidate(source=MODEL, derivation=DIRECT_HEAD) without geometry. Never wired
    # into the live application; the same causal input as Anticipator.predict; passes TEST-CAUSAL-1/2.

class Geometry(Protocol):
    def intersect(self, trajectory: Trajectory, source: CandidateSource) -> list[StrikeCandidate]: ...
    # Deterministic. Trajectory = {point_id, kind: OBSERVED|PREDICTED, samples: [(t, p), ...]}.
    # Applies the impact convention (first valid downward/inward entry per episode) and
    # sub-frame crossing interpolation identically for every source. Every candidate it
    # returns has derivation = GEOMETRY. A sparse predicted trajectory (t_offsets_s set) is
    # intersected as the polyline given; it is never densified.

class CommitPolicy(Protocol):
    commit_policy_id: str
    def step(self, candidates: Sequence[StrikeCandidate], track_state: TrackState,
             t_now: float) -> list[CommittedStrike]: ...   # per hand, per frame
    def reset(self, reason: ResetReason) -> None: ...      # per the reset matrix (§6.2)

class AudioScheduler(Protocol):
    audio_profile_id: str
    def schedule(self, committed: CommittedStrike) -> AudioEvent: ...
    # Shadow commits are never passed here (app-level rule); audio has no arm knowledge.

class FrameSource(Protocol):                               # record/replay symmetry (§12)
    def __iter__(self) -> Iterator[FrameSample]: ...       # LiveFrameSource | ReplayFrameSource
```

Every later phase's implementation states which interface it implements and passes the shared **conformance suite** (`TEST-CONFORM-*`, `causality-tests.md` §4): returns the correct record type, respects `hand_id`, never raises on `INVALID` input, is causal (`TEST-CAUSAL-1/2`).

---

## 12. Recording / replay symmetry (Task 01.9)

### 12.1 Principle

The live pipeline and the offline pipeline are **the same module code** driven by different `FrameSource`s:

- `LiveFrameSource` — the capture thread (§7).
- `ReplayFrameSource` — reads a recorded session and yields `FrameSample`s with their **original** `t_capture`/`t_frame_available` (`timestamp_source = REPLAY`), in `frame_id` order, with the recorded `dropped_since_last`.

The processing loop cannot tell them apart. Processing-done stamps (`t_tracking_done`, …) are re-stamped live during replay; therefore latency *components* differ between live and replay, but every **decision** (`TrackState`, `KinematicFeatures`, `TrajectoryPrediction`, `StrikeCandidate`, `CommittedStrike` sets) must be identical up to the documented tolerance — that is `TEST-PARITY-1`. For commit decisions that depend on `t_now`, replay uses `t_now = t_capture + Δ_proc` with `Δ_proc` set to a documented constant or to the live measured processing delay (Phase 09/13 define the value and label it).

### 12.2 Record mode

The live app (Phase 05) can run in *record mode*, persisting into `data/sessions/<session_id>/`:

| Path | Content | Raw or derived |
|---|---|---|
| `video.<ext>` | every delivered frame (full frame by default; `image_ref.crop` says which) — **authoritative** | raw |
| `frames.jsonl` | one `FrameSample` per frame with `image_ref.kind = FILE` | raw (timestamps cannot be regenerated) |
| `records/<RecordType>.jsonl` | header line (`RecordStreamHeader`) + one record per line, for every record type produced | **derived** — regenerable |
| `timing.jsonl` | `TimingRecord`s (FRAME and STRIKE) | derived (live stamps; historical, not regenerable identically) |
| `audio_track.<ext>` | optional microphone track for the practice-pad condition (ADR-0002) | raw |
| `config.snapshot.yaml` + `config_hash` | resolved config in force | provenance |
| `session.json` | Phase 05 developer-session provenance (arm, source, counters) — **not** the `SessionMetadata` | provenance |
| `metadata.json` | `SessionMetadata` (Phase 06, `schemas/session-metadata.schema.json`, ADR-0019): session kind, participant pseudonym, protocol version + seed, segment markers on `t_capture`, pad/mic block, `has_phys_gt`, consent status | provenance |
| `verify.json`, `checklist.json`, `audio_track.wav` | Phase 06 verification document, operator checklist, optional microphone track (ADR-0002) | derived / provenance / raw |

Rules: dropped frames are not recorded (there is nothing to record) but their count is; a record stream is written even when empty (header only) so absence is explicit; the video encoder must be lossless or its codec/parameters recorded in `SessionMetadata`, because tracking results depend on it (Phase 06 decision, recorded there).

### 12.3 Regeneration

Derived records can be regenerated from `video.<ext>` + `frames.jsonl` + a config + a code version by running the causal pipeline through `ReplayFrameSource`. The regenerated streams carry `producer = REGENERATED` and the `git_sha`/`config_hash` that produced them. `eval` (Phase 09) always regenerates rather than trusting recorded derived records when the code or config differs from the recording's.

### 12.4 Tests

`TEST-PARITY-1` (`causality-tests.md` §3) — executed in Phase 13; an informal replay-determinism check already in Phase 05 (Task 05.5).

---

## 13. Causality contract (Task 01.6)

Stated in `causality-tests.md` §1 with the two tests every causal component must pass:

- **`TEST-CAUSAL-1` — future-perturbation invariance:** outputs up to frame `i` are unchanged when frames `> i` are replaced by garbage or removed.
- **`TEST-CAUSAL-2` — history-truncation monotonicity:** outputs at frame `i` depend only on frames within the declared window `N`.

The harness (Phase 09) runs both on every `Tracker`, `Anticipator`, feature implementation, the commit policy and the simulator itself; Phase 13 re-runs `TEST-CAUSAL-1` in live-replay mode.

---

## 14. Configuration (Task 01.7; ADR-0010)

One resolved document validated against `configs/schema/config.schema.json` before any computation; hashed into `config_hash` (reproducibility policy §3). Blocks: `meta`, `camera_profile`, `roi`, `zones[]`, `tracking`, `anticipator`, `commit`, `audio`, `debug`, optional `arms`. Every numeric value is tunable and a candidate until a phase freezes it with evidence; a measured native FPS cannot appear without its `run_id` (schema-enforced). Example: `configs/example.candidate.yaml`.

---

## 15. What this phase deliberately leaves open

| Item | Marker | Resolved in |
|---|---|---|
| Threading vs multiprocessing for `hands`/`stick` | Pending Benchmark | Phase 16 |
| Whether `DEGRADED` commits are ever allowed | To Be Experimentally Determined | Phase 05/17 |
| Per-step uncertainty in `TrajectoryPrediction` in V1 | Open Question (field reserved, nullable). *(Phase 12, ADR-0034)* development layouts and probabilistic geometry IMPLEMENTED; V1 use PENDING the participant go/no-go | Phase 12 re-gate (participant CV) / Phase 13 |
| `Δ_proc` policy for replayed commit decisions | Pending Architecture Decision | Phase 09 (define), 13 (validate) |
| Filter family, tip method, model family, thresholds | not chosen here (interfaces only) | 03, 03, 10–13, 05/09/18 |
| Lossless vs lossy recording codec | Pending Architecture Decision | Phase 06 |
| Cross-process clock consistency | Pending Benchmark | Phase 16 |

---

## 16. Requirement traceability

| REQ | Where satisfied in this specification | Verification |
|---|---|---|
| REQ-001 (system + contribution) | §1 pipeline; §4 source abstraction; §11 interfaces | review (this gate) |
| REQ-004 (launch-to-sound flow, contributes) | §3 pipeline order; `ui` stand-here guide (Phase 02); zones displayed (Phase 04) | system test (05/20) |
| REQ-021 (no depth) | §9; `point2` = 2 components (`common.schema.json`) | review; schema test |
| REQ-033 (per-hand independence) | §3, §6 (ownership + reset matrix); ADR-0006 | review (01); test (03) |
| REQ-051 (single user) | §2 `hands` assigns exactly LEFT/RIGHT; no multi-user state anywhere; extra hands are rejected in Phase 03 | review |
| REQ-052 (fully local) | §2 no module has a network dependency; `anticipator.model.path` is a local file with hash; `onnxruntime` Azure provider forbidden (`environment.md`) | review (01); test (13/23) |
| REQ-055 / REQ-207 (kick not impossible, not built) | §10; ADR-0011; `trigger_type` enum + `OOS-REF` tags | review; schema test (FOOT rejected) |
| REQ-060b / REQ-302 (causal) | §5, §11 (no look-ahead argument), §13; `causality-tests.md` | tests `TEST-CAUSAL-1/2` (03, 05, 08, 09, 10, 13, 17) |
