# Phase 06 — Data Collection Pipeline

## Status

Planned

## Purpose

Build the recording tool, the structured recording protocol, the participant workflow (consent → setup → guided segments → verification), the session metadata schema, storage/versioning conventions, and the unusable-recording policy; validate the whole pipeline with a pilot; then record the participant dataset (target ~10–12 participants, 1–2 sessions each). This phase produces raw recordings and metadata — **no labels** (Phase 07) and **no training** (Phase 09+).

## Why This Phase Exists

The temporal model and every experimental comparison depend on a dataset that (a) contains the positive and negative behaviours listed in Q48, (b) is recorded with the same causal pipeline that will run live, (c) has reproducible metadata, and (d) is structured for participant-level splitting (Q49). A recording pipeline that is not validated before real participants arrive wastes the scarcest resource in the project — participant time.

## Relationship to Research Contribution

- Negative examples (fake swings, stop-before-impact, movement between zones) are the material for the **false-positive** axis of the primary analysis.
- Speed, distance, lighting, and occlusion variation determine whether measured lead time generalises.
- The optional practice-pad + microphone condition (ADR-0002) is the **only** source of `t_impact_phys`, enabling Phase 07 to validate `t_impact_est` against a physical reference.
- Raw video retention allows re-running improved trackers later (Phase 16) without new participants.

## Inputs

- Phase 05 application in record mode; frozen candidate prototype config (zone layout, thresholds, camera profile, ROI/distance from Phase 03).
- Phase 00 consent/information templates; ethics decision.
- Phase 02 lighting checklist; camera profile.
- Phase 01 `SessionMetadata` reservation; `FrameSample` and record schemas.
- Requirements traced (Phase 00 RTM, `docs/requirements/rtm.md`): owns REQ-003, REQ-046, REQ-047, REQ-048; contributes to REQ-012, REQ-024, REQ-027, REQ-028, REQ-032, REQ-049.

## Expected Outputs

- Recording tool (`recorder` + guided-protocol UI with on-screen cues and segment markers).
- Recording Protocol document (participant instructions, setup, segment list, timings).
- Session Metadata schema + validator.
- Storage layout, naming, checksums, dataset raw-version manifest (`ds-raw-v1.0`).
- Unusable-recording policy and exclusion log.
- Pilot recording report (pipeline validated on developer/pilot volunteers, labelled pilot).
- Participant recordings (count and durations reported as MEASURED after collection; no numbers assumed).
- Optional pad+mic subset recordings with synchronization markers.

## Dependencies

- Phase 05 Exit Gate; Phase 00 ethics/consent resolved (approval obtained or documented as not required).

## System Components

- `src/spacedrums/data/recorder.py` (extends Phase 05 record mode: segment markers, cue display, metadata prompts).
- `src/spacedrums/data/protocol.py` (segment definitions, timing, randomisation of zone order).
- `src/spacedrums/data/metadata.py` (schema, validation).
- `src/spacedrums/data/audio_capture.py` (microphone capture for the pad+mic condition, timestamped on `t_mono`).
- `scripts/session_checklist.py`, `scripts/verify_session.py` (post-session integrity checks), `scripts/build_raw_manifest.py`.
- `docs/protocols/recording-protocol.md`.

## Architecture

```
Participant ──► consent (paper/digital, ID → pseudonym) ──► setup checklist (camera profile, ROI/distance mark on floor, lighting tag)
   ──► recorder: warm-up + segments with on-screen cues ──► per-segment markers (t_mono) in session log
   ──► raw video (ROI or full frame — see 06.3) + FrameSample meta + all causal records (shadow A and B) + timing
   ──► optional: microphone stream + sync markers (clap / flash)
   ──► verify_session (integrity, FPS, drops, tracking validity ratio) ──► accept | quarantine
   ──► raw manifest (hashes) ──► ds-raw-vX.Y
```

- The recorder uses the **same causal pipeline** as the live app; recorded derived records are convenience outputs — the raw video is authoritative and derived records can be regenerated (Phase 01 Task 01.9).
- Sound feedback during recording: the live system plays sounds (active arm A or B per session config) so participants behave as real users; the active arm is recorded in metadata because it may influence behaviour (Open Question below).

## Detailed Tasks

### Task 06.1 — Recording Tool
- **What:** Extend record mode with: segment markers (`segment_id`, start/end `t_mono`), on-screen cue rendering (zone highlight, text, countdown, metronome tone optional), metadata prompts at session start, automatic file naming, and a post-segment quick check (FPS, drops, tracking validity ratio for the segment).
- **Why:** Protocol adherence and immediate detection of unusable segments.
- **Depends on:** Phase 05 Task 05.5.
- **Evidence:** Tool runs a full protocol on a pilot; all files present and schema-valid.

