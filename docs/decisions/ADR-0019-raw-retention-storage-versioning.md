# ADR-0019 — Raw video retention (full frame, lossless PNG sequence), storage layout, manifest-only dataset versioning, session metadata contract

| Field | Value |
|---|---|
| Status | **Proposed** (Phase 06, Tasks 06.3, 06.4, 06.9; submitted with the Phase 06 gate record). The retention decision is taken on the existing Phase 05 record mode and a DEV CAPTURE storage measurement; the pilot re-track and storage-per-session figures the phase document asks for are PENDING (no pilot recording exists). |
| Date | 2026-09-21 |
| Deciders | Project owner (via the Phase 06 gate), recorded by the Phase 06 submitter |
| Related | ADR-0002 (pad + microphone), ADR-0004 (clock), ADR-0010 (config), ADR-0012 (JSON-Schema contracts), ADR-0013 (capture), ADR-0017 (distance), ADR-0018 (record mode: PNG sequence); `docs/architecture/architecture.md` §12.2–12.3; `docs/architecture/contracts.md` §6; `docs/repo-layout.md` §3.4; `docs/reproducibility-policy.md`; REQ-046–049 |

## Context

Phase 06 must decide (Task 06.3) whether raw recordings keep full camera frames or an ROI crop, which codec, and what a session costs in storage; define (06.4) the `SessionMetadata` contract Phase 01 reserved; fix (06.9) the storage layout, hashing and the versioning tool (DVC vs manifest-only, a *Pending Architecture Decision* of the phase document). Phase 05's record mode already writes a lossless PNG per frame (`frames/frame_NNNNNN.png`, `cv2` compression level 1) beside `frames.jsonl`; `ReplayFrameSource` reads it back; architecture.md §12.2 requires "lossless or codec/parameters recorded".

## Decision

### 1. Retention: full frame, native resolution, lossless intra-frame PNG sequence

- **Full frame** (`image_ref.crop = FULL`) at the camera profile's native resolution (640×480 on HW-01), not the ROI crop: re-tracking with a different ROI (ADR-0017 factorial PENDING) and future methods (Phase 16) stay possible; the ROI is a fixed rectangle recorded per frame (`roi_px`) and can be re-cut at any time. ROI-only (`store_crop: ROI`) remains available in config as the fallback if storage forbids full frames.
- **Codec: PNG, one file per frame** (intra-frame, lossless, `IMWRITE_PNG_COMPRESSION = 1`). No temporal compression → no inter-frame artefacts that could bias later tip estimation; exact regeneration; already implemented and replay-proven (Phase 05 record/replay tests, Phase 06 regeneration check below); no new dependency. The video block of `SessionMetadata` records `container = PNG_SEQUENCE`, `codec = png`, `lossless = true`, crop, frame size and the compression parameter, so a future container change (FFV1/MKV is the candidate alternative) is a recorded change, not a silent one.
- **Storage estimate (DEV CAPTURE, labelled estimate):** the Phase 06 ingest session of the Phase 02 developer capture `swing-L2-exp-5` (171 real 640×480 frames, L2 lighting) measures **414,715 bytes per PNG frame** (`verify.json` → `quality.storage`, run `20260922-0041-p06-record-devcapture`). Arithmetic at 30 FPS: **≈ 0.75 GB per minute**, **≈ 7.5 GB per 10 min**, ≈ 15 GB for a 20-minute session. Per-session storage on a real protocol session is **MEASURED in the pilot (PENDING)**; the number above is a single developer capture in one lighting condition (PNG size depends on image content and noise).
- **Risk recorded:** the PNG encode runs in the processing loop (`SessionRecorder.write_frame`); its per-frame cost on HW-01 during a live session is **Pending Benchmark** (pilot). Mitigations if it causes drops: `IMWRITE_PNG_COMPRESSION = 0` (larger files, faster), ROI crop, or a writer thread (Phase 16 threading, ADR-0009). Post-hoc re-compression to level 9 or FFV1 for archival is allowed only as a verified lossless transform with the new parameters recorded in the metadata and a new manifest version.
- **Re-track check (Task 06.3 evidence, DEV CAPTURE):** `scripts/regenerate_session.py` replays a session's PNGs through the live perception + decision pipeline with `producer = REGENERATED` and compares every derived stream. On the developer session (run `20260922-0041-p06-regenerate-session`): **DECISION-IDENTICAL** — hand observations bit-identical; stick, track, candidate, commit and audio records identical in every decision field (frames, hands, statuses, zones, arms), with numeric fields differing only by floating-point noise (max |Δ| = 1.1 × 10⁻¹⁴; ids differ only by the session-id prefix; live stamps excluded). The perception stage is therefore deterministic in content but **not bit-exact across processes** (numpy summation/alignment in the stick RANSAC/PCA); two regenerations in separate processes were bit-identical to each other. Consequence: Phase 09/13 parity tests must compare with a stated numeric tolerance (candidate 1e-9), never bit-for-bit, unless the perception stage is made bit-reproducible.

