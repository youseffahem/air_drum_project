# tests/

**Status:** `tests/contracts/` (Phase 01 `TEST-SCHEMA-1` + Phase 02 record-class cases), `tests/timing/`, `tests/config/`, `tests/capture/`, `tests/ui/`, `tests/architecture/`, `tests/scripts/` IMPLEMENTED (Phase 02). Everything else PLANNED.

Layout mirrors `src/spacedrums/<subpackage>/` as `tests/<subpackage>/test_*.py`; cross-cutting suites under `tests/architecture/` (layer rules), `tests/scripts/` (measurement scripts in synthetic mode), later `tests/system/`.

Run (repository root): `.venv\Scripts\python.exe -m pytest` (configuration in `pyproject.toml`). Hardware tests are opt-in: `set SPACEDRUMS_HW_TESTS=1` runs `tests/capture/test_hardware_capture.py` against the webcam.

Test ids cited by gate records (`docs/repo-layout.md` section 3.5): `TEST-SCHEMA-1` (contracts), `TEST-TIMING-1`, `TEST-CONFIG-1`, `TEST-CAPTURE-1…5`, `TEST-UI-1`, `TEST-ARCH-1`, `TEST-SCRIPTS-1`; the live-source case of `TEST-CONFORM-7` is in `tests/capture/test_source.py`. Causality/parity suites: `docs/architecture/causality-tests.md`, implemented by the phases named there.
