# Phase 07 — Reopened Exit Gate (r2)

Reopened 2026-09-22 on the owner's explicit Phase 08 instruction. This record supersedes
`phase-07-gate.md` for current condition status; that submission and its historical evidence remain intact.
Submitter: Codex. Reviewer: project owner, pending. Proposed verdict: **PASS-WITH-CONDITIONS
for infrastructure; participant dataset Definition of Done remains unsatisfied**.

## Owner commit and clean verification

Inspected owner commit `1a8e790985bc97810eb28bd26ddc788136a16157` (`phase 7`, parent
`f29588a6aad8b40d045507888ee7289bbaac2e2f`). It contains the Phase 07 implementation,
schemas, tests, reports and original gate. Working tree was clean before and after every
command in the original gate §3.1. No Git history operation was performed.

Verified reference: `experiments/20260922-2043-p07-clean-verification/run.json` (schema-valid,
`git_dirty: false`, HW-01, config snapshot and hashed artefacts). Detailed command list,
exit codes, timings and post-command cleanliness are in
`experiments/20260922-203551-p07-clean/verification.json`; logs `00.log`–`17.log`.

| Verification | Actual result | Evidence class |
|---|---|---|
| Focused Phase 07 suite | 489 passed | UNIT / CONTRACT TEST |
| Full regression | 876 passed, 1 opt-in webcam test skipped | UNIT / PROPERTY / CONTRACT TEST |
| Ruff; import-linter | PASS; 7 contracts kept, 0 broken | STATIC CHECK |
| Contract validator | PASS, 465 checks | CONTRACT TEST |
| Label validator self-test | clean set passes; all 13 injected failures caught | SYNTHETIC / UNIT TEST |
| Both session label rebuilds | IDENTICAL on repeated generation; separation OK; validator CLEAN | SYNTHETIC / DEV CAPTURE, separately |
| Splits, manifest, acoustic, scripted review self-tests | PASS | SYNTHETIC / UNIT TEST |
| Smoother and interpolation comparisons | reproduced; QUADRATIC decision unchanged | SYNTHETIC |
| Environment, pinned model, seven audio sample hashes | PASS | STATIC CHECK |
| `git diff --check` | exit 0, clean tree | STATIC CHECK |

The whitespace check was executed directly on the clean tree: no index staging/reset was
needed. The historical command's `git add -N` / reset wrapper was deliberately unnecessary.
Additional clean runs of `label_stats.py --all` and `acoustic_onset.py --all` use the rebuilt
label directories; their report outputs are hashed in the verified run.

Rebuilt SYNTHETIC session: 65 labels, set hash
`sha256:d76de2749b1952cdb3d15491d12608b18812ebafbc1c087639a7518f22157378`.
Rebuilt DEV CAPTURE: 21 labels, set hash
`sha256:aeb256b03de10812798b6fe430338b5d5320ca1f299dc29717d3cc376c27a538`.
Hashes differ from the original runs because generator commit provenance changed; each
rebuild is internally deterministic. The original `data/labels/` outputs were preserved.

## Condition audit

| Condition | Status / classification | Evidence or remaining prerequisite |
|---|---|---|
| C-07-1 | PENDING — HUMAN ACTION | No manual tip annotations near impacts exist. Synthetic smoother evidence cannot validate them. |
| C-07-2 | PENDING — HUMAN ACTION dependency | Requires the real review pass before threshold refinement; no new review evidence. |
| C-07-3 | PENDING — HUMAN ACTION | No participant labels or human review logs; annotator availability remains unresolved. Scripted review is only a test. |
| C-07-4 | PENDING — HUMAN ACTION | No physical or manual crossing reference; ADR-0020 remains provisional. |
| C-07-5 | PENDING — OWNER / HUMAN ACTION | C-06-3 unresolved; no physical pad/mic evidence or evidenced drop decision. Synthetic acoustic rerun is not physical validation. |
| C-07-6 | PENDING — HUMAN ACTION dependency | No participant raw sessions, `ds-v1.0` manifest or frozen participant splits; C-06-4 remains open. |
| C-07-7 | **CLOSED** — 2026-09-22 | Every original §3.1 command rerun successfully on committed SHA with `git_dirty: false`; run above. |

Inventory inspected: raw roots DEV and SYNTHETIC only; label roots contain the two sessions
above; only self-test manifest/split files exist; no annotation/review/physical reference was
found. No other condition became executable at the owner commit. No participant recording
or human annotation was created.

## Acceptance, integrity, and handoff

Original tasks, acceptance criteria and limitations carry forward unchanged, except I-11's
dirty-tree limitation is resolved for the rerun references above. I-1–I-4, I-6, I-8–I-12: YES
within their stated infrastructure scope; I-5 and I-7: N/A (no new camera/marker measurement).
Participant criteria remain PENDING/PARTIAL exactly as in the original gate. A clean commit
does not turn synthetic evidence into participant evidence or constitute owner gate sign-off.

Phase 08 proceeds under the owner's explicit instruction, with participant-dependent work
pending and independent implementation authorized. This is not a claim that `ds-v1.0` exists
or that the reviewer has issued PASS. No executable Phase 07 condition remains.
