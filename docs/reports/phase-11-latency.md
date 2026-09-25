# Phase 11 latency, parameters and memory: multi-task vs single-task (Task 11.8)

Status: development CPU compute on HW-01. No shipped model exists; target-CPU and
participant-model measurements are PENDING.

## Run and method

`experiments/phase-11/20260925-1028-mt-latency-memory/run.json` (COMPLETED; `latency-memory.json`,
`raw-gru.json`, `raw-tcn.json`). Pair per family from the head-ablation run, fold 0, seed 10:
`traj-only` (bit-identical to the Phase 10 single-task model) and `all` (six heads,
`dominant-0.05`). Exported TorchScript models; batch 1; one intra-op thread; prepared validation
inputs; feature extraction and I/O excluded. Timing via `spacedrums.timing.now` through
`export.latency`, 10 interleaved blocks × 100 calls per model (1,000 calls each, 100 warm-up
calls in the first block). The machine ran nothing else. Working set: `GetProcessMemoryInfo` in a
fresh subprocess before loading, after loading, and after 200 inferences. It includes the
Python/PyTorch runtime. Inference cost depends on the architecture, not on the synthetic weights,
but the numbers still describe development models on HW-01 only.

## Results

| Family | Model | Parameters | Parameter bytes | Export bytes | p50 / p95 / p99 windowed (ms) | p50 / p95 / p99 bounded stateful (ms) | Working set after load / peak (MB) | Load Δ (MB) |
|---|---|---:|---:|---:|---|---|---:|---:|
| GRU | traj-only | 6,376 | 25,504 | 41,518 | 0.879 / 1.630 / 2.391 | 1.557 / 2.718 / 3.526 | 206.8 / 227.6 | 4.6 |
| GRU | all heads | 6,529 | 26,116 | 48,488 | 0.919 / 1.513 / 2.084 | 1.694 / 2.946 / 3.582 | 206.2 / 226.9 | 4.1 |
| TCN | traj-only | 6,648 | 26,592 | 55,468 | 0.550 / 1.344 / 1.881 | — | 206.8 / 227.7 | 5.0 |
| TCN | all heads | 6,801 | 27,204 | 63,230 | 0.596 / 1.413 / 2.790 | — | 207.1 / 228.1 | 4.6 |

MB = 10⁶ bytes. The five auxiliary heads are linear layers on the shared 16-unit state: +153
parameters (+2.4 % GRU, +2.3 % TCN) and ~7–8 kB of export. Median batch-one time rises by
0.04–0.05 ms. The p95/p99 differences are smaller than their run-to-run spread (the GRU all-heads
p95 is even lower). The model's share of process memory (a few MB at load, identical for both) is
negligible next to the ~200 MB runtime. Bounded stateful GRU inference is exact rolling-N and
costlier than windowed inference, as in Phase 10.

## Reading

On HW-01, the extra heads add no material CPU or memory cost at this model size. The ship decision
therefore rests on accuracy/FP/FN evidence, not on compute. This does not hold automatically for
larger heads (MLP heads, `head_hidden > 0`), for other encoder sizes, or on the eventual target CPU.
Grid-time latencies in the weighting/ablation `results.json` were measured with three parallel
workers and are not used here.
