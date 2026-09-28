# Phase 19 preparation record

**Status: PREPARATION ONLY. Experimental gate: PENDING. Phase 18: PENDING.**

The owner authorized a scheduling exception on 2026-09-27 for engineering preparation.
It does not authorize a participant experiment, approve preregistration, pass either
phase gate, or authorize Phase 20. No commit, tag or push is part of this work.

## Engineering scope

IMPLEMENTED: independent ablation tooling and plan schema, controlled masks/model switches,
CV export, frame dropping/retracking interfaces, paired statistics, hashed manifests and
report generation, dependency and data-scope refusals, and the offline engineering portion
of ADR-0036. See [report](../reports/phase-19-ablations.md) for verification outcomes.

SYNTHETIC/DEV ONLY: generated fixtures, repeated training/replay checks, causality tests,
synthetic A/B/C comparisons, synthetic live parity/fallback tests, and report regeneration.
These provide implementation evidence only. No synthetic result is a participant finding.

REQUIRES FROZEN REFERENCE: Phase 19 experimental configuration, feasible variant list,
fold/seed schedule, matching window, accepted live processing delay, complete operating
rule/budget, reference results, and archived approved preregistrations.

REQUIRES PARTICIPANT DATA: study estimates, confidence intervals interpreted about people,
mechanistic conclusions, external timing claims, and experimental completion.

## Phase 18 obligations carried forward

All remain PENDING at the Phase 18 gate:

- Actual participant dataset and results; reviewed ds-v1.0 labels and frozen folds.
- Live recordings, ethics/consent and live participant design decisions.
- External timing: M1 equipment, check and pad pilot; conditional M2; output-latency loopback.
- Participant regeneration and independent second-person reproduction.
- Owner/supervisor preregistration approval. Existing document and hashes are unchanged.
- Frozen model, configuration, W, measured processing delay, budgets, rules and reference.
- ADR-0036: engineering implementation/tests are recorded separately here; actual locked
  arm values, recorded live verification, dependency re-verification on the owner-committed SHA and reviewer
  acceptance remain required. The live candidate config is not a frozen reference.
- Reviewer gate decision and all unresolved conditions in the Phase 18 gate.
- Verified executor attribution. This session cannot independently verify the model picker
  or reasoning effort; records say `UNVERIFIED (Codex session)` / `UNVERIFIED`. The final
  preparation verification ran in a Claude Code session and records a self-reported,
  unverified `claude-opus-5-5` with effort `UNVERIFIED`.

The Phase 18 gate/report history is not rewritten by this record. Participant confirmation
of DEGRADED-commit policy, reacquisition thresholds/warm-up and the outstanding live
robustness checks remain governed by ADR-0039/0041 and the Phase 17/18 records.

## Owner action before any Phase 19 experiment

1. Finish the Phase 18 participant/live/external-timing and regeneration work; obtain an
   explicit reviewer gate decision permitting dependent experimental work.
2. Supply the actual frozen reference and its file hashes, CV/session scope, approved
   operating rule/budget, W, measured live delay, selected model and participant results.
3. Resolve and review the draft Phase 19 protocol and plan, including feasibility,
   history/horizon values, seeds, folds, compute budget and statistical rules. Archive and
   approve the final preregistration through the owner process; no approval is implied here.
4. Review the engineering changes, make any owner-controlled commit, and rerun checks on
   that clean SHA with verified executor attribution.
5. Explicitly authorize Phase 19 experimental execution. The preparation CLI's `--execute`
   remains disabled; any later enabling change must retain all frozen-input and CV guards.

Reviewer statement and experimental verdict: **PENDING**.
