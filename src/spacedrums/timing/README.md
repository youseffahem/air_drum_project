# spacedrums.timing

**Status:** PLANNED — package added by Phase 01 (ADR-0004, ADR-0012); no code yet. Layer L0: imports only `contracts`.

Will hold: the single clock accessor `now() -> float` (seconds on `t_mono`; concrete function identified by `clock_id`), and the `TimingRecord` collector (docs/architecture/architecture.md section 5). No other module may call `time.*` for timestamps. First code: Phase 02 (clock); full records: Phase 05.
