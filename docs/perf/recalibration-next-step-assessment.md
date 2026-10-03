# Re-calibration next step: tracking depth versus camera setup (read-only assessment)

**Status: ASSESSED. No direction chosen.**
- **Nothing adopted or changed:**
  - no code, config, layout or fitter change;
  - no calibration written;
  - no camera data collected, no live experiment, no participant data.
- **The offline FIXED candidate `cand-fixed4-v1` stays an offline feasibility finding only.** It is not
  adopted and not run live.
- **Phase 18 remains BLOCKED.**

Evidence (git-ignored, local): `experiments/pre-participant/20261003-recalibration/next-step-assessment/`.
- **Tables:** every number below comes from `tables.md`, which is generated from the JSON.
- **Code state:** HEAD `064cda5` plus the uncommitted working tree, unchanged before and after
  (`checks/production-*.txt`).
- **Follows:**
  - `experiments/.../20261003-recalibration/fitter-investigation/REPORT.md`;
  - `experiments/.../20261003-recalibration/candidate-layout/REPORT.md`;
  - `docs/perf/strike-reliability.md`.

**Provenance labels:**
- **[RECORDED]:** read from calibration files, observer rows or project documents.
- **[OFFLINE]:** computed here from recorded evidence with unchanged production code.
- **[INFERENCE]:** interpretation.
- **[HYPOTHESIS]:** an engineering model of setups that were never recorded. It is not a measurement.

"Reliable" means the tracker status is VALID (tip confidence ≥ `c_valid`). Nothing here is an accuracy
claim.

## 1. Owner decision

**The decision.** Should the next engineering target be:
- **A.** the four-zone layout, redesigned around the narrow band where tracking is reliable today; or
- **B.** the camera / setup first, so that reliable tracking covers more of the real stroke, with a layout
  designed after that?

**What the evidence supports:**
1. **The reliable band ends at the same height in every run.**
   - Below tip y ≈ 0.40–0.425 (ROI units, y down), the VALID share falls under 50 %.
   - This holds in Run1 at exposure −5 and in Run4 / Run5 at −6, in the slow sweep and in the test
     strikes. [OFFLINE]
   - Since the boundary is the same at −5 and −6, exposure does not explain it.
2. **What fails below the band is perception, and the failures are mixed.**
   - Hand not detected: up to 34 % of frames in Run4 strikes.
   - A low-confidence stick axis: 18–33 % at y 0.40–0.45.
   - No stick axis at all (tip placed at the prior length): up to 69 % in the Run1 session.
   - When a stick axis *is* found there, it is usually as long as higher up. [OFFLINE]
3. **Part of the stroke is not visible to the current estimator.**
   - The production tip is grip + L_prior × axis direction.
   - The reliable tip's vertical travel is about the hand's own travel: Run1 VALID tip 5–95 range 0.17–0.27
     against a wrist range of 0.21–0.24.
   - [INFERENCE] A stick rotating towards the camera changes mainly its visible length and its detectability,
     not the estimated tip height.
4. **The specific hypothesis ("sticks point toward the camera in the lower stroke") is consistent with some
   of the evidence but not established** (§3).
   - Supporting:
     - In the Run1 session, the right stick is found in only 27.5 % of frames at the hand's lowest
       positions.
     - The rejected candidates there are short blobs (median elongation 3.8).
     - Motion blur does not explain it: slow frames are worse.
   - Not supporting: in Run4 / Run5 the sticks that are still tracked low are not shorter. This check is
     survivorship-biased, because foreshortened sticks drop out.
   - Hand loss is a separate failure that no evidence links to viewpoint.
5. **No setup other than the current one has ever been tracked.**
   - The current setup: integrated laptop webcam, lens 0.75 m, tilt 0°, user ≈ 1.0 m.
   - The distance × lighting factorial (C-03-3) was never run, and the field of view is PENDING.
   - Every statement about another camera height, angle, distance or azimuth is a hypothesis (§5).

**Neither direction is supported by measured evidence of success.**
- A rests on in-sample geometry that passes only at the threshold (`cand-fixed4-v1`).
- B rests on a geometric model and on indirect 2D signals.
- **What each direction would need first:**
  - **A:** held-out recorded evidence that a band-shaped layout can be struck reliably, from more than one
    standing position.
  - **B:** a developer-only capture at two or three camera placements, measuring the band and the
    stick-visibility signals used here.
- Section 6 sets out evidence, unknowns, tests and risks for each.

