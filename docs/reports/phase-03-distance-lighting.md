# Phase 03 — Tracking Quality vs Distance and Lighting (Task 03.11)

| Field | Value |
|---|---|
| Status | **PARTIAL — factorial PENDING.** The distance × lighting protocol (`docs/protocols/camera-distance-benchmark.md` §7, Phase 02 Task 02.7 tracking columns) needs a person at the camera for a movement script per cell; no new recording was made in Phase 03 (owner instruction). What could be measured from the existing captures is below and is labelled; the recommendation is recorded as **ADR-0017 (Proposed)**. |
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-21 |
| Runs | clean-tree (commit `1917788…`, `git_dirty: false`): `20260921-1449-p03-tip-benchmark` (swing captures + distance stills, IMAGE mode for stills), `20260921-1447/1448/1452-p03-hands-check-*`; development originals: `20260921-1405`, `1403`, `1003/1004`, `1046-*` — identical detection outputs (benchmark report §6) |
| Tooling | `scripts/benchmark_tip_methods.py --distance` (stills) and `--capture <cell>` (movement-script cells); fills presence rate, axis confidence, support, override/ambiguity rates, tracker histogram; tip error once annotated |

## 1. Distance rows (single Phase 02 stills, L2, exposure −6, DSHOW 640×480, IMAGE-mode landmarker) — MEASURED, 1 frame each (clean-tree run `20260921-1449-p03-tip-benchmark`; identical to the development run)

| distance (m) | visibility (Phase 02, owner) | landmarks LEFT / RIGHT | handedness score L / R | hand span px L / R | axis found L / R | axis confidence L / R | axis support px L / R | tracking quality |
|---|---|---|---|---|---|---|---|---|
| 0.8 | yes / yes | no / no | — | — | — | — | — | not measurable on this frame (exposure) |
| 1.0 | yes / yes | no / no | — | — | — | — | — | idem |
| 1.2 | (dropped in Phase 02) | no / no | — | — | — | — | — | idem |
| 1.5 | yes / yes | **yes / yes** | 0.89 / 0.98 | 24.9 / 26.0 | yes / yes | 0.26 / 0.66 | 31.1 / 18.3 | 1-frame evidence only |
| 2.2 | yes / yes | no / no | — | — | — | — | — | idem |

Interpretation (honest): these stills were taken at exposure −6, the setting that the Task 03.1 measurement showed removes the hands from the estimator on the swing captures (−6: both hands in 10/171 frames; −7: 0/172; −5: 99/171). The absence of landmarks at 0.8–1.2 m and 2.2 m is therefore attributable to under-exposure, not to distance; the single detection at 1.5 m is one frame. **The distance columns cannot be filled from these stills**; they need the protocol's movement script per cell at the exposure of each lighting condition.

## 2. What the swing captures add (1.0 m, L2; 6 s each; from the Task 03.1/03.2 and benchmark runs)

| exposure | frames | both hands present (TEMPORAL identity) | label overrides (rate / detected frame) | ambiguous frames | GEOM present | axis found | tracker GEOM RIGHT VALID / DEGRADED / INVALID / STALE |
|---|---|---|---|---|---|---|---|
| −5 | 171 | 103 | 4 (0.024) | 0 | 272/273 hand-frames | 248/273 | 143 / 25 / 3 / 0 |
| −6 | 171 | 32 | 28 (0.25) | 4 | 144/144 | 44/144 | 11 / 66 / 2 / 92 |
| −7 | 172 | 0 | 0 | 0 | 0/0 | 0 | 0 / 0 / 172 / 0 |

Hand span at 1.0 m / −5: ≈ 28–31 px (landmark-based, replaces Phase 02's ±30 px click estimate); stick axis support p50 110 px, p90 126 px (Phase 02 click: 120 px).

## 3. Lighting

Only L2 exists in the captures; the three exposure settings are a *sensor* variable, not the lighting-checklist conditions L1/L3/L4/L5. Landmark presence rate by lighting condition is **PENDING** (no capture at any other condition).

## 4. Recommendation (ADR-0017, Proposed)

Keep the Phase 02 baseline as the data-collection candidate — DSHOW 640×480, ROI `[40, 20, 560, 440]`, user ≈ 1.0 m — with exposure **−5** at L2 (not −6), and run the factorial before Phase 06 records participants. `roi.px` stays a candidate; Phase 02 C-5 (frozen capture config) stays open.

## 5. What is needed to complete this task (owner, developer-only captures; no participants)

One session of ≈ 10 s per cell with the Phase 06 warm-up movement script (both hands, all four MVP zone paths, 4–6 hand crossings — this doubles as the Task 03.2 crossing capture P-03.2-1):

```
python scripts/exposure_blur_check.py record --name dist-d100-L2-exp-5 --exposure MANUAL:-5 --lighting L2 --seconds 10
python scripts/benchmark_tip_methods.py --capture dist-d100-L2-exp-5
```

for each distance in {0.8, 1.0, 1.2, 1.5} m and each available lighting condition (exposure per protocol). Then `tools/annotate_tip.py --capture <cell> --every 10` on at least the 1.0 m cells so Task 03.10's error tables exist for the same frames.
