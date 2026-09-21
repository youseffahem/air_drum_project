# spacedrums.contracts

**Status:** first code in Phase 02 (tests in `tests/contracts/test_record_classes.py`). Layer L0 (type-only): imports nothing else in `spacedrums` (checked by `tests/architecture/`).

- `enums.py` — every vocabulary of `schemas/common.schema.json` plus `TimestampSource`, `ImageRefKind`, `ImageCrop`, `ResetReason`.
- `records.py` — `FrameSample` and `ImageRef` (contracts.md section 3.1); further records are added by the phase that first produces them, each validated against its JSON Schema (the schema is the contract, the class is an implementation).
- `values.py` — `FrameView` (section 7); `Trajectory` arrives with Phase 04.
- `interfaces.py` — `FrameSource` Protocol (architecture.md section 11); the other Protocols arrive with their first implementers (03: `TipEstimator`, `Tracker`; 04: `Geometry`, `AudioScheduler`; 05: `Anticipator`, `CommitPolicy`).
- `schema.py` — locates `schemas/` + `configs/schema/`, builds one `referencing` registry, exposes `validate` / `errors` / `is_valid` per schema stem (reused by tests and scripts).
