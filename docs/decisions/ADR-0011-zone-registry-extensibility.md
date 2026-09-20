# ADR-0011 — Zone-registry extensibility: open trigger-type enum, generic tracked-point geometry, hand-agnostic zones

| Field | Value |
|---|---|
| Status | **Accepted** (Phase 01, Task 01.8 / 01.10) |
| Date | 2026-09-20 |
| Deciders | Project owner (Q11, Q17, Q55), recorded by Phase 01 |
| Related | `docs/requirements/out-of-scope.md` (REQ-207, §2 re-inclusion rule, §3 `OOS-REF` tags); ADR-0003; `docs/architecture/architecture.md` §10; `schemas/common.schema.json` (`trigger_type`, `hand_id`); `configs/schema/config.schema.json` (`zones[]`); REQ-011, REQ-055, REQ-207 |

## Context

Kick/foot interaction is outside V1 (Q55, REQ-207) but the architecture must not make it impossible. Either hand may hit any zone unless experiments show otherwise (Q11). The zone registry is the place where both constraints meet: a closed design would need a rewrite for a foot trigger; a design that implements foot support would violate scope.

## Decision

1. `Zone.trigger_type` is an enum with the single value `HAND_TIP` in schema 1.0. The enum is **declared open**: `FOOT` is a reserved name, tagged `OOS-REF:REQ-207` wherever mentioned, and can only be added by (a) the scope-expansion procedure of `out-of-scope.md` §2, (b) an ADR, and (c) a schema-version bump. A config containing `FOOT` is **invalid today** (schema test).
2. `geometry.intersect` is generic over a **trajectory of a tracked point** (`Trajectory{point_id, kind, samples}`); it assumes nothing about sticks or hands. `point_id` is a `hand_id` in V1; `LEFT_FOOT`/`RIGHT_FOOT` are reserved names under the same rule as above. A future foot tracker would produce `TrackState`-like records for a new `point_id` and reuse geometry, commit and audio unchanged.
3. Zones are **hand-agnostic**: `allowed_hands` is optional, defaults to `[LEFT, RIGHT]`, is present in the schema so a Phase 18 experiment on hand–zone assignment can be expressed without a schema change, and may not be restricted in V1 configs without an ADR.
4. Zone identities are stable string ids (ADR-0003); `kick` is a reserved id with no layout entry, sample or trigger in any V1 config.
5. Trigger-type and point-id vocabularies are shared by `SessionMetadata`/`LabelRecord` (Phases 06/07) so a dataset could later carry foot labels with only the enum bump.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Include `FOOT` in the enum now, unimplemented | A config could then request a foot zone that silently does nothing; also a scope contact without the re-inclusion procedure (integrity I-9). |
| Hard-code zones to hands (per-zone hand assignment) | Contradicts Q11; would prejudge a Phase 18 experiment. |
| Separate `FootZone`/`HandZone` types | Duplicates geometry; the generic trajectory input is the simpler extensibility point. |
| Kick via a hand gesture in V1 (ADR-0003 candidate (b) for the 7th zone) | Not excluded by this ADR — it would still be `HAND_TIP`; decided at the Phase 04 gate per ADR-0003. |

## Consequences

- Phase 04 implements the registry with the six ADR-0003 ids and reserved `kick`; validation rejects unknown trigger types.
- `grep -r OOS-REF` lists every intentional contact (schemas, config example, this ADR, architecture §10).
- Adding a foot trigger later touches: enum bump (common schema), a new tracker producer, session/label metadata — and nothing in geometry/commit/audio.
