# Requirements Traceability Matrix (RTM)

**Phase:** 00 — Task 00.1 · **Status:** PLANNED (this document; no requirement is yet IMPLEMENTED / MEASURED / VALIDATED)
**Source of truth:** [`../../project-discovery.md`](../../project-discovery.md) (Q1–Q60, Confirmed Core Architecture, Core Research Direction, Important Scope Rules, Current Project Philosophy).
**Roadmap:** [`../../phases/README.md`](../../phases/README.md).

## 1. How to read this matrix

- **One row per discovery answer** (Q1–Q60). Where one answer contains several independently verifiable requirements, the row is split into sub-IDs (`REQ-050a`, `REQ-050b`, …).
- **ID scheme (stable, machine-greppable):**
  - `REQ-001` … `REQ-060` ↔ discovery **Q1 … Q60** (the number *is* the question number).
  - `REQ-1xx` ↔ **Confirmed Core Architecture** pipeline stages + Core Research Direction.
  - `REQ-2xx` ↔ **Important Scope Rules** (out-of-scope items; detailed in [`out-of-scope.md`](out-of-scope.md)).
  - `REQ-3xx` ↔ **Current Project Philosophy** priorities.
- **Type:** `F` functional · `R` research (needs an experiment/measurement to answer) · `C` constraint (a rule the design must obey) · `X` out-of-scope (must *not* be built in V1).
- **Owning phase(s):** phase(s) whose Exit Gate is responsible for the requirement. The **first** listed phase is the primary owner. Phase `00` owns policy/paperwork requirements only.
- **Verification:** `test` (automated test in the owning phase) · `measurement` (a MEASURED quantity with method/hardware/date per README §4) · `review` (document/gate review) · `benchmark` (a comparative measurement between alternatives).
- **Status:** every row is **PLANNED** at the time of writing. Later phases update this column with evidence links; a row may only move to IMPLEMENTED / MEASURED / VALIDATED via a gate record in `docs/gates/`.
- Requirement text is quoted **verbatim or tightly paraphrased** from the discovery document; when in doubt the discovery document wins.

**Completeness rule (checked at every gate):** every Q# appears; every `REQ` has ≥ 1 owning phase; every phase document `phase-01 … phase-23` cites ≥ 1 `REQ` in its `## Inputs` section.

---

## 2. Discovery answers Q1–Q60

### A — Project Vision & Purpose

| Q# | REQ | Requirement (verbatim / tight paraphrase) | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|---|
| Q1 | REQ-001 | Software-only virtual drumming: single webcam + CV tracks **ordinary** drumsticks; estimates stick-tip motion; detects or predicts imminent virtual strikes; maps to zones; plays drum sounds in real time. Main contribution is Causal Temporal Strike Anticipation. | F/R | 01, 05, 13, 20 | review (01), system test (05, 13, 20) | PLANNED — P01 spec: `docs/architecture/architecture.md` §1, §4, §11 — gate pending |
| Q2 | REQ-002 | Allow playing a virtual kit without an electronic kit; research focus: reduce *perceived* Action-to-Sound Latency by predicting an imminent strike before the actual/virtual impact. | R | 10, 18 | measurement (18, external timing) | PLANNED |
| Q3 | REQ-003 | Primary user: beginners, students, hobbyists, users without a real kit, using ordinary sticks + webcam. | C | 06, 22 | review (protocol difficulty in 06; demo framing in 22) | PLANNED |
| Q4 | REQ-004 | Launch-to-first-sound flow: dedicated on-screen "stand here" area → detect/track hands + sticks → virtual zones displayed → user moves stick toward a zone → system estimates/predicts strike → commit → schedule → play sound. | F | 05, 02, 04, 14, 20 | system test (05, 20); test (02 guide, 04 zones) | PLANNED — P01: `architecture.md` §3; P02 contribution: stand-here guide `src/spacedrums/ui/guide.py` (`TEST-UI-1`, screenshot `docs/figures/phase-02/`) — gate pending |
| Q5 | REQ-005 | Contribution = causal temporal prediction of strikes from camera-derived hand/stick motion. Must clearly measure **Prediction Lead Time, Timing Error, False Positives**, and the effect of prediction on **Effective System Latency**. | R | 09, 10, 18 | measurement (harness 09; final 18) | PLANNED |
| Q6 | REQ-006 | Both research project and usable system; research is primary; system must be usable enough to demonstrate real-time virtual drumming. | C | 05, 20, 22 | review + system test | PLANNED |

