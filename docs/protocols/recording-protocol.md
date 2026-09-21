# Recording Protocol — Space Drums data collection

**Phase:** 06 — Task 06.2 · **Protocol id:** `spacedrums-recording-protocol` · **Version:** **v0.1-draft** (2026-09-21)
**Status:** IMPLEMENTED as machinery and documentation (`src/spacedrums/data/protocol.py`, `scripts/record_session.py`); **not yet run with any person**. v1.0 is frozen only after the pilot of Task 06.10, which is **PENDING** (no participant or pilot recording may be made before the ethics question in [`../ethics/ethics-approval-note.md`](../ethics/ethics-approval-note.md) is answered; the owner has additionally decided that no new recording is made in this phase).
**Source:** `phases/phase-06-data-collection.md` Task 06.2; `project-discovery.md` Q47–Q48; ADR-0002 (pad condition); ADR-0017 (distance); `docs/protocols/lighting-checklist.md`.

> Every duration, count and tempo in this document is a **candidate** (the phase document: "final durations/counts tunable and recorded in the protocol version"). The session length "candidate total" is arithmetic over the candidates, never a measured session length. The machine-readable definition in `protocol.py` is the source of truth; this document describes it.

## 1. Design

- **Within-participant, fixed/structured** (Q47): every participant performs all core segments; free play is not part of v0.1 (Open Question, enabled only explicitly with `--free-play`).
- **Zone order randomised per participant** for the single-hit block: a deterministic permutation seeded from `sha256(participant_id | session_index | protocol_id)` (`participant_seed`), so the order is reproducible from the metadata alone and differs between participants (order confounds, Experimental Design of the phase document). The seed and the order are recorded in `metadata.json` → `protocol`.
- **Segment markers on the capture clock:** each take is the half-open interval `[t_start, t_end)` on `t_capture`; `t_start` is the `t_capture` of the first frame in the take, `t_end` that of the first frame after it. Every frame therefore belongs to at most one take, reproducibly from `frames.jsonl` alone.
- **A cue is an instruction, not a label.** The segment type says what the participant was asked to do; Phase 07 labels come from observation of the recording (phase document, Failure Modes).
- **Active arm:** A (reactive) is the default for v0.1 (`--arm`), recorded per session; the Open Question "A only vs balanced A/B" remains for the owner.
- **Same causal pipeline as the live app:** the recorder is `spacedrums.app.main --record` with the guided-recorder hooks; derived records are convenience outputs, raw frames are authoritative (ADR-0019).

## 2. Segment list (v0.1-draft)

Ids as generated for a 4-zone layout with `snare` as primary zone `z1` and `hihat` as secondary zone `z2`; `zN` = the participant's randomised zone order. Core = counts towards the session-level exclusion rule of the unusable-recording policy.

| # (phase doc) | Segment id(s) | `SegmentType` | Cue (on screen) | Hands | Candidate duration | Core | Expects strikes |
|---|---|---|---|---|---|---|---|
| 1 | `s01_warmup` | `WARMUP` | Warm-up: move freely, do NOT strike | both | 20 s | yes | no (negative) |
| 2 | `s02…s09_single_<zone>_<R/L>` | `SINGLE_HITS` × 2·zones | Single hits on `<zone>`, one hand, ~1/s | R then L, zones in `zN` order | 12 s each (96 s for 4 zones) | yes | yes |
| 3a | `s10_alt_one_zone` | `ALTERNATING_ONE_ZONE` | Alternating L/R on `z1` | both | 15 s | yes | yes |
| 3b | `s11_alt_two_zones` | `ALTERNATING_TWO_ZONES` | R on `z1`, L on `z2`, alternating | both | 15 s | yes | yes |
| 4 | `s12_tempo_slow`, `s13_tempo_medium`, `s14_tempo_fast` | `TEMPO` × 3 | Repeated hits on `z1`, RIGHT, metronome 60 / 100 / 140 bpm (candidates) | R | 15 s each | yes | yes |
| 5 | `s15_rapid_R`, `s16_rapid_L` | `RAPID` × 2 | Rapid hits on `z1`, as fast as comfortable | R / L | 10 s each | yes | yes |
| 6 | `s17_near_simultaneous` | `NEAR_SIMULTANEOUS` | Both hands together: R on `z1` + L on `z2` | both | 15 s | yes | yes |
| 7 | `s18_move_between` | `MOVE_BETWEEN_ZONES` | Move between the highlighted zones WITHOUT striking | both | 15 s | yes | no (negative) |
| 8 | `s19_fake_swing` | `FAKE_SWING` | Swing towards `z1`, pull up before entering | both | 15 s | yes | no (negative) |
| 9 | `s20_stop_before_impact` | `STOP_BEFORE_IMPACT` | Approach `z1`, stop just above the surface | both | 15 s | yes | no (negative) |
| 10 | `s21_occlusion` | `OCCLUSION` | Play `z1` while crossing hands / stick in front of the other hand | both | 15 s | yes | yes |
| 11 | `s22_tracking_interruption` | `TRACKING_INTERRUPTION` | Play; move one hand out of the box and back; operator covers the camera briefly | both | 15 s | yes | yes |
| 12 | `s23_distance_variation` | `DISTANCE_VARIATION` | Step to the second floor mark; single hits on `z1`, `z2` | both | 20 s | no | yes |
| 13 | `s24_lighting_variation` | `LIGHTING_VARIATION` | Operator changes the lighting (checklist id); single hits on `z1` | both | 20 s | no | yes |
| 14 (optional) | `s25_pad_mic` | `PAD_MIC` (`condition = PAD`, `pad_zone_id`) | Practice pad at the pad zone; operator claps (key `m`) at start and end; single hits on the pad | both | 30 s | no | yes |
| 15 (optional, off) | `s26_free_play` | `FREE_PLAY` | Free play | both | 60 s | no | yes |

