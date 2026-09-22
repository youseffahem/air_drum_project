# Phase 07 — Dataset Creation & Labelling

## Status

**IMPLEMENTED (machinery) / PENDING (participant-dependent evidence)** — 2026-09-22.

Tasks 07.1, 07.2, 07.3, 07.4, 07.5, 07.6, 07.7, 07.8, 07.9 and 07.10 are implemented, tested and
documented; every one of them is exercised end to end on a SYNTHETIC full-protocol session and on
the existing DEV CAPTURE. **No participant recording exists** (Phase 06 conditions C-06-1…C-06-4),
so everything that is a measurement *of participants* — the review pass, inter-annotator agreement,
the acoustic validation, the frozen splits, `ds-v1.0` and its label counts — is **PENDING / NOT
VALIDATED**, not reported, and not estimated. See `docs/gates/phase-07-gate.md`.

## Purpose

Turn accepted raw recordings (`ds-raw-v1.0`) into a labelled, versioned, participant-split dataset (`ds-v1.0`): define and implement the labelling rules for ground-truth impacts (time, zone, position, intensity proxy), negative segments, and ambiguous events; build the QC/review tool; validate geometric impact times against the optional acoustic ground truth; freeze participant-level splits; write the dataset card. **Label generation is offline and may use the full recording (non-causal); this is the only place future information is permitted and it is stated explicitly.**

## Why This Phase Exists

Every metric in README §10 is computed against ground-truth impacts. If labels are inconsistent, leak participant identity across splits, or silently depend on the live tracker's causal noise, then lead-time, FP, and timing-error results are meaningless. Explicit labelling rules (Q49), QC, and participant-level separation (README §13) make the evaluation defensible.

## Relationship to Research Contribution

- Defines `t_impact_est` ground truth: the reference against which prediction lead time and timing error are measured.
- Provides the only physical reference (`t_impact_phys`, pad+mic subset) to quantify how far the geometric estimate is from a physical impact.
- Labels negatives (fake swings, stops) that make the FP analysis possible.
- Fixes the participant-level splits used by every ML phase — the same folds for baseline and temporal models.

## Inputs

- `ds-raw-v1.0` (raw video, `FrameSample` meta, recorded causal records, timing, metadata, optional audio).
- Phase 04 geometry (impact surfaces, entry test, sub-frame interpolation).
- Phase 03 tracker (re-run offline; plus an offline non-causal smoother for labels only).
- Phase 06 segment types and exclusion log.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-014 (ground-truth proxy), REQ-038 (labels), REQ-048 (QC), REQ-049 (splits, rules); contributes to REQ-015.

## Expected Outputs

- Labelling Rules document (`labeling-rules-v1.0.md`).
- Offline label generator (re-track → non-causal smooth → geometry → candidate events).
- QC/review tool and review log; inter-annotator agreement on a subset.
- `LabelRecord` files per session; `ds-v1.0` manifest; dataset card.
- Split files: `splits/ds-v1.0/{test_participants.json, cv_folds.json}`.
- Pad+mic validation report (`t_impact_est` vs. `t_impact_phys`).
- Label statistics report (counts per class/segment/participant — MEASURED).

## Dependencies

- Phase 06 Exit Gate.

## System Components

- `src/spacedrums/data/labels/{generate.py, smooth.py, rules.py, schema.py}`
- `src/spacedrums/data/splits.py`
- `tools/review_labels.py` (frame scrub, overlay, accept/reject/adjust, notes)
- `scripts/{build_labels, validate_labels, label_stats, build_splits, build_dataset_manifest, acoustic_onset}.py`
- `docs/dataset/labeling-rules-v1.0.md`, `docs/dataset/dataset-card-ds-v1.0.md`

## Architecture

```
raw video ──► offline re-track (Phase 03 causal tracker, frozen version) ──► causal TrackState (as the live system would see)
         ──► offline NON-CAUSAL smoother (labels only; e.g. RTS smoother / centred window) ──► reference tip trajectory
reference trajectory ──► Phase 04 geometry (entry test, sub-frame crossing) ──► candidate impact events
segment cues + candidate events ──► rules.py ──► LabelRecords (POSITIVE / NEGATIVE-* / AMBIGUOUS / EXCLUDED)
LabelRecords ──► review tool (human) ──► accepted labels (+ review log)
optional audio ──► acoustic onset detector ──► t_impact_phys ──► validation vs. t_impact_est (pad subset only)
accepted labels + metadata ──► splits (participant-level) ──► ds-v1.0 manifest + dataset card
```

