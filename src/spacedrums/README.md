# spacedrums

**Status:** first code landed in Phase 02 (`capture`, `ui.guide`, and the L0 packages `contracts`, `timing`, `config`). Every other subpackage is still a PLANNED stub whose README names the owning phase.

Layout and the allowed-dependency layers: `docs/architecture/architecture.md` section 2 (enforced by `.importlinter` + `tests/architecture/`). `pyproject.toml` carries the `[project]` table since Phase 02; install for development with `python -m pip install -e .` (documented in `docs/environment.md` section 4). Version `0.<phase>.<patch>`.

| Package | Status | Phase |
|---|---|---|
| `contracts` | IMPLEMENTED (enums, `FrameSample`/`ImageRef`, `FrameView`, `FrameSource` Protocol, schema access) | 01 spec / 02 code; later records by their producers |
| `timing` | IMPLEMENTED (`now()`, `CLOCK_ID = perf_counter`, CPU-time/sleep/wall-clock helpers) | 02; `TimingRecord` collector in 05 |
| `config` | IMPLEMENTED (fragment merge, schema validation, cross-field checks, `config_hash`, resolved snapshot) | 02 |
| `capture` | IMPLEMENTED (`LiveFrameSource`, backends, ROI helper, queue, stats, timestamp mapping, device probing) | 02 |
| `ui` | `guide.py` IMPLEMENTED (prototype overlay); zones/debug overlay PLANNED | 02 / 04 / 15 |
| `hands`, `stick`, `tracking`, `features`, `geometry`, `prediction`, `commit`, `audio`, `eval`, `data`, `calib`, `app` | PLANNED stubs | 03+ |
