# Temporal trajectory predictors — Phase 10

Status: IMPLEMENTED development machinery; participant validation PENDING.
See `docs/gates/phase-10-gate.md` for evidence, remaining scope and reviewer action.

`TemporalConfig` declares family/F/N/K/dt/size; `TrainConfig` declares seed,
optimizer, loss, weights, sampler, early stopping and CPU threads. `data.load_fold`
reads Phase 08 normalized train/validation archives and checks their fold/schema,
participant/session and normalization provenance. Held-out archives are not opened.
Masks are concatenated with zero-filled features. No hand-id feature is introduced.

The head predicts K 2D displacements, with only the optional within-H logit.
Fixed-grid targets interpolate valid delivered-frame targets without extrapolation.
N changes require fresh Phase 08 windows because window_elapsed depends on N;
auxiliary H changes require fresh labels from the existing target builder.

The GRU is unidirectional; masked whole frames reset hidden state. Its optional
bounded cache carries up to N independent start states and falls back to rebuilding
when overlapping features differ. It is exact rolling-N inference, not indefinite
single-state inference or a claimed speedup. The TCN uses left-padded residual
dilated convolutions with receptive field >=N and no time-dependent normalization.

`TemporalAnticipator.predict(history, features)` accepts one hand's causal history
and a normalized `(X,M)` window. Alternatively inject an upstream Phase 08 feature
assembler and matching fold stats. Model code never imports geometry; the replay
MODEL wrapper obtains candidates exclusively from Phase 04 intersection, derives
the inward-speed intensity proxy, and feeds the unchanged Phase 05 policy.
INVALID/STALE clear per-hand model state; warm-up requires N live observations.
dt_step is the prediction grid, not the live frame interval. Live input resampling
and integration are reserved for Phase 13.

Export uses the installed TorchScript runtime and verifies eager/reloaded outputs
on all validation samples in batch-one and batch-31 calls. PyTorch's deprecation
warning is retained in logs. Model hashes are verified on load. CPU timing reports
include raw samples, warmup, one-thread setting, p50/p95/p99 and cache rebuilds;
timing excludes feature extraction and I/O. Parameter bytes are not peak process RSS.

## Commands (repository root; Windows virtual environment)

```powershell
.venv\Scripts\python.exe -m pytest tests/temporal
.venv\Scripts\python.exe scripts/sweep_horizon.py --synthetic-fixture --output experiments/phase-10
.venv\Scripts\python.exe scripts/sweep_window.py --synthetic-fixture --n 4 16 --output experiments/phase-10
.venv\Scripts\python.exe scripts/verify_phase10.py --require-clean
```

All CLI entry points support `--help`. `train_temporal.py` accepts JSON containing
`model` (TemporalConfig), `training` (TrainConfig), and `aux_horizon_s` from the Phase
08 export configuration. `--plan` sweeps accept explicit cells with those values
and `fold_dir`; three seeds per model/fold are mandatory. For real data, validation
session event evaluation is a separate `eval_temporal.py` invocation. The fixture
runner composes it automatically. The confirmatory test runner is deliberately
pending the upstream freeze and predeclared protocol; `--partition test` is refused.

`eval_temporal.py --samples ... --expected ...` reloads the exported model and
compares every reported trajectory metric/denominator, with recorded tolerance.
This is same-environment development reproduction. It is not VALIDATED, a selected
participant model, or evidence that anticipation improves physical sound latency.
