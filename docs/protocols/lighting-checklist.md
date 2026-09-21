# Lighting-Variation Checklist

**Phase:** 02 — Task 02.9 · **Status:** IMPLEMENTED (checklist defined; no condition has been *measured* yet except the developer condition noted in §4)
**Used by:** Phase 03 (tracking benchmarks, Task 03.11), Phase 05 (playable prototype checks), Phase 06 (session metadata `lighting` descriptor, Q27–Q29), Phase 17 (robustness / failure injection), Phase 18 (reporting conditions per result).
**Source:** `project-discovery.md` Q27 ("normal indoor lighting … multiple realistic lighting conditions rather than … laboratory lighting"); REQ-027.

## 1. Why a checklist

Every result of this project must state the lighting it was obtained under (integrity item I-12). Phase 02 found that lighting is not a cosmetic factor on HW-01: under auto-exposure in a dim room the integrated webcam's sensor drops to **~10 unique frames/s** while the Windows pipeline pads the stream to a nominal 30 FPS with byte-identical frames (camera profile §5). A tracking or latency number without its lighting condition is therefore not interpretable.

## 2. Condition ids (candidate set — the final set is fixed with the recording location in Phase 06)

| Id | Name | How to reproduce | Expected effect on capture (to be measured) |
|---|---|---|---|
| **L1** | Daylight from a window | Daytime, curtains open, room lights off, user not back-lit (window to the side of or behind the camera) | Highest luminance; shortest usable manual exposure; least noise |
| **L2** | Overhead room light | Evening or curtains closed, ceiling light(s) on, no daylight | The "normal indoor" reference condition; manual exposure candidate `-6` (15.6 ms) |
| **L3** | Dim / evening | Single lamp or dimmed room light, no daylight; screen brightness normal | Auto-exposure lowers the frame rate (measured on HW-01); manual exposure gives dark, noisy frames — the trade-off of Q27 |
| **L4** | Mixed | Daylight from a window **and** overhead light | Colour temperature mix; flicker possible from mains lighting |
| **L5** | Back-lit | Window or bright lamp *behind* the user, in the camera's field of view | Auto-exposure darkens the user; hands/stick become silhouettes |
| **L0** | Developer / unspecified | Anything not matching L1–L5; must still be described in free text | Only for developer captures under `data/dev-captures/`; never for participant sessions |

Rules: a session records exactly one primary id; if the light changes mid-session (cloud, someone switches a lamp), the session is split into segments with their own id (Phase 06 `segments[]`), or the session is marked unusable per Phase 06's policy.

## 3. What to record per condition (session metadata, Phase 06 schema)

| Field | How to obtain | Why |
|---|---|---|
| `lighting.id` | one of L0–L5 | grouping in Phase 18 tables |
| `lighting.description` | free text: light sources, positions relative to camera/user, time of day, curtains | reproduction |
| `lighting.mean_luminance_auto` | mean grey level of the full frame under **auto** exposure, averaged over 2 s, from `scripts/exposure_blur_check.py inspect` (row `AUTO`) | objective proxy for the amount of light; comparable across sessions on the same camera |
| `lighting.auto_exposure_unique_fps` | unique-frame rate under auto exposure (same script) | detects the low-light frame-rate cap before recording |
| `lighting.exposure_used` | the `camera_profile.exposure` block in force (mode, value) | the setting the tracker actually saw |
| `lighting.flicker_note` | "none observed" / description | mains flicker shows as periodic luminance change in the FPS run's luminance samples |
| `background.description` | free text (Q28: uncontrolled background is allowed and must be described) | robustness reporting |

## 4. Conditions used so far

| Date | Condition | Where recorded | Notes |
|---|---|---|---|
| 2026-09-21 (night, 02:40–03:20 local) | **L0** — developer, unspecified: room lit essentially only by the laptop screen, whose brightness was at **0 %** (inspected 03:09); mean frame luminance under auto exposure ≈ 12–13 grey levels during the runs (an exploratory probe at ~00:30 saw ≈ 65, consistent with the screen having been dimmed in between); auto-exposure unique rate ≈ 10 FPS | Phase 02 FPS / exposure / latency runs (camera profile §3, §5, §6, §9) | No person was present to set or describe the room light; only the luminance proxy and the screen brightness are known. All Phase 02 numbers carry this condition; the flash-latency method needed exposure −4/−5 instead of the baseline −6 because of it. |

## 5. Procedure for a lighting check before any recording session (Phase 06)

1. Set the room to the intended condition id; describe it in the session notes.
2. Run `python scripts/exposure_blur_check.py inspect --backends <profile backend> --lighting <id>`; record `mean_luminance` and `unique_fps_short` of the `AUTO` row and of the profile's manual value.
3. If the manual setting of the camera profile yields mean luminance below the candidate floor (**To Be Experimentally Determined** in Phase 03 from tracking quality; placeholder: not below ~25 grey levels) choose the next longer exposure that still keeps ~30 unique FPS, and record the value used.
4. Record a 5 s stick swing with `exposure_blur_check.py record` and run `analyze`; keep the peak-motion crop with the session as the qualitative blur reference.
5. Enter the fields of §3 into the session metadata.

## 6. Open items

- Final condition set and the exact rooms: decided with the recording location (Phase 06).
- Luminance floor for tracking: **To Be Experimentally Determined** (Phase 03).
- Whether L3/L5 are recorded with participants or only in the Phase 17 robustness tests: Open Question (owner).
