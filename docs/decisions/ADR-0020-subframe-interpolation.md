# ADR-0020 — Sub-frame interpolation of the impact crossing time

**Status:** Accepted (provisional) — Phase 07, Task 07.4 · 2026-09-22
**Deciders:** submitter (evidence assembly), project owner (review pending)
**Supersedes:** the *Pending Architecture Decision* left open by Phase 04 (`docs/reports/phase-04-geometry-audio.md`, sub-frame timing)
**Related:** `docs/dataset/labeling-rules-v1.0.md` §3, `src/spacedrums/data/labels/interp.py`, `docs/reports/phase-07-interpolation.md`, ADR-0002 (physical GT), ADR-0007 (trajectory-first geometry)

---

## Context

Phase 04 detects an impact as an outside-to-inside crossing of a zone's impact surface and times it by **linear** interpolation between the two frames that bracket the crossing (`geometry.impact.crossing_time`). At 30 FPS a frame is 33 ms, and `t_impact_est` is the reference against which every lead-time and timing-error result in README §10 is measured, so a systematic bias of a few milliseconds in the estimator is a systematic bias in every one of those results. Phase 04 recorded the choice as Pending and asked Phase 07 to decide it.

A drum stroke near the surface is well approximated by a constant-acceleration approach. On such a path the straight line through two bracketing samples of the signed distance `d(t)` crosses zero **late** by approximately `a·dt² / (8·|v|)`; a parabola through three samples is exact.

## Decision rule, declared before the run

Fixed in `interp.DECISION_RULE` and in the phase document's *Experimental Design* section **before any comparison was executed**:

> Choose the estimator with the smaller **spread** (IQR of the signed error against the best available reference). If the two spreads are within 10 % of each other, choose the one with the smaller **|bias|**. If both are within 10 %, keep **LINEAR**, because it is what Phase 04 already implements and the simpler estimator carries fewer assumptions.

Reference, in order of preference:

1. `t_impact_phys` on the pad + microphone subset (Task 07.6) — **PENDING**, no such recording exists;
2. manual frame annotations near impacts (`tools/annotate_tip.py`) — **PENDING**, person-dependent;
3. the **analytic** crossing time of a SYNTHETIC trajectory — available now.

## Evidence

Only reference (3) could be executed. `scripts/subframe_interpolation.py` generates 24 strokes varying descent duration, depth and the phase of the crossing inside the frame interval, samples them at 30 FPS, and compares both estimators against the analytic crossing (`docs/reports/phase-07-interpolation.md`, regenerable).

**Evidence class: SYNTHETIC.** Table 1 isolates the estimator (no smoother in the path); Table 2 repeats it through the reference smoother.

| Table | Estimator | n | bias (median) | IQR | max abs |
|---|---|---:|---:|---:|---:|
| 1 — estimator only | LINEAR | 24 | −0.734 ms | 2.047 ms | 3.821 ms |
| 1 — estimator only | **QUADRATIC** | 24 | **0.000 ms** | **1.067 ms** | **1.832 ms** |
| 2 — through `rts-kalman-cv-v1` | LINEAR | 24 | −0.660 ms | 1.401 ms | 5.033 ms |
| 2 — through `rts-kalman-cv-v1` | **QUADRATIC** | 24 | −0.226 ms | 1.284 ms | 1.435 ms |

Both tables select `QUADRATIC` under the pre-declared rule (Table 1 on IQR, Table 2 on |bias| with IQRs within 10 %). The decision is taken on **Table 1**, the table that isolates the estimator under test.

## Decision

**`t_impact_est` is estimated with the QUADRATIC sub-frame estimator** (root of the parabola through three samples of the signed distance, inside the bracketing interval), falling back to LINEAR when a third sample is unavailable. The fallback is visible: `CrossingEstimate.method` and `provenance.interpolation` record which estimator produced the value.

Scope:

* This changes **label construction only**. `spacedrums.geometry` is untouched: the live pipeline still times a runtime candidate with `geometry.impact.crossing_time` (linear), because the causal path has no third sample after the crossing without waiting a frame — waiting would add latency to the very quantity the project is trying to reduce.
* The asymmetry is deliberate and is itself a measured quantity: the *offline* estimate is the reference, the *online* one is what the system achieves, and the difference belongs in the Phase 18 error budget rather than being hidden by making both estimators the same.

## Status: why "provisional"

The decision rule was pre-declared and applied honestly, but the only available reference is a generated trajectory. A synthetic comparison measures how the two estimators behave on a known parabolic approach sampled at the frame rate; it is **not** a measurement of the bias on this project's recordings, where the tip estimate carries detector noise, motion blur and a real (non-parabolic) stroke shape.

**PENDING / NOT VALIDATED:** the comparison against `t_impact_phys` (pad + microphone) and against manual frame annotations near impacts. Both need recordings that do not exist (Phase 06 conditions C-06-1…C-06-4). Condition **C-07-4** carries this forward.

## Consequences

* Positive: the estimator with the smaller spread and no measurable bias on a known approach; the choice is recorded, reproducible and re-checkable.
* Negative: it needs one sample beyond the bracket, so a crossing at the very end of a reference segment falls back to LINEAR. The fallback is recorded per event, not silent.
* Reverting to LINEAR after the participant-data comparison is a **`labels_version` bump** (`labels-v1.1`), because `provenance.interpolation` is part of `labels_hash`. Existing labels stay readable and are simply of the older version; the dataset manifest refuses to mix the two.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep LINEAR everywhere | The pre-declared rule selected QUADRATIC on the only evidence available; keeping LINEAR would mean ignoring the rule after seeing the result. |
| Use the smoother's continuous model to solve for the crossing analytically | Ties the impact time to the smoother's motion model rather than to the observed geometry, and would change with every smoother re-tuning. The bracketing-sample estimators depend only on the sampled trajectory. |
| Cubic / higher-order interpolation | More samples means a wider window around a sharp reversal — the same failure mode as an over-wide smoother window (Task 07.2). Not tested, not adopted. |
| Change the live geometry to quadratic too | Would require a frame of look-ahead in the causal path. Forbidden by the causality contract and self-defeating for an anticipation project. |