### B — Drumming Experience

| Q# | REQ | Requirement | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|---|
| Q7 | REQ-007 | User holds **two** ordinary physical drumsticks, no electronic sensors attached. | C | 03, 05 | system test with real sticks (05) | PLANNED |
| Q8 | REQ-008 | Sticks contain **no** special hardware (no IMUs, ESP32, electronics). See REQ-201/202/203. | X | 00 (register), 03 | review | PLANNED |
| Q9 | REQ-009 | **Markerless tracking is the primary goal.** Colored tape/markers only as a fallback or benchmark condition if markerless proves unreliable. | C | 03, 18 | benchmark (03 tip-method comparison); review (labelling of marker condition, 18) | PLANNED |
| Q10 | REQ-010 | Both hands **and** sticks must be tracked; motion must be understood quickly enough to predict the upcoming strike. | F | 03 | test + measurement (tracking latency, 03) | PLANNED |
| Q11 | REQ-011 | Either hand may hit any zone, unless future experiments show hand–zone assignment improves reliability. | F | 04, 05, 18 | test (04/05: no hand–zone restriction); review (18: revisit) | PLANNED |
| Q12 | REQ-012 | Support individual hits, alternating R/L, repeated hits, rapid consecutive hits, and simultaneous / near-simultaneous hits when the pipeline can reliably support them. | F | 05, 06, 17 | system test (05); protocol coverage (06); failure-injection (17) | PLANNED |
| Q13 | REQ-013 | Target speed: realistic beginner/intermediate drumming. Max BPM / hit rate is **To Be Experimentally Determined** with real sticks. | R | 05, 18 | measurement | PLANNED |
| Q14 | REQ-014 | Intensity estimated from kinematics (e.g. velocity near predicted impact); explicitly an **intensity proxy**, not force; V1 maps it to volume / MIDI-like velocity. | F | 04, 07, 11 | test (04 gain mapping); review (07 GT-proxy definition); measurement (11 agreement) | PLANNED |
| Q15 | REQ-015 | Distinguish drum **zones**, not articulation types (rim/center/edge = future work unless research-relevant). | C | 04, 07 | review | PLANNED |

### C — Virtual Drum Kit

| Q# | REQ | Requirement | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|---|
| Q16 | REQ-016 | MVP ≈ **4 zones**; V1 target ≈ **7 zones**; exact final arrangement confirmed before implementation (→ ADR-0003). | F | 04, 14 | review (ADR-0003, zone layout config) | PLANNED |
| Q17 | REQ-017 | Initial kit: Snare, Hi-Hat, Tom 1, Tom 2, Floor Tom, Crash/Ride. Kick requires a separate decision (foot tracking out of V1). | F | 04 | review (zone registry contents) | PLANNED |
| Q18 | REQ-018 | Drum zones are initially **fixed**. | C | 04, 14 | test (zone geometry deterministic across a session) | PLANNED |
| Q19 | REQ-019 | User does **not** manually determine position; the system defines and displays the stand-here area directly in the webcam view. | F | 02, 14 | test (02 guide overlay; 14 fit check) | PLANNED — P02 evidence: `ui/guide.py` + `scripts/show_guide.py` (`TEST-UI-1`); ROI from config, no manual positioning — gate pending |
| Q20 | REQ-020 | Clear **geometric** zones and low-latency interaction first; realistic kit visuals may be added later **without changing the core Detection/Prediction architecture**. | C | 04, 15, 22 | review (architecture untouched by UI work) | PLANNED |
| Q21 | REQ-021 | **No depth estimation** in the initial version; 2-D camera coordinates + virtual geometry. Depth considered later only if experiments show necessity. | C | 01, 04 | review (coordinate convention README §7) | PLANNED — P01 spec: `architecture.md` §9, ADR-0005, `common.schema.json` point2 (2-D) — TEST-SCHEMA-1 pass 2026-09-20 — gate pending |

