# Operator Setup Checklist — one per recording session

**Phase:** 06 — Task 06.5 · **Version:** CL-v0.1-draft (2026-09-21) · **Status:** DRAFT; mirrored item for item by `scripts/session_checklist.py` (`CHECKLIST_VERSION`), which files the answers as `<session_dir>/checklist.json`. Not yet used with any person.
**Rule:** every item is answered YES / NO / NA by the operator; nothing is pre-filled. A NO on CL-01…CL-03 means **no recording**. `verify_session` records whether a checklist file exists for participant / pilot sessions (`V-CHECKLIST`); the answers are the operator's responsibility and are never inferred by software.

## 1. Before the participant arrives

| Id | Item | Where the value goes |
|---|---|---|
| CL-01 | Ethics status checked: recording of this session kind is permitted (`docs/ethics/ethics-approval-note.md` answered; for a pilot: the same) | — |
| CL-04 | Camera on its fixed mount at the marked tripod position and height; not moved since the floor marks were made (REQ-024) | `camera_profile_id`; camera profile §7 placement |
| CL-05 | Floor marks present: primary distance mark (candidate `D100` = 1.0 m, ADR-0017) and second mark (label + nominal distance) | `distance_mark.*` |
| CL-06 | Lighting condition set and identified (L1–L5; `docs/protocols/lighting-checklist.md` §5): `python scripts/exposure_blur_check.py inspect --lighting <id>` run; mean luminance (AUTO row) and unique FPS noted; exposure value chosen | `lighting.*` |
| CL-07 | Camera profile confirmed in the config in force (profile id, resolution, requested FPS, exposure mode / value; `config_hash` will be recorded automatically) | `config.snapshot.yaml` |
| CL-10 | Audio output checked: drum sounds audible at a comfortable level (active arm A unless decided otherwise) | `arm_active` |
| CL-15 | Free disk space sufficient (ADR-0019 storage estimate: roughly 0.75 GB per minute at 30 FPS full-frame PNG — DEV CAPTURE estimate; pilot MEASURED value PENDING) | — |

## 2. With the participant

| Id | Item | Where the value goes |
|---|---|---|
| CL-02 | Consent signed (participant / pilot), form version noted, `consent_record_id` assigned; the signed copy is stored separately from the recordings | `consent_status`, `consent_record_id` |
| CL-03 | Pseudonym assigned (`P<NN>` / `PILOT<NN>`); no name is entered anywhere in the session | `participant_id` |
| CL-13 | Participant instruction sheet (`participant-instructions.md`) read with the participant; questions answered; withdrawal right stated | — |
| CL-08 | Playing area: participant stands inside the on-screen box at the primary mark; both hands and both sticks visible in the preview | `roi_px` |
| CL-09 | Sticks described: colour, length class (SHORT / STANDARD / LONG), marker NONE (TAPE only in an explicitly tagged benchmark block), own / project sticks | `stick_description.*`, `tip_method_condition` |
| CL-12 | Background described: tag (CLEAN / CLUTTER / PEOPLE / CLUTTER_PEOPLE), other people present yes / no | `background.*` |
| CL-11 | Pad + microphone (only if used and consented, CF item B1): pad placed at the zone's marked position (surface at the virtual impact surface as seen by the camera, residual offset noted); microphone level checked; clap audible in the monitor | `pad_mic.*`, `operator_notes` |
| CL-14 | Session metadata options entered into `scripts/record_session.py --live …` (participant, session index, lighting, background, sticks, handedness / experience / height range **only if given on the consent form Part D**, distance marks, consent) | `metadata.json` |

## 3. After the session

1. `python scripts/session_checklist.py <session_dir> --operator <initials> --answers <file>` (or `--yes/--no/--na`), so `checklist.json` sits beside `metadata.json`.
2. `python scripts/verify_session.py <session_dir> --exclusions-log data/raw/exclusions.jsonl` — act on `REVIEW` / `QUARANTINE` while the participant is present if possible (re-take = `r` in the recorder, new session index otherwise).
3. Sign the paper checklist; keep it with the consent form.
