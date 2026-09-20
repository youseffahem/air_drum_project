# Space Drums — Phase Roadmap

> Official implementation and research roadmap for the Space Drums graduation project.
> Primary requirements source: [`../project-discovery.md`](../project-discovery.md).
> Every phase document in this directory is **PLANNED**. Nothing described here is implemented, measured, or validated unless a later revision of the phase document says so with evidence.

---

## 1. Project Summary

Space Drums is a software-only virtual/air drumming system. The user holds two **ordinary physical drumsticks** (no IMUs, no ESP32, no sensors, no required markers). A **single webcam** observes a **fixed playing area**. The system detects hand landmarks and the stick visually, estimates the stick axis and stick tip, tracks the tip causally per hand, extracts kinematic features, **predicts the future tip trajectory**, intersects that predicted trajectory with **fixed virtual drum zones**, derives a predicted strike and Time-to-Impact, applies commit / refractory / duplicate-suppression logic, and schedules a local drum sample.

**Research question (from `project-discovery.md`):**

> Can a small causal temporal model predict the future trajectory and imminent virtual impact of an ordinary drumstick early enough to reduce effective Action-to-Sound Latency compared with reactive impact detection, while maintaining acceptable false-positive and timing-error behaviour?

**Core research contribution:** Causal Temporal Strike Anticipation — *trajectory first*:

```
Past Motion → Causal Temporal Model → Future Stick Trajectory → Virtual Drum Geometry
→ Predicted Intersection → Predicted Strike → Time-to-Impact → Audio Scheduling
```

The neural model is **never** reduced to a bare "strike = yes/no" classifier. It predicts future motion; deterministic geometry decides whether that motion reaches a zone; post-processing decides whether to commit; audio schedules the sample.

---

## 2. Phase Index

