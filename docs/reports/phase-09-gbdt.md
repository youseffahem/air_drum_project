# Phase 09 — C-GBDT diagnostic report

Status: SELF-TEST MODELS ONLY. Fold input is the Phase 08 in-memory synthetic
unit fixture exported under `ds-v0.0-selftest-features`, not a participant dataset.
The exact model files, input/model hashes, validation search logs, window-level
diagnostics and latency samples are under
`experiments/phase-09/20260922-2326-p09-development-verification/gbdt/`.

The trainer flattens `X[N,F]` and appends every mask bit. Train/validation
participant IDs must be disjoint and agree with the Phase 08 fold report and
normalization provenance. LightGBM is single-threaded with fixed seed 9,
deterministic row-wise training and balanced binary class weights. A fixed
three-trial validation search selects the strike head by log loss. Other heads
fit TTI on positives, zone when more than one class is present, and
displacements at the midpoint and final future steps. The self-test fixture
contains only one positive zone; no zone classifier is fitted there.

`GBDTAdapter` supports direct probability/TTI/zone candidates and a trajectory
formed from displacement heads. Both modes enter the same replay commit policy;
the trajectory mode enters Phase 04 geometry first. The model replay has a
future-perturbation test. The in-memory synthetic fixture also exercises the
trained fold-0 model through both event modes. At candidate W=50 ms and
τ=50 ms, p=0.5, n=0, direct mode matches 6/6 generated positives with 4 FPs
and median lead +34 ms; trajectory mode makes no commits and misses all 6.
These are **unit-fixture diagnostics**, not evidence about participant strokes.
`eval_gbdt.py` is ready for a frozen participant fold,
but no participant model can be trained or evaluated yet. The window-level
diagnostics do **not** establish event FP/min or lead time. Latency excludes
feature extraction, geometry and commit, and is development hardware evidence.

The fold-0 synthetic model's batch-one, single-thread CPU timing on HW-01 was
p50 0.371 ms, p95 0.609 ms and p99 0.863 ms over 500 calls after 50 warmups.
This is model inference timing on a unit fixture, not participant or full-pipeline
latency evidence.

| Required participant result | Status |
|---|---|
| Per-fold models and hashes | PENDING `ds-v1.0` features/stats |
| Direct and trajectory event metrics/curves | PENDING participant replay |
| Held-out test result with selected point and W | PENDING validation selection and freeze |
| CPU p50/p95/p99 on participant-trained model | PENDING |
