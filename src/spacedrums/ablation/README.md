# Ablation preparation

Offline Phase 19 tooling, above `live_eval`. See
`docs/experiments/phase-19-prereg.md` (draft) and ADR-0043.

Run `python scripts/run_ablations.py --synthetic-dev` for generated SYNTHETIC/DEV
machinery checks. It creates a new ignored experiment directory, retrains the declared
variants on generated CV groupings and records hashed artifacts. No camera/audio is used.
Use `--check-dependencies` to list missing real frozen inputs; exit 2 means blocked.
`--execute` always refuses in preparation, including with purportedly complete inputs.
`--regenerate <results.json> --output <new-directory>` regenerates a development report.

`transforms.py` keeps feature masks identical at training/replay, changes model configuration
without new model algorithms, drops raw frames and checks complete horizon-reuse signatures.
`retrack.py` injects fresh perception and calls the existing tracker/features; labels are copied
unchanged and never passed to perception. `statistics.py` resamples paired participants.
`guards.py` verifies real reference dependencies and contained hashed file inventories.

All checked-in examples are SYNTHETIC/DEV. No sample participant reference is supplied.