| # | Phase | File | One-line goal | Depends on |
|---|-------|------|---------------|------------|
| 00 | Project Definition & Environment | [phase-00-project-definition.md](phase-00-project-definition.md) | Freeze requirements traceability, environment, integrity policy | — |
| 01 | System Architecture & Contracts | [phase-01-system-architecture.md](phase-01-system-architecture.md) | Module boundaries, data contracts, causality contract | 00 |
| 02 | Camera Capture & CV Prototype | [phase-02-camera-capture.md](phase-02-camera-capture.md) | Timestamped capture, native-FPS measurement, playing ROI | 01 |
| 03 | Hand / Stick Tracking | [phase-03-hand-stick-tracking.md](phase-03-hand-stick-tracking.md) | Per-hand landmarks, markerless stick axis/tip, causal tracking | 02 |
| 04 | Virtual Drum Geometry & Audio Engine | [phase-04-drum-geometry-audio.md](phase-04-drum-geometry-audio.md) | Zones, impact surfaces, sub-frame crossing, sample scheduling | 01 |
| 05 | Rule-Based Baseline & First Playable Prototype | [phase-05-rule-based-baseline.md](phase-05-rule-based-baseline.md) | Baselines A & B, commit logic, playable MVP | 03, 04 |
| 06 | Data Collection Pipeline | [phase-06-data-collection.md](phase-06-data-collection.md) | Recording tool, protocol, metadata, unusable-recording policy | 05 |
| 07 | Dataset Creation & Labelling | [phase-07-dataset-labeling.md](phase-07-dataset-labeling.md) | Labelling rules, QC, participant-level splits, dataset freeze | 06 |
| 08 | Feature Engineering | [phase-08-feature-engineering.md](phase-08-feature-engineering.md) | Causal kinematic feature schema and leakage tests | 07 |
| 09 | Baseline ML Model & Evaluation Harness | [phase-09-baseline-ml.md](phase-09-baseline-ml.md) | Causal replay simulator, canonical metrics, GBDT baseline | 08 |
| 10 | Temporal AI / Future Trajectory Prediction | [phase-10-temporal-ai.md](phase-10-temporal-ai.md) | **Core research phase:** GRU/TCN trajectory prediction → geometry → strike | 09 |
| 11 | Multi-Task Prediction: TTI, Zone & Intensity | [phase-11-multitask-prediction.md](phase-11-multitask-prediction.md) | Shared encoder + task heads, per-task evaluation | 10 |
| 12 | Trajectory Prediction Extensions | [phase-12-trajectory-extensions.md](phase-12-trajectory-extensions.md) | Optional: longer horizon, attention, uncertainty | 10 (11 optional) |
| 13 | Real-Time Inference Integration | [phase-13-realtime-inference.md](phase-13-realtime-inference.md) | Live causal inference, fallback, offline/online parity | 05, 10 (11/12 optional) |
| 14 | Calibration | [phase-14-calibration.md](phase-14-calibration.md) | Calibration wizard: playing area, zones, mappings | 13 |
| 15 | Visualization / Debug Dashboard | [phase-15-debug-dashboard.md](phase-15-debug-dashboard.md) | Developer overlay exposing all internal states | 13 |
| 16 | Performance Optimization | [phase-16-optimization.md](phase-16-optimization.md) | Profiling, threading, native 60 FPS attempt, model cost | 13, 15 |
| 17 | Testing, Hardening & Failure Handling | [phase-17-testing-hardening.md](phase-17-testing-hardening.md) | Failure injection, invariants, soak tests | 16 |
| 18 | Evaluation & Experiments | [phase-18-evaluation-experiments.md](phase-18-evaluation-experiments.md) | Pre-registered A vs B vs C comparison, live end-to-end timing | 09, 10, 11, 13, 14, 17 |
| 19 | Ablation Study | [phase-19-ablation-study.md](phase-19-ablation-study.md) | Feature/history/horizon/architecture ablations | 18 |
| 20 | Final Integration & Release Candidate | [phase-20-final-integration.md](phase-20-final-integration.md) | Frozen configs/models, RC build, regression | 14–19 |
| 21 | Documentation & Thesis Material | [phase-21-documentation-thesis.md](phase-21-documentation-thesis.md) | Thesis chapters, claims audit, dataset card | 18, 19, 20 |
| 22 | Graduation Demo Preparation | [phase-22-graduation-demo.md](phase-22-graduation-demo.md) | Demo script, environment checklist, fallbacks | 20, 21 |
| 23 | Final Packaging & Release | [phase-23-final-packaging.md](phase-23-final-packaging.md) | Installable bundle, archive, final status table | 21, 22 |

Total: **24 phases** (00–23).

---

## 3. Dependency Graph

```
00 ── 01 ──┬── 02 ── 03 ──┐
           │              ├── 05 ── 06 ── 07 ── 08 ── 09 ── 10 ──┬── 11 ──┐
           └── 04 ────────┘                                      │        ├── 12 (optional)
                                                                 │        │
                       05 ─────────────────────────────── 13 ◄───┴────────┘
                                                          │
                                        ┌──────┬──────────┼──────────┐
                                       14     15 ── 16 ── 17        │
                                        │              │            │
                                        ├──── 09/10/11/13/14/17 ── 18 ── 19
                                        │                          │    │
                                        └────────── 20 ◄───────────┴────┘
                                                    │
                                                   21 ── 22 ── 23
```

Reading rule: an arrow means "must have passed its Exit Gate before the target phase starts". Phases 14 and 15 may run in parallel after 13. Phase 12 is optional and may be skipped with written justification (see its document).

---

## 4. Status Vocabulary (mandatory in every document and every claim)

| Label | Meaning |
|-------|---------|
| **PLANNED** | Described in a phase document; no code, data, or measurement exists. |
| **IMPLEMENTED** | Code exists, tests exist and pass, but no quantitative measurement has been recorded. |
| **MEASURED** | A quantity has been recorded with a documented method, date, hardware, and configuration. |
| **VALIDATED** | A measured result has been reviewed, reproduced (same data, same config, same seed where applicable), and accepted against the phase's acceptance criteria. |
| **PENDING** | Blocked on a dependency, decision, or benchmark. |

For experimental claims the following four-way distinction from `project-discovery.md` Q60 is also mandatory: **Target** (what we aim for) / **Measured** (what was recorded) / **Historical** (an earlier measurement, superseded) / **Pending** (not yet measured).

