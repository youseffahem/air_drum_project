# Phase 11 head ablation (Task 11.6)

Status: IMPLEMENTED and executed on a SYNTHETIC fixture; participant ablation PENDING.
SYNTHETIC DEVELOPMENT values only (dirty tree, HEAD `bd0bcf8`); these are not Phase 19 results.

## Run

`experiments/phase-11/20260925-0949-synthetic-ablation/run.json` — COMPLETED 2026-09-25
10:28:44 +03:00; 192 models, 3,904 hashed artifacts. Same fixture, folds, seeds, windows,
encoders and harness as the weighting run (`phase-11-weighting.md`). The weighting was chosen
mechanically (`plan.json` → `weighting_choice`: `dominant-0.05`, step 4 of the declared rule).
Variants: `traj-only` (Phase 10 single-task, fixed weights), `+strike`, `+tti`, `+zone`,
`+position`, `+intensity`, `all`, and `no-traj`. `no-traj` is the five auxiliary heads with equal
fixed weights and **no trajectory head**. Its strikes come from p(strike) + TTI + zone through the
same Phase 05 policy, as `DIRECT_HEAD` candidates in the flagged harness mode. Its results are
labelled **direct / no-trajectory (diagnostic)** and it is never a ship candidate. Three seeds × four
folds per variant and family.

Determinism across runs: all 24 `traj-only` and all 24 `all` checkpoints are bit-identical to the
corresponding `traj-only` and `dominant-0.05` checkpoints of the independent weighting run
(different parallel schedules). TorchScript archive bytes differ between runs. Numerical export
parity is verified per model instead.

## Frame-level and trajectory results (mean ± SD, 12 cells)

| Variant | Family | ADE | FDE | Head metric | Dev-budget lead ms (feasible cells) | Dev FP/min |
|---|---|---:|---:|---|---:|---:|
| traj-only | GRU | 0.0624 ± 0.0065 | 0.0851 ± 0.0072 | — | 14.5 (2) | 13.7 |
| +strike | GRU | 0.0661 ± 0.0054 | 0.0871 ± 0.0075 | AP 0.709 | 11.5 (2) | 14.1 |
| +tti | GRU | 0.0645 ± 0.0074 | 0.0871 ± 0.0097 | TTI MAE 53.4 ms | 12.6 (7) | 15.4 |
| +zone | GRU | 0.0791 ± 0.0055 | 0.1002 ± 0.0099 | zone acc. 0.924 | — (0) | 23.6 |
| +position | GRU | 0.0654 ± 0.0062 | 0.0897 ± 0.0067 | median 0.0428 | 11.3 (5) | 16.7 |
| +intensity | GRU | 0.0709 ± 0.0064 | 0.0934 ± 0.0100 | MAE 0.440, ρ 0.219 | — (0) | 17.3 |
| all | GRU | 0.0841 ± 0.0067 | 0.1060 ± 0.0096 | see weighting | 11.0 (2) | 20.7 |
| no-traj (diagnostic) | GRU | — | — | AP 0.654, TTI 49.9 ms, zone 0.926 | 13.7 (3) | 14.3 |
| traj-only | TCN | 0.0452 ± 0.0050 | 0.0696 ± 0.0066 | — | 13.4 (11) | 6.3 |
| +strike | TCN | 0.0580 ± 0.0059 | 0.0826 ± 0.0057 | AP 0.802 | 12.0 (9) | 8.2 |
| +tti | TCN | 0.0489 ± 0.0051 | 0.0739 ± 0.0075 | TTI MAE 44.4 ms | 14.1 (11) | 10.1 |
| +zone | TCN | 0.0685 ± 0.0072 | 0.0880 ± 0.0066 | zone acc. 0.927 | 11.7 (8) | 17.3 |
| +position | TCN | 0.0508 ± 0.0052 | 0.0768 ± 0.0066 | median 0.0387 | 15.7 (9) | 13.1 |
| +intensity | TCN | 0.0576 ± 0.0058 | 0.0816 ± 0.0076 | MAE 0.446, ρ 0.278 | 14.7 (6) | 14.8 |
| all | TCN | 0.0796 ± 0.0084 | 0.1033 ± 0.0107 | see weighting | 13.0 (7) | 22.4 |
| no-traj (diagnostic) | TCN | — | — | AP 0.731, TTI 49.2 ms, zone 0.929 | 7.3 (2) | 6.8 |

Paired deltas against `traj-only` and the degradation flags (ADE/FDE beyond 2 × seed SD) are in
`phase-11-conflicts.md` and `summary.json`. Only `+tti` stays within seed variance for both
families; `+zone` and `all` degrade both.

## What trajectory-first contributes (no-trajectory diagnostic, harness at equal τ)

Mean over 12 cells; ~84 labelled impacts per validation identity; *direct / no-trajectory (diagnostic)*
rows are swept over p_commit because they have no geometry.

| Arm | Family | τ 0.05 s: matched / FP·min⁻¹ / FN / timing MAE ms | τ 0.02 s: matched / FP·min⁻¹ / FN |
|---|---|---|---|
| traj-only (trajectory → geometry) | GRU | 39.2 / 31.9 / 0.536 / 16.2 | 18.4 / 11.4 / 0.781 |
| all heads (trajectory → geometry, gates off) | GRU | 38.2 / 58.7 / 0.545 / 19.0 | 18.2 / 17.7 / 0.781 |
| no-traj, p 0.3 (diagnostic) | GRU | 20.2 / 46.8 / 0.767 / 22.6 | 4.2 / 4.8 / 0.953 |
| no-traj, p 0.5 (diagnostic) | GRU | 9.9 / 22.6 / 0.885 / 20.3 | 3.5 / 4.4 / 0.960 |
| traj-only (trajectory → geometry) | TCN | 57.0 / 19.0 / 0.329 / 8.4 | 33.6 / 0.6 / 0.606 |
| all heads (trajectory → geometry, gates off) | TCN | 54.0 / 80.9 / 0.358 / 14.1 | 38.1 / 22.4 / 0.546 |
| no-traj, p 0.3 (diagnostic) | TCN | 27.4 / 63.5 / 0.679 / 21.3 | 15.6 / 9.9 / 0.815 |
| no-traj, p 0.5 (diagnostic) | TCN | 17.9 / 44.5 / 0.790 / 16.6 | 8.6 / 7.4 / 0.898 |

On this fixture the direct-head route matches far fewer impacts at comparable or higher FP, with
larger timing error, than the same encoder's trajectory routed through geometry. This is
diagnostic support for the trajectory-first design **on scripted data only**. Phase 19
(AB-NOTRAJ) must repeat it on participants before the thesis may use it.

## Reading (outcome-neutral, fixture only)

Adding heads did not improve the trajectory route here. The TTI head was cost-neutral. Zone
supervision hurt the most; the strike, position and intensity heads hurt the TCN. The combined
model inherited the costs. Heads remain useful as gates (`phase-11-gating.md`), not as
supervision that improves anticipation, on this fixture.

## Limitations

One scripted fixture and a single development weighting; linear heads; no tuning per variant; no
per-head gating combinations beyond `phase-11-gating.md`; participant behaviour may differ.