Two tip trajectories exist per session: the **causal** one (model input, identical to live) and the **reference** one (label source). Both are stored; the reference one is never fed to any causal component.

## Detailed Tasks

### Task 07.1 — Labelling Rules v1.0
- **What:** Write the rules:
  - **Positive impact (GT):** first valid downward/inward entry of the *reference* tip trajectory through a zone's impact surface per Phase 04, with `t_impact_est` by sub-frame interpolation; fields: `t_impact_est`, `zone_id`, `impact_position`, `crossing_velocity`, `intensity_proxy_gt`, `hand_id`, `episode_id`, `segment_id`, `confidence` (from reference-tracking quality around the event).
  - **GT intensity proxy:** component of the reference tip velocity along the inward normal at `t_impact_est` (primary definition; alternatives — peak speed in the preceding window — stored as secondary fields so Phase 11 can compare).
  - **Negative labels (segment-level and event-level):** `NEG_NO_STRIKE_MOTION`, `NEG_FAKE_SWING` (approach with speed above a threshold, min distance to surface below a threshold, no entry), `NEG_STOP_BEFORE_IMPACT` (deceleration to near-zero speed within a distance band above the surface, no entry), `NEG_BETWEEN_ZONES`, `NEG_UPWARD_CROSSING` (entry through the surface with `v·n_in < v_min` or exit-direction crossing), `NEG_TRACKING_LOSS` (interval), thresholds tunable and recorded.
  - **Ambiguous:** entries with `|v·n_in|` near `v_min` (band tunable), events during `DEGRADED` reference tracking, events where the review disagrees → `AMBIGUOUS`: excluded from metric numerators/denominators, retained in the dataset, counted in the report.
  - **Excluded:** events inside quarantined segments.
  - **Non-causality statement:** the reference trajectory uses future frames; it is used only to produce labels.
- **Why:** Q49 explicit rules; Q36–39 definitions; Q48 negatives.
- **Depends on:** Phase 04 geometry; Phase 06 segment types.
- **Evidence:** Versioned document; every rule has a unit test on synthetic trajectories.

### Task 07.2 — Offline Re-Tracking and Reference Smoother
- **What:** Re-run the frozen Phase 03 tracker on raw video (causal outputs, stored as `tracks_causal.jsonl`); implement the non-causal reference smoother (candidates: RTS smoother over the Kalman model, or centred Savitzky–Golay; gaps interpolated only if shorter than a tunable bound, else the interval is `NEG_TRACKING_LOSS`); store `tracks_reference.jsonl`. Also compute a **frame-annotation reference** on a stratified subset (manual tip clicks, reuse Phase 03 tool) to estimate reference-trajectory error near impacts.
- **Why:** Labels must come from the best available trajectory; the causal trajectory's noise must not define ground truth.
- **Depends on:** Phase 03 tracker (frozen version hash), Phase 06 raw data.
- **Evidence:** Both track files per session; smoother unit tests; manual-annotation error near impacts (MEASURED, subset size reported).

### Task 07.3 — Label Generator
- **What:** Apply Phase 04 geometry to the reference trajectory; apply rules; emit `LabelRecord`s with rule provenance (`rule_id`, thresholds, smoother id, tracker hash, geometry version).
- **Why:** Reproducible labels from raw data + versioned rules.
- **Depends on:** 07.1, 07.2.
- **Evidence:** Re-running the generator on the same inputs reproduces identical labels (hash check).

