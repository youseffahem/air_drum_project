# Phase 00 — Project Definition & Environment

## Status

Planned

## Purpose

Turn the confirmed answers in [`../project-discovery.md`](../project-discovery.md) into a traceable requirements baseline, fix the development environment and reproducibility rules, and install the research-integrity policy that every later phase must obey. This phase produces documents and configuration only — no pipeline code.

## Why This Phase Exists

Every later phase makes claims about scope ("kick is out of V1"), measurement ("native FPS"), and evidence ("MEASURED vs PENDING"). Without a single frozen requirements baseline, a status vocabulary, a pinned environment, and a consent template for participants, those claims cannot be audited and the dataset phases cannot legally or ethically start. This phase is cheap and prevents the most expensive class of error: building the wrong thing or being unable to reproduce what was built.

## Relationship to Research Contribution

The contribution — Causal Temporal Strike Anticipation — depends on being able to state, for every number in the thesis, *how* it was obtained and *whether it is a target or a measurement*. Phase 00 defines the vocabulary (README §4), the experiment-log format, and the seed/config/hash policy that Phases 09–19 rely on for reproducibility. It also fixes the requirements traceability that Phase 21 will use to show that each success criterion (Q50) was addressed.

## Inputs

- `project-discovery.md` (all 60 answers, confirmed architecture, scope rules, philosophy).
- Owner decisions recorded in this session: Python-first stack; optional practice-pad + microphone ground-truth condition; MVP zones = Snare, Hi-Hat, Tom 1, Crash/Ride.
- Available hardware (laptop, webcam) — to be inventoried, not assumed.

## Expected Outputs

- Requirements Traceability Matrix (RTM): each discovery Q# → requirement ID → owning phase(s) → verification method.
- Environment Specification: pinned Python version, dependency lock file strategy, OS notes, target-CPU naming convention.
- Repository layout and naming conventions document.
- Reproducibility Policy: seeds, config versioning, hashes, experiment log schema.
- Research Integrity Checklist (used at every Exit Gate).
- Participant consent + information sheet template (draft for institutional review if required).
- Hardware Inventory template (values filled only when measured/inspected).
- Decision Log (ADR-style) with the three owner decisions above as the first entries.

## Dependencies

None. This is the first phase.

## System Components

None implemented. Documents and configuration skeletons only:

- `docs/requirements/rtm.md`
- `docs/environment.md`
- `docs/reproducibility-policy.md`
- `docs/integrity-checklist.md`
- `docs/ethics/consent-template.md`
- `docs/hardware-inventory.md`
- `docs/decisions/ADR-0001..0003.md`
- `configs/` (empty skeleton with schema placeholder)

(Paths are the proposed layout; final layout is fixed in Task 00.4.)

## Architecture

Not applicable at the code level. The governing architecture is the confirmed pipeline in README §1; Phase 00 only records it as the authoritative reference and assigns each stage to a phase:

| Pipeline stage | Owning phase |
|----------------|--------------|
| Webcam / fixed playing ROI | 02 |
| Hand landmarks + markerless stick detection/segmentation | 03 |
| Stick axis + tip estimation | 03 |
| Causal temporal tracking | 03 |
| Kinematic features | 08 (offline schema), 13 (online parity) |
| Future trajectory prediction | 10 (11, 12) |
| Virtual drum geometry + intersection | 04 |
| Predicted strike + TTI | 05 (rule-based), 10 (model) |
| Commit / refractory / duplicate suppression | 05 |
| Drum engine + audio scheduling | 04 |

## Detailed Tasks

### Task 00.1 — Requirements Traceability Matrix
- **What:** Build a table with one row per discovery answer (Q1–Q60) plus the confirmed architecture and scope rules. Columns: Q#, requirement ID (`REQ-xxx`), requirement text (verbatim or tightly paraphrased), type (functional / research / constraint / out-of-scope), owning phase(s), verification method (test / measurement / review), status (PLANNED).
- **Why:** Phases 21 and 23 must show which requirement each result satisfies; the consistency audit of the roadmap needs a machine-checkable list.
- **Depends on:** `project-discovery.md`.
- **Evidence:** `rtm.md` with 60+ rows; every phase document references at least one `REQ-xxx`; no requirement has zero owning phases.

### Task 00.2 — Out-of-Scope Register
- **What:** A separate list of items explicitly excluded from V1 (ESP32, IMUs, electronic sticks, multi-user, full-body tracking, mandatory depth, kick/foot, MIDI core, cloud, mandatory markers), each with the discovery Q# and the rule for re-inclusion ("only by explicit scope expansion").
- **Why:** Prevents scope creep and gives the audit a grep-able source of truth.
- **Depends on:** 00.1.
- **Evidence:** Register file; referenced by README §12.

