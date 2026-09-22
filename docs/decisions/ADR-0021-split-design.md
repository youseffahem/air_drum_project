# ADR-0021 — Participant-level split design (`P07-SPLIT-1`)

**Status:** Accepted as a **rule**; no split is frozen (P = 0) — Phase 07, Task 07.8 · 2026-09-22
**Deciders:** submitter (rule), project owner (freeze, when participants exist)
**Related:** README §13, Q49 / REQ-049, `src/spacedrums/data/splits.py`, `schemas/split-file.schema.json`, `docs/dataset/labeling-rules-v1.0.md`

---

## Context

Every result from Phase 09 on is reported on a split of this dataset. Two things must be true of that split, and both are easy to get wrong silently:

1. **No participant may appear in more than one part.** A person's stroke style, stick, height and camera distance are shared across all of their sessions; a session-level split would let a model memorise the person and report it as skill.
2. **The split must be fixed before results are seen.** Choosing the number of held-out participants, or K, after looking at a metric turns a held-out set into a tuning set.

The complicating fact is that the participant count `P` is not known yet and will be small. A rule that only works for `P ≥ 20` is useless here; a rule invented once `P` is known is not a rule.

## Decision

The split is produced by rule **`P07-SPLIT-1`**, a function of `P` alone, fixed in code (`splits.plan_for`) **before any participant exists**:

| `P` | `n_test` | `K` | Note |
|---:|---:|---:|---|
| 0 | 0 | 0 | nothing can be split; a participant split cannot be frozen |
| 1–3 | 0 | `P` | too few to hold any participant out: **leave-one-participant-out only**, and every result is reported per participant |
| 4–7 | 1 | `min(4, P−1)` | one held-out participant; the test set is acknowledged as statistically weak |
| 8–11 | 2 | 5 | |
| 12–19 | 3 | 5 | |
| ≥ 20 | `round(0.2·P)` | 5 | held-out fraction 20 % |

Further rules, all machine-checked and written into both split files:

* **Grouping.** Every session of a participant travels with that participant. `sessions_by_participant` is recorded in the file, so the grouping is visible rather than implied.
* **Determinism.** Participants are ordered by pseudonym and assigned by a seeded permutation — `sorted by SHA-256(seed | salt | pseudonym)`, not `random.Random`, so the order is reproducible from the recorded inputs by anyone, in any Python build.
* **Stratification.** The held-out participants are spread over strata (experience, handedness) when those attributes were collected. When they were not, `stratify_keys` is empty and the rationale says *“No stratification was possible: the participant attributes were not collected.”* — never a guess.
* **Leakage checks.** `participants_disjoint`, `sessions_disjoint`, `no_session_in_two_folds`, `test_not_in_any_fold`, `every_session_assigned`. A frozen split with `all_passed = false` is refused by the schema **and** by the writer.
* **Normalisation rule for Phase 08**, stored in every split file so it cannot be forgotten: *feature-normalisation statistics are computed per fold on the TRAIN participants of that fold only — never on the validation participants, never on the held-out test participants, never on the whole dataset.*
* **One `split_hash`** over (rule id, dataset version, labels version, seed, participants, test participants, stratify keys, session grouping), shared by `test_participants.json` and `cv_folds.json` so the two can never disagree.
* **Kind gating.** A SYNTHETIC or DEV_CAPTURE roster may only produce a `ds-v0.0-selftest*` split and can never be frozen; participant or pilot material never enters a self-test split.
* **No empty participant split.** `data/splits/ds-v1.0/` must not exist before the participants do (the labelled-dataset analogue of the Phase 06 empty-manifest refusal).

Deviating from the table is possible (`--n-test`, `--k`) and **records a deviation**: the values land in the file beside `rule_id`, so a departure from the rule is visible in the artefact.

## Status

**No split is frozen. `P = 0`.** No participant has been recorded (Phase 06 conditions C-06-1…C-06-4), so `data/splits/ds-v1.0/` does not exist and cannot be written. What exists is the rule, the builder, the leakage checks and their tests (`tests/labels/test_dataset_splits.py`, 36 tests), plus a self-test split built from a SYNTHETIC roster of ten pseudonyms — machinery evidence, not a participant split.

## Consequences

* The number of held-out participants is a consequence of `P`, decided before any result exists. If the campaign yields, say, 6 participants, the split is 1 test + 4 folds and the weakness is stated rather than discovered later.
* For `P ≤ 3` there is **no held-out test set at all**. Phase 18 then reports leave-one-participant-out results per participant with confidence intervals, and no "test-set performance" number is reported, because there would be no test set. That is a real limitation of a small campaign and the rule makes it explicit instead of manufacturing a one-person test set.
* **Small-`P` caveat** (phase document, *Risks*): with few participants a fixed held-out set is statistically weak. Phase 18 reports per-participant results and CIs, and nested cross-validation stays on the table. The caveat text travels inside every split file's `rationale`.
* Re-running the builder on the same roster and seed reproduces the split exactly; changing the roster (a withdrawal, an added session) changes `split_hash`, which is what forces a new `ds` minor version rather than a silent re-split.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Random session-level split | Leaks participant identity between train and test; forbidden by README §13. |
| Decide `n_test` and `K` when `P` is known | Indistinguishable, after the fact, from choosing them to suit a result. The table removes the choice. |
| Always leave-one-participant-out, no held-out set | Loses the one clean estimate of generalisation to an unseen person whenever `P` is large enough to afford it. The table uses LOPO only where a held-out set is not affordable. |
| Stratify on performance (e.g. strike rate) | Stratifying on anything derived from the labels couples the split to the outcome. Only collected participant attributes are used. |
| `random.Random(seed).shuffle` | Deterministic, but its stream is a CPython implementation detail. A hash order can be reproduced from the recorded inputs by any implementation. |