### D — Camera & Computer Vision

| Q# | REQ | Requirement | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|---|
| Q22 | REQ-022 | Initially the laptop's normal webcam; later upgrade to a stronger external camera or iPhone camera possible. | C | 02 | review (camera profile names the device) | PLANNED — P02 evidence: `docs/camera-profile-hw01-integrated-webcam.md` names the device/driver/backend; upgrade path §9 — gate pending |
| Q23 | REQ-023 | Baseline **30 FPS**; target **true 60 FPS** if camera + computer reliably support it. **Fake/interpolated FPS must never be presented as native FPS.** | C/R | 02, 16 | measurement (native FPS, 02; end-to-end 60 FPS attempt, 16) | PLANNED — P02 evidence: native FPS MEASURED per mode (camera profile §3, runs `p02-fps-*`); 60 FPS attempt measured as not delivered on HW-01; duplicate refusal (ADR-0013) — gate pending |
| Q24 | REQ-024 | Camera fixed (tripod or fixed position) for consistent geometry and tracking. | C | 02, 06 | review (placement in camera profile / session metadata) | PLANNED — P02 evidence: placement recorded in camera profile §7; tripod still an Open Question (`hardware-inventory.md`) — gate pending |
| Q25 | REQ-025 | User–camera distance determined by benchmarking; FOV must cover both hands and stick paths without excessive tracking-resolution loss. | R | 02, 03 | benchmark | PLANNED — P02: protocol `docs/protocols/camera-distance-benchmark.md` + `scripts/distance_benchmark.py`; visibility table PENDING (needs a person); tracking part Phase 03 — gate pending |
| Q26 | REQ-026 | Both hands + enough surrounding space visible; full-body tracking **not** required; kick/foot later if needed. | C | 02 | review (ROI definition) | PLANNED — P02 evidence: fixed ROI `configs/camera/hw01-integrated-webcam.candidate.yaml` `roi.px` (candidate) + guide band — gate pending |
| Q27 | REQ-027 | Support normal indoor lighting; test under **multiple realistic lighting conditions**, not lab lighting. | C/R | 02, 06, 17, 18 | measurement (lighting conditions recorded per session; robustness tests) | PLANNED — P02: `docs/protocols/lighting-checklist.md` (L1–L5), exposure procedure; low-light frame-rate cap MEASURED (camera profile §5) — gate pending |
| Q28 | REQ-028 | Background need not be controlled; clutter and occlusion considered during evaluation. | C | 06, 17, 18 | measurement (background variation in dataset; failure injection) | PLANNED |
| Q29 | REQ-029 | Preferably stable with people/objects in background; multi-person interaction **out of scope**; testing includes realistic background variation. | F | 03, 17 | test (17 background-person injection) | PLANNED |
| Q30 | REQ-030 | Ordinary drumstick colours supported (markerless); coloured tape only fallback/benchmark. | C | 03 | benchmark | PLANNED |

### E — Stick Tracking

| Q# | REQ | Requirement | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|---|
| Q31 | REQ-031 | Tip detection = Hand Landmarks (primary reference) + Visual Stick Segmentation → Stick Axis Estimation → Tip Estimation. Implementation modular so Markerless Geometric, Visual Axis Refinement, and marker-based fallback can be **compared**. | F | 03 | benchmark (`TipEstimator` methods vs reference) | PLANNED |
| Q32 | REQ-032 | Assume a natural grip; allow reasonable variation in grip and stick orientation. | C | 03, 06 | test (03); protocol (06 records grip variation) | PLANNED |
| Q33 | REQ-033 | Automatically identify left/right hands; **each hand has independent Tracking, Kinematic, and Prediction State**. | F | 01, 03 | review (01 contracts); test (03) | PLANNED — P01 spec: `architecture.md` §3, §6 (ownership + reset matrix), ADR-0006 — gate pending |
| Q34 | REQ-034 | Tolerate short tracking interruptions using the available **causal** state when safe; **never use future information**; reset Predictor/Feature History when tracking becomes invalid or stale. | F | 03, 17 | test (causality invariance, README §13; state-machine tests) | PLANNED |
| Q35 | REQ-035 | On tracking loss of ~100–300 ms: enter safe **Invalid** state; reset history when necessary; re-enable prediction when valid tracking returns; **never fabricate a strike** during loss. | F | 03, 05, 17 | failure-injection test (17); test (03/05) | PLANNED |