### Task 00.3 — Stack Confirmation
- **What:** Confirm the Python-first candidate stack from README §11: Python version (candidate: a current CPython 3.x with wheels for all candidates), OpenCV, MediaPipe, PyTorch (CPU build), ONNX Runtime, LightGBM/XGBoost, PortAudio-based audio library, NumPy/SciPy, config/schema library, test framework. For each: candidate, license, CPU support, known Windows constraints, and the phase that will benchmark it. Where a choice cannot be made without measurement, record `Pending Benchmark` with the phase.
- **Why:** Later phases name concrete libraries; the choice must be documented once, with alternatives, not implied.
- **Depends on:** README §11.
- **Evidence:** `environment.md` with a dependency table and a lock-file strategy (e.g. `requirements.lock` / `pyproject` + lock). Environment can be recreated from scratch on a clean machine following the document (verified by a second person or a clean VM — recorded as a checklist item, not assumed).

### Task 00.4 — Repository Layout & Naming Conventions
- **What:** Define top-level directories (proposal: `src/spacedrums/` with subpackages `capture/ hands/ stick/ tracking/ features/ geometry/ prediction/ commit/ audio/ ui/ eval/ data/ calib/`; `configs/`; `data/` (git-ignored, manifest-tracked); `experiments/`; `docs/`; `tests/`; `scripts/`), naming rules for configs (`<component>.<variant>.v<N>.yaml`), model artefacts (`<family>-<task>-<dataset_version>-<seed>-<hash8>`), experiment runs (`YYYYMMDD-HHMM-<slug>`), and dataset versions (`ds-v<major>.<minor>`).
- **Why:** Reproducibility (README §13) and cross-phase references require stable names.
- **Depends on:** 00.3.
- **Evidence:** `docs/repo-layout.md`; empty skeleton directories with `README.md` stubs; a `configs/schema/` placeholder.

### Task 00.5 — Reproducibility Policy
- **What:** Rules for: global seeding (Python, NumPy, PyTorch, GBDT), deterministic data-loader ordering, config snapshot per run (full resolved config stored with the run), git commit hash + dirty flag per run, dataset version hash per run, hardware descriptor per run (CPU model, core count, RAM, OS build, camera model), and the experiment-log JSON schema (`run_id, phase, task, config_hash, dataset_version, git_sha, hardware_id, started_at, finished_at, metrics{}, artefacts[]`). Define the "same result" tolerance policy for VALIDATED status (exact for deterministic code paths; documented tolerance for non-deterministic ones).
- **Why:** README §4 VALIDATED status requires reproduction; Phase 09 harness implements this schema.
- **Depends on:** 00.4.
- **Evidence:** `reproducibility-policy.md`; JSON schema file for the experiment log.

### Task 00.6 — Research Integrity Checklist
- **What:** A checklist applied at every Exit Gate: (a) every number is labelled Target/Measured/Historical/Pending; (b) no claim of implementation without tests; (c) no causal component consumes future frames (points to the future-perturbation invariance test defined in Phase 01); (d) no fabricated data; (e) FPS reported as native only; (f) no "latency reduced" claim before Phase 18; (g) marker condition clearly labelled as fallback/benchmark; (h) participant-level split confirmed for any ML result.
- **Why:** Q60 and the non-negotiable rules must be operational, not aspirational.
- **Depends on:** README §4, §13.
- **Evidence:** `integrity-checklist.md`; each later phase's Definition of Done cites it.

### Task 00.7 — Participant Consent & Information Sheet
- **What:** Draft an information sheet (purpose, what is recorded — video of hands/arms/torso within the ROI, optional audio in the pad+mic condition, session duration, data storage, pseudonymisation, right to withdraw, intended dataset reuse) and a consent form with separate opt-ins for (i) use in this project, (ii) reuse in future research, (iii) inclusion in a released dataset. Identify whether institutional ethics approval is required (Open Question — depends on the institution).
- **Why:** Phase 06 cannot start without it; Q49 dataset reuse depends on consent scope.
- **Depends on:** Nothing technical.
- **Evidence:** Two template documents; a note recording the institution's answer on approval requirement (or `Open Question` if unanswered).

### Task 00.8 — Hardware Inventory Template
- **What:** Template fields: laptop model, CPU (model, cores, base/boost clocks), RAM, OS build, integrated webcam model and driver, advertised resolutions/FPS modes (as advertised — measured values come from Phase 02), audio output device, tripod/mount availability, external camera candidates (advertised specs only), microphone availability for the pad+mic condition.
- **Why:** Every MEASURED value must cite the hardware.
- **Depends on:** None.
- **Evidence:** Template with fields; values filled only after physical inspection, each marked "inspected on <date>".

### Task 00.9 — Decision Log Initialisation
- **What:** ADR-0001 Python-first stack; ADR-0002 optional practice-pad + microphone ground-truth condition; ADR-0003 MVP zone set (Snare, Hi-Hat, Tom 1, Crash/Ride) with V1 additions (Tom 2, Floor Tom) and the 7th zone marked Open Question. Each ADR: context, decision, alternatives, consequences, status.
- **Why:** Decisions made outside the discovery file must be as traceable as those inside it.
- **Depends on:** None.
- **Evidence:** Three ADR files; ADR index.

