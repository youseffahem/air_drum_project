# spacedrums.data

**Status:** IMPLEMENTED (Phase 06, machinery only) — recording protocol, guided-recorder hooks, `SessionMetadata`,
microphone capture + sync check, session verification / unusable-recording policy, raw manifests. Labelling, QC
and participant-level splits are Phase 07 and do not exist yet.

| Module | Task | Content |
|---|---|---|
| `protocol.py` | 06.2 | `SegmentType` (15 kinds), `SegmentSpec`, `Protocol`, `build_protocol` (zone order seeded from the pseudonym), `check_segment_markers`; `PROTOCOL_VERSION = 0.1-draft` (v1.0 needs the pilot) |
| `metadata.py` | 06.4 | `SessionMetadata` builder / validator for `schemas/session-metadata.schema.json`; `SessionKind` (SYNTHETIC / DEV_CAPTURE / PILOT / PARTICIPANT) with structural promotion refusal; `has_phys_gt` rule; naming |
| `recorder.py` | 06.1 | `GuidedRecorder` hooks (`on_frame`, `on_key`, `status_lines`, `draw_cues`) composed with `spacedrums.app.main.run` by `scripts/record_session.py`; markers half-open on `t_capture`; quick check |
| `audio_capture.py` | 06.6 | `AudioCapture` (PortAudio blocks mapped onto `t_mono`), WAV I/O, `detect_onsets`, `sync_check`, SYNTHETIC click generator |
| `validation.py` | 06.7 / 06.8 | `verify_session` → `verify.json` (checks, quality report, per-take verdicts, `ACCEPT | REVIEW | QUARANTINE`), `VerifyThresholds` (candidates), `ExclusionRecord`s |
| `manifest.py` | 06.9 | `build_raw_manifest` (SHA-256 per file, kind gating by version string, refusal list), `write_manifest` (refuses empty participant manifests), `check_manifest_files`, `apply_withdrawal` |

Layer: below `app` (never imports `spacedrums.app` or `spacedrums.ui`; `.importlinter`). Evidence labels: everything
produced by tests and self-tests is SYNTHETIC or DEV CAPTURE; no participant data exists (Phase 06 gate).