Markers for undecided items (use exactly these strings):

- `Open Question` — a design/scope question that needs a human decision.
- `To Be Experimentally Determined` — a value that must come from an experiment on real data.
- `Pending Benchmark` — a value that must come from a hardware/system benchmark.
- `Pending Architecture Decision` — a technical choice deferred to a named phase.

Rule: **no number appearing in a phase document is a result.** All numbers are either quoted from `project-discovery.md` (30 FPS baseline, 60 FPS target, ~4 MVP zones, ~7 V1 zones, 10–12 participants, 1–2 sessions, 100–300 ms tracking-loss example) or explicitly marked as *candidate*, *sweep value*, or *tunable*.

---

## 5. Timestamp & Latency Taxonomy (canonical)

All phases use the definitions below verbatim. Phases 04, 05, 09, 13, 16 and 18 must not redefine them.

### 5.1 Clock

- One **monotonic clock** (`t_mono`) is the reference for every timestamp in the system.
- Camera driver timestamps are mapped onto `t_mono` by the capture module (Phase 02, Task 02.2). The mapping method and its residual uncertainty are recorded as a **Measured** quantity in the camera profile.
- Audio device time is mapped onto `t_mono` by the audio engine (Phase 04, Task 04.7).

### 5.2 Per-event timestamps

| Symbol | Definition |
|--------|-----------|
| `t_capture` | Camera exposure/capture instant of a frame, on `t_mono`. |
| `t_frame_available` | Instant the frame is handed to the application. |
| `t_tracking_done` | Instant hand + stick tracking for that frame finishes. |
| `t_features_done` | Instant kinematic features for that frame are ready. |
| `t_inference_done` | Instant the temporal model (or rule-based extrapolator) returns. |
| `t_candidate` | Instant a `StrikeCandidate` is emitted. |
| `t_commit` | Instant commit logic accepts the candidate (sound is now inevitable). |
| `t_audio_scheduled` | Instant the audio engine receives the play request (with its target time). |
| `t_audio_out` | Instant the first sample of the drum sound leaves the DAC (estimated from measured audio output latency, or measured externally). |
| `t_acoustic_onset` | Instant sound is detected by an external microphone. **Only exists when measured externally.** |
| `t_impact_est` | Estimated virtual impact time: sub-frame interpolated crossing time of the tracked tip through a zone's impact surface (Phase 04 geometry). This is the primary reference time for all timing metrics. |
| `t_impact_pred` | Predicted impact time emitted by an anticipatory source (rule-based or model) = `t_candidate_reference + TTI`. |
| `t_impact_phys` | Physical impact time. **Only exists in the optional practice-pad + microphone recording condition** (Phase 06/07). Never assumed otherwise. |

### 5.3 Latency components

| Component | Definition |
|-----------|-----------|
| Camera capture latency | `t_frame_available − t_capture` |
| Tracking latency | `t_tracking_done − t_frame_available` |
| Feature extraction latency | `t_features_done − t_tracking_done` |
| Model inference latency | `t_inference_done − t_features_done` |
| Commit latency | `t_commit − t_inference_done` |
| Audio scheduling latency | `t_audio_scheduled − t_commit` |
| Audio output latency | `t_audio_out − t_audio_scheduled` (DAC/buffer path; measured in Phase 04) |
| Frame-quantization delay (reactive path only) | `t_capture(first frame after crossing) − t_impact_est` |

No sum of these is called "total latency" unless the exact set of terms is listed next to the number.

### 5.4 Research latency definitions