### 2. `SessionMetadata` contract (`schemas/session-metadata.schema.json`, version 1.0)

Implements the Phase 01 reservation (contracts.md §6) with every reserved field plus the Phase 06 fields, and adds the **session-kind classification** as a structural rule: `session_kind ∈ {SYNTHETIC, DEV_CAPTURE, PILOT, PARTICIPANT}` with conditional constraints on ids (`SYNTHETIC` / `DEV` / `PILOT<NN>` / `P<NN>`), session ids, consent (`NOT_REQUIRED` for synthetic/dev; `SIGNED` + record id for participants), dataset versions (synthetic/dev only in `ds-raw-v0.0-selftest*`), lighting ids (`L0`/`SYNTHETIC` never on a participant session) and source kind. Developer or synthetic material therefore **cannot** be relabelled as participant data without failing validation (integrity I-4). Fields without a value carry `NOT_COLLECTED` / `null` (participant meta, luminance, measured FPS, capture stats); nothing is defaulted to a plausible value. `has_phys_gt` follows the three-level availability rule of contracts.md §6 and is recomputed by the metadata builder. Segment markers are half-open intervals on `t_capture`.

Schema owner: Phase 06. Compatibility: additive changes → minor bump; changed meaning → major bump with migration notes (contracts.md §8). Companion documents: `session-verification` (verify.json), `exclusion-record`, `raw-manifest` — all version 1.0, examples under `schemas/examples/` (SYNTHETIC).

### 3. Storage layout, hashing, versioning: manifest-only (no DVC)

```
data/raw/<participant_id>/<session_id>/
    frames/frame_NNNNNN.png   frames.jsonl   records/<RecordType>.jsonl   timing.jsonl
    config.snapshot.yaml      session.json (Phase 05 provenance)   metadata.json (SessionMetadata)
    verify.json               checklist.json?   audio_track.wav?
data/manifests/<dataset_version>.json              tracked in git
data/manifests/<dataset_version>.exclusions.jsonl  tracked in git
```

- `data/**` stays git-ignored except `README.md` and `data/manifests/**`.
- A manifest lists every file of every accepted session (relative POSIX path, bytes, SHA-256), sorted by participant id, session id, path (dataset order = manifest order, reproducibility-policy §2); its canonical SHA-256 (`manifest_hash`) is the `dataset_hash` of experiment logs.
- Manifest **kind** is derived from the version string and gates admission: `ds-raw-v<M>.<m>` → PARTICIPANT sessions with SIGNED consent only; `…-pilot` → PILOT sessions with SIGNED consent; `ds-raw-v0.0-selftest[-slug]` → SYNTHETIC / DEV_CAPTURE only, labelled "TEST / DEVELOPMENT ONLY". Refused sessions are listed with the reason. An empty PARTICIPANT/PILOT manifest is refused (a `ds-raw-v1.0.json` cannot exist before participant sessions do).
- **Versioning tool = manifest-only.** DVC was considered and not adopted: the project has one development machine, no remote storage, and a file-based manifest + hash policy already in force (reproducibility-policy.md §3–5); DVC would add a second source of truth and a dependency for no reproducibility gain at this scale. If a remote / multi-machine dataset store becomes necessary (Phase 23 release), DVC or a git-annex-style tool may be adopted by a new ADR that keeps the manifest as the system of record.
- Withdrawal: files deleted by the owner; manifest rewritten with a content-free withdrawal record (policy §5).

## Alternatives considered

| Alternative | Why not |
|---|---|
| FFV1 in MKV (lossless video) | Needs ffmpeg/pyav (not in the lock file); intra-frame FFV1 is equivalent to PNG in loss terms; deferred as the archival re-compression candidate. |
| Visually lossless (H.264 CRF low) | Temporal compression alters edges the stick segmentation depends on; excluded by architecture.md §12.2 unless parameters are recorded, and any effect on re-tracking would need the pilot re-track test — not available. |
| ROI-only frames | ~18 % smaller on the current ROI; forecloses ROI changes and background-context analysis (Q28); kept as a config fallback. |
| DVC | See above. |
| `session.json` as the SessionMetadata (architecture.md §12.2 table) | Phase 05 already writes `session.json` as developer provenance; Phase 06 adds `metadata.json` next to it rather than repurposing a field (Phase 01 fallback rule: never repurpose). architecture.md §12.2 is amended accordingly. |

## Consequences

- `SessionRecorder` unchanged; `spacedrums.app.main` gains `--regenerated` (producer `REGENERATED`) and the composition hooks the guided recorder uses.
- Phase 07 consumes `metadata.json` (segments, `has_phys_gt`, pad markers), `verify.json` (per-take verdicts) and the manifest; labels and splits stay in Phase 07.
- Storage per participant session is large (≈ 0.75 GB/min estimate); disk space is a checklist item (CL-15) and a pilot measurement.
- Parity tests (Phase 13 `TEST-PARITY-1`) must state a numeric tolerance.
