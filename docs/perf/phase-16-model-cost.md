# Phase 16 model cost

Status: **PENDING** shipped-model selection and clean reproduction. These are
development measurements, 2026-09-26, HW-01 CPU, Torch intra-op threads 1.
No participant or held-out test evaluation was performed.

The pinned Phase 10 package `gru-fold0-seed10-8acb3421c0b0` is SYNTHETIC-trained,
N=8, K=1, hidden width 12. The same hashed 202-window validation archive is used
for all candidates. `model_cost.py` performs 20 warm-up calls, then three batches
of 300 batch-one calls in rotating candidate order. Serialization is independently
reloaded and checked exactly. Candidate exports and manifests have separate hashes.

| Variant | p50 ms | p95 ms | Maximum normalized output delta | Export tolerance | Full raw/harness regression |
|---|---:|---:|---:|---|---|
| Original float TorchScript | 0.798 | 1.247 | 0 | Reference | Reference |
| Frozen TorchScript graph | 0.797 | 1.475 | 0 | PASS | PASS |
| Dynamic int8 GRU/Linear | 1.854 | 2.637 | 0.0110442 | FAIL | FAIL |

Timing run: `experiments/phase-16/20260926-1334-model-cost/`. Exact regression
run paths are `20260926-1334-frozen-ordered-regression` and
`20260926-1335-int8-ordered-regression` under `experiments/phase-16/`; commands
are in `remaining-screens.json`. Frozen output and harness metrics match; int8 changes first
developer-capture commits from 11 to 13, as well as predictions and synthetic
event metrics. No tolerance was relaxed.

**Retain the original float export.** Freezing has no tail-latency advantage here;
int8 is slower and changes behavior. These small GRU results do not generalize to
a later owner-selected model. Its full benchmark and regression remain PENDING.

## Preserved initial experiments and correction

The first paired cost run `20260926-1325-model-cost` gave p50/p95 ms of
0.760/0.936 (float), 0.757/1.431 (frozen), and 1.795/2.075 (int8), with the same
numerical export outcomes. Initial raw regressions `20260926-1326-frozen-regression`
and `20260926-1327-int8-regression` failed exact upstream records too: dumping the
candidate YAML with sorted keys reordered grip-weight accumulation, changing
floating-point results around 1e-15. The configuration writer now preserves key
order. The fresh runs above isolate the model change; failed trials remain archived.

## Export scope

A separate serial CPU screen, `experiments/phase-16/20260926-1357-model-cpu-cost/`,
uses the same packages and pinned validation archive, 20 warm-up calls and three
rotating 300-call batches. Mean process CPU per call is 0.712 ms (float), 0.747 ms
(frozen), and 1.285 ms (int8). One-core utilization during those batches is
80.48%, 81.65% and 76.52%, respectively. The scope includes slicing/timer overhead;
it differs from application resource sampling. All three packages are resident,
so no per-variant memory saving is inferred. This additional screen does not
change the original float retention decision.

Graph freezing was tested within the existing verified TorchScript deployment
path. No ONNX runtime path, operator rewrite or stateful GRU was introduced:
the existing contract is windowed inference, and changing state ownership would
require independent reset/cadence/parity validation. The deployed runtime already
uses the pinned package and its strict manifest checks. Testing that path avoids
claiming an unimplemented ONNX or stateful speedup. This is a recorded scope
deviation from the candidate approaches, not shipped-model acceptance.