- **`L_sys` — system / action-to-sound latency without anticipation.** For Baseline A (reactive): `L_sys = t_audio_out − t_impact_est`. It contains frame-quantization delay + capture + tracking + (feature) + commit + audio scheduling + audio output latency.
- **`L_pred` — useful prediction lead time.** For an anticipatory commit matched to a ground-truth impact: `L_pred = t_impact_est − t_commit`. Positive means the commit happened before the estimated impact. A commit with `L_pred ≤ 0` provides no anticipation benefit.
- **Effective (perceived) latency — conceptual only:** `L_eff ≈ max(0, L_sys − L_pred)`. This is a *conceptual relationship used to motivate the research*. It is **not** a result and must not be reported as one. Reduction of effective latency is only claimable after Phase 18 measures `t_audio_out` (or `t_acoustic_onset`) relative to `t_impact_est` (or `t_impact_phys`) for the anticipatory system.
- **Audio timing error:** `TE_audio = t_audio_out − t_impact_est` (signed; negative = sound before estimated impact). Reported where `t_audio_out` is measured or estimated with a documented method.
- **Predicted-impact timing error:** `TE_pred = t_impact_pred − t_impact_est` (signed).

---

## 6. Event Taxonomy (canonical)

| Term | Definition |
|------|-----------|
| **Trajectory** | The sequence of estimated stick-tip positions over time for one hand (observed = past; predicted = future). |
| **Zone entry** | Geometric event: the trajectory crosses a zone's impact surface from outside to inside. Any direction. |
| **Valid impact (strike)** | The **first** zone entry in an entry episode whose crossing velocity satisfies the downward/inward condition of Phase 04. Upward/random crossings are not strikes. |
| **Predicted impact** | A valid impact that an anticipatory source (Baseline B or temporal AI) predicts will occur at `t_impact_pred` with Time-to-Impact `TTI = t_impact_pred − t_now`. |
| **Estimated impact** | A valid impact computed from *observed* tip positions with sub-frame interpolation → `t_impact_est`. Used as reference truth in offline evaluation. |
| **Physical impact ground truth** | `t_impact_phys` from the optional practice-pad + microphone condition. Exists only where recorded. |
| **Committed strike** | A predicted or observed impact accepted by commit logic → a sound is scheduled. |
| **Time-to-Impact (TTI)** | `t_impact_pred − t_reference_frame_capture` at prediction time. |
| **Intensity proxy** | A kinematic quantity (candidate: tip speed component along the impact-surface inward normal at/near crossing). Explicitly **not** physical force. |

---

## 7. Coordinate Convention

- Image plane only; **no depth in V1** (`project-discovery.md` Q21).
- Playing ROI: a fixed rectangle in the camera frame (Phase 02). All downstream coordinates are **ROI-normalized** `(x, y) ∈ [0,1]²`, origin top-left, **y increasing downward**. "Downward" in the impact definition means increasing `y` in this frame.
- Pixel-space values may be reported alongside normalized ones for interpretability; both must state the ROI size in pixels and the camera profile.
- Zone geometry, tracking, features, prediction, and labels all use this convention.

---

## 8. Per-Hand Tracking State Machine

Each hand (`LEFT`, `RIGHT`) owns an independent **Tracking State**, **Kinematic State**, and **Prediction State** (`project-discovery.md` Q33).

| State | Meaning | Commits allowed? |
|-------|---------|------------------|
| `VALID` | Fresh observation this frame with confidence ≥ `c_valid` (tunable). | Yes |
| `DEGRADED` | Observation with confidence in `[c_min, c_valid)` **or** a causal one-step bridge over a gap of ≤ `g_max` frames (tunable) using existing state only. | Only if explicitly enabled and experimentally validated (Phase 05/17) — default **No** |
| `INVALID` | No usable observation for > `g_max` frames, or confidence < `c_min`. Predictor and feature history are reset. | **Never** |
| `STALE` | State object exists but its last valid time is older than `age_max` (tunable). Treated as `INVALID` for safety; requires re-acquisition. | **Never** |

Rule (`project-discovery.md` Q34–35): the system must never fabricate a strike during a tracking-loss period, and must never use future information to bridge gaps.

---

## 9. Baseline Naming

