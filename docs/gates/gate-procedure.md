# Phase Exit-Gate Procedure

**Phase:** 00 — Task 00.10 · **Status:** IMPLEMENTED (procedure in force from the Phase 00 gate)
**Source:** `phases/README.md` §15 ("a phase is Done only when its Definition of Done is satisfied — code existing is never sufficient"); each phase document's *Acceptance Criteria*, *Definition of Done*, and *Exit Gate* sections.
**Template:** [`gate-record-template.md`](gate-record-template.md). Records: `docs/gates/phase-XX-gate.md`.

## 1. Roles

| Role | Who | Responsibility |
|---|---|---|
| **Submitter** | Whoever executed the phase (developer; may be an AI assistant acting for the owner) | Assembles the inputs (§2), pre-fills the record, states honestly what is and is not done. |
| **Reviewer** | **Project owner**, and the **supervisor** where the institution or the phase requires it (Phases 06/07 ethics and dataset freeze, 18 pre-registration, 21 thesis, 23 release — supervisor sign-off recommended). | Checks every acceptance criterion against evidence, fills the integrity checklist, issues the verdict. The submitter may not be the sole reviewer. |

## 2. Inputs to a gate review

1. **Artefact list** — every item in the phase document's *Artifacts Produced*, with path and status label.
2. **Acceptance-criteria table** — each criterion with evidence pointer (file, test id, run id) and MET / NOT MET / PARTIAL.
3. **Test report** — test ids executed, pass/fail, `git_sha` (N/A for document-only phases; the Phase 00 smoke script counts as its test).
4. **Measurements** — every MEASURED quantity produced in the phase, each with `run_id`, method, hardware id, date (N/A where the phase measures nothing).
5. **Integrity checklist** — [`../integrity-checklist.md`](../integrity-checklist.md) filled item by item.
6. **Open Questions / Pending items** carried forward, with the phase that will resolve each.
7. **Deviations** from the phase document (anything done differently, skipped, or added), each with a reason.

## 3. Procedure

1. Submitter creates `docs/gates/phase-XX-gate.md` from the template and fills §2 inputs.
2. Reviewer verifies each acceptance criterion **against the evidence, not the description** (open the file, run the test, check the number's label).
3. Reviewer completes the integrity checklist. Any **NO** must be resolved or explicitly conditioned.
4. Reviewer records the verdict:

| Verdict | Meaning | Effect |
|---|---|---|
| **PASS** | All acceptance criteria MET; checklist has no NO; Definition of Done satisfied. | Next phase(s) may start. Phase document `## Status` → the appropriate label (IMPLEMENTED / MEASURED / VALIDATED as applicable). Git tag `gate-XX-pass` once the repo has commits. |
| **PASS-WITH-CONDITIONS** | Minor items outstanding that do not affect the dependent phases' inputs. | Next phase may start; conditions listed with an owner and a deadline (a phase number by which they must be closed). Conditions are re-checked at the next gate. |
| **FAIL** | An acceptance criterion is NOT MET in a way that dependent phases rely on, or an integrity item is NO without an acceptable condition. | Phase continues; a new gate review is scheduled. Nothing downstream starts. |

5. The record is stored at `docs/gates/phase-XX-gate.md`, committed, and linked from the phase document's `## Exit Gate` section (a one-line "Gate record: … — verdict, date").
6. If the phase is later reopened (e.g. a downstream phase finds a defect), a new record `phase-XX-gate-r2.md` is created; the old one is kept and marked superseded.

## 4. Rules

- A gate cannot be passed by the submitter alone.
- No verdict without the integrity checklist filled.
- "Reviewed" means the reviewer looked at the evidence; a verbal "looks fine" is recorded as PASS-WITH-CONDITIONS with the condition "evidence review pending".
- Gate records are the **only** place a requirement's RTM status may be advanced.
- Date format in records: `YYYY-MM-DD`.
