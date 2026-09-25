# Phase 11 consistency checks, gating and commit-time intensity (Tasks 11.5, 11.7)

Status: IMPLEMENTED and executed on a SYNTHETIC fixture; participant gating evaluation PENDING.
SYNTHETIC DEVELOPMENT values only (dirty tree, HEAD `bd0bcf8`). No gate, tolerance or intensity
source is selected here.

## Run and method

`experiments/phase-11/20260925-1007-synthetic-gating/run.json` (COMPLETED; `plan.json`,
`curves.json`, `intensity.json`, `baseline-b.json`, `summary.json`, `lead-vs-fp-by-gate.png`).
Models: the 24 all-heads `dominant-0.05` cells of the weighting run (same configuration as the
ablation's `all` variant). For each validation session the model outputs are computed once
(`CachedPredictions`, which re-checks each causal window) and the unchanged harness replays
every gate × τ_commit ∈ {0.02, 0.05, 0.10} s. Its ungated points reproduce the weighting run's
equal-τ rows exactly.

`consistency.AuxGate` sits between geometry and the Phase 05 policy (ADR-0028). It attaches
`aux.consistency_flags`; the head probability never reaches `commit.p_commit`. Candidate gates:

| Gate | Setting |
|---|---|
| none | all off (the default) |
| p_aux-0.3 / 0.5 / 0.7 | pass only if p(strike within H) ≥ threshold |
| agree-tight / agree-loose | zone equal **and** \|TTI_head − TTI_geometry\| ≤ 0.02 / 0.05 s **and** position within 0.03 / 0.06 ROI |
| both-0.5-tight / loose | p_aux 0.5 and the agreement gate |
| intensity-head | no gate; committed intensity from the head |

## Lead / FP / FN per gate (mean over 12 cells per family)

| Gate | Family | τ 0.02: lead ms / FP·min⁻¹ / FN | τ 0.05 | τ 0.10 | ΔFP / ΔFN vs none at τ 0.05 (count per session) |
|---|---|---|---|---|---|
| none | GRU | 7.3 / 17.7 / 0.781 | 11.2 / 58.7 / 0.545 | 21.9 / 208.7 / 0.476 | 0 / 0 |
| p_aux-0.3 | GRU | 7.6 / 5.5 / 0.809 | 11.9 / 23.9 / 0.584 | 23.5 / 119.1 / 0.493 | −13.8 / +3.1 |
| p_aux-0.5 | GRU | 15.8 / 0.6 / 0.985 | 9.8 / 0.8 / 0.958 | 26.1 / 13.3 / 0.900 | −22.8 / +34.5 |
| agree-loose | GRU | 16.1 / 0.0 / 0.985 | 18.5 / 7.8 / 0.890 | 34.4 / 81.9 / 0.788 | −20.1 / +28.8 |
| agree-tight | GRU | 27.7 / 0.0 / 0.997 | 26.5 / 0.8 / 0.991 | 34.1 / 27.4 / 0.936 | −22.8 / +37.4 |
| none | TCN | 13.9 / 22.4 / 0.546 | 21.0 / 80.9 / 0.358 | 25.8 / 224.1 / 0.606 | 0 / 0 |
| p_aux-0.3 | TCN | 14.4 / 10.1 / 0.579 | 22.2 / 46.9 / 0.408 | 27.9 / 160.4 / 0.657 | −13.4 / +4.1 |
| p_aux-0.5 | TCN | 19.1 / 4.9 / 0.739 | 26.2 / 38.0 / 0.584 | 34.1 / 128.1 / 0.748 | −16.9 / +18.3 |
| p_aux-0.7 | TCN | 25.6 / 2.7 / 0.907 | 31.0 / 19.2 / 0.838 | 36.4 / 55.1 / 0.845 | −24.3 / +39.9 |
| agree-loose | TCN | 23.4 / 1.5 / 0.912 | 29.8 / 13.3 / 0.804 | 31.5 / 77.6 / 0.800 | −26.7 / +37.7 |
| agree-tight | TCN | 16.2 / 0.2 / 0.975 | 22.5 / 1.3 / 0.961 | 31.5 / 13.7 / 0.939 | −31.4 / +50.8 |

Every row, including GRU p_aux-0.7 and both-*, is in `summary.json` with timing MAE, zone
accuracy of matched strikes and the gate's decision counts. Across all cells the agreement gates
rejected 70–95 % of geometry candidates (e.g. TCN agree-tight: 239 passed, 4,845 rejected); the
GRU p_aux-0.5 gate passed 287 of 3,973 because the strike head's probabilities rarely exceed 0.5.
Median lead of the few remaining matches rises because the surviving commits are the confident,
early ones; with FN near 1 that is not a useful gain.

Development-budget picks (FP ≤ 30/min, FN ≤ 0.6; synthetic constants): feasible in 7/12 TCN
cells with no gate (lead 13.0 ms), 9/12 with p_aux-0.3 (15.4 ms) and 5/12 with p_aux-0.5
(22.0 ms). For the GRU: 2/12 with no gate and 4/12 with p_aux-0.3, none for the other gates.
Agreement gates were never feasible because FN exceeded the ceiling.

## Reading (fixture only)

- A **probability gate** moves the operating point along the lead/FP/FN curve. A mild
  threshold (0.3) removed about half the FPs for a few percentage points of FN on this fixture.
  Stronger thresholds trade FP for FN steeply. This is a trade-off, reported on the curve,
  not an improvement.
- The **agreement gates suppressed most valid strikes** (FN 0.79–1.0). This is the phase's
  predicted failure mode: head TTI/position errors (≈50 ms, ≈0.05 ROI; `phase-11-per-task.md`)
  are larger than the tolerances, so agreement is rare even for true strikes. Wider tolerances
  or zone-only agreement are candidates for participant CV. Nothing supports them here.

## Commit-time intensity (Task 11.7)

For every matched C-MT commit (τ 0.05 s, ungated models) the proxy is scored against the
label's `intensity_proxy_gt` (rule R2). Values are means over 12 cells:

| Source at the commit | GRU ρ / r / MAE | TCN ρ / r / MAE | Coverage |
|---|---|---|---|
| (a) geometry: inward crossing speed on the predicted trajectory | 0.334 / 0.411 / 0.889 | 0.307 / 0.412 / 0.973 | 1.00 |
| (b) intensity head at the commit frame | 0.318 / 0.317 / 0.398 | 0.212 / 0.288 / 0.400 | 1.00 |
| (c) Baseline B extrapolated inward speed, same hand/frame/zone | 0.701 / 0.570 / 0.656 | 0.621 / 0.520 / 0.722 | 0.81 / 0.89 |

At τ 0.02 and 0.10 the ordering is the same except GRU τ 0.10, where the head's ρ (0.371) exceeds
geometry's (0.186). Baseline B's own committed value (Phase 04 speed magnitude, its own commits)
gives Pearson r 0.69–0.74, MAE 0.51–0.78. That is a different definition and a different event set.

Reading: the head is best calibrated (lowest MAE) but ranks strikes poorly. The geometric speed on
the model's predicted trajectory ranks slightly better but is biased low. Straight-line
extrapolation of the observed track ranks best on this fixture, whose strokes accelerate along
straight vertical lines. Under the ADR-0029 rule (head only if its ρ beats geometry with a CI
excluding geometry's) nothing would switch. The development default stays **geometry**.
Participant data decide.

## Limitations

One fixture; tolerances and thresholds are untuned candidates; frame-level candidates share one
model per cell; development budget synthetic; no participant or perceptual intensity reference.