## 2. Q1: reliable tracking versus vertical tip position [RECORDED → OFFLINE]

**Sources:**
- Run4 / Run5 wizard observer rows: 9,148 and 3,210 frames.
- The Run1 calibrated play session (`data/dev-sessions/dev-20260928-calib-run1-session`, 325 frames, −5,
  played with `dev-owner-run1.calib.yaml`). Its existing probe rows were used, plus a gated observer replay.
- Runs 2–3 exist only as calibration files.

| Evidence | VALID tip y p50 | VALID tip y p95 | Collapse y (VALID share < 50 %) | Loss hazard after a VALID frame: descending / still / ascending |
|---|---:|---:|---:|---|
| Run4 slow sweep | 0.355 | 0.442 | **0.400** | 0.26 / 0.13 / 0.24 |
| Run4 test strikes | 0.359 | 0.478 | **0.425** | 0.29 / 0.18 / 0.15 |
| Run5 slow sweep | 0.337 | 0.391 | **0.400** | 0.12 / 0.11 / 0.08 |
| Run5 test strikes | 0.374 | 0.562 | **0.400** | 0.20 / 0.15 / 0.23 |
| Run1 play (−5) | 0.344 | 0.439 | **0.425** | 0.27 / 0.15 / 0.17 |

**How the columns are defined:**
- **Collapse y:** fixed in the script before it ran. Start at the bin with the most VALID tips, scan
  downwards, and take the first bin (≥ 8 frames) with a VALID share under 50 %.
- **Loss hazard:** the probability that a VALID tip is no longer VALID on the next consecutive frame. It
  uses observed positions only.

**Hazard by height** (per-frame loss probability for a VALID tip):
- **Within 0.30–0.40:** 0.07–0.34. The worst case is Run5 strikes at 0.35–0.40 (0.34).
- **Within 0.40–0.45:** 0.28–0.43.
- **At ≥ 0.45:** 0.30–0.67.
- **The last VALID tip before a loss** sits at median y 0.35–0.41.

**Across all five runs** (calibration files) [RECORDED]:
- The sweep's VALID 5–95 envelope is 0.095–0.237 tall (Run1 0.203, Run2 0.210, Run3 0.237, Run4 0.181,
  Run5 0.095).
- Test strikes detected: hi-hat 0–1/5 and snare 1–4/5.

**What replaces VALID below y 0.40.** It differs by run (`tables.md` T3):

| Evidence | VALID at 0.35–0.40 | VALID at 0.40–0.45 | Bridged (hand not detected) at 0.40–0.50 | DEGRADED axis at 0.40–0.45 | No axis (prior) at 0.40–0.50 |
|---|---:|---:|---:|---:|---:|
| Run4 strikes | 0.78 | 0.51 | 0.21–0.26 | 0.18 | 0.08–0.09 |
| Run5 strikes | 0.63 | 0.46 | 0.06–0.18 | 0.19 | 0.28–0.29 |
| Run1 play | 0.75 | 0.54 | 0.06–0.12 | 0.31 | 0.03–0.38 |

**Headroom (Run1 session).**
- Wrists sit at y 0.50–0.80 (p1–p99) and reliable tips at 0.16–0.90.
- That leaves about 86 px below the lowest wrists and about 69 px above the highest reliable tips.

## 3. Q2: stick orientation and depth

**What the code makes observable [RECORDED].**
- The production GEOM tip is `axis origin + L_prior × axis direction` (`stick/estimator.py:geom_tip`). The
  tip is not at the observed end of the stick.
- The only direct visibility signals per frame are:
  - the observed axis support (visible stick length, capped by a search region about 4 hand spans long:
    131–144 px here);
  - the axis direction and confidence;
  - the stick-candidate components (elongation, angle, rejection reason).
- No 3D orientation, pitch or depth is measured anywhere in the project.

**Run1 session, stroke height from the wrist landmark (independent of the stick)** [OFFLINE].
- **Method:** observer replay with unchanged production code, identical to the existing probe rows on
  650/650 hand-frames.

