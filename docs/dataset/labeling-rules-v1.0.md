# Space Drums — Labelling Rules v1.0

**Phase:** 07 — Task 07.1 · **Status:** IMPLEMENTED as `src/spacedrums/data/labels/rules.py`; every rule has a unit test on synthetic trajectories (`tests/labels/test_label_rules.py`, `TEST-LABEL-1`). **Applied to SYNTHETIC and DEV CAPTURE sessions only — no participant recording exists (Phase 06 C-06-1…C-06-4).**
**Rules version:** `1.0` · **Labels version:** `labels-v1.0` · **Geometry:** `p04-geometry-v1` (Phase 04, unchanged)
**Machine-readable:** `rules.RULES` (the table below, hashed into every label's `provenance.rules_hash`), `rules.Thresholds` (hashed into `provenance.thresholds_hash`).
**Related:** [`../architecture/contracts.md`](../architecture/contracts.md) §6 (`LabelRecord`, `ReferenceTrack`), [`../architecture/causality-tests.md`](../architecture/causality-tests.md) §1.1 (where non-causal artefacts may live), ADR-0002 (physical GT), ADR-0020 (sub-frame interpolation), ADR-0021 (splits), `schemas/label-record.schema.json`.

---

## 1. What a label is, and what it is not

Phase 07 produces **offline ground truth**. Five things are kept apart throughout this document, the code and the artefacts, because collapsing any two of them would invalidate the Phase 05/13/18 evaluation:

| Term | What it is | Where it lives |
|---|---|---|
| **Observed event** | A crossing or approach seen in *some* trajectory. | transient; the input to a rule |
| **Annotated ground truth** | `LabelRecord.t_impact_est` and its class — produced offline from the **reference** trajectory, reviewed by a human. | `labels/<session>/labels.jsonl` |
| **Model prediction** | `TrajectoryPrediction` / `DirectPrediction` from an anticipator. | `records/` |
| **Runtime strike candidate** | `StrikeCandidate` — what the causal geometry produced live. | `records/`, and copied for cross-reference into `LabelRecord.runtime_reference` |
| **Committed strike** | `CommittedStrike` — the live system's decision to make a sound. | `records/`, likewise cross-referenced |

`LabelRecord.runtime_reference` carries the last two with the fixed banner **“REAL-TIME AVAILABLE SIGNALS (not ground truth)”**, and the validator refuses a label whose `t_impact_est` equals the runtime candidate time exactly (`RUNTIME_TIME_COPIED`).

## 2. Non-causality statement

> **Label construction is non-causal by design, and it is the only place in this system where future information may be used.**

The reference trajectory (Task 07.2) is produced by a fixed-interval smoother whose backward pass conditions every sample on *all later* measurements of the session. Labels derived from it therefore encode future observations. That is correct for ground truth and fatal for a model input, so:

* every `LabelRecord` carries `causal: false` (schema `const`);
* every `ReferenceTrack` header carries `causal: false` and `kind: ReferenceTrack`;
* `RecordStreamHeader.record_type` has no value that names a label artefact, so a label file cannot be opened as a record stream at all;
* `.importlinter` contract `labels-are-offline` forbids every causal package (and `features`/`models` when Phase 08 creates them) from importing `spacedrums.data.labels` or `spacedrums.data.splits`;
* `tests/labels/test_label_leakage.py` (`TEST-LABEL-10`) scans the source for imports of the label machinery and for reads of `tracks_reference` from causal packages.

**Real-time available signals** — what an arm may legitimately see at frame `i` — are the records produced causally from frames with `t_capture ≤ t_i`: `FrameSample`, `HandObservation`, `StickObservation`, `TrackState`, `KinematicFeatures`, and its own predictions. Labels are used only (i) as matching references when scoring, after every arm has run, and (ii) as training **targets**.

## 3. The impact definition

An impact is **the Phase 04 entry test evaluated on the reference trajectory**, unchanged:

> the first crossing of a zone's *impact surface* in an **outside-to-inside** transition of the zone shape, whose inward speed `v·n_in` reaches the configured minimum `v_min`, timed by sub-frame interpolation between the two bracketing samples.

Explicitly **not** the definition, in any of the code paths:

* the lowest point of the stroke,
* the instant of velocity reversal,
* any model prediction or runtime candidate,
* a commit decision of the live system.

`impact_position` and `crossing_velocity` come from the bracketing segment's intersection with the surface (so the position lies *on* the surface); `t_impact_est` comes from the estimator chosen in ADR-0020. When the two differ by a fraction of a frame that is the expected behaviour of a better time estimator over the same geometry, and it is recorded in `provenance.interpolation`.

Phase 07 does not weaken the entry test; it *classifies what Phase 04 discarded*. Phase 04's `v_min` filter silently produces no candidate for a too-slow entry. Rule R5 turns the same event into an explicit `NEG_UPWARD_CROSSING`, which is what makes a false-positive analysis possible.

## 4. The rules

Rule ids are written into `LabelRecord.label_rule_id`. Thresholds are the fields of `rules.Thresholds`; **every value is a candidate** until a review pass on real recordings refines it, and the whole set is hashed into `provenance.thresholds_hash` so a change is visible in the artefacts.

| Id | Class | Rule |
|---|---|---|
| **R1** | `POSITIVE` | First outside-to-inside crossing of a zone impact surface by the **reference** tip in an entry episode, with `v·n_in ≥ v_min · (1 + ambiguous_band)`. `t_impact_est` is the sub-frame interpolated crossing instant. |
| **R2** | `POSITIVE` | `intensity_proxy_gt` = the component of the reference tip velocity along the zone's inward normal at `t_impact_est` (**primary**). Secondary proxies — peak speed and peak inward speed in the preceding `intensity_window_s` — are stored in `intensity_secondary` so Phase 11 can compare them; they never silently replace the primary definition. A **proxy**, never a force (REQ-014). |
| **R3** | `NEG_FAKE_SWING` | No entry in the episode; minimum distance to the surface ≤ `fake_swing_max_distance`; peak inward speed during the approach ≥ `fake_swing_min_inward_speed`; the tip is still moving at the closest approach (speed > `stop_speed_max`). |
| **R4** | `NEG_STOP_BEFORE_IMPACT` | No entry; minimum distance inside the band `[stop_band_min, stop_band_max]`; speed at the closest approach decelerated to ≤ `stop_speed_max`. Checked **before** R3 because it is the more specific rule (a stop-short is also close, and was also fast on the way in). |
| **R5** | `NEG_UPWARD_CROSSING` | An outside-to-inside crossing with `v·n_in ≤ 0` or `v·n_in < v_min · (1 − ambiguous_band)`; **and** any inside-to-outside (exit-direction) crossing that is not the recovery of an entry episode already labelled by R1/R5/R6 — the stick leaving a zone after its own strike is part of that episode, not a second event. |
| **R6a** | `AMBIGUOUS` | An entry whose `v·n_in` lies inside the band `v_min · (1 ± ambiguous_band)`. |
| **R6b** | `AMBIGUOUS` | An event whose reference tracking is degraded: valid fraction `< min_valid_fraction`, or mean reference quality `< degraded_quality`, or the window was bridged across a gap / touches a tracking-loss interval. |
| **R6c** | `AMBIGUOUS` | The first and second review passes disagree on **presence, zone or class** (a timing-only difference is recorded, not promoted to ambiguity). |
| **R7** | any | `confidence` = mean reference-sample quality in the ±`event_window_s` window × the fraction of non-interpolated samples. It describes how well the reference trajectory is known around the event, **not** how likely a strike was. |
| **R8** | `NEG_TRACKING_LOSS` | A gap in the reference trajectory longer than the smoother's bridging bound `max_gap_s`, or an interval with no valid observation. An INTERVAL label; no event label is produced inside it. |
| **R9** | `NEG_NO_STRIKE_MOTION` | An interval of at least `no_strike_min_s` in which the tip is tracked and moving (mean speed ≥ `motion_min_speed`) and no zone entry episode occurs. |
| **R10** | `NEG_BETWEEN_ZONES` | An interval of at least `between_zones_min_s` during which the tip leaves the neighbourhood of one zone and reaches the neighbourhood of another (distance to some impact surface ≤ `near_zone_distance` at both ends) with no entry in between. |
| **R11** | `EXCLUDED` | Any label whose time falls inside a segment or session quarantined by the Phase 06 unusable-recording policy. The label is kept with `excluded = true` and the `exclusion_id`, its pre-exclusion class is recorded in `notes`, it is counted in the statistics, and it is used in no metric. |

### 4.1 AMBIGUOUS and EXCLUDED are retained, and never counted

`AMBIGUOUS` and `EXCLUDED` labels stay in the dataset and appear in every statistics table. They are excluded from **both** the numerator and the denominator of every metric; `stats.metric_eligible` is the count that a metric may use, and the ambiguous fraction is reported beside every result (Phase 18).

### 4.2 The cue is a prior, never the label

Phase 06's protocol asks for specific behaviour per segment (`FAKE_SWING`, `STOP_BEFORE_IMPACT`, …). The segment type is copied into every label as context, and **the rules never read it**. A participant who actually strikes the zone during a fake-swing block produces a `POSITIVE`; the review resolves the surprise. This is the phase document's failure mode *“Positive labelled in a fake-swing segment (participant actually struck)”* and it is handled by construction.

## 5. Thresholds v1.0 (candidates)

| Threshold | Value | Unit | Note |
|---|---|---|---|
| `v_min` | from the session config (`geometry.v_min`, currently 0.15) | ROI-norm/s | Phase 04's entry test; not a Phase 07 choice |
| `ambiguous_band` | 0.15 | relative | ±15 % around `v_min` |
| `fake_swing_max_distance` | 0.06 | ROI-norm | |
| `fake_swing_min_inward_speed` | 0.25 | ROI-norm/s | |
| `stop_band_min` / `stop_band_max` | 0.0 / 0.08 | ROI-norm | |
| `stop_speed_max` | 0.10 | ROI-norm/s | “decelerated to near-zero” |
| `approach_window_s` | 0.40 | s | window for the peak-inward-speed statistic |
| `intensity_window_s` | 0.15 | s | window for the secondary intensity proxies |
| `event_window_s` | 0.20 | s | half-width of the quality window |
| `min_valid_fraction` | 0.60 | — | R6b |
| `degraded_quality` | 0.50 | — | R6b |
| `max_gap_s` | 0.20 | s | smoother bridging bound; R8 |
| `no_strike_min_s` | 0.50 | s | R9 |
| `motion_min_speed` | 0.05 | ROI-norm/s | R9 |
| `between_zones_min_s` | 0.30 | s | R10 |
| `near_zone_distance` | 0.12 | ROI-norm | R10 |

**None of these was tuned on participant data, because none exists.** They are starting points chosen so that each rule is exercised on the SYNTHETIC protocol session; the phase document lists the negative-rule thresholds as a *Decision That Must Be Experimentally Validated*, and they are refined after the first review pass (condition C-07-2).

## 6. QC protocol `P07-QC-1`

| Stratum | First pass | Second pass (agreement subset) |
|---|---|---|
| `POSITIVE` | 100 % (a lower rate is permitted only if the volume makes 100 % impossible, and the actual rate is then recorded in `label_set.qc.sampling`) | stratified sample |
| `AMBIGUOUS` | 100 % | stratified sample |
| `NEG_*` | sampled at `negatives_rate` (default 0.2, deterministic stride over the label ids) | stratified sample |
| `EXCLUDED` | not reviewed (quarantined material) | — |

Strata for the agreement subset: zone × hand × segment type × speed band × lighting (`review.stratum_of`).

* A reviewer may **accept**, **reject**, **adjust** (sub-frame time, zone or class) or **defer**. A deferral makes the event `AMBIGUOUS` (R6c).
* An **adjusted label always keeps its original values** in `review.original`, with one `review.history` item per changed field (who, when, from, to, why). The generator's `labeller_id` is never overwritten by a reviewer pseudonym.
* The review log (`labels/<session>/review.jsonl`) is **append-only** and is the audit trail; the label carries the current state.
* The **second pass** is an independent re-review. Where a second annotator is available it is `INTER_ANNOTATOR`; the phase document's fallback — the same annotator after a stated time gap — is permitted and is then labelled `SELF_REREVIEW` in the agreement report, because a self re-review measures consistency, not agreement.
* Agreement is reported two ways and never merged: **Cohen's κ** on event presence, and the **|Δt| distribution** over events both passes accepted. κ is reported as *undefined* rather than 1.0 when both passes used a single category throughout.

**Status: no annotation pass has been performed.** No human has reviewed any label; `docs/reports/phase-07-agreement.md` is PENDING.

## 7. Provenance and versioning

Every label carries the complete provenance needed to reproduce it: rules version and hash, thresholds hash, smoother id and hash, tracker id and hash, geometry version, zone layout, `v_min`, interpolation, config hash, git SHA, the SHA-256 of the session metadata, and both track file references.

> **Versioning rule.** Any change to the rules, the thresholds, the tracker or the smoother produces a **new `labels_version`**. Any change to the accepted sessions produces a new `ds` **minor** version.

`provenance.labels_hash` is the SHA-256 of exactly the machinery fields, so a stale `labels_version` is *detectable*, not merely discouraged: the validator raises `LABELS_HASH_MISMATCH`, and the dataset manifest refuses a label set whose `labels_hash` differs from the dataset's.

## 8. Evidence classes

Labels carry `source_kind` copied from `SessionMetadata.session_kind`. Statistics group by it and **never sum across it** (`schema.evidence_label` raises on a mixed set). The schemas make promotion impossible: a `SYNTHETIC` or `DEV_CAPTURE` label can only carry `ds-none-v0.0` or `ds-v0.0-selftest*`, and can never carry physical ground truth.

## 9. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-22 | Initial rules, thresholds (candidates) and QC protocol. Applied to SYNTHETIC and DEV CAPTURE material only. |
