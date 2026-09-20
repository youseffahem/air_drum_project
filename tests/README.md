# tests/

**Status:** `tests/contracts/` IMPLEMENTED (Phase 01, `TEST-SCHEMA-1`: 99 tests, pass on 2026-09-21 after the gate-review corrections, HW-01). Everything else PLANNED.

Layout mirrors src/spacedrums/<subpackage>/ as tests/<subpackage>/test_*.py; system tests under tests/system/; contract/schema tests under tests/contracts/.

Run (from the repository root): `.venv\Scripts\python.exe -m pytest` (configuration in pyproject.toml). Test ids cited by gate records follow docs/repo-layout.md section 3.5 (`TEST-<AREA>-<N>`); the causality/parity/conformance suites are specified in docs/architecture/causality-tests.md and implemented by the phases named there.
