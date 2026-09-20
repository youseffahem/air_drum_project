# schemas/

JSON Schemas that data files must validate against.

- `experiment-log.schema.json` - one record per experiment run (Phase 00, Task 00.5; consumed by Phases 09-19).
- `examples/` - example records used by `scripts/env_smoke.py` (accept valid, reject missing `dataset_version`).

Later: dataset manifest schema (Phase 06), config schema (Phase 01, lives in configs/schema/).
