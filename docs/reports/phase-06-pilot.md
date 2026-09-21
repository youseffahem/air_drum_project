# Phase 06 — Pilot Recording and Pipeline Validation Report

**Task:** 06.10 · **Date:** 2026-09-21 · **Hardware:** HW-01 · **Code:** dirty tree on `483f58bc021cb7c6d6c3086ca6c3955e95b41a06` (Phase 06 working tree; clean-tree reruns are a gate condition)
**Status of the pilot itself: PENDING / NOT VALIDATED.** No pilot session has been recorded: no person was at the camera, the owner decided that no new recording is made in this phase, and the ethics question (`docs/ethics/ethics-approval-note.md`) is still an Open Question, which forbids even a pilot recording. Every MEASURED quantity the phase document expects from the pilot is therefore **PENDING** (§4). What this report contains is the validation of the *pipeline machinery* on SYNTHETIC input and on an existing DEV CAPTURE — machinery evidence, never a pilot result.

## 1. What was validated without a person

| Check | Input | Label | Evidence | Result |
|---|---|---|---|---|
| Full draft protocol (25 segments incl. the pad block) through the recording tool in record mode: segment markers, cues, quick checks, `metadata.json`, SYNTHETIC click track through the microphone-capture path, verification | generated observations (`scripts/_p06.synthetic_protocol_sequence`, seed 0) | **SYNTHETIC** | run `20260921-2351-p06-record-synthetic` (`record_session.json`, `metadata.json`, `verify.json`) | COMPLETED; 1131 frames, 25 takes, 0 commits on non-VALID frames; verify **ACCEPT**, every check PASS, sync 2/2 markers matched (residual spread 8.5e-14 s — a property of the generated clicks, not of any microphone) |
| Real recorded frames through the same path (Phase 02 developer capture `swing-L2-exp-5`, 171 frames, L2): MediaPipe perception, stick, tracking, commit, record, metadata, verification | existing dev capture (no new recording) | **DEV CAPTURE** | run `20260921-2352-p06-record-devcapture`; session `data/raw/DEV/dev-p06-ingest-exp-5` (git-ignored) | COMPLETED; every integrity check PASS (files, schemas, config hash, frame order, images, FPS 29.93 vs requested 30, 1 drop, 0 stalls, references, safety 0); verdict **REVIEW** because 9/20 core takes fail `q_seg` on the LEFT hand — expected: the capture is one developer hand swinging for 6 s, not a protocol session. Storage: 414,715 bytes/frame (PNG level 1) |
| Re-track from raw frames (Task 06.3): regenerated derived records vs recorded ones | the DEV CAPTURE session above | **DEV CAPTURE** | run `20260921-2352-p06-regenerate-session` (`regenerate_session.json`) | **DECISION-IDENTICAL**: HandObservation bit-identical; all other streams identical in every decision field; numeric noise max 1.1e-14 (not bit-exact across processes — ADR-0019 §1) |
| Manifest builder on the above | SYNTHETIC + DEV CAPTURE sessions | **SYNTHETIC / DEV CAPTURE** | `tests/data/test_manifest.py`, `tests/scripts/test_phase06_scripts.py` | self-test manifests build, validate, re-hash clean; `ds-raw-v1.0` build refuses both kinds and writes nothing |
| Unit / integration tests | SYNTHETIC | **VERIFIED on SYNTHETIC** | `tests/data/` (40 tests), `tests/scripts/test_phase06_scripts.py` (7) | pass |

## 2. Tool stability

The recording tool ran the full protocol to completion in both modes without exceptions (SYNTHETIC: 1131 frames; DEV CAPTURE: 171 frames with the real perception stage, ~20 s wall clock on HW-01 including MediaPipe start-up). **Stability over a real 15–20 minute session with a person, the live window, keyboard control and PNG writes at 30 FPS is PENDING** (pilot). The PNG write cost per frame is a Pending Benchmark (ADR-0019 risk).

## 3. Protocol timing

Candidate total of cued playing: ~336 s for 4 zones without optional blocks (arithmetic over candidate durations, `docs/protocols/recording-protocol.md` §2). **Session length: MEASURED in the pilot — PENDING.**

## 4. Pilot measurements required by the phase document

| Quantity | Label | Value |
|---|---|---|
| Session length per protocol version | MEASURED (pilot) | **PENDING** |
| Storage per session | MEASURED (pilot) | **PENDING** — DEV CAPTURE estimate only: 414,715 bytes/frame → ≈ 0.75 GB/min at 30 FPS (arithmetic) |
| Per-segment tracking validity ratio distribution (→ `q_seg`, `q_sess`) | MEASURED (verify script on pilot sessions) | **PENDING** — thresholds remain candidates (0.6 / 0.5) |
| Drop / stall counts per session | MEASURED | **PENDING** (DEV CAPTURE ingest: 1 drop, 0 stalls over 171 frames — not a protocol session) |
| Pad+mic sync residual (clap-based) | MEASURED (pilot) | **PENDING** — machinery verified on a SYNTHETIC click track only |
| Pad+mic go / no-go | decision | **PENDING** (no microphone or pad inventoried: `docs/hardware-inventory.md`) |
| Record-mode per-frame overhead (PNG write) | Pending Benchmark | **PENDING** |
| Issues found / fixed in the pilot | — | none observed (no pilot) |
| Protocol v1.0 freeze | decision | **PENDING** — protocol stays v0.1-draft |

## 5. Issues found during the machinery validation (and their status)

1. Regeneration from raw frames is decision-identical but not bit-identical across processes (stick estimator floating-point noise ≤ 1.1e-14). Recorded in ADR-0019; parity tests must use a tolerance. Not fixed (no functional impact; a bit-reproducible perception stage is a Phase 16/17 option).
2. Hand-order flips are a poor exclusion criterion (crossings are cued): demoted to a reported quantity for Phase 07 QC.
3. An empty participant manifest could be written when no session qualified: the builder now refuses it.

## 6. Limitations

Everything above is machinery evidence on generated observations or one 6-second developer capture in one lighting condition. It says nothing about protocol adherence, participant behaviour, session length, tracking validity of real participants, storage of a real session, microphone feasibility, or the values of any threshold. Those are the pilot's job, and the pilot has not happened.