| Hand / wrist-height quartile | Axis found | VALID | Visible support p50 | / L | Rejections in no-axis frames |
|---|---:|---:|---:|---:|---|
| RIGHT, highest (Q1) | 61 % | 46 % | 64 px | 0.44 | orientation 43, not elongated 36, too small 33 |
| RIGHT, Q2 / Q3 | 89 % / 81 % | 81 % / 67 % | 111 / 108 px | 0.77 / 0.75 | ≤ 21 each |
| **RIGHT, lowest (Q4)** | **28 %** | **18 %** | 113 px (when found) | 0.79 | **orientation 60, too small 56, not elongated 54** |
| LEFT, highest (Q1) | 67 % | 41 % | 69 px | 0.53 | orientation 33, too small 21, not elongated 14 |
| LEFT, Q2 / Q3 | 84 % / 99 % | 57 % / 90 % | 86 / 108 px | 0.66 / 0.83 | ≤ 12 each |
| LEFT, lowest (Q4) | 99 % | 41 % | 118 px | 0.91 | 5 |

- **Motion blur is not the explanation.** Wrist speed is the blur proxy. For the right hand at its lowest
  positions, slow frames find the stick in 14 % of cases, fast frames in 86 % (n 64 / 14).
- **The right-hand failures are short, blob-like candidates** (median maximum elongation 3.8), rejected for
  orientation, size and elongation. When a stick is found there, it is long, so visibility is all-or-nothing.
- **The left hand at its lowest positions is a different case.** The stick is found and long, but only 41 %
  of frames are VALID. That failure lies outside stick visibility (confidence or identity).
- **The highest wrist positions** have shorter visible sticks (≈ 0.5 L) and larger image angles in both hands.

**Run4 / Run5 (estimated tip height)** [OFFLINE].
- In frames with an observed axis, the visible support does **not** shrink consistently as the tip goes
  lower:
  - Spearman ρ −0.04 (Run4 sweep), +0.12 (Run4 strikes), +0.02 (Run5 sweep), −0.21 (Run5 strikes);
  - Run4 strike-phase supports at y 0.40–0.55 are 92–132 px.
  - Only in Run4's all-phase rows below y ≈ 0.525 does the median support fall to 15–35 px.
- **[INFERENCE] This check is biased.** A strongly foreshortened stick loses its axis and leaves the
  observed set, to become a no-axis or bridged frame.

**Tip height versus hand height (Run1, VALID frames)** [OFFLINE]:
- **Left:** tip y and wrist y correlate at r = 0.74 (slope 0.89). The tip-minus-wrist offset varies over
  only 0.09.
- **Right:** r = 0.32. The stick tilts more in the image plane (|angle| p90 61°).
- **In both hands the tip's vertical range (0.17–0.27) is about the wrist's (0.21–0.24).**

**Verdict on the hypothesis [INFERENCE].**
- **Consistent with it:**
  - the stick disappears at particular stroke heights;
  - it leaves short, poorly elongated candidates;
  - slow frames are not better;
  - the estimator's tip height mostly follows the hand.
- **Equally consistent with:**
  - occlusion by the hand, forearm or body;
  - low contrast against the torso;
  - the stick leaving the 4-span search region at large angles.
- **Not explained by stick orientation at all:** hand-landmarker loss (BRIDGED), which is the largest
  failure in Run4 strikes.
- **Conclusion:** the evidence makes a depth / orientation component *plausible*. It does not establish it,
  and it does not show it to be the dominant cause.

## 4. Q3: the existing camera geometry [RECORDED]

| Item | Value | Source |
|---|---|---|
| Camera | HW-01 *integrated* laptop webcam, DSHOW 640 × 480, exposure −6 (Run4 / 5) and −5 (Runs 1–3) | `docs/camera-profile-hw01-integrated-webcam.md`; calibration files |
| Mount | laptop on a desk, lid at its working angle, no tripod (tripod is an open question) | camera profile §7 |
| Lens height / tilt | **0.75 m, 0°** (lid vertical); measured once, on 2026-09-21; not recorded for runs 1–5 | camera profile §7 |
| User distance | ≈ 1.0 m candidate | ADR-0017 (Proposed) |
| Horizontal field of view | **PENDING** (never measured; no spec) | camera profile §7 |
| ROI | `[40, 20, 560, 440]`, a candidate | config; ADR-0017 |
| Tracking versus distance | **never measured.** The distance stills were exposure-confounded; the factorial C-03-3 was never run | `docs/reports/phase-03-distance-lighting.md` |
| Apparent size (indicative clicks) | stick 134 px at 0.8 m, 120 px at 1.0 m, 64 px at 2.2 m | camera profile §7 |
| Exposure effect | at 1.0 m, frames with both hands: 103/171 at −5 versus 32/171 at −6 | Phase 03 report §2 |
| Held-up stick length (calibrations) | 0.29–0.34 ROI-h (≈ 130–150 px) for most hands; Run2 / Run3 left 0.17–0.19 and Run5 right 0.19 (all fell back to the default) | T1 |

