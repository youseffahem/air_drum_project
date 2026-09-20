# ADR-0012 — Record contracts as versioned JSON Schemas; type-only packages added to the layout

| Field | Value |
|---|---|
| Status | **Accepted** (Phase 01, Task 01.2 / 01.9 / 01.10) |
| Date | 2026-09-20 |
| Deciders | Project owner, recorded by Phase 01 |
| Related | `docs/architecture/contracts.md`; `schemas/*.schema.json`; `docs/repo-layout.md` §1, §2, §4 (amended here); `docs/architecture/architecture.md` §2.1, §12; REQ-108 (offline = online), REQ-308 |

## Context

Phases 06/07 store records on disk, Phase 09 replays them, Phase 13 must produce the same records live. The phase document allows "JSON Schema or dataclass stubs used only as schema". Phase 00 already uses JSON Schema (experiment log) with `jsonschema` in the lock. The repo layout deferred `pyproject.toml` and any package code to Phase 01/02 and has no home for shared record types, the clock accessor, the config loader, or the application composition root.

## Decision

1. **JSON Schema Draft 2020-12 is the contract.** One schema per record type under `schemas/`, shared definitions in `schemas/common.schema.json` referenced by `$ref`, `additionalProperties: false`, a pinned `schema_version` const per record, conditional (`if/then`) rules for source/status/kind-dependent nullability. Python classes (dataclasses or pydantic) that implement the records must serialise to exactly this JSON and are validated against the schemas in tests; the class is never the source of truth.
2. **Record streams on disk** are JSONL with a `RecordStreamHeader` first line pinning units, schema version and provenance (`contracts.md` §4). Raw video + `FrameSample` streams are authoritative; every other stream is derived and regenerable (`architecture.md` §12).
3. **Versioning:** additive nullable field → minor bump; meaning/unit/nullability change or removal → major bump with migration notes; fields are never repurposed; enums are extended only by bump + ADR (`contracts.md` §8).
4. **Layout amendment (`repo-layout.md`):** add `src/spacedrums/contracts/` (record types, enums, interface `Protocol`s), `src/spacedrums/timing/` (clock accessor, `TimingRecord` collector), `src/spacedrums/config/` (schema-validated loader, hashing) as type-only/low-level packages at layer L0, and `src/spacedrums/app/` as the composition root (created by Phase 05). Add `tests/contracts/` for `TEST-SCHEMA-1`. Add a minimal `pyproject.toml` holding **tool configuration only** (pytest, ruff); the `[project]` table and build backend arrive with the first module code (Phase 02).
5. **Naming amendment:** `*.candidate.yaml` config files are allowed with `meta.status: candidate` (ADR-0010).

## Alternatives considered

| Alternative | Why not |
|---|---|
| pydantic models as the contract | Python-only; harder to diff/review; the same validator would not serve non-Python tools (e.g. a thesis figure script in another language) — allowed as implementation, not as contract. |
| Dataclass stubs with no machine validation | Cannot reject a malformed record on disk; would not satisfy the acceptance criterion "machine-readable schema that validates". |
| Protocol Buffers / Avro | Strong typing and evolution rules, but adds a toolchain and binary files to a single-developer research project whose data volumes (records, not pixels) are small; JSONL is greppable and diffable. |
| Keep all types inside each pipeline package | Circular imports (commit needs TrackState and StrikeCandidate) and no single place for the import-linter's lowest layer. |

## Consequences

- 12 record schemas (11 at submission + the diagnostic-only `DirectPrediction` added at the gate review, 2026-09-21) + config schema exist and are tested now (`tests/contracts/`, `scripts/validate_contracts.py`).
- Every later phase that adds a field runs `TEST-SCHEMA-1` and updates the example; a schema bump is visible in the diff of `schema_version`.
- Disk cost of JSONL is accepted for V1; a columnar export (`.parquet` is already git-ignored) may be added by `eval` for analysis without changing the contract.
- `src/spacedrums/` still contains no code after Phase 01; the README stubs for the new packages state their owning phase.
