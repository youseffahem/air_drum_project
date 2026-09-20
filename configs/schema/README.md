# configs/schema/

`config.schema.json` — Space Drums top-level configuration schema (Phase 01, Task 01.7; ADR-0010). JSON Schema 2020-12, `$id: https://spacedrums.local/schemas/config.schema.json`, references `schemas/common.schema.json`.

Blocks: `meta`, `camera_profile`, `roi`, `zones[]`, `tracking`, `anticipator`, `commit`, `audio`, `debug`, optional `arms`. All numeric values are tunable candidates; a measured native FPS is only accepted together with its `run_id`. Tests: `tests/contracts/test_config_schema.py`. Later phases extend blocks by minor schema bumps (`anticipator.model` / `fallback` filled in Phase 13; `release` block in Phase 20).
