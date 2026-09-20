# Phase XX — Exit Gate Record

| Field | Value |
|---|---|
| Phase | XX — <name> |
| Phase document | `phases/phase-XX-<slug>.md` |
| Submitter | <name / role> |
| Reviewer(s) | <project owner> [, <supervisor>] |
| Review date | YYYY-MM-DD |
| Code state | `git_sha` <40-hex> / dirty: yes/no (N/A for document-only phases) |
| **Verdict** | **PASS / PASS-WITH-CONDITIONS / FAIL** |

## 1. Artefacts produced

| Artefact (from phase document) | Path | Status label | Present? |
|---|---|---|---|
| | | PLANNED / IMPLEMENTED / MEASURED / VALIDATED / PENDING | yes / no |

## 2. Acceptance criteria

| # | Criterion (verbatim from phase document) | Evidence (file / test id / run id) | MET / PARTIAL / NOT MET |
|---|---|---|---|
| 1 | | | |

## 3. Tests

| Test id | What it checks | Result | Where run (hardware id, date) |
|---|---|---|---|
| | | pass / fail | |

## 4. Measurements produced in this phase

| Quantity | Label | Value | run_id | Method | Hardware id |
|---|---|---|---|---|---|
| | Measured / Historical | | | | |

(If none: "None — this phase produces no measurements.")

## 5. Integrity checklist (copy of `docs/integrity-checklist.md`)

| # | Item | YES / NO / N/A | Evidence / reason |
|---|---|---|---|
| I-1 | Every number labelled Target / Measured / Historical / Pending | | |
| I-2 | No implementation claim without tests | | |
| I-3 | No causal component consumes future frames | | |
| I-4 | No fabricated data | | |
| I-5 | FPS reported as native only | | |
| I-6 | No "latency reduced" claim before Phase 18 | | |
| I-7 | Marker condition clearly labelled | | |
| I-8 | Participant-level split confirmed for ML results | | |
| I-9 | Scope respected (out-of-scope register) | | |
| I-10 | Status vocabulary correct | | |
| I-11 | Reproducibility fields complete | | |
| I-12 | Limitations stated | | |

## 6. Deviations from the phase document

| What | Why | Impact on dependents |
|---|---|---|
| | | |

## 7. Open Questions / Pending items carried forward

| Item | Marker | Resolving phase |
|---|---|---|
| | Open Question / To Be Experimentally Determined / Pending Benchmark / Pending Architecture Decision | |

## 8. Conditions (only for PASS-WITH-CONDITIONS)

| Condition | Owner | Must be closed by (phase/date) |
|---|---|---|
| | | |

## 9. Reviewer statement

<Free text: what was actually inspected, run, or opened; anything the reviewer did not verify.>

Signed: <reviewer>, YYYY-MM-DD