### F — Impact & Strike Definition

| Q# | REQ | Requirement | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|---|
| Q36 | REQ-036 | A strike = the **first valid downward/inward entry or crossing** of the estimated tip trajectory through the boundary/interior of a zone, per the project's impact convention. | F | 04 | unit test | PLANNED |
| Q37 | REQ-037 | Downward/inward entry is required; arbitrary upward crossings are **not** strikes. | F | 04 | unit test | PLANNED |
| Q38 | REQ-038 | Retain estimated impact **position** and zone when available (supports timing/trajectory evaluation). | F | 04, 07 | test (04 output fields); review (07 labels include position) | PLANNED |
| Q39 | REQ-039 | **Sub-frame impact timing**: interpolate between the two observations surrounding the crossing instead of taking the nearest frame. | F | 04 | unit test | PLANNED |
| Q40 | REQ-040 | No fixed validated lead time; **maximise useful Prediction Lead Time while controlling FP and Timing Error**; candidate lead times determined experimentally. | R | 09, 10, 18 | measurement (threshold/horizon sweeps) | PLANNED |

### G — AI / Machine Learning

| Q# | REQ | Requirement | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|---|
| Q41 | REQ-041 | Multi-task targets: strike-within-horizon, Time-to-Impact, impact zone, impact position (when useful), intensity proxy. **Main direction: Future Trajectory Prediction.** | R | 10, 11 | measurement (per-task metrics) | PLANNED |
| Q42 | REQ-042 | **Trajectory first**: Past Motion → Future Trajectory → Virtual Drum Geometry → Strike. Predicted strike is determined when the predicted trajectory intersects a zone per impact geometry. | C/R | 10, 13 | review + test (geometry code path shared with Phase 04, unchanged) | PLANNED |
| Q43 | REQ-043 | Preferred: a causal temporal model over recent hand/stick motion; **simpler baselines remain available for comparison**. | R | 05, 09, 10 | review (baselines A, B, C-GBDT exist) | PLANNED |
| Q44 | REQ-044 | Evaluate GBDT baseline, GRU, TCN, and (optional, if computationally justified) Tiny Transformer. **Select on validation performance AND real-time CPU inference cost.** | R | 09, 10, 12, 13 | measurement (multi-criteria selection ADR) | PLANNED |
| Q45 | REQ-045 | Metrics: Prediction Lead Time, FP rate, FN rate, Timing Error, Zone Accuracy, Trajectory Error, Intensity Error / Proxy Agreement, Inference Latency, End-to-End / Effective Latency where measurable. **Primary figure: Useful Prediction Lead Time vs False-Positive behaviour.** | R | 09, 18 | measurement (harness implements README §10) | PLANNED |

### H — Dataset & Experiments

| Q# | REQ | Requirement | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|---|
| Q46 | REQ-046 | Dataset target ≈ **10–12 participants**, **1–2 sessions** each (subject to availability). | C | 06 | review (recording manifest) | PLANNED |
| Q47 | REQ-047 | Fixed/structured protocol first; free playing added later only based on results. | C | 06 | review | PLANNED |
| Q48 | REQ-048 | Dataset contains negatives / fake-outs: normal movement, stick motion without strike, fake swings, stopping before impact, movement between zones, tracking interruptions, different speeds, different distances, realistic lighting variation, occlusion. | F | 06, 07 | review (protocol segments; QC coverage table) | PLANNED |
| Q49 | REQ-049 | Reusable research dataset if practical and permitted: reproducible metadata, participant-level splits, clear labelling rules, documentation. | C | 00 (consent), 06, 07, 23 | review (consent opt-ins; dataset card; release decision) | PLANNED |

### I — Final Success Criteria