**[INFERENCE]**
- The camera looks straight ahead from roughly the hands' height. The Run1 wrists appear below the image
  centre, which suggests hands at or below the 0.75 m lens; this depends on the unmeasured FOV and tilt.
- The drum stroke swings the stick in the player's forward–vertical plane, which contains the camera.
- So during a downstroke the stick turns *towards* the lens.
- With an integrated webcam, height and tilt are tied to the laptop's position and the screen's angle. The
  screen is also the live display.

## 5. Q4: possible developer-only setup changes, offline [HYPOTHESIS]

**The model.** `harness/camera_geometry_model.py`, orthographic foreshortening:
- the stick pitches 20–100° from vertical in the forward–vertical plane; impact is at ≈ 95°;
- hand height 0.55 / 0.75 / 0.95 m;
- "strongly foreshortened" = less than half the stick visible, a reference line only.
- **Visible factor:** the fraction of the stick's length that is visible from the camera; 1 = fully
  visible, 0 = seen end-on.

| Setup | Stick end-on at pitch | Visible factor at impact | Minimum over the stroke | Share of stroke < 0.5 | Pixel scale vs now |
|---|---|---:|---:|---:|---:|
| **Current:** frontal, lens 0.75 m, 1.0 m | 79–101° (**at impact**) | 0.09–0.28 | 0.00–0.02 | 36–64 % | 1.0 |
| Closer, 0.8 m | 76–104° | 0.09–0.33 | 0.00–0.07 | 32–68 % | ≈ 1.2 |
| Farther, 1.5 m | 82–98° | 0.05–0.22 | 0.00–0.01 | 41–59 % | ≈ 0.67 |
| Low, 0.30 m, tilted up | 104–123° | 0.16–0.47 | 0.07–0.39 | 9–32 % | 0.84–0.97 |
| High, 1.6 m, tilted down | 44–57° (**mid-stroke**) | 0.62–0.78 | ≈ 0 | 67–74 % | 0.69–0.84 |
| High, 2.0 m | 35–44° (mid-stroke) | 0.78–0.87 | ≈ 0 | 56–67 % | 0.57–0.69 |
| 20° to the side | never end-on | 0.35–0.43 | 0.34 | 27–57 % | ≈ 1.0 |
| 45° to the side | never end-on | 0.71–0.74 | 0.69–0.71 | 0 % | ≈ 1.0 |
| 90° (side view) | never end-on | ≈ 1.0 | ≈ 1.0 | 0 % | ≈ 1.0 |

**[HYPOTHESIS] What the model suggests:**
- **In front of the player, height and distance only move the end-on direction.**
  - Lens near hand height: end-on at impact.
  - Lens high: end-on mid-stroke.
  - Lens low and tilted up: end-on past impact, and only if the hands are well above it.
  - Distance changes the pixel scale; the closer camera (×1.2) has less ROI headroom (§2).
- **Only a sideways offset removes the end-on view.** At 45° the model keeps about 70 % of the stick visible
  everywhere in the stroke.
- **What an oblique view would change** (never recorded, all unknown):
  - one hand may occlude the other;
  - handedness and identity behave differently;
  - zone semantics change, and the mirrored live view no longer matches the player's left and right.

**What no offline analysis can settle:**
- whether the hand landmarker keeps both hands in any of these views;
- stick contrast against a different background;
- lighting and exposure at a new placement;
- whether the integrated webcam can be placed there at all, or whether an external camera would be needed;
- the real stroke pitch range.

## 6. Q5: the two directions

### A. Keep the current setup; redesign the four-zone layout around the narrow band

**Evidence for:**
- The band is stable in height across runs and exposures (collapse y 0.40–0.425).
- Zones whose arcs lie in the band were hit in the test strikes (Run4 snare 4/5).
- An in-sample FIXED four-zone arrangement exists (`cand-fixed4-v1`).

**Still unknown:**
- Whether a natural stroke can be detected in a band of this kind at all. The reliable band is mainly where
  a stick is held upright above the hand (tip height ≈ hand height − L). The downstroke itself leaves it.
- Robustness to standing position: the candidate fails for 48/49 shifts of ±0.03 in Run5, and the player
  moved ≈ 31 px between runs.
- The false-strike rate with zones beside the resting pose.