### Task 00.10 — Phase Exit-Gate Procedure
- **What:** Define the review procedure used by every phase: reviewer (project owner and/or supervisor), inputs (artefacts list, measurements, test report, integrity checklist), outcome (PASS / PASS-WITH-CONDITIONS / FAIL), and where the record is stored (`docs/gates/phase-XX-gate.md`).
- **Why:** README §15 states a phase is Done only after review.
- **Depends on:** 00.6.
- **Evidence:** Procedure document and the gate-record template.

## Data Requirements

None. No recordings are made in this phase.

## Algorithms / Technical Approach

Not applicable. The only "algorithm" is the traceability mapping (Q# → REQ → phase) and the hashing scheme for configs/datasets (candidate: SHA-256 over canonicalised JSON for configs; SHA-256 manifest over files for datasets).

## Interfaces / Contracts

- Experiment-log JSON schema (Task 00.5) — consumed by Phases 09–19.
- Config naming and versioning convention (Task 00.4) — consumed by all phases.
- Status vocabulary and undecided-item markers (README §4) — consumed by all documents.

## Tests

- **Document tests (manual):** RTM completeness check (every Q# present; every REQ has ≥1 owning phase; every phase file cites ≥1 REQ).
- **Environment test:** Fresh-machine (or clean virtual environment) install from the lock file succeeds; a smoke script imports every pinned library and prints versions. (This smoke script is an environment check, not project implementation.)
- **Schema test:** The experiment-log JSON schema validates an example record and rejects a record missing `dataset_version`.

## Measurements

- None of the project's research quantities are measured here.
- Recorded facts only: inspected hardware specs (labelled *inspected*, not *measured*), library versions.

## Experimental Design

Not applicable.

## Acceptance Criteria

1. RTM covers all 60 discovery answers plus architecture and scope rules; zero unowned requirements.
2. Environment specification allows a clean re-install; smoke import succeeds on the development machine.
3. Reproducibility policy and experiment-log schema exist and validate.
4. Integrity checklist exists and is referenced by the exit-gate procedure.
5. Consent/information templates exist; ethics-approval requirement recorded as answered or `Open Question`.
6. ADR-0001..0003 recorded.
7. Hardware inventory template exists (values may be empty).

## Definition of Done

- All artefacts in *Artifacts Produced* exist and were reviewed by the project owner (gate record stored).
- Integrity checklist applied to this phase's own documents (no numbers presented as results).
- No source code beyond the environment smoke script exists.

## Risks

- Ethics approval may take longer than expected → Phase 06 delayed.
- Library incompatibilities on Windows (MediaPipe / PyTorch / audio) discovered only later → mitigated by the smoke import now.
- Over-specifying repo layout before Phase 01 contracts exist → keep layout minimal; Phase 01 may amend with an ADR.

## Failure Modes

- RTM drifts from `project-discovery.md` → audit fails. Mitigation: RTM quotes Q# verbatim.
- Environment cannot be reproduced on a second machine → VALIDATED status becomes impossible later.

## Fallback Strategy

- If a candidate library cannot be installed on the target OS, record the alternative from README §11 and open an ADR; do not silently switch.
- If ethics approval is required and delayed, Phases 01–05 proceed (they need no participants); Phase 06 waits.

## Artifacts Produced

- `docs/requirements/rtm.md`
- `docs/requirements/out-of-scope.md`
- `docs/environment.md` + lock file strategy
- `docs/repo-layout.md` + skeleton directories
- `docs/reproducibility-policy.md` + `schemas/experiment-log.schema.json`
- `docs/integrity-checklist.md`
- `docs/ethics/information-sheet.md`, `docs/ethics/consent-form.md`
- `docs/hardware-inventory.md`
- `docs/decisions/ADR-0001..0003.md`
- `docs/gates/gate-procedure.md`, `docs/gates/phase-00-gate.md`

## Exit Gate

Reviewer confirms all acceptance criteria; gate record PASS. Phase 01 may start.

## What Must NOT Be Done Yet

- No camera capture code, tracking code, geometry, audio, or ML.
- No participant recordings, not even pilots.
- No dataset directories with content.
- No benchmark numbers of any kind.

## Open Questions

- Is institutional ethics approval required for recording participants' hands/arms and optional audio? (Task 00.7)
- Will a released dataset be permitted under the institution's rules? (affects consent form opt-in (iii))
- Final Python minor version and whether a single lock file can cover Windows and a second OS.

## Decisions That Must Be Experimentally Validated

- None in this phase. All benchmark-dependent stack choices are marked `Pending Benchmark` and assigned to Phases 02, 03, 04, and 13.