### Task 06.2 — Structured Recording Protocol
- **What:** Define the session script (fixed/structured, Q47). Candidate segment list (final durations/counts tunable and recorded in the protocol version):
  1. Warm-up / free movement without striking (also serves as no-strike motion).
  2. Single hits per zone, each hand separately, cued zone order randomised per participant.
  3. Alternating L/R hits on one zone; then on two zones.
  4. Repeated hits on one zone at three cued tempi (slow / medium / fast; tempo values are candidates, set via metronome, recorded).
  5. Rapid consecutive hits (as fast as comfortable) per hand.
  6. Near-simultaneous two-hand hits on two zones.
  7. Movement between zones without striking (cued path).
  8. Fake swings: swing toward a cued zone and pull up before entering.
  9. Stop-before-impact: approach a cued zone and stop just above the impact surface.
  10. Deliberate occlusion: cross hands / bring one stick in front of the other hand while playing.
  11. Induced tracking interruption: briefly move a hand out of the ROI and return; briefly cover the camera (operator).
  12. Distance variation: repeat a short hit block at a second marked distance.
  13. Lighting variation: repeat a short hit block under a second lighting condition (from the checklist), if the room allows.
  14. Optional pad+mic condition: a practice pad placed at one zone's physical position (height/location marked); participant strikes the pad; microphone records; sync markers at start/end.
  15. Optional free play (only if the owner decides to add it after reviewing structured results — Open Question; not in v1.0 of the protocol).
- **Why:** Q47–48 coverage of positives and all negative classes; controlled variation.
- **Depends on:** Phase 05 protocol scripting.
- **Evidence:** Versioned protocol document; cue definitions in `protocol.py`; pilot run-through timing (session length MEASURED on pilot).

### Task 06.3 — Raw Video Retention Policy
- **What:** Decide (ADR) whether to store full camera frames or ROI-only frames; codec (lossless or visually lossless intra-frame candidate to avoid temporal compression artefacts affecting later tracking); storage estimate per session (computed from the camera profile, labelled estimate). Recommendation: full frame at native resolution if storage permits, else ROI with margin.
- **Why:** Retaining raw video enables re-tracking with improved methods; compression choice affects future tip accuracy.
- **Depends on:** Phase 02 camera profile.
- **Evidence:** ADR; storage estimate; a pilot file re-tracked to confirm derived records regenerate.

### Task 06.4 — Session Metadata Schema
- **What:** Fields: `session_id`, `participant_pseudonym`, `participant_meta` (handedness, self-reported drumming experience level, height range — optional, consent-gated), `session_index`, `date`, `location_tag`, `camera_profile_id` + measured FPS for this session, `roi`, `distance_mark`, `lighting_tag`, `background_tag` (clutter/people present: yes/no), `stick_description` (colour, length class, marker: none/tape), `tip_method_active`, `arm_active` (A/B), `config_hash`, `zone_layout_id`, `segments[]` (id, type, start, end, notes), `pad_mic: {present, zone_id, sync_markers[]}`, `operator_notes`, `quality_flags[]`, `schema_version`.
- **Why:** Q49 reproducibility; stratified analysis later.
- **Depends on:** Phase 01 reservation.
- **Evidence:** Schema + validator; every pilot and participant session validates.

### Task 06.5 — Setup Checklist and Participant Instructions
- **What:** Operator checklist (tripod position/height marks, distance floor marks, lighting per tag, camera profile confirmation, audio device check, microphone check if pad condition, consent signed, pseudonym assigned). Participant instruction sheet in plain language: how to hold the sticks (natural grip; no special rule), where to stand (inside the on-screen box), what each cue means, that fake swings and stops are intentional, and that they may withdraw at any time.
- **Why:** Q19, Q32; consistency across sessions.
- **Depends on:** 06.2.
- **Evidence:** Checklist and instruction sheet; signed checklist per session.

### Task 06.6 — Pad + Microphone Condition (optional, ADR-0002)
- **What:** Microphone capture timestamped on `t_mono`; sync markers (operator clap in view + audible, and/or on-screen flash with a synchronized click) at segment start and end for drift check; pad placement procedure so that the physical pad surface coincides with the virtual zone's impact surface as seen by the camera (documented, approximate; residual offset noted). Feasibility (mic latency, sync accuracy) is Pending Benchmark in the pilot.
- **Why:** Only route to `t_impact_phys` (README §5.2); validates the geometric `t_impact_est`.
- **Depends on:** 06.1.
- **Evidence:** Pilot sync-accuracy measurement (clap-based offset residual, MEASURED); go/no-go recorded in the pilot report.

