# schemas/

JSON Schemas (Draft 2020-12) that data files must validate against. Each schema has an `$id` under `https://spacedrums.local/schemas/`; cross-file references use `$ref` to `common.schema.json` and are resolved with a `referencing.Registry` (see `scripts/validate_contracts.py` / `tests/contracts/conftest.py`).

- `experiment-log.schema.json` - one record per experiment run (Phase 00, Task 00.5; consumed by Phases 09-19).
- `common.schema.json` - shared definitions: units, `hand_id`, `point2`, enums (Phase 01, Task 01.2).
- Record contracts (Phase 01, Task 01.2; docs/architecture/contracts.md): `frame-sample`, `hand-observation`, `stick-observation`, `track-state`, `kinematic-features`, `trajectory-prediction`, `direct-prediction` (diagnostic-only, gate review 2026-09-21), `strike-candidate`, `committed-strike`, `audio-event`, `timing-record`, `record-stream-header`.
- `examples/` - `<name>.valid.example.json` per schema: SYNTHETIC placeholder documents used only by the schema tests (`TEST-SCHEMA-1`). They are not data and contain no measurement.
- Phase 06 dataset documents (Tasks 06.4, 06.7, 06.8, 06.9; ADR-0019): `session-metadata` (one recording session; session kind SYNTHETIC / DEV_CAPTURE / PILOT / PARTICIPANT with structural promotion refusal), `session-verification` (`verify.json`), `exclusion-record` (unusable-recording policy), `raw-manifest` (`data/manifests/<version>.json`). Examples are SYNTHETIC.

Config schema lives in `configs/schema/config.schema.json` (same `$id` namespace). Later: `label-record.schema.json` (Phase 07), `feature-schema-v1.json` (Phase 08), `calib-v1.schema.json` (Phase 14).

Check everything (from the repository root, Windows paths):

    .venv\Scripts\python.exe scripts\validate_contracts.py
    .venv\Scripts\python.exe -m pytest tests\contracts

Phase 08: `feature-schema-v1.json` is the generated **semantic descriptor**, not a JSON Schema;
it defines each ordered fs-v1 feature and is tested against its generator. The unchanged
`kinematic-features.schema.json` validates record envelopes. Config schema 1.4 adds the optional
features block (ADR-0022). Normalization/sample formats are documented in the feature schema.
