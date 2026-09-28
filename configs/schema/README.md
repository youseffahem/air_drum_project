# configs/schema/

`config.schema.json` — Space Drums top-level configuration schema (Phase 01, Task 01.7; ADR-0010). JSON Schema 2020-12, `$id: https://spacedrums.local/schemas/config.schema.json`, references `schemas/common.schema.json`.

Blocks: `meta`, `camera_profile`, `roi`, optional `hands` with its `identity` and `grip` sub-blocks (1.2, Phase 03, ADR-0014), optional `stick` (1.2, Phase 03, ADR-0015), `zones[]`, `tracking`, `anticipator`, `commit`, `audio`, `debug`, optional `arms`. All numeric values are tunable candidates; a measured native FPS is only accepted together with its `run_id`. Tests: `tests/contracts/test_config_schema.py`. Later phases extend blocks by minor schema bumps (`anticipator.model` / `fallback` filled in Phase 13; `release` block in Phase 20).

Schema 1.9 (ADR-0036 amendment, ADR-0043): optional `live_arm_settings` must contain
complete `A`, `B`, `C` entries. Each has a full `commit` block and `v_min`; B also has
the complete resolved `RuleSettings` dictionary, including its own `K` and `dt_step`.
The block is refused under older version declarations. The shared top-level settings
remain the legacy path when the block is absent. Nested `aux_heads` are refused because
the current live adapter supports Phase 10 GRU/TCN trajectories only. Calibration retains
the newer schema version. Actual experimental values must match the archived offline lock.
