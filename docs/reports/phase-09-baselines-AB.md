# Phase 09 — Baselines A/B diagnostic report

Status: SELF-TEST ONLY. No reviewed participant fold or held-out participant is available.
The exact self-test run, manifests, Parquet events and curves are under
`experiments/phase-09/20260922-2326-p09-development-verification/`.

| Input | Source | A matched / FP / FN | B observation | Interpretation |
|---|---|---|---|---|
| `synthetic-p07-labels` | SYNTHETIC generated labels, unreviewed | 32 / 0 / 0 at W=50 ms candidate | Example CV K=3, τ=50 ms, p=0.3, n=0: 28 / 0 / 4; median lead +28.33 ms versus A −5.00 ms | Generated-motion machinery diagnostic only |
| `dev-p06-ingest-exp-5` | DEV CAPTURE, unreviewed geometric labels | 1 / 0 / 0 at W=50 ms candidate | No matched B commits at the default Phase 05 settings; sweep records all achieved points | Developer diagnostic only; not a user study |

These numbers come from idealised `Δ_proc=0`, not measured processing delay. The
developer-session reproduction check separately injects the original per-frame
timestamps and confirms the live A commit list. The Phase 09 primary setting must
use measured stage latency and be reported with a measured audio-output latency
only under the `L_sys_est` name. No physical `L_sys` is claimed here.

The sweep covers CV/CA, K=3/6, τ=50/100 ms, p=0.3/0.5 and n=0/2.
The W sweep covers 25/50/75/100 ms. Each per-setting `results.json` contains
pooled, hand, zone and segment tables and explicit active-time denominators;
`events.parquet` contains matched/FP/FN rows. `curve.json` and
`lead-vs-fp.png` plot achieved points without interpolation. The full
participant per-fold/per-participant tables, bootstrap CIs, operating-point
selection and test results remain pending. See ADR-0024.