| Q# | REQ | Requirement | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|---|
| Q50 | REQ-050a | Real-time webcam-based virtual drumming works reliably enough to demonstrate actual strikes with ordinary sticks. | R | 05, 20, 22 | system test + demo rehearsal | PLANNED |
| Q50 | REQ-050b | Temporal prediction demonstrates **useful, measurable Prediction Lead Time vs the Reactive Baseline** without unacceptable False Positives. | R | 10, 18 | measurement | PLANNED |
| Q50 | REQ-050c | Scientifically defensible evaluation of whether prediction improves Action-to-Sound timing, **with limitations documented**. | R | 18, 21 | measurement + review (claims audit) | PLANNED |

### J — Additional System Requirements

| Q# | REQ | Requirement | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|---|
| Q51 | REQ-051 | Single drummer / single-user interaction only in V1. | C | 01, 03 | review | PLANNED — P01 spec: `architecture.md` §16 (single LEFT/RIGHT identity; no multi-user state) — gate pending |
| Q52 | REQ-052 | Runs completely **offline / local**; no Cloud APIs or internet required. | C | 01, 13, 23 | review + test (no network calls; packaged bundle runs offline) | PLANNED — P01 spec: `architecture.md` §16 (no network dependency; local model path + hash) — gate pending |
| Q53 | REQ-053 | Drum Engine plays **local recorded drum samples**, not runtime synthesis. | F | 04 | test | PLANNED |
| Q54 | REQ-054 | MIDI not required for core MVP; advanced / future feature. | X | 00 (register) | review | PLANNED |
| Q55 | REQ-055 | Kick/foot **not in V1** unless scope explicitly expanded; architecture must **not make future kick/foot impossible**. | C | 01, 04 | review (zone registry extensibility) | PLANNED — P01 spec: `architecture.md` §10, ADR-0011; config schema rejects FOOT (TEST-SCHEMA-1) — gate pending |
| Q56 | REQ-056 | Changing drum sounds preferably possible in a later UI/config stage; **not a core research requirement**. | F (low) | 14, 20 | review | PLANNED |
| Q57 | REQ-057 | Calibration Wizard determines camera/playing area and zone positions; not needed in the earliest prototype. | F | 14 | test | PLANNED |
| Q58 | REQ-058 | Debug / Developer Overlay exposes: tracking state, hand landmarks, stick-tip position, stick velocity, prediction, predicted trajectory, drum zone, Time-to-Impact, commit decisions, timing information. | F | 15 | test + review (all 10 items present) | PLANNED |
| Q59 | REQ-059 | Final demo: scientific correctness and measurable behaviour have priority over visual polish, but the demo must still look polished. | C | 22 | review | PLANNED |
| Q60 | REQ-060a | **Never fabricate** recordings, dataset samples, experimental results, accuracy, latency, FPS, or real-stick validation. | C | 00 (checklist), all gates | review (integrity checklist at every gate) | PLANNED |
| Q60 | REQ-060b | **Never use future frames** in a model that is supposed to be causal. | C | 01 (causality test), 03, 08, 09, 10, 13, 17 | test (future-perturbation invariance, defined Phase 01) | PLANNED — P01 spec: `docs/architecture/causality-tests.md` §2–§3 (TEST-CAUSAL-1/2 defined) — gate pending |
| Q60 | REQ-060c | **Never claim** prediction guarantees sound before physical impact unless experimentally measured and clearly defined. | C | 18, 21 | review (claims audit) | PLANNED |
| Q60 | REQ-060d | Preserve the **Target / Measured / Historical / Pending** distinction for all experimental claims. | C | 00 (policy), 21 | review | PLANNED |

---

## 3. Confirmed Core Architecture (pipeline stages) and Core Research Direction

Source: `project-discovery.md` → "Confirmed Core Architecture" and "Core Research Direction". Stage ownership matches `phases/phase-00-project-definition.md` § Architecture.

