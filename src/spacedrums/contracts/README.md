# spacedrums.contracts

**Status:** PLANNED — package added by Phase 01 (ADR-0012); no code yet. Layer L0 (type-only): imports nothing else in `spacedrums`.

Will hold: record types mirroring `schemas/*.schema.json` (docs/architecture/contracts.md), the enums of `schemas/common.schema.json`, the interface `Protocol`s of docs/architecture/architecture.md section 11 (`TipEstimator`, `Tracker`, `Anticipator`, `Geometry`, `CommitPolicy`, `AudioScheduler`, `FrameSource`), and the `Trajectory` / `FrameView` / `ResetReason` value types. The JSON Schema is the contract; classes here must serialise to exactly that JSON (tests in tests/contracts/). First code: Phase 02.