### Task 06.7 — Session Verification Script
- **What:** Post-session checks: file completeness, schema validity, measured FPS vs. profile (tolerance tunable), drop/stall counts, per-segment tracking validity ratio per hand, hand-swap events, audio sync residual (if pad). Produces a verdict `ACCEPT | REVIEW | QUARANTINE` with reasons.
- **Why:** Unusable-recording policy must be objective and immediate (re-record while the participant is present).
- **Depends on:** 06.1, 06.4.
- **Evidence:** Script; verdict logs for all sessions.

### Task 06.8 — Unusable-Recording Policy
- **What:** Definitions:
  - **Segment-level** exclusion if: tracking validity ratio below threshold `q_seg` (tunable; candidate to be set from pilot distribution) for the relevant hand(s); FPS deviation beyond tolerance; sync failure (pad condition); protocol violation noted by operator.
  - **Session-level** exclusion if: more than a fraction `q_sess` (tunable) of core segments excluded; consent incomplete; metadata unrecoverable.
  - Excluded material is **quarantined, never deleted** (unless the participant withdraws), listed in `exclusions.jsonl` with reason, and never enters train/val/test.
  - Re-recording: a failed segment is re-recorded immediately if time permits; the failed take is kept and flagged.
  - Withdrawal: all files of that participant are deleted and the manifest updated with a withdrawal record (no content).
- **Why:** Q60 integrity — exclusions must be rule-based and logged, not silent.
- **Depends on:** 06.7.
- **Evidence:** Policy document; exclusion log format; applied in pilot.

### Task 06.9 — Storage Layout, Naming, Hashing, Versioning
- **What:** `data/raw/<participant_pseudonym>/<session_id>/{video.*, frames.jsonl, records/, timing.jsonl, audio.wav?, metadata.json, config.snapshot.yaml, verify.json}`; SHA-256 per file; `data/manifests/ds-raw-v1.0.json` listing all accepted sessions with hashes; git-ignored data, tracked manifest; versioning tool choice (DVC vs. manifest-only) = Pending Architecture Decision recorded here.
- **Why:** Reproducibility; dataset versioning (Q49).
- **Depends on:** 06.7.
- **Evidence:** Manifest builder; a manifest for the pilot (`ds-raw-v0.x-pilot`).

### Task 06.10 — Pilot Recording and Pipeline Validation
- **What:** Run the full protocol with the developer and 1–2 volunteers (labelled pilot; included in the dataset only if they consent under the same protocol and are counted as participants — otherwise excluded from all splits). Measure session length, verify tool stability, sync accuracy, storage size, verdict script behaviour; adjust protocol → v1.0 freeze.
- **Why:** Do not discover tool defects on participant time.
- **Depends on:** 06.1–06.9.
- **Evidence:** Pilot report (MEASURED session length, storage per session, sync residual, issues found/fixed); protocol v1.0 frozen.

### Task 06.11 — Participant Recording Campaign
- **What:** Recruit ~10–12 participants (target); schedule 1–2 sessions each per availability; run the frozen protocol; verify each session; build `ds-raw-v1.0` manifest. Report the actual number of participants, sessions, accepted/quarantined segments, total duration — all MEASURED after the fact.
- **Why:** Q46.
- **Depends on:** 06.10.
- **Evidence:** Manifest; campaign report with actual counts; exclusion log.

## Data Requirements

- Participants: target ~10–12 (Q46); actual count reported, not assumed. Mixed experience levels preferred; handedness recorded.
- Per session: all core segments (1–11); distance/lighting variation segments (12–13) where feasible; pad+mic condition (14) for a subset (size To Be Experimentally Determined by feasibility and time).
- Sticks: participants' own ordinary sticks or a project-provided pair (colour recorded). Marker (tape) condition only as an explicitly tagged benchmark block if included (Open Question: include a short taped block per participant for the Phase 03/18 marker benchmark? — recommended if it costs < a few minutes; decision recorded in protocol v1.0).
- Backgrounds: normal room; a subset with people/objects moving in the background (Q29), tagged.

## Algorithms / Technical Approach

- Recording is the Phase 05 causal pipeline; no new algorithms.
- Sync: cross-correlation of the clap in the microphone stream with the operator-marked `t_mono` and/or the flash frame; residual reported.
- Verification: threshold checks on per-segment statistics.

## Interfaces / Contracts

