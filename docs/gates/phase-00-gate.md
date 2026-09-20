# Phase 00 — Exit Gate Record

| Field | Value |
|---|---|
| Phase | 00 — Project Definition & Environment |
| Phase document | `phases/phase-00-project-definition.md` |
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-20 |
| Reviewer(s) | Project owner — **review pending** |
| Review date | *pending* |
| Code state | git repository initialised (branch `main`), **no commits yet** → no `git_sha`. Document-only phase; the only script is `scripts/env_smoke.py`. |
| **Verdict** | **PENDING OWNER REVIEW** (submitter's self-assessment: all 7 acceptance criteria MET; recommend PASS-WITH-CONDITIONS — see §8) |

## 1. Artefacts produced

| Artefact (from phase document) | Path | Status label | Present? |
|---|---|---|---|
| RTM | `docs/requirements/rtm.md` | PLANNED (all rows) / document complete | yes |
| Out-of-Scope Register | `docs/requirements/out-of-scope.md` | policy | yes |
| Environment spec + lock strategy | `docs/environment.md`, `requirements.in`, `requirements.lock` | IMPLEMENTED (env only) | yes |
| Repo layout + skeleton | `docs/repo-layout.md`; `src/spacedrums/<13 subpackages>/README.md`; `configs/`, `configs/schema/`, `data/`, `experiments/`, `tests/`, `scripts/`, `schemas/` with README stubs; `.gitignore` | IMPLEMENTED (skeleton) | yes |
| Reproducibility policy + schema | `docs/reproducibility-policy.md`; `schemas/experiment-log.schema.json`; `schemas/examples/experiment-log.valid.example.json` | policy / schema IMPLEMENTED | yes |
| Integrity checklist | `docs/integrity-checklist.md` | IMPLEMENTED (in use) | yes |
| Ethics templates | `docs/ethics/information-sheet.md` (IS-v0.1), `docs/ethics/consent-form.md` (CF-v0.1), `docs/ethics/ethics-approval-note.md` | DRAFT / Open Question | yes |
| Hardware inventory | `docs/hardware-inventory.md` (HW-01 inspected 2026-09-20) | inspected, not measured | yes |
| ADR-0001..0003 + index | `docs/decisions/ADR-0001-python-first-stack.md`, `ADR-0002-practice-pad-microphone-ground-truth.md`, `ADR-0003-mvp-zone-set.md`, `README.md` | Accepted (0003 partial) | yes |
| Gate procedure + template + this record | `docs/gates/gate-procedure.md`, `gate-record-template.md`, `phase-00-gate.md` | IMPLEMENTED | yes |
| Environment smoke script | `scripts/env_smoke.py` | IMPLEMENTED, passes | yes |

Deviation from the proposed paths in the phase document's *System Components*: `docs/ethics/consent-template.md` was split into `information-sheet.md` + `consent-form.md` (as the *Artifacts Produced* section already lists) plus `ethics-approval-note.md` for the Open Question record.

## 2. Acceptance criteria

| # | Criterion (verbatim) | Evidence | Assessment |
|---|---|---|---|
| 1 | RTM covers all 60 discovery answers plus architecture and scope rules; zero unowned requirements. | Mechanical check run 2026-09-20 on `rtm.md`: `Q# covered: 60/60`, `REQ rows: 103, duplicates: [], unowned: []`; `24/24` phase documents cite ≥ 1 existing `REQ` id (bullet added to each `## Inputs` section). | MET |
| 2 | Environment specification allows a clean re-install; smoke import succeeds on the development machine. | `docs/environment.md` §4 procedure; `requirements.lock` (SHA-256 `f92a60c6…86a8`); `scripts/env_smoke.py` → `RESULT: PASS` (13/13 imports) on HW-01, Python 3.11.9, clean `venv`, 2026-09-20. **Clean second machine / VM not yet done** (checklist item, `environment.md` §6). | MET (dev machine); clean-machine row pending → condition C-1 |
| 3 | Reproducibility policy and experiment-log schema exist and validate. | `docs/reproducibility-policy.md`; `schemas/experiment-log.schema.json` validated by `env_smoke.py`: valid example accepted; record missing `dataset_version` rejected. | MET |
| 4 | Integrity checklist exists and is referenced by the exit-gate procedure. | `docs/integrity-checklist.md`; `docs/gates/gate-procedure.md` §2 item 5 and §3 step 3; all 24 phase documents' Definition of Done already cite it. | MET |
| 5 | Consent/information templates exist; ethics-approval requirement recorded as answered or `Open Question`. | IS-v0.1, CF-v0.1 (separate opt-ins C1/C2/C3 as specified); `ethics-approval-note.md` records **Open Question**. | MET |
| 6 | ADR-0001..0003 recorded. | Three ADRs with context/decision/alternatives/consequences/status + index. | MET |
| 7 | Hardware inventory template exists (values may be empty). | `docs/hardware-inventory.md`: HW-01 CPU/RAM/OS/webcam id/audio endpoints filled from OS metadata and marked *inspected on 2026-09-20*; webcam modes, driver, peripherals left as not-inspected / Open Question. | MET |

## 3. Tests

| Test id | What it checks | Result | Where run |
|---|---|---|---|
| ENV-SMOKE (`scripts/env_smoke.py`) | Import of numpy, scipy, opencv-python, mediapipe, torch (CPU), onnxruntime, lightgbm, sounddevice, soundfile, pydantic, PyYAML, jsonschema, pytest; prints versions | PASS | HW-01, `.venv` Python 3.11.9, 2026-09-20 |
| SCHEMA (inside `env_smoke.py`) | `experiment-log.schema.json` accepts the valid example; rejects a record missing `dataset_version` | PASS | same |
| RTM-COMPLETENESS (manual, ad-hoc script — not kept as project code) | 60/60 Q#; every REQ owned; every phase doc cites an existing REQ | PASS | 2026-09-20 |

## 4. Measurements produced in this phase

None — this phase produces no measurements. Recorded facts only: inspected hardware metadata (labelled *inspected*) and library versions (labelled from `pip freeze`, 2026-09-20).

## 5. Integrity checklist

| # | Item | YES / NO / N/A | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled | YES | Numbers in Phase 00 documents are: quoted discovery values (30/60 FPS, 4/7 zones, 10–12 participants, 100–300 ms), library versions, hardware metadata marked *inspected*, or explicitly *candidate* (tolerances in `reproducibility-policy.md` §6, seed list §2). No result is presented. |
| I-2 | No implementation claim without tests | YES | Only `env_smoke.py` is claimed IMPLEMENTED; it is its own test and passes. Skeleton dirs are labelled PLANNED stubs. |
| I-3 | No causal component consumes future frames | N/A | No code. Checklist points to the Phase 01 future-perturbation invariance test. |
| I-4 | No fabricated data | YES | No recordings, participants, labels or results exist. The schema example is named `*.valid.example.json`, is all-zero placeholders, and states "SYNTHETIC EXAMPLE … Not a result." `data/` is empty except README. |
| I-5 | FPS reported as native only | N/A | No FPS figure exists. `hardware-inventory.md` explicitly declines to state advertised webcam FPS until inspected and marks an *expectation* as not a measurement. |
| I-6 | No "latency reduced" claim | YES | All latency language is conceptual (README §5.4) or pending Phase 18; ADR-0002 and the ethics sheet describe the goal as a question. |
| I-7 | Marker condition labelled | N/A | No results. Policy captured in REQ-211, out-of-scope register, checklist. |
| I-8 | Participant-level split confirmed | N/A | No ML results. Policy captured in `reproducibility-policy.md` §4 and schema `split{}`. |
| I-9 | Scope respected | YES | Nothing out of scope built; `OOS-REF` tagging rule defined. |
| I-10 | Status vocabulary correct | YES | Phase 00 document `## Status` updated to IMPLEMENTED (document-only) pending gate; every artefact carries a label. |
| I-11 | Reproducibility fields complete | N/A | No runs. Schema and policy exist; no `git_sha` yet because the repository has no commits (see condition C-2). |
| I-12 | Limitations stated | YES | Open Questions listed in §7 below; `environment.md` §6 states the clean-machine verification is pending; `hardware-inventory.md` marks uninspected fields. |

## 6. Deviations from the phase document

| What | Why | Impact on dependents |
|---|---|---|
| Ethics artefacts split into three files (see §1). | The *Artifacts Produced* list already names two files; the approval status needed its own living record. | None. |
| A traceability bullet was **added to the `## Inputs` section of every phase document 01–23** (and 00). | Task 00.1 evidence requires every phase document to reference ≥ 1 `REQ-xxx`; adding to an existing section keeps the 25-section structure intact. | Phase documents now carry their owned REQ ids; Phase 21/23 coverage audit can grep them. |
| `phases/README.md` §12 gained a one-line link to the out-of-scope register. | Task 00.2 evidence: "referenced by README §12". | None. |
| Hardware inventory partially filled (CPU, RAM, OS, camera id, audio endpoints) rather than left empty. | Values were obtainable from OS metadata without measurement; each is marked *inspected on 2026-09-20* with the method. | Phase 02 still measures everything camera-related. |
| Environment verified in a clean `venv` on the dev machine, **not** on a clean machine/VM. | No second machine available in this session. | Recorded as a pending checklist row (`environment.md` §6) and condition C-1. |
| `requirements.lock` uses `pip freeze`, not `pip-tools` hashes. | Simplest reproducible mechanism; upgrade path documented (OQ-ENV-3). | None before Phase 06. |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase / owner |
|---|---|---|
| Is institutional ethics approval required for recording hands/arms (+ possibly faces) and optional pad audio? | Open Question | Project owner + supervisor, before the Phase 01 gate (so any review runs in parallel with Phases 01–05); Phase 06 blocked until answered. |
| Will a released dataset be permitted? (consent form item C3) | Open Question | Same as above. |
| Raw-video retention period for the information sheet. | Open Question | Same as above. |
| Final Python minor version (3.11 vs 3.12); single lock for a second OS. | Open Question (OQ-ENV-1, OQ-ENV-2) | Phase 01 gate. |
| Hash-pinned locks (`pip-tools`). | Open Question (OQ-ENV-3) | Before Phase 06. |
| 7th V1 zone (Crash vs Ride split / other). | Open Question (ADR-0003) | Phase 04 gate. |
| Tripod, drumsticks, practice pad, microphone, coloured tape, external camera — availability and specs. | Open Question | Owner, before Phase 02 (tripod/sticks) and Phase 06 (pad/mic). |
| Webcam driver version and advertised modes. | not inspected | Phase 02. |
| Experiment tracker beyond file manifests. | Pending Architecture Decision (default = files) | Phase 09. |
| Stack items marked Pending Benchmark: OpenCV backend/timestamps (02), MediaPipe landmark cost (03), audio host API/latency (04), ONNX vs TorchScript (13). | Pending Benchmark | 02, 03, 04, 13. |

## 8. Conditions (proposed, for PASS-WITH-CONDITIONS)

| Condition | Owner | Must be closed by |
|---|---|---|
| C-1: Clean-machine or clean-VM re-install from `requirements.lock` + `env_smoke.py` PASS, recorded in `environment.md` §6. | Project owner (or a second person) | Before any status is promoted to VALIDATED; at the latest the Phase 09 gate. |
| C-2: Make the first git commit of the Phase 00 artefacts and tag `gate-00-pass` after the verdict, so later runs can cite a `git_sha`. | Project owner | Phase 01 start. |
| C-3: Raise the ethics-approval and dataset-release questions with the supervisor; record answers in `docs/ethics/ethics-approval-note.md`. | Project owner | Phase 01 gate (must be answered before Phase 06). |

## 9. Reviewer statement

*To be written by the project owner after inspecting the artefacts.* Suggested minimum: open `rtm.md` and spot-check three Q# rows against `project-discovery.md`; run `.venv\Scripts\python.exe scripts\env_smoke.py`; read the three ADRs and confirm they match your decisions; confirm the consent opt-ins (C1/C2/C3) are the ones you want.

Signed: ____________________, YYYY-MM-DD