| Code | Name | Where defined | Source of `StrikeCandidate` |
|------|------|---------------|------------------------------|
| **A** | Reactive impact detection | Phase 05 | Observed crossing after it happens (`source = REACTIVE`) |
| **B** | Rule-based anticipation | Phase 05 | Causal constant-velocity / constant-acceleration extrapolation → geometry (`source = RULE`) |
| **C-GBDT** | Gradient-boosted tree baseline | Phase 09 | Learned, window features → outputs (`source = MODEL`) |
| **C-GRU / C-TCN** | Temporal AI (trajectory-first) | Phase 10 | Learned future trajectory → geometry (`source = MODEL`) |
| **C-MT** | Multi-task temporal AI | Phase 11 | As C-GRU/C-TCN with additional heads |
| **C-TT** | Tiny Transformer (optional) | Phase 12 | As above, only if computationally justified |

No winner is assumed. Phase 18's design must allow any of A, B, or C to come out best on any metric.

---

## 10. Canonical Metric Definitions

These definitions are implemented once in the Phase 09 evaluation harness and reused unchanged by Phases 10–19.

### 10.1 Event matching
- Performed **per hand**. Committed strikes `S` and ground-truth impacts `G` (from Phase 07 labels).
- Reference time of a committed strike: `t_impact_pred` for anticipatory sources; `t_impact_est` (as detected) for Baseline A.
- Greedy one-to-one matching by ascending `|t_ref(s) − t_impact_est(g)|`, accepting a pair only if the difference ≤ `W` (tolerance window, **tunable**; Phase 09 reports every metric for a sweep of `W` values and freezes the primary `W` before Phase 18).
- Zone agreement is **not** required for matching; it is reported as Zone Accuracy.

### 10.2 Metrics

| Metric | Definition |
|--------|-----------|
| **Prediction Lead Time (PLT / `L_pred`)** | `t_impact_est(g) − t_commit(s)` per matched pair. Report distribution (median, IQR, p10/p90) and fraction with `L_pred > 0`. |
| **False-Positive Rate** | `FP = |unmatched S|`. Report `FP / |S|` and `FP` per minute of active playing time. |
| **False-Negative Rate** | `FN = |unmatched G|`. Report `FN / |G|`. |
| **Timing Error** | `TE_pred = t_impact_pred − t_impact_est` per matched pair (signed; report MAE, bias, distribution). `TE_audio` where `t_audio_out` is available. |
| **Zone Accuracy** | Fraction of matched pairs with `zone(s) = zone(g)`. |
| **Trajectory Error** | Over a prediction horizon of `K` steps: `ADE = mean_k ‖p̂_k − p_k‖`, `FDE = ‖p̂_K − p_K‖`, in ROI-normalized units and pixels. **Impact-position error** = `‖x̂_impact − x_impact‖` for matched pairs. |
| **Intensity Proxy Agreement / Error** | Pearson `r`, Spearman `ρ`, and MAE between the predicted intensity proxy and the offline ground-truth proxy (Phase 07 definition). |
| **Inference Latency** | Wall-clock per call, batch size 1, on the named target CPU: p50 / p95 / p99, with model, input shape, runtime, and thread count recorded. |
| **End-to-End Latency** | Full decomposition table per §5.3 for a set of events; never a single undefined number. |
| **Effective Latency** | Only from external measurement in Phase 18 (`t_audio_out` or `t_acoustic_onset` vs. `t_impact_est` or `t_impact_phys`). |

### 10.3 Primary research analysis
The primary figure of the project is **Useful Prediction Lead Time vs. False-Positive behaviour**, produced by sweeping the commit threshold (and, where applicable, the prediction horizon) for each of A, B, and C, on held-out participants.

---

## 11. Technology Stack (candidates — confirmation is Phase 00, Task 00.3)

Decision recorded from the project owner: **Python-first**.

