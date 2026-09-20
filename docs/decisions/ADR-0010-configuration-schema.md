# ADR-0010 — Configuration: one schema-validated resolved document, candidate vs frozen files

| Field | Value |
|---|---|
| Status | **Accepted** (Phase 01, Task 01.7 / 01.10) |
| Date | 2026-09-20 |
| Deciders | Project owner, recorded by Phase 01 |
| Related | `configs/schema/config.schema.json`; `configs/example.candidate.yaml`; `docs/reproducibility-policy.md` §3; `docs/repo-layout.md` §3.1 (amended below); `docs/architecture/architecture.md` §14; REQ-308, REQ-023 (I-5), REQ-018 |

## Context

Every experiment must be reproducible from a config snapshot (Phase 00 policy). Thresholds (`c_valid`, `τ_commit`, refractory…), zone layouts, camera and audio settings, model paths and debug flags are spread across modules and phases. Without one schema, a typo silently changes behaviour, a measured value (native FPS) can be written into a config as if it were a setting, and the reproducibility hash covers an undefined object. The repo layout of Phase 00 prescribes versioned `<component>.<variant>.v<N>.yaml` names, while phases 02/04/05 also plan `*.candidate.yaml` development files.

## Decision

1. **One top-level schema** (`configs/schema/config.schema.json`, JSON Schema 2020-12, `additionalProperties: false` throughout) describes the **resolved** configuration: blocks `meta`, `camera_profile`, `roi`, `zones[]`, `tracking`, `anticipator`, `commit`, `audio`, `debug`, optional `arms`. Whether a run assembles it from one file or several fragments is an implementation detail of the loader (Phase 02); the resolved document is what is validated, written to `config.resolved.yaml`, and hashed (`config_hash`).
2. **Validation is mandatory at load, before any computation.** A config that does not validate stops the run. Loader-level cross-field checks (e.g. `c_min ≤ c_valid`, impact surface on the zone boundary) are listed in the schema descriptions and implemented by the owning phase.
3. **Every numeric value is tunable and labelled.** `meta.status` is `candidate` (development; may not be cited by a MEASURED result) or `frozen` (immutable versioned file `<component>.<variant>.v<N>.yaml` per `repo-layout.md` §3.1). Repo-layout amendment: files named `*.candidate.yaml` are permitted **only** with `meta.status: candidate` and never cited by a gate record or thesis result; freezing copies them to a versioned name with `supersedes` set.
4. **Measured values cannot masquerade as settings.** `camera_profile.requested_fps` is the requested mode; the delivered rate lives in `native_fps_measured {value_fps, run_id, method}` or is `null`. The schema makes a number without provenance invalid (integrity I-5).
5. Units in keys: seconds `_s`, pixels `_px`, frames `_frames`, Hz `_hz`; no `_ms` keys (tested).
6. Scope guards live in the schema: `trigger_type` enum is `HAND_TIP` only (ADR-0011); `queue.drop_policy` is `DROP_OLDEST` only (ADR-0009); `allowed_hands` defaults to both (REQ-011).

## Alternatives considered

| Alternative | Why not |
|---|---|
| pydantic models as the only schema | Excellent in Python, but the contract would be Python-only; JSON Schema is language-neutral, diffable, and the same validator library already serves the experiment log. pydantic may still be used *inside* the loader as long as it is generated from / checked against the JSON Schema. |
| Free-form YAML with defaults in code | Typos become silent behaviour changes; the hash would not describe behaviour. |
| Per-module independent schemas without a top-level document | The reproducibility hash needs one object; cross-module consistency (feature schema id ↔ model, zone ids ↔ samples) needs a single view. |
| Allowing a measured FPS as a plain number | Exactly the integrity failure I-5 is written to prevent. |

## Consequences

- Phase 02 writes the loader (`spacedrums.config`), the canonical JSON hashing, and the first real `camera_profile`; Phases 04/05/13 fill their blocks; each addition is a schema minor bump + example update + test run (`TEST-SCHEMA-1`).
- Release configs (Phase 20) extend the schema with a `release` block (superset), as the Phase 20 document already anticipates.
- The example config is a test fixture, not a runnable profile; it is explicitly marked as such.
