# Phase 11 per-task evaluation (Task 11.4)

Status: IMPLEMENTED and executed on a SYNTHETIC fixture; participant per-task metrics PENDING.
All values are SYNTHETIC DEVELOPMENT diagnostics (dirty tree, HEAD `bd0bcf8`); none is a
thesis result. The held-out test evaluation of Task 11.9 has not run.

## Run and method

`experiments/phase-11/20260925-1002-synthetic-per-task/run.json` (COMPLETED; `per-task.json`,
`summary.json`) evaluates the 24 all-heads cells of the weighting run that use the development
choice `dominant-0.05` (2 families × 4 folds × 3 seeds;
`experiments/phase-11/20260925-0913-synthetic-weighting`). The fixture is rebuilt and verified
against every fold's recorded dataset/split hash before use. Validation identities only.

For every labelled validation window (an impact within H_max = 0.3 s) each head is compared with:

- **geometry** — the unchanged Phase 04 intersection of this model's own predicted trajectory
  (K=4, H=0.133 s) with the zones, with the MODEL wrapper's inward-speed intensity; and
- **Baseline B** — rule CV extrapolation (K=6, H=0.2 s) through the same geometry, at the same
  hand/frame.

Geometry and B answer only when their horizon predicts a crossing, so each is scored on its
covered rows, and the head is also scored on geometry's rows. Strike: frame-level average
precision (AP) and ROC-AUC on `strike_mask` rows. Head values are decoded to physical units
(`heads.decode_heads`).

## Results (mean ± SD over 12 cells per family)

| Quantity | GRU | TCN |
|---|---:|---:|
| Labelled rows covered by geometry / by Baseline B | 0.322 ± 0.052 / 0.303 ± 0.020 | 0.412 ± 0.078 / 0.303 ± 0.020 |
| Strike head AP / ROC-AUC | 0.619 ± 0.070 / 0.860 ± 0.037 | 0.779 ± 0.067 / 0.923 ± 0.028 |
| TTI MAE, head on all rows (ms) | 51.7 ± 5.7 | 54.1 ± 10.7 |
| TTI MAE, head / geometry on geometry rows (ms) | 51.5 ± 6.5 / 57.7 ± 10.8 | 52.9 ± 9.7 / 44.3 ± 10.3 |
| TTI MAE, Baseline B on its rows (ms) | 47.4 ± 5.6 | 47.4 ± 5.6 |
| Zone accuracy, head on all rows | 0.927 ± 0.010 | 0.930 ± 0.012 |
| Zone accuracy, head / geometry on geometry rows | 0.933 ± 0.017 / 0.901 ± 0.032 | 0.946 ± 0.010 / 0.910 ± 0.029 |
| Zone accuracy, Baseline B | 0.970 ± 0.026 | 0.970 ± 0.026 |
| Impact-position median error, head all rows (ROI) | 0.0499 ± 0.0055 | 0.0589 ± 0.0074 |
| Impact-position median error, head / geometry on geometry rows | 0.0512 ± 0.0107 / 0.0332 ± 0.0060 | 0.0562 ± 0.0074 / 0.0270 ± 0.0057 |
| Impact-position median error, Baseline B | 0.0068 ± 0.0015 | 0.0068 ± 0.0015 |
| Intensity MAE (ROI/s): head all rows / geometry / Baseline B inward | 0.422 / 1.726 / 0.821 | 0.437 / 1.523 / 0.821 |
| Intensity Pearson r: head / geometry / Baseline B inward | 0.237 ± 0.142 / 0.052 ± 0.145 / 0.252 ± 0.118 | 0.263 ± 0.167 / 0.072 ± 0.115 / 0.252 ± 0.118 |

TTI stratified by true time to impact (MAE in ms; geometry coverage in brackets):

| True TTI | Head GRU | Geometry GRU | Head TCN | Geometry TCN |
|---|---:|---:|---:|---:|
| (0, 0.067] s | 50.7 | 34.5 (0.72) | 53.7 | 21.4 (0.83) |
| (0.067, 0.133] s | 37.3 | 23.6 (0.32) | 41.1 | 22.6 (0.53) |
| (0.133, 0.3] s | 58.2 | 136.7 (0.15) | 59.6 | 122.5 (0.18) |

Baseline B's values repeat across families because B does not depend on the model.

## Reading (outcome-neutral, fixture only)

- **TTI:** inside the trajectory horizon, geometry on the predicted trajectory is more accurate
  than the TTI head (21–35 ms versus 37–54 ms), but it answers for only 32–41 % of labelled rows.
  Beyond H its few answers are early predicted crossings with large error. The head answers
  everywhere with a roughly flat 37–60 ms error. It is a plausible consistency signal, not a
  replacement for geometry timing.
- **Zone:** head and geometry agree with the label about 90–95 % of the time; Baseline B is higher
  here because the fixture's strokes descend vertically, which favours straight-line extrapolation.
- **Position:** geometry beats the head, and B is best, for the same reason.
- **Intensity:** the inward crossing speed on the *predicted* trajectory tracks the GT proxy
  poorly (r ≈ 0.05–0.07, large MAE). The head and B's extrapolated inward speed correlate
  weakly (r ≈ 0.24–0.26). All three are weak on this fixture; see the commit-time comparison
  in `phase-11-gating.md` and ADR-0029.

## TTI parameterisation (Task 11.1 candidates)

`experiments/phase-11/20260925-1029-synthetic-tti/run.json` (COMPLETED 10:37:44 +03:00; 72
models; `scripts/compare_tti.py`) trains trajectory + TTI heads only, with `dominant-0.05`
weighting and the same folds/seeds, for each parameterisation: direct (TTI/H_max), log(TTI/H_max),
and 8 bins (expected value of the softmax). Its `tti-direct` cells reproduce the ablation's
`+tti` cells exactly.

| TTI mode | Family | TTI MAE ms (all rows) | Bias ms | MAE by true TTI (0–0.067 / 0.067–0.133 / 0.133–0.3 s) | ADE (traj-only: GRU 0.0624, TCN 0.0452) |
|---|---|---:|---:|---|---:|
| direct | GRU | 53.4 ± 7.8 | −2.4 | 64.7 / 33.4 / 57.0 | 0.0645 ± 0.0074 |
| log | GRU | 45.6 ± 5.6 | −17.8 | 24.5 / 26.3 / 63.1 | 0.0680 ± 0.0058 |
| bins | GRU | 52.3 ± 5.2 | −2.6 | 55.9 / 39.5 / 56.0 | 0.0779 ± 0.0054 |
| direct | TCN | 44.4 ± 8.1 | −2.9 | 48.1 / 28.5 / 49.6 | 0.0489 ± 0.0051 |
| log | TCN | 43.2 ± 9.3 | −11.8 | 23.7 / 27.9 / 58.2 | 0.0558 ± 0.0058 |
| bins | TCN | 45.8 ± 11.8 | −1.7 | 50.2 / 32.2 / 49.8 | 0.0760 ± 0.0082 |

Log-time regression is markedly better close to the impact, where a commit decision is made, but
it is biased towards early predictions and costs more trajectory accuracy than direct regression.
Bins cost the most. On this fixture, direct regression is the cheapest for the trajectory and log
the most useful for near-impact consistency checks. The open question stays
To Be Experimentally Determined on participant folds.

## Limitations

One scripted fixture whose kinematics (vertical strokes, uniform acceleration) favour
extrapolation; frame-level rather than participant-level uncertainty; development weighting
`dominant-0.05` only; no participant, DEV CAPTURE or physical-pad data. Numbers are not
transferable to real drumming.
