# spacedrums

**Status:** PLANNED - package skeleton only (Phase 00, Task 00.4; amended by Phase 01, ADR-0012). No `__init__.py`, no code.

Subpackages are stubs; each README names the owning phase. Phase 01 added the type-only packages `contracts/`, `timing/`, `config/` (layer L0 of docs/architecture/architecture.md section 2.2); `app/` (composition root) is created by Phase 05. The allowed-dependency layers are enforced with import-linter from Phase 02 on. `pyproject.toml` currently holds tool configuration only; the `[project]` table arrives with the first module code (Phase 02).
