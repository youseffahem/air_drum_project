# ADR-0015 — Markerless stick pipeline and the primary tip-estimation method (provisional: `GEOM`)

| Field | Value |
|---|---|
| Status | **Accepted as PROVISIONAL** (Phase 03, Tasks 03.4–03.10). The pipeline design and the `stick` config block are accepted; the *primary method* choice is provisional because the tip-error-vs-reference benchmark could not be executed (no annotated reference exists yet; annotation is person-dependent). It becomes final when Task 03.10's error tables exist (condition C-03-1 in the Phase 03 gate record). |
| Date | 2026-09-21 |
| Deciders | Project owner (via the Phase 03 gate), recorded by the Phase 03 submitter |
| Related | ADR-0005 (coordinates), ADR-0014 (hands, grip), REQ-009, REQ-104–106, REQ-211; `docs/reports/phase-03-tip-benchmark.md`; `configs/schema/config.schema.json` (`stick` block, 1.2) |

## Context

The phase requires three `TipEstimator`s behind one interface (`GEOM`, `AXIS_REFINED`, `MARKER`), a benchmark against a reference, and a primary *markerless* choice made on evidence. Development evidence on the Phase 02 dev captures (owner only; L2; DSHOW 640×480) established:

1. **Where the stick is relative to the hand.** In a fist the stick lies *across* the palm, parallel to the knuckle row (MCP 5→17), and its tip exits at the thumb/index side. Both grip-direction candidates named by the phase document (wrist→grip, index MCP→PIP) run *along the fingers*, perpendicular to the stick; the search region then misses the stick entirely (overlay, Task 03.3). A third candidate, **`KNUCKLE_ROW`** (pinky MCP → index MCP), is the default (ADR-0014 §12).
2. **Segmentation / axis sweep (development, exp-5, 273 hand-frames):** axis found on 84–91 % of hand-frames across {closing 1|3 px} × {elongation ≥ 2.0|3.0} × {PCA, RANSAC, HOUGH}; best cell closing 3, elongation 2.0, RANSAC (91 %); median axis support 109–116 px, consistent with Phase 02's 120 px stick at 1.0 m. Candidate defaults were set from this sweep.
3. **Stick edges.** Canny gives the two parallel stick edges ≈ 8 px apart; an inlier band relative to the hand span (`0.3 × span ≈ 8–9 px`) makes the fitted line the centre line between them; the support is the *connected* inlier run (stray in-band pixels — a background edge — cannot extend it).
4. **Benchmark run `20260921-1403-p03-tip-benchmark`** (development tree; reproduced exactly on the clean tree as `20260921-1449-p03-tip-benchmark`, commit `1917788…`, C-03-4; all methods on the same frames; details in the report): on exp-5 (exposure −5) `GEOM` and `AXIS_REFINED` both emit a tip on 272/273 hand-frames; `AXIS_REFINED` falls back to GEOM on 118/273 (43 %); `MARKER` (uncalibrated placeholder colour range, no marker on the sticks) emitted 28 false low-confidence blobs on the teal wall and 0 on the darker capture; the AXIS_REFINED tip lies within 1.1 px (median) / 13.2 px (p90) of the GEOM tip where both exist.
5. **No reference exists.** `tools/annotate_tip.py` is implemented and self-tested, but the annotation requires a person; no marker-equipped recording exists; no new recordings were made in this phase (owner instruction). Tip *error* is therefore PENDING for all three methods.

## Decision

1. **Pipeline (accepted):** grip reference (`hands.grip`, KNUCKLE_ROW) → hand-anchored rotated search region scaled by the hand span (Task 03.4) → Canny/closing/elongated-component candidates with orientation consistency (03.5) → RANSAC line through the grip with span-relative inlier band, PCA refinement, grip-proximity gate, connected support (03.6). All parameters live in `stick.*` (config schema 1.2) and are candidates.
2. **Three `TipEstimator`s (accepted):** `GEOM` = grip + `L·axis_dir` (`L` in ROI-height units, prior 0.27 from Phase 02; optional causal online refinement, default off); `AXIS_REFINED` = far end of the connected support, gated by deviation from GEOM and by minimum support, GEOM fallback with reduced confidence; `MARKER` = HSV blob, **fallback / benchmark only**, WARNING on instantiation, labelled in every record and overlay. `tip_confidence ≤ handedness_score` for every method (ADR-0014 §10 chain).
3. **Primary markerless method — PROVISIONAL: `GEOM`.** Grounds available now: identical presence to AXIS_REFINED; no fallback path; robust when the far end is blurred (design purpose; frame 120 of exp-5 shows a blurred swing); higher tip confidence (p50 0.75 vs 0.66) because AXIS_REFINED's fallback multiplier applies on 43 % of hand-frames; per-hand-frame compute 3.1 ms (p50). **Not** a grounds: accuracy — unknown without the reference. The decision is *reversible by evidence*: if the annotated benchmark shows AXIS_REFINED's non-fallback frames materially more accurate than GEOM, the primary becomes `AXIS_REFINED` and this ADR is superseded.
4. **`MARKER` stays fallback / benchmark** and needs a calibrated colour range before it produces anything meaningful; the uncalibrated placeholder produced false blobs on a teal wall (failure catalogue). No result in this project may be derived from it without the label (REQ-211, I-7).
5. **Learned segmentation** is not opened: the classical pipeline finds the axis on ≥ 84 % of hand-frames at exposure −5; the Open Question stays open until the benchmark's failure catalogue at other lighting conditions exists.

## Alternatives considered

| Alternative | Why not (now) |
|---|---|
| Declare `AXIS_REFINED` primary | 43 % fallback rate at exposure −5 (98.6 % at −6): most of the time it *is* GEOM with a lower confidence; no error evidence that its non-fallback frames are better. |
| Declare no primary until the reference exists | The phase's downstream (05/06 development) needs one method to run; a provisional, labelled choice with an explicit reversal rule is more useful and equally honest. |
| Colour/intensity segmentation instead of edges | Ordinary stick colours (Q9/Q30) and skin/wood similarity; edges worked on the first captures. Kept as a future candidate if the failure catalogue points at edge failures. |
| Fixed-pixel search region | Does not follow the user distance; the span-scaled region does (Task 03.11 evidence: hand span 25–26 px at 1.5 m). |

## Consequences

- `stick` module IMPLEMENTED with `TEST-CONFORM-1` for all three methods, `TEST-STICK-1/2` on synthetic images; `StickObservation` producer exists.
- Every downstream result (Phases 05–20) is labelled with `method_id`; `MARKER` results are labelled fallback/benchmark by construction.
- Task 03.10's error tables, the primary-method finalisation and the failure catalogue at other lighting conditions are gate conditions, not done.
- `stick.geom.l_prior` per-user calibration remains a Phase 14 question (Open Question kept).