### Task 07.4 — Sub-Frame Interpolation Comparison
- **What:** On the reference trajectory (denser effective sampling via the smoother's continuous model, or on the pad+mic subset with `t_impact_phys`), compare linear vs. quadratic sub-frame crossing estimates: bias and spread vs. the best available reference. Choose the primary interpolation (ADR).
- **Why:** Phase 04 left this Pending; it affects every timing metric.
- **Depends on:** 07.2, 07.6.
- **Evidence:** Comparison table (MEASURED); ADR.

### Task 07.5 — Review Tool and QC Protocol
- **What:** Tool: scrub frames around each candidate event with overlays (reference tip, causal tip, zone, surface, `t_impact_est` marker), keyboard accept/reject/adjust (adjust = shift `t_impact_est` by fractional frames or change zone; adjusted labels keep the original + reason), notes. QC protocol: 100% review of positives (or a defined sampling rate if volume is too high — rate recorded), 100% review of ambiguous, sampled review of negatives (rate recorded); second annotator re-reviews a stratified subset; agreement (event-level Cohen's κ; timing agreement as |Δt| distribution) reported.
- **Why:** Q49 quality; labelling rules alone cannot catch tracker failures.
- **Depends on:** 07.3.
- **Evidence:** Review log; agreement report (MEASURED).

### Task 07.6 — Acoustic Onset Ground Truth (pad+mic subset)
- **What:** Onset detection on the microphone track (candidate: spectral flux / energy threshold with backtracking to the onset sample), converted to `t_mono` via sync markers; pair with the geometric event on the pad zone; report `t_impact_phys − t_impact_est` distribution (bias, spread) and the fraction of pairings; document microphone-path latency bound.
- **Why:** The only physical reference; quantifies the geometric estimate's offset (needed to interpret "sound before impact" claims in Phase 18).
- **Depends on:** Phase 06 Task 06.6 data.
- **Evidence:** Validation report (MEASURED) or PENDING with the pilot reason if the condition was dropped.

### Task 07.7 — Label Schema and Validation
- **What:** `LabelRecord` schema (fields above + `dataset_version`, `labels_version`, `review_status`, `reviewer_id`, `adjusted:bool`); validator checks referential integrity with sessions/segments, monotone times, one positive per episode, no positives in quarantined segments.
- **Why:** Machine-checkable integrity before any training.
- **Depends on:** 07.3, 07.5.
- **Evidence:** Validator passes on all sessions; violations log empty or explained.

### Task 07.8 — Participant-Level Splits
- **What:** Given the actual participant count `P`:
  - Freeze a **held-out test set** of participants (candidate: a fixed fraction, chosen to keep ≥ 2–3 participants in test if `P` allows; the exact number decided from `P` and recorded), stratified by experience level/handedness if possible; sessions of a participant are never split.
  - Build **participant-grouped K-fold CV folds** on the remaining participants for model selection (K decided from `P`; recorded).
  - Leakage checks: participant sets disjoint; no session in two folds; feature-normalisation statistics computed per fold on training participants only (rule for Phase 08).
  - The same split files are mandatory for Phases 09–19.
- **Why:** README §13; Q49.
- **Depends on:** 07.7.
- **Evidence:** Split files; leakage test suite passes; split rationale in the dataset card.

### Task 07.9 — Label Statistics Report
- **What:** Counts per label class, per zone, per hand, per segment type, per participant; distribution of `intensity_proxy_gt`; tracking validity around positives; ambiguous fraction; review adjustments; distance/lighting strata sizes.
- **Why:** Dataset transparency; identifies class imbalance for Phase 09/10 loss design.
- **Depends on:** 07.7.
- **Evidence:** Report with MEASURED counts.

### Task 07.10 — Dataset Manifest, Versioning, and Dataset Card
- **What:** `ds-v1.0` manifest: raw manifest reference, tracker hash, smoother id, rules version, labels version, split files, per-file hashes; dataset card: purpose, collection protocol, participants (aggregate, pseudonymised), label definitions, known limitations (e.g. geometric GT, no depth, single camera), intended use, licence/consent scope, reuse conditions (Q49), change log. Versioning rule: any change to rules/tracker/smoother → new `labels_version`; any change to accepted sessions → new `ds` minor version.
- **Why:** Reproducibility and potential reuse.
- **Depends on:** All above.
- **Evidence:** Manifest + card; hash reproducibility check.

## Data Requirements

- All accepted sessions from `ds-raw-v1.0`.
- Manual annotation subset for reference-trajectory error (size reported).
- Second annotator availability for the agreement subset (Open Question: who).
- Pad+mic subset (if recorded).

## Algorithms / Technical Approach

- Reference smoothing: RTS smoother (fixed-interval) over the Phase 03 Kalman model, or centred polynomial filter — candidate choice by comparison to manual annotations.
- Impact detection: Phase 04 geometry, unchanged.
- Negative rules: threshold logic on approach speed, minimum distance to surface, deceleration profile — thresholds tunable, recorded.
- Acoustic onset: energy/spectral-flux onset with sub-sample backtracking; sync via clap cross-correlation.
- Agreement: Cohen's κ for event presence; |Δt| statistics for timing.

## Interfaces / Contracts

- `LabelRecord` schema (Task 07.7) — consumed by Phases 08–19.
- `tracks_causal.jsonl` (model inputs) and `tracks_reference.jsonl` (labels only; must never be loaded by feature/model code — enforced by a naming/path rule and a test in Phase 08).
- Split files format (Task 07.8).

## Tests

- **Unit:** each labelling rule on synthetic trajectories; smoother on synthetic signals; onset detector on synthetic clicks; split disjointness.
- **Integration:** generator determinism (hash); validator on all sessions; review-tool round-trip (adjusted label retains original).
- **Leakage tests:** participant disjointness; session integrity; a test that fails if any file under `features/` or `models/` imports or reads `tracks_reference`.

## Measurements

| Quantity | Method | Label |
|----------|--------|-------|
| Reference-trajectory error near impacts vs. manual annotation | Task 07.2 | MEASURED (subset) |
| Linear vs. quadratic sub-frame crossing bias/spread | Task 07.4 | MEASURED |
| `t_impact_phys − t_impact_est` (pad subset) | Task 07.6 | MEASURED or PENDING |
| Inter-annotator agreement (κ, |Δt|) | Task 07.5 | MEASURED |
| Label counts per class/zone/hand/segment/participant | Task 07.9 | MEASURED |
| Ambiguous fraction; adjustment rate | Task 07.9 | MEASURED |

## Experimental Design

- **Interpolation comparison:** paired comparison on the same events; report bias and IQR; choose by lower spread unless bias differs materially (decision rule recorded before looking at results).
- **Acoustic validation:** paired differences per event; report bias, spread, and the microphone-path latency bound; no claim that geometric impact equals physical impact — only the measured offset.
- **Agreement:** stratified subset (by zone, speed, lighting); κ and |Δt|.

## Acceptance Criteria

1. Labelling rules v1.0 documented, tested, and applied; label provenance stored.
2. Reference and causal tracks stored separately; leakage test in place.
3. Review completed per QC protocol; agreement reported.
4. Acoustic validation reported (or PENDING with reason).
5. Interpolation choice recorded (ADR).
6. Participant-level splits frozen; leakage tests pass.
7. `ds-v1.0` manifest, label statistics, and dataset card complete.

## Definition of Done

- All acceptance criteria; label validator clean; gate record PASS; integrity checklist applied (counts reported are actual; no "accuracy" of anything claimed).

## Risks

- Small participant count makes a fixed test set statistically weak → report per-participant results and CIs in Phase 18; consider nested CV (decision recorded in the split rationale).
- Reference smoother may over-smooth sharp reversals at impact → validate against manual annotation near impacts; tune window.
- Reviewer fatigue/bias → second-annotator subset; clear rules.
- Acoustic sync residual may be comparable to the quantities of interest → report it as a bound; do not over-interpret.

## Failure Modes

- Labels generated from the causal track by mistake → provenance fields + leakage test.
- Positive labelled in a fake-swing segment (participant actually struck) → rules are observation-based, cue is only a prior; review resolves.
- Splits accidentally share a participant across folds → leakage test.

## Fallback Strategy

- If the pad+mic condition was not recorded or sync failed, `t_impact_phys` stays PENDING and the dataset card states that ground truth is geometric only.
- If a second annotator is unavailable, self-re-review after a time gap with the caveat stated; agreement labelled accordingly.

## Artifacts Produced

- `docs/dataset/labeling-rules-v1.0.md`, `docs/dataset/dataset-card-ds-v1.0.md`
- `src/spacedrums/data/labels/`, `src/spacedrums/data/splits.py`, `tools/review_labels.py`, scripts
- `schemas/label-record.schema.json`
- `data/labels/<session>/labels.jsonl`, `tracks_causal.jsonl`, `tracks_reference.jsonl`
- `data/splits/ds-v1.0/*.json`, `data/manifests/ds-v1.0.json`
- `docs/reports/phase-07-label-stats.md`, `phase-07-agreement.md`, `phase-07-acoustic-validation.md`, `phase-07-interpolation.md`
- `docs/decisions/ADR-<n>-subframe-interpolation.md`, `ADR-<n>-split-design.md`
- `docs/gates/phase-07-gate.md`

## Exit Gate

Reviewer verifies rules, QC evidence, splits, manifest, dataset card. PASS → Phase 08.

## What Must NOT Be Done Yet

- No feature statistics or model training on any split.
- No use of `tracks_reference` outside label generation.
- No dataset release (consent and Phase 23 decision).
- No reporting of baseline performance (Phase 09).

## Open Questions

- Who is the second annotator?
- Held-out test-participant count given actual `P` (decide on evidence in Task 07.8).
- Should `AMBIGUOUS` events be used as soft negatives in training (Phase 09/10 option)? — record as an experiment option, default excluded.

## Decisions That Must Be Experimentally Validated

- Reference smoother choice and window (Task 07.2).
- Negative-rule thresholds (fake swing / stop-before-impact) (Task 07.1, refined after review).
- Sub-frame interpolation method (Task 07.4).
- Test-set size and K for CV (Task 07.8).
