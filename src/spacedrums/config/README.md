# spacedrums.config

**Status:** PLANNED — package added by Phase 01 (ADR-0010, ADR-0012); no code yet. Layer L0: imports only `contracts`.

Will hold: loading of YAML config files, resolution into one document, validation against `configs/schema/config.schema.json` before any computation, cross-field checks listed in the schema descriptions (e.g. `c_min <= c_valid`), canonical-JSON hashing into `config_hash` (docs/reproducibility-policy.md section 3), and writing `config.resolved.yaml`. First code: Phase 02.
