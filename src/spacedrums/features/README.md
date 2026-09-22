# spacedrums.features

Status: IMPLEMENTED (Phase 08); participant-fold evidence PENDING.

`core.py` computes fs-v1; `batch.py` and `streaming.py` share it. `schema.py`/`groups.py`
define dimensions and ablations; `normalize.py` fits train-only fold statistics;
`windows.py`/`targets.py` assemble causal inputs and offline targets.
The higher-layer verified loader is `spacedrums.data.feature_dataset`.

See `docs/features/feature-schema-v1.md`, ADR-0022 and `docs/gates/phase-08-gate.md`.
No model training or live application integration is included.