| REQ | Pipeline stage (verbatim) | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|
| REQ-101 | Webcam | F | 02 | test | PLANNED — P02 evidence: `spacedrums.capture.LiveFrameSource` (`TEST-CAPTURE-1…5`, `TEST-CONFORM-7` live case) — gate pending |
| REQ-102 | Fixed Playing ROI | F | 02 | test | PLANNED — P02 evidence: `capture/roi.py` px<->norm helper + crop (`TEST-CAPTURE-1`) — gate pending |
| REQ-103 | Hand Detection / Hand Landmarks | F | 03 | test | PLANNED |
| REQ-104 | Markerless Visual Stick Detection / Segmentation | F | 03 | benchmark | PLANNED |
| REQ-105 | Stick Axis Estimation | F | 03 | benchmark | PLANNED |
| REQ-106 | Stick Tip Estimation | F | 03 | benchmark | PLANNED |
| REQ-107 | Causal Temporal Tracking | F | 03 | test (causality) | PLANNED |
| REQ-108 | Kinematic Features | F | 08, 13 | test (offline/online parity) | PLANNED |
| REQ-109 | Future Trajectory Prediction | R | 10, 11, 12 | measurement | PLANNED |
| REQ-110 | Virtual Drum Geometry | F | 04 | unit test | PLANNED |
| REQ-111 | Predicted Trajectory / Zone Intersection | F | 04 | unit test (same routine for observed and predicted trajectories) | PLANNED |
| REQ-112 | Strike Prediction | F/R | 05 (rule-based), 10 (model) | measurement | PLANNED |
| REQ-113 | Time-to-Impact | F/R | 05, 10 | measurement | PLANNED |
| REQ-114 | Commit / Refractory / Duplicate Suppression | F | 05 | test (invariants: one commit per episode; refractory) | PLANNED |
| REQ-115 | Drum Engine | F | 04 | test | PLANNED |
| REQ-116 | Audio Scheduling (→ Drum Sound) | F | 04 | measurement (audio output latency) | PLANNED |
| REQ-117 | **Core Research Direction:** causal temporal prediction of future stick trajectory from monocular webcam hand/stick motion, then geometry-based impact determination and latency-aware audio scheduling; evaluate whether it provides useful lead time and reduces effective latency vs reactive detection with acceptable FP/TE. | R | 10, 18 | measurement | PLANNED |

---

## 4. Important Scope Rules (out of V1 scope)

Detailed register with re-inclusion rule: [`out-of-scope.md`](out-of-scope.md). Ownership: Phase 00 (register) + Phase 23 (final coverage audit confirms nothing out-of-scope was built or claimed).

| REQ | Excluded item (verbatim) | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|
| REQ-201 | ESP32 | X | 00, 23 | review | PLANNED |
| REQ-202 | IMU sensors | X | 00, 23 | review | PLANNED |
| REQ-203 | Electronic stick hardware | X | 00, 23 | review | PLANNED |
| REQ-204 | Multiple users | X | 00, 23 | review | PLANNED |
| REQ-205 | Full-body tracking | X | 00, 23 | review | PLANNED |
| REQ-206 | Mandatory depth estimation | X | 00, 23 | review | PLANNED |
| REQ-207 | Foot/Kick tracking | X | 00, 01 (must stay possible), 23 | review | PLANNED — P01 spec: `architecture.md` §10, ADR-0011 (reserved, not built; OOS-REF tags) — gate pending |
| REQ-208 | MIDI as a core requirement | X | 00, 23 | review | PLANNED |
| REQ-209 | Cloud processing | X | 00, 13, 23 | review + test (offline) | PLANNED |
| REQ-210 | Mandatory visual markers | X | 00, 03, 23 | review | PLANNED |
| REQ-211 | Marker-based tracking may **only** be used as a fallback or benchmark. | C | 03, 18, 21 | review (every marker result labelled as such) | PLANNED |

---

## 5. Current Project Philosophy (priorities)

| REQ | Priority (verbatim) | Type | Owning phase(s) | Verification | Status |
|---|---|---|---|---|---|
| REQ-301 | Scientific correctness | C | 00, 21 | review (integrity checklist; claims audit) | PLANNED |
| REQ-302 | Causal processing | C | 01, 03, 08, 09, 10, 13 | test (causality invariance) | PLANNED — P01 spec: `causality-tests.md` §1–§3; interfaces have no look-ahead (`architecture.md` §11) — gate pending |
| REQ-303 | Measurable performance | C | 09, 18 | measurement | PLANNED |
| REQ-304 | Real-time behaviour | C | 13, 16 | measurement (latency budgets) | PLANNED |
| REQ-305 | Robust Computer Vision | C | 03, 17 | test (failure injection) | PLANNED |
| REQ-306 | Meaningful temporal prediction | R | 10, 19 | measurement (ablations show contribution) | PLANNED |
| REQ-307 | Clear experimental comparison | R | 18 | measurement (pre-registered A/B/C) | PLANNED |
| REQ-308 | Reproducibility | C | 00, 09, 21 | review (reproducibility policy; manifests) | PLANNED |
| REQ-309 | Honest reporting of limitations | C | 21 | review | PLANNED |
| REQ-310 | Visual polish must not replace scientific validation. | C | 15, 22 | review | PLANNED |