**To test:**
- held-out recorded sessions with a band layout displayed, from more than one standing position;
- detection and false strikes per zone, under a pre-declared protocol.

**Risks:**
- Zones at the threshold, close to the resting tips (§7 of the candidate report).
- Small targets.
- FIXED mode, or a fitter change.
- "Strikes" may become small hand movements with the stick up, not a drum stroke.
- The strike-depth loss and hand loss remain unaddressed.

### B. Improve the camera / setup first, then design the layout

**Evidence for:**
- The losses below the band are perception losses (missing stick axis, low axis confidence, missing hand),
  not decision logic. This matches the strike-reliability record: elongation 22 % and orientation 20 % of
  discarded strike entries.
- In the Run1 session, the stick disappears at particular stroke heights, as short blobs, and not because
  of blur.
- The current geometry puts the stick end-on near impact [HYPOTHESIS].
- Exposure alone changed hand detection about threefold at 1.0 m, so the capture setup does move these
  failure rates.

**Still unknown:**
- Whether *any* placement widens the reliable band. Nothing other than the current setup was ever
  tracked, and FOV and real distance are unmeasured.
- Whether hand-landmarker loss improves or worsens off-axis.
- Practicality with an integrated webcam: the screen is the display, and height and tilt are coupled to it.
- Whether the right change is a viewpoint at all, rather than the stick-tip rule (prior length) or stick
  segmentation. Those are perception changes and outside this assessment's scope.

**To test (developer only, no participants):**
- Record a short fixed script (a slow sweep plus strikes on cue) at two or three placements:
  - the current one;
  - a lateral offset of about 30–45°;
  - optionally a raised or lowered lens.
- Use the same lighting and exposure, and an observer like this one.
- Measure per placement:
  - the VALID band and its collapse y;
  - the loss hazard;
  - axis-found share and visible support by wrist height;
  - hand-detection rate.
- This is the never-run factorial C-03-3, extended by placement. It needs explicit owner approval because it
  collects new camera data.

**Risks:**
- A new placement or camera changes the camera profile, which invalidates every existing calibration
  (`CAMERA_PROFILE_CHANGED`). It also changes the exposure / FPS characterisation and the Arm B/C training
  conditions.
- The tripod / mount question (REQ-024).
- The oblique-view issues above.
- It is slower to reach any layout, and it may move the bottleneck to hand detection instead of removing it.

## 7. Limits of this assessment

- **Small evidence base:** one player, three exposure −5 calibration runs plus one 30 s play session (Run1),
  and two exposure −6 runs (Run4 / Run5). Runs 2–3 have no frames or rows.
- **Tip heights are estimates,** not observed stick ends. Run4 / Run5 rows have no wrist positions.
- **The wrist quartiles are a coarse stroke-height proxy.** In wrist-driven strokes the wrist moves little.
- **The geometric model uses assumed pitch ranges, hand heights and orthographic projection.** It ignores the
  hand landmarker, occlusion, contrast and lighting.
- **No ground truth** (no annotated tip, no 3D) exists for any frame.

## 8. Checks and confirmations

| Check | Result |
|---|---|
| Run1 observer replay against the existing probe rows | identical on 650/650 hand-frames (status, tip, axis found) |
| Production state before / after (`checks/production-diff.txt`) | the only difference is this new file (working-tree entries 32 → 33, one `??` line) |
| Production state left unchanged | HEAD `064cda5`; the same 19-file diff; prototype config `53248432…` and camera profile `3877c660…`; `mvp4` / `v1-7` / prototype config files; all five calibration hashes; the `data/calibration/` listing |
| Writes outside the evidence folder | none under `data/`; the only new file in `src/`, `configs/`, `scripts/`, `tests/` and `docs/` is this one (`checks/no-other-writes.txt`) |
| Determinism | a rerun of all five scripts gives identical data and byte-identical replay rows and tables (`checks/determinism.txt`) |
| `ruff check` / `ruff format --check` on the harness | clean (`checks/ruff-harness.txt`) |
| `git diff --check`; this file | clean; no trailing whitespace, LF only (`checks/diff-check.txt`, `checks/doc-whitespace.txt`) |

**Confirmations:**
- No production source or config change.
- No new calibration.
- No new camera data: the Run1 frames were recorded on 2026-09-28 and were only replayed.
- No live experiment and no participant data.
- **Phase 18 remains BLOCKED.**
- No commit, push, tag, reset, clean or checkout.
- The only repository-visible addition is this file.
