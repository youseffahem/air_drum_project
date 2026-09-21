# Phase 03 — Task 03.2 Evidence Note: Left/Right Identity Assignment

| Field | Value |
|---|---|
| Task | 03.2 — Left/Right Identity Assignment (`phases/phase-03-hand-stick-tracking.md`, Checkpoint 03.A) |
| Status | **IMPLEMENTED** (code + synthetic-sequence tests) · swap-rate **MEASURED** on the existing dev captures (no crossings) · deliberate-crossing swap rate **PENDING** (§6: needs a dev capture with crossings; none was recorded, per the owner's instruction) |
| Submitter | Claude (AI assistant) acting for the project owner, 2026-09-21 |
| Code state | Development runs on the uncommitted tree at `4dd0c2e` (`git_dirty: true`). **Clean-tree reruns (C-03-4) on commit `191778882f646444395b58c71134c3942974c5d8`, `git_dirty: false`: `20260921-1447-p03-hands-check-video-idtemporal` and `20260921-1448-p03-hands-check-video-idraw` reproduce every figure in §3 exactly (both-hands 103 / 32 / 0 and 99 / 10 / 0; overrides 4 / 28; jumps 0; ambiguous 0 / 4).** |
| Hardware | HW-01 (`docs/hardware-inventory.md`), mains power, `cv2.getNumThreads() = 8` |
| Related | ADR-0014 §Decision 10; Task 03.1 note (`phase-03-task-03.1-hand-landmarker.md`); README §8 (Q33–Q35); contracts.md §3.2 |

## 1. What was built

| Artefact | Path | Tests |
|---|---|---|
| `IdentityAssigner`: label + continuity scoring, exhaustive injective assignment, ambiguity margin, `handedness_score` cap, event detection/logging (`LABEL_OVERRIDE`, `CONTINUITY_OVERRIDE`, `IDENTITY_JUMP`, `AMBIGUOUS`), causal memory (previous wrist per hand + `t_capture`, expiring after `max_gap_s`), `RAW` mode = Task 03.1 baseline | `src/spacedrums/hands/identity.py` | `tests/hands/test_identity.py` (`TEST-HANDS-4`, 18 cases on synthetic sequences: smooth crossing, label noise, same-label collision with/without memory, coincident hands with weak labels, single detection, gap expiry, identity jump, unknown label, extra detections, empty frames, causality prefix test, settings, reset, event serialisation) |
| Wrapper integration: the assigner replaces the raw label→`hand_id` step; `HandsFrameResult.identity`; `detector_id` gains the identity fragment; counters (`ambiguous_frames`; `label_collisions` = raw collisions in RAW mode, label overrides in TEMPORAL mode so runs stay comparable) | `src/spacedrums/hands/landmarker.py` | `tests/hands/test_landmarker.py` (RAW-mode cases pinned explicitly; TEMPORAL `detector_id`) |
| Config `hands.identity` (`mode`, `gate_distance`, `max_gap_s`, `w_label`, `ambiguity_margin`, `ambiguous_score_cap`); loader rule `tracking.c_min ≤ ambiguous_score_cap < tracking.c_valid` | `configs/schema/config.schema.json`, `configs/example.candidate.yaml`, `src/spacedrums/config/loader.py` | `tests/config/test_loader.py`, `tests/contracts/test_config_schema.py` (+ cases below) |
| Measurement: identity metrics + `identity_events.<capture>.jsonl` per capture; `--identity-mode RAW/TEMPORAL`; overlay tags `raw label -> assigned hand_id` (+ `AMBIGUOUS`); stub backend gained a 20-frame **synthetic** crossing with three label flips | `scripts/hands_landmark_check.py` | `tests/scripts/test_measurement_scripts.py` (TEMPORAL and RAW self-tests) |

Suite after the task: **274 passed, 1 skipped** (opt-in hardware test), from PowerShell and Git Bash; `ruff check .` clean; `lint-imports` 4 kept / 0 broken; `scripts/validate_contracts.py` PASS; both run logs validate against `experiment-log.schema.json`.

## 2. Definitions (what the numbers mean)

All per capture, TEMPORAL mode unless stated; denominators are *frames with ≥ 1 detection* (a frame without hands carries no identity information).

| Quantity | Definition |
|---|---|
| **label override** | an emitted hand whose assigned `hand_id` differs from the estimator's (swap-mapped) label — i.e. the raw label would have swapped or collided; continuity won. This is the **raw-label swap count**. |
| **continuity override** | the assigned detection is not the nearest gated detection to that hand's previous wrist — the label won. Expected at a genuine crossing frame. |
| **identity jump** | assigned detection outside the hand's own gate but inside the other hand's gate — a *possible* track swap of the final output. |
| **ambiguous frame** | best-vs-runner-up assignment margin `< ambiguity_margin`; every emitted `handedness_score` capped at `ambiguous_score_cap` (0.5) → downstream `DEGRADED` at most. |

Ground truth for "which hand is which" does not exist for these captures; the table therefore reports *disagreements between the two information sources* and *ambiguity*, not accuracy. The owner's check (Task 03.1, P-03.1-1) fixes the anatomical meaning of the labels; the swing captures were made without deliberate crossings.

## 3. Swap-rate measurement on the existing dev captures (MEASURED)

Runs (VIDEO mode, `hands` block of `configs/example.candidate.yaml` + HW-01 fragment; identity candidates `gate 0.15`, `max_gap 0.25 s`, `w_label 0.5`, `margin 0.15`, `cap 0.5`):

| Run id | Identity mode | `detector_id` suffix | config_hash |
|---|---|---|---|
| `20260921-1046-p03-hands-check-video-idtemporal` | TEMPORAL | `…:swap0:id-temporal-g0.15-gap0.25-wl0.50-m0.15-cap0.50` | `sha256:a6a5c3acbc49f329d…` |
| `20260921-1046-p03-hands-check-video-idraw` | RAW (Task 03.1 rule) | `…:swap0:id-raw` | `sha256:b5eedb6611a59ca44…` |

| Capture (L2, exposure) | Mode | Frames | Detected frames | Both present | LEFT / RIGHT present | Label overrides (rate) | Continuity overrides | Identity jumps | Ambiguous frames (rate) | Unassigned detections |
|---|---|---|---|---|---|---|---|---|---|---|
| exp-5 (−5) | RAW | 171 | 170 | 99 | 105 / 164 | — (4 raw same-label collisions) | — | — | — | 4 |
| exp-5 (−5) | **TEMPORAL** | 171 | 170 | **103** | 109 / 164 | **4 (0.024)** | 0 | **0** | **0 (0.0)** | 0 |
| exp-6 (−6) | RAW | 171 | 112 | 10 | 23 / 99 | — (22 raw same-label collisions) | — | — | — | 22 |
| exp-6 (−6) | **TEMPORAL** | 171 | 112 | **32** | 47 / 97 | **28 (0.25)** | 1 | **0** | **4 (0.036)** | 0 |
| exp-7 (−7) | both | 172 | 0 | 0 | 0 / 0 | 0 | 0 | 0 | 0 | 0 |

The RAW run reproduces the Task 03.1 numbers exactly (99 / 10 / 0 frames with both hands), confirming the baseline is unchanged.

Where the overrides come from (event files in the TEMPORAL run directory):
- exp-5: 4 `LABEL_OVERRIDE`, all for `LEFT`, on frames 35, 51, 71, 105 (raw scores 0.71–0.96) — isolated single-frame label flips of the image-right hand; no jumps, no ambiguity.
- exp-6: 26 of 28 overrides are `LEFT`; the estimator labelled the image-right hand `Right` on runs of consecutive frames (e.g. frames 21–23: both detections `Right` at 0.89–1.00; wrists at x ≈ 0.36 and 0.66). Continuity kept `LEFT` on the x ≈ 0.66 hand. The 4 ambiguous frames (74, 133, 140, 170) have margins 0.006–0.079: three are single-detection frames whose label contradicts a weak continuity cue, one is a two-detection frame at the end of the capture; each was emitted with `handedness_score ≤ 0.5`. The single `CONTINUITY_OVERRIDE` (frame 169, `RIGHT`, raw score 0.98) is the label winning over a small nearest-wrist difference (0.002 vs 0.022 ROI-normalized units, both well inside the gate) — not a crossing.
- Mean wrist x of the emitted `LEFT` hand in exp-6 moves from 0.42 (RAW) to 0.53 (TEMPORAL); `RIGHT` stays at 0.35. Without ground truth this is reported as a shift toward the side the Task 03.1 owner check established for the anatomical left, not as accuracy.

Processing time is unchanged within noise (exp-5 p50 32.6 ms TEMPORAL vs 33.2 ms RAW; the assigner enumerates ≤ 9 options per frame).

## 4. Synthetic-sequence evidence (labelled SYNTHETIC)

`TEST-HANDS-4` and the `--synthetic` self-test of the check script (stub backend: 10 static frames + a 20-frame crossing where LEFT and RIGHT swap image sides and the labels flip on 3 frames):

| Scenario | Result |
|---|---|
| Crossing, correct labels | identities follow continuity through the crossing; identity confidence > 0.8 on every frame; 0 events except 2 `CONTINUITY_OVERRIDE` at the crossing frame (labels correctly beat the nearest-wrist rule) |
| Crossing, labels flipped on 3 frames | 6 `LABEL_OVERRIDE` (3 frames × 2 hands); 0 identity jumps; 0 ambiguous frames — identities never swap. In RAW mode the same frames swap the emitted `RIGHT` across the image (`|Δx| > 0.2` between frames 14 and 15) |
| Both hands labelled `Right`, memory present | resolved by continuity, 1 override, not ambiguous |
| Both hands labelled `Right`, no memory | AMBIGUOUS (margin 0), both emitted with score ≤ 0.5 |
| Coincident detections, labels 0.55 / 0.55 | AMBIGUOUS (margin 0.10 < 0.15); at 0.6 / 0.6 (margin 0.20) the labels legitimately decide |
| Hands apart, confident label flip | continuity wins by 0.63 |
| Gap > `max_gap_s` | memory expires, labels alone decide, no events |
| Causality | results of the first 15 frames are identical whether or not 15 further frames are fed later |

## 5. Acceptance evaluation against the task

Task 03.2 — *"Combine the estimator's handedness score with temporal continuity (nearest previous wrist position, tunable gating distance) to assign LEFT/RIGHT stably; detect and log swaps; when ambiguous, mark both hands DEGRADED rather than guessing. Evidence: swap-rate measurement on dev captures with deliberate hand crossings; unit tests on synthetic sequences."*

| Requirement | Result |
|---|---|
| Handedness score + temporal continuity, nearest previous wrist, tunable gate | `IdentityAssigner` (§1); `gate_distance`, `max_gap_s`, `w_label`, `ambiguity_margin`, `ambiguous_score_cap` in config, all in `detector_id` |
| Stable assignment | synthetic crossings with label noise: 0 identity swaps (§4); dev captures: 0 identity jumps, 22 raw same-label collisions in exp-6 resolved (§3) |
| Detect and log swaps | four event kinds, `logging` INFO + `identity_events.<capture>.jsonl` per run; counters in `run.json` |
| Ambiguous ⇒ both hands DEGRADED, not guessed | AMBIGUOUS frames cap every `handedness_score` at 0.5; loader enforces `c_min ≤ cap < c_valid`; contract note for Tasks 03.7/03.13 (`tip_confidence ≤ handedness_score`) in ADR-0014 §10 |
| Unit tests on synthetic sequences | `TEST-HANDS-4`, 18 cases; script self-tests (TEMPORAL, RAW) |
| Swap-rate measurement on dev captures **with deliberate crossings** | **PENDING** — the existing captures contain no deliberate crossings and no new recording was permitted; the swap-rate *machinery* is measured on them (§3). Owner item P-03.2-1. |

**Verdict proposed to the owner: Task 03.2 IMPLEMENTED; swap-rate measurement MEASURED on the available captures; the crossing condition is PENDING on a ~10 s developer capture** (not a dataset recording). Task 03.3 may start; the crossing capture can be taken at any later point in Phase 03 (it is also the natural warm-up segment of Task 03.11's movement script).

## 6. Pending items

| Id | Item | Owner | Due |
|---|---|---|---|
| P-03.2-1 | **Deliberate-crossing dev capture** (developer only, not a participant): ~10 s at L2 / exposure −5 with 4–6 slow and fast hand crossings, recorded with `scripts/exposure_blur_check.py record --name cross-L2-exp-5 --exposure MANUAL:-5 --lighting L2 --seconds 10`; then `scripts/hands_landmark_check.py --capture cross-L2-exp-5` and `--identity-mode RAW` for the baseline. Report identity jumps, label overrides, ambiguous frames; owner visually reviews the events' overlay frames. | Project owner | before the Phase 03 gate (can be folded into Task 03.11's session) |
| P-03.2-2 | Tune `ambiguity_margin` / `w_label` only against P-03.2-1 evidence; current values are candidates. | Task 03.11 | Phase 03 gate |
| P-03.2-3 | **CLOSED 2026-09-21** — `20260921-1447-…-idtemporal`, `20260921-1448-…-idraw` on `1917788…`, figures identical. | Submitter | closed |

## 7. Integrity and test status

| # | Item | Answer | Pointer |
|---|---|---|---|
| I-1 | Numbers labelled | YES | §3 MEASURED with run ids; §4 SYNTHETIC; config values marked candidate |
| I-2 | IMPLEMENTED has tests | YES | §1; suite counts in the closing report |
| I-3 | No future frames | YES | assigner memory = previous frames only; prefix-invariance test in `TEST-HANDS-4` |
| I-4 | No fabricated data | YES | dev captures are the owner's Phase 02 developer captures; synthetic crossing labelled SYNTHETIC in code, run description and here |
| I-9 | Scope | YES | no grip points, stick, tracking or zones; `swap_handedness` untouched (owner decision) |
| I-10 | Status vocabulary | YES | phase document status line updated; RTM untouched until the gate |
| I-11 | Reproducibility | PARTIAL | `run.json` valid, snapshots + hashes present; `git_dirty: true` by construction (P-03.2-3) |
| I-12 | Limitations | YES | §2 (no ground truth), §5 (crossings pending), one person / one lighting condition / one camera mode |