---

## 6. Coverage summary

| Group | Rows | Unowned | Notes |
|---|---|---|---|
| Q1–Q60 | 65 (60 questions; Q50 split into 3 rows, Q60 into 4) | 0 | — |
| Architecture + research direction | 17 | 0 | — |
| Scope rules | 11 | 0 | Out-of-scope items owned by Phase 00 register + Phase 23 audit |
| Philosophy | 10 | 0 | — |
| **Total** | **103** | **0** | Acceptance criterion 1 satisfied at document level; per-phase citation check recorded in `docs/gates/phase-00-gate.md`. |

## 7. Phase → REQ reverse index

Used by Phases 21 and 23 to show each phase's requirement coverage. Each phase document cites these IDs in its `## Inputs` section.

| Phase | Primary REQs owned | Also contributes to |
|---|---|---|
| 00 | REQ-008, 049, 054, 060a, 060d, 201–210, 301, 308 | — |
| 01 | REQ-001, 021, 033, 051, 052, 055, 060b, 207, 302 | 004 |
| 02 | REQ-019, 022, 023, 024, 025, 026, 027, 101, 102 | 004 |
| 03 | REQ-007, 009, 010, 029, 030, 031, 032, 034, 035, 103–107, 210, 211, 305 | 025, 033, 051, 060b, 302 |
| 04 | REQ-011, 014, 015, 016, 017, 018, 020, 036, 037, 038, 039, 053, 110, 111, 115, 116 | 004, 021, 055 |
| 05 | REQ-004, 006, 012, 013, 043, 050a, 112, 113, 114 | 001, 007, 011, 035 |
| 06 | REQ-003, 046, 047, 048 | 012, 024, 027, 028, 032, 049 |
| 07 | REQ-014 (GT proxy), 038 (labels), 048 (QC), 049 (splits, rules) | 015 |
| 08 | REQ-108 | 060b, 302 |
| 09 | REQ-005, 040, 043, 044, 045, 303, 308 | 060b, 302 |
| 10 | REQ-002, 041, 042, 043, 044, 050b, 109, 112, 113, 117, 306 | 005, 040, 060b, 302 |
| 11 | REQ-041 (task heads), 014 (intensity agreement) | 109 |
| 12 | REQ-044 (Tiny Transformer go/no-go) | 109 |
| 13 | REQ-042 (live geometry path), 052, 108 (online parity), 304 | 001, 044, 209, 302 |
| 14 | REQ-057, 019, 016, 018, 056 | 004 |
| 15 | REQ-058, 310 | 020 |
| 16 | REQ-023 (60 FPS attempt), 304 | — |
| 17 | REQ-012, 027, 028, 029, 034, 035, 305 | 060b |
| 18 | REQ-002, 005, 009 (marker labelling), 011, 013, 040, 045, 050b, 050c, 060c, 117, 211, 307 | 027, 028 |
| 19 | REQ-306 | — |
| 20 | REQ-001, 004, 006, 050a, 056 | — |
| 21 | REQ-050c, 060c, 060d, 301, 308, 309 | 211 |
| 22 | REQ-003, 006, 050a, 059, 310 | 020 |
| 23 | REQ-049 (dataset release), 052 (offline bundle), 201–210 (coverage audit) | — |

---

## 8. Change control

- Adding, removing or re-wording a requirement requires an ADR in `docs/decisions/` and an update to this file in the same change.
- Re-including any `REQ-2xx` item requires explicit scope expansion per `out-of-scope.md` §2.
- Status columns are edited **only** with a link to evidence (test report, measurement record, gate record).
