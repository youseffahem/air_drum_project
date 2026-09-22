# Phase 07 — Inter-annotator agreement (Task 07.5)

**Status: PENDING / NOT VALIDATED.** No human has reviewed any label. There is no inter-annotator agreement, no κ, and no |Δt| distribution to report, and none is claimed anywhere in this repository.

**Protocol:** `P07-QC-1` (`docs/dataset/labeling-rules-v1.0.md` §6) · **Tool:** `tools/review_labels.py:0.7.0` · **Machinery tests:** `tests/labels/test_label_review.py` (`TEST-LABEL-6`, 25 tests), `tests/scripts/test_phase07_scripts.py`

---

## 1. Why it is pending

Agreement is a measurement of two people looking at the same events. It needs:

* **labelled recordings of participants** — none exist (Phase 06 conditions C-06-1…C-06-4: no pilot, no campaign, no person at the camera);
* **a first annotator** — the review pass has not been performed;
* **a second annotator** — an Open Question carried from the phase document (*“Who is the second annotator?”*), unresolved.

No substitute is offered. A machine pass over SYNTHETIC labels is not an annotator, and the scripted self-test below is labelled as machinery evidence wherever it appears.

## 2. What exists and is verified

| Component | Where | Verified by |
|---|---|---|
| Review queue under `P07-QC-1` (100 % of positives and ambiguous, deterministic sampled stride over negatives, excluded material never queued) | `review.review_queue`, `review.SamplingPlan` | `TEST-LABEL-6` |
| Frame-scrub review UI with overlays (reference tip, causal tip, zone, impact surface, `t_impact_est` marker), accept / reject / adjust / defer / note keys | `tools/review_labels.py` `interactive()` | manual path — **needs a person**; the non-interactive path below is what is tested |
| Applying a decision to a label: accept, reject, defer→AMBIGUOUS, adjust | `review.apply_entry` | `TEST-LABEL-6` |
| **Adjusted labels keep their original** (`review.original`) plus one `review.history` item per changed field, with who / when / from / to / why; a second adjustment appends and keeps the *first* original | `review.apply_entry` | `TEST-LABEL-6` |
| Append-only review log, schema-validated per entry | `labels/<session>/review.jsonl`, `schemas/label-review.schema.json` | `TEST-LABEL-6`, `TEST-SCHEMA-1` |
| Second pass never overwrites the first (`review.second_pass`) | `review.apply_entry` | `TEST-LABEL-6` |
| Presence / zone disagreement → `AMBIGUOUS` (rule R6c); timing disagreement recorded, first-pass value kept | `review.apply_entry` | `TEST-LABEL-6` |
| Cohen's κ on event presence; |Δt| median / p95 / max over jointly accepted events; κ reported as **undefined** (not 1.0) when a single category was used throughout | `review.cohen_kappa`, `review.agreement` | `TEST-LABEL-6` |
| Stratification of the agreement subset by zone × hand × segment type × speed band × lighting | `review.stratum_of` | `TEST-LABEL-6` |

### 2.1 Round-trip self-test (SYNTHETIC, scripted — not agreement)

`python tools/review_labels.py --selftest` generates a SYNTHETIC session, labels it, runs two **scripted machine passes** over the queue, and reports the round-trip:

```
[selftest] 6 of 6 labels queued under P07-QC-1
[selftest] QC after two passes: reviewed 6, accepted 4, rejected 1, adjusted 1, pending 0, second_pass 6
[selftest] adjusted synthetic-p07-review-RIGHT-POSITIVE-000002: original kept = True, history entries = 2
[selftest] review log: 12 entries (6 pass 1 + 6 pass 2), append-only
[selftest] agreement (SYNTHETIC, scripted): kappa 0.571, p_observed 0.833, n_pairs 6, n_both_present 1
[selftest] labels with a recorded disagreement: 1 (kinds ['PRESENCE'])
```

> **These are scripted decisions taken by a function, on generated labels.** They validate that the queue, the log, the correction history, the disagreement rule and the κ computation work. They are **not** inter-annotator agreement, and the κ above describes the script, not any annotator.

## 3. What will be reported once the campaign exists

| Quantity | Method | Label when measured |
|---|---|---|
| Cohen's κ, event presence, per stratum and overall | two passes over the agreement subset | MEASURED (subset size and stratification stated) |
| \|Δt\| distribution (median, p95, max) over jointly accepted events | same | MEASURED |
| Agreement **kind** | `INTER_ANNOTATOR` (two annotators) or `SELF_REREVIEW` (same annotator after a stated time gap — the phase document's fallback) | stated explicitly; a self re-review measures consistency, not agreement |
| Review coverage actually applied | `label_set.qc.sampling` | MEASURED |
| Adjustment rate and the distribution of adjustments | `label_set.qc`, `stats.adjustment_rate` | MEASURED |

Carried forward as condition **C-07-3**.


## Clean-tree verification update — 2026-09-22

Verified rerun: `20260922-2043-p07-clean-verification`, owner commit
`1a8e790985bc97810eb28bd26ddc788136a16157`, `git_dirty: false`.
Raw logs and regenerated outputs: `experiments/20260922-203551-p07-clean/`.
See `docs/gates/phase-07-gate-r2.md`. C-07-7 CLOSED; all human/participant
conditions remain PENDING. Historical outputs and evidence classes are preserved.
