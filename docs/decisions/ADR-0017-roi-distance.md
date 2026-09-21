# ADR-0017 — ROI / user distance for data collection (recommendation on partial evidence; factorial PENDING)

| Field | Value |
|---|---|
| Status | **Proposed — recommendation only.** The distance × lighting factorial of Task 03.11 could not be executed (it needs a person at the camera; no new recordings were made in Phase 03). The recommendation below rests on Phase 02's visibility rows, the Phase 03 exposure finding and single-frame landmark evidence; it becomes *Accepted* when the factorial (C-03-3) is run. ROI `roi.px` stays a **candidate**. |
| Date | 2026-09-21 |
| Deciders | Project owner (Phase 03 gate); recorded by the Phase 03 submitter |
| Related | ADR-0013 (baseline DSHOW 640×480 candidate; Phase 02 gate C-1, C-5, F-3), `docs/protocols/camera-distance-benchmark.md` §7 (decision rule), `docs/reports/phase-03-distance-lighting.md`, REQ-025, REQ-027 |

## Context

Protocol §7: the baseline distance is the largest distance at which both visibility answers are *yes* **and** the tracking-quality columns meet their thresholds. Phase 02 measured visibility *yes/yes* at 0.8, 1.0, 1.5 and 2.2 m (L2, exposure −6). Phase 03 could add to those single frames only what the pipeline computes on them (run `20260921-1405-p03-tip-benchmark`, IMAGE mode): landmarks present at **1.5 m only** (both hands; hand span 25–26 px; axis found on both hands, confidence 0.26 / 0.66, support 31 / 18 px); none at 0.8, 1.0, 1.2 or 2.2 m. Those stills were captured at exposure **−6**, which the Task 03.1 measurement showed collapses landmark presence even on the 6-second swing captures (−5: both hands in 99/171 frames; −6: 10/171; −7: 0/172). The distance rows are therefore **exposure-confounded**: they say nothing reliable about distance.

What the phase *did* establish about scale: at 1.0 m and exposure −5 (exp-5, 171 frames) the hand span is ≈ 28–31 px and the stick axis support ≈ 110–126 px (p50–p90), the search region scales with the span, and the tracker holds VALID/DEGRADED on 233/273 hand-frames.

## Recommendation (to be validated)

1. **Keep the Phase 02 baseline as the data-collection candidate: DSHOW, 640×480, ROI `[40, 20, 560, 440]`, user at ≈ 1.0 m**, lens height 0.75 m, tilt 0°. Grounds: visibility yes/yes; the only distance with a full 6-s tracking capture; hand span ≈ 30 px and stick ≈ 120 px give the segmentation a workable scale; Phase 02 found both hands and all four MVP zone paths inside this ROI at 1.0 m.
2. **Exposure for L2 must be −5, not −6** (Phase 02 F-3 resolved in the direction of the owner's L2 selection): −6 removes the hands for the landmark estimator far more than it gains in sensor rate. The C-5 freeze must carry −5 for L2 and a measured value per other lighting condition.
3. **Do not move to 1.5 m on the single-frame evidence**: one frame at one exposure is not a rate; the 1.5 m detection is consistent with the hands being smaller but better lit in that frame, not with 1.5 m being better.
4. **The factorial (C-03-3)** = the Task 03.11 movement script at {0.8, 1.0, 1.2, 1.5} m × {L1, L2, L3 …} with exposure set per lighting per protocol, ≈ 10 s per cell, developer only; it also hosts the deferred Task 03.2 crossing capture (P-03.2-1). `scripts/benchmark_tip_methods.py --capture <cell>` fills the table rows (presence rate, axis confidence, swap/override rates, state histogram; tip error once annotated).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Recommend 1.5 m (the only distance with landmarks on the stills) | Confounded by exposure; one frame; would move the participant farther without evidence that tip resolution suffices (stick support 18–31 px in that frame vs 110 px at 1.0 m). |
| MSMF 1280×720 for more pixels on the stick | ≈ 40 ms hand-over lag (ADR-0013); no tracking evidence yet that 640×480 is the resolution bottleneck — the exposure is. |
| Freeze the ROI now | Protocol §7 requires the tracking columns; freezing a candidate would misuse `meta.status: frozen`. |

## Consequences

- `roi.px` and the camera fragment remain candidates; Phase 02 C-5 (frozen capture config) cannot be closed at the Phase 03 gate on this evidence → carried as a Phase 03 gate condition.
- Phases 05–06 development may proceed at the 1.0 m / −5 candidate; the dataset protocol (Phase 06) must not start recording participants before the factorial fixes the distance and the per-lighting exposure.