Candidate total (arithmetic, 4 zones, no optional blocks): **~336 s of cued playing** (`Protocol.total_duration_s`); plus set-up, instructions, breaks and re-takes — the real session length is **MEASURED in the pilot (PENDING)**.

Tempo candidates: `TEMPO_BPM_CANDIDATES = {SLOW: 60, MEDIUM: 100, FAST: 140}` bpm; set on the metronome cue, recorded per segment (`tempo_bpm`). The metronome *tone* is optional in v0.1 (the cue shows the bpm; an audible click is a candidate improvement for the pilot).

## 3. Session flow (operator)

1. **Before the participant arrives:** `docs/protocols/operator-checklist.md` items CL-04…CL-07, CL-10, CL-15 (camera mount, floor marks, lighting check with `scripts/exposure_blur_check.py inspect`, camera profile, audio, disk space).
2. **Consent → pseudonym:** consent form CF (current version), `consent_record_id` assigned, pseudonym `P<NN>` (or `PILOT<NN>`); no name enters the recording (CL-01…CL-03).
3. **Instructions:** read `docs/protocols/participant-instructions.md` with the participant; sticks described (CL-09); background described (CL-12).
4. **Start the recorder** with the metadata options (CL-14), e.g.
   `python scripts/record_session.py --live --kind PARTICIPANT --participant P07 --session-index 1 --consent-status SIGNED --consent-record-id CF-… --lighting L2 --lighting-description "…" --background CLEAN --people-present no --stick-colour "…" --stick-length STANDARD --stick-owner OWN --handedness RIGHT --experience SOME --distance-mark D100 --distance-m 1.0 --second-distance-mark D130 --second-distance-m 1.3 [--pad-zone snare --mic-device "…"]`
   The recorder names the session `P07-S1` under `data/raw/P07/`, shows each cue with the highlighted zone(s) and a countdown, advances on time or on `n`, re-takes on `r` (the failed take stays, flagged `RETAKEN`), skips on `k`, places a sync marker on `m` (pad segment: clap in view of the camera **and** press `m` at the clap), and prints the post-segment quick check (frames, FPS estimate, drops, tracking validity per hand → `OK` / `REVIEW`). A `REVIEW` quick check is the cue to re-take immediately while the participant is present (Task 06.8).
5. **Between blocks:** 12/13 need the second floor mark / the second lighting condition (recorded as `distance_mark.second_mark_label`, `lighting.second_condition_id`); skip with `k` if the room does not allow them (recorded as a limitation, never simulated — phase document, Risks).
6. **End:** `q` closes the session; `metadata.json` is written (segments, markers, quick checks, `has_phys_gt`, capture stats).
7. **Immediately after:** `python scripts/session_checklist.py data/raw/P07/P07-S1 --operator XX --answers …` (file the checklist) and `python scripts/verify_session.py data/raw/P07/P07-S1 --exclusions-log data/raw/exclusions.jsonl` → `ACCEPT | REVIEW | QUARANTINE` with reasons; re-record segments while the participant is present if the verdict asks for it.
8. **Later:** `python scripts/build_raw_manifest.py build ds-raw-v1.0` (participant manifest; refuses anything that is not a consented participant session).

## 4. Metadata recorded per session

`schemas/session-metadata.schema.json` (Task 06.4): session kind and ids, participant meta (consent-form Part D; `NOT_COLLECTED` when not given), location, hardware / camera / audio profiles, ROI, distance marks, lighting (checklist fields), background, sticks, tip method + marker condition, active/shadow arms, config hash, git SHA, clock id, zone layout id, protocol version + seed + zone order + options, segments (id, type, take, `t_start`, `t_end`, condition, pad zone, status, cue, zones, hands, tempo, notes, quick check), pad+mic block (markers, audio track sidecar, alignment residual), `has_phys_gt` (availability rule of contracts.md §6), capture stats, video container/codec, consent status + record id, source kind, generator, operator notes, quality flags.

## 5. What the pilot must decide before v1.0 (all PENDING)

| Item | Marker |
|---|---|
| Segment durations, counts, tempi | To Be Experimentally Determined (pilot session length MEASURED) |
| `q_seg`, `q_sess` exclusion thresholds | To Be Experimentally Determined (pilot validity-ratio distribution) |
| Pad+mic feasibility, sync residual, subset size | Pending Benchmark (pilot) |
| Record-mode per-frame overhead of the PNG writes (drops) | Pending Benchmark (pilot; ADR-0019 risk) |
| Taped-stick benchmark block per participant | Open Question (owner) |
| Active arm A only vs balanced A/B | Open Question (owner; A recorded by default) |
| Free play after structured results | Open Question (Q47) |
| Final lighting condition set and room | Open Question (with the recording location) |

## 6. Change log

| Version | Date | Change |
|---|---|---|
| v0.1-draft | 2026-09-21 | First machine-readable draft; no session run with a person. |
