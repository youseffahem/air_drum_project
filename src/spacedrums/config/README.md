# spacedrums.config

**Status:** IMPLEMENTED (Phase 02; tests in `tests/config/`). Layer L0: imports only `contracts`.

`load_config(*yaml_paths, overrides=None)` deep-merges files in order (fragments such as `configs/camera/<device>.candidate.yaml` onto a base), validates the resolved document against `configs/schema/config.schema.json` (schema 1.1) plus the cross-field checks the schema descriptions promise (`c_min <= c_valid`, ROI inside the resolution, exposure mode/value consistency, measured values only with provenance), and returns `ResolvedConfig(data, config_hash, sources)`. `config_hash` = `sha256:` over canonical JSON (sorted keys, no whitespace, floats via repr, NaN/Inf forbidden — docs/reproducibility-policy.md section 3). `write_resolved` writes the `config.resolved.yaml` snapshot; `validate_blocks` checks a fragment on its own.