| Concern | Primary candidate | Alternatives to record in Phase 00 |
|---------|-------------------|------------------------------------|
| Camera capture | OpenCV (`cv2.VideoCapture`, backend per OS) | Platform SDK via `pyav`/`imageio-ffmpeg` if timestamps are unreliable |
| Hand landmarks | MediaPipe Hands (Hand Landmarker task) | Any CPU-capable 2-D hand-landmark model exposing 21 keypoints + handedness |
| Stick detection/segmentation | Classical CV (edge/line/PCA within hand-anchored ROI) first; lightweight learned segmentation if needed | Pending Benchmark (Phase 03) |
| Training | PyTorch | — |
| Inference | ONNX Runtime (CPU) or TorchScript | Pending Benchmark (Phase 13) |
| GBDT baseline | LightGBM or XGBoost | scikit-learn HistGradientBoosting |
| Audio | PortAudio-based library (e.g. `sounddevice`) with a callback-driven mixer | Pending Architecture Decision (Phase 04) if measured output latency is unacceptable |
| UI / overlay | OpenCV drawing for prototype; richer UI Pending Architecture Decision (Phase 15) | — |
| Config | Versioned YAML/JSON with schema validation | — |
| Experiment tracking | File-based manifests (JSON) + hashes; optional lightweight tracker | Pending Architecture Decision (Phase 00) |

The project is **CPU-first**. No GPU is assumed at inference time.

---

## 12. Scope Rules (from `project-discovery.md`)

Outside V1 scope: ESP32; IMU sensors; electronic stick hardware; multiple users; full-body tracking; mandatory depth estimation; foot/kick tracking; MIDI as a core requirement; cloud processing; mandatory visual markers.

- **Markerless tracking is primary.** Colored tape/markers are only a fallback or a benchmark/controlled experimental condition.
- **Kick is outside V1**, but the zone registry must not make a future kick zone impossible (Phase 01/04).
- **Single user, fully local, local drum samples.**
- **Either hand may hit any zone** unless experiments later show otherwise (Q11).

## 13. Research Integrity Rules (non-negotiable)

Never fabricate recordings, dataset samples, participants, labels, accuracy, FPS, latency, prediction lead time, experimental results, real-stick validation, or model performance. Never present a target as a measured result. Never present a hypothetical architecture as an implemented feature. Never claim a phase is complete without evidence. Never use future frames in causal evaluation. Never claim sound is guaranteed before physical impact without measurement. Always distinguish PLANNED / IMPLEMENTED / MEASURED / VALIDATED / PENDING.

**Causality rule (quoted in every phase that touches tracking, features, models, or evaluation):**
> Any component labelled *causal* consumes only observations with timestamp ≤ the current frame's `t_capture`. Offline *label generation* (Phase 07) may use the full recording and is therefore non-causal by design; this is documented and is the only place future information is permitted.

---

## 14. Glossary

| Term | Meaning |
|------|---------|
| ROI | Fixed playing region of interest in the camera frame. |
| Landmarks | 2-D hand keypoints (21 per hand in the MediaPipe convention). |
| Stick axis | Line (origin + unit direction) estimated along the drumstick in the image plane. |
| Stick tip | Estimated far end of the stick along the axis. |
| Tip-estimation method | One of `GEOM` (markerless geometric), `AXIS_REFINED` (visual axis refinement), `MARKER` (colored-marker fallback). |
| History window `N` | Number of past frames fed to a model (tunable). |
| Prediction horizon `H` / `K` | Future time span (`H`, seconds) / number of future steps (`K`) predicted (tunable). |
| TTI | Time-to-Impact. |
| Impact surface | Zone boundary segment/arc through which a valid entry must pass, with an inward normal. |
| Entry episode | Interval from a zone entry until the tip leaves the zone (or tracking is lost). One commit per episode. |
| Refractory period | Minimum time after a commit before the same hand may commit again to the same zone (tunable). |
| Intensity proxy | Kinematic stand-in for hit strength; not force. |
| Participant-level split | Train/validation/test partitions that never share a participant. |
| Causal replay simulator | Offline engine replaying recorded tracks frame by frame with past-only access and simulated timestamps (Phase 09). |
| Harness | The Phase 09 evaluation code implementing §10. |

---

## 15. How to Read a Phase Document

Every phase file has the same 25 sections in the same order. Tasks are numbered `XX.N` and referenced across phases as e.g. "Phase 04, Task 04.3". Each task states **What**, **Why**, **Depends on**, and **Evidence**. A phase is Done only when its *Definition of Done* is satisfied — code existing is never sufficient.
