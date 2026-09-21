# Unusable-Recording Policy

**Phase:** 06 — Task 06.8 · **Policy id:** `unusable-recording-policy-v0.1` · **Version:** v0.1 (2026-09-21)
**Status:** IMPLEMENTED as rules in `spacedrums.data.validation` (`verify_session`, `VerifyThresholds`, `exclusion_record`) and applied by `scripts/verify_session.py`; **thresholds are candidates** until the pilot distribution sets them (Task 06.10, PENDING); **applied so far only to SYNTHETIC and DEV CAPTURE sessions** (no participant or pilot session exists).
**Why:** Q60 integrity — exclusions must be rule-based and logged, never silent (phase document, Task 06.8).

## 1. Principles

1. **Objective and immediate.** The verdict is computed from the recorded files by `verify_session` right after the session, so a failed segment can be re-recorded while the participant is present.
2. **Quarantined, never deleted.** Excluded takes and sessions stay on disk exactly as recorded; the manifest builder refuses to list them (`refused` block); every exclusion is an `ExclusionRecord` (`schemas/exclusion-record.schema.json`) in the session's `verify.json` and in `data/manifests/<version>.exclusions.jsonl`. The only deletion is a participant's **withdrawal**.
3. **Reproducible.** The thresholds used are written into `verify.json` with their SHA-256 (`thresholds_hash`); an `ExclusionRecord` carries the same hash and the rule id, so a verdict can be re-derived later.
4. **Labelled.** The verdict document repeats the session classification (SYNTHETIC / DEV CAPTURE / PILOT / PARTICIPANT). A verdict on synthetic or developer material is machinery evidence only.
5. **Never invents a measurement.** A quantity that cannot be computed from the files is `null` with a reason in the check detail.

## 2. Segment-level exclusion (per take)

A take (`segment_id`, `take`) is **EXCLUDED** when any of the following holds; otherwise it is **ACCEPT**. Skipped / aborted takes are **SKIPPED** (not counted).

| Rule | Reason code | Candidate threshold (`VerifyThresholds`) |
|---|---|---|
| Tracking validity ratio (`VALID` frames / frames of the take) below `q_seg` for any **relevant hand** of the segment (the hand(s) the cue names; both for two-hand cues) | `LOW_TRACKING_VALIDITY` | `q_seg = 0.6` — **candidate**; set from the pilot distribution |
| FPS estimate of the take deviates from the profile FPS by more than `segment_fps_tolerance` (profile FPS = MEASURED native FPS if the profile cites one, else the requested mode, labelled as such) | `FPS_DEVIATION` | `segment_fps_tolerance = 0.25` — candidate |
| Fewer than `min_segment_frames` frames | `TOO_FEW_FRAMES` | `5` — candidate |
| Sync failure in a pad segment (fewer than `sync_min_matched` markers matched, or residual spread above `sync_residual_max_s`) — session-level `V-AUDIO` check, applied to the pad takes | `SYNC_FAILURE` | `sync_min_matched = 2`, `sync_residual_max_s = 0.05 s` — candidates |
| Operator-noted protocol violation (`notes` of the take contains `VIOLATION`) | `PROTOCOL_VIOLATION` | — |
| Superseded by a later take of the same segment (kept and flagged `RETAKEN`) | `RETAKEN` | — |

A **re-take** is recorded immediately with key `r`; the failed take is never removed from the recording (its frames stay in the single continuous frame stream; its marker stays in `segments[]` with status `RETAKEN`).

## 3. Session-level verdict

`verify_session` produces **`ACCEPT | REVIEW | QUARANTINE`**:

| Verdict | When |
|---|---|
| **QUARANTINE** | Any *hard* check FAILs: files missing (`V-FILES`), metadata unrecoverable or invalid (`V-META-SCHEMA`), config-hash mismatch between snapshot / metadata / stream headers (`V-CONFIG-HASH`), invalid stream headers (`V-HEADERS`), invalid frame records (`V-FRAMES-SCHEMA`), broken frame ordering or duplicate timestamps (`V-FRAME-ORDER`), missing or orphan image files (`V-FRAME-FILES`), invalid records (`V-RECORDS-SCHEMA`), **consent incomplete** for a participant / pilot session (`V-CONSENT`: status not SIGNED or no record id), or the **session rule**: more than `q_sess` of the recorded core takes excluded (`V-SESSION-POLICY`, `q_sess = 0.5` — candidate). A session-level `ExclusionRecord` is produced. |
| **REVIEW** | No hard failure, but at least one WARN or non-hard FAIL: FPS deviation of the whole session (`V-FPS`, `fps_tolerance = 0.15`), drop fraction above `max_drop_fraction = 0.05`, stalls above `max_stalls = 0`, frame-id gaps, dangling id references (`V-REFS`), TrackState multiplicity (`V-TRACK`), unknown zone ids (`V-ZONES`), commits on non-VALID frames (`V-SAFETY` — an invariant violation in the derived records, regenerable), some core takes excluded (`V-SEG-TRACKING`), audio sync residual spread beyond tolerance, missing operator checklist (`V-CHECKLIST`), operator quality flags (`V-FLAGS`). The session may enter a manifest only with `--include-review` (listed with its verdict). |
| **ACCEPT** | Everything else. |

`V-HANDSWAP` (hand-order flips, a heuristic proxy for identity swaps and crossings) is **reported, never a reason**: crossings are cued by the OCCLUSION segment; Phase 07 QC decides.

## 4. Session-level exclusion reasons (from the phase document)

- more than `q_sess` of the core segments excluded → `SESSION_RULE`;
- consent incomplete → `CONSENT_INCOMPLETE` (a PARTICIPANT session cannot even validate against the metadata schema without `consent_status = SIGNED` and a `consent_record_id`; a PILOT session validates with `PENDING` but is refused by every manifest);
- metadata unrecoverable → `METADATA_UNRECOVERABLE` / `SCHEMA_INVALID`.

## 5. Withdrawal

If a participant withdraws, **all** files of that participant are deleted by the owner and the manifest is rewritten with a withdrawal record that carries no content (`scripts/build_raw_manifest.py withdraw <manifest> --participant P<NN> --date …` → `withdrawals[]`: pseudonym, date, number of sessions removed, note). The participant's exclusion records are removed from the manifest's `exclusions` too (they would otherwise leak session ids).

## 6. Logs

- `<session_dir>/verify.json` — checks, quality report, per-take verdicts, exclusions (schema `session-verification`).
- `data/raw/exclusions.jsonl` (optional running log, `verify_session.py --exclusions-log`) and `data/manifests/<version>.exclusions.jsonl` (written with every manifest) — `ExclusionRecord`s, append-only.

## 7. What is pending

| Item | Marker |
|---|---|
| `q_seg`, `q_sess` values | To Be Experimentally Determined (pilot distribution) |
| FPS tolerances, drop / stall limits | candidates; pilot decides |
| Sync residual tolerance | Pending Benchmark (pilot, Task 06.6) |
| Policy applied to a real session | PENDING — applied so far to SYNTHETIC sessions (`tests/data/test_validation.py`, run `20260921-2351-p06-record-synthetic`) and to the DEV CAPTURE ingest session (`20260921-2352-p06-record-devcapture`: 9/20 core takes excluded by `LOW_TRACKING_VALIDITY` because the developer capture has one hand swinging, which is expected and not a protocol session) |