- `SessionMetadata` schema (Task 06.4) — consumed by Phases 07–19.
- Raw layout and manifest format (Task 06.9) — consumed by Phase 07.
- Segment types enumeration (Task 06.2) — consumed by Phase 07 labelling rules.

## Tests

- **Unit:** metadata validation; manifest hashing; verification thresholds; segment marker integrity (no overlaps, monotone).
- **Integration:** pilot session end-to-end; regenerate derived records from raw video and compare with recorded ones (determinism of the causal pipeline).
- **Sync test:** clap/flash offset residual on pilot (pad condition).

## Measurements

| Quantity | Method | Label |
|----------|--------|-------|
| Session length per protocol version | pilot / campaign | MEASURED |
| Storage per session | pilot | MEASURED |
| Per-segment tracking validity ratio distribution | verify script | MEASURED |
| Drop/stall counts per session | verify script | MEASURED |
| Pad+mic sync residual | Task 06.6 | MEASURED (pilot) |
| Participants, sessions, segments accepted/quarantined, total minutes | campaign | MEASURED |

## Experimental Design

- The protocol is a within-participant design: every participant performs all core segment types, with zone order randomised per participant to avoid order confounds. Distance and lighting variation are within-participant blocks where feasible.
- Active arm during recording (A or B) is recorded per session; if both are used across participants, balance is attempted and recorded (Open Question below).

## Acceptance Criteria

1. Recording tool, metadata schema, verification script, and manifest builder implemented and tested.
2. Protocol v1.0 frozen after a pilot; participant instruction sheet and operator checklist exist.
3. Unusable-recording policy documented and applied; exclusion log exists.
4. Pad+mic condition go/no-go recorded with measured sync residual.
5. Campaign completed with actual counts reported; `ds-raw-v1.0` manifest with hashes; all sessions schema-valid; consent records complete.

## Definition of Done

- All acceptance criteria; campaign report; gate record PASS; integrity checklist applied (no dataset-size numbers beyond actual counts; pilot data clearly labelled).

## Risks

- Recruitment shortfall → report the actual number; adjust split strategy in Phase 07 (participant-grouped CV handles small N; no fabrication).
- Tool crash mid-session → per-segment files and verification make partial sessions salvageable.
- Lighting/distance variation not feasible in the room → recorded as a limitation, not simulated.
- Pad+mic sync unreliable → condition dropped with the pilot evidence; `t_impact_phys` remains PENDING.

## Failure Modes

- Participant behaviour drifts from the cue (e.g. striking during a fake-swing segment) → operator note + Phase 07 manual review handles; segment type is a cue, labels come from observation.
- Hand swaps during crossings → recorded; Phase 07 QC.

## Fallback Strategy

- If markerless tracking validity is too low for some participants' sticks, record an additional taped block (labelled MARKER benchmark) rather than excluding the participant; markerless blocks stay in the dataset with their validity ratios.
- If fewer than the target participants are available, proceed with what exists and document; Phase 07 split design adapts.

## Artifacts Produced

- `src/spacedrums/data/{recorder,protocol,metadata,audio_capture}.py`
- `scripts/{session_checklist,verify_session,build_raw_manifest}.py`
- `docs/protocols/recording-protocol-v1.0.md`, `docs/protocols/participant-instructions.md`, `docs/protocols/operator-checklist.md`
- `docs/policies/unusable-recording-policy.md`
- `schemas/session-metadata.schema.json`
- `data/manifests/ds-raw-v0.x-pilot.json`, `data/manifests/ds-raw-v1.0.json`
- `docs/reports/phase-06-pilot.md`, `docs/reports/phase-06-campaign.md`
- `docs/gates/phase-06-gate.md`

## Exit Gate

Reviewer verifies protocol, policy, pilot report, campaign report, manifest, and consent completeness. PASS → Phase 07.

## What Must NOT Be Done Yet

- No labels, no train/val/test split files (Phase 07).
- No model training or feature statistics computed on the recordings.
- No reporting of strike counts as "accuracy" — only tracking-validity and integrity statistics.
- No dataset release.

## Open Questions

- Should the active arm during recording be A only (simplest, avoids anticipation influencing behaviour) or balanced A/B? (Recommendation: A only for v1.0; record as decision.)
- Include a short taped-stick benchmark block per participant?
- Add free/natural playing after reviewing structured results (Q47)?
- Institutional ethics approval status (from Phase 00).

## Decisions That Must Be Experimentally Validated

- Segment durations/counts and tempi (pilot).
- `q_seg`, `q_sess` exclusion thresholds (set from pilot distribution, then frozen).
- Pad+mic feasibility and subset size (pilot).
- Video codec/retention choice's effect on re-tracking (pilot re-track test).
